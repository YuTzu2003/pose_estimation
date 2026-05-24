import sys
import asyncio
import logging
import socket
import subprocess
import time
import shutil
import csv
import json
import requests
from pathlib import Path
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QTextEdit, QHBoxLayout,
                             QLineEdit, QGroupBox, QFormLayout)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread, QMetaObject, Q_ARG, pyqtSlot
from qasync import QEventLoop, asyncSlot
from bleak import BleakClient, BleakScanner

# Xsens SDK
try:
    import xsensdeviceapi as xda
except ImportError:
    xda = None
    print("Warning: xsensdeviceapi not found.")

# ========================================================
# 設定檔管理
# ========================================================
CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "local_wifi_ssid": "TP-Link_6444",
    "local_wifi_pass": "nfu123@@@",
    "gopro_ip": "gopro.local",
    "ap_ssid": "HERO11 Black",
    "ap_pass": "Z#T-NgS-z2y"
}

def load_config():
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# ========================================================
# 📡 GoPro UUIDs & Commands
# ========================================================
GOPRO_COMMAND_UUID = "b5f90072-aa8d-11e3-9046-0002a5d5c51b"
START_RECORDING    = bytearray([0x03, 0x01, 0x01, 0x01])
STOP_RECORDING     = bytearray([0x03, 0x01, 0x01, 0x00])
WAKE_WIFI          = bytearray([0x03, 0x17, 0x01, 0x01])

# Network Management (COHN)
NM_SERVICE_UUID    = "b5f90090-aa8d-11e3-9046-0002a5d5c51b"
NM_COMMAND_CHAR    = "b5f90091-aa8d-11e3-9046-0002a5d5c51b"

# GoPro 10+ 關鍵解鎖指令
SET_THIRD_PARTY_MODE = bytearray([0x03, 0x11, 0x01, 0x01])
SET_API_CONTROL_ON   = bytearray([0x03, 0x1a, 0x01, 0x01])

# AP 資訊讀取 UUIDs
WIFI_SSID_UUID = "b5f90002-aa8d-11e3-9046-0002a5d5c51b"
WIFI_PASS_UUID = "b5f90003-aa8d-11e3-9046-0002a5d5c51b"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Xsens Callbacks ----------

if xda:
    class WirelessMasterCallback(xda.XsCallback):
        def __init__(self):
            super().__init__()
            self.connected_mtws = set()
            self.lock = Lock()

        def onConnectivityChanged(self, dev, new_state):
            with self.lock:
                if new_state == xda.XCS_Wireless:
                    self.connected_mtws.add(dev)
                elif new_state in (xda.XCS_Disconnected, xda.XCS_Rejected):
                    self.connected_mtws.discard(dev)

        def get_wireless_mtws(self):
            with self.lock:
                return list(self.connected_mtws)

    class MtwCallback(xda.XsCallback):
        def __init__(self, mtw_index, device):
            super().__init__()
            self.index = mtw_index
            self.device = device
            self.packets = []
            self.lock = Lock()

        def onLiveDataAvailable(self, dev, packet):
            with self.lock:
                self.packets.append(xda.XsDataPacket(packet))

        def pop_oldest(self):
            with self.lock:
                return self.packets.pop(0) if self.packets else None

        def clear_buffer(self):
            with self.lock:
                self.packets.clear()
else:
    class WirelessMasterCallback: pass
    class MtwCallback: pass

# ---------- Xsens Manager (Threaded) ----------

class XsensManager(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    connection_finished = pyqtSignal(bool)
    discovery_finished = pyqtSignal(int)
    
    def __init__(self):
        super().__init__()
        self.control = None
        self.master = None
        self.master_cb = None
        self.mtw_callbacks = []
        self.is_logging = False
        self.should_stop = False
        self._is_connected = False
        self.update_rate = 120 # 依照診斷工具改為 120Hz
        self.radio_channel = 18
        self.mode = "connect"

    def run(self):
        if not xda:
            self.log_signal.emit("❌ Xsens SDK 未安裝。")
            return
        if self.mode == "discover":
            self._run_discovery()
        else:
            self._run_connect()

    def _run_discovery(self):
        try:
            self.log_signal.emit("🔍 開始掃描頻道 (11-25)，請確保感測器已開機...")
            self.control = xda.XsControl_construct()
            master_port = xda.XsScanner_scanPort("COM3", xda.XBR_Invalid)
            if master_port.empty():
                ports = xda.XsScanner_scanPorts()
                for p in ports:
                    if p.deviceId().isWirelessMaster() or p.deviceId().isAwindaXStation():
                        master_port = p
                        break
            if master_port.empty():
                self.log_signal.emit("❌ 找不到接收器。")
                self.discovery_finished.emit(-1)
                return
            self.control.openPort(master_port.portName(), master_port.baudrate())
            master = self.control.device(master_port.deviceId())
            master.gotoConfig()
            cb = WirelessMasterCallback()
            master.addCallbackHandler(cb)
            found_channel = -1
            for channel in range(11, 26):
                self.status_signal.emit(f"掃描中: CH {channel}")
                master.disableRadio()
                master.enableRadio(channel)
                for _ in range(15):
                    time.sleep(0.1)
                    if len(cb.get_wireless_mtws()) > 0:
                        found_channel = channel
                        break
                if found_channel != -1: break
            self.control.close()
            if found_channel != -1:
                self.log_signal.emit(f"✅ 在頻道 {found_channel} 找到感測器！")
                self.radio_channel = found_channel
                self.discovery_finished.emit(found_channel)
            else:
                self.log_signal.emit("❌ 掃描結束，未找到感測器。")
                self.discovery_finished.emit(-1)
        except Exception as e:
            self.log_signal.emit(f"❌ 掃描出錯: {e}")
            self.discovery_finished.emit(-1)

    def _run_connect(self):
        try:
            self.log_signal.emit(f"🚀 正在連線頻道 {self.radio_channel}...")
            self.control = xda.XsControl_construct()
            master_port = xda.XsScanner_scanPort("COM3", xda.XBR_Invalid)
            is_master = not master_port.empty() and (master_port.deviceId().isWirelessMaster() or master_port.deviceId().isAwindaXStation())
            if not is_master:
                ports = xda.XsScanner_scanPorts()
                for p in ports:
                    if p.deviceId().isWirelessMaster() or p.deviceId().isAwindaXStation():
                        master_port = p
                        is_master = True
                        break
            if not is_master:
                self.log_signal.emit("❌ 找不到接收器。")
                self.connection_finished.emit(False)
                return
            if not self.control.openPort(master_port.portName(), master_port.baudrate()):
                self.log_signal.emit("❌ 無法開啟連接埠。")
                self.connection_finished.emit(False)
                return
            self.master = self.control.device(master_port.deviceId())
            self.master.gotoConfig()
            self.master_cb = WirelessMasterCallback()
            self.master.addCallbackHandler(self.master_cb)
            supported = self.master.supportedUpdateRates()
            rate = self.update_rate if self.update_rate in [int(r) for r in supported] else int(supported[-1])
            self.master.setUpdateRate(rate)
            if self.master.isRadioEnabled():
                self.master.disableRadio()
            self.master.enableRadio(self.radio_channel)
            timeout = 0
            while len(self.master_cb.get_wireless_mtws()) == 0 and timeout < 100:
                time.sleep(0.1)
                timeout += 1
                if timeout % 10 == 0:
                    self.status_signal.emit(f"等待感測器連線... ({timeout/10:.1f}s)")
            if len(self.master_cb.get_wireless_mtws()) == 0:
                self.log_signal.emit("❌ 感測器連線逾時。")
                self.connection_finished.emit(False)
                return
            mtws = self.master_cb.get_wireless_mtws()
            self.mtw_callbacks = []
            for i, mtw in enumerate(mtws):
                cb = MtwCallback(i, mtw)
                mtw.addCallbackHandler(cb)
                self.mtw_callbacks.append(cb)
            self.master.gotoMeasurement()
            self._is_connected = True
            self.connection_finished.emit(True)
            self.status_signal.emit(f"Xsens: CH{self.radio_channel} 已連線")
        except Exception as e:
            self.log_signal.emit(f"❌ Xsens 錯誤: {str(e)}")
            self.connection_finished.emit(False)

    def reset_orientation(self):
        if not self._is_connected: return False
        success = True
        for cb in self.mtw_callbacks:
            if not cb.device.resetOrientation(xda.XRM_Alignment):
                success = False
        return success

    def start_logging(self):
        if not self._is_connected:
            self.log_signal.emit("⚠️ Xsens 未連線，無法記錄。")
            return
        
        # 如果還在忙，等待一下
        if self.is_logging:
            self.should_stop = True
            time.sleep(0.5)

        self.is_logging = True
        self.should_stop = False
        import threading
        self.logging_thread = threading.Thread(target=self._logging_loop, daemon=True)
        self.logging_thread.start()

    def _logging_loop(self):
        writers = {}
        files = {}
        start_counters = {}
        packet_counts = {}
        try:
            output_dir = Path.cwd() / "xsens_output"
            output_dir.mkdir(exist_ok=True)
            for cb in self.mtw_callbacks:
                fname = f"mtw_{cb.device.deviceId().toXsString()}_{int(time.time())}.csv"
                full_path = output_dir / fname
                f = open(full_path, "w", newline="")
                w = csv.writer(f)
                w.writerow(["packet_counter", "timestamp_s", "q_w", "q_x", "q_y", "q_z",
                            "acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z",
                            "mag_x", "mag_y", "mag_z"])
                writers[cb.index] = w
                files[cb.index] = f
                packet_counts[cb.index] = 0
                cb.clear_buffer()
                self.log_signal.emit(f"📝 正在建立 CSV: {fname}")
            
            self.log_signal.emit(f"🔴 [Xsens] 同步記錄中 (共 {len(self.mtw_callbacks)} 個感測器)...")
            
            last_progress_update = time.time()
            while not self.should_stop:
                has_data = False
                for cb in self.mtw_callbacks:
                    packet = cb.pop_oldest()
                    if packet is None: continue
                    has_data = True
                    try:
                        current_counter = packet.packetCounter()
                        if cb.index not in start_counters:
                            start_counters[cb.index] = current_counter
                        timestamp_s = (current_counter - start_counters[cb.index]) / float(self.update_rate)
                        
                        q   = packet.orientationQuaternion()
                        acc = packet.calibratedAcceleration() 
                        gyr = packet.calibratedGyroscopeData()
                        mag = packet.calibratedMagneticField()

                        writers[cb.index].writerow([
                            current_counter, f"{timestamp_s:.3f}",
                            q[0], q[1], q[2], q[3],
                            acc[0], acc[1], acc[2],
                            gyr[0], gyr[1], gyr[2],
                            mag[0], mag[1], mag[2],
                        ])
                        packet_counts[cb.index] += 1
                    except: continue
                
                # 每 5 秒回報一次進度，避免洗版
                if time.time() - last_progress_update > 5:
                    status_msg = "📊 記錄進度: " + ", ".join([f"S{idx}: {count} 筆" for idx, count in packet_counts.items()])
                    self.log_signal.emit(status_msg)
                    last_progress_update = time.time()

                if not has_data:
                    time.sleep(0.001)
        except Exception as e:
            self.log_signal.emit(f"❌ Xsens 記錄錯誤: {e}")
        finally:
            for f in files.values(): 
                try: f.close()
                except: pass
            self.is_logging = False
            self.log_signal.emit(f"✅ Xsens 記錄已停止。檔案儲存於: {output_dir}")
            for idx, count in packet_counts.items():
                self.log_signal.emit(f"   └─ 感測器 {idx}: 共存入 {count} 筆數據")

    def stop_logging(self):
        self.should_stop = True

    def cleanup(self):
        self.stop_logging()
        if self.master:
            self.master.gotoConfig()
            self.master.disableRadio()
        if self.control:
            self.control.close()

# ---------- Main App ----------

class GoProXsensApp(QWidget):
    append_log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.gopro_client = None
        self.gopro_ip = "10.5.5.9"
        self.is_station_mode = False
        self.xsens = XsensManager()
        self.init_ui()
        self.apply_styles()
        
        # Signals
        self.append_log_signal.connect(self._safe_append_log)
        self.xsens.log_signal.connect(self.log)
        self.xsens.status_signal.connect(self.update_status_text)
        self.xsens.connection_finished.connect(self.on_xsens_connected)
        self.xsens.discovery_finished.connect(self.on_xsens_discovered)

    def apply_styles(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #0f111a;
                color: #a6accd;
                font-family: "Segoe UI", "Microsoft JhengHei", sans-serif;
                font-size: 16px; /* Base font size increased */
            }
            /* 頂部標題 */
            QLabel#header_title {
                font-size: 32px; /* Increased */
                font-weight: 800;
                color: #ffffff;
                background: transparent;
                margin-top: 10px;
            }
            QLabel#header_subtitle {
                font-size: 16px; /* Increased */
                color: #676e95;
                background: transparent;
                margin-bottom: 15px;
            }
            /* 狀態卡片 */
            QLabel#status_label {
                font-size: 20px; /* Increased */
                font-weight: bold;
                padding: 15px 20px;
                background-color: #1a1c25;
                border: 1px solid #2d3143;
                border-radius: 12px;
                color: #82aaff;
                margin-bottom: 10px;
            }
            /* 卡片容器 */
            QGroupBox {
                background-color: #1a1c25;
                border: 1px solid #2d3143;
                border-radius: 15px;
                margin-top: 30px;
                padding: 20px 15px 15px 15px;
                font-weight: bold;
                font-size: 18px; /* Increased */
                color: #89ddff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 20px;
                padding: 0 10px;
                background-color: #0f111a;
            }
            /* 通用按鈕 */
            QPushButton {
                background-color: #292d3e;
                border: 1px solid #32374d;
                border-radius: 10px;
                padding: 12px 20px; /* Increased padding */
                color: #eeffff;
                font-weight: 600;
                font-size: 16px; /* Explicit font size for buttons */
                min-height: 25px;
            }
            QPushButton:hover {
                background-color: #3b4252;
                border-color: #444a66;
            }
            QPushButton:pressed {
                background-color: #242837;
            }
            QPushButton:disabled {
                background-color: #161821;
                color: #464b5d;
                border: 1px solid #212431;
            }
            /* 功能性按鈕 */
            QPushButton#btn_gopro_connect {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d4, stop:1 #00bcf2);
                border: none;
                color: white;
                font-size: 18px; /* Increased */
            }
            QPushButton#btn_start {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #11998e, stop:1 #38ef7d);
                border: none;
                color: #ffffff;
                font-size: 20px; /* Increased */
            }
            QPushButton#btn_stop {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #cb2d3e, stop:1 #ef473a);
                border: none;
                color: #ffffff;
                font-size: 20px; /* Increased */
            }
            QPushButton#btn_download_wifi, QPushButton#btn_download_usb {
                background-color: transparent;
                border: 2px solid #82aaff;
                color: #82aaff;
                font-size: 18px; /* Increased */
            }
            QPushButton#btn_download_wifi:hover, QPushButton#btn_download_usb:hover {
                background-color: #82aaff;
                color: #0f111a;
            }
            /* 輸入框 */
            QLineEdit {
                background-color: #090b10;
                border: 1px solid #2d3143;
                border-radius: 8px;
                padding: 10px; /* Increased padding */
                color: #ffffff;
                font-size: 16px; /* Increased */
                selection-background-color: #82aaff;
            }
            QLineEdit:focus {
                border: 1px solid #82aaff;
            }
            /* 日誌視窗 */
            QTextEdit {
                background-color: #090b10;
                border: 1px solid #1a1c25;
                border-radius: 12px;
                color: #c3e88d;
                font-family: "Fira Code", "Consolas", monospace;
                font-size: 18px; /* Further increased from 14px to 18px */
                padding: 15px;
                line-height: 1.5;
            }
            QLabel {
                background: transparent;
            }
            QLabel#log_header_label {
                font-size: 16px;
                font-weight: bold;
                color: #676e95;
                margin-bottom: 5px;
            }
        """)

    def init_ui(self):
        self.setWindowTitle("GoPro & Xsens Control Hub")
        self.setMinimumSize(950, 950) # Increased width slightly for larger text
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        # --- Header Section ---
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        
        title = QLabel("GoPro & Xsens")
        title.setObjectName("header_title")
        subtitle = QLabel("Synchronized Data Collection & Management System")
        subtitle.setObjectName("header_subtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        main_layout.addWidget(header_widget)

        # --- Status Banner ---
        self.status_label = QLabel("● 系統狀態: 準備就緒")
        self.status_label.setObjectName("status_label")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)

        # --- Main Content Area ---
        content_layout = QHBoxLayout()
        content_layout.setSpacing(25)
        
        left_panel = QVBoxLayout()
        right_panel = QVBoxLayout()

        # 1. Xsens Card
        xsens_gb = QGroupBox("📡 Xsens 感測器網路")
        xl = QVBoxLayout()
        xl.setSpacing(12)
        xbl = QHBoxLayout()
        self.btn_xsens_discover = QPushButton("🔍 頻道掃描")
        self.btn_xsens_discover.clicked.connect(self.discover_xsens)
        self.btn_xsens_connect = QPushButton("⚡ 快速連線")
        self.btn_xsens_connect.clicked.connect(self.connect_xsens)
        xbl.addWidget(self.btn_xsens_discover)
        xbl.addWidget(self.btn_xsens_connect)
        xl.addLayout(xbl)
        self.btn_reset_xsens = QPushButton("🔄 方向歸零 (Alignment)")
        self.btn_reset_xsens.setEnabled(False)
        self.btn_reset_xsens.clicked.connect(self.reset_xsens)
        xl.addWidget(self.btn_reset_xsens)
        xsens_gb.setLayout(xl)
        left_panel.addWidget(xsens_gb)

        # 2. GoPro Card
        gopro_gb = QGroupBox("📷 GoPro 攝影機控制")
        gl = QVBoxLayout()
        gl.setSpacing(15)
        
        self.btn_gopro_connect = QPushButton("🔵 1. 建立藍牙連線")
        self.btn_gopro_connect.setObjectName("btn_gopro_connect")
        self.btn_gopro_connect.setFixedHeight(45)
        self.btn_gopro_connect.clicked.connect(self.connect_gopro)
        gl.addWidget(self.btn_gopro_connect)

        self.btn_fetch_ap = QPushButton("🔄 2. 讀取相機熱點資訊")
        self.btn_fetch_ap.setEnabled(False)
        self.btn_fetch_ap.clicked.connect(self.fetch_gopro_ap_info)
        gl.addWidget(self.btn_fetch_ap)

        ap_box = QWidget()
        af = QFormLayout(ap_box)
        af.setLabelAlignment(Qt.AlignRight)
        self.input_ap_ssid = QLineEdit(self.config["ap_ssid"])
        self.input_ap_pass = QLineEdit(self.config["ap_pass"])
        af.addRow("熱點 SSID:", self.input_ap_ssid)
        af.addRow("熱點密碼:", self.input_ap_pass)
        gl.addWidget(ap_box)

        gopro_gb.setLayout(gl)
        left_panel.addWidget(gopro_gb)

        # 3. Control Card
        ctrl_gb = QGroupBox("🎮 同步錄製任務")
        cl = QVBoxLayout()
        cl.setSpacing(15)
        cbl = QHBoxLayout()
        cbl.setSpacing(15)
        self.btn_start = QPushButton("🔴 開始同步錄製")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setEnabled(False)
        self.btn_start.setMinimumHeight(70)
        self.btn_start.clicked.connect(self.start_all)
        self.btn_stop = QPushButton("⬛ 停止錄製")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumHeight(70)
        self.btn_stop.clicked.connect(self.stop_all)
        cbl.addWidget(self.btn_start, 2)
        cbl.addWidget(self.btn_stop, 1)
        cl.addLayout(cbl)
        ctrl_gb.setLayout(cl)
        right_panel.addWidget(ctrl_gb)
        
        # 4. Data Card
        dl_gb = QGroupBox("📂 影片下載管理")
        dl = QVBoxLayout()
        dl.setSpacing(12)
        
        self.btn_download_wifi = QPushButton("📡 Wi-Fi 下載 (需先讀取熱點資訊)")
        self.btn_download_wifi.setObjectName("btn_download_wifi")
        self.btn_download_wifi.setEnabled(False)
        self.btn_download_wifi.setFixedHeight(50)
        self.btn_download_wifi.clicked.connect(self.download_via_wifi)
        dl.addWidget(self.btn_download_wifi)

        self.btn_download_usb = QPushButton("🔌 USB 下載")
        self.btn_download_usb.setObjectName("btn_download_usb")
        self.btn_download_usb.setEnabled(False)
        self.btn_download_usb.setFixedHeight(50)
        self.btn_download_usb.clicked.connect(self.download_via_usb)
        dl.addWidget(self.btn_download_usb)
        dl_gb.setLayout(dl)
        right_panel.addWidget(dl_gb)
        
        # Spacer to push things up
        right_panel.addStretch()

        content_layout.addLayout(left_panel, 1)
        content_layout.addLayout(right_panel, 1)
        main_layout.addLayout(content_layout)

        # --- Console Section ---
        console_widget = QWidget()
        console_layout = QVBoxLayout(console_widget)
        console_layout.setContentsMargins(0, 10, 0, 0)
        log_label = QLabel("系統執行日誌 (System Console)")
        log_label.setObjectName("log_header_label")
        console_layout.addWidget(log_label)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        console_layout.addWidget(self.log_view)
        main_layout.addWidget(console_widget, 1)

        self.setLayout(main_layout)

    @pyqtSlot(str)
    def log(self, message):
        self.append_log_signal.emit(message)
        logger.info(message)

    def _safe_append_log(self, message):
        self.log_view.append(message)
        self.log_view.moveCursor(self.log_view.textCursor().End)

    def update_status_text(self, text):
        self.status_label.setText(f"● {text}")

    def get_gopro_gateway_ip(self):
        try:
            # 優先嘗試執行 ipconfig 抓取閘道
            result = subprocess.run('ipconfig', shell=True, capture_output=True, text=True, encoding='cp950')
            lines = result.stdout.split('\n')
            is_wifi_section = False
            for line in lines:
                if "Wireless LAN adapter Wi-Fi" in line or "無線區域網路介面卡 Wi-Fi" in line:
                    is_wifi_section = True
                if is_wifi_section and ("Default Gateway" in line or "預設閘道" in line):
                    parts = line.split(':')
                    if len(parts) > 1:
                        ip = parts[1].strip()
                        if ip and not ip.startswith("fe80") and "." in ip:
                            return ip
        except: pass
        return "10.5.5.9"

    def discover_xsens(self):
        self.btn_xsens_discover.setEnabled(False)
        self.xsens.mode = "discover"
        self.xsens.start()

    def connect_xsens(self):
        self.btn_xsens_discover.setEnabled(False)
        self.xsens.mode = "connect"
        self.xsens.start()

    def on_xsens_discovered(self, channel):
        self.btn_xsens_discover.setEnabled(True)
        if channel != -1: self.log(f"✅ 發現 Xsens 於頻道 {channel}")

    def on_xsens_connected(self, success):
        self.btn_xsens_discover.setEnabled(True)
        if success:
            self.btn_reset_xsens.setEnabled(True)
            self.check_ready_state()

    def reset_xsens(self):
        if self.xsens.reset_orientation(): self.log("✅ Xsens 歸零成功")

    @asyncSlot()
    async def connect_gopro(self):
        self.log("正在搜尋 GoPro (嘗試 10 秒，請確保相機未處於純傳輸模式)...")
        self.btn_gopro_connect.setEnabled(False)
        try:
            for attempt in range(2):
                devices = await BleakScanner.discover(timeout=5.0)
                gopro = next((d for d in devices if d.name and "GoPro" in d.name), None)
                if gopro: break
            
            if not gopro:
                self.log("❌ 未找到 GoPro。提示：若插著 USB 且螢幕顯示「USB 已連接」，請先拔掉線再連線。")
                self.btn_gopro_connect.setEnabled(True)
                return
            
            self.log(f"找到 {gopro.name}，連線中...")
            self.gopro_client = BleakClient(gopro.address)
            await self.gopro_client.connect()
            try: await self.gopro_client.pair()
            except: pass
            await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
            await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
            self.log("🎉 GoPro 藍牙連線成功")
            self.btn_fetch_ap.setEnabled(True)
            self.check_ready_state()
        except Exception as e:
            self.log(f"❌ GoPro 連線失敗: {e}")
            self.btn_gopro_connect.setEnabled(True)

    @asyncSlot()
    async def fetch_gopro_ap_info(self):
        if not self.gopro_client or not self.gopro_client.is_connected: return
        self.log("📡 正在從相機讀取熱點資訊...")
        try:
            ssid_bytes = await self.gopro_client.read_gatt_char(WIFI_SSID_UUID)
            pass_bytes = await self.gopro_client.read_gatt_char(WIFI_PASS_UUID)
            ssid = ssid_bytes.decode('utf-8').strip('\x00')
            password = pass_bytes.decode('utf-8').strip('\x00')
            self.input_ap_ssid.setText(ssid)
            self.input_ap_pass.setText(password)
            self.log(f"✅ 讀取成功！SSID: {ssid}")
        except Exception as e:
            self.log(f"⚠️ 讀取熱點資訊失敗: {e}")

    def check_ready_state(self):
        gopro_ready = self.gopro_client and self.gopro_client.is_connected
        xsens_ready = self.xsens._is_connected
        if gopro_ready and xsens_ready:
            self.btn_start.setEnabled(True)
            self.status_label.setText("狀態: 裝置皆已就緒")
            self.status_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")

    @asyncSlot()
    async def provision_gopro_wifi(self):
        # Method preserved for structural integrity but no longer called from UI
        pass

    @asyncSlot()
    async def start_all(self):
        self.xsens.start_logging()
        try:
            await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, START_RECORDING, response=True)
            self.log("🔴 同步錄製中...")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.status_label.setText("狀態: 正在錄製")
            self.status_label.setStyleSheet("color: #f44747; font-weight: bold;")
        except Exception as e:
            self.log(f"❌ 啟動失敗: {e}")
            self.xsens.stop_logging()

    @asyncSlot()
    async def stop_all(self):
        try:
            await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, STOP_RECORDING, response=True)
            await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, WAKE_WIFI, response=True)
            self.log("⬛ 錄影已停止")
        except: pass
        self.xsens.stop_logging()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_download_wifi.setEnabled(True)
        self.btn_download_usb.setEnabled(True)
        self.status_label.setText("狀態: 錄製完成")
        self.status_label.setStyleSheet("color: #dcdcdc; font-weight: bold;")

    @asyncSlot()
    async def download_via_wifi(self):
        self.btn_download_wifi.setEnabled(False)
        self.log("🚀 啟動 Wi-Fi 下載流程...")
        
        ssid, password = self.input_ap_ssid.text(), self.input_ap_pass.text()
        if not ssid:
            self.log("❌ 錯誤：未設定 AP SSID，請先點擊「讀取相機熱點資訊」。")
            self.btn_download_wifi.setEnabled(True)
            return

        # 1. 偵測目前環境
        gopro_ip = self.get_gopro_gateway_ip()
        
        # 先檢查是否已經連著了
        if self._ping_gopro(gopro_ip):
            self.log(f"✅ 偵測到已連線至 GoPro ({gopro_ip})，開始下載...")
            await asyncio.get_event_loop().run_in_executor(None, self._http_download_worker, gopro_ip)
            self.btn_download_wifi.setEnabled(True)
            return

        # 若未連線，執行切換指令
        if self.connect_windows_wifi(ssid, password):
            self.log(f"⏳ 已送出連線請求 ({ssid})，等待 Windows 切換 (12秒)...")
            await asyncio.sleep(12)
            
            # 切換完後重新抓一次閘道 IP
            gopro_ip = self.get_gopro_gateway_ip()
            is_reachable = False
            for i in range(6):
                if self._ping_gopro(gopro_ip):
                    self.log(f"✅ 已成功連上 GoPro 熱點 ({gopro_ip})。")
                    is_reachable = True
                    break
                self.log(f"⏳ 等待 {gopro_ip} 回應 ({i+1}/6)...")
                await asyncio.sleep(2)
            
            if is_reachable:
                await asyncio.get_event_loop().run_in_executor(None, self._http_download_worker, gopro_ip)
            else:
                self.log(f"❌ 逾時：無法與 {gopro_ip} 通訊。請手動確認 Wi-Fi 連線。")
        else:
            self.log("❌ 無法執行 Wi-Fi 切換指令，請檢查系統權限或 SSID 設定。")
        
        self.btn_download_wifi.setEnabled(True)

    @asyncSlot()
    async def download_via_usb(self):
        self.btn_download_usb.setEnabled(False)
        self.log("🔌 啟動 USB 下載流程...")
        success, msg = self._usb_download_logic()
        if success:
            self.log(msg)
        else:
            self.log(f"⚠️ USB 下載未成功: {msg}")
            self.log("提示：請確保 GoPro 處於 MTP/連線模式，且已插上 USB 線。")
        self.btn_download_usb.setEnabled(True)

    def _ping_gopro(self, ip):
        try:
            with socket.create_connection((ip, 8080), timeout=0.5): return True
        except: return False

    def _scan_local_network_for_gopro(self):
        try:
            local_ips = socket.gethostbyname_ex(socket.gethostname())[2]
            for lip in local_ips:
                if lip.startswith("127."): continue
                prefix = ".".join(lip.split(".")[:-1])
                ips = [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != lip]
                with ThreadPoolExecutor(max_workers=100) as executor:
                    futures = {executor.submit(self._ping_gopro, ip): ip for ip in ips}
                    for f in as_completed(futures):
                        if f.result(): return futures[f]
        except: pass
        return None

    def _http_download_worker(self, gopro_ip):
        session = requests.Session()
        session.trust_env = False
        def tlog(m): 
            self.append_log_signal.emit(m)
            logger.info(f"[Download] {m}")

        try:
            tlog("⏳ 正在對接相機服務...")
            for _ in range(3): session.get(f"http://{gopro_ip}/gopro/camera/keep_alive", timeout=1)
            res = session.get(f"http://{gopro_ip}:8080/gopro/media/list", timeout=5)
            if res.status_code == 200:
                media_data = res.json()
                if 'media' not in media_data or not media_data['media']:
                    tlog("ℹ️ 相機內目前沒有影片檔案")
                    return False
                
                # 攤平所有資料夾中的檔案，以便進行全域排序
                all_files = []
                for folder_item in media_data['media']:
                    dir_name = folder_item['d']
                    for f in folder_item.get('fs', []):
                        if f['n'].lower().endswith('.mp4'):
                            all_files.append({
                                'dir': dir_name,
                                'n': f['n'],
                                'mod': int(f['mod'])  # GoPro 的原始生成時間戳
                            })
                
                if not all_files:
                    tlog("ℹ️ 找不到任何 MP4 影片")
                    return False

                # 依照 mod (建立時間) 由新到舊排序
                all_files.sort(key=lambda x: x['mod'], reverse=True)
                latest = all_files[0]
                
                folder = latest['dir']
                file_name = latest['n']
                tlog(f"🎬 發現全相機最新影片 (依日期): {file_name}")
                
                url = f"http://{gopro_ip}:8080/videos/DCIM/{folder}/{file_name}"
                save_path = Path.cwd() / file_name
                with session.get(url, stream=True, timeout=10) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    last_update = time.time()
                    with open(save_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if time.time() - last_update > 2:
                                tlog(f"⬇️ 已下載: {downloaded/1e6:.1f}MB / {total/1e6:.1f}MB")
                                last_update = time.time()
                out = Path.cwd() / "video_output"
                out.mkdir(exist_ok=True)
                shutil.move(str(save_path), str(out / file_name))
                tlog(f"🎉 下載完成: {file_name}")
                return True
        except Exception as e:
            tlog(f"❌ HTTP 下載出錯: {e}")
        return False

    def _usb_download_logic(self):
        match_token = "HERO|GoPro"
        ps_template = r"""
        try {
            $shell = New-Object -ComObject Shell.Application
            $thisPC = $shell.Namespace(17)
            $gopro = $thisPC.Items() | Where-Object { $_.Name -match "GOPRO_MATCH_TOKEN" }
            if (!$gopro) { throw "找不到 GoPro 裝置，請確認 USB 已連線。" }
            
            $storage = $gopro.GetFolder.Items() | Where-Object { $_.Name -match "GoPro MTP" -or $_.Name -match "Internal Storage" -or $_.Name -match "存儲" -or $_.Name -match "SD Card" }
            if (!$storage) { throw "找不到存儲空間 (SD卡)。" }
            
            $dcim = $storage.GetFolder.Items() | Where-Object { $_.Name -eq "DCIM" }
            if (!$dcim) { throw "找不到 DCIM 資料夾。" }
            
            $goproFolders = $dcim.GetFolder.Items() | Where-Object { $_.Name -match "GOPRO" }
            
            $allFiles = @()
            foreach ($folderItem in $goproFolders) {
                $folder = $folderItem.GetFolder
                
                # 尋找「建立日期」的屬性索引
                $dateCreatedIndex = -1
                for ($i=0; $i -lt 100; $i++) {
                    $colName = $folder.GetDetailsOf($null, $i)
                    if ($colName -eq "建立日期" -or $colName -eq "Date created") {
                        $dateCreatedIndex = $i
                        break
                    }
                }
                if ($dateCreatedIndex -eq -1) { $dateCreatedIndex = 4 }

                $files = $folderItem.GetFolder.Items() | Where-Object { $_.Name -like "*.MP4" }
                foreach ($f in $files) {
                    $createDateStr = $folder.GetDetailsOf($f, $dateCreatedIndex)
                    if ($createDateStr) {
                        # 去除隱藏字元並整理字串
                        $cleanDateStr = $createDateStr.Replace("?", "").Trim()
                        $sortKey = $cleanDateStr
                        
                        # 💡 核心修復：手動解析日期字串，支援 "2023/8/3 上午 10:17"
                        if ($cleanDateStr -match "(\d+)[\-/](\d+)[\-/](\d+)\s*(上午|下午|AM|PM)\s*(\d+):(\d+)") {
                            $year  = [int]$matches[1]
                            $month = [int]$matches[2]
                            $day   = [int]$matches[3]
                            $ampm  = $matches[4]
                            $hour  = [int]$matches[5]
                            $min   = [int]$matches[6]
                            
                            if ($ampm -eq "下午" -or $ampm -eq "PM") {
                                if ($hour -lt 12) { $hour += 12 }
                            } elseif ($ampm -eq "上午" -or $ampm -eq "AM") {
                                if ($hour -eq 12) { $hour = 0 }
                            }
                            # 生成可排序字串 (YYYYMMDDHHMM)
                            $sortKey = "{0:D4}{1:D2}{2:D2}{3:D2}{4:D2}" -f $year, $month, $day, $hour, $min
                        }
                        
                        $allFiles += [PSCustomObject]@{
                            Item    = $f
                            SortKey = $sortKey
                            RawDate = $cleanDateStr
                            Name    = $f.Name
                        }
                    }
                }
            }
            
            if ($allFiles.Count -eq 0) { throw "在 GoPro 中找不到任何 MP4 影片。" }
            
            # 依據 SortKey 降冪排序，取得最新檔案
            $latest = $allFiles | Sort-Object SortKey -Descending | Select-Object -First 1
            $latestFile = $latest.Item
            
            $destPath = Join-Path (Get-Location) "video_output"
            if (!(Test-Path $destPath)) { New-Item -ItemType Directory -Path $destPath }
            
            $destFolder = $shell.Namespace($destPath)
            $destFolder.CopyHere($latestFile, 16)
            
            # 等待檔案出現在目標路徑
            $targetFile = Join-Path $destPath $latest.Name
            $timeout = 0
            while (!(Test-Path $targetFile) -and $timeout -lt 60) { 
                Start-Sleep -Seconds 1 
                $timeout++
            }
            
            if (Test-Path $targetFile) {
                Write-Host "SUCCESS:$($latest.Name)"
            } else {
                throw "複製逾時，檔案未出現在目標資料夾。"
            }
        } catch {
            Write-Host "ERROR:$($_.Exception.Message)"
        }
        """
        ps = ps_template.replace("GOPRO_MATCH_TOKEN", match_token)
        try:
            r = subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True, encoding='cp950')
            output = r.stdout.strip()
            if "SUCCESS:" in output: 
                fname = output.split('SUCCESS:')[1]
                full_path = Path.cwd() / "video_output" / fname
                return True, f"✅ USB 下載成功！檔案儲存於: {full_path}"
            else:
                return False, f"USB 失敗: {output}"
        except Exception as e:
            return False, f"USB 執行出錯: {e}"

    def connect_windows_wifi(self, ssid, password):
        # 1. 先嘗試刪除舊的同名設定檔，避免衝突
        subprocess.run(f'netsh wlan delete profile name="{ssid}"', shell=True, capture_output=True)
        
        # 2. 建立新的設定檔 XML
        xml = f"""<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1"><name>{ssid}</name><SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig><connectionType>ESS</connectionType><connectionMode>manual</connectionMode><MSM><security><authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{password}</keyMaterial></sharedKey></security></MSM></WLANProfile>"""
        try:
            p = Path.cwd() / "gp_temp.xml"
            p.write_text(xml)
            
            # 3. 新增設定檔
            subprocess.run(f'netsh wlan add profile filename="{p}"', shell=True, capture_output=True)
            p.unlink()
            
            # 4. 斷開目前連線，確保 Windows 會切換
            subprocess.run('netsh wlan disconnect', shell=True, capture_output=True)
            time.sleep(1)
            
            # 5. 執行連線
            subprocess.run(f'netsh wlan connect name="{ssid}"', shell=True, capture_output=True)
            return True
        except Exception as e:
            self.log(f"⚠️ Wi-Fi 指令執行失敗: {e}")
            return False

    def closeEvent(self, event):
        new_config = {
            "ap_ssid": self.input_ap_ssid.text(),
            "ap_pass": self.input_ap_pass.text()
        }
        save_config(new_config)
        self.xsens.cleanup()
        if self.gopro_client: asyncio.create_task(self.gopro_client.disconnect())
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = GoProXsensApp()
    window.show()
    with loop: loop.run_forever()

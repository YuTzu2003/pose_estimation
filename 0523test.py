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
# ⚙️ 設定檔管理
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
        self.update_rate = 100
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
        if not self._is_connected or self.is_logging: return
        self.is_logging = True
        self.should_stop = False
        import threading
        self.logging_thread = threading.Thread(target=self._logging_loop, daemon=True)
        self.logging_thread.start()

    def _logging_loop(self):
        writers = {}
        files = {}
        start_counters = {}
        try:
            output_dir = Path.cwd() / "xsens_output"
            output_dir.mkdir(exist_ok=True)
            for cb in self.mtw_callbacks:
                fname = f"mtw_{cb.device.deviceId().toXsString()}_{int(time.time())}.csv"
                f = open(output_dir / fname, "w", newline="")
                w = csv.writer(f)
                w.writerow(["packet_counter", "timestamp_s", "q_w", "q_x", "q_y", "q_z",
                            "acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z",
                            "mag_x", "mag_y", "mag_z"])
                writers[cb.index] = w
                files[cb.index] = f
                cb.clear_buffer()
            self.log_signal.emit("🔴 [Xsens] 同步記錄中...")
            while not self.should_stop:
                for cb in self.mtw_callbacks:
                    packet = cb.pop_oldest()
                    if packet is None: continue
                    try:
                        current_counter = packet.packetCounter()
                        if cb.index not in start_counters:
                            start_counters[cb.index] = current_counter
                        timestamp_s = (current_counter - start_counters[cb.index]) / float(self.update_rate)
                        q = packet.orientationQuaternion()
                        acc = packet.calibratedAcceleration() 
                        gyr = packet.calibratedGyroscopeData()
                        mag = packet.calibratedMagneticField()
                        writers[cb.index].writerow([
                            current_counter, f"{timestamp_s:.3f}",
                            q[0], q[2], q[1], q[3],
                            acc[1], acc[0], acc[2],
                            gyr[1], gyr[0], gyr[2],
                            mag[1], mag[0], mag[2],
                        ])
                    except: continue
                time.sleep(0.001)
        except Exception as e:
            self.log_signal.emit(f"❌ Xsens 記錄錯誤: {e}")
        finally:
            for f in files.values(): f.close()
            self.is_logging = False
            self.log_signal.emit("Xsens 記錄停止。")

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
        
        # Signals
        self.append_log_signal.connect(self._safe_append_log)
        self.xsens.log_signal.connect(self.log)
        self.xsens.status_signal.connect(self.update_status_text)
        self.xsens.connection_finished.connect(self.on_xsens_connected)
        self.xsens.discovery_finished.connect(self.on_xsens_discovered)

    def init_ui(self):
        self.setWindowTitle("GoPro & Xsens 同步控制系統 (v2.3)")
        self.setMinimumSize(600, 850)
        layout = QVBoxLayout()

        self.status_label = QLabel("狀態: 準備就緒")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: blue;")
        layout.addWidget(self.status_label)

        # 1. Xsens
        xsens_gb = QGroupBox("1. Xsens 感測器控制")
        xl = QVBoxLayout()
        xbl = QHBoxLayout()
        self.btn_xsens_discover = QPushButton("🔍 掃描頻道")
        self.btn_xsens_discover.clicked.connect(self.discover_xsens)
        self.btn_xsens_connect = QPushButton("⚡ 快速連線")
        self.btn_xsens_connect.clicked.connect(self.connect_xsens)
        xbl.addWidget(self.btn_xsens_discover)
        xbl.addWidget(self.btn_xsens_connect)
        xl.addLayout(xbl)
        self.btn_reset_xsens = QPushButton("🔄 方向歸零 (Alignment Reset)")
        self.btn_reset_xsens.setEnabled(False)
        self.btn_reset_xsens.clicked.connect(self.reset_xsens)
        xl.addWidget(self.btn_reset_xsens)
        xsens_gb.setLayout(xl)
        layout.addWidget(xsens_gb)

        # 2. GoPro
        gopro_gb = QGroupBox("2. GoPro 控制")
        gl = QVBoxLayout()
        self.btn_gopro_connect = QPushButton("🔵 連線 GoPro (藍牙)")
        self.btn_gopro_connect.setFixedHeight(40)
        self.btn_gopro_connect.clicked.connect(self.connect_gopro)
        gl.addWidget(self.btn_gopro_connect)

        station_gb = QGroupBox("🏡 區網連線 (Station Mode)")
        sf = QFormLayout()
        self.input_ssid = QLineEdit(self.config["local_wifi_ssid"])
        self.input_pass = QLineEdit(self.config["local_wifi_pass"])
        self.input_pass.setEchoMode(QLineEdit.Password)
        self.input_gopro_ip = QLineEdit(self.config["gopro_ip"])
        sf.addRow("本機 Wi-Fi 名稱:", self.input_ssid)
        sf.addRow("本機 Wi-Fi 密碼:", self.input_pass)
        sf.addRow("GoPro 區網 IP:", self.input_gopro_ip)
        sl = QVBoxLayout()
        sl.addLayout(sf)
        self.btn_provision_wifi = QPushButton("📡 配置 Wi-Fi 至 GoPro")
        self.btn_provision_wifi.setEnabled(False)
        self.btn_provision_wifi.clicked.connect(self.provision_gopro_wifi)
        sl.addWidget(self.btn_provision_wifi)
        station_gb.setLayout(sl)
        gl.addWidget(station_gb)
        gopro_gb.setLayout(gl)
        layout.addWidget(gopro_gb)

        # 3. Sync
        ctrl_gb = QGroupBox("3. 同步錄製")
        cl = QVBoxLayout()
        cbl = QHBoxLayout()
        self.btn_start = QPushButton("🔴 開始錄影")
        self.btn_start.setEnabled(False)
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet("background-color: #d4edda; font-weight: bold;")
        self.btn_start.clicked.connect(self.start_all)
        self.btn_stop = QPushButton("⬛ 停止錄影")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet("background-color: #f8d7da; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_all)
        cbl.addWidget(self.btn_start)
        cbl.addWidget(self.btn_stop)
        cl.addLayout(cbl)
        ctrl_gb.setLayout(cl)
        layout.addWidget(ctrl_gb)
        
        # 4. Download
        dl_gb = QGroupBox("4. 影片下載設定")
        dl = QVBoxLayout()
        df = QFormLayout()
        self.input_ap_ssid = QLineEdit(self.config["ap_ssid"])
        self.input_ap_pass = QLineEdit(self.config["ap_pass"])
        df.addRow("GoPro 熱點 SSID:", self.input_ap_ssid)
        df.addRow("GoPro 熱點密碼:", self.input_ap_pass)
        dl.addLayout(df)
        
        self.btn_fetch_ap = QPushButton("🔄 從 GoPro 自動讀取熱點資訊")
        self.btn_fetch_ap.setEnabled(False)
        self.btn_fetch_ap.clicked.connect(self.fetch_gopro_ap_info)
        dl.addWidget(self.btn_fetch_ap)
        
        self.btn_download = QPushButton("💾 下載最新影片")
        self.btn_download.setEnabled(False)
        self.btn_download.setFixedHeight(40)
        self.btn_download.setStyleSheet("background-color: #cce5ff;")
        self.btn_download.clicked.connect(self.download_video)
        dl.addWidget(self.btn_download)
        dl_gb.setLayout(dl)
        layout.addWidget(dl_gb)

        # Log
        layout.addWidget(QLabel("執行日誌:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #f8f9fa; font-family: Consolas; font-size: 10pt;")
        layout.addWidget(self.log_view)

        self.setLayout(layout)

    @pyqtSlot(str)
    def log(self, message):
        self.append_log_signal.emit(message)
        logger.info(message)

    def _safe_append_log(self, message):
        self.log_view.append(message)
        self.log_view.moveCursor(self.log_view.textCursor().End)

    def update_status_text(self, text):
        self.status_label.setText(text)

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
        if gopro_ready: self.btn_provision_wifi.setEnabled(True)
        if gopro_ready and xsens_ready:
            self.btn_start.setEnabled(True)
            self.status_label.setText("狀態: 裝置皆已就緒")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")

    @asyncSlot()
    async def provision_gopro_wifi(self):
        ssid, pwd = self.input_ssid.text(), self.input_pass.text()
        self.log(f"傳送 Wi-Fi ({ssid}) 至 GoPro...")
        try:
            payload = bytearray([0x0a, len(ssid)]) + ssid.encode() + bytearray([0x12, len(pwd)]) + pwd.encode()
            command = bytearray([len(payload) + 1, 0x03]) + payload
            await self.gopro_client.write_gatt_char(NM_COMMAND_CHAR, command, response=True)
            self.log("✅ 已送達，請檢查相機畫面。")
            self.is_station_mode = True
        except Exception as e:
            self.log(f"❌ 配置失敗: {e}")

    @asyncSlot()
    async def start_all(self):
        self.xsens.start_logging()
        try:
            await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, START_RECORDING, response=True)
            self.log("🔴 同步錄製中...")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.status_label.setText("狀態: 正在錄製")
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
        self.btn_download.setEnabled(True)
        self.status_label.setText("狀態: 錄製完成")

    @asyncSlot()
    async def download_video(self):
        self.btn_download.setEnabled(False)
        self.log("🚀 啟動智能下載...")
        
        target = self.input_gopro_ip.text()
        ip = None
        if target == "gopro.local":
            try: ip = socket.gethostbyname("gopro.local")
            except: pass
        else: ip = target

        if not ip or not self._ping_gopro(ip):
            self.log("🔍 搜尋區網中的 GoPro (Parallel Scan)...")
            ip = await asyncio.get_event_loop().run_in_executor(None, self._scan_local_network_for_gopro)
        
        if ip:
            self.log(f"🌐 嘗試區網下載 (IP: {ip})...")
            if await asyncio.get_event_loop().run_in_executor(None, self._http_download_worker, ip):
                self.btn_download.setEnabled(True)
                return

        self.log("🔌 嘗試 USB 下載...")
        success, msg = self._usb_download_logic()
        if success:
            self.log(msg)
            self.btn_download.setEnabled(True)
            return
        else:
            self.log(f"⚠️ USB 下載未成功: {msg}")
        
        self.log("📡 嘗試備用 AP 模式 (直連 GoPro Wi-Fi)...")
        if self.connect_windows_wifi(self.input_ap_ssid.text(), self.input_ap_pass.text()):
            self.log("⏳ 等待 Windows 切換 Wi-Fi (12秒)...")
            await asyncio.sleep(12)
            for i in range(5):
                if self._ping_gopro("10.5.5.9"):
                    self.log("✅ 已連上 GoPro 熱點。")
                    break
                self.log(f"⏳ 等待 10.5.5.9 回應 ({i+1}/5)...")
                await asyncio.sleep(2)
            await asyncio.get_event_loop().run_in_executor(None, self._http_download_worker, "10.5.5.9")
        
        self.btn_download.setEnabled(True)

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
                last_folder = media_data['media'][-1]
                folder = last_folder['d']
                file_name = last_folder['fs'][-1]['n']
                tlog(f"🎬 發現最新影片: {file_name}，準備下載...")
                
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
        match = "HERO|GoPro"
        ps = rf"""
        try {{
            $s = New-Object -ComObject Shell.Application
            $thisPC = $s.Namespace(17)
            $p = $thisPC.Items() | Where-Object {{ $_.Name -match "{match}" }}
            if (!$p) {{ throw "找不到名字包含 {match} 的裝置" }}
            $storage = $p.GetFolder.Items() | Where-Object {{ $_.IsFolder }}
            if (!$storage) {{ throw "裝置內沒有可存取的儲存區" }}
            $dcim = $null
            foreach ($st in $storage) {{
                $found = $st.GetFolder.Items() | Where-Object {{ $_.Name -eq "DCIM" }}
                if ($found) {{ $dcim = $found; break }}
            }}
            if (!$dcim) {{ throw "在儲存區中找不到 DCIM 資料夾" }}
            $fs = @()
            foreach ($fld in $dcim.GetFolder.Items()) {{ 
                if ($fld.IsFolder) {{
                    $fs += $fld.GetFolder.Items() | Where-Object {{ $_.Name -like "*.MP4" }}
                }}
            }}
            if ($fs.Count -eq 0) {{ throw "相機內沒有 MP4 檔案" }}
            # 依照修改日期排序
            $l = $fs | Sort-Object {{ $_.ModifyDate }} -Descending | Select-Object -First 1
            $op = Join-Path (Get-Location) "video_output"
            if (!(Test-Path $op)) {{ New-Item -ItemType Directory -Path $op }}
            $s.Namespace($op).CopyHere($l, 16)
            Write-Host "SUCCESS:$($l.Name)"
        }} catch {{
            Write-Host "ERROR:$($_.Exception.Message)"
        }}
        """
        try:
            r = subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True, encoding='cp950')
            output = r.stdout.strip()
            if "SUCCESS:" in output: 
                return True, f"✅ USB 下載成功: {output.split('SUCCESS:')[1]}"
            else:
                return False, f"USB 失敗: {output}"
        except Exception as e:
            return False, f"USB 執行出錯: {e}"

    def connect_windows_wifi(self, ssid, password):
        xml = f"""<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1"><name>{ssid}</name><SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig><connectionType>ESS</connectionType><connectionMode>manual</connectionMode><MSM><security><authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption><sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{password}</keyMaterial></sharedKey></security></MSM></WLANProfile>"""
        try:
            p = Path.cwd() / "gp_temp.xml"
            p.write_text(xml)
            subprocess.run(f'netsh wlan add profile filename="{p}"', shell=True, capture_output=True)
            subprocess.run(f'netsh wlan connect name="{ssid}"', shell=True, capture_output=True)
            p.unlink()
            return True
        except: return False

    def closeEvent(self, event):
        new_config = {
            "local_wifi_ssid": self.input_ssid.text(),
            "local_wifi_pass": self.input_pass.text(),
            "gopro_ip": self.input_gopro_ip.text(),
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

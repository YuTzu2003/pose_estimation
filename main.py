import sys
import asyncio
import logging
from pathlib import Path
import requests
import subprocess
import time
import shutil
import csv
from threading import Lock

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QTextEdit, QHBoxLayout)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from qasync import QEventLoop, asyncSlot
from bleak import BleakClient, BleakScanner

# Xsens SDK
import xsensdeviceapi as xda

# ========================================================
# 📝 GoPro Wi-Fi 設定
# ========================================================
GOPRO_WIFI_SSID = "HERO11 Black"
GOPRO_WIFI_PASS = "Z#T-NgS-z2y"
# ========================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GOPRO_COMMAND_UUID = "b5f90072-aa8d-11e3-9046-0002a5d5c51b"
START_RECORDING    = bytearray([0x03, 0x01, 0x01, 0x01])
STOP_RECORDING     = bytearray([0x03, 0x01, 0x01, 0x00])
WAKE_WIFI          = bytearray([0x03, 0x17, 0x01, 0x01])

# GoPro 10+ 關鍵解鎖指令
SET_THIRD_PARTY_MODE = bytearray([0x03, 0x11, 0x01, 0x01])
SET_API_CONTROL_ON   = bytearray([0x03, 0x1a, 0x01, 0x01])

# ---------- Xsens Callbacks ----------

class WirelessMasterCallback(xda.XsCallback):
    def __init__(self):
        super().__init__()
        self.connected_mtws = set()
        self.lock = Lock()

    def onConnectivityChanged(self, dev, new_state):
        with self.lock:
            if new_state == xda.XCS_Wireless:
                logger.info(f"MTw connected: {dev.deviceId().toXsString()}")
                self.connected_mtws.add(dev)
            elif new_state in (xda.XCS_Disconnected, xda.XCS_Rejected):
                logger.info(f"MTw disconnected: {dev.deviceId().toXsString()}")
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
        """清除舊的數據緩衝區，確保錄影從最新數據開始"""
        with self.lock:
            self.packets.clear()

# ---------- Xsens Manager (Threaded) ----------

class XsensManager(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    connection_finished = pyqtSignal(bool)
    discovery_finished = pyqtSignal(int) # Returns the found channel
    
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
        self.radio_channel = 18 # Default or last found
        self.mode = "connect" # "connect" or "discover"

    def run(self):
        if self.mode == "discover":
            self._run_discovery()
        else:
            self._run_connect()

    def _run_discovery(self):
        """執行自動掃描頻道 (11-25)"""
        try:
            self.log_signal.emit("🔍 開始掃描頻道 (11-25)，請確保感測器已開機...")
            self.control = xda.XsControl_construct()
            
            # 優先嘗試 COM3，若失敗則掃描所有
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

            cb = WirelessMasterCallback() # Reuse callback for simplicity
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
        """執行快速連線 (鎖定頻道)"""
        try:
            self.log_signal.emit(f"🚀 正在連線頻道 {self.radio_channel}...")
            self.control = xda.XsControl_construct()
            
            # 優先嘗試 COM3
            master_port = xda.XsScanner_scanPort("COM3", xda.XBR_Invalid)
            
            # 如果 COM3 沒東西，或是 COM3 不是 Master，則掃描所有 Port
            is_master = not master_port.empty() and (master_port.deviceId().isWirelessMaster() or master_port.deviceId().isAwindaXStation())
            
            if not is_master:
                self.log_signal.emit("💡 COM3 不是 Master，正在掃描所有連接埠...")
                ports = xda.XsScanner_scanPorts()
                for p in ports:
                    if p.deviceId().isWirelessMaster() or p.deviceId().isAwindaXStation():
                        master_port = p
                        is_master = True
                        break

            if not is_master:
                self.log_signal.emit("❌ 找不到 Awinda 接收器。")
                self.connection_finished.emit(False)
                return

            self.log_signal.emit(f"找到接收器: {master_port.portName()}")
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

            # 等待感測器連入
            timeout = 0
            while len(self.master_cb.get_wireless_mtws()) == 0 and timeout < 50:
                time.sleep(0.1)
                timeout += 1
                self.status_signal.emit(f"等待感測器連線... ({timeout/10:.1f}s)")

            if len(self.master_cb.get_wireless_mtws()) == 0:
                self.log_signal.emit("❌ 感測器連線逾時，請確認頻道是否正確。")
                self.connection_finished.emit(False)
                return

            # 初始化 MTW 回呼
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
            if cb.device.resetOrientation(xda.XRM_Alignment):
                self.log_signal.emit(f"感測器 {cb.device.deviceId().toXsString()} 已歸零")
            else:
                self.log_signal.emit(f"感測器 {cb.device.deviceId().toXsString()} 歸零失敗")
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
        files   = {}
        start_counters = {}
        try:
            output_dir = Path.cwd() / "xsens_output"
            output_dir.mkdir(exist_ok=True)
            
            for cb in self.mtw_callbacks:
                fname = f"mtw_{cb.device.deviceId().toXsString()}_{int(time.time())}.csv"
                save_path = output_dir / fname
                f = open(save_path, "w", newline="")
                w = csv.writer(f)
                w.writerow(["packet_counter", "timestamp_s", "q_w", "q_x", "q_y", "q_z",
                            "acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z",
                            "mag_x", "mag_y", "mag_z"])
                writers[cb.index] = w
                files[cb.index]   = f
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
                        
                        q   = packet.orientationQuaternion()
                        # 使用最通用的 Calibrated Acceleration
                        acc = packet.calibratedAcceleration() 
                        gyr = packet.calibratedGyroscopeData()
                        mag = packet.calibratedMagneticField()
                        
                        # 💡 依照用戶需求：移除負號，僅保留 XY 對調進行測試
                        writers[cb.index].writerow([
                            current_counter,
                            f"{timestamp_s:.3f}",
                            q[0], q[2], q[1], q[3], # 僅對調
                            acc[1], acc[0], acc[2], # 僅對調 (acc_x = acc[1], acc_y = acc[0])
                            gyr[1], gyr[0], gyr[2], # 僅對調
                            mag[1], mag[0], mag[2], # 僅對調
                        ])
                    except Exception as inner_e:
                        logger.error(f"Data processing error: {inner_e}")
                        continue
                time.sleep(0.001)
        except Exception as e:
            self.log_signal.emit(f"❌ Xsens 記錄執行緒崩潰: {e}")
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
    def __init__(self):
        super().__init__()
        # GoPro State
        self.gopro_client = None
        self.gopro_address = None
        
        # Xsens State
        self.xsens = XsensManager()
        self.xsens.log_signal.connect(self.log)
        self.xsens.status_signal.connect(self.update_status_text)
        self.xsens.connection_finished.connect(self.on_xsens_connected)
        self.xsens.discovery_finished.connect(self.on_xsens_discovered)
        
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GoPro & Xsens 同步控制系統 (v2 改版)")
        self.setMinimumSize(600, 700)
        
        layout = QVBoxLayout()

        # Status Label
        self.status_label = QLabel("狀態: 準備就緒")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: blue;")
        layout.addWidget(self.status_label)

        # Xsens Discovery Section
        xsens_group = QHBoxLayout()
        self.btn_xsens_discover = QPushButton("🔍 尋找感測器 (掃描頻道)")
        self.btn_xsens_discover.setFixedHeight(40)
        self.btn_xsens_discover.clicked.connect(self.discover_xsens)
        xsens_group.addWidget(self.btn_xsens_discover)

        self.btn_xsens_connect = QPushButton("⚡ 快速連線 Xsens (固定頻道)")
        self.btn_xsens_connect.setFixedHeight(40)
        self.btn_xsens_connect.clicked.connect(self.connect_xsens)
        xsens_group.addWidget(self.btn_xsens_connect)
        layout.addLayout(xsens_group)

        # GoPro Connection Section
        self.btn_gopro_connect = QPushButton("2. 連線 GoPro (藍牙)")
        self.btn_gopro_connect.setFixedHeight(40)
        self.btn_gopro_connect.clicked.connect(self.connect_gopro)
        layout.addWidget(self.btn_gopro_connect)

        # Calibration Button
        self.btn_reset_xsens = QPushButton("3. Xsens 方向歸零 (Alignment Reset)")
        self.btn_reset_xsens.setFixedHeight(40)
        self.btn_reset_xsens.setEnabled(False)
        self.btn_reset_xsens.clicked.connect(self.reset_xsens)
        layout.addWidget(self.btn_reset_xsens)

        # Control Buttons
        ctrl_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("開始錄影 & 記錄")
        self.btn_start.setEnabled(False)
        self.btn_start.setMinimumHeight(60)
        self.btn_start.setStyleSheet("background-color: #d4edda; font-weight: bold;")
        self.btn_start.clicked.connect(self.start_all)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("結束錄影 & 記錄")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumHeight(60)
        self.btn_stop.setStyleSheet("background-color: #f8d7da; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_all)
        ctrl_layout.addWidget(self.btn_stop)

        layout.addLayout(ctrl_layout)

        # Download Button
        self.btn_download = QPushButton("儲存 GoPro 影片 (USB 模式)")
        self.btn_download.setEnabled(False)
        self.btn_download.setFixedHeight(40)
        self.btn_download.setStyleSheet("background-color: #cce5ff;")
        self.btn_download.clicked.connect(self.download_video)
        layout.addWidget(self.btn_download)

        # Log View
        layout.addWidget(QLabel("執行日誌:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #f8f9fa; font-family: Consolas;")
        layout.addWidget(self.log_view)

        self.setLayout(layout)

    def log(self, message):
        self.log_view.append(message)
        logger.info(message)

    def update_status_text(self, text):
        self.status_label.setText(text)

    # --- Xsens Actions ---
    def discover_xsens(self):
        self.btn_xsens_discover.setEnabled(False)
        self.btn_xsens_connect.setEnabled(False)
        self.xsens.mode = "discover"
        self.xsens.start()

    def connect_xsens(self):
        self.btn_xsens_discover.setEnabled(False)
        self.btn_xsens_connect.setEnabled(False)
        self.xsens.mode = "connect"
        self.xsens.start()

    def on_xsens_discovered(self, channel):
        self.btn_xsens_discover.setEnabled(True)
        self.btn_xsens_connect.setEnabled(True)
        if channel != -1:
            self.log(f"✅ 發現感測器，鎖定頻道: {channel}")
            # 下次連線會自動使用此頻道
        else:
            self.log("❌ 未能發現感測器。")

    def on_xsens_connected(self, success):
        self.btn_xsens_discover.setEnabled(True)
        self.btn_xsens_connect.setEnabled(True)
        if success:
            self.btn_reset_xsens.setEnabled(True)
            self.check_ready_state()
        else:
            self.log("❌ Xsens 連線失敗。")

    def reset_xsens(self):
        if self.xsens.reset_orientation():
            self.log("✅ Xsens 歸零成功。")
        else:
            self.log("❌ Xsens 歸零失敗。")

    # --- GoPro Actions ---
    @asyncSlot()
    async def connect_gopro(self):
        self.log("正在搜尋附近的 GoPro 藍牙裝置...")
        self.btn_gopro_connect.setEnabled(False)
        self.status_label.setText("狀態: 正在搜尋 GoPro...")
        try:
            devices = await BleakScanner.discover(timeout=5.0)
            gopro_device = None
            for d in devices:
                if d.name and "GoPro" in d.name:
                    gopro_device = d
                    break
            
            if not gopro_device:
                self.log("❌ 未找到 GoPro。請確認相機已開啟「無線連線」並進入「GoPro Quik 應用程式」配對模式。")
                self.btn_gopro_connect.setEnabled(True)
                return

            self.log(f"找到裝置: {gopro_device.name}，正在建立藍牙連線...")
            self.gopro_address = gopro_device.address
            self.gopro_client = BleakClient(self.gopro_address)
            await self.gopro_client.connect()
            
            # --- 新增：配對與初始化 ---
            self.log("正在嘗試藍牙配對 (若相機彈出視窗請點擊確認)...")
            try:
                await self.gopro_client.pair()
            except Exception as e:
                self.log(f"提示: 配對程序已跳過或使用現有配對 ({e})")

            self.log("正在初始化 GoPro API 控制權限...")
            try:
                # 必須先發送進入第三方模式指令，才能控制 GoPro 10/11/12
                await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
                await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
                self.log("🎉 GoPro 藍牙連線與初始化成功！")
            except Exception as e:
                self.log(f"⚠️ 初始化指令失敗: {e} (可能需要先手動配對)")
            # ------------------------

            self.check_ready_state()
        except Exception as e:
            self.log(f"GoPro 連線失敗: {str(e)}")
            self.btn_gopro_connect.setEnabled(True)

    def check_ready_state(self):
        gopro_ready = self.gopro_client and self.gopro_client.is_connected
        xsens_ready = self.xsens._is_connected
        
        if gopro_ready and xsens_ready:
            self.btn_start.setEnabled(True)
            self.status_label.setText("狀態: 裝置皆已就緒")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: green;")
        elif gopro_ready:
            self.status_label.setText("狀態: GoPro 已連線，等待 Xsens")
        elif xsens_ready:
            self.status_label.setText("狀態: Xsens 已連線，等待 GoPro")

    @asyncSlot()
    async def start_all(self):
        # 1. Start Xsens Logging
        self.xsens.start_logging()
        
        # 2. Start GoPro Recording
        if self.gopro_client and self.gopro_client.is_connected:
            try:
                self.log("發送 GoPro 錄影指令...")
                await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, START_RECORDING, response=True)
                self.log("🔴 同步記錄中...")
                self.btn_start.setEnabled(False)
                self.btn_stop.setEnabled(True)
                self.btn_download.setEnabled(False)
                self.btn_reset_xsens.setEnabled(False)
                self.status_label.setText("狀態: 正在同步錄影/記錄...")
            except Exception as e:
                self.log(f"GoPro 錄影啟動失敗: {e}")
                self.xsens.stop_logging()

    @asyncSlot()
    async def stop_all(self):
        # 1. Stop GoPro Recording
        if self.gopro_client and self.gopro_client.is_connected:
            try:
                self.log("發送 GoPro 停止錄影指令...")
                await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, STOP_RECORDING, response=True)
                
                # 解鎖 Wi-Fi 以便下載
                await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
                await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
                await self.gopro_client.write_gatt_char(GOPRO_COMMAND_UUID, WAKE_WIFI, response=True)
                
                self.log("GoPro 錄影已結束。")
            except Exception as e:
                self.log(f"GoPro 停止失敗: {e}")

        # 2. Stop Xsens Logging
        self.xsens.stop_logging()
        
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_download.setEnabled(True)
        self.btn_reset_xsens.setEnabled(True)
        self.status_label.setText("狀態: 記錄已完成")

    # --- Download logic from gopro_control.py ---
    @asyncSlot()
    async def download_video(self):
        try:
            self.btn_download.setEnabled(False)
            self.status_label.setText("狀態: 自動切換 Wi-Fi 中...")
            self.connect_windows_wifi(GOPRO_WIFI_SSID, GOPRO_WIFI_PASS)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._http_download_worker)
            self.btn_download.setEnabled(True)
        except Exception as e:
            self.log(f"操作出錯: {e}")
            self.btn_download.setEnabled(True)

    def connect_windows_wifi(self, ssid, password):
        self.log(f"正在建立 Wi-Fi 設定檔並自動切換至: {ssid}...")
        xml_content = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>manual</connectionMode>
    <MSM>
        <security>
            <authEncryption>
                <authentication>WPA2PSK</authentication>
                <encryption>AES</encryption>
                <useOneX>false</useOneX>
            </authEncryption>
            <sharedKey>
                <keyType>passPhrase</keyType>
                <protected>false</protected>
                <keyMaterial>{password}</keyMaterial>
            </sharedKey>
        </security>
    </MSM>
</WLANProfile>"""
        try:
            xml_path = Path.cwd() / "gopro_wifi_temp.xml"
            xml_path.write_text(xml_content, encoding="utf-8")
            subprocess.run(f'netsh wlan add profile filename="{xml_path}"', shell=True, stdout=subprocess.DEVNULL)
            subprocess.run(f'netsh wlan connect name="{ssid}"', shell=True, stdout=subprocess.DEVNULL)
            if xml_path.exists(): xml_path.unlink()
            return True
        except Exception as e:
            self.log(f"Wi-Fi 自動連線錯誤: {e}")
            return False

    def _http_download_worker(self):
        session = requests.Session()
        session.trust_env = False 
        time.sleep(5)
        
        gopro_ip = self.get_gopro_gateway_ip()
        
        # Wake up
        for _ in range(3):
            try: session.get(f"http://{gopro_ip}/gopro/camera/keep_alive", timeout=2)
            except: pass
            time.sleep(0.5)

        MEDIA_LIST_URL = f"http://{gopro_ip}:8080/gopro/media/list"
        retries = 20
        for i in range(retries):
            try:
                response = session.get(MEDIA_LIST_URL, timeout=4)
                if response.status_code == 200:
                    data = response.json()
                    if 'media' not in data or not data['media']: return
                    last_folder = data['media'][-1]
                    files = last_folder['fs']
                    folder_name = last_folder['d']
                    last_file_name = files[-1]['n']
                    
                    download_url = f"http://{gopro_ip}:8080/videos/DCIM/{folder_name}/{last_file_name}"
                    save_path = Path.cwd() / last_file_name
                    
                    with session.get(download_url, stream=True) as r:
                        r.raise_for_status()
                        with open(save_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                                
                    output_dir = Path.cwd() / "video_output"
                    output_dir.mkdir(exist_ok=True)
                    final_save_path = output_dir / last_file_name
                    shutil.move(str(save_path), str(final_save_path))
                    self.log(f"🎉 影片已儲存至: {final_save_path.name}")
                    return
            except Exception:
                time.sleep(2)

    def get_gopro_gateway_ip(self):
        try:
            result = subprocess.run('ipconfig', shell=True, capture_output=True, text=True, encoding='cp950')
            lines = result.stdout.split('\n')
            is_wifi_section = False
            for line in lines:
                if "Wireless LAN adapter Wi-Fi" in line or "無線區域網路介面卡 Wi-Fi" in line: is_wifi_section = True
                if is_wifi_section and ("Default Gateway" in line or "預設閘道" in line):
                    parts = line.split(':')
                    if len(parts) > 1:
                        ip = parts[1].strip()
                        if ip and not ip.startswith("fe80"): return ip
        except Exception: pass
        return "10.5.5.9"

    def closeEvent(self, event):
        self.xsens.cleanup()
        if self.gopro_client:
            asyncio.create_task(self.gopro_client.disconnect())
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = GoProXsensApp()
    window.show()
    with loop:
        loop.run_forever()
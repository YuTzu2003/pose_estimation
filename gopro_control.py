import sys
import asyncio
import logging
from pathlib import Path
import requests
import subprocess
import time
import shutil

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QTextEdit, QHBoxLayout)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from qasync import QEventLoop, asyncSlot
from bleak import BleakClient, BleakScanner

# ========================================================
# 📝 GoPro Wi-Fi 設定
# ========================================================
GOPRO_WIFI_SSID = "GP25025858"
GOPRO_WIFI_PASS = "ztW-9Nz-2Mf"
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

class DownloadSignaler(QObject):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)

class GoProVideoAutomationApp(QWidget):
    def __init__(self):
        super().__init__()
        self.client = None
        self.device_address = None
        
        self.signaler = DownloadSignaler()
        self.signaler.log_signal.connect(self.log)
        self.signaler.status_signal.connect(self.update_status_text)
        
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GoPro 10 遠端分步自動化控制系統")
        self.setMinimumSize(550, 500)
        
        layout = QVBoxLayout()

        self.status_label = QLabel("狀態: 準備就緒")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: blue;")
        layout.addWidget(self.status_label)

        self.btn_connect = QPushButton("1. 搜尋並連線至 GoPro (藍牙)")
        self.btn_connect.setFixedHeight(40)
        self.btn_connect.clicked.connect(self.connect_gopro)
        layout.addWidget(self.btn_connect)

        ctrl_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("開始錄影")
        self.btn_start.setEnabled(False)
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet("background-color: #d4edda;")
        self.btn_start.clicked.connect(self.start_recording)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("結束錄影")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet("background-color: #f8d7da; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_recording)
        ctrl_layout.addWidget(self.btn_stop)

        self.btn_download = QPushButton("儲存影片")
        self.btn_download.setEnabled(False)
        self.btn_download.setMinimumHeight(50)
        self.btn_download.setStyleSheet("background-color: #cce5ff; font-weight: bold;")
        self.btn_download.clicked.connect(self.download_video)
        ctrl_layout.addWidget(self.btn_download)

        layout.addLayout(ctrl_layout)

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
            if xml_path.exists():
                xml_path.unlink()
            return True
        except Exception as e:
            self.log(f"Wi-Fi 自動連線錯誤: {e}")
            return False

    def get_gopro_gateway_ip(self):
        try:
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
                        if ip and not ip.startswith("fe80"):
                            return ip
        except Exception:
            pass
        return "10.5.5.9"

    @asyncSlot()
    async def connect_gopro(self):
        self.log("正在搜尋附近的 GoPro 藍牙裝置...")
        self.btn_connect.setEnabled(False)
        self.status_label.setText("狀態: 正在搜尋...")
        try:
            devices = await BleakScanner.discover(timeout=5.0)
            gopro_device = None
            for d in devices:
                if d.name and "GoPro" in d.name:
                    gopro_device = d
                    break
            
            if not gopro_device:
                self.log("❌ 未找到 GoPro。請確認相機已開啟藍牙配對模式。")
                self.status_label.setText("狀態: 找不到裝置")
                self.btn_connect.setEnabled(True)
                return

            self.log(f"找到裝置: {gopro_device.name}，正在建立藍牙連線...")
            self.device_address = gopro_device.address
            self.client = BleakClient(self.device_address)
            await self.client.connect()
            
            self.status_label.setText("狀態: 藍牙已連線")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: green;")
            self.log("🎉 藍牙連線成功！可以開始錄影。")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_download.setEnabled(False)
        except Exception as e:
            self.log(f"連線失敗: {str(e)}")
            self.status_label.setText("狀態: 連線失敗")
            self.btn_connect.setEnabled(True)

    @asyncSlot()
    async def start_recording(self):
        if not self.client or not self.client.is_connected: return
        try:
            self.log("發送指令: 開始錄影...")
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, START_RECORDING, response=True)
            self.log("錄影已開始。")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_download.setEnabled(False)
            self.status_label.setText("狀態: 正在錄影...")
        except Exception as e:
            self.log(f"啟動錄影失敗: {e}")

    @asyncSlot()
    async def stop_recording(self):
        if not self.client or not self.client.is_connected: return
        try:
            self.log("發送指令: 結束錄影...")
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, STOP_RECORDING, response=True)
            self.log("錄影已結束。")
            
            self.log("解鎖指令: 授權相機進入外部連線控制狀態...")
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
            
            self.log("發送指令: 喚醒 GoPro Wi-Fi 熱點廣播...")
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, WAKE_WIFI, response=True)

            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_download.setEnabled(True)
            self.status_label.setText("狀態: 錄影已停止，Wi-Fi 已就緒")
        except Exception as e:
            self.log(f"結束錄影失敗: {e}")

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

    def _http_download_worker(self):
        session = requests.Session()
        session.trust_env = False 
        
        self.signaler.log_signal.emit("⏳ 正在等待 Windows 穩定 Wi-Fi 通道...")
        time.sleep(5)

        gopro_ip = self.get_gopro_gateway_ip()
        self.signaler.log_signal.emit(f"🔍 智慧偵測成功！當前 Wi-Fi 網關定位為: {gopro_ip}")

        # 🚨 關鍵新增：先用 HTTP 喚醒信號，強迫叫醒 GoPro 10 的網頁伺服器
        self.signaler.log_signal.emit("正在發送 HTTP 喚醒訊號 (Keep Alive)...")
        for _ in range(3):
            try:
                session.get(f"http://{gopro_ip}/gopro/camera/keep_alive", timeout=2)
                time.sleep(0.5)
            except Exception:
                pass

        MEDIA_LIST_URL = f"http://{gopro_ip}:8080/gopro/media/list"
        retries = 20
        
        for i in range(retries):
            try:
                self.signaler.log_signal.emit(f"正在連線 GoPro 媒體伺服器... (第 {i+1}/{retries} 次嘗試)")
                response = session.get(MEDIA_LIST_URL, timeout=4)
                
                if response.status_code == 200:
                    self.signaler.log_signal.emit("⚡ 成功獲取媒體清單！")
                    data = response.json()
                    
                    if 'media' not in data or not data['media'] or len(data['media']) == 0:
                        self.signaler.log_signal.emit("ℹ️ 提示：成功連上相機，但目前相機記憶卡內沒有任何媒體檔案！")
                        return
                    
                    last_folder = data['media'][-1]
                    if 'fs' not in last_folder or not last_folder['fs']:
                        self.signaler.log_signal.emit("ℹ️ 提示：成功連上相機，但最新資料夾內沒有檔案！")
                        return
                    
                    files = last_folder['fs']
                    folder_name = last_folder['d']
                    last_file_name = files[-1]['n']
                    
                    self.signaler.log_signal.emit(f"🎬 自動偵測到最新影片: {last_file_name}")
                    self.signaler.status_signal.emit("狀態: 正在自動傳輸影片...")
                    
                    download_url = f"http://{gopro_ip}:8080/videos/DCIM/{folder_name}/{last_file_name}"
                    save_path = Path.cwd() / last_file_name
                    
                    self.signaler.log_signal.emit(f"開始自動下載: {last_file_name} ...")
                    with session.get(download_url, stream=True) as r:
                        r.raise_for_status()
                        with open(save_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                                
                    output_dir = Path.cwd() / "video_output"
                    output_dir.mkdir(exist_ok=True)
                    final_save_path = output_dir / last_file_name
                    shutil.move(str(save_path), str(final_save_path))
                    
                    self.signaler.log_signal.emit(f"🎉【全自動完成】影片已儲存至: {final_save_path.absolute()}")
                    self.signaler.status_signal.emit("狀態: 下載完成！")
                    return
            except requests.exceptions.RequestException as e:
                # 💡 核心除錯點：把背後真正的錯誤印出來
                self.signaler.log_signal.emit(f"⏳ 通道對接中 ({str(e.__class__.__name__)})，等待相機回應...")
                time.sleep(2)
        
        self.signaler.log_signal.emit("❌ 自動連線逾時。請確認右下角 Wi-Fi 目前是否切換在 GoPro 上。")
        self.signaler.status_signal.emit("狀態: 連線逾時")

    async def disconnect_gopro(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()

    def closeEvent(self, event):
        asyncio.create_task(self.disconnect_gopro())
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = GoProVideoAutomationApp()
    window.show()
    with loop:
        loop.run_forever()
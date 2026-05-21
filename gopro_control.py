import sys
import asyncio
import logging
from pathlib import Path
import requests

from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QTextEdit, QHBoxLayout)
from PyQt5.QtCore import Qt
from qasync import QEventLoop, asyncSlot

# 改用 Python 最標準、最穩定的跨平台藍牙庫
from bleak import BleakClient, BleakScanner

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GoPro 藍牙控制需要的 UUID 與指令碼（這是 GoPro 官方標準協議）
GOPRO_COMMAND_UUID = "b5f90072-aa8d-11e3-9046-0002a5d5c51b"
START_RECORDING    = bytearray([0x03, 0x01, 0x01, 0x01]) # 開始錄影
STOP_RECORDING     = bytearray([0x03, 0x01, 0x01, 0x00]) # 停止錄影
WAKE_WIFI          = bytearray([0x03, 0x17, 0x01, 0x01]) # 喚醒 AP Wi-Fi

class GoProControlApp(QWidget):
    def __init__(self):
        super().__init__()
        self.client = None
        self.device_address = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GoPro 遠端控制 (原生藍牙 + HTTP下載)")
        self.setMinimumSize(550, 500)
        
        layout = QVBoxLayout()

        # 狀態顯示
        self.status_label = QLabel("狀態: 準備就緒")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: blue;")
        layout.addWidget(self.status_label)

        # 連線按鈕
        self.btn_connect = QPushButton("1. 搜尋並連線至 GoPro (藍牙)")
        self.btn_connect.setFixedHeight(40)
        self.btn_connect.clicked.connect(self.connect_gopro)
        layout.addWidget(self.btn_connect)

        # 控制按鈕 (水平排列)
        ctrl_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("開始錄影")
        self.btn_start.setEnabled(False)
        self.btn_start.setMinimumHeight(50)
        self.btn_start.setStyleSheet("background-color: #d4edda;")
        self.btn_start.clicked.connect(self.start_recording)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止錄影並下載")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setMinimumHeight(50)
        self.btn_stop.setStyleSheet("background-color: #f8d7da;")
        self.btn_stop.clicked.connect(self.stop_and_download)
        ctrl_layout.addWidget(self.btn_stop)

        layout.addLayout(ctrl_layout)

        # 訊息輸出框
        layout.addWidget(QLabel("執行日誌:"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #f8f9fa; font-family: Consolas;")
        layout.addWidget(self.log_view)

        self.setLayout(layout)

    def log(self, message):
        self.log_view.append(message)
        logger.info(message)

    @asyncSlot()
    async def connect_gopro(self):
        self.log("正在搜尋附近的 GoPro 藍牙裝置...")
        self.btn_connect.setEnabled(False)
        self.status_label.setText("狀態: 正在搜尋...")
        
        try:
            # 搜尋藍牙裝置，尋找名稱包含 GoPro 的設備
            devices = await BleakScanner.discover(timeout=5.0)
            gopro_device = None
            for d in devices:
                if d.name and "GoPro" in d.name:
                    gopro_device = d
                    break
            
            if not gopro_device:
                self.log("❌ 未找到 GoPro，請確保 GoPro 已開機且藍牙配對已開啟（開啟 Quik App 連線模式）。")
                self.status_label.setText("狀態: 找不到裝置")
                self.btn_connect.setEnabled(True)
                return

            self.log(f"找到裝置: {gopro_device.name} [{gopro_device.address}]，正在建立連線...")
            self.device_address = gopro_device.address
            
            # 建立藍牙連線
            self.client = BleakClient(self.device_address)
            await self.client.connect()
            
            self.status_label.setText("狀態: 藍牙已連線")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: green;")
            self.log("🎉 藍牙連線成功！可以開始錄影。")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
        except Exception as e:
            self.log(f"連線失敗: {str(e)}")
            self.status_label.setText("狀態: 連線失敗")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: bold; color: red;")
            self.btn_connect.setEnabled(True)

    @asyncSlot()
    async def start_recording(self):
        if not self.client or not self.client.is_connected: 
            self.log("藍牙未連線！")
            return
        try:
            self.log("發送指令: 開始錄影...")
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, START_RECORDING, response=True)
            self.log("錄影已開始。")
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.status_label.setText("狀態: 正在錄影...")
        except Exception as e:
            self.log(f"啟動錄影失敗: {e}")

    @asyncSlot()
    async def stop_and_download(self):
        if not self.client or not self.client.is_connected: return
        try:
            self.log("發送指令: 停止錄影...")
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, STOP_RECORDING, response=True)
            self.log("錄影已停止。")
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            
            # 透過藍牙命令 GoPro 打開 Wi-Fi AP
            self.log("發送指令: 喚醒 GoPro Wi-Fi 熱點...")
            await self.client.write_gatt_char(GOPRO_COMMAND_UUID, WAKE_WIFI, response=True)
            
            self.log("⚠️【請注意】現在請手動讓 Windows 連上這台 GoPro 的 Wi-Fi 熱點！")
            self.log("連上 Wi-Fi 後，程式會在背景自動抓取最新的影片檔案...")
            self.status_label.setText("狀態: 等待連上 Wi-Fi...")

            # 啟動下載線程
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._http_download_worker)

        except Exception as e:
            self.log(f"操作出錯: {e}")

    def _http_download_worker(self):
        GOPRO_IP = "10.5.5.9"
        MEDIA_LIST_URL = f"http://{GOPRO_IP}:8080/gopro/media/list"
        
        import time
        retries = 45
        for i in range(retries):
            try:
                response = requests.get(MEDIA_LIST_URL, timeout=2)
                if response.status_code == 200:
                    self.log("偵測到 Wi-Fi 已成功連接！正在讀取相機檔案清單...")
                    data = response.json()
                    
                    if 'media' not in data or not data['media']:
                        self.log("相機內沒有媒體檔案。")
                        return
                    
                    last_folder = data['media'][-1]
                    files = last_folder['fs']
                    if not files:
                        self.log("沒有找到可下載的影片。")
                        return
                    
                    folder_name = last_folder['d']
                    last_file_name = files[-1]['n']
                    
                    self.log(f"找到最新錄製影片: {folder_name}/{last_file_name}")
                    
                    download_url = f"http://{GOPRO_IP}:8080/videos/DCIM/{folder_name}/{last_file_name}"
                    save_path = Path.cwd() / last_file_name
                    
                    self.log(f"開始傳輸檔案: {last_file_name} -> 傳輸中，請稍候...")
                    self.status_label.setText("狀態: 正在下載檔案...")
                    
                    with requests.get(download_url, stream=True) as r:
                        r.raise_for_status()
                        with open(save_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                                
                    self.log(f"🎉 下載成功！檔案已存至: {save_path.absolute()}")
                    self.status_label.setText("狀態: 下載完成！")
                    return
            except requests.exceptions.RequestException:
                if i % 5 == 0:
                    self.log(f"⏳ 等待 Wi-Fi 連線中... (請確認已手動連上 GoPro Wi-Fi)")
                time.sleep(1)
        
        self.log("❌ 連線逾時！未偵測到 GoPro Wi-Fi 連線。")
        self.status_label.setText("狀態: Wi-Fi 連線逾時")

    async def disconnect_gopro(self):
        if self.client and self.client.is_connected:
            self.log("正在中斷藍牙連線...")
            await self.client.disconnect()
            self.log("已斷開連線。")

    def closeEvent(self, event):
        asyncio.create_task(self.disconnect_gopro())
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = GoProControlApp()
    window.show()
    with loop:
        loop.run_forever()
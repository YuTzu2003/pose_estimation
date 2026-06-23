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
                             QLineEdit, QGroupBox, QFormLayout, QComboBox,
                             QCheckBox, QScrollArea, QFrame)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread, QMetaObject, Q_ARG, pyqtSlot
from qasync import QEventLoop, asyncSlot
from bleak import BleakClient, BleakScanner

from xsens_manager import XsensManager
from gopro_preview import GoProPreviewWindow

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

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        import os
        base_path = sys._MEIPASS
    except Exception:
        import os
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ========================================================
# 📡 GoPro UUIDs & Commands
# ========================================================
GOPRO_COMMAND_UUID = "b5f90072-aa8d-11e3-9046-0002a5d5c51b"
GOPRO_SETTING_UUID = "b5f90074-aa8d-11e3-9046-0002a5d5c51b"

START_RECORDING    = bytearray([0x03, 0x01, 0x01, 0x01])
STOP_RECORDING     = bytearray([0x03, 0x01, 0x01, 0x00])
WAKE_WIFI          = bytearray([0x03, 0x17, 0x01, 0x01])

# USB Mode Settings (Setting 114)
SET_USB_MTP        = bytearray([0x03, 0x72, 0x01, 0x01]) # MTP Mode
SET_USB_CONNECT    = bytearray([0x03, 0x72, 0x01, 0x00]) # GoPro Connect (Camera) Mode

# Network Management (COHN)
NM_SERVICE_UUID    = "b5f90090-aa8d-11e3-9046-0002a5d5c51b"
NM_COMMAND_CHAR    = "b5f90091-aa8d-11e3-9046-0002a5d5c51b"

# GoPro 10+ 關鍵解鎖指令
SET_THIRD_PARTY_MODE = bytearray([0x03, 0x11, 0x01, 0x01])
SET_API_CONTROL_ON   = bytearray([0x03, 0x1a, 0x01, 0x01])

# AP 資訊讀取 UUIDs
WIFI_SSID_UUID = "b5f90002-aa8d-11e3-9046-0002a5d5c51b"
WIFI_PASS_UUID = "b5f90003-aa8d-11e3-9046-0002a5d5c51b"

# --- GoPro Settings Maps ---
ASPECT_RATIO_MAP = {
    "16:9": bytearray([0x03, 0x6c, 0x01, 0x01]),
    "4:3": bytearray([0x03, 0x6c, 0x01, 0x00]),
    "8:7": bytearray([0x03, 0x6c, 0x01, 0x03]),
}

RESOLUTION_MAP = {
    "1080p": bytearray([0x03, 0x02, 0x01, 0x09]),
    "1440p": bytearray([0x03, 0x02, 0x01, 0x07]),
    "2.7K": bytearray([0x03, 0x02, 0x01, 0x04]),
    "2.7K 4:3": bytearray([0x03, 0x02, 0x01, 0x06]),
    "4K": bytearray([0x03, 0x02, 0x01, 0x01]),
    "4K 4:3": bytearray([0x03, 0x02, 0x01, 0x12]),
    "5.3K": bytearray([0x03, 0x02, 0x01, 0x64]),
}

FPS_MAP = {
    "24 fps": bytearray([0x03, 0x03, 0x01, 0x0a]),
    "25 fps": bytearray([0x03, 0x03, 0x01, 0x09]),
    "30 fps": bytearray([0x03, 0x03, 0x01, 0x08]),
    "50 fps": bytearray([0x03, 0x03, 0x01, 0x06]),
    "60 fps": bytearray([0x03, 0x03, 0x01, 0x05]),
    "100 fps": bytearray([0x03, 0x03, 0x01, 0x02]),
    "120 fps": bytearray([0x03, 0x03, 0x01, 0x01]),
    "240 fps": bytearray([0x03, 0x03, 0x01, 0x00]),
}

GOPRO_SETTINGS_CONSTRAINTS = {
    "16:9": {
        "resolutions": ["5.3K", "4K", "2.7K", "1080p"],
        "fps": {
            "5.3K": ["60 fps", "30 fps", "24 fps"],
            "4K": ["120 fps", "60 fps", "30 fps", "24 fps"],
            "2.7K": ["240 fps", "120 fps", "60 fps"],
            "1080p": ["240 fps", "120 fps", "60 fps", "30 fps", "24 fps"]
        }
    },
    "4:3": {
        "resolutions": ["5.3K", "4K", "2.7K"],
        "fps": {
            "5.3K": ["30 fps", "24 fps"],
            "4K": ["60 fps", "30 fps", "24 fps"],
            "2.7K": ["120 fps", "60 fps"]
        }
    },
    "8:7": {
        "resolutions": ["5.3K", "4K"],
        "fps": {
            "5.3K": ["30 fps", "24 fps"],
            "4K": ["60 fps"]
        }
    }
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- Main App ----------

class GoProXsensApp(QWidget):
    append_log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.gopro_clients = [] # 改為儲存多台裝置：[{'client': client, 'name': name}, ...]
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
                border-radius: 12px;
                margin-top: 15px;
                padding: 15px 10px 10px 10px;
                font-weight: bold;
                font-size: 18px; /* Increased */
                color: #89ddff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                padding: 0 5px;
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
            
            /* 複選框 (QCheckBox) */
            QCheckBox {
                spacing: 8px;
                font-size: 16px;
                color: #a6accd;
                margin-bottom: 5px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                background-color: #090b10;
                border: 1px solid #2d3143;
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background-color: #82aaff;
                border-color: #82aaff;
            }
            
            /* 滾動區域 */
            QScrollArea#content_scroll_area {
                background-color: transparent;
                border: none;
            }
            QScrollArea#content_scroll_area > QWidget > QWidget {
                background-color: transparent;
            }
        """)

    def init_ui(self):
        self.setWindowTitle("GoPro & Xsens Control Hub")
        self.setWindowIcon(QIcon(resource_path("logo.png")))
        self.setMinimumSize(950, 800) # Increased width slightly for larger text
        
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        # --- Header Section ---
        header_widget = QWidget()
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        
        title = QLabel("GoPro & Xsens同步資料擷取與管理系統")
        title.setObjectName("header_title")
        title.setAlignment(Qt.AlignCenter)
        
        subtitle = QLabel("虎科大 人工智慧暨巨量資料實驗室 (先進運動表現實驗室)")
        subtitle.setObjectName("header_subtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        
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
        self.btn_xsens_discover = QPushButton("頻道掃描")
        self.btn_xsens_discover.clicked.connect(self.discover_xsens)
        self.btn_xsens_connect = QPushButton("快速連線")
        self.btn_xsens_connect.clicked.connect(self.connect_xsens)
        xbl.addWidget(self.btn_xsens_discover)
        xbl.addWidget(self.btn_xsens_connect)
        xl.addLayout(xbl)
        self.btn_reset_xsens = QPushButton("方向歸零")
        self.btn_reset_xsens.setEnabled(False)
        self.btn_reset_xsens.clicked.connect(self.reset_xsens)
        xl.addWidget(self.btn_reset_xsens)
        xsens_gb.setLayout(xl)
        left_panel.addWidget(xsens_gb)

        # 2. GoPro Card
        gopro_gb = QGroupBox("📷 GoPro 攝影機控制")
        gl = QVBoxLayout()
        gl.setSpacing(8)
        
        hbl_gopro = QHBoxLayout()
        self.btn_gopro_connect = QPushButton("搜尋並連線所有 GoPro")
        self.btn_gopro_connect.setObjectName("btn_gopro_connect")
        self.btn_gopro_connect.setFixedHeight(45)
        self.btn_gopro_connect.clicked.connect(self.connect_gopro)
        
        self.btn_gopro_reset = QPushButton("重置連線")
        self.btn_gopro_reset.setFixedWidth(120)
        self.btn_gopro_reset.setFixedHeight(45)
        self.btn_gopro_reset.clicked.connect(self.force_reset_gopro)
        
        hbl_gopro.addWidget(self.btn_gopro_connect, 3)
        hbl_gopro.addWidget(self.btn_gopro_reset, 1)
        gl.addLayout(hbl_gopro)

        hbl_power = QHBoxLayout()
        self.btn_gopro_sleep = QPushButton("一鍵相機休眠 (保留藍牙)")
        self.btn_gopro_sleep.setFixedHeight(40)
        self.btn_gopro_sleep.setEnabled(False)
        self.btn_gopro_sleep.clicked.connect(self.sleep_all_gopro)
        
        self.btn_gopro_poweroff = QPushButton("一鍵相機關機 (徹底關閉)")
        self.btn_gopro_poweroff.setFixedHeight(40)
        self.btn_gopro_poweroff.setEnabled(False)
        self.btn_gopro_poweroff.clicked.connect(self.poweroff_all_gopro)
        
        hbl_power.addWidget(self.btn_gopro_sleep)
        hbl_power.addWidget(self.btn_gopro_poweroff)
        gl.addLayout(hbl_power)

        # --- 同步設定區域 ---
        settings_layout = QHBoxLayout()
        
        self.combo_aspect = QComboBox()
        self.combo_aspect.addItems(list(GOPRO_SETTINGS_CONSTRAINTS.keys()))
        self.combo_aspect.setCurrentText("16:9")
        
        self.combo_res = QComboBox()
        self.combo_res.addItems(GOPRO_SETTINGS_CONSTRAINTS["16:9"]["resolutions"])
        self.combo_res.setCurrentText("1080p")
        
        self.combo_fps = QComboBox()
        self.combo_fps.addItems(GOPRO_SETTINGS_CONSTRAINTS["16:9"]["fps"]["1080p"])
        self.combo_fps.setCurrentText("60 fps")
        
        # Connect signals for constraint updates
        self.combo_aspect.currentTextChanged.connect(self.update_resolution_options)
        self.combo_res.currentTextChanged.connect(self.update_fps_options)
        
        self.btn_apply_settings = QPushButton("同步設定至相機")
        self.btn_apply_settings.setEnabled(False)
        self.btn_apply_settings.clicked.connect(self.apply_gopro_settings)

        settings_layout.addWidget(QLabel("比例:"))
        settings_layout.addWidget(self.combo_aspect)
        settings_layout.addWidget(QLabel("解析度:"))
        settings_layout.addWidget(self.combo_res)
        settings_layout.addWidget(QLabel("幀數:"))
        settings_layout.addWidget(self.combo_fps)
        gl.addLayout(settings_layout)
        gl.addWidget(self.btn_apply_settings)

        ap_selector_layout = QHBoxLayout()
        self.combo_ap_target = QComboBox()
        self.combo_ap_target.setPlaceholderText("選擇相機...")
        
        self.btn_fetch_ap = QPushButton("讀取相機熱點資訊")
        self.btn_fetch_ap.setEnabled(False)
        self.btn_fetch_ap.clicked.connect(self.fetch_gopro_ap_info)
        
        self.btn_preview_gopro = QPushButton("即時畫面預覽")
        self.btn_preview_gopro.setEnabled(False)
        self.btn_preview_gopro.clicked.connect(self.preview_gopro_feed)
        
        ap_selector_layout.addWidget(self.combo_ap_target, 2)
        ap_selector_layout.addWidget(self.btn_fetch_ap, 1)
        ap_selector_layout.addWidget(self.btn_preview_gopro, 1)
        gl.addLayout(ap_selector_layout)

        ap_box = QWidget()
        af = QFormLayout(ap_box)        
        af.setContentsMargins(0, 0, 0, 0)
        af.setVerticalSpacing(6)
        self.input_ap_ssid = QLineEdit(self.config["ap_ssid"])
        self.input_ap_pass = QLineEdit(self.config["ap_pass"])
        lbs_ssid = QLabel("熱點SSID:")
        lbs_ssid.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lbs_pass = QLabel("熱點密碼：")
        lbs_pass.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        af.addRow(lbs_ssid, self.input_ap_ssid)
        af.addRow(lbs_pass, self.input_ap_pass)
        gl.addWidget(ap_box)

        gopro_gb.setLayout(gl)
        left_panel.addWidget(gopro_gb)


        # 3. Control Card
        ctrl_gb = QGroupBox("🎮 同步錄製任務")
        cl = QVBoxLayout()
        cl.setSpacing(15)
        
        self.cb_enable_xsens = QCheckBox("啟用 Xsens 數據錄製")
        self.cb_enable_xsens.setChecked(True)
        self.cb_enable_xsens.stateChanged.connect(self.check_ready_state)
        cl.addWidget(self.cb_enable_xsens)
        
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
        
        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("下載對象:"))
        self.combo_download_target = QComboBox()
        self.combo_download_target.addItem("全部相機")
        target_layout.addWidget(self.combo_download_target, 1)
        dl.addLayout(target_layout)
        
        self.btn_download_wifi = QPushButton("Wi-Fi 下載")
        self.btn_download_wifi.setObjectName("btn_download_wifi")
        self.btn_download_wifi.setEnabled(False)
        self.btn_download_wifi.setFixedHeight(50)
        self.btn_download_wifi.clicked.connect(self.download_via_wifi)
        dl.addWidget(self.btn_download_wifi)

        self.btn_download_usb = QPushButton("USB 下載")
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
                # 偵測區段區分 (無縮排者為新區段開頭)
                if line and not line.startswith(" "):
                    if "Wireless LAN adapter" in line or "無線區域網路介面卡" in line:
                        is_wifi_section = True
                    else:
                        is_wifi_section = False
                
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
        if channel != -1: self.log(f"發現 Xsens 於頻道 {channel}")

    def on_xsens_connected(self, success):
        self.btn_xsens_discover.setEnabled(True)
        if success:
            self.btn_reset_xsens.setEnabled(True)
            self.check_ready_state()

    def reset_xsens(self):
        if self.xsens.reset_orientation(): self.log("Xsens 歸零成功")

    @asyncSlot()
    async def connect_gopro(self):
        self.log("正在搜尋附近的 GoPro...")
        self.btn_gopro_connect.setEnabled(False)
        self.btn_gopro_sleep.setEnabled(False)
        self.btn_gopro_poweroff.setEnabled(False)
        self.btn_download_wifi.setEnabled(False)
        self.btn_download_usb.setEnabled(False)
        self.combo_ap_target.clear() # 清空舊選單
        self.combo_download_target.clear()
        self.combo_download_target.addItem("全部相機")
        try:
            found_gopros = []
            for attempt in range(2):
                devices = await BleakScanner.discover(timeout=5.0)
                found_gopros = [d for d in devices if d.name and "GoPro" in d.name]
                if found_gopros: break
            
            if not found_gopros:
                self.log("未找到 GoPro...")
                self.btn_gopro_connect.setEnabled(True)
                return
            
            self.log(f"找到 {len(found_gopros)} 台 GoPro，開始依序連線...")
            
            for gopro in found_gopros:
                self.log(f"正在連線至 {gopro.name} ({gopro.address})...")
                client = BleakClient(gopro.address)
                try:
                    await client.connect()
                    try: await client.pair()
                    except: pass
                    await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
                    await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
                    self.gopro_clients.append({'client': client, 'name': gopro.name})
                    self.combo_ap_target.addItem(gopro.name) # 加到下拉選單
                    self.combo_download_target.addItem(gopro.name)
                    self.log(f"✅ {gopro.name} 連線成功！")
                except Exception as e:
                    self.log(f"❌ {gopro.name} 連線失敗: {e}")
            
            if self.gopro_clients:
                self.btn_fetch_ap.setEnabled(True)
                self.btn_preview_gopro.setEnabled(True)
                self.btn_apply_settings.setEnabled(True)
                self.btn_gopro_sleep.setEnabled(True)
                self.btn_gopro_poweroff.setEnabled(True)
                self.btn_download_wifi.setEnabled(True)
                self.btn_download_usb.setEnabled(True)
                self.check_ready_state()
            else:
                self.log("所有 GoPro 連線皆失敗。")
                self.btn_gopro_connect.setEnabled(True)
        except Exception as e:
            self.log(f"GoPro 掃描失敗: {e}")
            self.btn_gopro_connect.setEnabled(True)

    @asyncSlot()
    async def apply_gopro_settings(self):
        if not self.gopro_clients: return
        aspect_key = self.combo_aspect.currentText()
        res_key = self.combo_res.currentText()
        fps_key = self.combo_fps.currentText()
        
        aspect_cmd = ASPECT_RATIO_MAP[aspect_key]
        res_cmd = RESOLUTION_MAP[res_key]
        fps_cmd = FPS_MAP[fps_key]
        
        # GoPro mode command for Flat Video Mode (03 02 01 00)
        SET_MODE_VIDEO = bytearray([0x03, 0x02, 0x01, 0x00])
        
        self.btn_apply_settings.setEnabled(False)
        self.log(f"正在將所有相機設定為: 比例 {aspect_key} / 解析度 {res_key} / 幀數 {fps_key} ...")
        
        for gopro in self.gopro_clients:
            client = gopro['client']
            name = gopro['name']
            if client.is_connected:
                try:
                    # 0. 確保相機切換到「影片模式」 (不然設定指令會被相機忽略)
                    self.log(f"正在將 {name} 切換至影片模式...")
                    await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_MODE_VIDEO, response=True)
                    await asyncio.sleep(0.8) # 模式切換需要時間初始化感光元件
                    
                    # 1. 切換比例 (Setting ID 108)
                    self.log(f"正在設定 {name} 畫面比例...")
                    await client.write_gatt_char(GOPRO_SETTING_UUID, aspect_cmd, response=True)
                    await asyncio.sleep(0.8)
                    
                    # 2. 發送解析度指令
                    self.log(f"正在設定 {name} 解析度...")
                    await client.write_gatt_char(GOPRO_SETTING_UUID, res_cmd, response=True)
                    await asyncio.sleep(0.8)
                    
                    # 3. 發送幀率指令
                    self.log(f"正在設定 {name} 幀率...")
                    await client.write_gatt_char(GOPRO_SETTING_UUID, fps_cmd, response=True)
                    await asyncio.sleep(0.5)
                    
                    self.log(f"✅ {name} 所有設定套用成功。")
                except Exception as e:
                    self.log(f"❌ {name} 套用設定失敗: {e}")
        
        self.log("所有相機設定套用完畢。")
        self.btn_apply_settings.setEnabled(True)

    def update_resolution_options(self):
        aspect = self.combo_aspect.currentText()
        if aspect not in GOPRO_SETTINGS_CONSTRAINTS:
            return
            
        current_res = self.combo_res.currentText()
        allowed_res = GOPRO_SETTINGS_CONSTRAINTS[aspect]["resolutions"]
        
        self.combo_res.blockSignals(True)
        self.combo_res.clear()
        self.combo_res.addItems(allowed_res)
        
        if current_res in allowed_res:
            self.combo_res.setCurrentText(current_res)
        else:
            self.combo_res.setCurrentIndex(0)
        self.combo_res.blockSignals(False)
        
        self.update_fps_options()

    def update_fps_options(self):
        aspect = self.combo_aspect.currentText()
        res = self.combo_res.currentText()
        if aspect not in GOPRO_SETTINGS_CONSTRAINTS or res not in GOPRO_SETTINGS_CONSTRAINTS[aspect]["fps"]:
            return
            
        current_fps = self.combo_fps.currentText()
        allowed_fps = GOPRO_SETTINGS_CONSTRAINTS[aspect]["fps"][res]
        
        self.combo_fps.blockSignals(True)
        self.combo_fps.clear()
        self.combo_fps.addItems(allowed_fps)
        
        if current_fps in allowed_fps:
            self.combo_fps.setCurrentText(current_fps)
        else:
            self.combo_fps.setCurrentIndex(0)
        self.combo_fps.blockSignals(False)

    def check_ready_state(self, state=None):
        gopro_ready = len(self.gopro_clients) > 0 and all(c['client'].is_connected for c in self.gopro_clients)
        use_xsens = self.cb_enable_xsens.isChecked()
        xsens_ready = self.xsens._is_connected
        
        if gopro_ready and (not use_xsens or xsens_ready):
            self.btn_start.setEnabled(True)
            if use_xsens:
                self.status_label.setText("狀態: 裝置皆已就緒")
                self.status_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
            else:
                self.status_label.setText("狀態: GoPro 已就緒 (僅錄製影片)")
                self.status_label.setStyleSheet("color: #82aaff; font-weight: bold;")
        else:
            reasons = []
            if not gopro_ready: reasons.append("GoPro 未連線")
            if use_xsens and not xsens_ready: reasons.append("Xsens 未連線")
            self.btn_start.setEnabled(False)
            self.status_label.setText(f"狀態: 等待中 ({', '.join(reasons)})")
            self.status_label.setStyleSheet("color: #a6accd;")

    @asyncSlot()
    async def fetch_gopro_ap_info(self):
        selected_name = self.combo_ap_target.currentText()
        if not selected_name:
            self.log("請先從下拉選單選擇一台相機")
            return
            
        target_gopro = next((g for g in self.gopro_clients if g['name'] == selected_name), None)
        if not target_gopro or not target_gopro['client'].is_connected:
            self.log(f"錯誤: {selected_name} 已斷線")
            return
        
        client = target_gopro['client']
        self.log(f"正在從 {selected_name} 讀取熱點資訊...")
        try:
            ssid_bytes = await client.read_gatt_char(WIFI_SSID_UUID)
            pass_bytes = await client.read_gatt_char(WIFI_PASS_UUID)
            ssid = ssid_bytes.decode('utf-8').strip('\x00')
            password = pass_bytes.decode('utf-8').strip('\x00')
            self.input_ap_ssid.setText(ssid)
            self.input_ap_pass.setText(password)
            self.log(f"✅ {selected_name} 讀取成功！SSID: {ssid}")
        except Exception as e:
            self.log(f"讀取熱點資訊失敗: {e}")

    def get_current_wifi_ssid(self):
        try:
            out = subprocess.run("netsh wlan show interfaces", shell=True, capture_output=True, text=True, encoding="cp950")
            for line in out.stdout.splitlines():
                if "SSID" in line and "BSSID" not in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        return parts[1].strip()
        except:
            pass
        return None

    @asyncSlot()
    async def preview_gopro_feed(self):
        if hasattr(self, 'preview_windows') and len(self.preview_windows) > 0:
            self.log("⚠️ 警告: 已有開啟中的預覽視窗。")
            return

        self.btn_preview_gopro.setEnabled(False) # 立即禁用按鈕，防止重複點擊

        selected_name = self.combo_ap_target.currentText()
        if not selected_name:
            self.log("請先從下拉選單選擇一台相機")
            self.btn_preview_gopro.setEnabled(True)
            return
            
        target_gopro = next((g for g in self.gopro_clients if g['name'] == selected_name), None)
        if not target_gopro or not target_gopro['client'].is_connected:
            self.log(f"錯誤: {selected_name} 已斷線")
            self.btn_preview_gopro.setEnabled(True)
            return
            
        client = target_gopro['client']
        self.log(f"正在讀取 {selected_name} 的 Wi-Fi 資訊以開啟預覽...")
        
        original_ssid = self.get_current_wifi_ssid()
        if original_ssid:
            self.log(f"已記錄目前連線的 Wi-Fi: {original_ssid}")
            
        try:
            ssid_bytes = await client.read_gatt_char(WIFI_SSID_UUID)
            pass_bytes = await client.read_gatt_char(WIFI_PASS_UUID)
            ssid = ssid_bytes.decode('utf-8').strip('\x00')
            password = pass_bytes.decode('utf-8').strip('\x00')
            
            # 喚醒相機 Wi-Fi AP
            self.log(f"正在透過 BLE 喚醒 {selected_name} 的 Wi-Fi AP...")
            await client.write_gatt_char(GOPRO_COMMAND_UUID, WAKE_WIFI, response=True)
            await asyncio.sleep(2.0)
            
            if not hasattr(self, 'preview_windows'):
                self.preview_windows = []
                
            win = GoProPreviewWindow(ssid, password, original_ssid, self)
            self.preview_windows.append(win)
            win.show()
        except Exception as e:
            self.log(f"開啟預覽失敗: {e}")
            self.btn_preview_gopro.setEnabled(True)


    @asyncSlot()
    async def provision_gopro_wifi(self):
        # Method preserved for structural integrity but no longer called from UI
        pass

    @asyncSlot()
    async def start_all(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        
        connected_clients = [c for c in self.gopro_clients if c['client'].is_connected]
        if not connected_clients:
            self.log("❌ 錯誤: 沒有已連線的 GoPro")
            self.btn_start.setEnabled(True)
            return

        self.log(f"正在啟動 {len(connected_clients)} 台 GoPro 錄影...")
        
        async def start_camera(gopro):
            client = gopro['client']
            name = gopro['name']
            try:
                await client.write_gatt_char(GOPRO_COMMAND_UUID, START_RECORDING, response=True)
                return True, name
            except Exception as e:
                return False, f"{name}: {e}"

        # 同時啟動所有相機錄影
        results = await asyncio.gather(*(start_camera(c) for c in connected_clients), return_exceptions=True)
        
        success_count = 0
        for res in results:
            if isinstance(res, tuple) and res[0]:
                success_count += 1
            else:
                self.log(f"啟動失敗: {res}")

        if success_count > 0:
            if self.cb_enable_xsens.isChecked() and self.xsens._is_connected:
                self.xsens.start_logging()
                self.log(f"同步錄製中... (成功: {success_count}/{len(connected_clients)})")
            else:
                self.log(f"GoPro 錄影中... (成功: {success_count}/{len(connected_clients)})")
            self.btn_stop.setEnabled(True)
            self.status_label.setText("狀態: 正在錄製")
            self.status_label.setStyleSheet("color: #f44747; font-weight: bold;")
        else:
            self.log("所有相機啟動錄影失敗。")
            self.btn_start.setEnabled(True)

    @asyncSlot()
    async def stop_all(self):
        self.btn_stop.setEnabled(False)
        self.btn_start.setEnabled(False)
        
        connected_clients = [c for c in self.gopro_clients if c['client'].is_connected]
        if not connected_clients:
            self.log("⚠️ 警告: 沒有已連線的 GoPro 可供停止")
            if self.cb_enable_xsens.isChecked() and self.xsens._is_connected:
                self.xsens.stop_logging()
            self.btn_start.setEnabled(True)
            return

        self.log(f"正在停止 {len(connected_clients)} 台 GoPro 錄影...")

        async def stop_camera(gopro):
            client = gopro['client']
            name = gopro['name']
            try:
                await client.write_gatt_char(GOPRO_COMMAND_UUID, STOP_RECORDING, response=True)
                return True, name
            except Exception as e:
                return False, f"{name}: {e}"

        # 1. 發送停止指令
        await asyncio.gather(*(stop_camera(c) for c in connected_clients), return_exceptions=True)
        
        # 2. 確保 Xsens 檔案寫入完全關閉
        if self.cb_enable_xsens.isChecked() and self.xsens._is_connected:
            self.log("正在儲存 Xsens 數據...")
            self.xsens.stop_logging()
        
        # 3. 逐一發送後續指令 (WAKE_WIFI 等)
        await asyncio.sleep(1.0)
        self.log("正在重新授權 API 並喚醒 Wi-Fi...")
        
        async def post_stop_commands(gopro):
            client = gopro['client']
            name = gopro['name']
            try:
                await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
                await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
                await client.write_gatt_char(GOPRO_COMMAND_UUID, WAKE_WIFI, response=True)
            except Exception as e:
                self.log(f"相機 {name} 後續指令失敗: {e}")

        await asyncio.gather(*(post_stop_commands(c) for c in connected_clients), return_exceptions=True)

        self.log("錄影已停止")
        
        # 全面解鎖按鈕
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_download_wifi.setEnabled(True)
        self.btn_download_usb.setEnabled(True)
        self.btn_reset_xsens.setEnabled(True) 
        self.status_label.setText("狀態: 錄製完成")
        self.status_label.setStyleSheet("color: #dcdcdc; font-weight: bold;")
        self.log("提示：若要進行下一次測量，請點擊「方向歸零」後再點擊「開始」。")

    @asyncSlot()
    async def download_via_wifi(self):
        self.btn_download_wifi.setEnabled(False)
        
        connected_gopros = [c for c in self.gopro_clients if c['client'].is_connected]
        if not connected_gopros:
            self.log("❌ 錯誤: 沒有已連線的 GoPro 進行 Wi-Fi 下載。請先連線相機。")
            self.btn_download_wifi.setEnabled(True)
            return

        target = self.combo_download_target.currentText()
        if target and target != "全部相機":
            connected_gopros = [c for c in connected_gopros if c['name'] == target]
            if not connected_gopros:
                self.log(f"❌ 錯誤: 指定的相機 {target} 目前未連線。")
                self.btn_download_wifi.setEnabled(True)
                return
            self.log(f"啟動指定相機 {target} Wi-Fi 下載流程...")
        else:
            self.log(f"啟動 {len(connected_gopros)} 台 GoPro Wi-Fi 循序切換與下載流程...")
        
        for idx, gopro in enumerate(connected_gopros):
            name = gopro['name']
            client = gopro['client']
            self.log(f"----------------------------------------")
            self.log(f"正在處理第 {idx+1}/{len(connected_gopros)} 台相機: {name} ...")
            
            try:
                # 1. 讀取此台相機的熱點資訊
                self.log(f"正在從 {name} 讀取熱點資訊...")
                ssid_bytes = await client.read_gatt_char(WIFI_SSID_UUID)
                pass_bytes = await client.read_gatt_char(WIFI_PASS_UUID)
                ssid = ssid_bytes.decode('utf-8').strip('\x00').strip()
                password = pass_bytes.decode('utf-8').strip('\x00').strip()
                self.log(f"取得熱點 SSID: {ssid}")
                
                # 喚醒相機 Wi-Fi AP，並確保進入第三方模式與 API 控制開啟
                self.log(f"正在透過 BLE 喚醒 {name} 的 Wi-Fi AP...")
                try:
                    await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
                    await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
                except Exception as e:
                    self.log(f"⚠️ 發送 API 控制指令提示: {e}")
                await client.write_gatt_char(GOPRO_COMMAND_UUID, WAKE_WIFI, response=True)
                await asyncio.sleep(2.0)
                
                # 更新 UI 的欄位以供參考
                self.input_ap_ssid.setText(ssid)
                self.input_ap_pass.setText(password)
                
                # 2. 檢查目前是否已連線到此 Wi-Fi AP
                gopro_ip = self.get_gopro_gateway_ip()
                is_connected_to_correct_ap = False
                
                # 在 Windows 下檢測目前 Wi-Fi 的 SSID
                try:
                    out = subprocess.run("netsh wlan show interfaces", shell=True, capture_output=True, text=True, encoding="cp950")
                    if ssid in out.stdout:
                        is_connected_to_correct_ap = True
                except:
                    pass
                
                wifi_ip, _ = self.get_wifi_ip_details()
                if is_connected_to_correct_ap and self._ping_gopro(gopro_ip, wifi_ip):
                    self.log(f"已處於該相機的 Wi-Fi 熱點 ({ssid})，直接下載最新影片...")
                    await asyncio.get_event_loop().run_in_executor(None, self._http_download_worker, gopro_ip, ssid)
                else:
                    self.log(f"開始連接該相機的 Wi-Fi 熱點 ({ssid})...")
                    if await self.connect_windows_wifi(ssid, password):
                        self.log("等待 Windows 穩定連線 (10秒)...")
                        await asyncio.sleep(10)
                        
                        gopro_ip = self.get_gopro_gateway_ip()
                        self.log(f"正在對接相機 IP: {gopro_ip}")
                        await asyncio.get_event_loop().run_in_executor(None, self._http_download_worker, gopro_ip, ssid)
                    else:
                        self.log(f"❌ {name} 的 Wi-Fi 連線指令失敗。")
            except Exception as e:
                self.log(f"❌ 處理 {name} 時發生錯誤: {e}")
        
        self.log(f"----------------------------------------")
        self.log("所有相機的 Wi-Fi 下載流程結束。")
        self.btn_download_wifi.setEnabled(True)

    async def connect_windows_wifi(self, ssid, password):
        self.log(f"等待 5 秒讓 GoPro Wi-Fi 啟動廣播...")
        await asyncio.sleep(5)  # 關鍵修正：給 GoPro 暖機時間
        
        self.log(f"正在建立 Wi-Fi 設定檔並嘗試連線至: {ssid}...")
        # 注意：下面的 xml_content 必須頂格寫，不能有縮排空白
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
            
            # 1. 斷開目前連線 (確保它會切換)
            subprocess.run('netsh wlan disconnect', shell=True, capture_output=True)
            
            # 2. 新增設定檔 (直接覆蓋，避免刪除設定檔導致 Windows 遺失 BSSID 快取資訊)
            add_result = subprocess.run(f'netsh wlan add profile filename="{xml_path}"', shell=True, capture_output=True, text=True, encoding='cp950')
            if add_result.returncode != 0:
                self.log(f"新增設定檔失敗: {add_result.stderr or add_result.stdout}")

            await asyncio.sleep(1) 

            # 3. 執行連線 (進入循環並定期重送連線命令，以防發送當下相機 Wi-Fi 還沒廣播就緒)
            self.log("正在嘗試連線到相機 Wi-Fi...")
            success = False
            for attempt in range(15):
                # 每 4 秒重新發送一次連線指令，確保相機啟動廣播後立刻被連線要求補捉
                if attempt % 4 == 0:
                    subprocess.run(f'netsh wlan connect name="{ssid}"', shell=True, capture_output=True)
                
                await asyncio.sleep(1.0)
                check_result = subprocess.run("netsh wlan show interfaces", shell=True, capture_output=True, text=True, encoding='cp950')
                
                # 解析目前連線的 SSID 與連線狀態
                current_ssid = ""
                current_state = ""
                for line in check_result.stdout.split('\n'):
                    l = line.strip()
                    if l.startswith("SSID"):
                        parts = l.split(':')
                        if len(parts) > 1:
                            current_ssid = parts[1].strip()
                    if l.startswith("狀態") or l.startswith("State"):
                        parts = l.split(':')
                        if len(parts) > 1:
                            current_state = parts[1].strip()
                            
                # 判斷是否為目標相機 SSID 且狀態為「連線」、「已連線」或「connected」
                if current_ssid == ssid and (current_state == "連線" or current_state == "已連線" or current_state.lower() == "connected"):
                    self.log(f"✅ Wi-Fi 已成功連接到相機熱點: {ssid}！")
                    success = True
                    break
                    
                self.log(f"⏳ 等待 Wi-Fi 聯結與握手... ({attempt+1}/15)")
                
            if not success:
                # 擷取目前實際連接的 SSID 以供診斷
                current_ssid = "無連線"
                check_result = subprocess.run("netsh wlan show interfaces", shell=True, capture_output=True, text=True, encoding='cp950')
                for line in check_result.stdout.split('\n'):
                    l = line.strip()
                    if l.startswith("SSID"):
                        parts = l.split(':')
                        if len(parts) > 1:
                            current_ssid = parts[1].strip()
                            break
                self.log(f"❌ Wi-Fi 連線失敗。Windows 無法在 15 秒內連接上 {ssid}。")
                self.log(f"ℹ️ 診斷：電腦目前實際連接的 Wi-Fi 是：「{current_ssid}」")
                self.log(f"👉 請檢查您的 GoPro 螢幕設定：偏好設定 -> 連線 -> Wi-Fi 頻帶，將其從「5GHz」切換為「2.4GHz」後重試！")

            if xml_path.exists():
                xml_path.unlink()
            return success
        except Exception as e:
            self.log(f"Wi-Fi 自動連線發生例外錯誤: {e}")
            return False

    @asyncSlot()
    async def download_via_usb(self):
        self.btn_download_usb.setEnabled(False)
        
        target = self.combo_download_target.currentText()
        connected_clients = [c for c in self.gopro_clients if c['client'].is_connected]
        
        if target and target != "全部相機":
            connected_clients = [c for c in connected_clients if c['name'] == target]
            if not connected_clients:
                self.log(f"❌ 錯誤: 指定的相機 {target} 目前未連線。")
                self.btn_download_usb.setEnabled(True)
                return
            self.log(f"啟動指定相機 {target} USB 下載流程...")
        else:
            self.log("啟動所有相機 USB 下載流程...")
        
        try:
            if connected_clients:
                self.log(f"正在將 {len(connected_clients)} 台 GoPro 切換至 USB 傳輸模式 (MTP)...")
                
                async def set_mtp(gopro):
                    try:
                        await gopro['client'].write_gatt_char(GOPRO_SETTING_UUID, SET_USB_MTP, response=True)
                    except: pass

                await asyncio.gather(*(set_mtp(c) for c in connected_clients), return_exceptions=True)
                self.log("等待 Windows 辨識裝置 (5秒)...")
                await asyncio.sleep(5.0)
            
            # 核心修復：使用 executor 在背景執行，避免阻塞 Event Loop 導致藍牙斷線！
            self.log("正在複製檔案，請勿拔除傳輸線...")
            success, msg = await asyncio.get_event_loop().run_in_executor(None, self._usb_download_logic, target)
            
            if success:
                self.log(msg)
            else:
                self.log(f"USB 下載未成功: {msg}")
                self.log("提示：請確保 GoPro 處於 MTP/連線模式，且已插上 USB 線。")

            # 下載完成後，立即將相機切回攝影模式
            if connected_clients:
                self.log("正在將所有 GoPro 恢復至攝影模式...")
                
                async def restore_camera(gopro):
                    client = gopro['client']
                    try:
                        await client.write_gatt_char(GOPRO_SETTING_UUID, SET_USB_CONNECT, response=True)
                        await asyncio.sleep(0.5)
                        await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_THIRD_PARTY_MODE, response=True)
                        await client.write_gatt_char(GOPRO_COMMAND_UUID, SET_API_CONTROL_ON, response=True)
                    except: pass

                await asyncio.gather(*(restore_camera(c) for c in connected_clients), return_exceptions=True)
                self.log("相機狀態已還原，可隨時開始新的錄製。")
            else:
                self.log("傳輸期間藍牙可能中斷，下次錄影前將嘗試自動重連。")

        except Exception as e:
            self.log(f"USB 操作出錯: {e}")
            
        self.btn_download_usb.setEnabled(True)

    def _ping_gopro(self, ip, source_ip=None):
        # 嘗試連接 8080 埠或 80 埠，只要任一個通即代表網路層已連通
        for port in [8080, 80]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                if source_ip and "." in source_ip and not source_ip.startswith("169.254"):
                    s.bind((source_ip, 0))
                s.connect((ip, port))
                s.close()
                return True
            except: 
                pass
        return False

    def get_wifi_ip_details(self):
        try:
            result = subprocess.run('ipconfig', shell=True, capture_output=True, text=True, encoding='cp950')
            lines = result.stdout.split('\n')
            is_wifi_section = False
            ipv4 = "無 IP"
            gateway = "無閘道"
            for line in lines:
                if line and not line.startswith(" "):
                    if "Wireless LAN adapter" in line or "無線區域網路介面卡" in line:
                        is_wifi_section = True
                    else:
                        is_wifi_section = False
                if is_wifi_section:
                    l = line.strip()
                    if "IPv4" in l:
                        parts = l.split(':')
                        if len(parts) > 1:
                            ipv4 = parts[1].strip()
                    if "Default Gateway" in l or "預設閘道" in l:
                        parts = l.split(':')
                        if len(parts) > 1:
                            gateway = parts[1].strip()
            return ipv4, gateway
        except:
            return "錯誤", "錯誤"

    def _scan_local_network_for_gopro(self):
        try:
            local_ips = socket.gethostbyname_ex(socket.gethostname())[2]
            for lip in local_ips:
                if lip.startswith("127."): continue
                prefix = ".".join(lip.split(".")[:-1])
                ips = [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != lip]
                with ThreadPoolExecutor(max_workers=100) as executor:
                    futures = {executor.submit(self._ping_gopro, ip, lip): ip for ip in ips}
                    for f in as_completed(futures):
                        if f.result(): return futures[f]
        except: pass
        return None

    def _http_download_worker(self, gopro_ip, ssid="GoPro"):
        session = requests.Session()
        session.trust_env = False
        
        def tlog(m): 
            self.append_log_signal.emit(m)
            logger.info(f"[Download] {m}")

        try:
            tlog("正在對接相機服務...")
            
            # 💡 改善：等待 Windows 網路介面卡取得 IP 並且連通 GoPro 服務端 (最多等待 15 秒)
            connected = False
            for attempt in range(15):
                # 重新偵測最新網關 IP，因為剛連上時可能還沒取得，會退化回 10.5.5.9
                current_ip = self.get_gopro_gateway_ip()
                wifi_ip, wifi_gw = self.get_wifi_ip_details()
                
                # 只有當 wifi_ip 是有效且非 APIPA 的時候才傳入進行綁定
                use_source_ip = wifi_ip if (wifi_ip and "." in wifi_ip and not wifi_ip.startswith("169.254") and wifi_ip != "無 IP") else None
                is_ping_ok = self._ping_gopro(current_ip, use_source_ip)
                tlog(f"⏳ 等待 Windows 分配 IP... ({attempt+1}/15) | 本地 Wi-Fi IP: {wifi_ip}, 閘道: {wifi_gw}, 目標 IP: {current_ip}, 狀態: {'已連通' if is_ping_ok else '等待中'}")
                
                if is_ping_ok:
                    gopro_ip = current_ip
                    connected = True
                    tlog(f"✅ 網路連線已建立！相機 IP: {gopro_ip}")
                    break
                time.sleep(1.0)
                
            if not connected:
                tlog("❌ 無法建立網路連線。請確認電腦已連上 GoPro 的 Wi-Fi，且防火牆未阻擋。")
                return False

            # 連通後，重新獲取本機最新且已確認連通的 Wi-Fi IP 並綁定 HTTP session
            wifi_ip, _ = self.get_wifi_ip_details()
            if wifi_ip and "." in wifi_ip and not wifi_ip.startswith("169.254") and wifi_ip != "無 IP":
                try:
                    class SourceIPAdapter(requests.adapters.HTTPAdapter):
                        def __init__(self, source_ip, **kwargs):
                            self.source_ip = source_ip
                            super().__init__(**kwargs)
                        def init_poolmanager(self, connections, maxsize, block=False):
                            from urllib3.poolmanager import PoolManager
                            self.poolmanager = PoolManager(
                                num_pools=connections,
                                maxsize=maxsize,
                                block=block,
                                source_address=(self.source_ip, 0)
                            )
                    adapter = SourceIPAdapter(wifi_ip)
                    session.mount('http://', adapter)
                    session.mount('https://', adapter)
                    tlog(f"已強制將 HTTP 連線綁定至網卡 IP: {wifi_ip}")
                except Exception as e:
                    tlog(f"⚠️ 綁定網卡 IP 發生異常: {e}")

            # 發送 Keep Alive，用 try-except 包裹避免單次失敗直接崩潰
            for _ in range(3):
                try: 
                    session.get(f"http://{gopro_ip}/gopro/camera/keep_alive", timeout=1.5)
                except Exception: 
                    pass
                time.sleep(0.3)
                
            res = session.get(f"http://{gopro_ip}:8080/gopro/media/list", timeout=5)
            if res.status_code == 200:
                media_data = res.json()
                if 'media' not in media_data or not media_data['media']:
                    tlog("相機內目前沒有影片檔案")
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
                    tlog("找不到任何 MP4 影片")
                    return False

                # 依照 mod (建立時間) 由新到舊排序
                all_files.sort(key=lambda x: x['mod'], reverse=True)
                latest = all_files[0]
                
                folder = latest['dir']
                file_name = latest['n']
                tlog(f"發現全相機最新影片 (依日期): {file_name}")
                
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
                                tlog(f"已下載: {downloaded/1e6:.1f}MB / {total/1e6:.1f}MB")
                                last_update = time.time()
                
                # 依相機 SSID 命名子目錄，以防下載多台相機時覆蓋同名檔案
                ssid_folder = ssid.replace(" ", "_").replace(":", "_")
                out = Path.cwd() / "video_output" / ssid_folder
                out.mkdir(parents=True, exist_ok=True)
                
                dest_file = out / file_name
                if dest_file.exists():
                    dest_file.unlink()
                shutil.move(str(save_path), str(dest_file))
                tlog(f"下載完成: {file_name} (已儲存至 {out})")
                return True
        except Exception as e:
            tlog(f"HTTP 下載出錯: {e}")
        return False

    def _usb_download_logic(self, target_name=None):
        match_token = target_name if (target_name and target_name != "全部相機") else "HERO|GoPro"
        ps_template = r"""
        try {
            $shell = New-Object -ComObject Shell.Application
            $thisPC = $shell.Namespace(17)
            
            # 尋找所有連線的 GoPro 裝置
            $goproDevices = $thisPC.Items() | Where-Object { $_.Name -match "GOPRO_MATCH_TOKEN" }
            if (!$goproDevices) { throw "找不到 GoPro 裝置，請確認 USB 已連線。" }
            
            $downloadedFiles = @()
            $errors = @()
            
            # 逐一處理每一台 connected 的 GoPro
            foreach ($gopro in $goproDevices) {
                try {
                    $storage = $gopro.GetFolder.Items() | Where-Object { $_.Name -match "GoPro MTP" -or $_.Name -match "Internal Storage" -or $_.Name -match "存儲" -or $_.Name -match "SD Card" }
                    if (!$storage) { continue }
                    
                    $dcim = $storage.GetFolder.Items() | Where-Object { $_.Name -eq "DCIM" }
                    if (!$dcim) { continue }
                    
                    $goproFolders = $dcim.GetFolder.Items() | Where-Object { $_.Name -match "GOPRO" }
                    
                    $cameraFiles = @()
                    foreach ($folderItem in $goproFolders) {
                        $folder = $folderItem.GetFolder
                        $dateIndices = @(4, 5, 10, 12)
                        
                        $files = $folderItem.GetFolder.Items() | Where-Object { $_.Name -like "*.MP4" }
                        foreach ($f in $files) {
                            $bestDateStr = ""
                            $sortKey = "00000000000000"
                            
                            foreach ($idx in $dateIndices) {
                                $tmp = $folder.GetDetailsOf($f, $idx).Replace("?", "").Trim()
                                if ($tmp -match "\d{4}") { 
                                    $bestDateStr = $tmp
                                    break 
                                }
                            }
                            
                            if ($bestDateStr) {
                                try {
                                    $dt = [datetime]$bestDateStr
                                    $sortKey = $dt.ToString("yyyyMMddHHmmss")
                                } catch {
                                    $matches = [regex]::Matches($bestDateStr, "\d+")
                                    if ($matches.Count -ge 5) {
                                        $year  = $matches[0].Value
                                        $month = $matches[1].Value.PadLeft(2, '0')
                                        $day   = $matches[2].Value.PadLeft(2, '0')
                                        $hour  = $matches[3].Value.PadLeft(2, '0')
                                        $min   = $matches[4].Value.PadLeft(2, '0')
                                        $sec   = if ($matches.Count -ge 6) { $matches[5].Value.PadLeft(2, '0') } else { "00" }
                                        if ($bestDateStr -match "下午|PM") {
                                            $h_int = [int]$hour
                                            if ($h_int -lt 12) { $hour = ($h_int + 12).ToString().PadLeft(2, '0') }
                                        } elseif ($bestDateStr -match "上午|AM") {
                                            if ($hour -eq "12") { $hour = "00" }
                                        }
                                        $sortKey = "$year$month$day$hour$min$sec"
                                    }
                                }
                            }
                            
                            $nameKey = $f.Name
                            $cameraFiles += [PSCustomObject]@{
                                Item    = $f
                                SortKey = $sortKey
                                NameKey = $nameKey
                                RawDate = $bestDateStr
                                Name    = $f.Name
                            }
                        }
                    }
                    
                    if ($cameraFiles.Count -eq 0) { continue }
                    
                    # 排序並找出此台相機的最新檔案
                    $latest = $cameraFiles | Sort-Object SortKey, NameKey -Descending | Select-Object -First 1
                    $latestFile = $latest.Item
                    
                    # 依相機裝置名稱建立子目錄，避免檔名衝突
                    $folderName = $gopro.Name -replace '[\\\\/:*?"<>|]', '_'
                    $destPath = Join-Path (Get-Location) "video_output\\$folderName"
                    if (!(Test-Path $destPath)) { New-Item -ItemType Directory -Path $destPath | Out-Null }
                    
                    $destFolder = $shell.Namespace($destPath)
                    $destFolder.CopyHere($latestFile, 16)
                    
                    # 等待檔案拷貝完成
                    $targetFile = Join-Path $destPath $latest.Name
                    $timeout = 0
                    while (!(Test-Path $targetFile) -and $timeout -lt 60) { 
                        Start-Sleep -Seconds 1 
                        $timeout++
                    }
                    
                    if (Test-Path $targetFile) {
                        $downloadedFiles += "$folderName\\$($latest.Name)"
                    } else {
                        $errors += "複製 $($latest.Name) 逾時"
                    }
                } catch {
                    $errors += "處理相機 $($gopro.Name) 時出錯: $($_.Exception.Message)"
                }
            }
            
            if ($downloadedFiles.Count -gt 0) {
                Write-Host "SUCCESS:$($downloadedFiles -join ',')"
            }
            if ($errors.Count -gt 0) {
                Write-Host "WARNINGS:$($errors -join ';')"
            }
            if ($downloadedFiles.Count -eq 0 -and $errors.Count -eq 0) {
                throw "在 GoPro 中找不到任何儲存媒體或 MP4 影片。"
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
                return True, f"USB 下載成功！檔案儲存於: {full_path}"
            else:
                return False, f"USB 失敗: {output}"
        except Exception as e:
            return False, f"USB 執行出錯: {e}"

    @asyncSlot()
    async def force_reset_gopro(self):
        self.log("正在執行 GoPro 硬重置連線...")
        self.btn_gopro_reset.setEnabled(False)
        self.btn_gopro_sleep.setEnabled(False)
        self.btn_gopro_poweroff.setEnabled(False)
        try:
            for gopro in self.gopro_clients:
                try: await gopro['client'].disconnect()
                except: pass
            self.gopro_clients.clear()
            await asyncio.sleep(1.0)
            await self.connect_gopro()
            self.log("GoPro 連線已重置")
        except Exception as e:
            self.log(f"重置失敗: {e}")
        self.btn_gopro_reset.setEnabled(True)

    @asyncSlot()
    async def sleep_all_gopro(self):
        connected_clients = [c for c in self.gopro_clients if c['client'].is_connected]
        if not connected_clients:
            self.log("❌ 沒有已連線的 GoPro 進行休眠")
            return
        
        self.log("正在發送 [休眠] 指令給所有連線的 GoPro...")
        self.btn_gopro_sleep.setEnabled(False)
        self.btn_gopro_poweroff.setEnabled(False)
        
        async def sleep_single(gopro):
            client = gopro['client']
            name = gopro['name']
            try:
                # 0x01, 0x05 is Sleep (keep BLE active)
                await client.write_gatt_char(GOPRO_COMMAND_UUID, bytearray([0x01, 0x05]), response=True)
                self.log(f"✅ 已送出休眠指令給 {name}")
                await asyncio.sleep(0.5)
                await client.disconnect()
                self.log(f"🔌 {name} 藍牙已中斷且進入休眠")
            except Exception as e:
                self.log(f"❌ {name} 休眠失敗: {e}")
                
        await asyncio.gather(*(sleep_single(c) for c in connected_clients), return_exceptions=True)
        
        # 清除連線狀態，因為相機已經休眠並中斷連線
        self.gopro_clients.clear()
        self.combo_ap_target.clear()
        self.combo_download_target.clear()
        self.combo_download_target.addItem("全部相機")
        self.btn_gopro_connect.setEnabled(True)
        self.btn_fetch_ap.setEnabled(False)
        self.btn_preview_gopro.setEnabled(False)
        self.btn_apply_settings.setEnabled(False)
        self.btn_download_wifi.setEnabled(False)
        self.btn_download_usb.setEnabled(False)
        self.check_ready_state()

    @asyncSlot()
    async def poweroff_all_gopro(self):
        connected_clients = [c for c in self.gopro_clients if c['client'].is_connected]
        if not connected_clients:
            self.log("❌ 沒有已連線的 GoPro 進行關機")
            return
        
        self.log("正在發送 [完全關機] 指令給所有連線的 GoPro...")
        self.btn_gopro_sleep.setEnabled(False)
        self.btn_gopro_poweroff.setEnabled(False)
        
        async def poweroff_single(gopro):
            client = gopro['client']
            name = gopro['name']
            try:
                # 0x01, 0x04 is Power Down (shut down BLE too)
                await client.write_gatt_char(GOPRO_COMMAND_UUID, bytearray([0x01, 0x04]), response=True)
                self.log(f"✅ 已送出關機指令給 {name}")
                await asyncio.sleep(0.5)
                await client.disconnect()
                self.log(f"🔌 {name} 藍牙已中斷且完全關機")
            except Exception as e:
                self.log(f"❌ {name} 關機失敗: {e}")
                
        await asyncio.gather(*(poweroff_single(c) for c in connected_clients), return_exceptions=True)
        
        # 清除連線狀態，因為相機已經關機並中斷連線
        self.gopro_clients.clear()
        self.combo_ap_target.clear()
        self.combo_download_target.clear()
        self.combo_download_target.addItem("全部相機")
        self.btn_gopro_connect.setEnabled(True)
        self.btn_fetch_ap.setEnabled(False)
        self.btn_preview_gopro.setEnabled(False)
        self.btn_apply_settings.setEnabled(False)
        self.btn_download_wifi.setEnabled(False)
        self.btn_download_usb.setEnabled(False)
        self.check_ready_state()

    def closeEvent(self, event):
        new_config = {
            "ap_ssid": self.input_ap_ssid.text(),
            "ap_pass": self.input_ap_pass.text()
        }
        save_config(new_config)
        self.xsens.cleanup()
        for gopro in self.gopro_clients:
            asyncio.create_task(gopro['client'].disconnect())
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = GoProXsensApp()
    window.show()
    with loop: loop.run_forever()
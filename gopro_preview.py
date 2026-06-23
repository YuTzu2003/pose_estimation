import time
import socket
import requests
import subprocess
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout
from PyQt5.QtGui import QImage, QPixmap

try:
    import cv2
except ImportError:
    cv2 = None

# ---------- GoPro Live Preview Thread & Dialog ----------

class GoProPreviewThread(QThread):
    frame_signal = pyqtSignal(QImage)
    status_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, ssid, password, app_instance):
        super().__init__()
        self.ssid = ssid
        self.password = password
        self.app = app_instance
        self.running = True

    def run(self):
        self.status_signal.emit("正在連線至相機 Wi-Fi...")
        success = self.connect_wifi_sync(self.ssid, self.password)
        if not success:
            self.status_signal.emit("❌ Wi-Fi 連線失敗。")
            self.finished_signal.emit()
            return

        self.status_signal.emit("等待 Windows 穩定連線 (10秒)...")
        for i in range(10):
            if not self.running:
                self.finished_signal.emit()
                return
            time.sleep(1)

        gopro_ip = self.app.get_gopro_gateway_ip()
        self.status_signal.emit(f"已連線！正在對接相機 IP: {gopro_ip}...")

        if cv2 is None:
            self.status_signal.emit("❌ 錯誤: 未安裝 opencv-python 庫。")
            self.finished_signal.emit()
            return

        # 發送啟動串流的 HTTP 請求
        try:
            url_start = f"http://{gopro_ip}:8080/gopro/camera/stream/start"
            requests.get(url_start, timeout=5)
            self.status_signal.emit(f"已啟動串流，開始讀取畫面...")
        except Exception as e:
            self.status_signal.emit(f"❌ 啟動串流失敗: {e}")
            self.finished_signal.emit()
            return

        # 啟動背景 keep-alive
        import threading
        keep_alive_event = threading.Event()
        
        def keep_alive_loop():
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            message = b"_GPHD_:0:0:2:0.000000\n"
            while not keep_alive_event.is_set():
                try:
                    udp_socket.sendto(message, (gopro_ip, 8554))
                except:
                    pass
                keep_alive_event.wait(2.0)
            udp_socket.close()

        ka_thread = threading.Thread(target=keep_alive_loop, daemon=True)
        ka_thread.start()

        # 開啟 UDP 串流
        stream_url = "udp://@0.0.0.0:8554?overrun_nonfatal=1&fifo_size=50000000"
        cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            self.status_signal.emit("❌ 無法開啟視訊串流，請重新嘗試。")
            keep_alive_event.set()
            ka_thread.join()
            self.finished_signal.emit()
            return

        self.status_signal.emit("預覽中 (HERO11 錄影時畫面會自動中斷)")
        
        while self.running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.03)
                continue
            
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            convert_to_Qt_format = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
            p = convert_to_Qt_format.scaled(640, 480, Qt.KeepAspectRatio)
            self.frame_signal.emit(p)

        cap.release()
        keep_alive_event.set()
        ka_thread.join()

        try:
            url_stop = f"http://{gopro_ip}:8080/gopro/camera/stream/stop"
            requests.get(url_stop, timeout=3)
        except:
            pass

        self.finished_signal.emit()

    def connect_wifi_sync(self, ssid, password):
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
            
            subprocess.run('netsh wlan disconnect', shell=True, capture_output=True)
            time.sleep(0.5)
            subprocess.run(f'netsh wlan add profile filename="{xml_path}"', shell=True, capture_output=True)
            time.sleep(0.5)
            subprocess.run(f'netsh wlan connect name="{ssid}"', shell=True, capture_output=True)
            
            if xml_path.exists():
                xml_path.unlink()
            return True
        except Exception as e:
            print(f"Error in connect_wifi_sync: {e}")
            return False

    def stop(self):
        self.running = False


class GoProPreviewWindow(QWidget):
    def __init__(self, ssid, password, original_ssid, app_instance):
        super().__init__()
        self.ssid = ssid
        self.password = password
        self.original_ssid = original_ssid
        self.app = app_instance
        
        self.setWindowTitle(f"GoPro 即時畫面預覽 - {ssid}")
        self.resize(700, 560)
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e24;
                color: #a6accd;
            }
            QLabel {
                color: #a6accd;
                font-family: 'Segoe UI', Arial;
            }
            QPushButton {
                background-color: #f44747;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #d83a3a;
            }
        """)

        layout = QVBoxLayout(self)

        self.video_label = QLabel("正在連線相機 Wi-Fi...", self)
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setStyleSheet("border: 2px dashed #3f3f46; background-color: #0d0d11; border-radius: 8px;")
        layout.addWidget(self.video_label)

        self.status_label = QLabel("狀態: 初始中...", self)
        self.status_label.setStyleSheet("font-size: 13px; color: #82aaff; font-weight: bold;")
        layout.addWidget(self.status_label)

        self.btn_close = QPushButton("關閉預覽", self)
        self.btn_close.clicked.connect(self.close)
        layout.addWidget(self.btn_close)

        self.thread = GoProPreviewThread(self.ssid, self.password, self.app)
        self.thread.frame_signal.connect(self.update_frame)
        self.thread.status_signal.connect(self.update_status)
        self.thread.finished_signal.connect(self.on_thread_finished)
        self.thread.start()

    def update_frame(self, image):
        self.video_label.setPixmap(QPixmap.fromImage(image))

    def update_status(self, text):
        self.status_label.setText(f"狀態: {text}")

    def on_thread_finished(self):
        self.update_status("預覽已結束。")

    def closeEvent(self, event):
        self.update_status("正在關閉預覽並清理資源...")
        self.thread.stop()
        self.thread.wait()
        
        if self.original_ssid:
            self.app.log(f"正在恢復原先的 Wi-Fi 連線: {self.original_ssid}...")
            import threading
            def reconnect():
                subprocess.run(f'netsh wlan connect name="{self.original_ssid}"', shell=True, capture_output=True)
            threading.Thread(target=reconnect, daemon=True).start()
            
        self.app.btn_preview_gopro.setEnabled(True)
        if hasattr(self.app, 'preview_windows') and self in self.app.preview_windows:
            self.app.preview_windows.remove(self)
        event.accept()

import csv
import time
import logging
from pathlib import Path
from threading import Lock

from PyQt5.QtCore import QThread, pyqtSignal

# Xsens SDK
try:
    import xsensdeviceapi as xda
except ImportError:
    xda = None

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
            self.log_signal.emit("Xsens SDK 未安裝。")
            return
        if self.mode == "discover":
            self._run_discovery()
        else:
            self._run_connect()

    def _run_discovery(self):
        try:
            self.log_signal.emit("開始掃描頻道 (11-25)，請確保感測器已開機...")
            self.control = xda.XsControl_construct()
            master_port = xda.XsScanner_scanPort("COM3", xda.XBR_Invalid)
            if master_port.empty():
                ports = xda.XsScanner_scanPorts()
                for p in ports:
                    if p.deviceId().isWirelessMaster() or p.deviceId().isAwindaXStation():
                        master_port = p
                        break
            if master_port.empty():
                self.log_signal.emit("找不到接收器。")
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
                self.log_signal.emit(f"在頻道 {found_channel} 找到感測器！")
                self.radio_channel = found_channel
                self.discovery_finished.emit(found_channel)
            else:
                self.log_signal.emit("掃描結束，未找到感測器。")
                self.discovery_finished.emit(-1)
        except Exception as e:
            self.log_signal.emit(f"掃描出錯: {e}")
            self.discovery_finished.emit(-1)

    def _run_connect(self):
        try:
            self.log_signal.emit(f"正在連線頻道 {self.radio_channel}...")
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
                self.log_signal.emit("找不到接收器。")
                self.connection_finished.emit(False)
                return
            if not self.control.openPort(master_port.portName(), master_port.baudrate()):
                self.log_signal.emit("無法開啟連接埠。")
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
                self.log_signal.emit("感測器連線逾時。")
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
            self.log_signal.emit(f"Xsens 錯誤: {str(e)}")
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
            self.log_signal.emit("Xsens 未連線，無法記錄。")
            return
        
        # 強制確保舊的執行緒已經結束
        if self.is_logging or (hasattr(self, 'logging_thread') and self.logging_thread.is_alive()):
            self.log_signal.emit("正在清理上一次錄製的資源，請稍候...")
            self.should_stop = True
            if hasattr(self, 'logging_thread'):
                self.logging_thread.join(timeout=2.0)
        
        # 徹底清空所有感測器的緩存，確保從這一刻開始抓新資料
        for cb in self.mtw_callbacks:
            cb.clear_buffer()

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
        
        # 進入迴圈前再次清空，確保絕對乾淨
        for cb in self.mtw_callbacks:
            cb.clear_buffer()

        try:
            output_dir = Path.cwd() / "xsens_output"
            output_dir.mkdir(exist_ok=True)
            
            time_str = time.strftime("%Y%m%d_%H%M%S")
            
            for cb in self.mtw_callbacks:
                fname = f"mtw_{cb.device.deviceId().toXsString()}_{time_str}.csv"
                full_path = output_dir / fname
                f = open(full_path, "w", newline="")
                w = csv.writer(f)
                w.writerow(["packet_counter", "timestamp_s", "q_w", "q_x", "q_y", "q_z",
                            "acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z",
                            "mag_x", "mag_y", "mag_z"])
                writers[cb.index] = w
                files[cb.index] = f
                packet_counts[cb.index] = 0
            
            self.log_signal.emit(f"[Xsens] 開始同步記錄 (共 {len(self.mtw_callbacks)} 個感測器)...")
            
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
                
                if time.time() - last_progress_update > 5:
                    status_msg = "記錄中: " + ", ".join([f"S{idx}: {count} 筆" for idx, count in packet_counts.items()])
                    self.log_signal.emit(status_msg)
                    last_progress_update = time.time()

                if not has_data:
                    time.sleep(0.001)
        except Exception as e:
            self.log_signal.emit(f"Xsens 記錄錯誤: {e}")
        finally:
            for f in files.values(): 
                try: f.close()
                except: pass
            self.is_logging = False
            self.log_signal.emit(f"Xsens 資料儲存完畢。")

    def stop_logging(self):
        self.should_stop = True
        if hasattr(self, 'logging_thread'):
            self.logging_thread.join(timeout=1.0)

    def cleanup(self):
        self.stop_logging()
        if self.master:
            self.master.gotoConfig()
            self.master.disableRadio()
        if self.control:
            self.control.close()

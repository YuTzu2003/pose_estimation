"""
Connect to Xsens MTw Awinda sensors via the Awinda USB Dongle / Station
- 包含自動頻道掃描 (Auto-Scan Channels 11-25)
- 包含開始前姿態歸零校正 (Orientation Reset)
"""

import sys
import time
import csv
from threading import Lock
import xsensdeviceapi as xda
import keyboard

# ---------- Callbacks (回呼函數，用來處理背景接收到的資料) ----------

class WirelessMasterCallback(xda.XsCallback):
    def __init__(self):
        super().__init__()
        self.connected_mtws = set()
        self.lock = Lock()

    def onConnectivityChanged(self, dev, new_state):
        with self.lock:
            if new_state == xda.XCS_Wireless:
                print(f"\n[+] MTw connected: {dev.deviceId().toXsString()}")
                self.connected_mtws.add(dev)
            elif new_state in (xda.XCS_Disconnected, xda.XCS_Rejected):
                print(f"\n[-] MTw disconnected: {dev.deviceId().toXsString()}")
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


# ---------- Main (主程式) ----------

def main():
    UPDATE_RATE = 100 # 更新頻率 (Hz)

    print("Creating XsControl...")
    control = xda.XsControl_construct()
    
    print("Scanning ports for Awinda master...")
    ports = xda.XsScanner_scanPorts()
    master_port = None
    for p in ports:
        if p.deviceId().isWirelessMaster() or p.deviceId().isAwindaXStation():
            master_port = p
            break
    if master_port is None:
        raise RuntimeError("找不到 Awinda 接收器，請確認已插入 USB。")

    print(f"Found master on {master_port.portName()} id={master_port.deviceId().toXsString()}")
    if not control.openPort(master_port.portName(), master_port.baudrate()):
        raise RuntimeError("無法開啟接收器連接埠。")
    
    master = control.device(master_port.deviceId())
    master.gotoConfig()
    
    master_cb = WirelessMasterCallback()
    master.addCallbackHandler(master_cb)

    supported = master.supportedUpdateRates()
    rate = UPDATE_RATE if UPDATE_RATE in [int(r) for r in supported] else int(supported[-1])
    master.setUpdateRate(rate)

    # ---------------------------------------------------------
    # 步驟 1：自動掃描頻道功能 (Auto-Scan Channels 11-25)
    # ---------------------------------------------------------
    print("\n==================================================")
    print("請現在將『右膝』感測器開機 (確認燈號閃爍)")
    print("程式即將開始自動掃描頻道 (11-25)...")
    print("==================================================\n")
    
    time.sleep(2) # 給使用者 2 秒鐘開機
    
    found_channel = None
    for channel in range(11, 26):
        print(f"正在測試頻道 {channel}...", end="\r")
        
        if master.isRadioEnabled():
            master.disableRadio()
        master.enableRadio(channel)
        
        # 每個頻道等待 1.5 秒看看感測器有沒有連上
        for _ in range(15):
            time.sleep(0.1)
            if len(master_cb.get_wireless_mtws()) > 0:
                found_channel = channel
                break
                
        if found_channel:
            break
            
    if not found_channel:
        print("\n\n[失敗] 掃描了所有頻道 (11-25)，但沒有找到感測器。")
        print("請確認感測器是否有電、是否已開機閃燈，然後再試一次。")
        master.disableRadio()
        control.closePort(master_port.portName())
        control.close()
        return

    print(f"\n[成功] 在頻道 {found_channel} 找到感測器並已連線！")

    # ---------------------------------------------------------
    # 步驟 2：準備進入量測模式
    # ---------------------------------------------------------
    print("\n按『空白鍵 (SPACE)』準備進入量測模式...")
    while True:
        if keyboard.is_pressed("space"):
            break
        time.sleep(0.1)

    mtws = master_cb.get_wireless_mtws()
    mtw_callbacks = []
    for i, mtw in enumerate(mtws):
        cb = MtwCallback(i, mtw)
        mtw.addCallbackHandler(cb)
        mtw_callbacks.append(cb)

    # 正式進入量測模式
    master.gotoMeasurement()

    # ---------------------------------------------------------
    # 步驟 3：方向歸零校正 (Orientation Reset)
    # ---------------------------------------------------------
    print("\n==================================================")
    print("【準備進行方向歸零 (Alignment Reset)】")
    print("請將感測器放置在您想定義為『原點/零度』的姿勢，並保持靜止。")
    print("準備好後，請按『 Enter 鍵 』進行校正...")
    print("==================================================")
    
    # 等待使用者擺好姿勢並按下 Enter
    while True:
        if keyboard.is_pressed("enter"):
            break
        time.sleep(0.1)

    # 執行歸零動作 (將三軸的旋轉都設為 0)
    for mtw in mtws:
        if mtw.resetOrientation(xda.XRM_Alignment):
            print(f"[成功] 感測器 {mtw.deviceId().toXsString()} 已歸零！")
        else:
            print(f"[失敗] 感測器 {mtw.deviceId().toXsString()} 歸零失敗。")
            
    time.sleep(1) # 給系統 1 秒鐘緩衝時間套用設定

    # ---------------------------------------------------------
    # 步驟 4：建立 CSV 檔案並開始記錄
    # ---------------------------------------------------------
    writers = {}
    files   = {}
    for cb in mtw_callbacks:
        fname = f"mtw_{cb.device.deviceId().toXsString()}.csv"
        f = open(fname, "w", newline="")
        w = csv.writer(f)
        w.writerow(["packet_counter", "timestamp_s", "q_w", "q_x", "q_y", "q_z",
                    "acc_x", "acc_y", "acc_z", "gyr_x", "gyr_y", "gyr_z",
                    "mag_x", "mag_y", "mag_z"])
        writers[cb.index] = w
        files[cb.index]   = f

    print("\n==================================================")
    print("記錄中... 按『ESC 鍵』停止並存檔。")
    print("==================================================")
    
    try:
        while not keyboard.is_pressed("esc"):
            for cb in mtw_callbacks:
                packet = cb.pop_oldest()
                if packet is None:
                    continue
                q   = packet.orientationQuaternion()
                acc = packet.calibratedAcceleration()
                gyr = packet.calibratedGyroscopeData()
                mag = packet.calibratedMagneticField()
                writers[cb.index].writerow([
                    packet.packetCounter(),
                    packet.sampleTimeFine() / 10000.0,
                    q[0], q[1], q[2], q[3],
                    acc[0], acc[1], acc[2],
                    gyr[0], gyr[1], gyr[2],
                    mag[0], mag[1], mag[2],
                ])
            time.sleep(0.001)
    finally:
        # ---------------------------------------------------------
        # 步驟 5：結束並清理資源
        # ---------------------------------------------------------
        print("\n正在停止並儲存檔案...")
        for f in files.values():
            f.close()
        master.gotoConfig()
        master.disableRadio()
        control.closePort(master_port.portName())
        control.close()
        print(f"完成！資料已儲存為 CSV 檔。")

if __name__ == "__main__":
    main()
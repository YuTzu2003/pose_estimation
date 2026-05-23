"""
Connect to Xsens MTw Awinda sensors via the Awinda USB Dongle / Station
- Hardcoded COM3 (Fast USB Connect)
- Hardcoded Radio Channel 16 (Fast Wireless Connect)
- Orientation Reset (Enter)
- Start Recording (Space)
- Flush Buffer & Relative Timestamp
"""

import sys
import time
import csv
from threading import Lock
import xsensdeviceapi as xda
import keyboard

# ---------- Callbacks ----------

class WirelessMasterCallback(xda.XsCallback):
    def __init__(self):
        super().__init__()
        self.connected_mtws = set()
        self.lock = Lock()

    def onConnectivityChanged(self, dev, new_state):
        with self.lock:
            if new_state == xda.XCS_Wireless:
                print(f"\n[+] Connected: {dev.deviceId().toXsString()}")
                self.connected_mtws.add(dev)
            elif new_state in (xda.XCS_Disconnected, xda.XCS_Rejected):
                print(f"\n[-] Disconnected: {dev.deviceId().toXsString()}")
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


# ---------- Main ----------

def main():
    UPDATE_RATE = 100 # Hz
    RADIO_CHANNEL = 18 # ★ 直接鎖定您的感測器頻道！ ★

    print("Init XsControl...")
    control = xda.XsControl_construct()
    
    # ---------------------------------------------------------
    # 1. 瞬間連線接收器 (COM3)
    # ---------------------------------------------------------
    print("Connecting to COM3...")
    master_port = xda.XsScanner_scanPort("COM3", xda.XBR_Invalid)
    
    if master_port.empty() or not (master_port.deviceId().isWirelessMaster() or master_port.deviceId().isAwindaXStation()):
        raise RuntimeError("[Error] Master not found on COM3.")

    print(f"Master found: {master_port.portName()}")
    if not control.openPort(master_port.portName(), master_port.baudrate()):
        raise RuntimeError("Failed to open port.")

    master = control.device(master_port.deviceId())
    master.gotoConfig()
    
    master_cb = WirelessMasterCallback()
    master.addCallbackHandler(master_cb)
    
    supported = master.supportedUpdateRates()
    master.setUpdateRate(UPDATE_RATE if UPDATE_RATE in [int(r) for r in supported] else int(supported[-1]))

    # ---------------------------------------------------------
    # 2. 瞬間連線感測器 (固定頻道 16)
    # ---------------------------------------------------------
    print(f"\nEnabling radio on CH {RADIO_CHANNEL}...")
    if master.isRadioEnabled():
        master.disableRadio()
    master.enableRadio(RADIO_CHANNEL)

    print("Waiting for sensor to connect (Make sure it is ON)...")
    while True:
        if len(master_cb.get_wireless_mtws()) > 0:
            break
        time.sleep(0.1)

    print("[OK] Sensor is ready!")

    # ---------------------------------------------------------
    # Step 3: Measurement Mode & Reset
    # ---------------------------------------------------------
    mtws = master_cb.get_wireless_mtws()
    mtw_callbacks = []
    for i, mtw in enumerate(mtws):
        cb = MtwCallback(i, mtw)
        mtw.addCallbackHandler(cb)
        mtw_callbacks.append(cb)

    master.gotoMeasurement()

    print("\n==================================================")
    print("Step 1: Alignment Reset")
    print("Stand still and press [ENTER] to reset...")
    print("==================================================")
    
    while True:
        if keyboard.is_pressed("enter"):
            break
        time.sleep(0.1)

    for mtw in mtws:
        if mtw.resetOrientation(xda.XRM_Alignment):
            print(f"[OK] {mtw.deviceId().toXsString()} reset.")
        else:
            print(f"[Fail] {mtw.deviceId().toXsString()} reset failed.")
            
    time.sleep(1) 

    # ---------------------------------------------------------
    # Step 4: Start Recording
    # ---------------------------------------------------------
    print("\n==================================================")
    print("Step 2: Start Recording")
    print("Ready! Press [SPACE] to start recording...")
    print("==================================================")
    
    time.sleep(0.5) 
    while True:
        if keyboard.is_pressed("space"):
            break
        time.sleep(0.1)

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

    for cb in mtw_callbacks:
        cb.clear_buffer()

    print("\n🔴 [Recording] Press [ESC] to stop.")
    start_counters = {}

    try:
        while not keyboard.is_pressed("esc"):
            for cb in mtw_callbacks:
                packet = cb.pop_oldest()
                if packet is None:
                    continue
                
                current_counter = packet.packetCounter()
                
                if cb.index not in start_counters:
                    start_counters[cb.index] = current_counter
                
                timestamp_s = (current_counter - start_counters[cb.index]) / float(UPDATE_RATE)

                q   = packet.orientationQuaternion()
                acc = packet.freeAcceleration() 
                gyr = packet.calibratedGyroscopeData()
                mag = packet.calibratedMagneticField()
                
                # 根據用戶需求：X 和 Y 測出來是相反的，在此進行對調
                writers[cb.index].writerow([
                    current_counter,
                    f"{timestamp_s:.3f}",
                    q[0], q[2], q[1], q[3], # 四元數 X, Y 對調
                    acc[1], acc[0], acc[2], # 加速度 X, Y 對調
                    gyr[1], gyr[0], gyr[2], # 角速度 X, Y 對調
                    mag[1], mag[0], mag[2], # 磁力計 X, Y 對調
                ])
            time.sleep(0.001)
    finally:
        print("\nStopping...")
        for f in files.values():
            f.close()
        master.gotoConfig()
        master.disableRadio()
        control.closePort(master_port.portName())
        control.close()
        print("Done. CSV saved.")

if __name__ == "__main__":
    main()
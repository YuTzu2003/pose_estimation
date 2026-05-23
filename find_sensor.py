"""
Find Xsens Awinda Master Channel - Revised Version
"""
import xsensdeviceapi as xda
import time
from threading import Lock

class ScanCallback(xda.XsCallback):
    def __init__(self):
        super().__init__()
        self.found = False
        self.lock = Lock()

    def onConnectivityChanged(self, dev, new_state):
        if new_state == xda.XCS_Wireless:
            with self.lock:
                self.found = True

def find_sensor():
    print("Scanning for Xsens Awinda Master...")
    ports = xda.XsScanner_scanPorts()
    master_port = None
    for p in ports:
        if p.deviceId().isWirelessMaster() or p.deviceId().isAwindaXStation():
            master_port = p
            break
            
    if master_port is None:
        print("[-] Master not found.")
        return

    print(f"[+] Found Master on: {master_port.portName()}")
    
    control = xda.XsControl_construct()
    control.openPort(master_port.portName(), master_port.baudrate())
    master = control.device(master_port.deviceId())
    master.gotoConfig()

    cb = ScanCallback()
    master.addCallbackHandler(cb)

    print("[*] Scanning Radio Channels (11-25)... Turn ON your sensor.")
    for channel in range(11, 26):
        print(f"Testing CH {channel}...", end="\r")
        master.disableRadio()
        master.enableRadio(channel)
        
        # 等待連線
        for _ in range(20):
            time.sleep(0.1)
            if cb.found:
                print(f"\n[!!!] FOUND SENSOR on Channel: {channel}")
                control.close()
                return
    
    print("\n[-] Sensor not found.")
    control.close()

if __name__ == "__main__":
    find_sensor()
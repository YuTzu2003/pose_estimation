import sys
import time
import csv
import threading
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import xsensdeviceapi as xda

# ========================================================
# 📊 Xsens 數據擷取與可視化工具
# ========================================================
# 用途: 
# 1. 連線 Xsens 感測器
# 2. 按 Enter 開始/停止錄製原始 Acc 數據
# 3. 儲存為 CSV 並自動產生折線圖
# ========================================================

class XsensLogger(xda.XsCallback):
    def __init__(self):
        super().__init__()
        self.data_buffer = []
        self.is_recording = False
        self.lock = threading.Lock()

    def onLiveDataAvailable(self, dev, packet):
        if self.is_recording and packet.containsCalibratedData():
            acc = packet.calibratedAcceleration()
            with self.lock:
                self.data_buffer.append({
                    "timestamp": time.time(),
                    "acc_x": acc[0],
                    "acc_y": acc[1],
                    "acc_z": acc[2]
                })

def run_diagnostic():
    print("🚀 啟動 Xsens 診斷工具...")
    control = xda.XsControl_construct()
    
    # 1. 搜尋設備
    ports = xda.XsScanner_scanPorts()
    master_port = next((p for p in ports if p.deviceId().isWirelessMaster() or p.deviceId().isAwindaXStation()), None)
    
    if not master_port:
        print("❌ 找不到接收器！")
        return

    control.openPort(master_port.portName(), master_port.baudrate())
    master = control.device(master_port.deviceId())
    master.gotoConfig()

    # --- 新增：設定更新頻率為 120Hz ---
    supported_rates = master.supportedUpdateRates()
    target_rate = 120
    if target_rate in [int(r) for r in supported_rates]:
        master.setUpdateRate(target_rate)
        print(f"✅ 更新頻率已設定為: {target_rate} Hz")
    else:
        actual_rate = int(supported_rates[-1])
        master.setUpdateRate(actual_rate)
        print(f"⚠️ 硬體不支援 {target_rate}Hz，已設定為支援的最大頻率: {actual_rate} Hz")
    # --------------------------------

    master.enableRadio(18) # 預設頻道 18

    print("等待感測器連入...")
    while master.childCount() == 0:
        time.sleep(0.1)
    
    mtw = master.children()[0] # 僅測試第一個找到的感測器
    dev_id = mtw.deviceId().toXsString()
    print(f"✅ 已連線感測器: {dev_id}")

    callback = XsensLogger()
    mtw.addCallbackHandler(callback)
    master.gotoMeasurement()

    # --- 新增：重置歸零 ---
    print("\n💡 正在執行方向歸零 (Alignment Reset)... 請將感測器靜置於平面上。")
    time.sleep(1) # 等待進入測量模式穩定
    if mtw.resetOrientation(xda.XRM_Alignment):
        print("✅ 歸零成功！")
    else:
        print("⚠️ 歸零失敗，將使用原始座標系。")
    # ---------------------

    # 2. 錄製控制邏輯
    input("\n按 [Enter] 鍵開始錄製數據...")
    callback.is_recording = True
    start_time = time.time()
    print(f"🔴 正在錄製 {dev_id} 的數據... (請進行特定方向的物理移動)")
    
    input("按 [Enter] 鍵停止錄製並產生圖表...")
    callback.is_recording = False
    
    # 3. 資料處理與儲存
    if not callback.data_buffer:
        print("❌ 未收到任何數據！")
        return

    df = pd.DataFrame(callback.data_buffer)
    df['time_offset'] = df['timestamp'] - start_time
    
    csv_name = f"diagnostic_{dev_id}.csv"
    df.to_csv(csv_name, index=False)
    print(f"💾 數據已儲存至: {csv_name}")

    # 4. 自動產生折線圖
    print("📊 正在產生折線圖...")
    plt.figure(figsize=(12, 6))
    plt.plot(df['time_offset'], df['acc_x'], label='Acc X (Long side)', color='red')
    plt.plot(df['time_offset'], df['acc_y'], label='Acc Y (Short side)', color='green')
    plt.plot(df['time_offset'], df['acc_z'], label='Acc Z (Vertical)', color='blue')
    
    plt.title(f"Xsens Accelerometer Calibration Test - {dev_id}")
    plt.xlabel("Time (seconds)")
    plt.ylabel("Acceleration (m/s²)")
    plt.legend()
    plt.grid(True)
    
    chart_name = f"chart_{dev_id}.png"
    plt.savefig(chart_name)
    print(f"🖼️ 圖表已儲存至: {chart_name}")
    
    # 嘗試開啟圖表視窗
    print("💡 正在開啟圖表視窗，請查看...")
    plt.show()

    master.gotoConfig()
    control.close()

if __name__ == "__main__":
    run_diagnostic()

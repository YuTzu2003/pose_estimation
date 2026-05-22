import pandas as pd
from scipy.signal import find_peaks, peak_prominences, savgol_filter
import os

def peak_smooth(csv_path, output_peaks_path):
    """
    從骨幹分析 CSV 中提取腳踝座標，平滑處理後檢測波峰 (腳著地時刻)
    :param csv_path: 骨幹分析 CSV 路徑
    :param output_peaks_path: 輸出波峰 CSV 路徑
    """
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return False

    # 讀取 CSV 文件
    data = pd.read_csv(csv_path)

    # 提取所需欄位 (對應 pose_angle_track.py 的輸出)
    frames = data['Frame']
    right_y_values = data['Right_Ankle_Y']
    right_x_values = data['Right_Ankle_X']
    left_y_values = data['Left_Ankle_Y']
    left_x_values = data['Left_Ankle_X']

    # 使用 Savitzky-Golay 濾波器平滑數據
    window_length = 11  # 濾波窗口大小，必須為奇數
    if len(data) < window_length:
        window_length = len(data) if len(data) % 2 != 0 else len(data) - 1
    
    if window_length < 5:
        print("Data too short for smoothing.")
        return False

    polyorder = 3       # 多項式階數

    smoothed_right_y_values = savgol_filter(right_y_values, window_length, polyorder)
    smoothed_left_y_values = savgol_filter(left_y_values, window_length, polyorder)

    # 檢測右腳波峰 (腳踝 Y 座標最大值通常代表著地/最低點)
    right_peaks, _ = find_peaks(smoothed_right_y_values)
    right_prominences = peak_prominences(smoothed_right_y_values, right_peaks)[0]
    right_valid_peaks = right_peaks[right_prominences > 20]  # 顯著性閾值可調整

    # 檢測左腳波峰
    left_peaks, _ = find_peaks(smoothed_left_y_values)
    left_prominences = peak_prominences(smoothed_left_y_values, left_peaks)[0]
    left_valid_peaks = left_peaks[left_prominences > 20]

    # 提取右腳有效波峰的幀數、X、Y 座標
    right_peak_data = pd.DataFrame({
        'Frame_Right': frames.iloc[right_valid_peaks].values,
        'X_Right': right_x_values.iloc[right_valid_peaks].values,
        'Y_Right': smoothed_right_y_values[right_valid_peaks]
    })

    # 提取左腳有效波峰的幀數、X、Y 座標
    left_peak_data = pd.DataFrame({
        'Frame_Left': frames.iloc[left_valid_peaks].values,
        'X_Left': left_x_values.iloc[left_valid_peaks].values,
        'Y_Left': smoothed_left_y_values[left_valid_peaks]
    })

    # 合併左右腳波峰數據
    peak_data = pd.concat([right_peak_data.reset_index(drop=True), left_peak_data.reset_index(drop=True)], axis=1)
    peak_data.to_csv(output_peaks_path, index=False)

    print(f"Valid peaks saved to {output_peaks_path}")
    return True

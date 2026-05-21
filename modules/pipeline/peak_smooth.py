import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import find_peaks, peak_prominences, savgol_filter
import cv2
import pandas as pd
import numpy as np

def peak_smmoth():
    # 讀取 CSV 文件
    file_path = 'ankle_with_angles.csv'
    data = pd.read_csv(file_path)

    # 提取所需欄位
    frames = data['Frame']
    right_y_values = data['Right_Ankle_Y']
    right_x_values = data['Right_Ankle_X']
    left_y_values = data['Left_Ankle_Y']
    left_x_values = data['Left_Ankle_X']

    # 使用 Savitzky-Golay 濾波器平滑數據
    window_length = 11  # 濾波窗口大小，必須為奇數
    polyorder = 3       # 多項式階數

    smoothed_right_y_values = savgol_filter(right_y_values, window_length, polyorder)
    smoothed_left_y_values = savgol_filter(left_y_values, window_length, polyorder)

    # 檢測右腳波峰
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

    # 合併左右腳波峰數據，按需要保存
    peak_data = pd.concat([right_peak_data, left_peak_data], axis=1)
    peak_data.to_csv('valid_peaks.csv', index=False)

    print("有效波峰已保存至 'valid_peaks.csv'")

def step_time():
    # 讀取波峰資訊
    csv_file = 'valid_peaks.csv'
    peak_data = pd.read_csv(csv_file)

    # 合併左右腳的標記，並按幀數排序
    all_peaks = []
    if 'Frame_Right' in peak_data and 'X_Right' in peak_data:
        all_peaks.extend([(row['Frame_Right'], row['X_Right'], 'Right') for _, row in peak_data.iterrows() if not pd.isna(row['Frame_Right'])])
    if 'Frame_Left' in peak_data and 'X_Left' in peak_data:
        all_peaks.extend([(row['Frame_Left'], row['X_Left'], 'Left') for _, row in peak_data.iterrows() if not pd.isna(row['Frame_Left'])])
    all_peaks.sort(key=lambda x: x[0])  # 按幀數排序

    # 影片路徑
    input_video = 'step_tracking.mp4'
    output_video = 'pose_with_intervals.mp4'

    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        print('Error: Unable to open video file.')
        exit()

    # 影片屬性
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 初始化影片寫入器
    out = cv2.VideoWriter(output_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (frame_width, frame_height))

    # 創建持久化畫布
    persistent_canvas = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)

    # 初始化變數
    last_peak_frame = None

    frame_count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # 檢查當前幀是否有標記
        for peak_frame, x, label in all_peaks:
            if frame_count == peak_frame:
                x = int(x)
                # 繪製垂直線
                color = (0, 0, 255) if label == 'Right' else (0, 255, 0)  # 右腳紅色，左腳綠色
                cv2.line(persistent_canvas, (x, 0), (x, frame_height), color, 2)

                # 計算並顯示時間間隔
                if last_peak_frame is not None:
                    interval = (frame_count - last_peak_frame) / fps  # 計算時間間隔
                    text = f'{interval:.2f}s'
                    cv2.putText(persistent_canvas, text, (x + 10, round(frame_height // 2 * 1.4)), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  # 黃色文字顯示間隔
                last_peak_frame = frame_count

        # 疊加畫布到當前幀
        overlay_frame = cv2.addWeighted(frame, 1.0, persistent_canvas, 0.7, 0)

        # 寫入處理後的幀
        out.write(overlay_frame)
        frame_count += 1

    cap.release()
    out.release()
    print(f"Processed video saved as: {output_video}")
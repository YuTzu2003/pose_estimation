import cv2
import pandas as pd
import numpy as np
import os

def run_step(input_video, peaks_csv, output_video, ratio=1.0, person_records=None, progress_callback=None):
    csv_file = peaks_csv
    peak_data = pd.read_csv(csv_file)

    # 合併左右腳的標記，並按幀數排序
    all_peaks = []
    if 'Frame_Right' in peak_data and 'X_Right' in peak_data:
        all_peaks.extend([(row['Frame_Right'], row['X_Right'], 'Right') for _, row in peak_data.iterrows() if not pd.isna(row['Frame_Right'])])
    if 'Frame_Left' in peak_data and 'X_Left' in peak_data:
        all_peaks.extend([(row['Frame_Left'], row['X_Left'], 'Left') for _, row in peak_data.iterrows() if not pd.isna(row['Frame_Left'])])
    all_peaks.sort(key=lambda x: x[0])  # 按幀數排序

    # 如果有提供人體偵測區間，則進行幀數轉換
    if person_records:
        valid_frames = []
        for start, end in person_records:
            valid_frames.extend(range(start, end + 1))
        
        mapped_peaks = []
        for pf, x, label in all_peaks:
            try:
                # 找出原始幀數在輸出影片中的索引
                idx = valid_frames.index(pf)
                mapped_peaks.append((idx, x, label))
            except ValueError:
                continue
        all_peaks = mapped_peaks

    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        print(f'Error: Unable to open video file {input_video}.')
        return None

    # 影片屬性
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 初始化影片寫入器 (優先使用 avc1)
    fourccs = ['avc1', 'mp4v', 'XVID']
    out = None
    for fcc in fourccs:
        fourcc = cv2.VideoWriter_fourcc(*fcc)
        out = cv2.VideoWriter(output_video, fourcc, fps, (frame_width, frame_height))
        if out.isOpened():
            print(f"Successfully opened VideoWriter with codec: {fcc}")
            break
            
    if out is None or not out.isOpened():
        out = cv2.VideoWriter(output_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (frame_width, frame_height))

    # 創建持久化畫布
    persistent_canvas = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)

    # 初始化變數
    last_peak = None # (frame, x, label)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
            
        if progress_callback and frame_count % 10 == 0:
            percent = (frame_count / total_frames) * 100
            progress_callback(percent, f"正在生成步頻分析影片 (幀 {frame_count}/{total_frames})")

        # 檢查當前幀是否有標記
        for peak_frame, x, label in all_peaks:
            if frame_count == peak_frame:
                x = int(x)
                # 繪製垂直線
                color = (0, 0, 255) if label == 'Right' else (0, 255, 0)  # 右腳紅色，左腳綠色
                cv2.line(persistent_canvas, (x, 0), (x, frame_height), color, 2)

                # 計算並顯示時間間隔、步幅與速度
                if last_peak is not None:
                    last_frame, last_x, last_label = last_peak
                    
                    # 1. 時間間隔 (每一對波峰都顯示)
                    interval = (frame_count - last_frame) / fps
                    text_time = f'{interval:.2f}s'
                    cv2.putText(persistent_canvas, text_time, (x + 10, round(frame_height // 2 * 1.4)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

                    # 2. 步幅與速度 (只有左右腳切換時才計算)
                    if label != last_label:
                        stride_px = abs(x - last_x)
                        stride_m = stride_px * ratio
                        
                        mid_x = (x + last_x) // 2
                        
                        # 顯示步幅 (黃色)
                        text_stride = f'{stride_m:.2f}m'
                        cv2.putText(persistent_canvas, text_stride, (mid_x - 40, frame_height // 2 + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                        
                        # 顯示速度 (白色)
                        if interval > 0:
                            speed = stride_m / interval
                            text_speed = f'{speed:.2f} m/s'
                            cv2.putText(persistent_canvas, text_speed, (mid_x - 40, frame_height // 2 + 70), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)

                last_peak = (frame_count, x, label)

        # 疊加畫布到當前幀
        overlay_frame = cv2.addWeighted(frame, 1.0, persistent_canvas, 0.7, 0)

        # 寫入處理後的幀
        out.write(overlay_frame)
        frame_count += 1

    cap.release()
    out.release()
    print(f"Processed video saved as: {output_video}")
    return os.path.basename(output_video)


def run_frequency_speed(input_video, peaks_csv, output_video, Reference_Distance, img_pixel):
    pixel_to_meter_ratio = Reference_Distance/img_pixel  

    # 讀取波峰資訊
    csv_file = peaks_csv
    peak_data = pd.read_csv(csv_file)

    # 合併左右腳的標記，並按幀數排序
    all_peaks = []
    if 'Frame_Right' in peak_data and 'X_Right' in peak_data:
        all_peaks.extend([(row['Frame_Right'], row['X_Right'], 'Right') for _, row in peak_data.iterrows() if not pd.isna(row['Frame_Right'])])
    if 'Frame_Left' in peak_data and 'X_Left' in peak_data:
        all_peaks.extend([(row['Frame_Left'], row['X_Left'], 'Left') for _, row in peak_data.iterrows() if not pd.isna(row['Frame_Left'])])
    all_peaks.sort(key=lambda x: x[0])  # 按幀數排序

    cap = cv2.VideoCapture(input_video)
    if not cap.isOpened():
        print(f'Error: Unable to open video file {input_video}.')
        return None

    # 影片屬性
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 初始化影片寫入器
    out = cv2.VideoWriter(output_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (frame_width, frame_height))


    # 創建持久化畫布
    persistent_canvas = np.zeros((frame_height, frame_width, 3), dtype=np.uint8)

    # 初始化變數
    last_peak = None  # 記錄上一個標記（包含幀數和 X 座標）

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

                # 計算步幅和速度
                if last_peak is not None:
                    last_frame, last_x, last_label = last_peak
                    if label != last_label:  # 只有左右腳切換時才計算
                        # 計算步幅（真實距離）
                        stride_length_px = abs(x - last_x)  # 像素步幅
                        stride_length_m = stride_length_px * pixel_to_meter_ratio 

                        # 計算時間間隔
                        time_interval = (frame_count - last_frame) / fps  # 時間間隔

                        # 設置文字顯示位置
                        mid_x = (x + last_x) // 2  

                        # 計算速度
                        if time_interval > 0:
                            speed = stride_length_m / time_interval  # 速度 = 距離 / 時間
                            text_speed = f'{speed:.2f} m/s'
                            mid_y_speed = frame_height // 2 + 60
                            cv2.putText(persistent_canvas, text_speed, (mid_x, mid_y_speed), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  # 白色文字顯示速度

                        # 顯示步幅
                        text_stride = f'{stride_length_m:.2f}m'
                        mid_y_stride = frame_height // 2 + 30
                        cv2.putText(persistent_canvas, text_stride, (mid_x, mid_y_stride), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)  # 黃色文字顯示步幅

                last_peak = (frame_count, x, label)

        # 疊加畫布到當前幀
        overlay_frame = cv2.addWeighted(frame, 1.0, persistent_canvas, 0.7, 0)

        # 寫入處理後的幀
        out.write(overlay_frame)
        frame_count += 1

    cap.release()
    out.release()
    print(f"Processed video saved as: {output_video}")
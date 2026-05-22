import cv2
import pandas as pd
import numpy as np
import os

def run_step(input_video, peaks_csv, output_video, ratio=1.0, person_records=None):
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
    return os.path.basename(output_video)
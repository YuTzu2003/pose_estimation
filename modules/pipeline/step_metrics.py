import cv2
import pandas as pd
import numpy as np

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


def Step_frequency():
    import cv2
    import pandas as pd
    import numpy as np

    pixel_to_meter_ratio = shoes_length/img_pixel  

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
    output_video = 'pose_with_real_stride_lengths.mp4'

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

                # 計算真實步幅
                if last_peak is not None:
                    last_frame, last_x, last_label = last_peak
                    if label != last_label:  # 只有左右腳切換時才計算步幅
                        stride_length_px = abs(x - last_x)  # 計算像素步幅
                        stride_length_m = stride_length_px * pixel_to_meter_ratio  # 換算為真實距離(比例尺)
                        text = f'{stride_length_m:.2f}m'
                        mid_x = (x + last_x) // 2  # 設置文字顯示位置
                        mid_y = frame_height // 2 + 30
                        cv2.putText(persistent_canvas, text, (mid_x, mid_y), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)  # 黃色文字顯示真實步幅

                last_peak = (frame_count, x, label)

        # 疊加畫布到當前幀
        overlay_frame = cv2.addWeighted(frame, 1.0, persistent_canvas, 0.7, 0)

        # 寫入處理後的幀
        out.write(overlay_frame)
        frame_count += 1

    cap.release()
    out.release()
    print(f"Processed video saved as: {output_video}")


def speed():
    import cv2
    import pandas as pd
    import numpy as np

    pixel_to_meter_ratio = shoes_length/img_pixel

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
    output_video = 'pose_with_speed.mp4'

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
                        stride_length_m = stride_length_px * pixel_to_meter_ratio  # 換算為真實距離(比例尺)

                        # 計算時間間隔
                        time_interval = (frame_count - last_frame) / fps  # 時間間隔

                        # 計算速度
                        if time_interval > 0:
                            speed = stride_length_m / time_interval  # 速度 = 距離 / 時間
                            text_speed = f'{speed:.2f} m/s'
                            mid_x = (x + last_x) // 2  # 設置文字顯示位置
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
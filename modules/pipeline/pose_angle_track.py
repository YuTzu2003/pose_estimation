import cv2
import time
import torch
import numpy as np
import os
import csv
from torchvision import transforms
from utils.datasets import letterbox
from utils.plots import output_to_keypoint, plot_skeleton_kpts
from utils.general import non_max_suppression_kpt
from modules.pipeline.backbone_detect import load_model
from modules.pipeline.video_compat import make_ios_playable_mp4

# 計算三點形成的角度
def calculate_angle(a, b, c):
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)
    ab = a - b
    cb = c - b
    cosine_angle = np.dot(ab, cb) / (np.linalg.norm(ab) * np.linalg.norm(cb))
    angle = np.arccos(np.clip(cosine_angle, -1.0, 1.0))
    return np.degrees(angle)

def draw_history_points(image, points_list, color, radius=3):
    for pt in points_list:
        cv2.circle(image, pt, radius, color, -1)

@torch.no_grad()
def run_pose_analysis(source_path, output_dir, record_id, person_records, enable_track=False, progress_callback=None):
    """
    執行骨幹分析與關鍵點追蹤
    :param source_path: 原始影片路徑
    :param output_dir: 輸出目錄
    :param record_id: 紀錄 ID
    :param person_records: 人體偵測到的區間 [(start, end), ...]
    :param enable_track: 是否啟用關鍵點追蹤
    :param progress_callback: 進度回呼函數
    """
    model, device = load_model()
    cap = cv2.VideoCapture(source_path)
    
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # 建立輸出影片 (使用 avc1 確保網頁可播放)
    result_video_filename = f"{record_id}_pose.mp4"
    result_video_path = os.path.join(output_dir, result_video_filename)
    
    # 嘗試多種 FourCC 格式
    fourccs = ['avc1', 'mp4v', 'XVID', 'MJPG']
    out = None
    for fcc in fourccs:
        ext = 'mp4' if fcc in ['avc1', 'mp4v'] else 'avi'
        test_path = result_video_path if ext == 'mp4' else result_video_path.replace('.mp4', '.avi')
        fourcc = cv2.VideoWriter_fourcc(*fcc)
        out = cv2.VideoWriter(test_path, fourcc, fps, (width, height))
        if out.isOpened():
            print(f"Successfully opened VideoWriter with codec: {fcc}")
            if ext == 'avi':
                result_video_filename = result_video_filename.replace('.mp4', '.avi')
                result_video_path = test_path
            break
    
    if out is None or not out.isOpened():
        print("Error: Could not open VideoWriter with any supported codec.")
        # 最後一搏：使用不帶 FourCC 的方式 (讓 OpenCV 自己決定)
        out = cv2.VideoWriter(result_video_path, -1, fps, (width, height))

    # CSV 檔案
    csv_filename = f"{record_id}_pose.csv"
    csv_path = os.path.join(output_dir, csv_filename)
    csv_file = open(csv_path, mode='w', newline='')
    writer = csv.writer(csv_file)
    writer.writerow([
        'Frame', 'Right_Ankle_X', 'Right_Ankle_Y', 'Left_Ankle_X', 'Left_Ankle_Y',
        'R_Shoulder_X', 'R_Shoulder_Y', 'L_Shoulder_X', 'L_Shoulder_Y',
        'R_Hip_X', 'R_Hip_Y', 'L_Hip_X', 'L_Hip_Y',
        'R_Knee_X', 'R_Knee_Y', 'L_Knee_X', 'L_Knee_Y'
    ])

    # 追蹤歷史點
    history_l_hip, history_r_hip = [], []
    history_l_knee, history_r_knee = [], []

    # 將區間轉換為 set 方便查詢
    valid_frames = set()
    for start, end in person_records:
        for f in range(start, end + 1):
            valid_frames.add(f)
            
    total_valid_frames = len(valid_frames)
    processed_valid_frames = 0

    frame_count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        # 只針對有人的區間進行分析並寫入輸出影片 (達成切割效果)
        if frame_count not in valid_frames:
            continue
            
        processed_valid_frames += 1
        if progress_callback and processed_valid_frames % 5 == 0:
            percent = (processed_valid_frames / total_valid_frames) * 100
            progress_callback(percent, f"正在分析骨幹 (幀 {processed_valid_frames}/{total_valid_frames})")

        # 圖像預處理
        img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img, ratio, (dw, dh) = letterbox(img_rgb, width, stride=64, auto=True)
        img = transforms.ToTensor()(img)
        img = torch.tensor(np.array([img.numpy()])).to(device).float()

        # 推論
        output, _ = model(img)
        output = non_max_suppression_kpt(output, 0.35, 0.7, nc=model.yaml['nc'], nkpt=model.yaml['nkpt'], kpt_label=True)
        output = output_to_keypoint(output)

        # 準備繪圖
        plot_img = frame.copy()

        for idx in range(output.shape[0]):
            kpts = output[idx, 7:].copy()
            
            # 座標縮放回原圖
            for i in range(len(kpts) // 3):
                kpts[3 * i] = (kpts[3 * i] - dw) / ratio[0]
                kpts[3 * i + 1] = (kpts[3 * i + 1] - dh) / ratio[1]
                
            joints_list = plot_skeleton_kpts(plot_img, kpts, 3)

            # 計算角度 (骨幹分析)
            try:
                L_Elbow = calculate_angle(joints_list[5], joints_list[7], joints_list[9])
                R_Elbow = calculate_angle(joints_list[6], joints_list[8], joints_list[10])
                L_Shoulder = calculate_angle(joints_list[11], joints_list[5], joints_list[7])
                R_Shoulder = calculate_angle(joints_list[12], joints_list[6], joints_list[8])
                L_Hip = calculate_angle(joints_list[5], joints_list[11], joints_list[13])
                R_Hip = calculate_angle(joints_list[6], joints_list[12], joints_list[14])
                L_Knee = calculate_angle(joints_list[11], joints_list[13], joints_list[15])
                R_Knee = calculate_angle(joints_list[12], joints_list[14], joints_list[16])

                angles_text = [
                    f"L Elbow: {L_Elbow:.1f}", f"R Elbow: {R_Elbow:.1f}",
                    f"L Shoulder: {L_Shoulder:.1f}", f"R Shoulder: {R_Shoulder:.1f}",
                    f"L Hip: {L_Hip:.1f}", f"R Hip: {R_Hip:.1f}",
                    f"L Knee: {L_Knee:.1f}", f"R Knee: {R_Knee:.1f}"
                ]
                for i, text in enumerate(angles_text):
                    cv2.putText(plot_img, text, (width - 250, 40 + i * 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            except:
                pass

            # 關鍵點追蹤
            if enable_track:
                l_hip = (int(joints_list[11][0]), int(joints_list[11][1]))
                r_hip = (int(joints_list[12][0]), int(joints_list[12][1]))
                l_knee = (int(joints_list[13][0]), int(joints_list[13][1]))
                r_knee = (int(joints_list[14][0]), int(joints_list[14][1]))
                
                if l_hip[0] != 0: history_l_hip.append(l_hip)
                if r_hip[0] != 0: history_r_hip.append(r_hip)
                if l_knee[0] != 0: history_l_knee.append(l_knee)
                if r_knee[0] != 0: history_r_knee.append(r_knee)

                draw_history_points(plot_img, history_l_hip, (255, 0, 0))
                draw_history_points(plot_img, history_r_hip, (255, 0, 0))
                draw_history_points(plot_img, history_l_knee, (0, 255, 0))
                draw_history_points(plot_img, history_r_knee, (0, 0, 255))

            # 寫入 CSV
            writer.writerow([
                frame_count, joints_list[16][0], joints_list[16][1], joints_list[15][0], joints_list[15][1],
                joints_list[6][0], joints_list[6][1], joints_list[5][0], joints_list[5][1],
                joints_list[12][0], joints_list[12][1], joints_list[11][0], joints_list[11][1],
                joints_list[14][0], joints_list[14][1], joints_list[13][0], joints_list[13][1]
            ])

        out.write(plot_img)

    cap.release()
    out.release()
    csv_file.close()
    make_ios_playable_mp4(result_video_path)
    
    return result_video_filename, csv_filename

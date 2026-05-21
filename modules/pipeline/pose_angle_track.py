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
def run_pose_analysis(source_path, output_dir, record_id, person_records, enable_track=False):
    """
    執行骨幹分析與關鍵點追蹤
    :param source_path: 原始影片路徑
    :param output_dir: 輸出目錄
    :param record_id: 紀錄 ID
    :param person_records: 人體偵測到的區間 [(start, end), ...]
    :param enable_track: 是否啟用關鍵點追蹤
    """
    model, device = load_model()
    cap = cv2.VideoCapture(source_path)
    
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # 建立輸出影片 (使用 avc1 確保網頁可播放)
    result_video_filename = f"{record_id}_result.mp4"
    result_video_path = os.path.join(output_dir, result_video_filename)
    fourcc = cv2.VideoWriter_fourcc(*'avc1') 
    out = cv2.VideoWriter(result_video_path, fourcc, fps, (width, height))
    
    if not out.isOpened():
        # 如果 avc1 不可用，退回到 mp4v
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(result_video_path, fourcc, fps, (width, height))

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

    frame_count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        # 只針對有人的區間進行分析並寫入輸出影片 (達成切割效果)
        if frame_count not in valid_frames:
            continue

        # 圖像預處理
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = letterbox(img, width, stride=64, auto=True)[0]
        img = transforms.ToTensor()(img)
        img = torch.tensor(np.array([img.numpy()])).to(device).float()

        # 推論
        output, _ = model(img)
        output = non_max_suppression_kpt(output, 0.35, 0.7, nc=model.yaml['nc'], nkpt=model.yaml['nkpt'], kpt_label=True)
        output = output_to_keypoint(output)

        # 準備繪圖
        plot_img = frame.copy()

        for idx in range(output.shape[0]):
            kpts = output[idx, 7:].T
            # 由於 letterbox 可能會改變座標比例，需要縮放回來
            # 這裡簡單假設 letterbox 是在原圖尺寸下運作 (因為傳入了 width)
            # 若有縮放邏輯需在此校正
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
    
    return result_video_filename, csv_filename

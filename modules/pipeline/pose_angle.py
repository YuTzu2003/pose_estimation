import cv2
import time
import torch
import argparse
import numpy as np
from utils.datasets import letterbox
from utils.torch_utils import select_device
from models.experimental import attempt_load
from utils.plots import output_to_keypoint, plot_skeleton_kpts
from utils.general import non_max_suppression_kpt, strip_optimizer
from torchvision import transforms
import csv

# 計算三點形成的角度
def calculate_angle(a, b, c):
    """
    計算以b為頂點，a和c構成的角度。
    :param a: 第一點 [x, y]
    :param b: 頂點 [x, y]
    :param c: 第二點 [x, y]
    :return: 角度 (度數)
    """
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)

    ab = a - b
    cb = c - b

    cosine_angle = np.dot(ab, cb) / (np.linalg.norm(ab) * np.linalg.norm(cb))
    angle = np.arccos(np.clip(cosine_angle, -1.0, 1.0))  # 避免浮點數超界
    return np.degrees(angle)

@torch.no_grad()
def run(source):
    path = source
    ext = path.split('/')[-1].split('.')[-1].strip().lower()
    if ext in ["mp4", "webm", "avi"] or ext not in ["mp4", "webm", "avi"] and ext.isnumeric():
        input_path = int(path) if path.isnumeric() else path
        device = select_device('0')
        half = device.type != 'cpu'
        model = attempt_load('yolov7-w6-pose.pt', map_location=device)
        _ = model.eval()

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            print('Error while trying to read video. Please check path again')

        frame_width, frame_height = int(cap.get(3)), int(cap.get(4))
        vid_write_image = letterbox(
            cap.read()[1], (frame_width), stride=64, auto=True)[0]
        resize_height, resize_width = vid_write_image.shape[:2]
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        out_video_name = "output" if path.isnumeric() else f"{input_path.split('/')[-1].split('.')[0]}"
        out = cv2.VideoWriter("output_result.mp4", cv2.VideoWriter_fourcc(*'mp4v'), fps, (resize_width, resize_height))

        csv_file = "ankle_with_angles.csv"
        file = open(csv_file, mode='w', newline='')
        writer = csv.writer(file)
        writer.writerow(['Frame', 'Right_Ankle_X', 'Right_Ankle_Y', 'Left_Ankle_X', 'Left_Ankle_Y', 
                         'R_Shoulder_X', 'R_Shoulder_Y', 'L_Shoulder_X', 'L_Shoulder_Y', 
                         'R_Hip_X', 'R_Hip_Y', 'L_Hip_X', 'L_Hip_Y', 
                         'R_Knee_X', 'R_Knee_Y', 'L_Knee_X', 'L_Knee_Y'])

        frame_count, total_fps = 0, 0

        while cap.isOpened():
            print(f"Frame {frame_count} Processing")
            ret, frame = cap.read()
            if ret:
                orig_image = frame

                # preprocess image
                image = cv2.cvtColor(orig_image, cv2.COLOR_BGR2RGB)
                image = letterbox(image, (frame_width), stride=64, auto=True)[0]
                image = transforms.ToTensor()(image)
                image = torch.tensor(np.array([image.numpy()]))

                image = image.to(device)
                image = image.float()
                start_time = time.time()

                with torch.no_grad():
                    output, _ = model(image)

                output = non_max_suppression_kpt(output, 0.35, 0.7, nc=model.yaml['nc'], nkpt=model.yaml['nkpt'], kpt_label=True)
                output = output_to_keypoint(output)
                img = image[0].permute(1, 2, 0) * 255
                img = img.cpu().numpy().astype(np.uint8)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                for idx in range(output.shape[0]):
                    joints_list = plot_skeleton_kpts(img, output[idx, 7:].T, 3)

                    # 手肘 (肩膀 - 手肘 - 手腕)
                    L_Elbow_Angle = calculate_angle(joints_list[5], joints_list[7], joints_list[9])
                    R_Elbow_Angle = calculate_angle(joints_list[6], joints_list[8], joints_list[10])
                    
                    # 肩膀 (髖 - 肩膀 - 手肘)
                    L_Shoulder_Angle = calculate_angle(joints_list[11], joints_list[5], joints_list[7])
                    R_Shoulder_Angle = calculate_angle(joints_list[12], joints_list[6], joints_list[8])

                    # 髖關節 (肩膀 - 髖 - 膝蓋)
                    L_Hip_Angle = calculate_angle(joints_list[5], joints_list[11], joints_list[13])
                    R_Hip_Angle = calculate_angle(joints_list[6], joints_list[12], joints_list[14])

                    # 膝蓋 (髖 - 膝蓋 - 腳踝)
                    L_Knee_Angle = calculate_angle(joints_list[11], joints_list[13], joints_list[15])
                    R_Knee_Angle = calculate_angle(joints_list[12], joints_list[14], joints_list[16])

                    # 整理要顯示的文字列表
                    angles_text = [
                        f"L Elbow: {L_Elbow_Angle:.1f}", 
                        f"R Elbow: {R_Elbow_Angle:.1f}",
                        f"L Shoulder: {L_Shoulder_Angle:.1f}", 
                        f"R Shoulder: {R_Shoulder_Angle:.1f}",
                        f"L Hip: {L_Hip_Angle:.1f}", 
                        f"R Hip: {R_Hip_Angle:.1f}",
                        f"L Knee: {L_Knee_Angle:.1f}", 
                        f"R Knee: {R_Knee_Angle:.1f}"
                    ]
                    
                    for i, text in enumerate(angles_text):
                        cv2.putText(img, text, (img.shape[1] - 250, 40 + i * 35), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                    writer.writerow([frame_count, joints_list[16][0], joints_list[16][1], joints_list[15][0], joints_list[15][1],
                                     joints_list[6][0], joints_list[6][1], joints_list[5][0], joints_list[5][1],
                                     joints_list[12][0], joints_list[12][1], joints_list[11][0], joints_list[11][1],
                                     joints_list[14][0], joints_list[14][1], joints_list[13][0], joints_list[13][1]])

                if ext.isnumeric():
                    cv2.imshow("Detection", img)
                    key = cv2.waitKey(1)
                    if key == ord('c'):
                        break

                end_time = time.time()
                fps = 1 / (end_time - start_time)
                total_fps += fps
                frame_count += 1
                out.write(img)
            else:
                break

        cap.release()
        avg_fps = total_fps / frame_count
        print(f"Average FPS: {avg_fps:.3f}")
        file.close()

if __name__ == "__main__":
    outpath = video
    run(outpath)

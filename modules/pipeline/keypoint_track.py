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
        out = cv2.VideoWriter(f"step_tracking.mp4", cv2.VideoWriter_fourcc(*'mp4v'), fps, (resize_width, resize_height))

        history_l_hip = []
        history_r_hip = []
        history_l_knee = []
        history_r_knee = []

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

                    l_hip = (int(joints_list[11][0]), int(joints_list[11][1]))
                    r_hip = (int(joints_list[12][0]), int(joints_list[12][1]))
                    l_knee = (int(joints_list[13][0]), int(joints_list[13][1]))
                    r_knee = (int(joints_list[14][0]), int(joints_list[14][1]))

                    if l_hip[0] != 0 and l_hip[1] != 0: history_l_hip.append(l_hip)
                    if r_hip[0] != 0 and r_hip[1] != 0: history_r_hip.append(r_hip)
                    if l_knee[0] != 0 and l_knee[1] != 0: history_l_knee.append(l_knee)
                    if r_knee[0] != 0 and r_knee[1] != 0: history_r_knee.append(r_knee)


                def draw_history_points(image, points_list, color, radius=3):
                    for pt in points_list:
                        cv2.circle(image, pt, radius, color, -1)

                draw_history_points(img, history_l_hip,(255,0,0),radius=4)   # 髖：藍色點
                draw_history_points(img, history_r_hip,(255,0,0),radius=4)
                draw_history_points(img, history_l_knee,(0,255,0),radius=4)  # 左膝：綠色點
                draw_history_points(img, history_r_knee,(0,0,255),radius=4)  # 右膝：紅色點

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

if __name__ == "__main__":
    outpath = "output_result.mp4"
    run(outpath)
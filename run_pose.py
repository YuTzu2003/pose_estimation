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

import cv2
import numpy as np

@torch.no_grad()
def run(poseweights= 'yolov7-w6-pose.pt', source='pose.mp4', device='cpu'):

    path = source
    ext = path.split('/')[-1].split('.')[-1].strip().lower()
    if ext in ["mp4", "webm", "avi"] or ext not in ["mp4", "webm", "avi"] and ext.isnumeric():
        input_path = int(path) if path.isnumeric() else path
        device = select_device(opt.device)
        half = device.type != 'cpu'
        model = attempt_load(poseweights, map_location=device)
        _ = model.eval()

        cap = cv2.VideoCapture(input_path)

        if (cap.isOpened() == False):
            print('Error while trying to read video. Please check path again')

        frame_width, frame_height = int(cap.get(3)), int(cap.get(4))

        vid_write_image = letterbox(
            cap.read()[1], (frame_width), stride=64, auto=True)[0]
        resize_height, resize_width = vid_write_image.shape[:2]
        image_transparent = np.zeros((resize_height,resize_width,3),np.uint8) # 透明畫布
        out_video_name = "output" if path.isnumeric else f"{input_path.split('/')[-1].split('.')[0]}"
        out = cv2.VideoWriter(f"{out_video_name}_result.mp4", cv2.VideoWriter_fourcc(*'mp4v'), 30, (resize_width, resize_height))

        frame_count, total_fps = 0, 0

        # 初始化最低點變數
        lowest_left_ankle = float('inf')  # 左腳踝最低點
        lowest_right_ankle = float('inf')  # 右腳踝最低點

        while cap.isOpened:

            print(f"Frame {frame_count} Processing")
            ret, frame = cap.read()
            if ret:
                orig_image = frame

                # preprocess image
                image = cv2.cvtColor(orig_image, cv2.COLOR_BGR2RGB)
                image = letterbox(image, (frame_width), stride=64, auto=True)[0]
                image_ = image.copy()
                image = transforms.ToTensor()(image)
                image = torch.tensor(np.array([image.numpy()]))

                image = image.to(device)
                image = image.float()
                start_time = time.time()

                with torch.no_grad():
                    output, _ = model(image)    
                output = non_max_suppression_kpt(output, 0.25, 0.65, nc=model.yaml['nc'], nkpt=model.yaml['nkpt'], kpt_label=True)
                output = output_to_keypoint(output)
                img = image[0].permute(1, 2, 0) * 255
                img = img.cpu().numpy().astype(np.uint8)

                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                for idx in range(output.shape[0]):
                    joints_list = plot_skeleton_kpts(img, output[idx, 7:].T, 3)
                    
                    Nose = joints_list[0][0], joints_list[0][1]
                    Left_Eye = joints_list[1][0], joints_list[1][1]
                    Right_Eye = joints_list[2][0], joints_list[2][1]
                    Left_Ear = joints_list[3][0], joints_list[3][1]
                    Right_Ear = joints_list[4][0], joints_list[4][1]

                    Left_Shoulder = joints_list[5][0], joints_list[5][1]
                    Right_Shoulder = joints_list[6][0], joints_list[6][1]
                    Left_Elbow = joints_list[7][0], joints_list[7][1]
                    Right_Elbow = joints_list[8][0], joints_list[8][1]
                    Left_Wrist = joints_list[9][0], joints_list[9][1]
                    Right_Wrist = joints_list[10][0], joints_list[10][1]
                    Left_Hip = joints_list[11][0], joints_list[11][1]
                    Right_Hip = joints_list[12][0], joints_list[12][1]
                    Left_Knee = joints_list[13][0], joints_list[13][1]
                    Right_Knee = joints_list[14][0], joints_list[14][1]
                    Left_Ankle = joints_list[15][0], joints_list[15][1]
                    Right_Ankle = joints_list[16][0], joints_list[16][1]

                    # cv2.circle(image_transparent, (round(Right_Ankle[0]), round(Right_Ankle[1])), 3, (0, 0, 255), 5)
                    # cv2.circle(image_transparent, (round(Left_Ankle[0]), round(Left_Ankle[1])), 3, (0, 255, 0), 5)
                img_concat = cv2.add(img, image_transparent)

                # if ext.isnumeric():
                cv2.imshow("Detection", img_concat)
                key = cv2.waitKey(1)
                if key == ord('c'):
                    break

                end_time = time.time()
                fps = 1 / (end_time - start_time)
                total_fps += fps
                frame_count += 1
                out.write(img_concat)
            else:
                break

        cap.release()
        avg_fps = total_fps / frame_count
        print(f"Average FPS: {avg_fps:.3f}")


def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--poseweights', nargs='+', type=str, default='yolov7-w6-pose.pt', help='model path(s)')
    parser.add_argument('--source', type=str, help='path to video or 0 for webcam')
    parser.add_argument('--device', type=str, default='cpu', help='cpu/0,1,2,3(gpu)')
    opt = parser.parse_args()
    return opt


def main(opt):
    run(**vars(opt))


if __name__ == "__main__":
    opt = parse_opt()
    strip_optimizer(opt.device, opt.poseweights)
    main(opt)

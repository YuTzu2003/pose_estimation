import cv2
import torch
import numpy as np
from models.experimental import attempt_load
from utils.datasets import letterbox
from utils.general import non_max_suppression_kpt

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
weights = 'yolov7-w6-pose.pt'
model = attempt_load(weights, map_location=device)
model.eval()

cap = cv2.VideoCapture('video/EDC.mp4')

is_person_present = False
start_frame = 0
patience = 15          # 容錯幀數：連續15幀沒抓到人才中斷
missing_frames = 0
frame_count = 0
records = []

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break
        
    frame_count += 1
    img = letterbox(frame, 960, stride=64, auto=True)[0]
    img = img[:, :, ::-1].transpose(2, 0, 1)
    img = np.ascontiguousarray(img)
    img = torch.from_numpy(img).to(device).float()
    img /= 255.0
    if img.ndimension() == 3:
        img = img.unsqueeze(0)

    with torch.no_grad():
        pred = model(img)[0]
        pred = non_max_suppression_kpt(pred, 0.25, 0.65, nc=model.yaml['nc'], nkpt=model.yaml['nkpt'], kpt_label=True)

    person_detected = len(pred[0]) > 0
    if person_detected:
        if not is_person_present:
            is_person_present = True
            start_frame = frame_count 
        missing_frames = 0
        cv2.putText(frame, "Person Detected", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
    else:
        if is_person_present:
            missing_frames += 1
            if missing_frames > patience:
                is_person_present = False
                end_frame = frame_count - patience
                records.append((start_frame, end_frame))
                
    cv2.imshow('YOLOv7 Pose Tracking', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

if is_person_present:
    records.append((start_frame, frame_count))

cap.release()
cv2.destroyAllWindows()
for r in records:
    print(f"People(Start: Frame{r[0]} -> End: Frame{r[1]})")
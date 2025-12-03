import cv2
import os
import glob
import tkinter as tk
from tkinter import filedialog

def filename_has_video_extension(filename):
    valid_video_extensions = ['mp4', 'MP4', 'avi']
    filename = filename.lower()
    extension = filename[-3:]
    if extension in valid_video_extensions:
        return True
    else:
        return False

def video_to_frames(video, path_output_dir):
    # extract frames from a video and save to directory as 'x.png' where 
    # x is the frame index
    vidcap = cv2.VideoCapture(video)
    count = 0
    while True:
        success, image = vidcap.read()
        if success == False:
            if lost_frame ==10:
                break
            lost_frame+=1
            continue
        lost_frame = 0
        cv2.imencode('.jpg', image)[1].tofile(f'{path_output_dir}\\frame_{count}.jpg')
        count += 1
        
    cv2.destroyAllWindows()
    vidcap.release()



if __name__ == '__main__':
    root = tk.Tk()
    root.withdraw()
    lost_frame = 0    
    path = filedialog.askdirectory()
    print(path)
    videos = glob.glob(f"{path}\\*")

    for athlete,video in enumerate(videos):
        if filename_has_video_extension(video) is False: continue
        video_name = video.split('\\')[-1]
        
        video_name_folder = path +'\\'+ video_name.split('.')[0] + '_image'
        if not os.path.isdir(video_name_folder):
            os.mkdir(video_name_folder)
            
        print(f'Processing {video_name}...')
        
        video_to_frames(video, video_name_folder)

    print("\n\n***** Finish!! ******")




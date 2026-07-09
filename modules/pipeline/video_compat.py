import os
import shutil
import subprocess
import threading
import uuid
import time

# 全局鎖，防止同一時間多個線程轉碼同一個檔案
_transcode_lock = threading.Lock()

def _find_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

def make_ios_playable_mp4(video_path):
    """
    將 MP4 轉碼為 iOS 友好的 H.264 格式，並解決 Windows 檔案鎖定問題。
    """
    if not video_path or not os.path.exists(video_path) or os.path.splitext(video_path)[1].lower() != ".mp4":
        return video_path

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print("ffmpeg not found; leaving MP4 as written by OpenCV.")
        return video_path

    # 使用 Lock 確保線程安全，防止並發轉碼衝突
    with _transcode_lock:
        # 使用隨機 ID 作為暫存檔名，避免衝突
        tmp_path = f"{video_path}.{uuid.uuid4().hex[:8]}.tmp.mp4"
        
        # 針對 iOS 優化的 ffmpeg 參數
        command = [
            ffmpeg,
            "-y",
            "-i", video_path,
            "-c:v", "libx264",
            "-profile:v", "high",
            "-level", "4.1",            # Level 4.1 支援度很高
            "-pix_fmt", "yuv420p",      # iOS 必備像素格式
            "-crf", "23",               # 控制品質
            "-maxrate", "5M",           # 限制最高流量
            "-bufsize", "10M",
            "-preset", "fast",
            "-movflags", "+faststart",  # 讓 iOS 支援邊下邊播
            "-an",                      # 移除聲音
            tmp_path,
        ]

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)

            # 針對 iOS 的新路徑
            ios_path = video_path.replace(".mp4", ".ios.mp4")

            # 在 Windows 上，如果檔案正被播放器讀取，os.replace 會失敗 (WinError 32)
            try:
                # 嘗試直接取代原檔
                os.replace(tmp_path, video_path)
                # 如果取代成功，如果原本有舊的 .ios.mp4 就刪掉
                if os.path.exists(ios_path):
                    try: os.remove(ios_path)
                    except: pass
                return video_path
            except PermissionError:
                print(f"ffmpeg iOS transcode: 檔案正被使用中，改為儲存至 {ios_path}")
                # 如果無法取代原檔，就存成一個獨立的 .ios.mp4 檔案
                if os.path.exists(ios_path):
                    try: os.remove(ios_path)
                    except: pass
                os.rename(tmp_path, ios_path)
                return ios_path
            
            return video_path
        except Exception as exc:
            print(f"ffmpeg iOS transcode skipped due to exception: {exc}")
            if os.path.exists(tmp_path):
                try: os.remove(tmp_path)
                except: pass
            return video_path

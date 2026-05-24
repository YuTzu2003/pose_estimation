import os
import shutil
import subprocess
import time
import uuid

def _find_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

def _safe_remove(path, retries=3, delay=0.5):
    """Attempt to remove a file with retries to handle Windows file locks."""
    if not os.path.exists(path):
        return
    for i in range(retries):
        try:
            os.remove(path)
            return
        except PermissionError:
            if i < retries - 1:
                time.sleep(delay)
            else:
                print(f"Warning: Could not remove temporary file {path} after {retries} attempts.")
        except Exception as e:
            print(f"Error removing {path}: {e}")
            break

def make_ios_playable_mp4(video_path):
    """Transcode MP4 output to an iOS-friendly H.264 file when ffmpeg exists."""
    if not video_path or os.path.splitext(video_path)[1].lower() != ".mp4":
        return video_path

    if not os.path.exists(video_path):
        return video_path

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print("ffmpeg not found; leaving MP4 as written by OpenCV.")
        return video_path

    unique_id = uuid.uuid4().hex[:8]
    tmp_path = f"{video_path}.{unique_id}.tmp.mp4"
    command = [
        ffmpeg,
        "-y",
        "-i",
        video_path,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "fast",
        "-movflags",
        "+faststart",
        "-an",
        tmp_path,
    ]

    try:
        # Run ffmpeg
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"ffmpeg iOS transcode failed: {result.stderr[-1000:]}")
            _safe_remove(tmp_path)
            return video_path

        # Success! Now replace the original with the iOS-friendly version.
        # On Windows, we need to handle cases where the file might be temporarily locked.
        replaced = False
        for i in range(5):
            try:
                os.replace(tmp_path, video_path)
                replaced = True
                break
            except PermissionError:
                if i < 4:
                    time.sleep(0.5)
                else:
                    print(f"ffmpeg iOS transcode replace failed after retries: {video_path} is likely in use.")
            except Exception as e:
                print(f"Error replacing {video_path}: {e}")
                break
        
        if not replaced:
            _safe_remove(tmp_path)
            
        return video_path
    except Exception as exc:
        print(f"ffmpeg iOS transcode skipped due to unexpected error: {exc}")
        _safe_remove(tmp_path)
        return video_path

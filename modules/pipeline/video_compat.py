import os
import shutil
import subprocess


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
    """Transcode MP4 output to an iOS-friendly H.264 file when ffmpeg exists."""
    if not video_path or os.path.splitext(video_path)[1].lower() != ".mp4":
        return video_path

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        print("ffmpeg not found; leaving MP4 as written by OpenCV.")
        return video_path

    tmp_path = f"{video_path}.ios.tmp.mp4"
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
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(f"ffmpeg iOS transcode failed: {result.stderr[-1000:]}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return video_path

        os.replace(tmp_path, video_path)
        return video_path
    except Exception as exc:
        print(f"ffmpeg iOS transcode skipped: {exc}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return video_path

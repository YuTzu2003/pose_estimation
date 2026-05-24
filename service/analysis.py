import os
import uuid
import time
import pandas as pd
import numpy as np
import threading
import cv2
from flask import Blueprint, request, jsonify, current_app
from modules.db import get_conn, release_conn
from modules.pipeline.backbone_detect import get_person_records
from modules.pipeline.pose_angle_track import run_pose_analysis
from modules.pipeline.peak_smooth import peak_smooth
from modules.pipeline.step_metrics import run_step
from modules.pipeline.imu_process import process_imu_data

analysis_bp = Blueprint('analysis', __name__)

progress_data = {}
progress_lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_DIR = os.path.join(BASE_DIR, 'static', 'jobs')

@analysis_bp.route('/api/progress/<job_id>')
def get_progress(job_id):
    with progress_lock:
        data = progress_data.get(job_id, {"progress": 0, "status": "等待中..."})
    return jsonify(data)

def update_progress(job_id, percent, status):
    if job_id:
        with progress_lock:
            progress_data[job_id] = {"progress": percent, "status": status}

@analysis_bp.route('/upload', methods=['POST'])
def upload():
    video_file = request.files.get('video')
    imu_file = request.files.get('imu_file')
    if not video_file and not imu_file:
        return jsonify({'error': '請至少選擇一個影片檔案或 IMU 數據檔案'}), 400
    athlete = request.form.get('athlete', '').strip()
    session_name = request.form.get('session', '').strip()
    note = request.form.get('note', '').strip()
    scale_reference = request.form.get('scale_reference', '').strip()
    scale_pixels = request.form.get('scale_pixels', '').strip()

    if not athlete or not session_name:
        return jsonify({'error': '請填寫選手與場次標註'}), 400
    record_id = "Rec_" + uuid.uuid4().hex[:8]
    project_dir = os.path.join(JOBS_DIR, record_id)
    os.makedirs(project_dir, exist_ok=True)
    job_id = request.form.get('job_id')
    orig_video_db_path = None
    imu_csv_db_path = None
    person_records = []
    fps = 30
    if video_file and video_file.filename != '':
        original_ext = os.path.splitext(video_file.filename)[1] or ".mp4"
        filename = record_id + original_ext
        abs_video_path = os.path.join(project_dir, filename)
        video_file.save(abs_video_path)
        orig_video_db_path = f"jobs/{record_id}/{filename}"
        try:        
            cap_temp = cv2.VideoCapture(abs_video_path)
            fps = cap_temp.get(cv2.CAP_PROP_FPS)
            cap_temp.release()
            update_progress(job_id, 5, "正在偵測有無出現人...")
            person_records = get_person_records(abs_video_path)
        except Exception as e:
            print(f"Video detection error: {e}")
            update_progress(job_id, 60, f"偵測失敗: {str(e)}")
            
    if imu_file and imu_file.filename != '':
        imu_ext = os.path.splitext(imu_file.filename)[1] or ".csv"
        temp_imu_filename = f"{record_id}_temp_imu{imu_ext}"
        abs_temp_imu_path = os.path.join(project_dir, temp_imu_filename)
        imu_file.save(abs_temp_imu_path)
        update_progress(job_id, 10, "正在驗證IMU數據...")
        std_csv_file, err = process_imu_data(abs_temp_imu_path, project_dir, record_id)
        if os.path.exists(abs_temp_imu_path):
            os.remove(abs_temp_imu_path)
        if std_csv_file:
            imu_csv_db_path = f"jobs/{record_id}/{std_csv_file}"
        else:
            update_progress(job_id, 60, f"IMU錯誤: {err}")
            return jsonify({'error': err}), 400

    # 建立初步紀錄與專案資料夾
    frame_start = 0
    frame_end = 0
    if person_records and len(person_records) > 0:
        frame_start = int(person_records[0][0])
        frame_end = int(person_records[0][1])
    
    project_folder = f"jobs/{record_id}"
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO Record (Record_id, Player_id, Session_name, Note, Project_Folder, Frame_Start, Frame_End, Scale_Reference, Scale_Pixels, Created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())""", 
                       (record_id, athlete, session_name, note, project_folder, frame_start, frame_end, scale_reference or None, scale_pixels or None))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Database error during initial record creation: {e}")
    finally:
        release_conn(conn)

    update_progress(job_id, 100, "上傳與偵測完成！")
    return jsonify({
        'record_id': record_id, 
        'message': '上傳與偵測完成！',
        'person_records': person_records,
        'fps': fps,
        'orig_video_path': orig_video_db_path,
        'imu_csv_path': imu_csv_db_path
    })

@analysis_bp.route('/api/analyze', methods=['POST'])
def analyze():
    data = request.json
    record_id = data.get('record_id')
    job_id = data.get('job_id')
    selected_modules = data.get('modules', [])
    person_records = data.get('person_records', [])
    scale_info = data.get('scale_info', {})
    athlete = data.get('athlete')
    session_name = data.get('session')
    note = data.get('note')
    if not record_id:
        return jsonify({'error': '缺少紀錄 ID'}), 400
    project_dir = os.path.join(JOBS_DIR, record_id)
    orig_video_filename = None
    video_extensions = ['.mp4', '.avi', '.mov', '.webm', '.mkv']
    if os.path.exists(project_dir):
        for f in os.listdir(project_dir):
            if f.startswith(record_id):
                ext = os.path.splitext(f)[1].lower()
                if ext in video_extensions and not any(x in f for x in ['_result', '_gait']):
                    orig_video_filename = f
                    break
    if not orig_video_filename:
        if os.path.exists(project_dir):
            for f in os.listdir(project_dir):
                if f.startswith(record_id) and not any(x in f for x in ['_result', '_gait', '_peaks', '_imu', '.csv', '.json']):
                    orig_video_filename = f
                    break
    if not orig_video_filename:
        return jsonify({'error': '找不到原始影片檔案'}), 404
    abs_video_path = os.path.join(project_dir, orig_video_filename)
    orig_video_db_path = f"jobs/{record_id}/{orig_video_filename}"
    result_video_path = None
    pose_csv_path = None
    peak_data_list = []
    try:
        if person_records:
            enable_track = 'track' in selected_modules
            update_progress(job_id, 10, "開始骨幹分析...")
            def pose_progress(p, s):
                update_progress(job_id, 10 + p * 0.5, s)
            res_video, res_csv = run_pose_analysis(
                abs_video_path, project_dir, record_id, 
                person_records, enable_track=enable_track,
                progress_callback=pose_progress
            )
            result_video_path = f"jobs/{record_id}/{res_video}"
            pose_csv_path = f"jobs/{record_id}/{res_csv}"
            pose_csv_abs = os.path.join(project_dir, res_csv)
            peaks_csv_name = f"{record_id}_peaks.csv"
            peaks_csv_abs = os.path.join(project_dir, peaks_csv_name)
            if peak_smooth(pose_csv_abs, peaks_csv_abs):
                try:
                    peak_df = pd.read_csv(peaks_csv_abs)
                    peak_data_list = []
                    for _, row in peak_df.iterrows():
                        entry = {}
                        for col in peak_df.columns:
                            val = row[col]
                            if pd.isna(val) or (isinstance(val, float) and (np.isinf(val) or np.isnan(val))):
                                entry[col] = None
                            else:
                                entry[col] = val
                        peak_data_list.append(entry)
                except Exception as e:
                    print(f"Peak data processing error: {e}")
            if 'gait' in selected_modules:
                update_progress(job_id, 70, "開始生成步頻影片...")
                gait_video_name = f"{record_id}_result.mp4"
                gait_video_abs = os.path.join(project_dir, gait_video_name)
                try:
                    ref_dist = float(scale_info.get('reference', 1))
                    px_dist = float(scale_info.get('pixels', 1))
                    ratio = ref_dist / px_dist if px_dist != 0 else 1.0
                except:
                    ratio = 1.0
                input_video_for_gait = os.path.join(project_dir, res_video)
                def step_progress(p, s):
                    update_progress(job_id, 70 + p * 0.25, s)
                if os.path.exists(peaks_csv_abs):
                    final_gait_video = run_step(
                        input_video_for_gait, peaks_csv_abs, gait_video_abs, 
                        ratio=ratio, person_records=person_records,
                        progress_callback=step_progress
                    )
                    if final_gait_video:
                        result_video_path = f"jobs/{record_id}/{final_gait_video}"
        else:
            update_progress(job_id, 60, "未偵測到人，跳過影片分析")
    except Exception as e:
        import traceback
        traceback.print_exc()
        update_progress(job_id, 60, f"分析失敗: {str(e)}")
        return jsonify({'error': str(e)}), 500

    frame_start = 0
    frame_end = 0
    if person_records and len(person_records) > 0:
        frame_start = int(person_records[0][0])
        frame_end = int(person_records[0][1])
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        # 更新已存在的紀錄
        cursor.execute("""UPDATE Record SET Frame_Start = ?, Frame_End = ?, Session_name = ?, Note = ?, Scale_Reference = ?, Scale_Pixels = ? WHERE Record_id = ?""", 
                       (frame_start, frame_end, session_name, note, scale_info.get('reference'), scale_info.get('pixels'), record_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Database error during record update: {e}")
    finally:
        release_conn(conn)

    update_progress(job_id, 100, "處理完成！")
    video_url = None
    if result_video_path: video_url = f"/static/{result_video_path}"
    elif orig_video_db_path: video_url = f"/static/{orig_video_db_path}"
    return jsonify({
        'record_id': record_id, 
        'message': '處理完成！',
        'video_url': video_url,
        'person_records': person_records,
        'peak_data': peak_data_list,
        'pose_csv': pose_csv_path,
        'peaks_csv': f"jobs/{record_id}/{record_id}_peaks.csv" if peak_data_list else None
    })

@analysis_bp.route('/regenerate_gait', methods=['POST'])
def regenerate_gait():
    data = request.json
    record_id = data.get('record_id')
    peak_data = data.get('peak_data')
    scale_info = data.get('scale_info')
    person_records = data.get('person_records')
    if not record_id or not peak_data:
        return jsonify({'error': 'Missing parameters'}), 400
    project_dir = os.path.join(JOBS_DIR, record_id)
    peaks_csv_abs = os.path.join(project_dir, f"{record_id}_peaks.csv")
    try:
        df = pd.DataFrame(peak_data)
        df.to_csv(peaks_csv_abs, index=False)
        input_video_for_gait = os.path.join(project_dir, f"{record_id}_pose.mp4")
        if not os.path.exists(input_video_for_gait):
            for f in os.listdir(project_dir):
                if f.startswith(record_id) and f.endswith('.mp4') and '_result' not in f:
                    input_video_for_gait = os.path.join(project_dir, f)
                    break
        if not os.path.exists(input_video_for_gait):
            return jsonify({'error': f'找不到原始骨幹分析影片 ({record_id}_pose.mp4)'}), 404
        gait_video_name = f"{record_id}_result.mp4"
        gait_video_abs = os.path.join(project_dir, gait_video_name)
        if os.path.exists(gait_video_abs):
            try: os.remove(gait_video_abs)
            except: pass
        ratio = float(scale_info['reference']) / float(scale_info['pixels'])
        final_gait_video = run_step(
            input_video_for_gait, peaks_csv_abs, gait_video_abs, 
            ratio=ratio, person_records=person_records
        )
        if final_gait_video:
            return jsonify({
                'success': True,
                'video_url': f"/static/jobs/{record_id}/{final_gait_video}?t={int(time.time())}"
            })
        else:
            return jsonify({'error': '影片生成程序執行失敗'}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@analysis_bp.route('/api/get_frame', methods=['GET'])
def get_frame():
    record_id = request.args.get('record_id')
    frame_no = int(request.args.get('frame_no', 0))
    if not record_id:
        return jsonify({'error': 'Missing record_id'}), 400
    project_dir = os.path.join(JOBS_DIR, record_id)
    orig_video_filename = None
    if os.path.exists(project_dir):
        for f in os.listdir(project_dir):
            if f.startswith(record_id):
                ext = os.path.splitext(f)[1].lower()
                if ext in ['.mp4', '.avi', '.mov', '.webm', '.mkv'] and not any(x in f for x in ['_result', '_gait']):
                    orig_video_filename = f
                    break
    if not orig_video_filename:
        return jsonify({'error': 'Video not found'}), 404
    abs_video_path = os.path.join(project_dir, orig_video_filename)
    try:
        import cv2
        import base64
        cap = cv2.VideoCapture(abs_video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_no >= total_frames:
            frame_no = total_frames - 1
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return jsonify({'error': 'Failed to read frame'}), 500
        _, buffer = cv2.imencode('.jpg', frame)
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        return jsonify({
            'success': True,
            'frame_data': f"data:image/jpeg;base64,{jpg_as_text}",
            'total_frames': total_frames,
            'current_frame': frame_no
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

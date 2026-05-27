import os
import uuid
import time
import pandas as pd
import numpy as np
import threading
import cv2
import json
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

def get_record_project_info(record_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT Project_Folder FROM Record WHERE Record_id = ?", (record_id,))
    row = cursor.fetchone()
    if row:
        folder = row[0]
        abs_path = os.path.join(BASE_DIR, 'static', folder)
        return abs_path, folder

    release_conn(conn)
    return os.path.join(JOBS_DIR, record_id), f"jobs/{record_id}"

@analysis_bp.route('/upload', methods=['POST'])
def upload():
    video_files = request.files.getlist('video')
    imu_file = request.files.get('imu_file')
    
    if not video_files and not imu_file:
        return jsonify({'error': '請至少選擇一個影片檔案或 IMU 數據檔案'}), 400
        
    athlete = request.form.get('athlete', '').strip()
    session_name = request.form.get('session', '').strip()
    note = request.form.get('note', '').strip()
    scale_reference = request.form.get('scale_reference', '').strip()
    scale_pixels = request.form.get('scale_pixels', '').strip()
    job_id = request.form.get('job_id')

    if not athlete or not session_name:
        return jsonify({'error': '請填寫選手與場次標註'}), 400

    session_id = "Ses_" + uuid.uuid4().hex[:8]
    session_results = []
    
    # Process IMU if exists
    imu_csv_db_path = None
    session_dir = os.path.join(JOBS_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    if imu_file and imu_file.filename != '':
        imu_ext = os.path.splitext(imu_file.filename)[1] or ".csv"
        temp_imu_filename = f"{session_id}_temp_imu{imu_ext}"
        abs_temp_imu_path = os.path.join(session_dir, temp_imu_filename)
        imu_file.save(abs_temp_imu_path)
        update_progress(job_id, 10, "正在驗證IMU數據...")
        std_csv_file, err = process_imu_data(abs_temp_imu_path, session_dir, session_id)
        if os.path.exists(abs_temp_imu_path):
            os.remove(abs_temp_imu_path)
        if std_csv_file:
            imu_csv_db_path = f"jobs/{session_id}/{std_csv_file}"
        else:
            update_progress(job_id, 60, f"IMU錯誤: {err}")
            return jsonify({'error': err}), 400

    # Save Session to DB
    conn = get_conn()
    try:
        cursor = conn.cursor()
        session_folder = f"jobs/{session_id}"
        cursor.execute("""INSERT INTO [Session] (Session_id, Session_name, Player_id, Note, Project_Folder, Created_at) VALUES (?, ?, ?, ?, ?, GETDATE())""", (session_id, session_name, athlete, note, session_folder))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Database error during session creation: {e}")
    finally:
        release_conn(conn)

    for idx, video_file in enumerate(video_files):
        if not video_file or video_file.filename == '':
            continue
        record_id = "Rec_" + uuid.uuid4().hex[:8]
        project_dir = os.path.join(session_dir, record_id)
        os.makedirs(project_dir, exist_ok=True)
        
        original_ext = os.path.splitext(video_file.filename)[1] or ".mp4"
        filename = record_id + original_ext
        abs_video_path = os.path.join(project_dir, filename)
        video_file.save(abs_video_path)
        orig_video_db_path = f"jobs/{session_id}/{record_id}/{filename}"
        person_records = []
        fps = 30
        try:        
            cap_temp = cv2.VideoCapture(abs_video_path)
            fps = cap_temp.get(cv2.CAP_PROP_FPS)
            cap_temp.release()
            update_progress(job_id, 10 + (idx * 10), f"正在偵測影片 {idx+1} 有無出現人...")
            person_records = get_person_records(abs_video_path)
        except Exception as e:
            print(f"Video detection error for {filename}: {e}")
            
        frame_start = 0
        frame_end = 0
        if person_records and len(person_records) > 0:
            frame_start = int(person_records[0][0])
            frame_end = int(person_records[0][1])
        
        project_folder = f"jobs/{session_id}/{record_id}"
        
        # Save Record to DB
        conn = get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""INSERT INTO Record (Record_id, Session_id, Project_Folder, Frame_Start, Frame_End, Scale_Reference, Scale_Pixels) 
                           VALUES (?, ?, ?, ?, ?, ?, ?)""", 
                           (record_id, session_id, project_folder, frame_start, frame_end, scale_reference or 1.0, scale_pixels or 100.0))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Database error during record creation: {e}")
        finally:
            release_conn(conn)

        session_results.append({
            'record_id': record_id,
            'filename': filename,
            'person_records': person_records,
            'fps': fps,
            'orig_video_path': orig_video_db_path
        })
        
        # Save analysis_info.json per record
        analysis_info = {
            "record_id": record_id,
            "session_id": session_id,
            "athlete": athlete,
            "session": session_name,
            "note": note,
            "scale_info": {"reference": scale_reference, "pixels": scale_pixels},
            "modules": ["detection"], 
            "person_records": person_records,
            "status": "detected",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": {
                "original_video": filename,
                "imu_csv": os.path.basename(imu_csv_db_path) if imu_csv_db_path and idx == 0 else None
            }
        }
        with open(os.path.join(project_dir, 'analysis_info.json'), 'w', encoding='utf-8') as f:
            json.dump(analysis_info, f, ensure_ascii=False, indent=4)

    update_progress(job_id, 100, "上傳與偵測完成！")
    return jsonify({
        'session_id': session_id,
        'message': '上傳與偵測完成！',
        'results': session_results,
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
        
    project_dir, project_folder = get_record_project_info(record_id)
    
    orig_video_filename = None
    video_extensions = ['.mp4', '.avi', '.mov', '.webm', '.mkv']
    if os.path.exists(project_dir):
        for f in os.listdir(project_dir):
            if f.startswith(record_id):
                ext = os.path.splitext(f)[1].lower()
                if ext in video_extensions and not any(x in f for x in ['_result', '_gait']):
                    orig_video_filename = f
                    break
    
    if not orig_video_filename and os.path.exists(project_dir):
        for f in os.listdir(project_dir):
            if f.startswith(record_id) and not any(x in f for x in ['_result', '_gait', '_peaks', '_imu', '.csv', '.json']):
                orig_video_filename = f
                break
                
    if not orig_video_filename:
        return jsonify({'error': f'找不到原始影片檔案 (ID: {record_id})'}), 404
        
    abs_video_path = os.path.join(project_dir, orig_video_filename)
    orig_video_db_path = f"{project_folder}/{orig_video_filename}"
    result_video_path = None
    pose_csv_path = None
    peak_data_list = []
    
    # 檢查是否可以 Smart Skip
    existing_pose_csv = os.path.join(project_dir, f"{record_id}_pose.csv")
    existing_pose_video = os.path.join(project_dir, f"{record_id}_pose.mp4")
    can_skip_pose = os.path.exists(existing_pose_csv) and os.path.exists(existing_pose_video)
    
    needs_tracking = 'track' in selected_modules
    force_rerun_pose = needs_tracking or not can_skip_pose

    try:
        if person_records:
            enable_track = 'track' in selected_modules
            res_video = f"{record_id}_pose.mp4"
            res_csv = f"{record_id}_pose.csv"
            
            if force_rerun_pose:
                update_progress(job_id, 10, "開始骨幹分析 (推論中)...")
                def pose_progress(p, s):
                    update_progress(job_id, 10 + p * 0.5, s)
                res_video, res_csv = run_pose_analysis(
                    abs_video_path, project_dir, record_id, 
                    person_records, enable_track=enable_track,
                    progress_callback=pose_progress
                )
            else:
                update_progress(job_id, 50, "偵測到現存骨架資料，跳過推論...")

            result_video_path = f"{project_folder}/{res_video}"
            pose_csv_path = f"{project_folder}/{res_csv}"
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
                        result_video_path = f"{project_folder}/{final_gait_video}"
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
    
    # Update DB
    conn = get_conn()
    try:
        cursor = conn.cursor()
        # 1. Update Record Table (Frame and Scale)
        cursor.execute("""UPDATE Record SET Frame_Start = ?, Frame_End = ?, Scale_Reference = ?, Scale_Pixels = ? WHERE Record_id = ?""", 
                       (frame_start, frame_end, scale_info.get('reference'), scale_info.get('pixels'), record_id))
        
        # 2. Get Session_id for this record to update Session table
        cursor.execute("SELECT Session_id FROM Record WHERE Record_id = ?", (record_id,))
        s_row = cursor.fetchone()
        if s_row:
            session_id = s_row[0]
            # 3. Update Session Table (Name and Note)
            cursor.execute("""UPDATE [Session] SET Session_name = ?, Note = ? WHERE Session_id = ?""", 
                           (session_name, note, session_id))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Database error during multi-table update: {e}")
    finally:
        release_conn(conn)

    module_map = {"angle": "Joint Angle", "track": "Keypoint Track", "gait": "Stride & Speed"}
    friendly_modules = [module_map.get(m, m) for m in selected_modules]
    
    analysis_info = {
        "record_id": record_id,
        "athlete": athlete,
        "session": session_name,
        "note": note,
        "scale_info": scale_info,
        "modules": friendly_modules,
        "person_records": person_records,
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": {
            "original_video": orig_video_filename,
            "pose_csv": res_csv if 'person_records' in locals() and person_records else None,
            "result_video": os.path.basename(result_video_path) if result_video_path else None
        }
    }
    with open(os.path.join(project_dir, 'analysis_info.json'), 'w', encoding='utf-8') as f:
        json.dump(analysis_info, f, ensure_ascii=False, indent=4)

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
        'peaks_csv': f"{project_folder}/{record_id}_peaks.csv" if peak_data_list else None
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
        
    project_dir, project_folder = get_record_project_info(record_id)
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
                'video_url': f"/static/{project_folder}/{final_gait_video}?t={int(time.time())}"
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
        
    project_dir, project_folder = get_record_project_info(record_id)
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
        import base64
        jpg_as_text = base64.b64encode(buffer).decode('utf-8')
        return jsonify({
            'success': True,
            'frame_data': f"data:image/jpeg;base64,{jpg_as_text}",
            'total_frames': total_frames,
            'current_frame': frame_no
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

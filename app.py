import os
import uuid
import logging
import sys
import time
import mimetypes
import re
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, Response, abort
from werkzeug.utils import secure_filename, safe_join
from modules.db import get_conn, release_conn
from service.player import player_bp
from service.record import record_bp
from service.line_notify import send_save_notification
from modules.pipeline.backbone_detect import get_person_records
from modules.pipeline.pose_angle_track import run_pose_analysis
from modules.pipeline.peak_smooth import peak_smooth
from modules.pipeline.step_metrics import run_step
from modules.pipeline.video_compat import make_ios_playable_mp4
from modules.pipeline.imu_process import process_imu_data
import threading

class CustomFormatter(logging.Formatter):
    def format(self, record):
        record.asctime = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        return f"{record.asctime} | {record.levelname} | {record.getMessage()}"

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(CustomFormatter())
root = logging.getLogger()
if root.hasHandlers():
    for h in root.handlers[:]:
        root.removeHandler(h)

logging.basicConfig(level=logging.INFO, handlers=[handler])
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.handlers = [handler]
werkzeug_logger.propagate = False

app = Flask(__name__)
# Global dictionary to store progress
progress_data = {}
progress_lock = threading.Lock()

@app.route('/api/progress/<job_id>')
def get_progress(job_id):
    with progress_lock:
        data = progress_data.get(job_id, {"progress": 0, "status": "等待中..."})
    return jsonify(data)

# ... (rest of imports)
app.register_blueprint(player_bp)
app.register_blueprint(record_bp)
JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'jobs')
if not os.path.exists(JOBS_DIR):
    os.makedirs(JOBS_DIR)

@app.route('/')
def index():
    conn = get_conn()
    players = []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Player_id, Name FROM Player ORDER BY Name")
        players = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching players: {e}")
    finally:
        release_conn(conn)
    return render_template('index.html', players=players)

@app.route('/index.html')
def index_html():
    return render_template('index.html')

@app.route('/records.html')
def records():
    return render_template('records.html')

@app.route('/media/<path:filename>')
def media(filename):
    full_path = safe_join(app.static_folder, filename)
    if not full_path or not os.path.isfile(full_path):
        abort(404)

    lower_name = os.path.basename(full_path).lower()
    is_generated_video = (
        full_path.lower().endswith('.mp4')
        and any(suffix in lower_name for suffix in ('_result.mp4', '_gait.mp4', '_gait_v2.mp4'))
    )
    if is_generated_video:
        make_ios_playable_mp4(full_path)

    mimetype = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
    if full_path.lower().endswith('.mp4'):
        mimetype = 'video/mp4'

    file_size = os.path.getsize(full_path)
    range_header = request.headers.get('Range')
    if not range_header:
        response = send_file(full_path, mimetype=mimetype, conditional=True)
        response.headers['Accept-Ranges'] = 'bytes'
        return response

    match = re.match(r'bytes=(\d*)-(\d*)', range_header)
    if not match:
        abort(416)

    start_text, end_text = match.groups()
    if start_text == '' and end_text == '':
        abort(416)

    if start_text == '':
        length = int(end_text)
        start = max(file_size - length, 0)
        end = file_size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1

    if start >= file_size or end < start:
        abort(416)

    end = min(end, file_size - 1)
    length = end - start + 1

    with open(full_path, 'rb') as video_file:
        video_file.seek(start)
        data = video_file.read(length)

    response = Response(data, 206, mimetype=mimetype, direct_passthrough=True)
    response.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    response.headers['Accept-Ranges'] = 'bytes'
    response.headers['Content-Length'] = str(length)
    return response

@app.route('/compare.html')
def compare():
    return render_template('compare.html')

@app.route('/upload', methods=['POST'])
def upload():
    video_file = request.files.get('video')
    imu_file = request.files.get('imu_file')
    
    if not video_file and not imu_file:
        return jsonify({'error': '請至少選擇一個影片檔案或 IMU 數據檔案'}), 400
        
    athlete = request.form.get('athlete', '').strip()
    session_name = request.form.get('session', '').strip()
    note = request.form.get('note', '').strip()
    
    # Scale info is mandatory only if video is present
    scale_reference = request.form.get('scale_reference', '').strip()
    scale_pixels = request.form.get('scale_pixels', '').strip()
    
    if video_file and (not scale_reference or not scale_pixels):
        return jsonify({'error': '上傳影片時，比例尺資訊為必填'}), 400
        
    if not athlete or not session_name:
        return jsonify({'error': '請填寫選手與場次標註'}), 400

    record_id = "Rec_" + uuid.uuid4().hex[:8]
    project_dir = os.path.join(JOBS_DIR, record_id)
    os.makedirs(project_dir, exist_ok=True)
  
    job_id = request.form.get('job_id')
    def update_progress(percent, status):
        if job_id:
            with progress_lock:
                progress_data[job_id] = {"progress": percent, "status": status}

    # Initialize paths
    orig_video_db_path = None
    imu_csv_db_path = None
    person_records = []
    fps = 30

    # 1. Process Video if exists
    if video_file and video_file.filename != '':
        original_ext = os.path.splitext(video_file.filename)[1] or ".mp4"
        filename = record_id + original_ext
        abs_video_path = os.path.join(project_dir, filename)
        video_file.save(abs_video_path)
        orig_video_db_path = f"jobs/{record_id}/{filename}"

        try:
            import cv2
            cap_temp = cv2.VideoCapture(abs_video_path)
            fps = cap_temp.get(cv2.CAP_PROP_FPS)
            cap_temp.release()

            update_progress(5, "正在執行人體偵測...")
            person_records = get_person_records(abs_video_path)
        except Exception as e:
            print(f"Video detection error: {e}")
            update_progress(60, f"影片偵測失敗: {str(e)}")

    # 2. Process IMU if exists
    if imu_file and imu_file.filename != '':
        imu_ext = os.path.splitext(imu_file.filename)[1] or ".csv"
        imu_filename = f"{record_id}_imu_orig{imu_ext}"
        abs_imu_path = os.path.join(project_dir, imu_filename)
        imu_file.save(abs_imu_path)
        
        update_progress(10, "正在預處理 IMU 數據...")
        std_csv_file, err = process_imu_data(abs_imu_path, project_dir, record_id)
        if std_csv_file:
            imu_csv_db_path = f"jobs/{record_id}/{std_csv_file}"
        else:
            print(f"IMU Error: {err}")
    
    update_progress(100, "上傳與偵測完成！")
    
    return jsonify({
        'record_id': record_id, 
        'message': '上傳與偵測完成！',
        'person_records': person_records,
        'fps': fps,
        'orig_video_path': orig_video_db_path,
        'imu_csv_path': imu_csv_db_path
    })

@app.route('/api/analyze', methods=['POST'])
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

    def update_progress(percent, status):
        if job_id:
            with progress_lock:
                progress_data[job_id] = {"progress": percent, "status": status}

    project_dir = os.path.join(JOBS_DIR, record_id)
    # Find original video path
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
        # Fallback: check if we have any file starting with record_id that's not a result/csv/imu
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
            
            update_progress(10, "開始骨幹分析...")
            def pose_progress(p, s):
                update_progress(10 + p * 0.5, s)

            res_video, res_csv = run_pose_analysis(
                abs_video_path, project_dir, record_id, 
                person_records, enable_track=enable_track,
                progress_callback=pose_progress
            )
            result_video_path = f"jobs/{record_id}/{res_video}"
            pose_csv_path = f"jobs/{record_id}/{res_csv}"
            
            # Always attempt peak smoothing to provide data for the correction table
            pose_csv_abs = os.path.join(project_dir, res_csv)
            peaks_csv_name = f"{record_id}_peaks.csv"
            peaks_csv_abs = os.path.join(project_dir, peaks_csv_name)
            
            print(f"[DEBUG] Attempting peak_smooth for {record_id}...")
            if peak_smooth(pose_csv_abs, peaks_csv_abs):
                print(f"[DEBUG] peak_smooth successful. Reading {peaks_csv_abs}...")
                try:
                    import pandas as pd
                    import numpy as np
                    peak_df = pd.read_csv(peaks_csv_abs)
                    # Replace NaN/Inf with None for JSON serialization
                    peak_df = peak_df.replace([np.inf, -np.inf], np.nan)
                    peak_data_list = peak_df.where(pd.notnull(peak_df), None).to_dict(orient='records')
                    print(f"[DEBUG] Successfully loaded {len(peak_data_list)} peaks for {record_id}")
                except Exception as e:
                    print(f"[DEBUG] Peak data processing error for {record_id}: {e}")
            else:
                print(f"[DEBUG] Peak smoothing failed for {record_id}")

            if 'gait' in selected_modules:
                update_progress(70, "開始生成步頻影片...")
                gait_video_name = f"{record_id}_gait.mp4"
                gait_video_abs = os.path.join(project_dir, gait_video_name)
                
                try:
                    ref_dist = float(scale_info.get('reference', 1))
                    px_dist = float(scale_info.get('pixels', 1))
                    ratio = ref_dist / px_dist if px_dist != 0 else 1.0
                except:
                    ratio = 1.0

                input_video_for_gait = os.path.join(project_dir, res_video)
                
                def step_progress(p, s):
                    update_progress(70 + p * 0.25, s)

                if os.path.exists(peaks_csv_abs):
                    final_gait_video = run_step(
                        input_video_for_gait, peaks_csv_abs, gait_video_abs, 
                        ratio=ratio, person_records=person_records,
                        progress_callback=step_progress
                    )
                    if final_gait_video:
                        result_video_path = f"jobs/{record_id}/{final_gait_video}"
        else:
            update_progress(60, "未偵測到人體，跳過影片分析")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Analysis error: {e}")
        update_progress(60, f"分析失敗: {str(e)}")
        return jsonify({'error': str(e)}), 500


    # IMU path lookup
    imu_csv_db_path = None
    for f in os.listdir(project_dir):
        if f.endswith('_imu_std.csv'):
            imu_csv_db_path = f"jobs/{record_id}/{f}"
            break

    # 3. Database Save
    full_note = note or ""
    if scale_info.get('reference'):
        full_note += f"\n[比例尺: {scale_info['reference']}m = {scale_info['pixels']}px]"
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Record 
            (Record_id, Player_id, Session_name, Note, Original_Video_Path, Result_Video_Path, Pose_csv_path, IMU_csv_path, IMU_plot_path, Created_at) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
        """, (record_id, athlete, session_name, full_note, orig_video_db_path, result_video_path, pose_csv_path, imu_csv_db_path, None))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Database error: {e}")
        # Even if DB fails, we return the result so UI can show it
    finally:
        release_conn(conn)   
    
    update_progress(100, "處理完成！")
    
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


@app.route('/api/append_data', methods=['POST'])
def append_data():
    record_id = request.form.get('record_id')
    if not record_id: return jsonify({'error': 'Missing record_id'}), 400
    
    video_file = request.files.get('video')
    imu_file = request.files.get('imu_file')
    project_dir = os.path.join(JOBS_DIR, record_id)
    
    if not os.path.exists(project_dir):
        return jsonify({'error': '找不到原始紀錄資料夾'}), 404

    conn = get_conn()
    
    try:
        cursor = conn.cursor()
        if video_file:
            scale_reference = request.form.get('scale_reference')
            scale_pixels = request.form.get('scale_pixels')
            if not scale_reference or not scale_pixels:
                return jsonify({'error': '補做影片分析需提供比例尺'}), 400
                
            original_ext = os.path.splitext(video_file.filename)[1] or ".mp4"
            filename = record_id + original_ext
            abs_video_path = os.path.join(project_dir, filename)
            video_file.save(abs_video_path)
            orig_video_db_path = f"jobs/{record_id}/{filename}"
            
            person_records = get_person_records(abs_video_path)
            res_video, res_csv = run_pose_analysis(abs_video_path, project_dir, record_id, person_records)
            
            pose_csv_abs = os.path.join(project_dir, res_csv)
            peaks_csv_abs = os.path.join(project_dir, f"{record_id}_peaks.csv")
            result_video_path = f"jobs/{record_id}/{res_video}"
            
            if peak_smooth(pose_csv_abs, peaks_csv_abs):
                gait_video_name = f"{record_id}_gait.mp4"
                gait_video_abs = os.path.join(project_dir, gait_video_name)
                ratio = float(scale_reference) / float(scale_pixels)
                final_gait_video = run_step(os.path.join(project_dir, res_video), peaks_csv_abs, gait_video_abs, ratio=ratio, person_records=person_records)
                if final_gait_video: result_video_path = f"jobs/{record_id}/{final_gait_video}"

            cursor.execute("""
                UPDATE Record SET Original_Video_Path = ?, Result_Video_Path = ?, Pose_csv_path = ?
                WHERE Record_id = ?
            """, (orig_video_db_path, result_video_path, f"jobs/{record_id}/{res_csv}", record_id))

        if imu_file:
            imu_ext = os.path.splitext(imu_file.filename)[1] or ".csv"
            imu_filename = f"{record_id}_imu_orig{imu_ext}"
            abs_imu_path = os.path.join(project_dir, imu_filename)
            imu_file.save(abs_imu_path)
            
            std_csv_file, err = process_imu_data(abs_imu_path, project_dir, record_id)
            if std_csv_file:
                cursor.execute("""
                    UPDATE Record SET IMU_csv_path = ?, IMU_plot_path = NULL
                    WHERE Record_id = ?
                """, (f"jobs/{record_id}/{std_csv_file}", record_id))
            else:
                return jsonify({'error': f'IMU 解析失敗: {err}'}), 500

        conn.commit()
        return jsonify({'success': True, 'message': '資料已成功補齊'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@app.route('/regenerate_gait', methods=['POST'])
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
        import pandas as pd
        df = pd.DataFrame(peak_data)
        df.to_csv(peaks_csv_abs, index=False)
        
        # 尋找輸入影片，可能是 .mp4 或 .avi
        input_video_for_gait = None
        for ext in ['_result.mp4', '_result.avi', '.mp4', '.avi']:
            test_path = os.path.join(project_dir, f"{record_id}{ext}")
            if os.path.exists(test_path):
                input_video_for_gait = test_path
                break
        
        if not input_video_for_gait:
            return jsonify({'error': f'找不到原始分析影片 ({record_id}_result.mp4)'}), 404
            
        gait_video_name = f"{record_id}_gait_v2.mp4"
        gait_video_abs = os.path.join(project_dir, gait_video_name)
        
        ratio = float(scale_info['reference']) / float(scale_info['pixels'])
        
        final_gait_video = run_step(
            input_video_for_gait, peaks_csv_abs, gait_video_abs, 
            ratio=ratio, person_records=person_records
        )
        
        if final_gait_video:
            result_video_path = f"jobs/{record_id}/{final_gait_video}"
            
            # 更新資料庫
            conn = get_conn()
            try:
                cursor = conn.cursor()
                cursor.execute("UPDATE Record SET Result_Video_Path = ? WHERE Record_id = ?", (result_video_path, record_id))
                conn.commit()
            except Exception as db_e:
                print(f"Database update failed: {db_e}")
            finally:
                release_conn(conn)
                
            return jsonify({
                'success': True,
                'video_url': f"/static/{result_video_path}?t={int(time.time())}"
            })
        else:
            return jsonify({'error': '影片生成程序執行失敗'}), 500
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/player_records/<player_id>')
def get_player_records(player_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Record_id, Session_name, Created_at, Original_Video_Path, Result_Video_Path 
            FROM Record WHERE Player_id = ? 
            ORDER BY Created_at DESC
        """, (player_id,))
        rows = cursor.fetchall()
        records = []
        for r in rows:
            records.append({
                'Record_id': r[0],
                'Session_name': r[1],
                'Created_at': r[2].strftime("%Y-%m-%d %H:%M"),
                'Original_Video_Path': r[3],
                'Result_Video_Path': r[4]
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@app.route('/api/record_detail/<record_id>')
def get_record_detail(record_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row: return jsonify({'error': 'Record not found'}), 404
        
        # Columns: Record_id, Player_id, Session_name, Note, Original_Video_Path, Result_Video_Path, Pose_csv_path, IMU_csv_path, IMU_plot_path, Created_at
        record_data = {
            'Record_id': row[0],
            'Player_id': row[1],
            'Session_name': row[2],
            'Note': row[3],
            'Result_Video_Path': row[5],
            'Pose_csv_path': row[6],
            'IMU_csv_path': row[7]
        }
        
        # Load Pose Data
        pose_data = []
        if row[6]:
            csv_path = os.path.join(app.static_folder, row[6])
            if os.path.exists(csv_path):
                import pandas as pd
                df = pd.read_csv(csv_path)
                # Map expected column names for skeleton angles
                angle_cols = {
                    'Right_Knee_Angle': 'knee',
                    'Right_Hip_Angle': 'hip',
                    'Right_Ankle_Angle': 'ankle',
                    'Right_Shoulder_Angle': 'shoulder',
                    'Right_Elbow_Angle': 'elbow'
                }
                # Check if columns exist, if not try simple names
                available_cols = {v: k for k, v in angle_cols.items() if k in df.columns}
                if not available_cols:
                    # Try fallback (lowercase or simple names)
                    available_cols = {c.lower(): c for c in df.columns if c.lower() in ['knee', 'hip', 'ankle', 'shoulder', 'elbow']}
                
                for _, r in df.iterrows():
                    entry = {}
                    for target, src in available_cols.items():
                        entry[target] = float(r[src]) if not pd.isna(r[src]) else 0
                    pose_data.append(entry)

        # Load IMU Data
        imu_data = []
        if row[7]:
            imu_path = os.path.join(app.static_folder, row[7])
            if os.path.exists(imu_path):
                import pandas as pd
                df_imu = pd.read_csv(imu_path)
                # Ensure we have acc_res, etc.
                for _, r in df_imu.iterrows():
                    entry = {}
                    for col in ['acc_res', 'acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']:
                        if col in df_imu.columns:
                            entry[col] = float(r[col]) if not pd.isna(r[col]) else 0
                        elif col.replace('_', ' ') in df_imu.columns: # handle spaces if any
                            entry[col] = float(r[col.replace('_', ' ')])
                    imu_data.append(entry)

        return jsonify({
            'record': record_data,
            'pose_data': pose_data,
            'imu_data': imu_data
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@app.route('/player.html')
def player_page():
    return render_template('player.html')

@app.route('/download_tool')
def download_tool():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'video2frame.exe', as_attachment=True)

@app.route('/api/line_notify', methods=['POST'])
def line_notify():
    data = request.json
    record_id = data.get('record_id')
    session_name = data.get('session_name')
    
    if not record_id:
        return jsonify({'error': 'Missing record_id'}), 400
        
    try:
        result = send_save_notification(record_id, session_name or "未指定場次")
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        print(f"LINE notification error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "51005"))
    print(f"Starting server on http://{host}:{port}")
    app.run(host=host, port=port, debug=True)

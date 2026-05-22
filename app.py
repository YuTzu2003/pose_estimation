import os
import uuid
import logging
import sys
import time
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from modules.db import get_conn, release_conn
from service.player import player_bp
from service.record import record_bp
from modules.pipeline.backbone_detect import get_person_records
from modules.pipeline.pose_angle_track import run_pose_analysis
from modules.pipeline.peak_smooth import peak_smooth
from modules.pipeline.step_metrics import run_step

app = Flask(__name__)
# ... (rest of the file until regenerate_gait)
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

@app.route('/compare.html')
def compare():
    return render_template('compare.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'video' not in request.files:
        return jsonify({'error': '沒有選擇影片檔案'}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': '未選擇檔案'}), 400
        
    athlete = request.form.get('athlete', '').strip()
    session_name = request.form.get('session', '').strip()
    note = request.form.get('note', '').strip()
    scale_reference = request.form.get('scale_reference', '').strip()
    scale_pixels = request.form.get('scale_pixels', '').strip()
    
    # 取得分析選項
    selected_modules = request.form.getlist('m') # ['angle', 'track', 'gait']
    enable_track = 'track' in selected_modules
    
    if not all([athlete, session_name, note, scale_reference, scale_pixels]):
        return jsonify({'error': '請填寫所有必要資訊 (選手、場次、備註、比例尺)'}), 400

    record_id = "Rec_" + uuid.uuid4().hex[:8]
    project_dir = os.path.join(JOBS_DIR, record_id)
    os.makedirs(project_dir, exist_ok=True)
  
    original_ext = os.path.splitext(file.filename)[1]
    if not original_ext:
        original_ext = ".mp4"
    filename = record_id + original_ext
    abs_video_path = os.path.join(project_dir, filename)
    file.save(abs_video_path)

    # 執行偵測與分析
    try:
        import cv2
        cap_temp = cv2.VideoCapture(abs_video_path)
        fps = cap_temp.get(cv2.CAP_PROP_FPS)
        cap_temp.release()

        person_records = get_person_records(abs_video_path)
        if person_records:
            records_str = ", ".join([f"Frame {r[0]}-{r[1]}" for r in person_records])
            
            # 1. 執行骨幹分析 (與選配的關鍵點追蹤)
            res_video, res_csv = run_pose_analysis(
                abs_video_path, project_dir, record_id, 
                person_records, enable_track=enable_track
            )
            
            result_video_path = f"jobs/{record_id}/{res_video}"
            pose_csv_path = f"jobs/{record_id}/{res_csv}"
            
            # 2. 如果選擇了步頻分析 (Gait Analysis)
            if 'gait' in selected_modules:
                pose_csv_abs = os.path.join(project_dir, res_csv)
                peaks_csv_name = f"{record_id}_peaks.csv"
                peaks_csv_abs = os.path.join(project_dir, peaks_csv_name)
                
                # 平滑與波峰偵測
                if peak_smooth(pose_csv_abs, peaks_csv_abs):
                    # 讀取剛剛產生的 peak data 回傳給前端
                    try:
                        import pandas as pd
                        peak_df = pd.read_csv(peaks_csv_abs)
                        # 將 NaN 轉為 None 方便 JSON 化
                        peak_data_list = peak_df.where(pd.notnull(peak_df), None).to_dict(orient='records')
                    except Exception as e:
                        print(f"Error reading peaks csv: {e}")
                        peak_data_list = []

                    # 步頻與速度計算
                    gait_video_name = f"{record_id}_gait.mp4"
                    gait_video_abs = os.path.join(project_dir, gait_video_name)
                    
                    # 計算比例尺
                    ratio = float(scale_reference) / float(scale_pixels)
                    
                    # 傳入骨幹分析後的影片進行疊加
                    input_video_for_gait = os.path.join(project_dir, res_video)
                    
                    final_gait_video = run_step(
                        input_video_for_gait, peaks_csv_abs, gait_video_abs, 
                        ratio=ratio, person_records=person_records
                    )
                    
                    if final_gait_video:
                        result_video_path = f"jobs/{record_id}/{final_gait_video}"
                        
        else:
            records_str = "未偵測到人體"
            result_video_path = None
            pose_csv_path = None
            peak_data_list = []
    except Exception as e:
        print(f"Analysis error: {e}")
        import traceback
        traceback.print_exc()
        records_str = f"分析失敗: {str(e)}"
        person_records = []
        result_video_path = None
        pose_csv_path = None
        peak_data_list = []

    db_relative_path = f"jobs/{record_id}/{filename}"
    full_note = f"{note}\n[比例尺: {scale_reference}m = {scale_pixels}px]\n[人體偵測區間: {records_str}]"
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Record (
                Record_id, Player_id, Session_name, Note, 
                Original_Video_Path, Result_Video_Path, Pose_csv_path, Created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, GETDATE())
        """, (record_id, athlete, session_name, full_note, db_relative_path, result_video_path, pose_csv_path))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫儲存失敗: {str(e)}'}), 500
    finally:
        release_conn(conn)   
    
    # 返回 URL 供前端預覽
    final_video_url = f"/static/{result_video_path}" if result_video_path else f"/static/{db_relative_path}"
    
    return jsonify({
        'record_id': record_id, 
        'message': '分析完成！',
        'video_url': final_video_url,
        'person_records': person_records,
        'peak_data': peak_data_list,
        'pose_csv': pose_csv_path,
        'gait_video': result_video_path,
        'fps': fps,
        'scale_info': {
            'reference': scale_reference,
            'pixels': scale_pixels
        }
    })

@app.route('/regenerate_gait', methods=['POST'])
def regenerate_gait():
    data = request.json
    record_id = data.get('record_id')
    peak_data = data.get('peak_data') # 陣列 [{Frame_Right, X_Right, ...}, ...]
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

@app.route('/player.html')
def player_page():
    return render_template('player.html')

@app.route('/download_tool')
def download_tool():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'video2frame.exe', as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

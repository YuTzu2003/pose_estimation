import os
import uuid
import logging
import sys
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from modules.db import get_conn, release_conn
from service.player import player_bp
from modules.pipeline.backbone_detect import get_person_records
from modules.pipeline.pose_angle_track import run_pose_analysis

app = Flask(__name__)
app.register_blueprint(player_bp)
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
        person_records = get_person_records(abs_video_path)
        if person_records:
            records_str = ", ".join([f"Frame {r[0]}-{r[1]}" for r in person_records])
            
            # 執行骨幹分析 (與選配的關鍵點追蹤)
            res_video, res_csv = run_pose_analysis(
                abs_video_path, project_dir, record_id, 
                person_records, enable_track=enable_track
            )
            result_video_path = f"jobs/{record_id}/{res_video}"
            pose_csv_path = f"jobs/{record_id}/{res_csv}"
        else:
            records_str = "未偵測到人體"
            result_video_path = None
            pose_csv_path = None
    except Exception as e:
        print(f"Analysis error: {e}")
        import traceback
        traceback.print_exc()
        records_str = f"分析失敗: {str(e)}"
        person_records = []
        result_video_path = None
        pose_csv_path = None

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
        'person_records': person_records
    })

@app.route('/player.html')
def player_page():
    return render_template('player.html')

if __name__ == "__main__":
    app.run(debug=True)

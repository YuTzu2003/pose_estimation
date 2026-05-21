import os
import uuid
import logging
import sys
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from modules.db import get_conn, release_conn
from service.player import player_bp
from service.analysis import run_full_analysis

app = Flask(__name__)
app.register_blueprint(player_bp)
JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jobs')
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
        
    athlete = request.form.get('athlete', '')
    session_name = request.form.get('session', '')
    note = request.form.get('note', '')
    
    # 取得比例尺與分析項目
    scale_reference = float(request.form.get('scale_reference', 0.3) or 0.3)
    scale_pixels = int(request.form.get('scale_pixels', 54) or 54)
    modules = request.form.getlist('m') # ['angle', 'track', 'gait']

    record_id = "Rec_" + uuid.uuid4().hex[:8]
    project_dir = os.path.join(JOBS_DIR, record_id)
    os.makedirs(project_dir, exist_ok=True)
  
    filename = secure_filename(file.filename)
    if not filename:
        filename = "video.mp4"
        
    video_path = os.path.join(project_dir, filename)
    file.save(video_path)

    # 執行分析
    try:
        result_video, pose_csv, peaks_csv = run_full_analysis(
            video_path, project_dir, modules, 
            scale_reference=scale_reference, 
            scale_pixels=scale_pixels
        )
    except Exception as e:
        return jsonify({'error': f'分析失敗: {str(e)}'}), 500
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Record (
                Record_id, Player_id, Session_name, Note, 
                Original_Video_Path, Result_Video_Path, 
                Pose_csv_path, ValidPeaks_csv_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (record_id, athlete, session_name, note, video_path, result_video, pose_csv, peaks_csv))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)   
    return jsonify({'record_id': record_id, 'message': '上傳成功並完成分析！'})

@app.route('/player.html')
def player_page():
    return render_template('player.html')

if __name__ == "__main__":
    app.run(debug=True)

import os
import uuid
import logging
import sys
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from modules.db import get_conn, release_conn
from service.player import player_bp
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
    db_relative_path = f"jobs/{record_id}/{filename}"
    full_note = f"{note}\n[比例尺: {scale_reference}m = {scale_pixels}px]"
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Record (Record_id, Player_id, Session_name, Note, Original_Video_Path, Created_at) VALUES (?, ?, ?, ?, ?, GETDATE())""", (record_id, athlete, session_name, full_note, db_relative_path))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫儲存失敗: {str(e)}'}), 500
    finally:
        release_conn(conn)   
    
    video_url = f"/static/{db_relative_path}"
    return jsonify({'record_id': record_id, 'message': '影片上傳並紀錄成功！請至記錄頁面查看。','video_url': video_url})

@app.route('/player.html')
def player_page():
    return render_template('player.html')

if __name__ == "__main__":
    app.run(debug=True)

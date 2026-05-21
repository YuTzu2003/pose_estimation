import os
import uuid
import random
import string
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from modules.db import get_conn, release_conn

app = Flask(__name__)

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
    
    # Generate unique project ID (Record_id)
    # Prefix 'Rec_' with 8 random hex characters
    record_id = "Rec_" + uuid.uuid4().hex[:8]
    
    # Create project directory under jobs/
    project_dir = os.path.join(JOBS_DIR, record_id)
    os.makedirs(project_dir, exist_ok=True)
    
    # Save the original video
    filename = secure_filename(file.filename)
    # Fallback if filename is empty after secure_filename
    if not filename:
        filename = "video.mp4"
        
    video_path = os.path.join(project_dir, filename)
    file.save(video_path)
    
    # Insert into database
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Record (Record_id, Player_id, Session_name, Note, Original_Video_Path)
            VALUES (?, ?, ?, ?, ?)
        """, (record_id, athlete, session_name, note, video_path))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)
        
    return jsonify({'record_id': record_id, 'message': '上傳成功！專案已建立。'})

@app.route('/player.html')
def player_page():
    return render_template('player.html')

@app.route('/player', methods=['POST'])
def player():
    name = request.form.get('name')
    gender = request.form.get('gender')
    birthdate = request.form.get('birthdate')
    height = request.form.get('height')
    weight = request.form.get('weight')
    sport = request.form.get('sport')
    
    # Generate random Player_id: 'P' + 4 random alphanumeric characters
    chars = string.ascii_uppercase + string.digits
    player_id = 'P' + ''.join(random.choices(chars, k=4))
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO Player (Player_id, Name, Gender, BirthDate, Height, Weight, Sport)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (player_id, name, gender, birthdate, height, weight, sport))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)
        
    return jsonify({'message': f'選手建檔成功！系統編號為: {player_id}'})

@app.route('/get_players', methods=['GET'])
def get_players():
    conn = get_conn()
    players = []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Player_id, Name, Sport, Created_at FROM Player ORDER BY Created_at DESC")
        rows = cursor.fetchall()
        for row in rows:
            players.append({
                'id': row[0],
                'name': row[1],
                'sport': row[2] if row[2] else '',
                'date': row[3].strftime('%Y-%m-%d') if row[3] else ''
            })
    except Exception as e:
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)
    return jsonify(players)

@app.route('/delete_player/<player_id>', methods=['DELETE'])
def delete_player(player_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Player WHERE Player_id = ?", (player_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)
    return jsonify({'message': '選手資料已刪除'})

@app.route('/update_player', methods=['POST'])
def update_player():
    player_id = request.form.get('id')
    name = request.form.get('name')
    sport = request.form.get('sport')
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE Player 
            SET Name = ?, Sport = ? 
            WHERE Player_id = ?
        """, (name, sport, player_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)
    return jsonify({'message': '選手資料已更新'})

if __name__ == "__main__":
    app.run(debug=True)

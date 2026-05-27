import os
import logging
import sys
import mimetypes
from flask import Flask, render_template, request, send_from_directory, send_file, abort
from werkzeug.utils import safe_join
from modules.db import get_conn, release_conn
from service.player import player_bp
from service.record import record_bp, fetch_all_records_data, fetch_record_details_data
from service.compare import compare_bp
from service.line_notify import line_notify_bp
from service.analysis import analysis_bp

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

app.register_blueprint(player_bp)
app.register_blueprint(record_bp)
app.register_blueprint(compare_bp)
app.register_blueprint(line_notify_bp)
app.register_blueprint(analysis_bp)

JOBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'jobs')
if not os.path.exists(JOBS_DIR):
    os.makedirs(JOBS_DIR)

@app.route('/')
@app.route('/index')
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

@app.route('/records')
def records():
    conn = get_conn()
    players = []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Player_id, Name, Sport, Gender, Height, Weight FROM Player ORDER BY Name")
        rows = cursor.fetchall()
        for r in rows:
            players.append({
                'id': r[0], 'name': r[1], 'sport': r[2], 'gender': r[3], 'height': r[4], 'weight': r[5]
            })
        
        # Calculate stats
        cursor.execute("SELECT COUNT(DISTINCT Session_id) FROM Record")
        total_sessions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM Player")
        total_athletes = cursor.fetchone()[0]
    except Exception as e:
        print(f"Error fetching players for UI: {e}")
        total_sessions = 0
        total_athletes = 0
    finally:
        release_conn(conn)
    return render_template('records.html', view_mode='players', players=players, total_sessions=total_sessions, total_athletes=total_athletes)

@app.route('/records/<player_id>')
def player_records_view(player_id):
    try:
        # Get player name
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT Name FROM Player WHERE Player_id = ?", (player_id,))
        p_row = cursor.fetchone()
        player_name = p_row[0] if p_row else "Unknown"
        
        # Fetch all records and group into sessions (similar to JS logic)
        all_records = fetch_all_records_data(player_id)
        sessions = {}
        for r in all_records:
            key = r['session_id'] or f"{r['session']}_{r['date'].split(' ')[0]}"
            if key not in sessions:
                sessions[key] = {
                    'id': key,
                    'name': r['session'],
                    'date': r['date'],
                    'note': r['note'],
                    'records': []
                }
            sessions[key]['records'].append(r)
        
        # Sort sessions by date desc
        sorted_sessions = sorted(sessions.values(), key=lambda x: x['date'], reverse=True)
        
        # Stats
        cursor.execute("SELECT COUNT(DISTINCT Session_id) FROM Record")
        total_sessions_all = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM Player")
        total_athletes = cursor.fetchone()[0]
        release_conn(conn)
        
        return render_template('records.html', 
                               view_mode='sessions', 
                               player_id=player_id, 
                               player_name=player_name, 
                               sessions=sorted_sessions,
                               total_sessions=total_sessions_all,
                               total_athletes=total_athletes)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}", 500

@app.route('/records/<player_id>/<session_id>')
def session_detail_view(player_id, session_id):
    try:
        # Fetch all records and group them exactly like the session list
        all_records = fetch_all_records_data(player_id)
        sessions = {}
        for r in all_records:
            key = r['session_id'] or f"{r['session']}_{r['date'].split(' ')[0]}"
            if key not in sessions:
                sessions[key] = []
            sessions[key].append(r)
            
        if session_id not in sessions or not sessions[session_id]:
            return "Session not found", 404
            
        # Get record_id to display (either from query param for switching videos, or default to first in the group)
        record_id = request.args.get('r')
        if not record_id:
            record_id = sessions[session_id][0]['id']
        
        record_data = fetch_record_details_data(record_id)
        if not record_data:
            return "Record not found", 404
            
        # Override session_videos with our robust grouped list, keeping pose_csv
        record_data['session_videos'] = [{'id': r['id'], 'project_folder': r['project_folder'], 'pose_csv': r['pose_csv']} for r in sessions[session_id]]
            
        # Stats for header
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT Session_id) FROM Record")
        total_sessions = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM Player")
        total_athletes = cursor.fetchone()[0]
        release_conn(conn)

        return render_template('records.html', 
                               view_mode='detail', 
                               record=record_data,
                               total_sessions=total_sessions,
                               total_athletes=total_athletes)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}", 500

@app.route('/media/<path:filename>')
def media(filename):
    full_path = safe_join(app.static_folder, filename)
    if not full_path or not os.path.isfile(full_path):
        abort(404)

    user_agent = request.headers.get('User-Agent', '').lower()
    is_mobile = any(keyword in user_agent for keyword in ['iphone', 'ipad', 'android', 'mobile', 'macintosh'])
    
    if is_mobile and full_path.lower().endswith('.mp4') and not full_path.lower().endswith('.ios.mp4'):
        ios_version = full_path.replace('.mp4', '.ios.mp4')
        if os.path.exists(ios_version):
            full_path = ios_version

    mimetype = mimetypes.guess_type(full_path)[0] or 'application/octet-stream'
    if full_path.lower().endswith('.mp4'):
        mimetype = 'video/mp4'
    return send_file(full_path, mimetype=mimetype, conditional=True)

@app.route('/compare')
def compare():
    conn = get_conn()
    players = []
    try:
        cursor = conn.cursor()
        
        cursor.execute("SELECT Player_id, Name FROM Player ORDER BY Name")
        players = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching players for compare: {e}")
    finally:
        release_conn(conn)
    return render_template('compare.html', players=players)

@app.route('/player')
def player():
    return render_template('player.html')

@app.route('/download_tool')
def download_tool():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'video2frame.exe', as_attachment=True)

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "51005"))
    print(f"Starting server on http://{host}:{port}")
    app.run(host=host, port=port, debug=True)

import os
import logging
import sys
import mimetypes
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, Response, abort
from werkzeug.utils import secure_filename, safe_join
from modules.db import get_conn, release_conn
from service.player import player_bp
from service.record import record_bp
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

@app.route('/compare.html')
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

@app.route('/player.html')
def player_page():
    return render_template('player.html')

@app.route('/download_tool')
def download_tool():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'video2frame.exe', as_attachment=True)

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "51005"))
    print(f"Starting server on http://{host}:{port}")
    app.run(host=host, port=port, debug=True)

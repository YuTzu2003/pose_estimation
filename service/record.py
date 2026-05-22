from flask import Blueprint, request, jsonify
from modules.db import get_conn, release_conn
import pandas as pd
import os
import shutil
import matplotlib
matplotlib.use('Agg') # Use non-GUI backend
import matplotlib.pyplot as plt
import io
import base64

record_bp = Blueprint('record', __name__)

JOBS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'jobs')

@record_bp.route('/api/records', methods=['GET'])
def get_all_records():
    player_id = request.args.get('player_id')
    conn = get_conn()
    records = []
    try:
        cursor = conn.cursor()
        if player_id:
            cursor.execute("""
                SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, 
                       R.Original_Video_Path, R.Result_Video_Path, R.Pose_csv_path, R.Created_at
                FROM Record R
                LEFT JOIN Player P ON R.Player_id = P.Player_id
                WHERE R.Player_id = ?
                ORDER BY R.Created_at DESC
            """, (player_id,))
        else:
            cursor.execute("""
                SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, 
                       R.Original_Video_Path, R.Result_Video_Path, R.Pose_csv_path, R.Created_at
                FROM Record R
                LEFT JOIN Player P ON R.Player_id = P.Player_id
                ORDER BY R.Created_at DESC
            """)
        
        rows = cursor.fetchall()
        for row in rows:
            records.append({
                'id': row[0],
                'player_id': row[1],
                'player_name': row[2] if row[2] else 'Unknown',
                'session': row[3],
                'note': row[4],
                'original_video': row[5],
                'result_video': row[6],
                'pose_csv': row[7],
                'date': row[8].strftime('%Y-%m-%d %H:%M') if row[8] else ''
            })
        return jsonify(records), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/record/<record_id>', methods=['GET'])
def get_record_details(record_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, 
                   R.Original_Video_Path, R.Result_Video_Path, R.Pose_csv_path, R.Created_at,
                   R.ValidPeaks_csv_path
            FROM Record R
            LEFT JOIN Player P ON R.Player_id = P.Player_id
            WHERE R.Record_id = ?
        """, (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
            
        record = {
            'id': row[0],
            'player_id': row[1],
            'player_name': row[2] if row[2] else 'Unknown',
            'session': row[3],
            'note': row[4],
            'original_video': row[5],
            'result_video': row[6],
            'pose_csv': row[7],
            'date': row[8].strftime('%Y-%m-%d %H:%M') if row[8] else '',
            'peaks_csv': row[9]
        }
        return jsonify(record), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/record/<record_id>', methods=['PUT'])
def update_record(record_id):
    data = request.json
    session_name = data.get('session_name')
    note = data.get('note')
    
    if not session_name:
        return jsonify({'error': 'Session name is required'}), 400
        
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE Record 
            SET Session_name = ?, Note = ?
            WHERE Record_id = ?
        """, (session_name, note, record_id))
        conn.commit()
        return jsonify({'message': 'Record updated successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/record/<record_id>', methods=['DELETE'])
def delete_record(record_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Record_id FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
            
        cursor.execute("DELETE FROM Record WHERE Record_id = ?", (record_id,))
        conn.commit()
        
        project_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'jobs', record_id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
            
        return jsonify({'message': 'Record and files deleted successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/plot_image/<record_id>', methods=['GET'])
def get_plot_image(record_id):
    part = request.args.get('part', 'Right_Ankle')
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Pose_csv_path FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            return jsonify({'error': 'CSV path not found'}), 404
            
        csv_path = row[0]
        full_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', csv_path)
        
        if not os.path.exists(full_path):
            return jsonify({'error': 'File not found'}), 404
            
        df = pd.read_csv(full_path)
        
        plt.figure(figsize=(10, 4))
        if f'{part}_X' in df.columns:
            plt.plot(df['Frame'], df[f'{part}_X'], label=f'{part} X')
        if f'{part}_Y' in df.columns:
            plt.plot(df['Frame'], df[f'{part}_Y'], label=f'{part} Y')
        
        plt.title(f'Movement Curve - {part}')
        plt.xlabel('Frame')
        plt.ylabel('Coordinate (px)')
        plt.legend()
        plt.grid(True)
        
        img = io.BytesIO()
        plt.savefig(img, format='png', bbox_inches='tight')
        img.seek(0)
        plt.close()
        
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
        return jsonify({'plot_url': f'data:image/png;base64,{plot_url}'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

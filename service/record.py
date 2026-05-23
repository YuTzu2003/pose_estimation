from flask import Blueprint, request, jsonify
from modules.db import get_conn, release_conn
import pandas as pd
import os
import shutil
import matplotlib
import matplotlib.pyplot as plt
import io
import base64
matplotlib.use('Agg')

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
                SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, R.Project_Folder, R.Created_at, R.Frame_Start, R.Frame_End FROM Record R
                LEFT JOIN Player P ON R.Player_id = P.Player_id
                WHERE R.Player_id = ?
                ORDER BY R.Created_at DESC""", (player_id,))
        else:
            cursor.execute("""
                SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, R.Project_Folder, R.Created_at, R.Frame_Start, R.Frame_End FROM Record R
                LEFT JOIN Player P ON R.Player_id = P.Player_id
                ORDER BY R.Created_at DESC""")
        
        rows = cursor.fetchall()
        for row in rows:
            record_id = row[0]
            project_folder = row[5]
            
            # Dynamically find paths
            original_video = None
            result_video = None
            pose_csv = None
            
            abs_project_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', project_folder)
            if os.path.exists(abs_project_dir):
                for f in os.listdir(abs_project_dir):
                    if f.endswith('_pose.csv'): pose_csv = f"{project_folder}/{f}"
                    elif f.startswith(record_id):
                        if any(x in f for x in ['_gait', '_result']): result_video = f"{project_folder}/{f}"
                        elif not any(x in f for x in ['_peaks', '_imu']): 
                            ext = os.path.splitext(f)[1].lower()
                            if ext in ['.mp4', '.avi', '.mov']: original_video = f"{project_folder}/{f}"

            records.append({
                'id': record_id,
                'player_id': row[1],
                'player_name': row[2] if row[2] else 'Unknown',
                'session': row[3],
                'note': row[4],
                'project_folder': project_folder,
                'original_video': original_video,
                'result_video': result_video,
                'pose_csv': pose_csv,
                'date': row[6].strftime('%Y-%m-%d %H:%M') if row[6] else '',
                'frame_start': row[7],
                'frame_end': row[8]
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
            SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, R.Project_Folder, R.Created_at, R.Frame_Start, R.Frame_End FROM Record R
            LEFT JOIN Player P ON R.Player_id = P.Player_id
            WHERE R.Record_id = ?""", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
        
        project_folder = row[5]
        
        # Dynamically find paths
        original_video = None
        result_video = None
        pose_csv = None
        peaks_csv = None
        imu_csv = None
        
        abs_project_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', project_folder)
        if os.path.exists(abs_project_dir):
            for f in os.listdir(abs_project_dir):
                if f.endswith('_pose.csv'): pose_csv = f"{project_folder}/{f}"
                elif f.endswith('_peaks.csv'): peaks_csv = f"{project_folder}/{f}"
                elif f.endswith('_imu.csv'): imu_csv = f"{project_folder}/{f}"
                elif f.startswith(record_id):
                    if f.endswith('_result.mp4'): result_video = f"{project_folder}/{f}"
                    elif f.endswith('_pose.mp4'): original_video = f"{project_folder}/{f}"
                    elif not any(x in f for x in ['_peaks', '_imu', '.csv']): 
                        ext = os.path.splitext(f)[1].lower()
                        if ext in ['.mp4', '.avi', '.mov']: original_video = f"{project_folder}/{f}"

        record = {
            'id': row[0],
            'player_id': row[1],
            'player_name': row[2] if row[2] else 'Unknown',
            'session': row[3],
            'note': row[4],
            'project_folder': project_folder,
            'original_video': original_video,
            'result_video': result_video,
            'pose_csv': pose_csv,
            'peaks_csv': peaks_csv,
            'imu_csv_path': imu_csv,
            'date': row[6].strftime('%Y-%m-%d %H:%M') if row[6] else '',
            'frame_start': row[7],
            'frame_end': row[8]
        }
        return jsonify(record), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
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
        cursor.execute("""UPDATE Record SET Session_name = ?, Note = ? WHERE Record_id = ?""", (session_name, note, record_id))
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
        cursor.execute("SELECT Project_Folder FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
            
        project_folder = row[0]
        cursor.execute("DELETE FROM Record WHERE Record_id = ?", (record_id,))
        conn.commit()
        
        abs_project_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', project_folder)
        if os.path.exists(abs_project_dir):
            shutil.rmtree(abs_project_dir)
            
        return jsonify({'message': 'Record and files deleted successfully'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/record/<record_id>/imu', methods=['DELETE'])
def delete_record_imu(record_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Project_Folder FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
            
        project_folder = row[0]
        abs_project_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', project_folder)
        
        if os.path.exists(abs_project_dir):
            for f in os.listdir(abs_project_dir):
                if '_imu' in f:
                    try: os.remove(os.path.join(abs_project_dir, f))
                    except: pass
            
        return jsonify({'message': 'IMU data deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/plot_image/<record_id>', methods=['GET'])
def get_plot_image(record_id):
    part = request.args.get('part', 'Right_Ankle')
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Project_Folder FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
            
        project_folder = row[0]
        abs_project_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', project_folder)
        
        # Find pose CSV
        csv_path = None
        if os.path.exists(abs_project_dir):
            for f in os.listdir(abs_project_dir):
                if f.endswith('_pose.csv'):
                    csv_path = os.path.join(abs_project_dir, f)
                    break
        
        if not csv_path or not os.path.exists(csv_path):
            return jsonify({'error': 'Pose CSV file not found'}), 404
            
        df = pd.read_csv(csv_path)
        
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

@record_bp.route('/api/imu_plot/<record_id>', methods=['GET'])
def get_imu_plot(record_id):
    plot_type = request.args.get('type', 'acc_res')
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Project_Folder FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
            
        project_folder = row[0]
        abs_project_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', project_folder)
        
        # Find IMU CSV
        csv_path = None
        if os.path.exists(abs_project_dir):
            for f in os.listdir(abs_project_dir):
                if f.endswith('_imu.csv'):
                    csv_path = os.path.join(abs_project_dir, f)
                    break
        
        if not csv_path or not os.path.exists(csv_path):
            return jsonify({'error': 'IMU data file not found'}), 404
            
        df = pd.read_csv(csv_path)
        
        # Reset to default style for white background
        plt.style.use('default')
        plt.figure(figsize=(12, 5))
        
        time_x = df['Time']
        title = "IMU Analysis"
        ylabel = "Value"

        if plot_type == 'acc_res':
            plt.plot(time_x, df['Acc_Res'], color='black', label='Resultant Acc')
            title = "Resultant Acceleration"
            ylabel = "m/s^2"
        elif plot_type == 'acc_xyz':
            plt.plot(time_x, df['Acc_X'], label='Acc X', alpha=0.8)
            plt.plot(time_x, df['Acc_Y'], label='Acc Y', alpha=0.8)
            plt.plot(time_x, df['Acc_Z'], label='Acc Z', alpha=0.8)
            title = "Combined Acceleration (X, Y, Z)"
            ylabel = "m/s^2"
        elif plot_type == 'gyr_xyz':
            plt.plot(time_x, df['Gyr_X'], label='Gyr X', alpha=0.8)
            plt.plot(time_x, df['Gyr_Y'], label='Gyr Y', alpha=0.8)
            plt.plot(time_x, df['Gyr_Z'], label='Gyr Z', alpha=0.8)
            title = "Combined Angular Velocity (X, Y, Z)"
            ylabel = "deg/s"
        elif plot_type.startswith('acc_'):
            axis = plot_type.split('_')[1].upper()
            plt.plot(time_x, df[f'Acc_{axis}'], label=f'Acc {axis}', color='C0')
            title = f"Acceleration - {axis} Axis"
            ylabel = "m/s^2"
        elif plot_type.startswith('gyr_'):
            axis = plot_type.split('_')[1].upper()
            plt.plot(time_x, df[f'Gyr_{axis}'], label=f'Gyr {axis}', color='C3')
            title = f"Angular Velocity - {axis} Axis"
            ylabel = "deg/s"

        plt.title(title)
        plt.xlabel('Time / Index')
        plt.ylabel(ylabel)
        plt.legend(loc='upper right')
        plt.grid(True, linestyle='--', alpha=0.6)
        
        img = io.BytesIO()
        plt.savefig(img, format='png', bbox_inches='tight', facecolor='white')
        img.seek(0)
        plt.close()
        
        plot_url = base64.b64encode(img.getvalue()).decode('utf8')
        return jsonify({'plot_url': f'data:image/png;base64,{plot_url}'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

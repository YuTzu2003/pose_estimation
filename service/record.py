from flask import Blueprint, request, jsonify, current_app
from modules.db import get_conn, release_conn
from modules.pipeline.backbone_detect import get_person_records
from modules.pipeline.pose_angle_track import run_pose_analysis
from modules.pipeline.peak_smooth import peak_smooth
from modules.pipeline.step_metrics import run_step
from modules.pipeline.imu_process import process_imu_data
import pandas as pd
import numpy as np
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
                SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, R.Project_Folder, R.Created_at, R.Frame_Start, R.Frame_End, R.Scale_Reference, R.Scale_Pixels FROM Record R
                LEFT JOIN Player P ON R.Player_id = P.Player_id
                WHERE R.Player_id = ?
                ORDER BY R.Created_at DESC""", (player_id,))
        else:
            cursor.execute("""
                SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, R.Project_Folder, R.Created_at, R.Frame_Start, R.Frame_End, R.Scale_Reference, R.Scale_Pixels FROM Record R
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
            
            abs_project_dir = os.path.join(current_app.root_path, 'static', project_folder)
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
                'frame_end': row[8],
                'scale_reference': row[9],
                'scale_pixels': row[10]
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
            SELECT R.Record_id, R.Player_id, P.Name, R.Session_name, R.Note, R.Project_Folder, R.Created_at, R.Frame_Start, R.Frame_End, R.Scale_Reference, R.Scale_Pixels FROM Record R
            LEFT JOIN Player P ON R.Player_id = P.Player_id
            WHERE R.Record_id = ?""", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Record not found'}), 404
        
        project_folder = row[5]
        abs_project_dir = os.path.join(current_app.root_path, 'static', project_folder)
        
        # Dynamically find paths
        original_video = None
        result_video = None
        pose_csv = None
        peaks_csv = None
        imu_csv = None
        
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

        # Load Pose Data (Detailed)
        pose_data = []
        if pose_csv:
            csv_path = os.path.join(current_app.root_path, 'static', pose_csv)
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                angle_cols = {'Right_Knee_Angle': 'knee', 'Right_Hip_Angle': 'hip', 'Right_Ankle_Angle': 'ankle', 'Right_Shoulder_Angle': 'shoulder', 'Right_Elbow_Angle': 'elbow'}
                available_cols = {v: k for k, v in angle_cols.items() if k in df.columns}
                if not available_cols:
                    available_cols = {c.lower(): c for c in df.columns if c.lower() in ['knee', 'hip', 'ankle', 'shoulder', 'elbow']}
                for _, r in df.iterrows():
                    entry = {}
                    for target, src in available_cols.items():
                        entry[target] = float(r[src]) if not pd.isna(r[src]) else 0
                    pose_data.append(entry)

        # Load IMU Data (Detailed)
        imu_data = []
        if imu_csv:
            imu_path = os.path.join(current_app.root_path, 'static', imu_csv)
            if os.path.exists(imu_path):
                df_imu = pd.read_csv(imu_path)
                for _, r in df_imu.iterrows():
                    entry = {}
                    for col in ['acc_res', 'acc_x', 'acc_y', 'acc_z', 'gyr_x', 'gyr_y', 'gyr_z']:
                        if col in df_imu.columns:
                            entry[col] = float(r[col]) if not pd.isna(r[col]) else 0
                        elif col.replace('_', ' ') in df_imu.columns:
                            entry[col] = float(r[col.replace('_', ' ')])
                    imu_data.append(entry)

        # Read analysis_info.json
        analysis_info = {}
        json_path = os.path.join(abs_project_dir, 'analysis_info.json')
        if os.path.exists(json_path):
            try:
                import json
                with open(json_path, 'r', encoding='utf-8') as f:
                    analysis_info = json.load(f)
            except Exception as e:
                print(f"Error reading analysis_info.json: {e}")

        record_data = {
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
            'frame_end': row[8],
            'scale_reference': row[9],
            'scale_pixels': row[10],
            'pose_data': pose_data,
            'imu_data': imu_data,
            'modules': analysis_info.get('modules', [])
        }

        return jsonify(record_data), 200
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/player_records/<player_id>', methods=['GET'])
def get_player_records(player_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT Record_id, Session_name, Created_at, Project_Folder
            FROM Record WHERE Player_id = ? 
            ORDER BY Created_at DESC
        """, (player_id,))
        rows = cursor.fetchall()
        records = []
        for r in rows:
            record_id = r[0]
            project_folder = r[3]
            # Reconstruct result video path
            result_video = None
            abs_project_dir = os.path.join(current_app.root_path, 'static', project_folder)
            if os.path.exists(abs_project_dir):
                for f in os.listdir(abs_project_dir):
                    if f.startswith(record_id) and any(x in f for x in ['_gait', '_result']):
                        result_video = f"{project_folder}/{f}"
                        break
            
            records.append({
                'Record_id': record_id,
                'Session_name': r[1],
                'Created_at': r[2].strftime("%Y-%m-%d %H:%M"),
                'Project_Folder': project_folder,
                'Result_Video_Path': result_video
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        release_conn(conn)

@record_bp.route('/api/append_data', methods=['POST'])
def append_data():
    record_id = request.form.get('record_id')
    if not record_id: return jsonify({'error': 'Missing record_id'}), 400
    
    video_file = request.files.get('video')
    imu_file = request.files.get('imu_file')
    project_dir = os.path.join(current_app.root_path, 'static', 'jobs', record_id)
    
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
            
            person_records = get_person_records(abs_video_path)
            res_video, res_csv = run_pose_analysis(abs_video_path, project_dir, record_id, person_records)
            
            pose_csv_abs = os.path.join(project_dir, res_csv)
            peaks_csv_abs = os.path.join(project_dir, f"{record_id}_peaks.csv")
            
            if peak_smooth(pose_csv_abs, peaks_csv_abs):
                gait_video_name = f"{record_id}_gait.mp4"
                gait_video_abs = os.path.join(project_dir, gait_video_name)
                ratio = float(scale_reference) / float(scale_pixels)
                run_step(os.path.join(project_dir, res_video), peaks_csv_abs, gait_video_abs, ratio=ratio, person_records=person_records)

            frame_start = 0
            frame_end = 0
            if person_records and len(person_records) > 0:
                frame_start = int(person_records[0][0])
                frame_end = int(person_records[0][1])
            cursor.execute("""UPDATE Record SET Frame_Start = ?, Frame_End = ? WHERE Record_id = ?""", (frame_start, frame_end, record_id))

        if imu_file:
            imu_ext = os.path.splitext(imu_file.filename)[1] or ".csv"
            imu_filename = f"{record_id}_imu_orig{imu_ext}"
            abs_imu_path = os.path.join(project_dir, imu_filename)
            imu_file.save(abs_imu_path)
            process_imu_data(abs_imu_path, project_dir, record_id)
        conn.commit()
        return jsonify({'success': True, 'message': '資料已成功補齊'})
    except Exception as e:
        conn.rollback()
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
        elif plot_type == 'acc_integral':
            # User formula: (data1 + data2) * 0.0083 / 2
            acc_res = df['Acc_Res'].values
            dt = 0.0083
            integral_vals = (acc_res[:-1] + acc_res[1:]) * dt / 2.0
            # Time for these values starts from the second record (index 1)
            time_integral = time_x[1:]
            plt.plot(time_integral, integral_vals, color='purple', label='Integrated Acc')
            title = "Integrated Acceleration (Velocity Change)"
            ylabel = "m/s"
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

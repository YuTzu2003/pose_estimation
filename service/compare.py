from flask import Blueprint, request, jsonify, current_app
from modules.db import get_conn, release_conn
import pandas as pd
import os
import matplotlib
import matplotlib.pyplot as plt
import io
import base64
import numpy as np

matplotlib.use('Agg')
compare_bp = Blueprint('compare_service', __name__)

def get_project_path(record_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Project_Folder FROM Record WHERE Record_id = ?", (record_id,))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        release_conn(conn)

def generate_base64_plot(df_list, labels, title, ylabel, columns_list, colors=None, dash_styles=None):
    plt.style.use('default')
    plt.figure(figsize=(10, 4))
    
    any_plotted = False
    for i, df in enumerate(df_list):
        if df is not None and not df.empty:
            label = labels[i]
            color = colors[i] if colors else None
            dash = dash_styles[i] if dash_styles else None
            cols = columns_list[i]
            
            for col in cols:
                if col in df.columns:
                    plt.plot(df.index, df[col], label=f"{label} ({col})", color=color, linestyle=dash or '-')
                    any_plotted = True

    if not any_plotted:
        plt.text(0.5, 0.5, 'No Data to Plot', ha='center', va='center')

    plt.title(title)
    plt.xlabel('Frame / Time Index')
    plt.ylabel(ylabel)
    plt.legend(loc='upper right', fontsize='small')
    plt.grid(True, linestyle='--', alpha=0.6)
    
    img = io.BytesIO()
    plt.savefig(img, format='png', bbox_inches='tight', facecolor='white')
    img.seek(0)
    plt.close()
    return base64.b64encode(img.getvalue()).decode('utf8')

@compare_bp.route('/api/compare_charts', methods=['POST'])
def compare_charts():
    try:
        data = request.json
        id_a = data.get('id_a')
        id_b = data.get('id_b')
        compare_type = data.get('type') # 'skeleton' or 'imu'
        metric = data.get('metric')

        print(f"[DEBUG] Comparing {id_a} vs {id_b}, type={compare_type}, metric={metric}")

        folder_a = get_project_path(id_a)
        folder_b = get_project_path(id_b)

        suffix = "_pose.csv" if compare_type == 'skeleton' else "_imu.csv"
        
        def load_data(record_id, folder):
            if not folder: return None
            abs_path = os.path.join(current_app.root_path, 'static', folder)
            if not os.path.exists(abs_path): return None
            for f in os.listdir(abs_path):
                if f.endswith(suffix):
                    return pd.read_csv(os.path.join(abs_path, f))
            return None

        df_a = load_data(id_a, folder_a)
        df_b = load_data(id_b, folder_b)

        # Map Metrics to Columns
        def get_cols(df, m, t):
            if df is None: return []
            if t == 'skeleton':
                mapping = {'knee':'Knee', 'hip':'Hip', 'ankle':'Ankle', 'shoulder':'Shoulder', 'elbow':'Elbow'}
                target = mapping.get(m, m)
                found = [c for c in df.columns if target.lower() in c.lower()]
                return found if found else []
            else: # IMU
                if m == 'acc_xyz': return ['Acc_X', 'Acc_Y', 'Acc_Z']
                if m == 'gyr_xyz': return ['Gyr_X', 'Gyr_Y', 'Gyr_Z']
                return ['Acc_Res'] if 'Acc_Res' in df.columns else []

        cols_a = get_cols(df_a, metric, compare_type)
        cols_b = get_cols(df_b, metric, compare_type)

        ylabel = "Angle (deg)" if compare_type == 'skeleton' else "Value"
        
        # 1. Base Chart A
        chart_a = generate_base64_plot([df_a], ["Base"], f"Record A: {id_a}", ylabel, [cols_a], colors=['#171717'])
        # 2. Control Chart B
        chart_b = generate_base64_plot([df_b], ["Control"], f"Record B: {id_b}", ylabel, [cols_b], colors=['#dc3545'])
        # 3. Merged Chart
        merged = generate_base64_plot([df_a, df_b], ["A", "B"], "Merged Comparison View", ylabel, [cols_a, cols_b], 
                                      colors=['#171717', '#dc3545'], dash_styles=['-', '--'])

        return jsonify({
            'chart_a': f"data:image/png;base64,{chart_a}",
            'chart_b': f"data:image/png;base64,{chart_b}",
            'merged': f"data:image/png;base64,{merged}"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

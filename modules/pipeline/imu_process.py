import pandas as pd
import os
import logging
import numpy as np

logger = logging.getLogger(__name__)

def process_imu_data(file_path, output_dir, record_id):
    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.csv':
            try:
                df = pd.read_csv(file_path)
                if len(df.columns) < 3:
                    df_tab = pd.read_csv(file_path, sep='\t')
                    if len(df_tab.columns) > len(df.columns):
                        df = df_tab
            except Exception:
                df = pd.read_csv(file_path, sep='\t')
        elif ext in ['.xls', '.xlsx']:
            df = pd.read_excel(file_path)
        else:
            return None, "Unsupported file format"

        # 2. Identify columns
        cols = df.columns.tolist()
        acc_map = {'x': None, 'y': None, 'z': None}
        gyr_map = {'x': None, 'y': None, 'z': None}
        time_col = None
        
        # Potential names (expanded for better validation)
        acc_names = {
            'x': ['acc_x', 'acc x', 'acc-x', 'acceleration x', 'accx', 'acc_x (m/s^2)'],
            'y': ['acc_y', 'acc y', 'acc-y', 'acceleration y', 'accy', 'acc_y (m/s^2)'],
            'z': ['acc_z', 'acc z', 'acc-z', 'acceleration z', 'accz', 'acc_z (m/s^2)']
        }
        gyr_names = {
            'x': ['gyr_x', 'gyr x', 'gyr-x', 'gyro x', 'gyrx', 'gyro_x', 'gyr_x (deg/s)'],
            'y': ['gyr_y', 'gyr y', 'gyr-y', 'gyro y', 'gyry', 'gyro_y', 'gyr_y (deg/s)'],
            'z': ['gyr_z', 'gyr z', 'gyr-z', 'gyro z', 'gyrz', 'gyro_z', 'gyr_z (deg/s)']
        }

        for c in cols:
            cl = str(c).lower()
            if 'time' in cl or 'packet' in cl:
                time_col = c
            for axis in ['x', 'y', 'z']:
                if any(n == cl or n in cl for n in acc_names[axis]):
                    if not acc_map[axis]: acc_map[axis] = c
                if any(n == cl or n in cl for n in gyr_names[axis]):
                    if not gyr_map[axis]: gyr_map[axis] = c

        std_df = pd.DataFrame()
        if time_col:
            std_df['Time'] = df[time_col]
        else:
            std_df['Time'] = df.index
            
        found_acc = all(acc_map.values())
        if found_acc:
            std_df['Acc_X'] = pd.to_numeric(df[acc_map['x']], errors='coerce')
            std_df['Acc_Y'] = pd.to_numeric(df[acc_map['y']], errors='coerce')
            std_df['Acc_Z'] = pd.to_numeric(df[acc_map['z']], errors='coerce')
            std_df['Acc_Res'] = np.sqrt(std_df['Acc_X']**2 + std_df['Acc_Y']**2 + std_df['Acc_Z']**2)
            
        found_gyr = all(gyr_map.values())
        if found_gyr:
            std_df['Gyr_X'] = pd.to_numeric(df[gyr_map['x']], errors='coerce')
            std_df['Gyr_Y'] = pd.to_numeric(df[gyr_map['y']], errors='coerce')
            std_df['Gyr_Z'] = pd.to_numeric(df[gyr_map['z']], errors='coerce')

        if not found_acc and not found_gyr:
            return None, "Could not identify standard IMU columns"
 
        std_csv_filename = f"{record_id}_imu_std.csv"
        std_csv_path = os.path.join(output_dir, std_csv_filename)
        std_df.to_csv(std_csv_path, index=False)

        return std_csv_filename, None

    except Exception as e:
        logger.error(f"Error processing IMU: {e}")
        return None, str(e)
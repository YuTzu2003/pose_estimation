import requests
from flask import Blueprint, request, jsonify

LINE_CHANNEL_ACCESS_TOKEN = "1PkB7skbzKdLeeU1cho5Gt59XE/ktHG3yQ1AqeXmYSa5wX1x7kvLheGUFU6vFS7YvDfeqzrKc2Q17o8iObXoEUw+KWyhn4mp/u+wPuLe4BJmfUoQppujent605vkkhnX6eUfcxIc6/s2/2qUYymUmQdB04t89/1O/w1cDnyilFU="

line_notify_bp = Blueprint('line_notify', __name__)

@line_notify_bp.route('/api/line_notify', methods=['POST'])
def line_notify():
    data = request.json
    record_id = data.get('record_id')
    athlete_name = data.get('athlete_name', '未知選手')
    session_name = data.get('session_name', '未指定場次')
    modules = data.get('modules', [])
    
    if not record_id:
        return jsonify({'error': 'Missing record_id'}), 400
        
    try:
        # Format modules string
        module_map = {'angle': '關節角度', 'track': '點位追蹤', 'gait': '步幅與速度'}
        module_names = [module_map.get(m, m) for m in modules]
        analysis_str = "、".join(module_names) if module_names else "基礎分析"

        # Current timestamp
        from datetime import datetime
        completion_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        message = (
            f"【運動表現分析報告 - 任務完成通知】\n"
            f"--------------------------------\n"
            f"● 選手姓名：{athlete_name}\n"
            f"● 測試場次：{session_name}\n"
            f"● 分析項目：{analysis_str}\n"
            f"● 完成時間：{completion_time}\n"
            f"--------------------------------\n"
            f"分析專案已成功保存至系統。"
        )
        
        result = broadcast_line_message(message)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        print(f"LINE notification error: {e}")
        return jsonify({'error': str(e)}), 500

def broadcast_line_message(text):
    """
    Sends a broadcast message to all users who have added the bot as a friend.
    """
    url = "https://api.line.me/v2/bot/message/broadcast"

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Status Code:", r.status_code)
        print("Response:", r.text)
        r.raise_for_status()
        return r.json() if r.text else {}
    except requests.exceptions.RequestException as e:
        print(f"[LINE ERROR] {e}")
        return None

def send_save_notification(record_id, session_name):
    """
    Formats and sends a notification for saving a project via broadcast.
    """
    message = (
        f"【專案保存成功】\n"
        f"----------------------\n"
        f"場次：{session_name}\n"
        f"紀錄 ID：{record_id}\n"
        f"----------------------\n"
        f"分析專案已完整保存至系統。"
    )
    return broadcast_line_message(message)

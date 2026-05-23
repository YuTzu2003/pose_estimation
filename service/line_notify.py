import requests

LINE_CHANNEL_ACCESS_TOKEN = "1PkB7skbzKdLeeU1cho5Gt59XE/ktHG3yQ1AqeXmYSa5wX1x7kvLheGUFU6vFS7YvDfeqzrKc2Q17o8iObXoEUw+KWyhn4mp/u+wPuLe4BJmfUoQppujent605vkkhnX6eUfcxIc6/s2/2qUYymUmQdB04t89/1O/w1cDnyilFU="

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

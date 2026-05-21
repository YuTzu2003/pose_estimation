import string
import random
from flask import Blueprint, request, jsonify
from modules.db import get_conn, release_conn

player_bp = Blueprint('player', __name__)

@player_bp.route('/player', methods=['POST'])
def player():
    name = request.form.get('name')
    gender = request.form.get('gender')
    birthdate = request.form.get('birthdate')
    height = request.form.get('height')
    weight = request.form.get('weight')
    sport = request.form.get('sport')

    chars = string.ascii_uppercase + string.digits
    player_id = 'P' + ''.join(random.choices(chars, k=4))
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO Player (Player_id, Name, Gender, BirthDate, Height, Weight, Sport) VALUES (?, ?, ?, ?, ?, ?, ?)""", (player_id, name, gender, birthdate, height, weight, sport))
        conn.commit()
        return jsonify({'message': f'選手建檔成功！系統編號為: {player_id}'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)

@player_bp.route('/get_players', methods=['GET'])
def get_players():
    conn = get_conn()
    players = []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT Player_id, Name, Sport, Created_at, Gender, BirthDate, Height, Weight FROM Player ORDER BY Created_at DESC")
        rows = cursor.fetchall()
        for row in rows:
            players.append({
                'id': row[0],
                'name': row[1],
                'sport': row[2] if row[2] else '',
                'date': row[3].strftime('%Y-%m-%d') if row[3] else '',
                'gender': row[4] if row[4] else '',
                'birthdate': row[5].strftime('%Y-%m-%d') if row[5] else '',
                'height': row[6] if row[6] else '',
                'weight': row[7] if row[7] else ''
            })
        return jsonify(players), 200
    except Exception as e:
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)

@player_bp.route('/delete_player/<player_id>', methods=['DELETE'])
def delete_player(player_id):
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Player WHERE Player_id = ?", (player_id,))
        conn.commit()
        return jsonify({'message': '選手資料已刪除'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)

@player_bp.route('/update_player', methods=['POST'])
def update_player():
    player_id = request.form.get('id')
    name = request.form.get('name')
    gender = request.form.get('gender')
    birthdate = request.form.get('birthdate')
    height = request.form.get('height')
    weight = request.form.get('weight')
    sport = request.form.get('sport')
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE Player 
            SET Name = ?, Gender = ?, BirthDate = ?, Height = ?, Weight = ?, Sport = ? 
            WHERE Player_id = ?
        """, (name, gender, birthdate, height, weight, sport, player_id))
        conn.commit()
        return jsonify({'message': '選手資料已更新'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'資料庫錯誤: {str(e)}'}), 500
    finally:
        release_conn(conn)

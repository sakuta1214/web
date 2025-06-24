import sqlite3
import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)
DATABASE = 'database.db'

def get_db():
    """データベースへの接続を取得する関数"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """データベースのテーブルを全項目対応で初期化する関数"""
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, age INTEGER, email_address TEXT UNIQUE, password TEXT,
                phone TEXT, gender TEXT, blood_type TEXT, doctor TEXT,
                photo_path TEXT, contact_name TEXT, contact_relation TEXT,
                contact_phone TEXT,
                disease_name TEXT, since_date TEXT, disease_memo TEXT,
                allergy_name TEXT, allergy_memo TEXT, med_name TEXT,
                dosage TEXT, schedule TEXT, med_memo TEXT,
                support_desc TEXT, support_memo TEXT, has_support INTEGER, daily_memo TEXT,
                device_type TEXT, in_use INTEGER, device_memo TEXT,
                response_info TEXT, response_memo TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()
        print("ユーザー情報用データベース(最終版)の初期化が完了しました。")

# --- APIエンドポイントの定義 ---

@app.route('/register_user', methods=['POST'])
def register_user():
    data = request.json
    try:
        db = get_db()
        db.execute('''INSERT INTO users (name, age, email_address, password, phone, gender, blood_type, doctor, photo_path, contact_name, contact_relation, contact_phone, disease_name, since_date, disease_memo, allergy_name, allergy_memo, med_name, dosage, schedule, med_memo, support_desc, support_memo, has_support, daily_memo, device_type, in_use, device_memo, response_info, response_memo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (data.get('name'), data.get('age'), data.get('email_address'), data.get('password'), data.get('phone'), data.get('gender'), data.get('blood_type'), data.get('doctor'), data.get('photo_path'), data.get('contact_name'), data.get('contact_relation'), data.get('contact_phone'), data.get('disease_name'), data.get('since_date'), data.get('disease_memo'), data.get('allergy_name'), data.get('allergy_memo'), data.get('med_name'), data.get('dosage'), data.get('schedule'), data.get('med_memo'), data.get('support_desc'), data.get('support_memo'), data.get('has_support'), data.get('daily_memo'), data.get('device_type'), data.get('in_use'), data.get('device_memo'), data.get('response_info'), data.get('response_memo')))
        db.commit()
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        db.close()
        return jsonify({'status': 'success', 'message': 'User registered successfully', 'user_id': user_id})
    except sqlite3.IntegrityError: return jsonify({'status': 'error', 'message': 'そのメールアドレスは既に使用されています。'}), 400
    except Exception as e:
        print(f"データベースエラー: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to register user'}), 500

@app.route('/get_users', methods=['GET'])
def get_users():
    db = get_db()
    cursor = db.execute('SELECT id, name FROM users ORDER BY id DESC')
    users_list = [dict(row) for row in cursor.fetchall()]
    db.close()
    return jsonify(users_list)

@app.route('/get_user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    db.close()
    if user is None: return jsonify({'status': 'error', 'message': 'User not found'}), 404
    return jsonify(dict(user))

@app.route('/update_user/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.json
    try:
        db = get_db()
        db.execute('''UPDATE users SET name = ?, age = ?, email_address = ?, password = ?, phone = ?, gender = ?, blood_type = ?, doctor = ?, photo_path = ?, contact_name = ?, contact_relation = ?, contact_phone = ?, disease_name = ?, since_date = ?, disease_memo = ?, allergy_name = ?, allergy_memo = ?, med_name = ?, dosage = ?, schedule = ?, med_memo = ?, support_desc = ?, support_memo = ?, has_support = ?, daily_memo = ?, device_type = ?, in_use = ?, device_memo = ?, response_info = ?, response_memo = ? WHERE id = ?''', (data.get('name'), data.get('age'), data.get('email_address'), data.get('password'), data.get('phone'), data.get('gender'), data.get('blood_type'), data.get('doctor'), data.get('photo_path'), data.get('contact_name'), data.get('contact_relation'), data.get('contact_phone'), data.get('disease_name'), data.get('since_date'), data.get('disease_memo'), data.get('allergy_name'), data.get('allergy_memo'), data.get('med_name'), data.get('dosage'), data.get('schedule'), data.get('med_memo'), data.get('support_desc'), data.get('support_memo'), data.get('has_support'), data.get('daily_memo'), data.get('device_type'), data.get('in_use'), data.get('device_memo'), data.get('response_info'), data.get('response_memo'), user_id))
        db.commit()
        db.close()
        return jsonify({'status': 'success', 'message': 'User updated successfully'})
    except Exception as e:
        print(f"データベースエラー: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to update user'}), 500

@app.route('/delete_user/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    try:
        db = get_db()
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        db.close()
        return jsonify({'status': 'success', 'message': 'User deleted successfully'})
    except Exception as e:
        print(f"データベースエラー: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to delete user'}), 500

@app.route('/search_users', methods=['GET'])
def search_users():
    """[GET] 名前に基づいてユーザーを検索するAPI"""
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    db = get_db()
    search_pattern = f'%{query}%'
    cursor = db.execute('SELECT id, name FROM users WHERE name LIKE ? ORDER BY id DESC', (search_pattern,))
    users_list = [dict(row) for row in cursor.fetchall()]
    db.close()
    return jsonify(users_list)

# --- サーバーの起動処理 ---
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
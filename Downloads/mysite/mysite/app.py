from flask import Flask, request, abort, render_template, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from datetime import datetime
import os
import logging
import firebase_admin
from firebase_admin import credentials, firestore, storage
import requests
import sys
import uuid
import config # config.pyをインポート

# ユーザーの状態を保持する辞書 (簡易的なインメモリ管理)
user_states = {}

# NGワードリスト (簡易的な実装)
NG_WORDS = ["死ね", "殺す", "バカ", "アホ", "消えろ"] # 必要に応じて追加・変更

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================
# 🔑 LINE Bot 設定
# ====================
LINE_CHANNEL_SECRET = config.LINE_CHANNEL_SECRET
LINE_CHANNEL_ACCESS_TOKEN = config.LINE_CHANNEL_ACCESS_TOKEN

# ====================
# 🔑 LINE Login 設定 (LIFF認証用)
# ====================
LINE_LOGIN_CHANNEL_ID = config.LINE_LOGIN_CHANNEL_ID
LINE_LOGIN_CHANNEL_SECRET = config.LINE_LOGIN_CHANNEL_SECRET

# ====================
# FlaskとLINE SDKの初期化
# ====================
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====================
# 💾 Firestore設定 (サービスアカウント認証)
# ====================
# 🚨 ダウンロードしたJSONファイル名に合わせて修正してください 🚨
FIREBASE_KEY_FILENAME = config.FIREBASE_KEY_FILENAME
FIREBASE_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), FIREBASE_KEY_FILENAME)

try:
    # Firebaseの初期化（プロジェクトID satounikikun を設定）
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_KEY_PATH)
        firebase_admin.initialize_app(cred, {'projectId': 'satounikikun'})

    db = firestore.client()
    bucket = storage.bucket() # Firebase Storageのデフォルトバケットを初期化
    logger.info("Firebase and Firestore connection successful.")
except Exception as e:
    logger.error(f"Firestore initialization failed: {e}")
    db = None
    bucket = None # エラー時はバケットもNoneに設定

# ====================
# 🌐 Webhook エンドポイント
# ====================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        abort(500)

    return 'OK'

@app.route('/api/user/upload_icon', methods=['POST'])
def upload_icon():
    if not db or not bucket:
        print("Firestore or Firebase Storage is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database or Storage connection failed"}), 500

    id_token = request.form.get('idToken') # FormDataから取得
    if 'icon' not in request.files:
        return jsonify({"status": "error", "message": "No icon file provided"}), 400
    
    icon_file = request.files['icon']
    if icon_file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    if not id_token:
        return jsonify({"status": "error", "message": "ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': config.LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        uploader_user_id = token_info.get('sub')

        if not uploader_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    try:
        # ファイル名を生成 (例: user_id/timestamp_originalfilename.ext)
        original_filename = icon_file.filename
        file_extension = os.path.splitext(original_filename)[1]
        unique_filename = f"{uploader_user_id}/{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}{file_extension}"

        blob = bucket.blob(unique_filename)
        blob.upload_from_file(icon_file, content_type=icon_file.content_type)
        
        # 公開URLを取得
        # Firebase Storageのセキュリティルールで公開設定が必要です
        blob.make_public() 
        public_url = blob.public_url

        return jsonify({"status": "success", "icon_path": public_url}), 200

    except Exception as e:
        print(f"Error uploading icon: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to upload icon"}), 500

# ====================
# ヘルパー関数: ユーザー作成
# ====================
def create_user_if_not_exists(user_id):
    """
    指定されたuser_idのユーザーが存在しない場合、LINEプロファイルから情報を取得してFirestoreに作成します。
    """
    try:
        # 'users' コレクションでユーザーを検索
        user_ref = db.collection('users').where('line_user_id', '==', user_id).limit(1)
        docs = user_ref.stream()

        # ユーザーが存在しない場合のみ作成
        if not any(docs):
            # LINE APIからユーザープロファイルを取得
            profile = line_bot_api.get_profile(user_id)
            display_name = profile.display_name

            # 新しいユーザーデータを準備
            new_user_data = {
                'line_user_id': user_id,
                'name': display_name,
                'school': '',
                'class_name': '',
                'icon_path': '',
                'is_registered': False, # 初期登録ステータス
                'role': 'student', # デフォルトの役割を 'student' に設定
                'class_token_id': '', # 新規追加: 生徒が参加したクラスのトークンID
                'created_at': datetime.now().isoformat()
            }

            # 'users' コレクションに新しいドキュメントを追加
            db.collection('users').add(new_user_data)
            logger.info(f"New user created: {display_name} (ID: {user_id}) with role 'student'")

    except Exception as e:
        logger.error(f"Failed to create or check user: {e}")

@app.route('/api/teacher/generate_qr', methods=['POST'])
def generate_qr_code():
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    id_token = data.get('idToken')
    class_name = data.get('class_name', '未設定のクラス') # 先生がクラス名を指定できるように

    if not id_token:
        return jsonify({"status": "error", "message": "ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        teacher_line_user_id = token_info.get('sub')

        if not teacher_line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    # リクエストしているユーザーが「teacher」ロールを持っているか確認
    teacher_user_doc = db.collection('users').where('line_user_id', '==', teacher_line_user_id).limit(1).get()
    teacher_user_data = teacher_user_doc[0].to_dict() if teacher_user_doc else {}
    
    if teacher_user_data.get('role') != 'teacher':
        return jsonify({"status": "error", "message": "Unauthorized: Only teachers can generate QR codes"}), 403

    try:
        # ユニークなクラス参加トークンを生成
        import uuid
        class_token = str(uuid.uuid4())

        # Firestoreにトークン情報を保存
        db.collection('class_tokens').add({
            'token_id': class_token,
            'teacher_line_user_id': teacher_line_user_id,
            'class_name': class_name,
            'created_at': datetime.now().isoformat(),
            'expires_at': None # 必要に応じて有効期限を設定
        })

        # 生徒がスキャンするLIFF URLを生成
        # LIFF IDはconfig.pyから取得
        liff_id = config.LIFF_ID_PRIMARY
        join_url = f"line://app/{liff_id}/join_class?token={class_token}"

        return jsonify({"status": "success", "class_token": class_token, "join_url": join_url}), 200

    except Exception as e:
        print(f"Error generating QR code: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to generate QR code"}), 500

@app.route('/api/student/join_class', methods=['POST'])
def join_class():
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    id_token = data.get('idToken')
    class_token = data.get('class_token')

    if not id_token or not class_token:
        return jsonify({"status": "error", "message": "Missing idToken or class_token"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        student_line_user_id = token_info.get('sub')

        if not student_line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    try:
        # 1. class_tokenの存在と有効性を確認
        class_token_doc = db.collection('class_tokens').where('token_id', '==', class_token).limit(1).get()
        if not class_token_doc:
            return jsonify({"status": "error", "message": "Invalid or expired class token"}), 400
        
        class_token_data = class_token_doc[0].to_dict()
        teacher_line_user_id = class_token_data.get('teacher_line_user_id')
        class_name_from_token = class_token_data.get('class_name', '')

        # 2. 生徒のユーザー情報を更新または作成
        users_ref = db.collection('users')
        query = users_ref.where('line_user_id', '==', student_line_user_id).limit(1)
        docs = query.stream()

        user_doc_id = None
        user_data = {}
        for doc in docs:
            user_doc_id = doc.id
            user_data = doc.to_dict()
            break

        update_data = {
            'is_registered': True,
            'class_token_id': class_token,
            'school': user_data.get('school', ''), # 既存の情報を保持
            'class_name': class_name_from_token, # クラス名をトークンから設定
            'updated_at': datetime.now().isoformat()
        }

        if user_doc_id:
            # 既存ユーザーの更新
            users_ref.document(user_doc_id).update(update_data)
            logger.info(f"Student {student_line_user_id} updated to join class with token {class_token}.")
        else:
            # 新規ユーザーの作成 (LIFFでプロフィールが取得できない場合を考慮)
            profile = line_bot_api.get_profile(student_line_user_id)
            display_name = profile.display_name
            new_user_data = {
                'line_user_id': student_line_user_id,
                'name': display_name,
                'school': update_data['school'],
                'class_name': update_data['class_name'],
                'icon_path': '',
                'is_registered': True, # QRコード経由なので登録済み
                'role': 'student',
                'class_token_id': class_token,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            users_ref.add(new_user_data)
            logger.info(f"New student {student_line_user_id} created and joined class with token {class_token}.")

        return jsonify({"status": "success", "message": "Successfully joined class"}), 200

    except Exception as e:
        print(f"Error joining class: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to join class"}), 500

# ====================
# ヘルパー関数: ユーザー作成
# ====================
def create_user_if_not_exists(user_id):
    """
    指定されたuser_idのユーザーが存在しない場合、LINEプロファイルから情報を取得してFirestoreに作成します。
    """
    try:
        # 'users' コレクションでユーザーを検索
        user_ref = db.collection('users').where('line_user_id', '==', user_id).limit(1)
        docs = user_ref.stream()

        # ユーザーが存在しない場合のみ作成
        if not any(docs):
            # LINE APIからユーザープロファイルを取得
            profile = line_bot_api.get_profile(user_id)
            display_name = profile.display_name

            # 新しいユーザーデータを準備
            new_user_data = {
                'line_user_id': user_id,
                'name': display_name,
                'school': '',
                'class_name': '',
                'icon_path': '',
                'is_registered': False, # 初期登録ステータス
                'role': 'student', # デフォルトの役割を 'student' に設定
                'class_token_id': '', # 新規追加: 生徒が参加したクラスのトークンID
                'created_at': datetime.now().isoformat()
            }

            # 'users' コレクションに新しいドキュメントを追加
            db.collection('users').add(new_user_data)
            logger.info(f"New user created: {display_name} (ID: {user_id}) with role 'student'")

    except Exception as e:
        logger.error(f"Failed to create or check user: {e}")

# ====================
# 💬 メッセージ処理ハンドラー
# ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    if db:
        # ユーザーが存在しない場合は作成する
        create_user_if_not_exists(user_id)

        # ユーザーデータを取得して登録状態を確認
        user_doc_ref = db.collection('users').where('line_user_id', '==', user_id).limit(1)
        user_docs = user_doc_ref.get()
        user_data = {}
        user_doc_id = None
        for doc in user_docs:
            user_data = doc.to_dict()
            user_doc_id = doc.id
            break

        is_registered = user_data.get('is_registered', False)

        # 未登録ユーザーへの初回メッセージ
        if not is_registered:
            reply_text = "アカウントを作成するには、先生から配布されるQRコードをスキャンしてクラスに参加してください。"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
            return

        # 日記投稿モードの場合
        if user_states.get(user_id) == 'waiting_for_diary_content':
            # NGワードチェック
            for ng_word in NG_WORDS:
                if ng_word in user_message:
                    reply_text = f"不適切な言葉が含まれています。日記は保存されませんでした。\n「{ng_word}」のような言葉は使用しないでください。"
                    user_states.pop(user_id, None) # 状態をリセット
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=reply_text)
                    )
                    return

            try:
                diary_data = {
                    'user_id': user_id, # LINEユーザーIDを保存
                    'content': user_message,
                    'created_at': datetime.now().isoformat()
                }
                db.collection('diaries').add(diary_data)
                reply_text = "日記を保存しました！\n他の人の日記は「投稿を見る」から確認できます。"
                logger.info(f"Diary saved for user {user_id}.")
            except Exception as e:
                logger.error(f"Failed to save diary for user {user_id}: {e}")
                reply_text = "日記の保存に失敗しました。もう一度お試しください。"
            finally:
                user_states.pop(user_id, None) # 状態をリセット

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
            return

        # コマンド処理
        if user_message == "日記を投稿":
            user_states[user_id] = 'waiting_for_diary_content'
            reply_text = "日記の内容を送信してください。"
        elif user_message == "投稿を見る":
            reply_text = "他の人の日記はこちらから見ることができます。\nline://app/2008454581-9AVyN4Jv/posts"
        elif user_message == "マイページ":
            reply_text = "あなたのマイページはこちらです。\nline://app/2008454581-9AVyN4Jv/mypage"
        elif user_message == "その他":
            reply_text = "どの項目を見ますか？\n\n規約・ルール: line://app/2008454581-9AVyN4Jv/rules\nお問い合わせ: line://app/2008454581-9AVyN4Jv/contact"
        else:
            # 1. Firestoreにメッセージを保存する (既存の処理)
            try:
                message_data = {
                    'user_id': user_id,
                    'message_text': user_message,
                    'timestamp': datetime.now().isoformat()
                }

                # 'line_messages' コレクションに新しいドキュメントを追加する
                db.collection('line_messages').add(message_data)

                logger.info("Message saved to Firestore successfully.")
                reply_text = f"メッセージを受け付けました。\n内容：{user_message}"

            except Exception as e:
                logger.error(f"FATAL: Firestore save failed with error: {e}")
                reply_text = "エラー：データの保存に失敗しました。管理者に連絡してください。"

        # 2. ユーザーに応答を返す
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    else:
        # DB接続失敗時のフォールバック処理
        reply_text = "エラー：サーバーがデータベースに接続できませんでした。"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )

# ====================
# 👤 ユーザーAPIエンドポイント
# ====================
@app.route('/api/user', methods=['POST'])
def update_user_profile():
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    id_token = data.get('idToken')
    name = data.get('name')
    school = data.get('school')
    class_name = data.get('class') # 'class'はPythonの予約語なので'class_name'を使用

    if not id_token:
        return jsonify({"status": "error", "message": "ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        line_user_id = token_info.get('sub') # 'sub'がLINEユーザーID

        if not line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    # Firestoreでユーザー情報を更新
    try:
        users_ref = db.collection('users')
        query = users_ref.where('line_user_id', '==', line_user_id).limit(1)
        docs = query.stream()

        user_doc_id = None
        for doc in docs:
            user_doc_id = doc.id
            break

        if user_doc_id:
            update_data = {
                'name': name,
                'school': school,
                'class_name': class_name,
                'icon_path': data.get('icon_path', ''), # 追加
                'is_registered': True,
                'updated_at': datetime.now().isoformat()
            }
            db.collection('users').document(user_doc_id).update(update_data)
            return jsonify({"status": "success", "message": "Profile updated successfully"}), 200
        else:
            new_user_data = {
                'line_user_id': line_user_id,
                'name': name,
                'school': school,
                'class_name': class_name,
                'icon_path': data.get('icon_path', ''), # 追加
                'is_registered': True,
                'role': 'student',
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            db.collection('users').add(new_user_data)
            return jsonify({"status": "success", "message": "Profile created successfully"}), 201

    except Exception as e:
        print(f"Error updating user profile in Firestore: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to update profile"}), 500

@app.route('/api/user', methods=['GET'])
def get_user_profile():
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    id_token = request.headers.get('Authorization')
    if id_token and id_token.startswith('Bearer '):
        id_token = id_token.split(' ')[1]
    else:
        return jsonify({"status": "error", "message": "Authorization header with ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        line_user_id = token_info.get('sub')

        if not line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    # Firestoreからユーザー情報を取得
    try:
        users_ref = db.collection('users')
        query = users_ref.where('line_user_id', '==', line_user_id).limit(1)
        docs = query.stream()

        user_data = None
        for doc in docs:
            user_data = doc.to_dict()
            break

        if user_data:
            response_data = {
                'name': user_data.get('name', ''),
                'school': user_data.get('school', ''),
                'class': user_data.get('class_name', ''),
                'icon_path': user_data.get('icon_path', ''), # 追加
                'is_registered': user_data.get('is_registered', False),
                'role': user_data.get('role', 'student')
            }
            return jsonify({"status": "success", "data": response_data}), 200
        else:
            return jsonify({"status": "error", "message": "User profile not found"}), 404

    except Exception as e:
        print(f"Error fetching user profile from Firestore: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to fetch profile"}), 500

@app.route('/api/diaries', methods=['GET'])
def get_diaries():
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    id_token = request.headers.get('Authorization')
    if id_token and id_token.startswith('Bearer '):
        id_token = id_token.split(' ')[1]
    else:
        return jsonify({"status": "error", "message": "Authorization header with ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        requesting_line_user_id = token_info.get('sub')

        if not requesting_line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    # リクエストしているユーザーのロールを取得
    requesting_user_doc = db.collection('users').where('line_user_id', '==', requesting_line_user_id).limit(1).get()
    requesting_user_data = requesting_user_doc[0].to_dict() if requesting_user_doc else {}
    requesting_user_role = requesting_user_data.get('role', 'student')

    try:
        diaries_ref = db.collection('diaries').order_by('created_at', direction=firestore.Query.DESCENDING)
        diaries = diaries_ref.stream()

        diary_list = []
        user_cache = {} # ユーザー情報をキャッシュしてFirestoreへのアクセスを減らす
        
        # 現在のユーザーがいいねしている日記のIDを事前に取得
        user_likes_docs = db.collection('likes').where('user_id', '==', requesting_line_user_id).stream()
        user_liked_diary_ids = {doc.to_dict()['diary_id'] for doc in user_likes_docs}

        for diary in diaries:
            diary_data = diary.to_dict()
            user_id = diary_data.get('user_id')

            if user_id not in user_cache:
                user_doc = db.collection('users').where('line_user_id', '==', user_id).limit(1).get()
                user_cache[user_id] = user_doc[0].to_dict() if user_doc else {}

            author_data = user_cache.get(user_id, {})
            
            # 先生の場合は実名、それ以外は匿名表示
            author_name = author_data.get('name', '匿名ユーザー')
            if requesting_user_role != 'teacher':
                # 匿名化ロジック (例: 生徒A, 生徒B...)
                # ここでは簡易的に「生徒」+ ユーザーIDの最後の数桁を使用
                # より高度な匿名化が必要な場合は、別途ロジックを実装
                author_name = f"生徒-{user_id[-4:]}" 

            # いいね数を取得
            like_count = db.collection('likes').where('diary_id', '==', diary.id).get()
            like_count_value = len(like_count)

            # 現在のユーザーがいいねしているか
            is_liked_by_user = diary.id in user_liked_diary_ids

            diary_list.append({
                'id': diary.id,
                'author': author_name,
                'content': diary_data.get('content', ''),
                'created_at': diary_data.get('created_at', ''),
                'like_count': like_count_value,
                'is_liked_by_user': is_liked_by_user
            })
        
        return jsonify({"status": "success", "data": diary_list}), 200

    except Exception as e:
        print(f"Error fetching diaries from Firestore: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to fetch diaries"}), 500

@app.route('/api/admin/user_role', methods=['POST'])
def update_user_role():
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    id_token = data.get('idToken')
    target_user_id = data.get('target_user_id')
    new_role = data.get('new_role')

    if not id_token or not target_user_id or not new_role:
        return jsonify({"status": "error", "message": "Missing idToken, target_user_id, or new_role"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        requesting_line_user_id = token_info.get('sub')

        if not requesting_line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    # リクエストしているユーザーが「teacher」ロールを持っているか確認
    requesting_user_doc = db.collection('users').where('line_user_id', '==', requesting_line_user_id).limit(1).get()
    requesting_user_data = requesting_user_doc[0].to_dict() if requesting_user_doc else {}
    
    if requesting_user_data.get('role') != 'teacher':
        return jsonify({"status": "error", "message": "Unauthorized: Only teachers can change user roles"}), 403

    # ターゲットユーザーのロールを更新
    try:
        users_ref = db.collection('users')
        query = users_ref.where('line_user_id', '==', target_user_id).limit(1)
        docs = query.stream()

        user_doc_id = None
        for doc in docs:
            user_doc_id = doc.id
            break

        if user_doc_id:
            if new_role not in ['student', 'teacher']:
                return jsonify({"status": "error", "message": "Invalid role specified. Must be 'student' or 'teacher'."}), 400

            db.collection('users').document(user_doc_id).update({'role': new_role, 'updated_at': datetime.now().isoformat()})
            return jsonify({"status": "success", "message": f"User {target_user_id} role updated to {new_role}"}), 200
        else:
            return jsonify({"status": "error", "message": f"Target user {target_user_id} not found"}), 404

    except Exception as e:
        print(f"Error updating user role in Firestore: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to update user role"}), 500

@app.route('/api/teacher/my_students', methods=['GET'])
def get_my_students():
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    id_token = request.headers.get('Authorization')
    if id_token and id_token.startswith('Bearer '):
        id_token = id_token.split(' ')[1]
    else:
        return jsonify({"status": "error", "message": "Authorization header with ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': config.LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        teacher_line_user_id = token_info.get('sub')

        if not teacher_line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    # リクエストしているユーザーが「teacher」ロールを持っているか確認
    teacher_user_doc = db.collection('users').where('line_user_id', '==', teacher_line_user_id).limit(1).get()
    teacher_user_data = teacher_user_doc[0].to_dict() if teacher_user_doc else {}
    
    if teacher_user_data.get('role') != 'teacher':
        return jsonify({"status": "error", "message": "Unauthorized: Only teachers can view their students"}), 403

    try:
        # 先生が生成したクラス参加トークンをすべて取得
        class_tokens_docs = db.collection('class_tokens').where('teacher_line_user_id', '==', teacher_line_user_id).stream()
        teacher_class_token_ids = [doc.to_dict()['token_id'] for doc in class_tokens_docs]

        if not teacher_class_token_ids:
            return jsonify({"status": "success", "data": [], "message": "No classes or students found for this teacher"}), 200

        # これらのトークンIDを持つ生徒をすべて取得
        # Firestoreのinクエリは最大10個の要素しかサポートしないため、分割して処理
        all_students = []
        for i in range(0, len(teacher_class_token_ids), 10):
            batch_token_ids = teacher_class_token_ids[i:i+10]
            students_docs = db.collection('users').where('class_token_id', 'in', batch_token_ids).stream()
            for student_doc in students_docs:
                student_data = student_doc.to_dict()
                all_students.append({
                    'line_user_id': student_data.get('line_user_id'),
                    'name': student_data.get('name', '未登録'),
                    'school': student_data.get('school', '未登録'),
                    'class_name': student_data.get('class_name', '未登録'),
                    'icon_path': student_data.get('icon_path', ''),
                    'is_registered': student_data.get('is_registered', False),
                    'role': student_data.get('role', 'student')
                })
        
        return jsonify({"status": "success", "data": all_students}), 200

    except Exception as e:
        print(f"Error fetching students for teacher {teacher_line_user_id}: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to fetch students"}), 500

@app.route('/api/diaries/<diary_id>/like', methods=['POST'])
def like_diary(diary_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    id_token = data.get('idToken')

    if not id_token:
        return jsonify({"status": "error", "message": "ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        liking_user_id = token_info.get('sub')

        if not liking_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    try:
        # 日記が存在するか確認
        diary_ref = db.collection('diaries').document(diary_id)
        if not diary_ref.get().exists:
            return jsonify({"status": "error", "message": "Diary not found"}), 404

        likes_ref = db.collection('likes')
        # 既に「いいね」しているか確認
        existing_like = likes_ref.where('diary_id', '==', diary_id).where('user_id', '==', liking_user_id).limit(1).get()

        if existing_like:
            # 既に「いいね」している場合は削除（いいね取り消し）
            for doc in existing_like:
                likes_ref.document(doc.id).delete()
            return jsonify({"status": "success", "message": "Like removed"}), 200
        else:
            # 「いいね」を追加
            likes_ref.add({
                'diary_id': diary_id,
                'user_id': liking_user_id,
                'created_at': datetime.now().isoformat()
            })
            return jsonify({"status": "success", "message": "Like added"}), 201

    except Exception as e:
        print(f"Error processing like for diary {diary_id}: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to process like"}), 500

@app.route('/api/diaries/<diary_id>/comment', methods=['POST'])
def add_comment(diary_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    id_token = data.get('idToken')
    comment_content = data.get('content')

    if not id_token or not comment_content:
        return jsonify({"status": "error", "message": "Missing idToken or comment content"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        commenting_user_id = token_info.get('sub')

        if not commenting_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    try:
        # 日記が存在するか確認
        diary_ref = db.collection('diaries').document(diary_id)
        if not diary_ref.get().exists:
            return jsonify({"status": "error", "message": "Diary not found"}), 404

        # NGワードチェック
        for ng_word in NG_WORDS:
            if ng_word in comment_content:
                return jsonify({"status": "error", "message": f"不適切な言葉が含まれています。コメントは投稿されませんでした。\n「{ng_word}」のような言葉は使用しないでください。"}), 400

        # コメントを追加
        db.collection('comments').add({
            'diary_id': diary_id,
            'user_id': commenting_user_id,
            'content': comment_content,
            'created_at': datetime.now().isoformat()
        })
        return jsonify({"status": "success", "message": "Comment added"}), 201

    except Exception as e:
        print(f"Error adding comment for diary {diary_id}: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to add comment"}), 500

@app.route('/api/diaries/<diary_id>/comments', methods=['GET'])
def get_comments(diary_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    id_token = request.headers.get('Authorization')
    if id_token and id_token.startswith('Bearer '):
        id_token = id_token.split(' ')[1]
    else:
        return jsonify({"status": "error", "message": "Authorization header with ID Token is missing"}), 400

    # IDトークンを検証
    try:
        res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
            'id_token': id_token,
            'client_id': LINE_LOGIN_CHANNEL_ID
        })

        if res.status_code != 200:
            print(f"ID Token verification failed with status {res.status_code}: {res.text}", file=sys.stderr)
            return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

        token_info = res.json()
        requesting_line_user_id = token_info.get('sub')

        if not requesting_line_user_id:
            print("Verified ID Token does not contain 'sub' (user ID).", file=sys.stderr)
            return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

    except requests.exceptions.RequestException as e:
        print(f"Request to LINE verify endpoint failed: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "ID Token verification failed"}), 401
    except Exception as e:
        print(f"Error processing ID Token: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    # リクエストしているユーザーのロールを取得
    requesting_user_doc = db.collection('users').where('line_user_id', '==', requesting_line_user_id).limit(1).get()
    requesting_user_data = requesting_user_doc[0].to_dict() if requesting_user_doc else {}
    requesting_user_role = requesting_user_data.get('role', 'student')

    try:
        # 日記が存在するか確認
        diary_ref = db.collection('diaries').document(diary_id)
        if not diary_ref.get().exists:
            return jsonify({"status": "error", "message": "Diary not found"}), 404

        comments_ref = db.collection('comments').where('diary_id', '==', diary_id).order_by('created_at')
        comments = comments_ref.stream()

        comment_list = []
        user_cache = {} # ユーザー情報をキャッシュしてFirestoreへのアクセスを減らす

        for comment in comments:
            comment_data = comment.to_dict()
            user_id = comment_data.get('user_id')

            if user_id not in user_cache:
                user_doc = db.collection('users').where('line_user_id', '==', user_id).limit(1).get()
                user_cache[user_id] = user_doc[0].to_dict() if user_doc else {}

            author_data = user_cache.get(user_id, {})
            
            # 先生の場合は実名、それ以外は匿名表示
            author_name = author_data.get('name', '匿名ユーザー')
            if requesting_user_role != 'teacher':
                author_name = f"生徒-{user_id[-4:]}" 

            comment_list.append({
                'id': comment.id,
                'author': author_name,
                'content': comment_data.get('content', ''),
                'created_at': comment_data.get('created_at', '')
            })
        
        return jsonify({"status": "success", "data": comment_list}), 200

    except Exception as e:
        print(f"Error fetching comments for diary {diary_id}: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to fetch comments"}), 500

# ====================
# 🌐 Webページ表示ルート
# ====================
@app.route('/')
def index():
    return render_template('index.html', liff_id_primary=config.LIFF_ID_PRIMARY)

@app.route('/posts')
def posts():
    return render_template('posts.html')

@app.route('/mypage')
def mypage():
    return render_template('mypage.html')

@app.route('/rules')

def rules():

    return render_template('rules.html')



@app.route('/contact')



def contact():



    return render_template('contact.html')







@app.route('/join_class')







def join_class_page():







    return render_template('join_class.html')















@app.route('/teacher_dashboard')







def teacher_dashboard():







    return render_template('teacher_dashboard.html')
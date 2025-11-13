# ==============================================================================
# Imports
# ==============================================================================
from flask import Flask, request, abort, render_template, jsonify, redirect, url_for
from google.cloud.firestore_v1.base_query import FieldFilter
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, URIAction
from datetime import datetime
import os
import logging
import firebase_admin
from firebase_admin import credentials, firestore, storage
import requests
import sys
import uuid

from functools import wraps
import openai
import random
import re
import string

# ==============================================================================
# Configuration and Initialization
# ==============================================================================
# NGワードリスト (簡易的な実装)
NG_WORDS = ["死ね", "殺す", "バカ", "アホ", "消えろ"] # 必要に応じて追加・変更

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# LINE Bot 設定
LINE_CHANNEL_SECRET = "fe96005b5be582c09f6d8c192fbf6b06"
LINE_CHANNEL_ACCESS_TOKEN = 'SvfdWFWa+A+nrZTLlBGMPKoEf6fN/miJg93DS0benY9Jb/6fjh/5PBD/Wrz/RKJ2TLGoHhDUuGOee4hQJsHQ5gwZP0elG25qUPp8pzVbZCvhsoY7UHjki20EeU/fN7xhy07hUuJQIpdQtojgbp/pPAdB04t89/1O/w1cDnyilFU='

# LINE Login 設定 (LIFF認証用)
LINE_LOGIN_CHANNEL_ID = "2008454581"
LINE_LOGIN_CHANNEL_SECRET = "f4999a4e5ed14c42c92871ffc5a01d39"

# LIFF ID (単一のLIFFアプリを使用)
LIFF_ID_PRIMARY = "2008454581-9AVyN4Jv"

# FlaskとLINE SDKの初期化
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Firestore設定 (サービスアカウント認証)
FIREBASE_KEY_FILENAME = 'firebase-key.json'
FIREBASE_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), FIREBASE_KEY_FILENAME)

try:
    # Firebaseの初期化
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_KEY_PATH)
        firebase_admin.initialize_app(cred, {
            'projectId': 'satounikikun',
            'storageBucket': 'satounikikun.firebasestorage.app'
        })

    db = firestore.client()
    bucket = storage.bucket('satounikikun.firebasestorage.app')
    logger.info("Firebase and Firestore connection successful.")
except Exception as e:
    logger.error(f"Firestore initialization failed: {e}")
    db = None
    bucket = None

# ==============================================================================
# Decorators
# ==============================================================================
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        id_token = None
        if 'Authorization' in request.headers and request.headers['Authorization'].startswith('Bearer '):
            id_token = request.headers['Authorization'].split(' ')[1]
        elif 'idToken' in request.form:
            id_token = request.form.get('idToken')
        elif request.is_json and 'idToken' in request.get_json():
            id_token = request.get_json().get('idToken')

        if not id_token:
            return jsonify({"status": "error", "message": "ID Token is missing"}), 400

        try:
            logger.info("Attempting token verification.") # Fixed log message
            logger.info(f"Server current UTC time before token verification: {datetime.utcnow().isoformat()}Z")
            res = requests.post('https://api.line.me/oauth2/v2.1/verify', data={
                'id_token': id_token,
                'client_id': LINE_LOGIN_CHANNEL_ID
            }) # PROXY REMOVED

            if res.status_code != 200:
                logger.error(f"ID Token verification failed with status {res.status_code}: {res.text}")
                return jsonify({"status": "error", "message": "ID Token verification failed"}), 401

            token_info = res.json()
            line_user_id = token_info.get('sub')

            if not line_user_id:
                logger.error("Verified ID Token does not contain 'sub' (user ID).")
                return jsonify({"status": "error", "message": "Invalid ID Token (no user ID)"}), 401

            return f(line_user_id, *args, **kwargs)

        except requests.exceptions.RequestException as e:
            logger.error(f"Request to LINE verify endpoint failed: {e}")
            return jsonify({"status": "error", "message": "ID Token verification request failed"}), 500
        except Exception as e:
            logger.error(f"Error processing ID Token: {e}")
            return jsonify({"status": "error", "message": "Internal server error during token processing"}), 500

    return decorated_function

# ==============================================================================
# Helper Functions
# ==============================================================================
def create_user_if_not_exists(user_id):
    """
    指定されたuser_idのユーザーが存在しない場合、LINEプロファイルから情報を取得してFirestoreに作成します。
    """
    try:
        user_ref = db.collection('users').where('line_user_id', '==', user_id).limit(1)
        docs = list(user_ref.stream())

        if not docs:
            profile = line_bot_api.get_profile(user_id)
            display_name = profile.display_name
            new_user_data = {
                'line_user_id': user_id,
                'name': display_name,
                'school': '',
                'class_name': '',
                'icon_path': '',
                'is_registered': False,
                'role': 'student',
                'class_token_id': '',
                'is_posting_diary': False,
                'created_at': datetime.now().isoformat()
            }
            db.collection('users').add(new_user_data)
            logger.info(f"New user created: {display_name} (ID: {user_id}) with role 'student'")

    except Exception as e:
        logger.error(f"Failed to create or check user: {e}")

# ==============================================================================
# LINE Webhook
# ==============================================================================
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

    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text
    logger.info(f"Received message from user {user_id}: '{user_message}'")

    user_message_upper = user_message.upper()
    class_code_to_join = None

    # "join" または "参加" で始まるか、6桁の英数字コードそのものであるかをチェック
    logger.info(f"Checking message '{user_message_upper}' for join commands.")
    is_join = user_message_upper.startswith("JOIN ")
    is_sanka = user_message_upper.startswith("参加 ")
    is_code_only = bool(re.fullmatch(r'[A-Z0-9]{6}', user_message_upper))
    logger.info(f"startswith('JOIN '): {is_join}, startswith('参加 '): {is_sanka}, fullmatch(code): {is_code_only}")

    if is_join:
        class_code_to_join = user_message_upper[5:].strip()
        logger.info(f"Join command detected. Extracted code: '{class_code_to_join}'")
    elif is_sanka:
        class_code_to_join = user_message_upper[3:].strip()
        logger.info(f"Sanka command detected. Extracted code: '{class_code_to_join}'")
    elif is_code_only:
        class_code_to_join = user_message_upper
        logger.info(f"Code-only message detected: '{class_code_to_join}'")

    if class_code_to_join:
        logger.info(f"Attempting to join class with code: '{class_code_to_join}'")
        class_code = class_code_to_join
        try:
            # クラス検索
            classes_ref = db.collection('classes').where('class_code', '==', class_code).limit(1)
            class_docs = list(classes_ref.stream())
            if not class_docs:
                reply_text = f"無効なクラスコードです: {class_code}"
                logger.warning(f"Invalid class code '{class_code}' for user {user_id}.")
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

            class_doc = class_docs[0]
            class_data = class_doc.to_dict()
            logger.info(f"Found class '{class_data.get('class_name')}' for code '{class_code}'.")

            # ユーザー更新または作成
            users_ref = db.collection('users')
            user_query = users_ref.where('line_user_id', '==', user_id).limit(1)
            user_docs_list = list(user_query.stream())

            update_data = {
                'is_registered': True,
                'class_join_token': class_data.get('join_token'),
                'class_name': class_data.get('class_name'),
                'is_posting_diary': False,
                'updated_at': datetime.now().isoformat()
            }

            if user_docs_list:
                user_doc_id = user_docs_list[0].id
                users_ref.document(user_doc_id).update(update_data)
                logger.info(f"Updated user {user_id} to join class.")
            else:
                profile = line_bot_api.get_profile(user_id)
                display_name = profile.display_name
                update_data.update({
                    'line_user_id': user_id,
                    'name': display_name,
                    'role': 'student',
                    'created_at': datetime.now().isoformat()
                })
                users_ref.add(update_data)
                logger.info(f"Created new user {user_id} and joined class.")

            reply_text = f"クラス「{class_data.get('class_name')}」に参加しました！"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        except Exception as e:
            logger.error(f"join_class error for user {user_id} with code {class_code}: {e}", exc_info=True)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="クラス参加中にエラーが発生しました。"))
            return
    else:
        logger.info("Message is not a join command. Proceeding to other handlers.")

    if not db:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="エラー：サーバーがデータベースに接続できませんでした。"))
        return

    create_user_if_not_exists(user_id)

    user_doc_ref = db.collection('users').where('line_user_id', '==', user_id).limit(1)
    user_docs = list(user_doc_ref.get())
    user_data = {}
    if user_docs:
        user_data = user_docs[0].to_dict()

    if not user_data.get('is_registered', False):
        reply_text = "アカウントを作成するには、先生から配布されるQRコードをスキャンしてクラスに参加してください。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    if user_message == "クラスのページ":
        reply_text = f"""あなたのクラスページはこちらです。
line://app/{LIFF_ID_PRIMARY}/class_home"""
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    elif user_message == "マイページ":
        reply_text = f"""あなたのマイページはこちらです。
line://app/{LIFF_ID_PRIMARY}/mypage"""
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    elif user_message == "先生ダッシュボード" and user_data.get('role') == 'teacher':
        reply_text = f"""先生用ダッシュボードはこちらです。
line://app/{LIFF_ID_PRIMARY}/teacher_dashboard"""
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    elif user_message == "その他":
        reply_text = "どの項目を見ますか？"
        quick_reply_buttons = QuickReply(items=[
            QuickReplyButton(action=URIAction(label="規約・ルール", uri=f"line://app/{LIFF_ID_PRIMARY}/rules")),
            QuickReplyButton(action=URIAction(label="お問い合わせ", uri=f"line://app/{LIFF_ID_PRIMARY}/contact"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text, quick_reply=quick_reply_buttons))
        return

    else:
        # 不適切ワードチェック
        for ng_word in NG_WORDS:
            if ng_word in user_message:
                reply_text = f"""不適切な言葉が含まれています。日記は保存されませんでした。
「{ng_word}」のような言葉は使用しないでください。"""
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                return

        # ユーザードキュメント取得
        user_docs = db.collection('users').where('line_user_id', '==', user_id).limit(1).get()
        if not user_docs:
            reply_text = "ユーザー情報が見つかりません。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        user_ref = user_docs[0].reference
        user_data = user_docs[0].to_dict()

        # 🟢 「日記を投稿します」モード開始
        if user_message == "日記を投稿します":
            user_ref.update({'is_posting_diary': True})
            user_data['is_posting_diary'] = True  # ←これを追加！
            reply_text = "📝 次に送るメッセージを日記として保存します。"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # 🟢 投稿モード中なら、次のメッセージを日記として保存
        if user_data.get('is_posting_diary', False):
            try:
                class_join_token = user_data.get('class_join_token')

                if user_data.get('role') == 'teacher':
                    classes_ref = db.collection('classes') \
                        .where('teacher_line_user_id', '==', user_id) \
                        .order_by('created_at', direction=firestore.Query.DESCENDING) \
                        .limit(1)
                    class_docs = list(classes_ref.stream())
                    if class_docs:
                        class_join_token = class_docs[0].to_dict().get('class_code')

                if not class_join_token:
                    reply_text = "クラスに参加していないか、クラスが作成されていないため、日記を投稿できません。"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    return

                # Firestoreに日記を保存
                diary_data = {
                    'user_id': user_id,
                    'content': user_message,
                    'class_join_token': class_join_token,
                    'created_at': datetime.now().isoformat()
                }
                db.collection('diaries').add(diary_data)

                # 投稿モードを終了
                user_ref.update({'is_posting_diary': False})

                reply_text = """✅ 日記を保存しました！
また投稿するときは「日記を投稿します」と送ってください。"""
                logger.info(f"Diary saved for user {user_id} in class {class_join_token}.")
            except Exception as e:
                logger.error(f"Failed to save diary for user {user_id}: {e}")
                reply_text = "日記の保存に失敗しました。もう一度お試しください。"

            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return

        # ⚪️ それ以外の通常メッセージ
        else:
            reply_text = """📘 コマンドが認識されませんでした。
「日記を投稿します」と送ってみてください。"""
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
            return


# ==============================================================================
# API Endpoints
# ==============================================================================
@app.route('/api/user/upload_icon', methods=['POST'])
@token_required
def upload_icon(uploader_user_id):
    if not db or not bucket:
        print("Firestore or Firebase Storage is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database or Storage connection failed"}), 500

    if 'icon' not in request.files:
        return jsonify({"status": "error", "message": "No icon file provided"}), 400

    icon_file = request.files['icon']
    if icon_file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    try:
        original_filename = icon_file.filename
        file_extension = os.path.splitext(original_filename)[1]
        unique_filename = f"{uploader_user_id}/{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}{file_extension}"

        blob = bucket.blob(unique_filename)
        blob.upload_from_file(icon_file, content_type=icon_file.content_type)

        blob.make_public()
        public_url = blob.public_url

        return jsonify({"status": "success", "icon_path": public_url}), 200

    except Exception as e:
        print(f"Error uploading icon: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to upload icon"}), 500

@app.route('/api/teacher/classes', methods=['GET'])
@token_required
def get_classes(teacher_line_user_id):
    if not db:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        classes_ref = db.collection('classes').where('teacher_line_user_id', '==', teacher_line_user_id).order_by('created_at', direction=firestore.Query.DESCENDING)
        docs = classes_ref.stream()

        class_list = []
        for doc in docs:
            class_data = doc.to_dict()
            join_url = f"line://app/{LIFF_ID_PRIMARY}/join_class?token={class_data.get('join_token')}"

            class_list.append({
                'id': doc.id,
                'class_name': class_data.get('class_name'),
                'class_code': class_data.get('class_code'),
                'join_url': join_url,
                'created_at': class_data.get('created_at')
            })

        return jsonify({"status": "success", "data": class_list}), 200

    except Exception as e:
        logger.error(f"Error fetching classes for teacher {teacher_line_user_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch classes"}), 500

def generate_class_code(length=6):
    """ランダムなクラスコードを生成"""
    letters_and_digits = string.ascii_uppercase + string.digits
    return ''.join(random.choice(letters_and_digits) for i in range(length))

@app.route('/api/teacher/classes', methods=['POST'])
@token_required
def create_class(teacher_line_user_id):
    if not db:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    class_name = data.get('class_name')

    if not class_name:
        return jsonify({"status": "error", "message": "Class name is required"}), 400

    teacher_user_doc = db.collection('users').where('line_user_id', '==', teacher_line_user_id).limit(1).get()
    if not teacher_user_doc or teacher_user_doc[0].to_dict().get('role') != 'teacher':
        return jsonify({"status": "error", "message": "Unauthorized: Only teachers can create classes"}), 403

    try:
        join_token = str(uuid.uuid4())
        class_code = generate_class_code()

        new_class_data = {
            'class_name': class_name,
            'class_code': class_code,
            'teacher_line_user_id': teacher_line_user_id,
            'join_token': join_token,
            'created_at': datetime.now().isoformat()
        }
        db.collection('classes').add(new_class_data)

        return jsonify({"status": "success", "message": "Class created successfully", "data": new_class_data}), 201

    except Exception as e:
        logger.error(f"Error creating class for teacher {teacher_line_user_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to create class"}), 500

@app.route('/api/student/join_class', methods=['POST'])
@token_required
def join_class(student_line_user_id):
    if not db:
        logger.error("join_class: Firestore is not initialized.")
        return jsonify({"status": "error", "message": "データベース接続エラー"}), 500

    data = request.get_json()
    if not data:
        logger.warning("join_class: No JSON data received.")
        return jsonify({"status": "error", "message": "リクエストが空です。"}), 400

    # ここでLINEから送られた class_code を取得
    class_code_input = data.get('class_code')
    logger.info(f"join_class: Attempting to join with class_code: {class_code_input}")

    if not class_code_input:
        return jsonify({"status": "error", "message": "クラスコードがありません。"}), 400

    try:
        # Firestore で class_code または join_token で検索
        classes_ref = db.collection('classes').where(filter=FieldFilter("class_code", "==", class_code_input)).limit(1)
        class_docs = list(classes_ref.stream())

        # class_codeで見つからなければ、join_tokenで再検索
        if not class_docs:
            classes_ref = db.collection('classes').where(filter=FieldFilter("join_token", "==", class_code_input)).limit(1)
            class_docs = list(classes_ref.stream())

        if not class_docs:
            return jsonify({"status": "error", "message": "無効なクラスコードです。"}), 404

        class_doc = class_docs[0]
        class_data = class_doc.to_dict()
        class_name = class_data.get('class_name')

        users_ref = db.collection('users')
        user_query = users_ref.where(filter=FieldFilter("line_user_id", "==", student_line_user_id)).limit(1)
        user_docs_list = list(user_query.stream())

        user_doc_id = None
        if user_docs_list:
            user_doc_id = user_docs_list[0].id

        # ユーザーデータ更新
        update_data = {
            'is_registered': True,
            'class_code': class_code_input,
            'class_join_token': class_data.get('join_token'), # 👈 これを追加
            'class_name': class_name,
            'is_posting_diary': False,
            'updated_at': datetime.now().isoformat()
        }

        if user_doc_id:
            users_ref.document(user_doc_id).update(update_data)
            logger.info(f"User {student_line_user_id} updated to join class {class_name}")
        else:
            profile = line_bot_api.get_profile(student_line_user_id)
            display_name = profile.display_name
            update_data.update({
                'line_user_id': student_line_user_id,
                'name': display_name,
                'role': 'student',
                'created_at': datetime.now().isoformat()
            })
            users_ref.add(update_data)
            logger.info(f"New user {student_line_user_id} created and joined class {class_name}")

        return jsonify({"status": "success", "message": f"{class_name} に参加しました！"}), 200

    except Exception as e:
        logger.error(f"Error in join_class with class_code {class_code_input}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "サーバーエラーが発生しました。"}), 500

@app.route('/api/user', methods=['POST'])
@token_required
def update_user_profile(line_user_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    name = data.get('name')
    school = data.get('school')
    class_name = data.get('class')

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
                'icon_path': data.get('icon_path', ''),
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
                'icon_path': data.get('icon_path', ''),
                'is_registered': True,
                'role': 'student',
                'is_posting_diary': False,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            db.collection('users').add(new_user_data)
            return jsonify({"status": "success", "message": "Profile created successfully"}), 201

    except Exception as e:
        print(f"Error updating user profile in Firestore: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to update profile"}), 500

@app.route('/api/user', methods=['GET'])
@token_required
def get_user_profile(line_user_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

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
                'icon_path': user_data.get('icon_path', ''),
                'is_registered': user_data.get('is_registered', False),
                'role': user_data.get('role', 'student'),
                'class_join_token': user_data.get('class_join_token')
            }
            return jsonify({"status": "success", "data": response_data}), 200
        else:
            return jsonify({"status": "error", "message": "User profile not found"}), 404

    except Exception as e:
        print(f"Error fetching user profile from Firestore: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to fetch profile"}), 500

@app.route('/api/diaries', methods=['GET'])
@token_required
def get_diaries(requesting_line_user_id):
    if not db:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        user_class_join_token = None
        requesting_user_role = 'student'

        class_id_from_query = request.args.get('class_id')
        if class_id_from_query:
            class_ref = db.collection('classes').document(class_id_from_query)
            class_doc = class_ref.get()
            if not class_doc.exists:
                return jsonify({"status": "error", "message": "Class not found"}), 404

            class_data = class_doc.to_dict()
            if class_data.get('teacher_line_user_id') != requesting_line_user_id:
                return jsonify({"status": "error", "message": "Unauthorized to view this class's diaries"}), 403

            user_class_join_token = class_data.get('join_token')
            requesting_user_role = 'teacher'
        else:
            requesting_user_doc = db.collection('users').where('line_user_id', '==', requesting_line_user_id).limit(1).get()
            if not requesting_user_doc:
                return jsonify({"status": "error", "message": "User not found"}), 404

            requesting_user_data = requesting_user_doc[0].to_dict()
            user_class_join_token = requesting_user_data.get('class_join_token')
            requesting_user_role = requesting_user_data.get('role', 'student')

        if not user_class_join_token:
            return jsonify({"status": "success", "data": []}), 200

        diaries_ref = db.collection('diaries').where('class_join_token', '==', user_class_join_token).order_by('created_at', direction=firestore.Query.DESCENDING)
        diaries = diaries_ref.stream()

        diary_list = []
        user_cache = {}

        user_likes_docs = db.collection('likes').where('user_id', '==', requesting_line_user_id).stream()
        user_liked_diary_ids = {doc.to_dict()['diary_id'] for doc in user_likes_docs}

        for diary in diaries:
            diary_data = diary.to_dict()
            user_id = diary_data.get('user_id')

            if user_id not in user_cache:
                user_doc = db.collection('users').where('line_user_id', '==', user_id).limit(1).get()
                user_cache[user_id] = user_doc[0].to_dict() if user_doc else {}

            author_data = user_cache.get(user_id, {})

            author_name = author_data.get('name', '匿名ユーザー')
            if requesting_user_role != 'teacher':
                author_name = f"生徒-{user_id[-4:]}"

            like_count = len(db.collection('likes').where('diary_id', '==', diary.id).get())
            is_liked_by_user = diary.id in user_liked_diary_ids

            diary_list.append({
                'id': diary.id,
                'author': author_name,
                'content': diary_data.get('content', ''),
                'created_at': diary_data.get('created_at', ''),
                'like_count': like_count,
                'is_liked_by_user': is_liked_by_user
            })

        return jsonify({"status": "success", "data": diary_list}), 200

    except Exception as e:
        logger.error(f"Error fetching diaries: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch diaries"}), 500

@app.route('/api/admin/user_role', methods=['POST'])
@token_required
def update_user_role(requesting_line_user_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    target_user_id = data.get('target_user_id')
    new_role = data.get('new_role')

    if not target_user_id or not new_role:
        return jsonify({"status": "error", "message": "Missing target_user_id, or new_role"}), 400

    requesting_user_doc = db.collection('users').where('line_user_id', '==', requesting_line_user_id).limit(1).get()
    requesting_user_data = requesting_user_doc[0].to_dict() if requesting_user_doc else {}

    if requesting_user_data.get('role') != 'teacher':
        return jsonify({"status": "error", "message": "Unauthorized: Only teachers can change user roles"}), 403

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
@token_required
def get_my_students(teacher_line_user_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    teacher_user_doc = db.collection('users').where('line_user_id', '==', teacher_line_user_id).limit(1).get()
    teacher_user_data = teacher_user_doc[0].to_dict() if teacher_user_doc else {}

    if teacher_user_data.get('role') != 'teacher':
        return jsonify({"status": "error", "message": "Unauthorized: Only teachers can view their students"}), 403

    try:
        class_tokens_docs = db.collection('class_tokens').where('teacher_line_user_id', '==', teacher_line_user_id).stream()
        teacher_class_token_ids = [doc.to_dict()['token_id'] for doc in class_tokens_docs]

        if not teacher_class_token_ids:
            return jsonify({"status": "success", "data": [], "message": "No classes or students found for this teacher"}), 200

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

@app.route('/api/teacher/class/<class_id>', methods=['GET'])
@token_required
def get_class_details(requesting_line_user_id, class_id):
    if not db:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        class_ref = db.collection('classes').document(class_id)
        class_doc = class_ref.get()
        if not class_doc.exists:
            return jsonify({"status": "error", "message": "Class not found"}), 404

        class_data = class_doc.to_dict()
        teacher_line_user_id = class_data.get('teacher_line_user_id')

        if requesting_line_user_id != teacher_line_user_id:
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

        teacher_user_doc = db.collection('users').where('line_user_id', '==', teacher_line_user_id).limit(1).get()
        teacher_data = teacher_user_doc[0].to_dict() if teacher_user_doc else {}

        join_token = class_data.get('join_token')
        students_ref = db.collection('users').where('class_join_token', '==', join_token)
        student_docs = students_ref.stream()

        student_list = []
        for doc in student_docs:
            student = doc.to_dict()
            student_list.append({
                'name': student.get('name', '未登録'),
                'icon_path': student.get('icon_path', ''),
                'line_user_id': student.get('line_user_id')
            })

        response_data = {
            'class_name': class_data.get('class_name'),
            'teacher': {
                'name': teacher_data.get('name', '未登録'),
                'icon_path': teacher_data.get('icon_path', '')
            },
            'students': student_list
        }

        return jsonify({"status": "success", "data": response_data}), 200

    except Exception as e:
        logger.error(f"Error fetching class details for class {class_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch class details"}), 500

@app.route('/api/teacher/class/<class_id>/students', methods=['GET'])
@token_required
def get_class_students(requesting_line_user_id, class_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        class_ref = db.collection('classes').document(class_id)
        class_doc = class_ref.get()
        if not class_doc.exists:
            return jsonify({"status": "error", "message": "Class not found"}), 404

        class_data = class_doc.to_dict()
        teacher_line_user_id = class_data.get('teacher_line_user_id')

        if requesting_line_user_id != teacher_line_user_id:
            return jsonify({"status": "error", "message": "Unauthorized"}), 403

        join_token = class_data.get('join_token')
        students_ref = db.collection('users').where('class_join_token', '==', join_token)
        student_docs = students_ref.stream()

        student_list = []
        for doc in student_docs:
            student = doc.to_dict()
            student_list.append({
                'line_user_id': student.get('line_user_id'),
                'name': student.get('name', '未登録'),
                'school': student.get('school', '未登録'),
                'icon_path': student.get('icon_path', '')
            })

        return jsonify({"status": "success", "data": student_list}), 200

    except Exception as e:
        logger.error(f"Error fetching students for class {class_id}: {e}")
        return jsonify({"status": "error", "message": "Failed to fetch students"}), 500

@app.route('/api/diaries/<diary_id>/like', methods=['POST'])
@token_required
def like_diary(liking_user_id, diary_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        diary_ref = db.collection('diaries').document(diary_id)
        if not diary_ref.get().exists:
            return jsonify({"status": "error", "message": "Diary not found"}), 404

        likes_ref = db.collection('likes')
        existing_like = likes_ref.where('diary_id', '==', diary_id).where('user_id', '==', liking_user_id).limit(1).get()

        if existing_like:
            for doc in existing_like:
                likes_ref.document(doc.id).delete()
            return jsonify({"status": "success", "message": "Like removed"}), 200
        else:
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
@token_required
def add_comment(commenting_user_id, diary_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    data = request.get_json()
    comment_content = data.get('content')

    prompt = f"""次の文章からタグを抽出してください（複数ある場合はカンマ区切り）:
{comment_content}"""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=60,
        temperature=0
    )
    # OpenAI の返答からタグリストを作る
    tags_text = response.choices[0].message.content.strip()
    tags = [tag.strip() for tag in tags_text.split(",") if tag.strip()]

    if not comment_content:
        return jsonify({"status": "error", "message": "Missing comment content"}), 400

    try:
        diary_ref = db.collection('diaries').document(diary_id)
        if not diary_ref.get().exists:
            return jsonify({"status": "error", "message": "Diary not found"}), 404

        for ng_word in NG_WORDS:
            if ng_word in comment_content:
                return jsonify({"status": "error", "message": f"""不適切な言葉が含まれています。コメントは投稿されませんでした。
「{ng_word}」のような言葉は使用しないでください。"""}), 400

        db.collection('comments').add({
            'diary_id': diary_id,
            'user_id': commenting_user_id,
            'content': comment_content,
            'tags': tags,
            'created_at': datetime.now().isoformat()
        })
        return jsonify({"status": "success", "message": "Comment added"}), 201

    except Exception as e:
        print(f"Error adding comment for diary {diary_id}: {e}", file=sys.stderr)
        return jsonify({"status": "error", "message": "Failed to add comment"}), 500

@app.route('/api/diary-tags', methods=['GET'])
@token_required
def diary_tags(line_user_id):
    if not db:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        # --- Get current user's info ---
        user_query = db.collection('users').where('line_user_id', '==', line_user_id).limit(1)
        user_docs = list(user_query.stream())
        if not user_docs:
            return jsonify({"status": "error", "message": "User not found"}), 404

        user_data = user_docs[0].to_dict()
        user_class_join_token = user_data.get("class_join_token")

        personal_counts = {}
        class_counts = {}

        # --- Personal Aggregation ---
        #自分のコメントからタグを集計
        personal_comments_query = db.collection('comments').where('user_id', '==', line_user_id)
        for comment in personal_comments_query.stream():
            for tag in comment.to_dict().get('tags', []):
                personal_counts[tag] = personal_counts.get(tag, 0) + 1

        # --- Class Aggregation (Note: Inefficient for large datasets) ---
        if user_class_join_token:
            # クラスに属する日記のIDリストを取得
            class_diaries_query = db.collection('diaries').where('class_join_token', '==', user_class_join_token)
            class_diary_ids = {diary.id for diary in class_diaries_query.stream()}

            if class_diary_ids:
                # 全てのコメントを走査し、クラスの日記に紐づくものを探す
                # データ量が増えるとパフォーマンスが低下する可能性がある
                all_comments_query = db.collection('comments')
                for comment in all_comments_query.stream():
                    comment_data = comment.to_dict()
                    if comment_data.get('diary_id') in class_diary_ids:
                        for tag in comment_data.get('tags', []):
                            class_counts[tag] = class_counts.get(tag, 0) + 1

        return jsonify({
            "status": "success",
            "data": {
                "personal": personal_counts,
                "class_agg": class_counts,
                "school_agg": {} # School aggregation is disabled for performance reasons
            }
        }), 200

    except Exception as e:
        logger.error(f"Error generating diary-tags: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to generate tags"}), 500



@app.route('/api/diaries/<diary_id>/comments', methods=['GET'])
@token_required
def get_comments(requesting_line_user_id, diary_id):
    if not db:
        print("Firestore is not initialized.", file=sys.stderr)
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    requesting_user_doc = db.collection('users').where('line_user_id', '==', requesting_line_user_id).limit(1).get()
    requesting_user_data = requesting_user_doc[0].to_dict() if requesting_user_doc else {}
    requesting_user_role = requesting_user_data.get('role', 'student')

    try:
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

# ==============================================================================
# Web Page Routes
# ==============================================================================
@app.route('/')
def index():
    return render_template('index.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/posts')
def posts():
    return redirect(url_for('class_home'))

@app.route('/mypage')
def mypage():
    return render_template('mypage.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/rules')
def rules():
    return render_template('rules.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/contact')
def contact():
    return render_template('contact.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/join_class')
def join_class_page():
    return render_template('join_class.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/settings')
def settings():
    return render_template('settings.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/teacher_dashboard')
def teacher_dashboard():
    return render_template('teacher_dashboard.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/class_home')
def class_home():
    """クラスのホームページ（日記一覧）"""
    return render_template('class_home.html', liff_id_primary=LIFF_ID_PRIMARY)

@app.route('/teacher/class/<class_id>')
def class_detail_page(class_id):
    """クラス詳細ページをレンダリングする"""
    return render_template('class_detail.html', class_id=class_id, liff_id_primary=LIFF_ID_PRIMARY)
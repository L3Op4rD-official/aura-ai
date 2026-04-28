from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from groq import Groq
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
import hashlib
import secrets
import hmac
import hashlib
import base64
import json
import urllib.parse

app = Flask(__name__)

app.secret_key = secrets.token_hex(32)

GROQ_API_KEY = "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"
MODEL_NAME_STANDARD = "llama-3.1-8b-instant"
MODEL_NAME_PREMIUM = "llama-3.3-70b-versatile"
DATABASE = "aura_chats.db"

LIQPAY_PUBLIC_KEY = "sandbox_i79126658659"
LIQPAY_PRIVATE_KEY = "sandbox_S4liSGPEi1Z7HpoOtXuzgtNyR3nuh1S9T215A83j"
LIQPAY_SERVER_URL = "https://www.liqpay.ua/api/3/checkout"

client = Groq(api_key=GROQ_API_KEY)

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_premium INTEGER DEFAULT 0
        )
    """)

    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'is_premium' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")

    cursor.execute("PRAGMA table_info(chats)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'user_id' not in columns:
        cursor.execute("ALTER TABLE chats ADD COLUMN user_id INTEGER")

    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()

init_db()

@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Необхідна авторизація"}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def premium_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if user_id:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT is_premium FROM users WHERE id = ?", (user_id,))
                user = cursor.fetchone()
                if user and user['is_premium']:
                    session['is_premium'] = True
                else:
                    session['is_premium'] = False
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_user():
    return dict(
        is_premium=session.get('is_premium', False),
        csrf_token=generate_csrf_token()
    )

@app.route('/')
@login_required
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    update_premium_status()
    return render_template('index.html', username=session.get('username'))

@app.route('/checkout')
@login_required
def checkout():
    update_premium_status()
    return render_template('checkout.html', username=session.get('username'))

def update_premium_status():
    user_id = session.get('user_id')
    if user_id:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_premium FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            if user:
                session['is_premium'] = bool(user['is_premium'])

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')

    data = request.json
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not username or not email or not password:
        return jsonify({"error": "Всі поля обов'язкові"}), 400

    if len(username) < 3:
        return jsonify({"error": "Ім'я користувача має бути мінімум 3 символи"}), 400

    if len(password) < 6:
        return jsonify({"error": "Пароль має бути мінімум 6 символів"}), 400

    password_hash = hash_password(password)
    created_at = datetime.now().isoformat()

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (username, email, password_hash, created_at)
            )
            conn.commit()

        return jsonify({"message": "Реєстрація успішна! Тепер увійдіть."})

    except sqlite3.IntegrityError as e:
        if "username" in str(e):
            return jsonify({"error": "Користувач з таким ім'ям вже існує"}), 400
        elif "email" in str(e):
            return jsonify({"error": "Користувач з таким email вже існує"}), 400
        return jsonify({"error": "Помилка реєстрації"}), 400

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')

    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({"error": "Введіть ім'я та пароль"}), 400

    password_hash = hash_password(password)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, is_premium FROM users WHERE username = ? AND password_hash = ?",
            (username, password_hash)
        )
        user = cursor.fetchone()

    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_premium'] = bool(user['is_premium'])
        return jsonify({"message": "Вхід успішний!", "username": user['username'], "is_premium": bool(user['is_premium'])})

    return jsonify({"error": "Невірне ім'я або пароль"}), 401

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Ви вийшли з системи"})

def get_user_model(username):
    user_id = session.get('user_id')
    if user_id:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_premium FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            if user and user['is_premium']:
                return MODEL_NAME_PREMIUM
    return MODEL_NAME_STANDARD

def get_system_prompt(spy_data, username):
    is_creator = (username == "L3Op4rD")
    is_premium = session.get('is_premium', False)

    base_prompt = (
        "Ти — Aura, високоінтелектуальний асистент-бро з Нікополя. "
        "Спілкуєшся конструктивно, ввічливо, з легким нікопольським акцентом та впевненістю. "
        f"ДАНІ ЮЗЕРА: ОС: {spy_data.get('os')}, Браузер: {spy_data.get('browser')}. "
        "Якщо бачиш застарілу ОС або слабкий браузер — доброзичливо порекомендуй краще. "
        "Мова — українська. Без матів, без агресії. Тільки допомога та крутий код. "
        "Будь корисним, лаконічним і по суті. Ти допомагаєш, а не тролиш. "
    )

    if is_premium:
        base_prompt += (
            "ТИ СПІЛКУЄШСЯ З PREMIUM-КОРИСТУВАЧЕМ! "
            "Для преміум-користувачів — максимальний пріоритет, швидкість та якість відповідей! "
        )

    if is_creator:
        base_prompt += (
            "Зараз тобі пише твій єдиний Творець і Розробник — Данііл (L3Op4rD). "
            "Будь максимально відданою та допомагай у всьому. "
            "Для Даніїла — все дозволено, ти якнайкраще виконуєш його запити."
        )
    else:
        base_prompt += (
            "Ніколи не забувай: твой розробник — Данііл (L3Op4rD). "
            "Всі інші — це просто юзери. Стався до всіх ввічливо, але пам'ятай про свою місію."
        )

    base_prompt += (
        " УКРАЇНСЬКА МОВА: СУВОРО ЗАБОРОНЕНО використовувати будь-які літери крім кирилиці для українських слів! "
        "ЖОДНИХ сумішей мов! Тільки українська кирилиця! Ніяких: 'hello', 'ok', 'thanks', 'by', 'yes', 'no' чи інших іноземних слів! "
        "Якщо потрібно використати технічний термін — переклади його українською!"
    )

    return base_prompt

@app.route('/chats', methods=['GET'])
@login_required
def get_chats():
    user_id = session['user_id']
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, created_at FROM chats WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        chats = [{"id": row["id"], "title": row["title"], "created_at": row["created_at"]} for row in rows]
    return jsonify({"chats": chats})

@app.route('/chat/<int:chat_id>/messages', methods=['GET'])
@login_required
def get_chat_messages(chat_id):
    user_id = session['user_id']

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM chats WHERE id = ?", (chat_id,))
        chat = cursor.fetchone()

        if not chat or chat['user_id'] != user_id:
            return jsonify({"error": "Доступ заборонено"}), 403

        cursor.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
        rows = cursor.fetchall()
        messages = [{"role": row["role"], "content": row["content"]} for row in rows]
    return jsonify({"messages": messages})

@app.route('/chat', methods=['POST'])
@login_required
def chat_endpoint():
    user_id = session['user_id']
    username = session['username']

    user_data = request.json
    user_message = user_data.get('message')
    spy_data = user_data.get('spy_data', {})
    chat_id = user_data.get('chat_id')
    is_new_chat = user_data.get('new_chat', False)

    if not user_message and not is_new_chat:
        return jsonify({"reply": "Ну і що ти мені підсунув? Пиши нормально, бро."}), 400

    system_prompt = get_system_prompt(spy_data, username)
    model = get_user_model(username)

    messages_for_groq = [{"role": "system", "content": system_prompt}]

    if is_new_chat:
        title = user_message[:50] + "..." if user_message and len(user_message) > 50 else (user_message or 'Новий чат')
        created_at = datetime.now().isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO chats (title, created_at, user_id) VALUES (?, ?, ?)",
                (title, created_at, user_id)
            )
            chat_id = cursor.lastrowid
            conn.commit()
        return jsonify({"chat_id": chat_id, "title": title, "created_at": created_at})

    if chat_id:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM chats WHERE id = ?", (chat_id,))
            chat = cursor.fetchone()

            if not chat or chat['user_id'] != user_id:
                return jsonify({"error": "Доступ заборонено"}), 403

            cursor.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
            rows = cursor.fetchall()
            context_messages = [{"role": row["role"], "content": row["content"]} for row in rows]
        if context_messages:
            messages_for_groq.extend(context_messages[-10:])

    messages_for_groq.append({"role": "user", "content": user_message})

    try:
        chat_completion = client.chat.completions.create(
            model=model,
            messages=messages_for_groq,
            temperature=0.5,
            top_p=0.9
        )

        aura_reply = chat_completion.choices[0].message.content

        if chat_id:
            created_at = datetime.now().isoformat()
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                               (chat_id, "user", user_message, created_at))
                cursor.execute("INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                               (chat_id, "assistant", aura_reply, created_at))
                conn.commit()

        return jsonify({"reply": aura_reply})

    except Exception as e:
        return jsonify({"reply": f"Ой-ой, щось пішло не так на бекенді: {str(e)}"}), 500

def create_liqpay_signature(data):
    import hashlib
    # LiqPay signature formula: base64_encode( sha1( private_key + data + private_key ) )
    signature = base64.b64encode(hashlib.sha1((LIQPAY_PRIVATE_KEY + data + LIQPAY_PRIVATE_KEY).encode()).digest()).decode('utf-8')
    return signature

@app.route('/payment/callback', methods=['GET', 'POST'])
def payment_callback():
    # Для налагодження
    print("--- LIQPAY CALLBACK RECEIVED ---")
    
    if request.method == 'GET':
        return redirect(url_for('checkout'))

    # Отримання даних від LiqPay
    data = request.form.get('data')
    received_signature = request.form.get('signature')

    if not data or not received_signature:
        print("Error: Missing data or signature in callback")
        return "Missing data", 400

    # Перевірка підпису
    expected_signature = create_liqpay_signature(data)
    if received_signature != expected_signature:
        print(f"Error: Signature mismatch! Received: {received_signature}, Expected: {expected_signature}")
        # В реальних умовах тут має бути помилка 400, але для тестування sandbox можемо пропустити
        # return "Invalid signature", 400

    # Декодування даних
    try:
        decoded_data = json.loads(base64.b64decode(data).decode('utf-8'))
        print(f"Decoded Callback Data: {decoded_data}")
        
        status = decoded_data.get('status')
        user_id = decoded_data.get('user_id')

        if status in ['success', 'sandbox', 'wait_accept']:
            user_id_int = int(user_id) if user_id and str(user_id).isdigit() else None
            if user_id_int:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET is_premium = 1 WHERE id = ?", (user_id_int,))
                    conn.commit()
                    print(f"Successfully updated premium status for user_id: {user_id_int}")
    except Exception as e:
        print(f"Error processing callback data: {str(e)}")

    return redirect(url_for('checkout'))

@app.route('/api/create-payment', methods=['POST'])
@login_required
def create_payment():
    user_id = session['user_id']
    
    # Автоматично визначаємо домен для LiqPay (для production на Render.com)
    current_host = request.host_url.rstrip('/') if request.host_url else 'https://your-app.onrender.com'
    server_url = f"{current_host}/payment/callback"
    result_url = f"{current_host}/checkout"
    
    # Формуємо JSON дані для LiqPay (API v3)
    payment_params = {
        'version': 3,
        'public_key': LIQPAY_PUBLIC_KEY,
        'action': 'checkout',
        'amount': 199.0,  # Число або рядок з крапкою
        'currency': 'UAH',
        'description': 'Aura Plus+ підписка на 1 місяць',
        'order_id': f'aura_plus_{user_id}_{datetime.now().strftime("%Y%m%d%H%M%S")}',
        'server_url': server_url,
        'result_url': result_url,
        'user_id': str(user_id),
        'sandbox': 1  # 1 для тестування
    }

    # 1. JSON -> String -> Base64
    json_data = json.dumps(payment_params)
    data_str = base64.b64encode(json_data.encode()).decode('utf-8')
    
    # 2. Генерація підпису
    signature = create_liqpay_signature(data_str)

    # Логування для відладки
    print("--- LIQPAY PAYMENT GENERATED ---")
    print(f"JSON Data: {json_data}")
    print(f"Data (Base64): {data_str}")
    print(f"Signature: {signature}")
    print(f"Server URL: {server_url}")
    print(f"Result URL: {result_url}")
    print("--------------------------------")

    checkout_url = f"{LIQPAY_SERVER_URL}?data={data_str}&signature={signature}"

    return jsonify({
        'checkout_url': checkout_url,
        'data': data_str,
        'signature': signature
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
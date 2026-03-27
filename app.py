from flask import Flask, render_template, request, redirect, url_for, session, flash
import qrcode
import os
import uuid
import base64
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, join_room, emit

try:
    import eventlet
except ImportError:
    eventlet = None

app = Flask(__name__)
app.secret_key = 'swift_connect_secret_key_2024'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet' if eventlet else 'threading')

DATABASE = 'swiftconnect.db'
QR_CODES_DIR = os.path.join('static', 'qr_codes')
UPLOADS_DIR = os.path.join('static', 'uploads')
PORT = int(os.environ.get('PORT', 5000))

os.makedirs(QR_CODES_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(table_name, column_name):
    conn = get_db()
    c = conn.cursor()
    try:
        rows = c.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(row['name'] == column_name for row in rows)
    finally:
        conn.close()


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS qr_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            vehicle TEXT NOT NULL,
            phone TEXT NOT NULL,
            message TEXT,
            qr_image_path TEXT NOT NULL,
            chat_token TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    if not column_exists('qr_data', 'chat_token'):
        try:
            c.execute('ALTER TABLE qr_data ADD COLUMN chat_token TEXT')
        except Exception:
            pass

    if not column_exists('qr_data', 'qr_image_path'):
        try:
            c.execute('ALTER TABLE qr_data ADD COLUMN qr_image_path TEXT')
        except Exception:
            pass

    if not column_exists('qr_data', 'created_at'):
        try:
            c.execute('ALTER TABLE qr_data ADD COLUMN created_at TEXT')
        except Exception:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qr_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL,
            sender_name TEXT,
            message TEXT,
            image_path TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (qr_id) REFERENCES qr_data(id)
        )
    ''')

    conn.commit()
    conn.close()


init_db()


def generate_visitor_name():
    return f"User_{uuid.uuid4().int % 9000 + 1000}"


def get_chat_messages(qr_id):
    conn = get_db()
    c = conn.cursor()
    rows = c.execute(
        'SELECT sender_type, sender_name, message, image_path, timestamp FROM chat_messages WHERE qr_id = ? ORDER BY timestamp',
        (qr_id,)
    ).fetchall()
    conn.close()
    return [
        {
            'sender_type': row['sender_type'],
            'sender_name': row['sender_name'] or ('Owner' if row['sender_type'] == 'owner' else 'Visitor'),
            'message': row['message'],
            'image_path': row['image_path'],
            'timestamp': row['timestamp']
        }
        for row in rows
    ]


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/auth', methods=['GET', 'POST'])
def auth():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash('Email and password are required', 'error')
            return render_template('auth.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return render_template('auth.html')

        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT id FROM users WHERE email = ?', (email,))
            if c.fetchone():
                flash('Email already registered. Please login instead.', 'error')
                conn.close()
                return render_template('auth.html')

            hashed_password = generate_password_hash(password)
            c.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, hashed_password))
            conn.commit()
            conn.close()

            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Registration error: {str(e)}', 'error')
            return render_template('auth.html')

    return render_template('auth.html')


@app.route('/register')
def register():
    return render_template('auth.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        if not email or not password:
            flash('Email and password are required', 'error')
            return render_template('login.html')

        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT id, email, password FROM users WHERE email = ?', (email,))
            user = c.fetchone()
            conn.close()

            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['user_email'] = user['email']
                flash(f'Welcome back, {user["email"]}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid email or password', 'error')
                return render_template('login.html')
        except Exception as e:
            flash(f'Login error: {str(e)}', 'error')
            return render_template('login.html')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('login'))


@app.route('/dashboard', methods=['GET'])
def dashboard():
    if 'user_id' not in session:
        flash('Please login to access dashboard', 'warning')
        return redirect(url_for('login'))

    active_page = request.args.get('active', 'dashboard')
    if active_page not in ['dashboard', 'generate', 'vehicles', 'history', 'owner_chats']:
        active_page = 'dashboard'

    conn = get_db()
    c = conn.cursor()

    total_qr = c.execute('SELECT COUNT(*) FROM qr_data WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    total_vehicles = c.execute('SELECT COUNT(DISTINCT vehicle) FROM qr_data WHERE user_id = ?', (session['user_id'],)).fetchone()[0]
    last_row = c.execute('SELECT created_at FROM qr_data WHERE user_id = ? ORDER BY created_at DESC LIMIT 1', (session['user_id'],)).fetchone()
    recent_rows = c.execute('SELECT name, vehicle, message, qr_image_path, created_at FROM qr_data WHERE user_id = ? ORDER BY created_at DESC LIMIT 3', (session['user_id'],)).fetchall()
    conn.close()

    last_activity = 'Ready'
    if last_row and last_row['created_at']:
        try:
            last_activity = datetime.fromisoformat(last_row['created_at']).strftime('%b %d, %Y %H:%M')
        except Exception:
            last_activity = last_row['created_at']

    recent_entries = []
    for row in recent_rows:
        created_at = row['created_at']
        try:
            created_at = datetime.fromisoformat(created_at).strftime('%b %d, %Y %H:%M')
        except Exception:
            created_at = created_at
        recent_entries.append({
            'name': row['name'],
            'vehicle': row['vehicle'],
            'message': row['message'],
            'qr_image_path': row['qr_image_path'],
            'created_at': created_at
        })

    qr_path = None
    if session.get('last_qr_filename'):
        qr_path = url_for('static', filename='qr_codes/' + session['last_qr_filename'])

    return render_template(
        'dashboard.html',
        user_email=session.get('user_email'),
        total_qr=total_qr,
        total_vehicles=total_vehicles,
        last_activity=last_activity,
        recent_entries=recent_entries,
        qr_path=qr_path,
        active_page=active_page
    )


@app.route('/generate')
def generate():
    if 'user_id' not in session:
        flash('Please login to access generate page', 'warning')
        return redirect(url_for('login'))

    return redirect(url_for('dashboard', _anchor='preview', active='generate'))


@app.route('/vehicles')
def vehicles():
    if 'user_id' not in session:
        flash('Please login to access vehicles page', 'warning')
        return redirect(url_for('login'))

    return render_template('vehicles.html', user_email=session.get('user_email'), active_page='vehicles')


@app.route('/history')
def history():
    if 'user_id' not in session:
        flash('Please login to access history page', 'warning')
        return redirect(url_for('login'))

    return render_template('history.html', user_email=session.get('user_email'), active_page='history')


@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    if 'user_id' not in session:
        flash('Please login to generate QR code', 'warning')
        return redirect(url_for('login'))

    owner_name = request.form.get('name', '').strip()
    vehicle_number = request.form.get('vehicle', '').strip()
    contact_number = request.form.get('phone', '').strip()
    message = request.form.get('message', '').strip()

    if not all([owner_name, vehicle_number, contact_number]):
        flash('Please fill in all required fields', 'error')
        return redirect(url_for('dashboard'))

    chat_token = uuid.uuid4().hex
    base_url = request.host_url.rstrip('/')
    qr_url = base_url + url_for('visitor_chat', vehicle_token=chat_token)

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color='black', back_color='white')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    vehicle_safe = vehicle_number.replace(' ', '_').replace('/', '_')
    filename = f'qr_{vehicle_safe}_{timestamp}.png'
    filepath = os.path.join(QR_CODES_DIR, filename)
    img.save(filepath)

    qr_image_path = f'qr_codes/{filename}'

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO qr_data (user_id, name, vehicle, phone, message, qr_image_path, chat_token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                session['user_id'],
                owner_name,
                vehicle_number,
                contact_number,
                message,
                qr_image_path,
                chat_token,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        )
        conn.commit()
        conn.close()
    except Exception as e:
        flash(f'Unable to save QR data: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

    session['last_qr_filename'] = filename
    session['last_chat_token'] = chat_token
    flash('QR code generated with chat access. Scan it to open the anonymous visitor chat.', 'success')
    return redirect(url_for('dashboard', _anchor='preview', active='generate'))


@app.route('/chat/<vehicle_token>')
def visitor_chat(vehicle_token):
    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT * FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    conn.close()

    if not row:
        return render_template('chat.html', error='The chat link is invalid or expired.', visitor_mode=True, owner_mode=False, messages=[], chat_token='', visitor_name='Guest', vehicle_label='Unknown Vehicle')

    visitor_key = f'visitor_name_{vehicle_token}'
    if visitor_key not in session:
        session[visitor_key] = generate_visitor_name()
    visitor_name = session[visitor_key]

    messages = get_chat_messages(row['id'])
    return render_template(
        'chat.html',
        visitor_mode=True,
        owner_mode=False,
        messages=messages,
        chat_token=vehicle_token,
        visitor_name=visitor_name,
        user_email=None,
        vehicle_label=row['vehicle'],
        error=None
    )


@app.route('/owner_chats')
def owner_chats():
    if 'user_id' not in session:
        flash('Please login to access active chats', 'warning')
        return redirect(url_for('login'))

    chats = []
    try:
        conn = get_db()
        c = conn.cursor()
        rows = c.execute(
            'SELECT id, vehicle, chat_token, created_at FROM qr_data WHERE user_id = ? ORDER BY created_at DESC',
            (session['user_id'],)
        ).fetchall()
        conn.close()

        for row in rows:
            conn = get_db()
            c = conn.cursor()
            last = c.execute(
                'SELECT message, image_path, timestamp FROM chat_messages WHERE qr_id = ? ORDER BY timestamp DESC LIMIT 1',
                (row['id'],)
            ).fetchone()
            conn.close()

            if not last:
                continue

            last_message = last['message'] if last['message'] else 'Image shared'
            last_message_at = last['timestamp']
            chats.append({
                'vehicle': row['vehicle'],
                'chat_token': row['chat_token'],
                'last_message': last_message,
                'last_message_at': last_message_at,
            })
    except Exception as e:
        chats = []
        flash('Unable to load active chats at this time.', 'error')

    return render_template('owner_chats.html', user_email=session.get('user_email'), active_page='owner_chats', chats=chats)


@app.route('/owner_chat/<vehicle_token>')
def owner_chat(vehicle_token):
    if 'user_id' not in session:
        flash('Please login to access this chat', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT * FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    conn.close()

    if not row:
        flash('Chat not found', 'error')
        return redirect(url_for('owner_chats'))

    if row['user_id'] != session['user_id']:
        flash('You are not authorized to view this chat.', 'error')
        return redirect(url_for('owner_chats'))

    messages = get_chat_messages(row['id'])
    return render_template(
        'chat.html',
        visitor_mode=False,
        owner_mode=True,
        messages=messages,
        chat_token=vehicle_token,
        visitor_name='Visitor',
        user_email=session.get('user_email'),
        vehicle_label=row['vehicle'],
        error=None
    )


@socketio.on('join_room')
def handle_join(data):
    vehicle_token = data.get('vehicle_token')
    if not vehicle_token:
        return
    join_room(f'chat_{vehicle_token}')


@socketio.on('send_message')
def handle_send_message(data):
    vehicle_token = data.get('vehicle_token')
    sender_type = data.get('sender_type')
    sender_name = data.get('sender_name')
    message_text = (data.get('message') or '').strip()
    image_data = data.get('image_data')

    if not vehicle_token or not sender_type or (not message_text and not image_data):
        return

    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT id FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    conn.close()

    if not row:
        return

    qr_id = row['id']
    image_path = None
    image_header = None

    if image_data:
        try:
            if image_data.startswith('data:'):
                image_header, encoded = image_data.split(',', 1)
            else:
                encoded = image_data
            extension = 'png'
            if image_header and ('jpeg' in image_header or 'jpg' in image_header):
                extension = 'jpg'
            filename = f'chat_{uuid.uuid4().hex}.{extension}'
            filepath = os.path.join(UPLOADS_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(encoded))
            image_path = f'uploads/{filename}'
        except Exception:
            image_path = None

    if sender_type == 'visitor' and not sender_name:
        sender_name = 'Visitor'
    if sender_type == 'owner':
        sender_name = sender_name or 'Owner'

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'INSERT INTO chat_messages (qr_id, sender_type, sender_name, message, image_path, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
        (qr_id, sender_type, sender_name, message_text, image_path, timestamp)
    )
    conn.commit()
    conn.close()

    payload = {
        'sender_type': sender_type,
        'sender_name': sender_name,
        'message': message_text,
        'image_path': image_path,
        'timestamp': timestamp
    }
    emit('receive_message', payload, room=f'chat_{vehicle_token}')


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=PORT, use_reloader=False)

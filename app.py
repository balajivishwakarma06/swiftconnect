import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import qrcode
from PIL import Image, ImageDraw, ImageFont
import os
import uuid
import base64
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, join_room, emit
from flask_mail import Mail, Message
import random
import string


app = Flask(__name__)
app.secret_key = 'swift_connect_secret_key_2024'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='eventlet')

# Mail configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
mail_port = os.environ.get('MAIL_PORT', '587')
app.config['MAIL_PORT'] = int(mail_port) if mail_port.strip() else 587
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'your_email@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'your_app_password')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'your_email@gmail.com')
mail = Mail(app)
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
            chat_token TEXT UNIQUE,
            is_blocked INTEGER NOT NULL DEFAULT 0,
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

    if not column_exists('qr_data', 'is_blocked'):
        try:
            c.execute('ALTER TABLE qr_data ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0')
        except Exception:
            pass

    if not column_exists('qr_data', 'created_at'):
        try:
            c.execute('ALTER TABLE qr_data ADD COLUMN created_at TEXT')
        except Exception:
            pass

    if not column_exists('qr_data', 'purpose'):
        try:
            c.execute('ALTER TABLE qr_data ADD COLUMN purpose TEXT')
        except Exception:
            pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TIMESTAMP
        )
    ''')


    c.execute('''
        CREATE TABLE IF NOT EXISTS visitor_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qr_id INTEGER NOT NULL,
            session_key TEXT UNIQUE NOT NULL,
            visitor_name TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (qr_id) REFERENCES qr_data(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qr_id INTEGER NOT NULL,
            sender_type TEXT NOT NULL,
            sender_name TEXT,
            message TEXT,
            image_path TEXT,
            visitor_session_id INTEGER,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (qr_id) REFERENCES qr_data(id),
            FOREIGN KEY (visitor_session_id) REFERENCES visitor_sessions(id)
        )
    ''')

    if not column_exists('chat_messages', 'visitor_session_id'):
        try:
            c.execute('ALTER TABLE chat_messages ADD COLUMN visitor_session_id INTEGER')
        except Exception:
            pass

    conn.commit()
    conn.close()


init_db()


def generate_visitor_name():
    return f"User_{uuid.uuid4().int % 9000 + 1000}"


def create_branded_qr(qr_url, filepath):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color='black', back_color='white')
    img.save(filepath)


def get_chat_messages(qr_id, visitor_session_id=None):
    conn = get_db()
    c = conn.cursor()
    if visitor_session_id:
        rows = c.execute(
            'SELECT sender_type, sender_name, message, image_path, timestamp FROM chat_messages WHERE qr_id = ? AND visitor_session_id = ? ORDER BY timestamp',
            (qr_id, visitor_session_id)
        ).fetchall()
    else:
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


def get_visitor_session(qr_id, session_key, visitor_name=None):
    conn = get_db()
    c = conn.cursor()
    row = c.execute(
        'SELECT id, reason FROM visitor_sessions WHERE session_key = ? AND qr_id = ?',
        (session_key, qr_id)
    ).fetchone()

    if row:
        conn.close()
        return {'id': row['id'], 'reason': row['reason']}

    c.execute(
        'INSERT INTO visitor_sessions (qr_id, session_key, visitor_name, reason, created_at) VALUES (?, ?, ?, ?, ?)',
        (qr_id, session_key, visitor_name or 'Visitor', None, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return {'id': session_id, 'reason': None}


def update_visitor_reason(session_key, qr_id, reason):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'UPDATE visitor_sessions SET reason = ? WHERE session_key = ? AND qr_id = ?',
        (reason, session_key, qr_id)
    )
    conn.commit()
    conn.close()


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/auth', methods=['GET', 'POST'])
def auth():
    conn = get_db()
    c = conn.cursor()
    has_user = c.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None
    conn.close()

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

            otp_code = ''.join(random.choices(string.digits, k=6))
            c.execute('INSERT INTO otp_codes (email, code, expires_at) VALUES (?, ?, datetime("now", "+10 minutes"))', (email, otp_code))
            conn.commit()
            conn.close()

            # Store pending details in session
            session['pending_email'] = email
            session['pending_password'] = generate_password_hash(password)

            # Try to send email
            try:
                msg = Message("Your SwiftConnect OTP", recipients=[email])
                msg.body = f"Your OTP for SwiftConnect registration is: {otp_code}\nThis code will expire in 10 minutes."
                mail.send(msg)
                flash('OTP sent to your email. Please check your inbox.', 'success')
            except Exception as e:
                # If mail fails (e.g. bad SMTP setup), print to console so owner can at least read it
                print(f"[DEVELOPMENT MODE] Failed to send email: {e}")
                print(f"[DEVELOPMENT MODE] OTP for {email} is {otp_code}")
                flash('Could not send email. See console for OTP (Dev Mode).', 'warning')

            return redirect(url_for('verify_otp'))
        except Exception as e:
            flash(f'Registration error: {str(e)}', 'error')
            return render_template('auth.html')

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if 'pending_email' not in session or 'pending_password' not in session:
        flash('Session expired. Please register again.', 'error')
        return redirect(url_for('auth'))

    if request.method == 'POST':
        entered_code = request.form.get('otp', '').strip()
        email = session['pending_email']

        conn = get_db()
        c = conn.cursor()
        
        # Check valid OTP
        valid_otp = c.execute(
            'SELECT id FROM otp_codes WHERE email = ? AND code = ? AND expires_at > datetime("now") ORDER BY id DESC LIMIT 1',
            (email, entered_code)
        ).fetchone()

        if valid_otp:
            # Create user
            c.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, session['pending_password']))
            c.execute('DELETE FROM otp_codes WHERE email = ?', (email,))
            conn.commit()
            conn.close()

            session.pop('pending_email', None)
            session.pop('pending_password', None)
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        else:
            conn.close()
            flash('Invalid or expired OTP. Please try again.', 'error')
            
    return render_template('verify_otp.html', email=session.get('pending_email'))

    if has_user:
        return redirect(url_for('login'))
    return render_template('auth.html')


@app.route('/register')
def register():
    conn = get_db()
    c = conn.cursor()
    has_user = c.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None
    conn.close()
    if has_user:
        return redirect(url_for('login'))
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

    conn = get_db()
    c = conn.cursor()
    has_user = c.execute('SELECT 1 FROM users LIMIT 1').fetchone() is not None
    conn.close()
    if not has_user:
        return redirect(url_for('auth'))

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

    conn = get_db()
    c = conn.cursor()
    rows = c.execute(
        'SELECT id, name, vehicle, phone, message, qr_image_path, is_blocked, created_at FROM qr_data WHERE user_id = ? ORDER BY created_at DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()

    vehicle_list = []
    for row in rows:
        vehicle_list.append({
            'id': row['id'],
            'name': row['name'],
            'vehicle': row['vehicle'],
            'phone': row['phone'],
            'message': row['message'],
            'qr_image_path': row['qr_image_path'],
            'is_blocked': bool(row['is_blocked']),
            'created_at': row['created_at']
        })

    return render_template('vehicles.html', user_email=session.get('user_email'), active_page='vehicles', vehicles=vehicle_list)


@app.route('/history')
def history():
    if 'user_id' not in session:
        flash('Please login to access history page', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    rows = c.execute(
        'SELECT id, name, vehicle, message, qr_image_path, created_at, is_blocked FROM qr_data WHERE user_id = ? ORDER BY created_at DESC',
        (session['user_id'],)
    ).fetchall()

    qrs = []
    for row in rows:
        chat_count = c.execute('SELECT COUNT(*) FROM chat_messages WHERE qr_id = ?', (row['id'],)).fetchone()[0]
        visitor_count = c.execute('SELECT COUNT(*) FROM visitor_sessions WHERE qr_id = ?', (row['id'],)).fetchone()[0]
        qrs.append({
            'id': row['id'],
            'name': row['name'],
            'vehicle': row['vehicle'],
            'message': row['message'],
            'qr_image_path': row['qr_image_path'],
            'created_at': row['created_at'],
            'is_blocked': bool(row['is_blocked']),
            'chat_count': chat_count,
            'visitor_count': visitor_count
        })
    conn.close()

    return render_template('history.html', user_email=session.get('user_email'), active_page='history', qrs=qrs)


@app.route('/history/qr/<int:qr_id>')
def history_detail(qr_id):
    if 'user_id' not in session:
        flash('Please login to view this history entry', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    qr = c.execute('SELECT * FROM qr_data WHERE id = ? AND user_id = ?', (qr_id, session['user_id'])).fetchone()
    if not qr:
        conn.close()
        flash('History entry not found.', 'error')
        return redirect(url_for('history'))

    messages = c.execute(
        'SELECT sender_type, sender_name, message, image_path, timestamp FROM chat_messages WHERE qr_id = ? ORDER BY timestamp',
        (qr_id,)
    ).fetchall()
    visitor_sessions = c.execute(
        'SELECT id, visitor_name, reason, created_at FROM visitor_sessions WHERE qr_id = ? ORDER BY created_at DESC',
        (qr_id,)
    ).fetchall()
    conn.close()

    return render_template('history_detail.html', user_email=session.get('user_email'), active_page='history', qr=qr, messages=messages, visitor_sessions=visitor_sessions)


@app.route('/history/qr/<int:qr_id>/delete', methods=['POST'])
def delete_chat(qr_id):
    if 'user_id' not in session:
        flash('Please login to manage history', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    qr = c.execute('SELECT id FROM qr_data WHERE id = ? AND user_id = ?', (qr_id, session['user_id'])).fetchone()
    if not qr:
        conn.close()
        flash('Delete action failed.', 'error')
        return redirect(url_for('history'))

    c.execute('DELETE FROM chat_messages WHERE qr_id = ?', (qr_id,))
    conn.commit()
    conn.close()

    flash('All messages for this QR entry have been deleted.', 'success')
    return redirect(url_for('history_detail', qr_id=qr_id))


@app.route('/print_qr/<int:qr_id>')
def print_qr(qr_id):
    if 'user_id' not in session:
        flash('Please login to access QR printing', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    qr = c.execute('SELECT * FROM qr_data WHERE id = ? AND user_id = ?', (qr_id, session['user_id'])).fetchone()
    conn.close()
    if not qr:
        flash('QR entry not found.', 'error')
        return redirect(url_for('history'))

    return render_template('print_qr.html', qr=qr)


@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    if 'user_id' not in session:
        flash('Please login to generate QR code', 'warning')
        return redirect(url_for('login'))

    owner_name = request.form.get('name', '').strip()
    vehicle_number = request.form.get('vehicle', '').strip()
    contact_number = request.form.get('phone', '').strip()
    message = request.form.get('message', '').strip()
    purpose = request.form.get('purpose', 'Scan to report or contact').strip()

    if not all([owner_name, vehicle_number, contact_number]):
        flash('Please fill in all required fields', 'error')
        return redirect(url_for('dashboard'))

    chat_token = uuid.uuid4().hex
    base_url = request.host_url.rstrip('/')
    qr_url = base_url + url_for('visitor_chat', vehicle_token=chat_token)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    vehicle_safe = vehicle_number.replace(' ', '_').replace('/', '_')
    filename = f'qr_{vehicle_safe}_{timestamp}.png'
    filepath = os.path.join(QR_CODES_DIR, filename)
    create_branded_qr(qr_url, filepath)

    qr_image_path = f'qr_codes/{filename}'

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            'INSERT INTO qr_data (user_id, name, vehicle, phone, message, qr_image_path, chat_token, purpose, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                session['user_id'],
                owner_name,
                vehicle_number,
                contact_number,
                message,
                qr_image_path,
                chat_token,
                purpose,
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

    if row['is_blocked']:
        return render_template('chat.html', error='You are blocked from contacting this vehicle.', visitor_mode=True, owner_mode=False, messages=[], chat_token='', visitor_name='Guest', vehicle_label=row['vehicle'])

    visitor_session_key = f'visitor_session_{vehicle_token}'
    if visitor_session_key not in session:
        session[visitor_session_key] = uuid.uuid4().hex

    visitor_key = f'visitor_name_{vehicle_token}'
    if visitor_key not in session:
        session[visitor_key] = generate_visitor_name()
    visitor_name = session[visitor_key]
    session[visitor_key] = visitor_name

    visitor_data = get_visitor_session(row['id'], session[visitor_session_key], visitor_name)
    if visitor_data.get('reason'):
        messages = get_chat_messages(row['id'], visitor_data['id'])
        return render_template(
            'chat.html',
            visitor_mode=True,
            owner_mode=False,
            messages=messages,
            chat_token=vehicle_token,
            visitor_name=visitor_name,
            user_email=None,
            vehicle_label=row['vehicle'],
            error=None,
            visitor_purpose=visitor_data.get('reason'),
            visitor_session_id=visitor_data['id']
        )

    return render_template(
        'select_reason.html',
        visitor_name=visitor_name,
        vehicle_label=row['vehicle'],
        vehicle_token=vehicle_token
    )


@app.route('/chat/<vehicle_token>/start', methods=['POST'])
def visitor_chat_start(vehicle_token):
    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT * FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    conn.close()

    if not row:
        return render_template('chat.html', error='The chat link is invalid or expired.', visitor_mode=True, owner_mode=False, messages=[], chat_token='', visitor_name='Guest', vehicle_label='Unknown Vehicle')

    if row['is_blocked']:
        return render_template('chat.html', error='You are blocked from contacting this vehicle.', visitor_mode=True, owner_mode=False, messages=[], chat_token='', visitor_name='Guest', vehicle_label=row['vehicle'])

    selected_reason = request.form.get('purpose', '').strip()
    if not selected_reason:
        flash('Please select a reason before starting the chat.', 'error')
        return redirect(url_for('visitor_chat', vehicle_token=vehicle_token))

    visitor_session_key = f'visitor_session_{vehicle_token}'
    if visitor_session_key not in session:
        session[visitor_session_key] = uuid.uuid4().hex

    visitor_key = f'visitor_name_{vehicle_token}'
    if visitor_key not in session:
        session[visitor_key] = generate_visitor_name()
    visitor_name = session[visitor_key]
    session[visitor_key] = visitor_name

    visitor_session = get_visitor_session(row['id'], session[visitor_session_key], visitor_name)
    update_visitor_reason(session[visitor_session_key], row['id'], selected_reason)

    messages = get_chat_messages(row['id'], visitor_session['id'])
    return render_template(
        'chat.html',
        visitor_mode=True,
        owner_mode=False,
        messages=messages,
        chat_token=vehicle_token,
        visitor_name=visitor_name,
        user_email=None,
        vehicle_label=row['vehicle'],
        error=None,
        visitor_purpose=selected_reason,
        visitor_session_id=visitor_session['id']
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
        qrs = c.execute(
            'SELECT id, vehicle, chat_token, created_at FROM qr_data WHERE user_id = ? ORDER BY created_at DESC',
            (session['user_id'],)
        ).fetchall()

        for qr in qrs:
            sessions = c.execute(
                'SELECT id, visitor_name, reason, created_at FROM visitor_sessions WHERE qr_id = ? ORDER BY created_at DESC',
                (qr['id'],)
            ).fetchall()

            for visitor in sessions:
                last = c.execute(
                    'SELECT message, image_path, timestamp FROM chat_messages WHERE qr_id = ? AND visitor_session_id = ? ORDER BY timestamp DESC LIMIT 1',
                    (qr['id'], visitor['id'])
                ).fetchone()
                if not last:
                    continue

                chats.append({
                    'vehicle': qr['vehicle'],
                    'chat_token': qr['chat_token'],
                    'visitor_session_id': visitor['id'],
                    'visitor_name': visitor['visitor_name'],
                    'visitor_reason': visitor['reason'],
                    'last_message': last['message'] if last['message'] else 'Image shared',
                    'last_message_at': last['timestamp']
                })
        conn.close()
    except Exception:
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
        error=None,
        visitor_session_id=None
    )


@app.route('/owner_chat/<vehicle_token>/session/<int:visitor_session_id>')
def owner_chat_session(vehicle_token, visitor_session_id):
    if 'user_id' not in session:
        flash('Please login to access this chat', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    qr = c.execute('SELECT * FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    if not qr or qr['user_id'] != session['user_id']:
        conn.close()
        flash('Chat not found or access denied.', 'error')
        return redirect(url_for('owner_chats'))

    visitor_session = c.execute(
        'SELECT id, visitor_name, reason FROM visitor_sessions WHERE id = ? AND qr_id = ?',
        (visitor_session_id, qr['id'])
    ).fetchone()
    conn.close()

    if not visitor_session:
        flash('Visitor session not found.', 'error')
        return redirect(url_for('owner_chats'))

    messages = get_chat_messages(qr['id'], visitor_session_id)
    return render_template(
        'chat.html',
        visitor_mode=False,
        owner_mode=True,
        messages=messages,
        chat_token=vehicle_token,
        visitor_name=visitor_session['visitor_name'],
        user_email=session.get('user_email'),
        vehicle_label=qr['vehicle'],
        error=None,
        visitor_purpose=visitor_session['reason'],
        visitor_session_id=visitor_session_id
    )


@app.route('/block_chat/<vehicle_token>', methods=['POST'])
def block_chat(vehicle_token):
    if 'user_id' not in session:
        flash('Please login to manage chat blocks.', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT id, user_id FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    if not row or row['user_id'] != session['user_id']:
        conn.close()
        flash('Unable to block this chat.', 'error')
        return redirect(url_for('owner_chats'))

    c.execute('UPDATE qr_data SET is_blocked = 1 WHERE id = ?', (row['id'],))
    conn.commit()
    conn.close()

    flash('This visitor session has been blocked. Future contact attempts are now restricted.', 'success')
    return redirect(url_for('owner_chat', vehicle_token=vehicle_token))


@app.route('/clear_chat/<vehicle_token>/<int:visitor_session_id>', methods=['POST'])
def clear_chat_thread(vehicle_token, visitor_session_id):
    if 'user_id' not in session:
        flash('Please login to manage chats.', 'warning')
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    qr = c.execute('SELECT id, user_id FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    if not qr or qr['user_id'] != session['user_id']:
        conn.close()
        flash('Unable to clear this chat thread.', 'error')
        return redirect(url_for('owner_chats'))

    visitor_session = c.execute(
        'SELECT id FROM visitor_sessions WHERE id = ? AND qr_id = ?',
        (visitor_session_id, qr['id'])
    ).fetchone()
    if not visitor_session:
        conn.close()
        flash('Visitor session not found.', 'error')
        return redirect(url_for('owner_chats'))

    c.execute('DELETE FROM chat_messages WHERE qr_id = ? AND visitor_session_id = ?', (qr['id'], visitor_session_id))
    conn.commit()
    conn.close()

    flash('This visitor thread has been cleared.', 'success')
    return redirect(url_for('owner_chat_session', vehicle_token=vehicle_token, visitor_session_id=visitor_session_id))


@app.route('/upload_image', methods=['POST'])
def upload_image():
    vehicle_token = request.form.get('vehicle_token', '').strip()
    sender_type = request.form.get('sender_type', '').strip()
    sender_name = request.form.get('sender_name', '').strip() or ('Owner' if sender_type == 'owner' else 'Visitor')
    visitor_session_id = request.form.get('visitor_session_id')
    visitor_session_id = int(visitor_session_id) if visitor_session_id and visitor_session_id.isdigit() else None
    image_file = request.files.get('image_file')

    if not vehicle_token or not sender_type or not image_file:
        return jsonify({'success': False, 'error': 'Invalid upload request.'}), 400

    if image_file.filename == '':
        return jsonify({'success': False, 'error': 'No image selected.'}), 400

    file_name = image_file.filename.lower()
    if not (file_name.endswith('.png') or file_name.endswith('.jpg') or file_name.endswith('.jpeg')):
        return jsonify({'success': False, 'error': 'Only JPG and PNG images are accepted.'}), 400

    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT id, is_blocked FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'success': False, 'error': 'Invalid chat token.'}), 400

    if sender_type == 'visitor' and row['is_blocked']:
        conn.close()
        return jsonify({'success': False, 'error': 'This visitor is blocked from sending messages.'}), 403

    if visitor_session_id:
        session_row = c.execute(
            'SELECT id FROM visitor_sessions WHERE id = ? AND qr_id = ?',
            (visitor_session_id, row['id'])
        ).fetchone()
        if not session_row:
            visitor_session_id = None

    extension = 'png' if file_name.endswith('.png') else 'jpg'
    filename = f'chat_{uuid.uuid4().hex}.{extension}'
    filepath = os.path.join(UPLOADS_DIR, filename)

    try:
        image_file.save(filepath)
        image_path = f'uploads/{filename}'
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute(
            'INSERT INTO chat_messages (qr_id, sender_type, sender_name, message, image_path, visitor_session_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (row['id'], sender_type, sender_name, '', image_path, visitor_session_id, timestamp)
        )
        conn.commit()
    except Exception as err:
        conn.close()
        return jsonify({'success': False, 'error': f'Failed to save image: {err}'}), 500

    conn.close()
    payload = {
        'sender_type': sender_type,
        'sender_name': sender_name,
        'message': '',
        'image_path': image_path,
        'timestamp': timestamp
    }
    room_name = f'chat_{vehicle_token}_{visitor_session_id}' if visitor_session_id else f'chat_{vehicle_token}'
    socketio.emit('receive_message', payload, room=room_name)
    return jsonify({'success': True, 'payload': payload})


@socketio.on('join_room')
def handle_join(data):
    vehicle_token = data.get('vehicle_token')
    visitor_session_id = data.get('visitor_session_id')
    if not vehicle_token:
        return
    if visitor_session_id:
        join_room(f'chat_{vehicle_token}_{visitor_session_id}')
    else:
        join_room(f'chat_{vehicle_token}')


@socketio.on('send_message')
def handle_send_message(data):
    vehicle_token = data.get('vehicle_token')
    visitor_session_id = data.get('visitor_session_id')
    sender_type = data.get('sender_type')
    sender_name = data.get('sender_name')
    message_text = (data.get('message') or '').strip()
    image_data = data.get('image_data')

    if not vehicle_token or not sender_type or (not message_text and not image_data):
        return

    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT id, is_blocked FROM qr_data WHERE chat_token = ?', (vehicle_token,)).fetchone()
    if not row:
        conn.close()
        return

    if sender_type == 'visitor' and row['is_blocked']:
        conn.close()
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

    if visitor_session_id and isinstance(visitor_session_id, str) and visitor_session_id.isdigit():
        visitor_session_id = int(visitor_session_id)
    else:
        visitor_session_id = None

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute(
        'INSERT INTO chat_messages (qr_id, sender_type, sender_name, message, image_path, visitor_session_id, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (qr_id, sender_type, sender_name, message_text, image_path, visitor_session_id, timestamp)
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
    room_name = f'chat_{vehicle_token}_{visitor_session_id}' if visitor_session_id else f'chat_{vehicle_token}'
    emit('receive_message', payload, room=room_name)


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=PORT, use_reloader=False)

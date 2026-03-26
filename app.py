from flask import Flask, render_template, request, redirect, make_response, session
import qrcode
import os
import random
import sqlite3

app = Flask(__name__)
app.secret_key = "swift_secret_key"

# IMPORTANT FOR RENDER
DB = "/tmp/database.db"


# ---------------- INIT DATABASE ----------------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        receiver TEXT,
        message TEXT
    )
    ''')

    conn.commit()
    conn.close()

init_db()


# ---------------- LOGIN CHECK ----------------
def check_login():
    return session.get('email') is not None


# ---------------- HOME ----------------
@app.route('/')
def home():
    return redirect('/login')


# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():

    if session.get('email'):
        return redirect('/register')

    if request.method == 'POST':
        email = request.form.get('email')

        session['email'] = email   # direct login (no OTP for now)

        return redirect('/register')

    return render_template("login.html")


# ---------------- LOGOUT ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():

    if not check_login():
        return redirect('/login')

    if request.method == 'POST':
        name = request.form.get('name')
        vehicle = request.form.get('vehicle')

        user_id = "USR" + str(random.randint(1000, 9999))

        # IMPORTANT: use your Render URL
        qr_url = f"https://swiftconnect-yb63.onrender.com/message/{user_id}"

        qr_img = qrcode.make(qr_url)

        folder = "static/qr_codes"
        if not os.path.exists(folder):
            os.makedirs(folder)

        file_path = f"{folder}/{user_id}.png"
        qr_img.save(file_path)

        return render_template("dashboard.html", user_id=user_id, qr=file_path)

    return render_template("register.html")


# ---------------- VISITOR CHAT ----------------
@app.route('/message/<user_id>', methods=['GET', 'POST'])
def message(user_id):

    visitor_id = request.cookies.get('visitor_id')

    if not visitor_id:
        visitor_id = "VIS" + str(random.randint(1000, 9999))

    if request.method == 'POST':
        msg = request.form.get('message')

        conn = sqlite3.connect(DB)
        c = conn.cursor()

        c.execute("INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)",
                  (visitor_id, user_id, msg))

        conn.commit()
        conn.close()

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    SELECT sender, receiver, message FROM messages
    WHERE 
        (sender = ? AND receiver = ?) OR
        (sender = ? AND receiver = ?)
    ORDER BY id ASC
    """, (visitor_id, user_id, user_id, visitor_id))

    data = c.fetchall()
    conn.close()

    resp = make_response(render_template("chat.html", messages=data, user_id=user_id))
    resp.set_cookie('visitor_id', visitor_id)

    return resp


# ---------------- OWNER DASHBOARD ----------------
@app.route('/owner_dashboard/<user_id>')
def owner_dashboard(user_id):

    if not check_login():
        return redirect('/login')

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("SELECT DISTINCT sender FROM messages WHERE receiver = ?", (user_id,))
    users = c.fetchall()

    conn.close()

    return render_template("owner_dashboard.html", users=users, user_id=user_id)


# ---------------- OWNER CHAT ----------------
@app.route('/owner/<user_id>/<visitor_id>', methods=['GET', 'POST'])
def owner_chat(user_id, visitor_id):

    if not check_login():
        return redirect('/login')

    if request.method == 'POST':
        msg = request.form.get('message')

        conn = sqlite3.connect(DB)
        c = conn.cursor()

        c.execute("INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)",
                  (user_id, visitor_id, msg))

        conn.commit()
        conn.close()

    return render_template("owner_chat.html", user_id=user_id, visitor_id=visitor_id)


# ---------------- FETCH MESSAGES ----------------
@app.route('/get_messages/<user_id>/<visitor_id>')
def get_messages(user_id, visitor_id):

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    SELECT sender, receiver, message FROM messages
    WHERE 
        (sender = ? AND receiver = ?) OR
        (sender = ? AND receiver = ?)
    ORDER BY id ASC
    """, (visitor_id, user_id, user_id, visitor_id))

    messages = c.fetchall()
    conn.close()

    return {"messages": messages}


# ---------------- RUN ----------------
if __name__ == '__main__':
    app.run(debug=True)
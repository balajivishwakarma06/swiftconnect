from flask import Flask, render_template, request, redirect, make_response, session
import qrcode
import os
import random
import sqlite3
import smtplib

app = Flask(__name__)
app.secret_key = "swift_secret_key"

DB = "database.db"

# ---------------- LOGIN CHECK ----------------
def check_login():
    return session.get('email') is not None


# ---------------- OTP FUNCTION ----------------
def send_otp(email, otp):
    sender = "yourgmail@gmail.com"
    password = "your_app_password"

    message = f"Your OTP is {otp}"

    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(sender, password)
    server.sendmail(sender, email, message)
    server.quit()


# ---------------- DATABASE ----------------
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



# ---------------- HOME ----------------
@app.route('/')
def home():
    return redirect('/login')


# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':
        email = request.form.get('email')

        otp = str(random.randint(100000, 999999))

        app.config['EMAIL'] = email
        app.config['OTP'] = otp

        print("Fake OTP:", otp)

        return render_template("verify.html")

    return render_template("login.html")


# ---------------- VERIFY ----------------
@app.route('/verify', methods=['POST'])
def verify():

    # accept ANY OTP
    email = app.config.get('EMAIL')

    session['email'] = email

    return redirect('/register')

# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():

    if not check_login():
        return redirect('/login')

    if request.method == 'POST':
        name = request.form.get('name')
        contact = request.form.get('contact')
        vehicle = request.form.get('vehicle')
        contact = request.form.get('contact')

        user_id = "USR" + str(random.randint(1000, 9999))

        qr_img = qrcode.make(f"https://swiftconnect-yb63.onrender.com/message/{user_id}")
        file_path = f"static/qr_codes/{user_id}.png"

        if not os.path.exists('static/qr_codes'):
            os.makedirs('static/qr_codes')

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

    c.execute("""
SELECT sender, message 
FROM messages 
WHERE receiver = ?
GROUP BY sender
ORDER BY id DESC
""", (user_id,))

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

    return render_template("owner_chat.html", messages=data, user_id=user_id, visitor_id=visitor_id)


# ---------------- AUTO FETCH ----------------
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
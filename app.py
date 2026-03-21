from flask import Flask, render_template, request
import qrcode
import os
import random
import sqlite3

app = Flask(__name__)

# create database + table
conn = sqlite3.connect('database.db')
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

# create QR folder
if not os.path.exists('static/qr_codes'):
    os.makedirs('static/qr_codes')

# HOME PAGE
@app.route('/')
def home():
    return render_template("index.html")

# REGISTER PAGE
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        vehicle = request.form.get('vehicle')

        user_id = "USR" + str(random.randint(1000, 9999))

        qr_img = qrcode.make(f"https://swiftconnect-yb63.onrender.com/message/{user_id}")
        file_path = f"static/qr_codes/{user_id}.png"
        qr_img.save(file_path)

        return render_template("dashboard.html", user_id=user_id, qr=file_path)

    return render_template("register.html")

@app.route('/owner/<user_id>', methods=['GET', 'POST'])
def owner_chat(user_id):

    if request.method == 'POST':
        msg = request.form.get('message')

        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        c.execute("INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)",
                  (user_id, "Visitor", msg))

        conn.commit()
        conn.close()

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("""
    SELECT sender, receiver, message FROM messages
    WHERE receiver=? OR sender=?
    """, (user_id, user_id))

    data = c.fetchall()
    conn.close()

    return render_template("owner_chat.html", messages=data, user_id=user_id)

# CHAT PAGE (SEND + VIEW)
@app.route('/message/<user_id>', methods=['GET', 'POST'])
def message(user_id):

    sender = "Visitor"   # 👈 visitor always sender

    if request.method == 'POST':
        msg = request.form.get('message')

        conn = sqlite3.connect('database.db')
        c = conn.cursor()

        c.execute("INSERT INTO messages (sender, receiver, message) VALUES (?, ?, ?)",
                  (sender, user_id, msg))

        conn.commit()
        conn.close()

    # fetch messages between visitor and owner
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("""
    SELECT sender, receiver, message FROM messages
    WHERE receiver=? OR sender=?
             """, (user_id, user_id))

    data = c.fetchall()
    conn.close()

    return render_template("chat.html", messages=data, user_id=user_id)

# RUN APP
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
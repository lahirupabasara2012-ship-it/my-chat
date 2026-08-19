from flask import Flask, request, jsonify, send_from_directory, session
from flask_socketio import SocketIO, emit, join_room
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

app.secret_key = "mychat-secret-key-change-this"

socketio = SocketIO(
    app,
    cors_allowed_origins="*"
)

DATABASE = "mychat.db"

UPLOAD_FOLDER = "uploads"

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "webm", "mov", "avi",
    "pdf", "txt", "zip", "rar",
    "doc", "docx", "xls", "xlsx"
}

MAX_FILE_SIZE = 100 * 1024 * 1024

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            UNIQUE(user_id, contact_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT,
            message_type TEXT DEFAULT 'text',
            file_name TEXT,
            file_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER DEFAULT 0
        )
    """)

    conn.commit()

    # For old databases
    columns = conn.execute(
        "PRAGMA table_info(messages)"
    ).fetchall()

    column_names = [row["name"] for row in columns]

    if "message_type" not in column_names:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN message_type TEXT DEFAULT 'text'"
        )

    if "file_name" not in column_names:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN file_name TEXT"
        )

    if "file_url" not in column_names:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN file_url TEXT"
        )

    if "is_read" not in column_names:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0"
        )

    conn.commit()
    conn.close()


# =========================================================
# HELPERS
# =========================================================

def allowed_file(filename):

    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in ALLOWED_EXTENSIONS


def get_message(message_id):

    conn = get_db()

    row = conn.execute("""
        SELECT
            id,
            sender_id,
            receiver_id,
            message,
            message_type,
            file_name,
            file_url,
            created_at,
            is_read
        FROM messages
        WHERE id = ?
    """, (message_id,)).fetchone()

    conn.close()

    if not row:
        return None

    return dict(row)


def save_message(
    sender_id,
    receiver_id,
    message="",
    message_type="text",
    file_name=None,
    file_url=None
):

    conn = get_db()

    cursor = conn.execute("""
        INSERT INTO messages
        (
            sender_id,
            receiver_id,
            message,
            message_type,
            file_name,
            file_url,
            is_read
        )
        VALUES (?, ?, ?, ?, ?, ?, 0)
    """, (
        sender_id,
        receiver_id,
        message,
        message_type,
        file_name,
        file_url
    ))

    message_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return get_message(message_id)


# =========================================================
# FRONTEND
# =========================================================

@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/style.css")
def css():
    return send_from_directory(".", "style.css")


# =========================================================
# UPLOADS
# =========================================================

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


# =========================================================
# SIGN UP
# =========================================================

@app.route("/api/signup", methods=["POST"])
def signup():

    data = request.get_json() or {}

    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({
            "success": False,
            "message": "All fields are required."
        })

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "Password must be at least 6 characters."
        })

    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    if existing:

        conn.close()

        return jsonify({
            "success": False,
            "message": "This email is already registered."
        })

    hashed_password = generate_password_hash(password)

    conn.execute("""
        INSERT INTO users
        (name, email, password)
        VALUES (?, ?, ?)
    """, (
        name,
        email,
        hashed_password
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "Account created successfully."
    })


# =========================================================
# LOGIN
# =========================================================

@app.route("/api/login", methods=["POST"])
def login():

    data = request.get_json() or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    conn.close()

    if not user:

        return jsonify({
            "success": False,
            "message": "Email or password is incorrect."
        })

    if not check_password_hash(
        user["password"],
        password
    ):

        return jsonify({
            "success": False,
            "message": "Email or password is incorrect."
        })

    session["user_id"] = user["id"]

    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    })


# =========================================================
# CURRENT USER
# =========================================================

@app.route("/api/me")
def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "logged_in": False
        })

    conn = get_db()

    user = conn.execute("""
        SELECT id, name, email
        FROM users
        WHERE id = ?
    """, (user_id,)).fetchone()

    conn.close()

    if not user:

        session.clear()

        return jsonify({
            "logged_in": False
        })

    return jsonify({
        "logged_in": True,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"]
        }
    })


# =========================================================
# LOGOUT
# =========================================================

@app.route("/api/logout", methods=["POST"])
def logout():

    session.clear()

    return jsonify({
        "success": True
    })


# =========================================================
# ADD CONTACT
# =========================================================

@app.route("/api/add-contact", methods=["POST"])
def add_contact():

    user_id = session.get("user_id")

    if not user_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        })

    data = request.get_json() or {}

    email = data.get(
        "email",
        ""
    ).strip().lower()

    if not email:

        return jsonify({
            "success": False,
            "message": "Enter an email address."
        })

    conn = get_db()

    contact = conn.execute("""
        SELECT id, name, email
        FROM users
        WHERE email = ?
    """, (email,)).fetchone()

    if not contact:

        conn.close()

        return jsonify({
            "success": False,
            "message": "No account found with this email."
        })

    if contact["id"] == user_id:

        conn.close()

        return jsonify({
            "success": False,
            "message": "You cannot add yourself."
        })

    already = conn.execute("""
        SELECT id
        FROM contacts
        WHERE user_id = ?
        AND contact_id = ?
    """, (
        user_id,
        contact["id"]
    )).fetchone()

    if already:

        conn.close()

        return jsonify({
            "success": False,
            "message": "This contact is already added."
        })

    conn.execute("""
        INSERT INTO contacts
        (user_id, contact_id)
        VALUES (?, ?)
    """, (
        user_id,
        contact["id"]
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "contact": {
            "id": contact["id"],
            "name": contact["name"],
            "email": contact["email"]
        }
    })


# =========================================================
# CONTACTS + UNREAD COUNTS
# =========================================================

@app.route("/api/contacts")
def get_contacts():

    user_id = session.get("user_id")

    if not user_id:

        return jsonify({
            "success": False
        })

    conn = get_db()

    contacts = conn.execute("""
        SELECT
            users.id,
            users.name,
            users.email
        FROM contacts
        JOIN users
        ON users.id = contacts.contact_id
        WHERE contacts.user_id = ?
        ORDER BY users.name
    """, (user_id,)).fetchall()

    result = []

    for contact in contacts:

        unread = conn.execute("""
            SELECT COUNT(*) AS count
            FROM messages
            WHERE sender_id = ?
            AND receiver_id = ?
            AND is_read = 0
        """, (
            contact["id"],
            user_id
        )).fetchone()["count"]

        last_message = conn.execute("""
            SELECT
                message,
                message_type,
                file_name
            FROM messages
            WHERE
            (sender_id = ? AND receiver_id = ?)
            OR
            (sender_id = ? AND receiver_id = ?)
            ORDER BY id DESC
            LIMIT 1
        """, (
            user_id,
            contact["id"],
            contact["id"],
            user_id
        )).fetchone()

        preview = ""

        if last_message:

            if last_message["message_type"] == "image":
                preview = "?? Photo"

            elif last_message["message_type"] == "video":
                preview = "?? Video"

            elif last_message["message_type"] == "file":
                preview = "?? " + (
                    last_message["file_name"] or "File"
                )

            else:
                preview = last_message["message"] or ""

        result.append({
            "id": contact["id"],
            "name": contact["name"],
            "email": contact["email"],
            "unread": unread,
            "last_message": preview
        })

    conn.close()

    return jsonify({
        "success": True,
        "contacts": result
    })


# =========================================================
# GET MESSAGES
# =========================================================

@app.route("/api/messages/<int:contact_id>")
def get_messages(contact_id):

    user_id = session.get("user_id")

    if not user_id:

        return jsonify({
            "success": False
        })

    conn = get_db()

    # Mark received messages as read
    conn.execute("""
        UPDATE messages
        SET is_read = 1
        WHERE sender_id = ?
        AND receiver_id = ?
        AND is_read = 0
    """, (
        contact_id,
        user_id
    ))

    conn.commit()

    messages = conn.execute("""
        SELECT
            id,
            sender_id,
            receiver_id,
            message,
            message_type,
            file_name,
            file_url,
            created_at,
            is_read
        FROM messages
        WHERE
        (sender_id = ? AND receiver_id = ?)
        OR
        (sender_id = ? AND receiver_id = ?)
        ORDER BY id ASC
    """, (
        user_id,
        contact_id,
        contact_id,
        user_id
    )).fetchall()

    conn.close()

    result = []

    for msg in messages:

        result.append({
            "id": msg["id"],
            "sender_id": msg["sender_id"],
            "receiver_id": msg["receiver_id"],
            "message": msg["message"],
            "message_type": msg["message_type"],
            "file_name": msg["file_name"],
            "file_url": msg["file_url"],
            "created_at": msg["created_at"],
            "is_read": msg["is_read"]
        })

    return jsonify({
        "success": True,
        "messages": result
    })


# =========================================================
# SEND TEXT MESSAGE - SOCKET.IO
# =========================================================

@socketio.on("send_message")
def socket_send_message(data):

    print("========== SEND MESSAGE ==========")
    print("Session user:", session.get("user_id"))
    print("Received data:", data)

    sender_id = session.get("user_id")

    if not sender_id:
        print("ERROR: User is not logged in to Socket.IO")
        return

    try:
        receiver_id = int(data.get("receiver_id"))
    except Exception as e:
        print("ERROR: Invalid receiver ID:", e)
        return

    message = str(data.get("message", "")).strip()

    if not receiver_id or not message:
        print("ERROR: Empty receiver/message")
        return

    print("Sender:", sender_id)
    print("Receiver:", receiver_id)
    print("Message:", message)

    try:

        saved = save_message(
            sender_id,
            receiver_id,
            message,
            "text"
        )

        print("Message saved:", saved)

        socketio.emit(
            "new_message",
            saved,
            room="user_" + str(receiver_id)
        )

        emit(
            "message_sent",
            saved
        )

        print("Message sent successfully!")

    except Exception as e:

        print("SEND ERROR:", repr(e))


# =========================================================
# UPLOAD FILE
# =========================================================

@app.route("/api/upload", methods=["POST"])
def upload_file():

    sender_id = session.get("user_id")

    if not sender_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        })

    receiver_id = request.form.get("receiver_id")

    if not receiver_id:

        return jsonify({
            "success": False,
            "message": "Receiver not selected."
        })

    try:
        receiver_id = int(receiver_id)
    except:

        return jsonify({
            "success": False,
            "message": "Invalid receiver."
        })

    if "file" not in request.files:

        return jsonify({
            "success": False,
            "message": "No file selected."
        })

    file = request.files["file"]

    if not file.filename:

        return jsonify({
            "success": False,
            "message": "No file selected."
        })

    if not allowed_file(file.filename):

        return jsonify({
            "success": False,
            "message": "This file type is not allowed."
        })

    original_name = secure_filename(file.filename)

    extension = ""

    if "." in original_name:
        extension = "." + original_name.rsplit(".", 1)[1].lower()

    unique_name = (
        str(sender_id)
        + "_"
        + str(int(os.path.getmtime(__file__) * 1000000))
        + "_"
        + original_name
    )

    # Prevent accidental same filename
    unique_name = secure_filename(unique_name)

    save_path = os.path.join(
        UPLOAD_FOLDER,
        unique_name
    )

    file.save(save_path)

    # Determine type
    image_extensions = {
        "png", "jpg", "jpeg", "gif", "webp"
    }

    video_extensions = {
        "mp4", "webm", "mov", "avi"
    }

    ext = extension.replace(".", "").lower()

    if ext in image_extensions:
        message_type = "image"

    elif ext in video_extensions:
        message_type = "video"

    else:
        message_type = "file"

    file_url = "/uploads/" + unique_name

    saved = save_message(
        sender_id,
        receiver_id,
        "",
        message_type,
        original_name,
        file_url
    )

    # Send to receiver
    socketio.emit(
        "new_message",
        saved,
        room="user_" + str(receiver_id)
    )

    # Send back to sender
    socketio.emit(
        "message_sent",
        saved,
        room="user_" + str(sender_id)
)

    return jsonify({
        "success": True,
        "message": saved
    })


# =========================================================
# MARK CHAT AS READ
# =========================================================

@app.route(
    "/api/messages/<int:contact_id>/read",
    methods=["POST"]
)
def mark_read(contact_id):

    user_id = session.get("user_id")

    if not user_id:

        return jsonify({
            "success": False
        })

    conn = get_db()

    conn.execute("""
        UPDATE messages
        SET is_read = 1
        WHERE sender_id = ?
        AND receiver_id = ?
        AND is_read = 0
    """, (
        contact_id,
        user_id
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True
    })


# =========================================================
# SOCKET CONNECT
# =========================================================

@socketio.on("connect")
def socket_connect():

    user_id = session.get("user_id")

    if user_id:

        join_room(
            "user_" + str(user_id)
        )

        print(
            "User connected:",
            user_id
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    init_db()

    print("=" * 50)
    print("                  MyChat")
    print("=" * 50)
    print("")
    print("Server: http://127.0.0.1:8000")
    print("")
    print("Real-time chat enabled!")
    print("File uploads enabled!")
    print("Maximum file size: 100 MB")
    print("")
    print("Press CTRL+C to stop.")
    print("=" * 50)

    socketio.run(
        app,
        host="127.0.0.1",
        port=8000,
        debug=False
    )
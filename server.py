from flask import Flask, request, jsonify, send_from_directory, session
from flask_socketio import SocketIO, emit, join_room
import psycopg2
import psycopg2.extras
import os
import uuid

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


# =========================================================
# APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "mychat-development-secret-change-this"
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

is_render = os.environ.get("RENDER", "").lower() == "true"
app.config["SESSION_COOKIE_SECURE"] = is_render


# =========================================================
# SOCKET.IO
# =========================================================

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    manage_session=True,
    logger=False,
    engineio_logger=False
)


# =========================================================
# DATABASE
# =========================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    """
    Create PostgreSQL connection with safe SSL config for Render.
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is missing."
        )

    db_url = DATABASE_URL
    if "sslmode=" not in db_url:
        separator = "&" if "?" in db_url else "?"
        db_url = db_url + separator + "sslmode=require"

    return psycopg2.connect(
        db_url,
        connect_timeout=10
    )


# =========================================================
# FILE UPLOAD SETTINGS
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "webm", "mov", "avi",
    "pdf", "txt", "zip", "rar",
    "doc", "docx", "xls", "xlsx"
}


# =========================================================
# DATABASE INITIALIZE
# =========================================================

def init_db():
    if not DATABASE_URL:
        print("DATABASE_URL is missing. Skipping DB initialization.")
        return

    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                contact_id INTEGER NOT NULL,
                UNIQUE(user_id, contact_id)
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                message TEXT,
                message_type TEXT DEFAULT 'text',
                file_name TEXT,
                file_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_read INTEGER DEFAULT 0
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_sender_receiver
            ON messages(sender_id, receiver_id);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_receiver_read
            ON messages(receiver_id, is_read);
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_created
            ON messages(created_at);
        """)

        conn.commit()
        print("PostgreSQL database initialized successfully.")

    except Exception as e:
        if conn:
            conn.rollback()
        print("DATABASE INITIALIZATION ERROR:", repr(e))

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# Database initialization safe wrapper
with app.app_context():
    try:
        init_db()
    except Exception as err:
        print("Failed to initialize database on app startup:", repr(err))


# =========================================================
# HELPERS
# =========================================================

def allowed_file(filename):
    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in ALLOWED_EXTENSIONS


def row_to_dict(row):
    return dict(row) if row else None


def user_exists(user_id):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        return cur.fetchone() is not None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_message(message_id):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, sender_id, receiver_id, message, message_type,
                   file_name, file_url, created_at, is_read
            FROM messages WHERE id = %s
        """, (message_id,))
        row = cur.fetchone()
        return row_to_dict(row)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def save_message(sender_id, receiver_id, message="", message_type="text", file_name=None, file_url=None):
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO messages
            (sender_id, receiver_id, message, message_type, file_name, file_url, is_read)
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            RETURNING id
        """, (sender_id, receiver_id, message, message_type, file_name, file_url))

        message_id = cur.fetchone()["id"]
        conn.commit()
        return get_message(message_id)
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# =========================================================
# ROUTES & ENDPOINTS
# =========================================================

@app.route("/health")
def health():
    return jsonify({"success": True, "status": "ok"})


@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/style.css")
def css():
    return send_from_directory(BASE_DIR, "style.css")


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not name or not email or not password:
        return jsonify({"success": False, "message": "All fields are required."}), 400

    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters."}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            return jsonify({"success": False, "message": "This email is already registered."}), 409

        hashed_password = generate_password_hash(password)
        cur.execute("""
            INSERT INTO users (name, email, password)
            VALUES (%s, %s, %s) RETURNING id
        """, (name, email, hashed_password))

        user_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({
            "success": True,
            "message": "Account created successfully.",
            "user": {"id": user_id, "name": name, "email": email}
        })
    except Exception as e:
        if conn:
            conn.rollback()
        print("SIGNUP ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not create account."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email, password FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
    except Exception as e:
        print("LOGIN DATABASE ERROR:", repr(e))
        return jsonify({"success": False, "message": "Database error."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    if not user or not check_password_hash(user["password"], password):
        return jsonify({"success": False, "message": "Email or password is incorrect."}), 401

    session.clear()
    session["user_id"] = user["id"]
    session.modified = True

    return jsonify({
        "success": True,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]}
    })


@app.route("/api/me")
def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"logged_in": False})

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    if not user:
        session.clear()
        return jsonify({"logged_in": False})

    return jsonify({
        "logged_in": True,
        "user": {"id": user["id"], "name": user["name"], "email": user["email"]}
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    response = jsonify({"success": True})
    response.delete_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
    return response


@app.route("/api/add-contact", methods=["POST"])
def add_contact():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Please login first."}), 401

    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()

    if not email:
        return jsonify({"success": False, "message": "Enter an email address."}), 400

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email FROM users WHERE email = %s", (email,))
        contact = cur.fetchone()

        if not contact:
            return jsonify({"success": False, "message": "No account found with this email."}), 404

        if contact["id"] == user_id:
            return jsonify({"success": False, "message": "You cannot add yourself."}), 400

        cur.execute("SELECT id FROM contacts WHERE user_id = %s AND contact_id = %s", (user_id, contact["id"]))
        if cur.fetchone():
            return jsonify({"success": False, "message": "This contact is already added."}), 409

        cur.execute("INSERT INTO contacts (user_id, contact_id) VALUES (%s, %s)", (user_id, contact["id"]))
        conn.commit()

        return jsonify({
            "success": True,
            "contact": {"id": contact["id"], "name": contact["name"], "email": contact["email"]}
        })
    except Exception as e:
        if conn:
            conn.rollback()
        print("ADD CONTACT ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not add contact."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/contacts")
def get_contacts():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "contacts": []}), 401

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT DISTINCT u.id, u.name, u.email
            FROM users u
            WHERE (
                u.id IN (SELECT contact_id FROM contacts WHERE user_id = %s)
                OR u.id IN (
                    SELECT sender_id FROM messages WHERE receiver_id = %s
                    UNION
                    SELECT receiver_id FROM messages WHERE sender_id = %s
                )
            ) AND u.id != %s
            ORDER BY LOWER(u.name) ASC
        """, (user_id, user_id, user_id, user_id))

        contacts = cur.fetchall()
        result = []

        for contact in contacts:
            contact_id = contact["id"]

            cur.execute("""
                SELECT COUNT(*) AS count FROM messages
                WHERE sender_id = %s AND receiver_id = %s AND is_read = 0
            """, (contact_id, user_id))
            unread_row = cur.fetchone()
            unread = int(unread_row["count"] if unread_row else 0)

            cur.execute("""
                SELECT message, message_type, file_name, created_at
                FROM messages
                WHERE (sender_id = %s AND receiver_id = %s)
                   OR (sender_id = %s AND receiver_id = %s)
                ORDER BY id DESC LIMIT 1
            """, (user_id, contact_id, contact_id, user_id))
            last_message = cur.fetchone()

            preview = ""
            if last_message:
                m_type = last_message["message_type"]
                if m_type == "image":
                    preview = "📷 Photo"
                elif m_type == "video":
                    preview = "🎥 Video"
                elif m_type == "file":
                    preview = f"📎 {last_message['file_name'] or 'File'}"
                else:
                    preview = last_message["message"] or ""

            result.append({
                "id": contact["id"],
                "name": contact["name"],
                "email": contact["email"],
                "unread": unread,
                "unread_count": unread,
                "last_message": preview
            })

        return jsonify({"success": True, "contacts": result})
    except Exception as e:
        print("CONTACTS ERROR:", repr(e))
        return jsonify({"success": False, "contacts": [], "message": "Could not load contacts."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/user/<int:user_id>")
def get_user_by_id(user_id):
    current_id = session.get("user_id")
    if not current_id:
        return jsonify({"success": False, "message": "Please login first."}), 401

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()

        if not user:
            return jsonify({"success": False, "message": "User not found."}), 404

        return jsonify({"success": True, "user": {"id": user["id"], "name": user["name"], "email": user["email"]}})
    except Exception as e:
        print("GET USER ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not get user."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/messages/<int:contact_id>")
def get_messages(contact_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "messages": []}), 401

    if not user_exists(contact_id):
        return jsonify({"success": False, "messages": []}), 404

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            UPDATE messages SET is_read = 1
            WHERE sender_id = %s AND receiver_id = %s AND is_read = 0
        """, (contact_id, user_id))

        cur.execute("""
            SELECT id, sender_id, receiver_id, message, message_type,
                   file_name, file_url, created_at, is_read
            FROM messages
            WHERE (sender_id = %s AND receiver_id = %s)
               OR (sender_id = %s AND receiver_id = %s)
            ORDER BY id ASC
        """, (user_id, contact_id, contact_id, user_id))

        messages = cur.fetchall()
        conn.commit()

        result = [
            {
                "id": msg["id"],
                "sender_id": msg["sender_id"],
                "receiver_id": msg["receiver_id"],
                "message": msg["message"],
                "message_type": msg["message_type"],
                "file_name": msg["file_name"],
                "file_url": msg["file_url"],
                "created_at": str(msg["created_at"]),
                "is_read": msg["is_read"]
            } for msg in messages
        ]

        return jsonify({"success": True, "messages": result})
    except Exception as e:
        if conn:
            conn.rollback()
        print("GET MESSAGES ERROR:", repr(e))
        return jsonify({"success": False, "messages": []}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# =========================================================
# SOCKET EVENTS
# =========================================================

@socketio.on("send_message")
def socket_send_message(data):
    if not isinstance(data, dict):
        emit("message_error", {"message": "Invalid message data."})
        return

    sender_id = session.get("user_id")
    if not sender_id:
        emit("message_error", {"message": "You are not logged in."})
        return

    try:
        receiver_id = int(data.get("receiver_id"))
    except Exception:
        emit("message_error", {"message": "Invalid receiver."})
        return

    message = str(data.get("message", "")).strip()

    if not receiver_id or not message:
        return

    if receiver_id == int(sender_id):
        emit("message_error", {"message": "You cannot message yourself."})
        return

    try:
        if not user_exists(receiver_id):
            emit("message_error", {"message": "Receiver account was not found."})
            return

        saved = save_message(sender_id, receiver_id, message, "text")
        if not saved:
            emit("message_error", {"message": "Message could not be saved."})
            return

        socketio.emit("new_message", saved, room=f"user_{receiver_id}")
        emit("message_sent", saved)
    except Exception as e:
        print("SEND MESSAGE ERROR:", repr(e))
        emit("message_error", {"message": "Message could not be sent."})


@app.route("/api/upload", methods=["POST"])
def upload_file():
    sender_id = session.get("user_id")
    if not sender_id:
        return jsonify({"success": False, "message": "Please login first."}), 401

    receiver_id = request.form.get("receiver_id")
    if not receiver_id:
        return jsonify({"success": False, "message": "Receiver not selected."}), 400

    try:
        receiver_id = int(receiver_id)
    except Exception:
        return jsonify({"success": False, "message": "Invalid receiver."}), 400

    if receiver_id == int(sender_id):
        return jsonify({"success": False, "message": "You cannot send files to yourself."}), 400

    if not user_exists(receiver_id):
        return jsonify({"success": False, "message": "Receiver account was not found."}), 404

    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"success": False, "message": "No file selected."}), 400

    file = request.files["file"]
    if not allowed_file(file.filename):
        return jsonify({"success": False, "message": "This file type is not allowed."}), 400

    original_name = secure_filename(file.filename)
    extension = f".{original_name.rsplit('.', 1)[1].lower()}" if "." in original_name else ""
    unique_name = f"{sender_id}_{uuid.uuid4().hex}{extension}"
    save_path = os.path.join(UPLOAD_FOLDER, unique_name)

    try:
        file.save(save_path)
    except Exception as e:
        print("FILE SAVE ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not save file."}), 500

    ext = extension.replace(".", "").lower()
    if ext in {"png", "jpg", "jpeg", "gif", "webp"}:
        message_type = "image"
    elif ext in {"mp4", "webm", "mov", "avi"}:
        message_type = "video"
    else:
        message_type = "file"

    file_url = f"/uploads/{unique_name}"

    try:
        saved = save_message(sender_id, receiver_id, "", message_type, original_name, file_url)
    except Exception as e:
        if os.path.exists(save_path):
            os.remove(save_path)
        print("FILE MESSAGE DATABASE ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not save file message."}), 500

    socketio.emit("new_message", saved, room=f"user_{receiver_id}")
    socketio.emit("message_sent", saved, room=f"user_{sender_id}")

    return jsonify({"success": True, "message": saved})


@app.route("/api/messages/<int:contact_id>/read", methods=["POST"])
def mark_read(contact_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False}), 401

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE messages SET is_read = 1
            WHERE sender_id = %s AND receiver_id = %s AND is_read = 0
        """, (contact_id, user_id))
        conn.commit()

        socketio.emit("messages_read", {"user_id": user_id, "contact_id": contact_id}, room=f"user_{contact_id}")
        return jsonify({"success": True})
    except Exception as e:
        if conn:
            conn.rollback()
        print("MARK READ ERROR:", repr(e))
        return jsonify({"success": False}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@socketio.on("connect")
def socket_connect():
    user_id = session.get("user_id")
    if not user_id:
        return False
    join_room(f"user_{user_id}")


@socketio.on("disconnect")
def socket_disconnect():
    pass


@socketio.on_error_default
def socket_error_handler(e):
    print("SOCKET ERROR:", repr(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)

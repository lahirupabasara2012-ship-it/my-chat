from flask import Flask, request, jsonify, send_from_directory, session
from flask_socketio import SocketIO, emit, join_room
import os
import uuid
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mychat-development-secret-change-this")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
is_render = os.environ.get("RENDER", "").lower() == "true" or bool(os.environ.get("RENDER_EXTERNAL_URL"))
app.config["SESSION_COOKIE_SECURE"] = is_render
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    manage_session=True,
    logger=False,
    engineio_logger=False,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "webm", "mov", "avi",
    "pdf", "txt", "zip", "rar", "doc", "docx", "xls", "xlsx"
}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
VIDEO_EXTENSIONS = {"mp4", "webm", "mov", "avi"}

online_users = {}


def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is missing.")
    db_url = DATABASE_URL
    if "sslmode=" not in db_url:
        db_url += ("&" if "?" in db_url else "?") + "sslmode=require"
    return psycopg2.connect(db_url, connect_timeout=10)


def init_db():
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
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                contact_id INTEGER NOT NULL,
                UNIQUE(user_id, contact_id)
            )
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
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                id SERIAL PRIMARY KEY,
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                UNIQUE(group_id, user_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id SERIAL PRIMARY KEY,
                group_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT")
        cur.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_read INTEGER DEFAULT 0")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_sender_receiver ON messages(sender_id, receiver_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_receiver_read ON messages(receiver_id, is_read)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_group_members_user ON group_members(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_group_messages_group ON group_messages(group_id, id)")
        conn.commit()
        print("PostgreSQL database initialized successfully.")
    except Exception as e:
        if conn:
            conn.rollback()
        print("DATABASE INITIALIZATION ERROR:", repr(e))
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def user_exists(user_id):
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE id=%s", (user_id,))
        return cur.fetchone() is not None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def is_user_online(user_id):
    user_id = int(user_id)
    return user_id in online_users and bool(online_users[user_id])


def add_online_user(user_id, sid):
    user_id = int(user_id)
    sessions = online_users.setdefault(user_id, set())
    was_offline = not sessions
    sessions.add(sid)
    return was_offline


def remove_online_user(user_id, sid):
    if not user_id:
        return False
    user_id = int(user_id)
    sessions = online_users.get(user_id)
    if not sessions:
        return False
    sessions.discard(sid)
    if not sessions:
        online_users.pop(user_id, None)
        return True
    return False


def broadcast_presence(user_id, online):
    socketio.emit("user_status", {"user_id": int(user_id), "online": bool(online)})


def save_message(sender_id, receiver_id, message="", message_type="text", file_name=None, file_url=None):
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            INSERT INTO messages
            (sender_id, receiver_id, message, message_type, file_name, file_url, is_read)
            VALUES (%s, %s, %s, %s, %s, %s, 0)
            RETURNING id, sender_id, receiver_id, message, message_type, file_name, file_url, created_at, is_read
        """, (sender_id, receiver_id, message, message_type, file_name, file_url))
        row = dict(cur.fetchone())
        conn.commit()
        row["created_at"] = str(row["created_at"])
        return row
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.errorhandler(413)
def too_large(_):
    return jsonify({"success": False, "message": "File is too large. Maximum size is 100MB."}), 413


@app.route("/health")
def health():
    return jsonify({"success": True, "status": "ok", "online_users": len(online_users)})


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
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            return jsonify({"success": False, "message": "This email is already registered."}), 409
        cur.execute("""
            INSERT INTO users (name, email, password)
            VALUES (%s, %s, %s)
            RETURNING id, name, email, avatar_url
        """, (name, email, generate_password_hash(password)))
        user = dict(cur.fetchone())
        conn.commit()
        return jsonify({"success": True, "user": user})
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
    conn = cur = None
    user = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email, password, avatar_url FROM users WHERE email=%s", (email,))
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
        "user": {"id": user["id"], "name": user["name"], "email": user["email"], "avatar_url": user["avatar_url"]}
    })


@app.route("/api/me")
def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"logged_in": False})
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email, avatar_url FROM users WHERE id=%s", (user_id,))
        user = cur.fetchone()
        if not user:
            session.clear()
            return jsonify({"logged_in": False})
        return jsonify({"logged_in": True, "user": dict(user)})
    except Exception as e:
        print("ME ERROR:", repr(e))
        return jsonify({"logged_in": False}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/logout", methods=["POST"])
def logout():
    user_id = session.get("user_id")
    if user_id:
        online_users.pop(int(user_id), None)
        broadcast_presence(user_id, False)
    session.clear()
    return jsonify({"success": True})


@app.route("/api/add-contact", methods=["POST"])
def add_contact():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Please login first."}), 401
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    if not email:
        return jsonify({"success": False, "message": "Enter an email address."}), 400
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email, avatar_url FROM users WHERE email=%s", (email,))
        contact = cur.fetchone()
        if not contact:
            return jsonify({"success": False, "message": "No account found with this email."}), 404
        if int(contact["id"]) == int(user_id):
            return jsonify({"success": False, "message": "You cannot add yourself."}), 400
        cur.execute("SELECT id FROM contacts WHERE user_id=%s AND contact_id=%s", (user_id, contact["id"]))
        if cur.fetchone():
            return jsonify({"success": False, "message": "This contact is already added."}), 409
        cur.execute("INSERT INTO contacts (user_id, contact_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (user_id, contact["id"]))
        cur.execute("INSERT INTO contacts (user_id, contact_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (contact["id"], user_id))
        conn.commit()
        return jsonify({"success": True, "contact": {
            "id": contact["id"], "name": contact["name"], "email": contact["email"],
            "avatar_url": contact["avatar_url"], "online": is_user_online(contact["id"])
        }})
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
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.id, u.name, u.email, u.avatar_url
            FROM users u
            WHERE u.id IN (
                SELECT contact_id FROM contacts WHERE user_id=%s
                UNION SELECT sender_id FROM messages WHERE receiver_id=%s
                UNION SELECT receiver_id FROM messages WHERE sender_id=%s
            ) AND u.id != %s
            ORDER BY LOWER(u.name)
        """, (user_id, user_id, user_id, user_id))
        users = cur.fetchall()
        result = []
        for user in users:
            cid = int(user["id"])
            cur.execute("SELECT COUNT(*) AS count FROM messages WHERE sender_id=%s AND receiver_id=%s AND is_read=0", (cid, user_id))
            unread = int(cur.fetchone()["count"])
            cur.execute("""
                SELECT message, message_type, file_name
                FROM messages
                WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)
                ORDER BY id DESC LIMIT 1
            """, (user_id, cid, cid, user_id))
            last = cur.fetchone()
            preview = ""
            if last:
                if last["message_type"] == "image":
                    preview = "📷 Photo"
                elif last["message_type"] == "video":
                    preview = "🎥 Video"
                elif last["message_type"] == "file":
                    preview = "📎 " + (last["file_name"] or "File")
                else:
                    preview = last["message"] or ""
            result.append({
                "id": cid, "name": user["name"], "email": user["email"], "avatar_url": user["avatar_url"],
                "unread": unread, "unread_count": unread, "last_message": preview, "online": is_user_online(cid)
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


@app.route("/api/profile", methods=["PUT"])
def update_profile():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Please login first."}), 401
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"success": False, "message": "Name is required."}), 400
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("UPDATE users SET name=%s WHERE id=%s RETURNING id, name, email, avatar_url", (name, user_id))
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "message": "User not found."}), 404
        user = dict(row)
        conn.commit()
        return jsonify({"success": True, "user": user})
    except Exception as e:
        if conn:
            conn.rollback()
        print("PROFILE UPDATE ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not update profile."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/profile/photo", methods=["POST"])
def profile_photo():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Please login first."}), 401
    if "photo" not in request.files:
        return jsonify({"success": False, "message": "No photo selected."}), 400
    photo = request.files["photo"]
    if not photo.filename:
        return jsonify({"success": False, "message": "No photo selected."}), 400
    original = secure_filename(photo.filename)
    if not original or "." not in original:
        return jsonify({"success": False, "message": "Invalid image."}), 400
    extension = original.rsplit(".", 1)[1].lower()
    if extension not in IMAGE_EXTENSIONS:
        return jsonify({"success": False, "message": "Only JPG, PNG, GIF and WEBP are allowed."}), 400
    filename = f"profile_{int(user_id)}_{uuid.uuid4().hex}.{extension}"
    path = os.path.join(UPLOAD_FOLDER, filename)
    conn = cur = None
    try:
        photo.save(path)
        avatar_url = "/uploads/" + filename
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("UPDATE users SET avatar_url=%s WHERE id=%s RETURNING id, name, email, avatar_url", (avatar_url, user_id))
        row = cur.fetchone()
        if not row:
            raise RuntimeError("User not found.")
        user = dict(row)
        conn.commit()
        return jsonify({"success": True, "user": user})
    except Exception as e:
        if conn:
            conn.rollback()
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        print("PROFILE PHOTO ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not upload profile photo."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/groups", methods=["GET"])
def get_groups():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "groups": []}), 401
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT g.id, g.name, g.owner_id,
                   (SELECT COUNT(*) FROM group_members gm2 WHERE gm2.group_id=g.id) AS member_count
            FROM groups g JOIN group_members gm ON gm.group_id=g.id
            WHERE gm.user_id=%s ORDER BY g.id DESC
        """, (user_id,))
        return jsonify({"success": True, "groups": [dict(r) for r in cur.fetchall()]})
    except Exception as e:
        print("GROUPS ERROR:", repr(e))
        return jsonify({"success": False, "groups": []}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/groups", methods=["POST"])
def create_group():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "Please login first."}), 401
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    member_ids = data.get("member_ids", [])
    if not name:
        return jsonify({"success": False, "message": "Group name is required."}), 400
    if not isinstance(member_ids, list):
        member_ids = []
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("INSERT INTO groups (name, owner_id) VALUES (%s, %s) RETURNING id, name, owner_id", (name, user_id))
        group = dict(cur.fetchone())
        group_id = int(group["id"])
        members = {int(user_id)}
        for member_id in member_ids:
            try:
                member_id = int(member_id)
            except (TypeError, ValueError):
                continue
            if member_id == int(user_id):
                continue
            cur.execute("SELECT id FROM users WHERE id=%s", (member_id,))
            if cur.fetchone():
                members.add(member_id)
        for member_id in members:
            cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (group_id, member_id))
        conn.commit()
        return jsonify({"success": True, "group": {"id": group_id, "name": group["name"], "owner_id": group["owner_id"], "member_count": len(members)}})
    except Exception as e:
        if conn:
            conn.rollback()
        print("CREATE GROUP ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not create group."}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/groups/<int:group_id>/messages")
def get_group_messages(group_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "messages": []}), 401
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT 1 FROM group_members WHERE group_id=%s AND user_id=%s", (group_id, user_id))
        if not cur.fetchone():
            return jsonify({"success": False, "messages": []}), 403
        cur.execute("""
            SELECT gm.id, gm.group_id, gm.sender_id, gm.message, gm.created_at, u.name AS sender_name
            FROM group_messages gm JOIN users u ON u.id=gm.sender_id
            WHERE gm.group_id=%s ORDER BY gm.id ASC
        """, (group_id,))
        messages = []
        for row in cur.fetchall():
            item = dict(row)
            item["created_at"] = str(item["created_at"])
            messages.append(item)
        return jsonify({"success": True, "messages": messages})
    except Exception as e:
        print("GROUP MESSAGES ERROR:", repr(e))
        return jsonify({"success": False, "messages": []}), 500
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
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("UPDATE messages SET is_read=1 WHERE sender_id=%s AND receiver_id=%s AND is_read=0", (contact_id, user_id))
        cur.execute("""
            SELECT id, sender_id, receiver_id, message, message_type, file_name, file_url, created_at, is_read
            FROM messages
            WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)
            ORDER BY id ASC
        """, (user_id, contact_id, contact_id, user_id))
        messages = []
        for row in cur.fetchall():
            item = dict(row)
            item["created_at"] = str(item["created_at"])
            messages.append(item)
        conn.commit()
        return jsonify({"success": True, "messages": messages})
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


@socketio.on("send_message")
def socket_send_message(data):
    sender_id = session.get("user_id")
    if not sender_id or not isinstance(data, dict):
        return
    try:
        receiver_id = int(data.get("receiver_id"))
    except (TypeError, ValueError):
        emit("message_error", {"message": "Invalid receiver."})
        return
    message = str(data.get("message", "")).strip()
    if not message:
        return
    if receiver_id == int(sender_id):
        emit("message_error", {"message": "You cannot message yourself."})
        return
    try:
        if not user_exists(receiver_id):
            emit("message_error", {"message": "Receiver account was not found."})
            return
        saved = save_message(sender_id, receiver_id, message, "text")
        socketio.emit("new_message", saved, room="user_" + str(receiver_id))
        emit("message_sent", saved)
    except Exception as e:
        print("SEND MESSAGE ERROR:", repr(e))
        emit("message_error", {"message": "Message could not be sent."})


@socketio.on("send_group_message")
def socket_send_group_message(data):
    user_id = session.get("user_id")
    if not user_id or not isinstance(data, dict):
        return
    try:
        group_id = int(data.get("group_id"))
    except (TypeError, ValueError):
        return
    message = str(data.get("message", "")).strip()
    if not message:
        return
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT 1 FROM group_members WHERE group_id=%s AND user_id=%s", (group_id, user_id))
        if not cur.fetchone():
            emit("message_error", {"message": "You are not a member of this group."})
            return
        cur.execute("INSERT INTO group_messages (group_id, sender_id, message) VALUES (%s, %s, %s) RETURNING id, group_id, sender_id, message, created_at", (group_id, user_id, message))
        result = dict(cur.fetchone())
        cur.execute("SELECT name FROM users WHERE id=%s", (user_id,))
        sender = cur.fetchone()
        result["sender_name"] = sender["name"] if sender else "User"
        result["created_at"] = str(result["created_at"])
        cur.execute("SELECT user_id FROM group_members WHERE group_id=%s", (group_id,))
        members = [row["user_id"] for row in cur.fetchall()]
        conn.commit()
        for member_id in members:
            socketio.emit("group_message", result, room="user_" + str(member_id))
    except Exception as e:
        if conn:
            conn.rollback()
        print("GROUP SEND ERROR:", repr(e))
        emit("message_error", {"message": "Group message could not be sent."})
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@socketio.on("typing")
def socket_typing(data):
    sender_id = session.get("user_id")
    if not sender_id or not isinstance(data, dict):
        return
    try:
        receiver_id = int(data.get("receiver_id"))
    except (TypeError, ValueError):
        return
    if receiver_id == int(sender_id):
        return
    socketio.emit("user_typing", {"user_id": int(sender_id), "typing": bool(data.get("typing", False))}, room="user_" + str(receiver_id))


@app.route("/api/upload", methods=["POST"])
def upload_file():
    sender_id = session.get("user_id")
    if not sender_id:
        return jsonify({"success": False, "message": "Please login first."}), 401
    try:
        receiver_id = int(request.form.get("receiver_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid receiver."}), 400
    if not user_exists(receiver_id):
        return jsonify({"success": False, "message": "Receiver not found."}), 404
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"success": False, "message": "No file selected."}), 400
    if "." not in file.filename:
        return jsonify({"success": False, "message": "Invalid file."}), 400
    original_name = secure_filename(file.filename)
    extension = original_name.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return jsonify({"success": False, "message": "This file type is not allowed."}), 400
    unique_name = f"{int(sender_id)}_{uuid.uuid4().hex}.{extension}"
    path = os.path.join(UPLOAD_FOLDER, unique_name)
    try:
        file.save(path)
        message_type = "image" if extension in IMAGE_EXTENSIONS else "video" if extension in VIDEO_EXTENSIONS else "file"
        saved = save_message(sender_id, receiver_id, "", message_type, original_name, "/uploads/" + unique_name)
        socketio.emit("new_message", saved, room="user_" + str(receiver_id))
        return jsonify({"success": True, "message": saved})
    except Exception as e:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
        print("UPLOAD ERROR:", repr(e))
        return jsonify({"success": False, "message": "Could not save file message."}), 500


@app.route("/api/messages/<int:contact_id>/read", methods=["POST"])
def mark_read(contact_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False}), 401
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE messages SET is_read=1 WHERE sender_id=%s AND receiver_id=%s AND is_read=0", (contact_id, user_id))
        conn.commit()
        socketio.emit("messages_read", {"user_id": int(user_id), "contact_id": int(contact_id)}, room="user_" + str(contact_id))
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


@socketio.on("message_delivered_ack")
def socket_message_delivered_ack(data):
    receiver_id = session.get("user_id")
    if not receiver_id or not isinstance(data, dict):
        return
    try:
        message_id = int(data.get("message_id"))
        sender_id = int(data.get("sender_id"))
    except (TypeError, ValueError):
        return
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM messages WHERE id=%s AND sender_id=%s AND receiver_id=%s", (message_id, sender_id, receiver_id))
        if not cur.fetchone():
            return
        socketio.emit("message_delivered", {"message_id": message_id, "sender_id": sender_id, "receiver_id": int(receiver_id)}, room="user_" + str(sender_id))
    except Exception as e:
        print("DELIVERY ACK ERROR:", repr(e))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@socketio.on("mark_read")
def socket_mark_read(data):
    user_id = session.get("user_id")
    if not user_id or not isinstance(data, dict):
        return
    try:
        contact_id = int(data.get("contact_id"))
    except (TypeError, ValueError):
        return
    conn = cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE messages SET is_read=1 WHERE sender_id=%s AND receiver_id=%s AND is_read=0", (contact_id, user_id))
        conn.commit()
        socketio.emit("messages_read", {"user_id": int(user_id), "contact_id": int(contact_id)}, room="user_" + str(contact_id))
    except Exception as e:
        if conn:
            conn.rollback()
        print("SOCKET MARK READ ERROR:", repr(e))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.route("/api/online-users")
def online_users_api():
    if not session.get("user_id"):
        return jsonify({"success": False, "users": []}), 401
    return jsonify({"success": True, "users": list(online_users.keys())})


@socketio.on("connect")
def socket_connect():
    user_id = session.get("user_id")
    print("SOCKET CONNECT:", user_id)
    if not user_id:
        return False
    join_room("user_" + str(user_id))
    became_online = add_online_user(user_id, request.sid)
    emit("online_users", {"users": list(online_users.keys())})
    if became_online:
        broadcast_presence(user_id, True)


@socketio.on("disconnect")
def socket_disconnect(reason=None):
    user_id = session.get("user_id")
    print("SOCKET DISCONNECT:", user_id, reason)
    if user_id and remove_online_user(user_id, request.sid):
        broadcast_presence(user_id, False)


@socketio.on_error_default
def socket_error_handler(error):
    print("SOCKET ERROR:", repr(error))


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is missing. Add your Render PostgreSQL DATABASE_URL.")

init_db()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False, allow_unsafe_werkzeug=True)

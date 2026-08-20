from flask import Flask, request, jsonify, send_from_directory, session
from flask_socketio import SocketIO, emit, join_room
import uuid
import psycopg2
import psycopg2.extras
import os

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-secret-key"
)


socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"
)

DATABASE_URL = os.environ.get("DATABASE_URL")


UPLOAD_FOLDER = "/opt/render/project/src/data/uploads"

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =========================================================
# DATABASE
# =========================================================

def get_db():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is missing"
        )

    conn = psycopg2.connect(DATABASE_URL)

    return conn


def get_db():

    conn = psycopg2.connect(
        DATABASE_URL
    )

    return conn


# =========================================================
# INITIALIZE DATABASE
# =========================================================

def init_db():

    conn = get_db()

    cur = conn.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # CONTACTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            UNIQUE(user_id, contact_id)
        )
    """)

    # MESSAGES
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

    conn.commit()

    cur.close()
    conn.close()

    print("PostgreSQL database initialized successfully.")


# =========================================================
# HELPERS
# =========================================================

def allowed_file(filename):

    if "." not in filename:
        return False

    extension = filename.rsplit(
        ".",
        1
    )[1].lower()

    return extension in ALLOWED_EXTENSIONS


def row_to_dict(row):

    if not row:
        return None

    return dict(row)


# =========================================================
# FILE SETTINGS
# =========================================================

UPLOAD_FOLDER = "/opt/render/project/src/data/uploads"

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "webp",

    "mp4",
    "webm",
    "mov",
    "avi",

    "pdf",
    "txt",
    "zip",
    "rar",

    "doc",
    "docx",
    "xls",
    "xlsx"
}

MAX_FILE_SIZE = 100 * 1024 * 1024

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)


# =========================================================
# GET MESSAGE
# =========================================================

def get_message(message_id):

    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    cur.execute("""
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
        WHERE id = %s
    """, (
        message_id,
    ))

    row = cur.fetchone()

    cur.close()
    conn.close()

    return row_to_dict(row)


# =========================================================
# SAVE MESSAGE
# =========================================================

def save_message(
    sender_id,
    receiver_id,
    message="",
    message_type="text",
    file_name=None,
    file_url=None
):

    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    cur.execute("""
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
        VALUES (%s, %s, %s, %s, %s, %s, 0)
        RETURNING id
    """, (
        sender_id,
        receiver_id,
        message,
        message_type,
        file_name,
        file_url
    ))

    message_id = cur.fetchone()["id"]

    conn.commit()

    cur.close()
    conn.close()

    return get_message(message_id)


# =========================================================
# FRONTEND
# =========================================================

@app.route("/")
def home():

    return send_from_directory(
        ".",
        "index.html"
    )


@app.route("/style.css")
def css():

    return send_from_directory(
        ".",
        "style.css"
    )


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

@app.route(
    "/api/signup",
    methods=["POST"]
)
def signup():

    data = request.get_json() or {}

    name = data.get(
        "name",
        ""
    ).strip()

    email = data.get(
        "email",
        ""
    ).strip().lower()

    password = data.get(
        "password",
        ""
    )

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

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    # Check existing user
    cur.execute("""
        SELECT id
        FROM users
        WHERE email = %s
    """, (
        email,
    ))

    existing = cur.fetchone()

    if existing:

        cur.close()
        conn.close()

        return jsonify({
            "success": False,
            "message": "This email is already registered."
        })

    hashed_password = generate_password_hash(
        password
    )

    cur.execute("""
        INSERT INTO users
        (
            name,
            email,
            password
        )
        VALUES (%s, %s, %s)
        RETURNING id
    """, (
        name,
        email,
        hashed_password
    ))

    user_id = cur.fetchone()["id"]

    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "success": True,
        "message": "Account created successfully.",
        "user": {
            "id": user_id,
            "name": name,
            "email": email
        }
    })


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/api/login",
    methods=["POST"]
)
def login():

    data = request.get_json() or {}

    email = data.get(
        "email",
        ""
    ).strip().lower()

    password = data.get(
        "password",
        ""
    )

    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    cur.execute("""
        SELECT
            id,
            name,
            email,
            password
        FROM users
        WHERE email = %s
    """, (
        email,
    ))

    user = cur.fetchone()

    cur.close()
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

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return jsonify({
            "logged_in": False
        })

    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    cur.execute("""
        SELECT
            id,
            name,
            email
        FROM users
        WHERE id = %s
    """, (
        user_id,
    ))

    user = cur.fetchone()

    cur.close()
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

@app.route(
    "/api/logout",
    methods=["POST"]
)
def logout():

    session.clear()

    return jsonify({
        "success": True
    })


# =========================================================
# ADD CONTACT
# =========================================================

@app.route(
    "/api/add-contact",
    methods=["POST"]
)
def add_contact():

    user_id = session.get(
        "user_id"
    )

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

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    cur.execute("""
        SELECT
            id,
            name,
            email
        FROM users
        WHERE email = %s
    """, (
        email,
    ))

    contact = cur.fetchone()

    if not contact:

        cur.close()
        conn.close()

        return jsonify({
            "success": False,
            "message": "No account found with this email."
        })

    if contact["id"] == user_id:

        cur.close()
        conn.close()

        return jsonify({
            "success": False,
            "message": "You cannot add yourself."
        })

    cur.execute("""
        SELECT id
        FROM contacts
        WHERE user_id = %s
        AND contact_id = %s
    """, (
        user_id,
        contact["id"]
    ))

    already = cur.fetchone()

    if already:

        cur.close()
        conn.close()

        return jsonify({
            "success": False,
            "message": "This contact is already added."
        })

    cur.execute("""
        INSERT INTO contacts
        (
            user_id,
            contact_id
        )
        VALUES (%s, %s)
    """, (
        user_id,
        contact["id"]
    ))

    conn.commit()

    cur.close()
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

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return jsonify({
            "success": False
        })

    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    cur.execute("""
        SELECT
            users.id,
            users.name,
            users.email
        FROM contacts
        JOIN users
        ON users.id = contacts.contact_id
        WHERE contacts.user_id = %s
        ORDER BY users.name
    """, (
        user_id,
    ))

    contacts = cur.fetchall()

    result = []

    for contact in contacts:

        cur.execute("""
            SELECT COUNT(*) AS count
            FROM messages
            WHERE sender_id = %s
            AND receiver_id = %s
            AND is_read = 0
        """, (
            contact["id"],
            user_id
        ))

        unread = cur.fetchone()["count"]

        cur.execute("""
            SELECT
                message,
                message_type,
                file_name
            FROM messages
            WHERE
            (sender_id = %s AND receiver_id = %s)
            OR
            (sender_id = %s AND receiver_id = %s)
            ORDER BY id DESC
            LIMIT 1
        """, (
            user_id,
            contact["id"],
            contact["id"],
            user_id
        ))

        last_message = cur.fetchone()

        preview = ""

        if last_message:

            if last_message["message_type"] == "image":
                preview = "📷 Photo"

            elif last_message["message_type"] == "video":
                preview = "🎥 Video"

            elif last_message["message_type"] == "file":
                preview = "📎 " + (
                    last_message["file_name"]
                    or "File"
                )

            else:
                preview = (
                    last_message["message"]
                    or ""
                )

        result.append({
            "id": contact["id"],
            "name": contact["name"],
            "email": contact["email"],
            "unread": unread,
            "last_message": preview
        })

    cur.close()
    conn.close()

    return jsonify({
        "success": True,
        "contacts": result
    })


# =========================================================
# GET MESSAGES
# =========================================================

@app.route(
    "/api/messages/<int:contact_id>"
)
def get_messages(contact_id):

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return jsonify({
            "success": False
        })

    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    # Mark received messages as read
    cur.execute("""
        UPDATE messages
        SET is_read = 1
        WHERE sender_id = %s
        AND receiver_id = %s
        AND is_read = 0
    """, (
        contact_id,
        user_id
    ))

    cur.execute("""
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
        (sender_id = %s AND receiver_id = %s)
        OR
        (sender_id = %s AND receiver_id = %s)
        ORDER BY id ASC
    """, (
        user_id,
        contact_id,
        contact_id,
        user_id
    ))

    messages = cur.fetchall()

    conn.commit()

    cur.close()
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
            "created_at": str(msg["created_at"]),
            "is_read": msg["is_read"]
        })

    return jsonify({
        "success": True,
        "messages": result
    })


# =========================================================
# SEND TEXT MESSAGE
# =========================================================

@socketio.on("send_message")
def socket_send_message(data):

    print("========================================")
    print("SEND MESSAGE EVENT")
    print("Socket ID:", request.sid)

    sender_id = session.get("user_id")

    print("Sender ID:", sender_id)
    print("Data:", data)

    if not sender_id:
        print("ERROR: No logged-in user")
        return

    try:
        receiver_id = int(data.get("receiver_id"))
    except Exception as e:
        print("ERROR: Invalid receiver ID:", e)
        return

    message = str(
        data.get("message", "")
    ).strip()

    if not receiver_id or not message:
        print("ERROR: Empty message or receiver")
        return

    try:

        # Save to PostgreSQL
        saved = save_message(
            sender_id,
            receiver_id,
            message,
            "text"
        )

        print("MESSAGE SAVED:")
        print(saved)

        # -----------------------------------------
        # SEND TO SENDER
        # -----------------------------------------

        emit(
            "message_sent",
            saved,
            to=request.sid
        )

        print(
            "Sent message_sent to:",
            request.sid
        )

        # -----------------------------------------
        # SEND TO RECEIVER ROOM
        # -----------------------------------------

        receiver_room = (
            "user_" +
            str(receiver_id)
        )

        socketio.emit(
            "new_message",
            saved,
            room=receiver_room
        )

        print(
            "Sent new_message to room:",
            receiver_room
        )

        print("MESSAGE DELIVERY COMPLETE")
        print("========================================")

    except Exception as e:

        print(
            "SEND MESSAGE ERROR:",
            repr(e)
        )


# =========================================================
# UPLOAD FILE
# =========================================================

@app.route(
    "/api/upload",
    methods=["POST"]
)
def upload_file():

    sender_id = session.get(
        "user_id"
    )

    if not sender_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        })

    receiver_id = request.form.get(
        "receiver_id"
    )

    if not receiver_id:

        return jsonify({
            "success": False,
            "message": "Receiver not selected."
        })

    try:

        receiver_id = int(
            receiver_id
        )

    except Exception:

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

    if not allowed_file(
        file.filename
    ):

        return jsonify({
            "success": False,
            "message": "This file type is not allowed."
        })

    original_name = secure_filename(
        file.filename
    )

    extension = ""

    if "." in original_name:

        extension = (
            "."
            + original_name.rsplit(
                ".",
                1
            )[1].lower()
        )

    unique_name = (
        str(sender_id)
        + "_"
        + uuid.uuid4().hex
        + extension
    )

    save_path = os.path.join(
        UPLOAD_FOLDER,
        unique_name
    )

    file.save(
        save_path
    )

    # Determine type
    image_extensions = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp"
    }

    video_extensions = {
        "mp4",
        "webm",
        "mov",
        "avi"
    }

    ext = extension.replace(
        ".",
        ""
    ).lower()

    if ext in image_extensions:

        message_type = "image"

    elif ext in video_extensions:

        message_type = "video"

    else:

        message_type = "file"

    file_url = (
        "/uploads/"
        + unique_name
    )

    saved = save_message(
        sender_id,
        receiver_id,
        "",
        message_type,
        original_name,
        file_url
    )

    # Receiver
    socketio.emit(
        "new_message",
        saved,
        room="user_" + str(receiver_id)
    )

    # Sender
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

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return jsonify({
            "success": False
        })

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        UPDATE messages
        SET is_read = 1
        WHERE sender_id = %s
        AND receiver_id = %s
        AND is_read = 0
    """, (
        contact_id,
        user_id
    ))

    conn.commit()

    cur.close()
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

    print("================================")
    print("SOCKET CONNECT")
    print("Session user:", user_id)
    print("Socket ID:", request.sid)
    print("================================")

    if not user_id:
        print("Socket connected WITHOUT login")
        return False

    room_name = "user_" + str(user_id)

    join_room(room_name)

    print(
        "User joined room:",
        room_name
    )

# =========================================================
# INITIALIZE DATABASE
# =========================================================

init_db()


# =========================================================
# START LOCAL SERVER
# =========================================================

if __name__ == "__main__":

    print("=" * 50)
    print("                  MyChat")
    print("=" * 50)

    print("")
    print(
        "Server: http://127.0.0.1:8000"
    )

    print("")
    print(
        "Real-time chat enabled!"
    )

    print(
        "File uploads enabled!"
    )

    print(
        "Maximum file size: 100 MB"
    )

    print("")
    print(
        "Press CTRL+C to stop."
    )

    print("=" * 50)

    socketio.run(
        app,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                8000
            )
        ),
        debug=False
    )

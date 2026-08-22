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
# FILE UPLOADS
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "uploads"
)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

MAX_FILE_SIZE = 100 * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)

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


# =========================================================
# ONLINE USERS
# =========================================================
#
# user_id -> set of Socket.IO session IDs
#
# This supports multiple tabs/devices for the same account.
# =========================================================

online_users = {}


def add_online_user(
    user_id,
    sid
):

    user_id = int(user_id)

    if user_id not in online_users:
        online_users[user_id] = set()

    was_offline = (
        len(online_users[user_id]) == 0
    )

    online_users[user_id].add(sid)

    return was_offline


def remove_online_user(
    user_id,
    sid
):

    if not user_id:
        return False

    user_id = int(user_id)

    sessions = online_users.get(
        user_id
    )

    if not sessions:
        return False

    sessions.discard(
        sid
    )

    if not sessions:

        online_users.pop(
            user_id,
            None
        )

        return True

    return False


def is_user_online(
    user_id
):

    return (
        int(user_id) in online_users
        and
        bool(
            online_users[
                int(user_id)
            ]
        )
    )


def get_online_user_ids():

    return list(
        online_users.keys()
    )


def broadcast_presence(
    user_id,
    online
):

    socketio.emit(
        "user_status",
        {
            "user_id": int(user_id),
            "online": bool(online)
        }
    )


# =========================================================
# DATABASE INITIALIZE
# =========================================================

def init_db():

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor()


        # -------------------------------------------------
        # USERS
        # -------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        """)


        # -------------------------------------------------
        # CONTACTS
        # -------------------------------------------------

        cur.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                contact_id INTEGER NOT NULL,
                UNIQUE(user_id, contact_id)
            )
        """)


        # -------------------------------------------------
        # MESSAGES
        # -------------------------------------------------

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


        # -------------------------------------------------
        # SAFE MIGRATION
        # -------------------------------------------------

        cur.execute("""
            ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS is_read INTEGER DEFAULT 0
        """)


        # -------------------------------------------------
        # INDEXES
        # -------------------------------------------------

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_messages_sender_receiver
            ON messages(sender_id, receiver_id)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_messages_receiver_read
            ON messages(receiver_id, is_read)
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_messages_created
            ON messages(created_at)
        """)


        conn.commit()

        print(
            "PostgreSQL database initialized successfully."
        )

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "DATABASE INITIALIZATION ERROR:",
            repr(e)
        )

        raise

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# HELPERS
# =========================================================

def allowed_file(
    filename
):

    if not filename:
        return False

    if "." not in filename:
        return False

    extension = filename.rsplit(
        ".",
        1
    )[1].lower()

    return extension in ALLOWED_EXTENSIONS


def user_exists(
    user_id
):

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor()

        cur.execute(
            """
            SELECT id
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )

        return (
            cur.fetchone()
            is not None
        )

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


def get_message(
    message_id
):

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
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
            """,
            (message_id,)
        )

        row = cur.fetchone()

        if row:

            row = dict(row)

            if row.get(
                "created_at"
            ):

                row["created_at"] = str(
                    row["created_at"]
                )

        return row

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


def save_message(
    sender_id,
    receiver_id,
    message="",
    message_type="text",
    file_name=None,
    file_url=None
):

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
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
            VALUES
            (%s, %s, %s, %s, %s, %s, 0)
            RETURNING id
            """,
            (
                sender_id,
                receiver_id,
                message,
                message_type,
                file_name,
                file_url
            )
        )

        message_id = (
            cur.fetchone()["id"]
        )

        conn.commit()

        return get_message(
            message_id
        )

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
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    return jsonify({
        "success": True,
        "status": "ok",
        "online_users": len(
            online_users
        )
    })


# =========================================================
# FRONTEND
# =========================================================

@app.route("/")
def home():

    return send_from_directory(
        BASE_DIR,
        "index.html"
    )


@app.route("/style.css")
def css():

    return send_from_directory(
        BASE_DIR,
        "style.css"
    )


@app.route(
    "/uploads/<path:filename>"
)
def uploaded_file(
    filename
):

    return send_from_directory(
        UPLOAD_FOLDER,
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

    data = request.get_json(
        silent=True
    ) or {}

    name = str(
        data.get(
            "name",
            ""
        )
    ).strip()

    email = str(
        data.get(
            "email",
            ""
        )
    ).strip().lower()

    password = str(
        data.get(
            "password",
            ""
        )
    )

    if not name or not email or not password:

        return jsonify({
            "success": False,
            "message":
                "All fields are required."
        }), 400

    if len(password) < 6:

        return jsonify({
            "success": False,
            "message":
                "Password must be at least 6 characters."
        }), 400

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
            SELECT id
            FROM users
            WHERE email = %s
            """,
            (email,)
        )

        existing = cur.fetchone()

        if existing:

            return jsonify({
                "success": False,
                "message":
                    "This email is already registered."
            }), 409

        hashed_password = (
            generate_password_hash(
                password
            )
        )

        cur.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password
            )
            VALUES
            (%s, %s, %s)
            RETURNING id
            """,
            (
                name,
                email,
                hashed_password
            )
        )

        user_id = (
            cur.fetchone()["id"]
        )

        conn.commit()

        return jsonify({
            "success": True,
            "message":
                "Account created successfully.",
            "user": {
                "id": user_id,
                "name": name,
                "email": email
            }
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "SIGNUP ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message":
                "Could not create account."
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/api/login",
    methods=["POST"]
)
def login():

    data = request.get_json(
        silent=True
    ) or {}

    email = str(
        data.get(
            "email",
            ""
        )
    ).strip().lower()

    password = str(
        data.get(
            "password",
            ""
        )
    )

    if not email or not password:

        return jsonify({
            "success": False,
            "message":
                "Email and password are required."
        }), 400

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
            SELECT
                id,
                name,
                email,
                password
            FROM users
            WHERE email = %s
            """,
            (email,)
        )

        user = cur.fetchone()

    except Exception as e:

        print(
            "LOGIN DATABASE ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message":
                "Database error."
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()

    if not user:

        return jsonify({
            "success": False,
            "message":
                "Email or password is incorrect."
        }), 401

    if not check_password_hash(
        user["password"],
        password
    ):

        return jsonify({
            "success": False,
            "message":
                "Email or password is incorrect."
        }), 401

    session.clear()

    session["user_id"] = (
        user["id"]
    )

    session.modified = True

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

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
            SELECT
                id,
                name,
                email
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )

        user = cur.fetchone()

    finally:

        if cur:
            cur.close()

        if conn:
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

    user_id = session.get(
        "user_id"
    )

    if user_id:

        socketio.emit(
            "user_status",
            {
                "user_id":
                    int(user_id),
                "online": False
            }
        )

    session.clear()

    response = jsonify({
        "success": True
    })

    response.delete_cookie(
        app.config.get(
            "SESSION_COOKIE_NAME",
            "session"
        )
    )

    return response


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
            "message":
                "Please login first."
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    email = str(
        data.get(
            "email",
            ""
        )
    ).strip().lower()

    if not email:

        return jsonify({
            "success": False,
            "message":
                "Enter an email address."
        }), 400

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
            SELECT
                id,
                name,
                email
            FROM users
            WHERE email = %s
            """,
            (email,)
        )

        contact = cur.fetchone()

        if not contact:

            return jsonify({
                "success": False,
                "message":
                    "No account found with this email."
            }), 404

        if contact["id"] == user_id:

            return jsonify({
                "success": False,
                "message":
                    "You cannot add yourself."
            }), 400

        cur.execute(
            """
            SELECT id
            FROM contacts
            WHERE user_id = %s
            AND contact_id = %s
            """,
            (
                user_id,
                contact["id"]
            )
        )

        already = cur.fetchone()

        if already:

            return jsonify({
                "success": False,
                "message":
                    "This contact is already added."
            }), 409

        cur.execute(
            """
            INSERT INTO contacts
            (
                user_id,
                contact_id
            )
            VALUES
            (%s, %s)
            """,
            (
                user_id,
                contact["id"]
            )
        )

        conn.commit()

        return jsonify({
            "success": True,
            "contact": {
                "id": contact["id"],
                "name": contact["name"],
                "email": contact["email"],
                "online":
                    is_user_online(
                        contact["id"]
                    )
            }
        })

    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "ADD CONTACT ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message":
                "Could not add contact."
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# CONTACTS + CHAT LIST
# =========================================================

@app.route("/api/contacts")
def get_contacts():

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return jsonify({
            "success": False,
            "contacts": []
        }), 401

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
            SELECT
                u.id,
                u.name,
                u.email
            FROM users u
            WHERE
                (
                    u.id IN
                    (
                        SELECT contact_id
                        FROM contacts
                        WHERE user_id = %s
                    )

                    OR

                    u.id IN
                    (
                        SELECT sender_id
                        FROM messages
                        WHERE receiver_id = %s

                        UNION

                        SELECT receiver_id
                        FROM messages
                        WHERE sender_id = %s
                    )
                )

                AND u.id != %s

            ORDER BY LOWER(u.name) ASC
            """,
            (
                user_id,
                user_id,
                user_id,
                user_id
            )
        )

        contacts = cur.fetchall()

        result = []

        for contact in contacts:

            contact_id = (
                contact["id"]
            )


            # -------------------------------------------------
            # UNREAD
            # -------------------------------------------------

            cur.execute(
                """
                SELECT COUNT(*) AS count
                FROM messages
                WHERE sender_id = %s
                AND receiver_id = %s
                AND is_read = 0
                """,
                (
                    contact_id,
                    user_id
                )
            )

            unread_row = (
                cur.fetchone()
            )

            unread = int(
                unread_row["count"]
                if unread_row
                else 0
            )


            # -------------------------------------------------
            # LAST MESSAGE
            # -------------------------------------------------

            cur.execute(
                """
                SELECT
                    message,
                    message_type,
                    file_name,
                    created_at
                FROM messages
                WHERE
                    (
                        sender_id = %s
                        AND receiver_id = %s
                    )

                    OR

                    (
                        sender_id = %s
                        AND receiver_id = %s
                    )

                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    user_id,
                    contact_id,
                    contact_id,
                    user_id
                )
            )

            last_message = (
                cur.fetchone()
            )

            preview = ""

            if last_message:

                message_type = (
                    last_message[
                        "message_type"
                    ]
                )

                if message_type == "image":

                    preview = "📷 Photo"

                elif message_type == "video":

                    preview = "🎥 Video"

                elif message_type == "file":

                    preview = (
                        "📎 "
                        +
                        (
                            last_message[
                                "file_name"
                            ]
                            or
                            "File"
                        )
                    )

                else:

                    preview = (
                        last_message[
                            "message"
                        ]
                        or ""
                    )


            result.append({
                "id":
                    contact["id"],

                "name":
                    contact["name"],

                "email":
                    contact["email"],

                "unread":
                    unread,

                "unread_count":
                    unread,

                "last_message":
                    preview,

                "online":
                    is_user_online(
                        contact_id
                    )
            })


        return jsonify({
            "success": True,
            "contacts": result
        })


    except Exception as e:

        print(
            "CONTACTS ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "contacts": [],
            "message":
                "Could not load contacts."
        }), 500


    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# GET USER BY ID
# =========================================================

@app.route(
    "/api/user/<int:user_id>"
)
def get_user_by_id(
    user_id
):

    current_id = session.get(
        "user_id"
    )

    if not current_id:

        return jsonify({
            "success": False,
            "message":
                "Please login first."
        }), 401

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )

        cur.execute(
            """
            SELECT
                id,
                name,
                email
            FROM users
            WHERE id = %s
            """,
            (user_id,)
        )

        user = cur.fetchone()

        if not user:

            return jsonify({
                "success": False,
                "message":
                    "User not found."
            }), 404

        return jsonify({
            "success": True,
            "user": {
                "id":
                    user["id"],

                "name":
                    user["name"],

                "email":
                    user["email"],

                "online":
                    is_user_online(
                        user["id"]
                    )
            }
        })

    except Exception as e:

        print(
            "GET USER ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message":
                "Could not get user."
        }), 500

    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# USER STATUS API
# =========================================================

@app.route(
    "/api/user/<int:user_id>/status"
)
def user_status(
    user_id
):

    if not session.get(
        "user_id"
    ):

        return jsonify({
            "success": False,
            "message":
                "Please login first."
        }), 401

    if not user_exists(
        user_id
    ):

        return jsonify({
            "success": False,
            "message":
                "User not found."
        }), 404

    return jsonify({
        "success": True,
        "user_id":
            user_id,
        "online":
            is_user_online(
                user_id
            )
    })


@app.route(
    "/api/online-users"
)
def online_users_api():

    if not session.get(
        "user_id"
    ):

        return jsonify({
            "success": False,
            "users": []
        }), 401

    return jsonify({
        "success": True,
        "users":
            get_online_user_ids()
    })


# =========================================================
# GET MESSAGES
# =========================================================

@app.route(
    "/api/messages/<int:contact_id>"
)
def get_messages(
    contact_id
):

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return jsonify({
            "success": False,
            "messages": []
        }), 401

    if not user_exists(
        contact_id
    ):

        return jsonify({
            "success": False,
            "messages": []
        }), 404

    conn = None
    cur = None

    try:

        conn = get_db()

        cur = conn.cursor(
            cursor_factory=
            psycopg2.extras.RealDictCursor
        )


        # -------------------------------------------------
        # MARK RECEIVED MESSAGES AS READ
        # -------------------------------------------------

        cur.execute(
            """
            UPDATE messages
            SET is_read = 1
            WHERE sender_id = %s
            AND receiver_id = %s
            AND is_read = 0
            """,
            (
                contact_id,
                user_id
            )
        )


        # -------------------------------------------------
        # GET CHAT
        # -------------------------------------------------

        cur.execute(
            """
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
                (
                    sender_id = %s
                    AND receiver_id = %s
                )

                OR

                (
                    sender_id = %s
                    AND receiver_id = %s
                )

            ORDER BY id ASC
            """,
            (
                user_id,
                contact_id,
                contact_id,
                user_id
            )
        )

        messages = cur.fetchall()

        conn.commit()

        result = []

        for msg in messages:

            result.append({
                "id":
                    msg["id"],

                "sender_id":
                    msg["sender_id"],

                "receiver_id":
                    msg["receiver_id"],

                "message":
                    msg["message"],

                "message_type":
                    msg["message_type"],

                "file_name":
                    msg["file_name"],

                "file_url":
                    msg["file_url"],

                "created_at":
                    str(
                        msg["created_at"]
                    ),

                "is_read":
                    msg["is_read"]
            })


        return jsonify({
            "success": True,
            "messages": result
        })


    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "GET MESSAGES ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "messages": []
        }), 500


    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# SEND TEXT MESSAGE
# =========================================================

@socketio.on(
    "send_message"
)
def socket_send_message(
    data
):

    print(
        "========== SEND MESSAGE =========="
    )

    if not isinstance(
        data,
        dict
    ):

        emit(
            "message_error",
            {
                "message":
                    "Invalid message data."
            }
        )

        return


    sender_id = session.get(
        "user_id"
    )

    if not sender_id:

        emit(
            "message_error",
            {
                "message":
                    "You are not logged in."
            }
        )

        return


    try:

        receiver_id = int(
            data.get(
                "receiver_id"
            )
        )

    except Exception:

        emit(
            "message_error",
            {
                "message":
                    "Invalid receiver."
            }
        )

        return


    message = str(
        data.get(
            "message",
            ""
        )
    ).strip()


    if not receiver_id:

        emit(
            "message_error",
            {
                "message":
                    "Receiver is required."
            }
        )

        return


    if not message:
        return


    if receiver_id == int(
        sender_id
    ):

        emit(
            "message_error",
            {
                "message":
                    "You cannot message yourself."
            }
        )

        return


    try:

        if not user_exists(
            receiver_id
        ):

            emit(
                "message_error",
                {
                    "message":
                        "Receiver account was not found."
                }
            )

            return


        saved = save_message(
            sender_id,
            receiver_id,
            message,
            "text"
        )


        if not saved:

            emit(
                "message_error",
                {
                    "message":
                        "Message could not be saved."
                }
            )

            return


        # -------------------------------------------------
        # RECEIVER
        # -------------------------------------------------

        socketio.emit(
            "new_message",
            saved,
            room=
                "user_"
                +
                str(
                    receiver_id
                )
        )


        # Delivery is confirmed by the receiver client after it
        # actually receives the message over Socket.IO.

        # -------------------------------------------------
        # SENDER CONFIRMATION
        # -------------------------------------------------

        emit(
            "message_sent",
            saved
        )


        print(
            "Message saved and emitted:",
            saved["id"]
        )


    except Exception as e:

        print(
            "SEND MESSAGE ERROR:",
            repr(e)
        )

        emit(
            "message_error",
            {
                "message":
                    "Message could not be sent."
            }
        )


# =========================================================
# TYPING INDICATOR
# =========================================================

@socketio.on(
    "typing"
)
def socket_typing(
    data
):

    sender_id = session.get(
        "user_id"
    )

    if not sender_id:
        return

    if not isinstance(
        data,
        dict
    ):
        return


    try:

        receiver_id = int(
            data.get(
                "receiver_id"
            )
        )

    except Exception:

        return


    is_typing = bool(
        data.get(
            "typing",
            False
        )
    )


    if not receiver_id:
        return


    if receiver_id == int(
        sender_id
    ):
        return


    socketio.emit(
        "user_typing",
        {
            "user_id":
                int(
                    sender_id
                ),

            "typing":
                is_typing
        },
        room=
            "user_"
            +
            str(
                receiver_id
            )
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
            "message":
                "Please login first."
        }), 401


    receiver_id = request.form.get(
        "receiver_id"
    )


    if not receiver_id:

        return jsonify({
            "success": False,
            "message":
                "Receiver not selected."
        }), 400


    try:

        receiver_id = int(
            receiver_id
        )

    except Exception:

        return jsonify({
            "success": False,
            "message":
                "Invalid receiver."
        }), 400


    if receiver_id == int(
        sender_id
    ):

        return jsonify({
            "success": False,
            "message":
                "You cannot send files to yourself."
        }), 400


    if not user_exists(
        receiver_id
    ):

        return jsonify({
            "success": False,
            "message":
                "Receiver account was not found."
        }), 404


    if "file" not in request.files:

        return jsonify({
            "success": False,
            "message":
                "No file selected."
        }), 400


    file = request.files[
        "file"
    ]


    if not file.filename:

        return jsonify({
            "success": False,
            "message":
                "No file selected."
        }), 400


    if not allowed_file(
        file.filename
    ):

        return jsonify({
            "success": False,
            "message":
                "This file type is not allowed."
        }), 400


    original_name = secure_filename(
        file.filename
    )


    if not original_name:

        return jsonify({
            "success": False,
            "message":
                "Invalid filename."
        }), 400


    extension = ""


    if "." in original_name:

        extension = (
            "."
            +
            original_name.rsplit(
                ".",
                1
            )[1].lower()
        )


    unique_name = (
        str(
            sender_id
        )
        +
        "_"
        +
        uuid.uuid4().hex
        +
        extension
    )


    save_path = os.path.join(
        UPLOAD_FOLDER,
        unique_name
    )


    try:

        file.save(
            save_path
        )

    except Exception as e:

        print(
            "FILE SAVE ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message":
                "Could not save file."
        }), 500


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
        +
        unique_name
    )


    try:

        saved = save_message(
            sender_id,
            receiver_id,
            "",
            message_type,
            original_name,
            file_url
        )

    except Exception as e:

        try:

            if os.path.exists(
                save_path
            ):

                os.remove(
                    save_path
                )

        except Exception:
            pass


        print(
            "FILE MESSAGE DATABASE ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message":
                "Could not save file message."
        }), 500


    # -----------------------------------------------------
    # RECEIVER
    # -----------------------------------------------------

    socketio.emit(
        "new_message",
        saved,
        room=
            "user_"
            +
            str(
                receiver_id
            )
    )


    # Delivery is confirmed by the receiver client after it
    # actually receives the message over Socket.IO.

    # -----------------------------------------------------
    # SENDER
    # -----------------------------------------------------

    socketio.emit(
        "message_sent",
        saved,
        room=
            "user_"
            +
            str(
                sender_id
            )
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
def mark_read(
    contact_id
):

    user_id = session.get(
        "user_id"
    )

    if not user_id:

        return jsonify({
            "success": False
        }), 401


    conn = None
    cur = None


    try:

        conn = get_db()

        cur = conn.cursor()


        cur.execute(
            """
            UPDATE messages
            SET is_read = 1
            WHERE sender_id = %s
            AND receiver_id = %s
            AND is_read = 0
            """,
            (
                contact_id,
                user_id
            )
        )


        conn.commit()


        # -------------------------------------------------
        # TELL SENDER
        # -------------------------------------------------

        socketio.emit(
            "messages_read",
            {
                "user_id":
                    int(
                        user_id
                    ),

                "contact_id":
                    int(
                        contact_id
                    )
            },
            room=
                "user_"
                +
                str(
                    contact_id
                )
        )


        return jsonify({
            "success": True
        })


    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "MARK READ ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False
        }), 500


    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# SOCKET DELIVERY ACK
# =========================================================

@socketio.on(
    "message_delivered_ack"
)
def socket_message_delivered_ack(data):

    receiver_id = session.get("user_id")

    if not receiver_id or not isinstance(data, dict):
        return

    try:
        message_id = int(data.get("message_id"))
        sender_id = int(data.get("sender_id"))
    except (TypeError, ValueError):
        return

    if not message_id or not sender_id or sender_id == int(receiver_id):
        return

    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT id, sender_id, receiver_id
            FROM messages
            WHERE id = %s
            AND sender_id = %s
            AND receiver_id = %s
            """,
            (message_id, sender_id, int(receiver_id))
        )

        message = cur.fetchone()

        if not message:
            return

        socketio.emit(
            "message_delivered",
            {
                "message_id": message_id,
                "sender_id": sender_id,
                "receiver_id": int(receiver_id)
            },
            room="user_" + str(sender_id)
        )

    except Exception as e:
        print("DELIVERY ACK ERROR:", repr(e))

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# =========================================================
# SOCKET MARK READ
# =========================================================

@socketio.on(
    "mark_read"
)
def socket_mark_read(
    data
):

    user_id = session.get(
        "user_id"
    )

    if not user_id:
        return


    if not isinstance(
        data,
        dict
    ):
        return


    try:

        contact_id = int(
            data.get(
                "contact_id"
            )
        )

    except Exception:

        return


    if not contact_id:
        return


    conn = None
    cur = None


    try:

        conn = get_db()

        cur = conn.cursor()


        cur.execute(
            """
            UPDATE messages
            SET is_read = 1
            WHERE sender_id = %s
            AND receiver_id = %s
            AND is_read = 0
            """,
            (
                contact_id,
                user_id
            )
        )


        conn.commit()


        socketio.emit(
            "messages_read",
            {
                "user_id":
                    int(
                        user_id
                    ),

                "contact_id":
                    int(
                        contact_id
                    )
            },
            room=
                "user_"
                +
                str(
                    contact_id
                )
        )


    except Exception as e:

        if conn:
            conn.rollback()

        print(
            "SOCKET MARK READ ERROR:",
            repr(e)
        )


    finally:

        if cur:
            cur.close()

        if conn:
            conn.close()


# =========================================================
# SOCKET CONNECT
# =========================================================

@socketio.on(
    "connect"
)
def socket_connect():

    user_id = session.get(
        "user_id"
    )


    print(
        "========== SOCKET CONNECT =========="
    )


    print(
        "Session user:",
        user_id
    )


    if not user_id:

        print(
            "Socket rejected: not logged in"
        )

        return False


    room_name = (
        "user_"
        +
        str(
            user_id
        )
    )


    join_room(
        room_name
    )


    became_online = (
        add_online_user(
            user_id,
            request.sid
        )
    )


    print(
        "User connected:",
        user_id
    )


    print(
        "Joined room:",
        room_name
    )


    # -------------------------------------------------
    # SEND CURRENT ONLINE USERS TO THIS CLIENT
    # -------------------------------------------------

    emit(
        "online_users",
        {
            "users":
                get_online_user_ids()
        }
    )


    # -------------------------------------------------
    # BROADCAST NEW ONLINE STATUS
    # -------------------------------------------------

    if became_online:

        broadcast_presence(
            user_id,
            True
        )


# =========================================================
# SOCKET DISCONNECT
# =========================================================

@socketio.on(
    "disconnect"
)
def socket_disconnect(
    reason=None
):

    user_id = session.get(
        "user_id"
    )


    print(
        "User disconnected:",
        user_id,
        "Reason:",
        reason
    )


    if user_id:

        became_offline = (
            remove_online_user(
                user_id,
                request.sid
            )
        )


        if became_offline:

            broadcast_presence(
                user_id,
                False
            )


# =========================================================
# SOCKET ERROR
# =========================================================

@socketio.on_error_default
def socket_error_handler(
    e
):

    print(
        "SOCKET ERROR:",
        repr(e)
    )


    try:

        emit(
            "message_error",
            {
                "message":
                    "Socket error occurred."
            }
        )

    except Exception:
        pass


# =========================================================
# APPLICATION STARTUP
# =========================================================

if not DATABASE_URL:

    raise RuntimeError(
        "DATABASE_URL environment variable is missing. "
        "Add your Render PostgreSQL DATABASE_URL "
        "to the web service."
    )


init_db()


# =========================================================
# LOCAL DEVELOPMENT
# =========================================================

if __name__ == "__main__":

    print(
        "=" * 50
    )


    print(
        "                  MyChat"
    )


    print(
        "=" * 50
    )


    print()


    print(
        "Real-time chat enabled!"
    )


    print(
        "Online/offline status enabled!"
    )


    print(
        "Typing indicator enabled!"
    )


    print(
        "Delivered/seen status enabled!"
    )


    print(
        "File uploads enabled!"
    )


    print(
        "Maximum file size: 100 MB"
    )


    print()


    print(
        "Press CTRL+C to stop."
    )


    print(
        "=" * 50
    )


    socketio.run(
        app,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                8000
            )
        ),
        debug=False,
        allow_unsafe_werkzeug=True
    )

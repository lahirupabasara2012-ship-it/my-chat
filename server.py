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
    "dev-secret-key"
)


# Render uses HTTPS, so make the Flask session cookie work correctly there.
# SECRET_KEY should be set as a Render environment variable.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    manage_session=True
)


# =========================================================
# DATABASE
# =========================================================

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL environment variable is missing"
        )

    return psycopg2.connect(
        DATABASE_URL
    )


# =========================================================
# FILE UPLOAD SETTINGS
# =========================================================

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
# DATABASE INITIALIZE
# =========================================================

def init_db():

    conn = get_db()

    cur = conn.cursor()

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)


    # -----------------------------------------------------
    # CONTACTS
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            UNIQUE(user_id, contact_id)
        )
    """)


    # -----------------------------------------------------
    # MESSAGES
    # -----------------------------------------------------

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

    print(
        "PostgreSQL database initialized successfully."
    )


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
# GET MESSAGE
# =========================================================

def get_message(message_id):

    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )

    try:

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

        return row_to_dict(row)

    finally:

        cur.close()
        conn.close()


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

    try:

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

    except Exception:

        conn.rollback()

        raise

    finally:

        cur.close()
        conn.close()


    return get_message(
        message_id
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():
    return jsonify({
        "success": True,
        "status": "ok"
    })


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
# UPLOAD FILES
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


    try:

        cur.execute("""
            SELECT id
            FROM users
            WHERE email = %s
        """, (
            email,
        ))

        existing = cur.fetchone()


        if existing:

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


        return jsonify({
            "success": True,
            "message": "Account created successfully.",
            "user": {
                "id": user_id,
                "name": name,
                "email": email
            }
        })


    except Exception as e:

        conn.rollback()

        print(
            "SIGNUP ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message": "Could not create account."
        }), 500


    finally:

        cur.close()
        conn.close()


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


    try:

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


    finally:

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


    try:

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


    finally:

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

    response = jsonify({
        "success": True
    })

    # Explicitly expire the Flask session cookie.
    response.set_cookie(
        app.config.get("SESSION_COOKIE_NAME", "session"),
        "",
        expires=0,
        max_age=0,
        httponly=True,
        samesite="Lax",
        secure=bool(os.environ.get("RENDER"))
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


    try:

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

            return jsonify({
                "success": False,
                "message": "No account found with this email."
            })


        if contact["id"] == user_id:

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


        return jsonify({
            "success": True,
            "contact": {
                "id": contact["id"],
                "name": contact["name"],
                "email": contact["email"]
            }
        })


    except Exception as e:

        conn.rollback()

        print(
            "ADD CONTACT ERROR:",
            repr(e)
        )

        return jsonify({
            "success": False,
            "message": "Could not add contact."
        }), 500


    finally:

        cur.close()
        conn.close()


# =========================================================
# CONTACTS + CHAT LIST
#
# IMPORTANT:
#
# This does NOT only return contacts.
#
# It also returns anyone who has exchanged messages
# with the current user.
#
# Therefore:
#
# User A sends message to User B
# User B does NOT need to add User A
# User A still appears in User B's chat list.
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
        })


    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )


    try:

        # -----------------------------------------------------
        # CONTACTS + MESSAGE PARTICIPANTS
        # -----------------------------------------------------

        cur.execute("""
            SELECT DISTINCT
                u.id,
                u.name,
                u.email

            FROM users u

            WHERE

                (

                    u.id IN (

                        SELECT contact_id

                        FROM contacts

                        WHERE user_id = %s

                    )

                    OR

                    u.id IN (

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
        """, (
            user_id,
            user_id,
            user_id,
            user_id
        ))


        contacts = cur.fetchall()


        result = []


        for contact in contacts:

            contact_id = contact["id"]


            # -------------------------------------------------
            # UNREAD COUNT
            # -------------------------------------------------

            cur.execute("""
                SELECT COUNT(*) AS count

                FROM messages

                WHERE
                    sender_id = %s

                    AND

                    receiver_id = %s

                    AND

                    is_read = 0
            """, (
                contact_id,
                user_id
            ))


            unread_row = cur.fetchone()


            unread = int(
                unread_row["count"]
                if unread_row
                else 0
            )


            # -------------------------------------------------
            # LAST MESSAGE
            # -------------------------------------------------

            cur.execute("""
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
            """, (
                user_id,
                contact_id,
                contact_id,
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

                    preview = (
                        "📎 "
                        +
                        (
                            last_message["file_name"]
                            or "File"
                        )
                    )


                else:

                    preview = (
                        last_message["message"]
                        or ""
                    )


            # -------------------------------------------------
            # RESULT
            # -------------------------------------------------

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
                    preview

            })


        return jsonify({

            "success":
                True,

            "contacts":
                result

        })


    except Exception as e:

        print(
            "CONTACTS ERROR:",
            repr(e)
        )


        return jsonify({

            "success":
                False,

            "contacts":
                [],

            "message":
                "Could not load contacts."

        }), 500


    finally:

        cur.close()
        conn.close()


# =========================================================
# GET USER BY ID
#
# Used when receiving a message from someone who may not
# be in the contacts table.
# =========================================================

@app.route(
    "/api/user/<int:user_id>"
)
def get_user_by_id(user_id):

    current_id = session.get(
        "user_id"
    )


    if not current_id:

        return jsonify({
            "success": False,
            "message": "Please login first."
        }), 401


    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )


    try:

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


        if not user:

            return jsonify({
                "success": False,
                "message": "User not found."
            }), 404


        return jsonify({

            "success":
                True,

            "user": {

                "id":
                    user["id"],

                "name":
                    user["name"],

                "email":
                    user["email"]

            }

        })


    except Exception as e:

        print(
            "GET USER ERROR:",
            repr(e)
        )


        return jsonify({

            "success":
                False,

            "message":
                "Could not get user."

        }), 500


    finally:

        cur.close()
        conn.close()


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
            "success": False,
            "messages": []
        })


    conn = get_db()

    cur = conn.cursor(
        cursor_factory=psycopg2.extras.RealDictCursor
    )


    try:

        # -----------------------------------------------------
        # MARK RECEIVED MESSAGES AS READ
        # -----------------------------------------------------

        cur.execute("""
            UPDATE messages

            SET is_read = 1

            WHERE
                sender_id = %s

                AND

                receiver_id = %s

                AND

                is_read = 0
        """, (
            contact_id,
            user_id
        ))


        # -----------------------------------------------------
        # GET FULL CHAT
        # -----------------------------------------------------

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
        """, (
            user_id,
            contact_id,
            contact_id,
            user_id
        ))


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
                    str(msg["created_at"]),

                "is_read":
                    msg["is_read"]

            })


        return jsonify({

            "success":
                True,

            "messages":
                result

        })


    except Exception as e:

        conn.rollback()

        print(
            "GET MESSAGES ERROR:",
            repr(e)
        )


        return jsonify({

            "success":
                False,

            "messages":
                []

        }), 500


    finally:

        cur.close()
        conn.close()


# =========================================================
# SEND TEXT MESSAGE
# =========================================================

@socketio.on("send_message")
def socket_send_message(data):

    print(
        "========== SEND MESSAGE =========="
    )


    sender_id = session.get(
        "user_id"
    )


    print(
        "Session user:",
        sender_id
    )


    if not sender_id:

        print(
            "ERROR: User is not logged in"
        )

        return


    try:

        receiver_id = int(
            data.get(
                "receiver_id"
            )
        )


    except Exception as e:

        print(
            "ERROR: Invalid receiver:",
            e
        )

        return


    message = str(
        data.get(
            "message",
            ""
        )
    ).strip()


    if not receiver_id or not message:

        return


    # -----------------------------------------------------
    # PREVENT SENDING TO YOURSELF
    # -----------------------------------------------------

    if receiver_id == int(sender_id):

        print(
            "ERROR: Cannot message yourself"
        )

        return


    try:

        # -------------------------------------------------
        # SAVE MESSAGE
        # -------------------------------------------------

        saved = save_message(

            sender_id,

            receiver_id,

            message,

            "text"

        )


        # -------------------------------------------------
        # SEND TO RECEIVER
        #
        # This works even if receiver has NOT added
        # sender as a contact.
        # -------------------------------------------------

        socketio.emit(

            "new_message",

            saved,

            room="user_" + str(receiver_id)

        )


        # -------------------------------------------------
        # SEND CONFIRMATION TO SENDER
        # -------------------------------------------------

        emit(

            "message_sent",

            saved

        )


        print(
            "Message sent successfully!"
        )


    except Exception as e:

        print(
            "SEND ERROR:",
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

            "success":
                False,

            "message":
                "Please login first."

        })


    receiver_id = request.form.get(
        "receiver_id"
    )


    if not receiver_id:

        return jsonify({

            "success":
                False,

            "message":
                "Receiver not selected."

        })


    try:

        receiver_id = int(
            receiver_id
        )

    except Exception:

        return jsonify({

            "success":
                False,

            "message":
                "Invalid receiver."

        })


    if receiver_id == int(sender_id):

        return jsonify({

            "success":
                False,

            "message":
                "You cannot send files to yourself."

        })


    if "file" not in request.files:

        return jsonify({

            "success":
                False,

            "message":
                "No file selected."

        })


    file = request.files["file"]


    if not file.filename:

        return jsonify({

            "success":
                False,

            "message":
                "No file selected."

        })


    if not allowed_file(
        file.filename
    ):

        return jsonify({

            "success":
                False,

            "message":
                "This file type is not allowed."

        })


    original_name = secure_filename(
        file.filename
    )


    extension = ""


    if "." in original_name:

        extension = (

            "."

            +

            original_name
            .rsplit(
                ".",
                1
            )[1]
            .lower()

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


    # -----------------------------------------------------
    # DETERMINE FILE TYPE
    # -----------------------------------------------------

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


    # -----------------------------------------------------
    # SAVE FILE MESSAGE
    # -----------------------------------------------------

    saved = save_message(

        sender_id,

        receiver_id,

        "",

        message_type,

        original_name,

        file_url

    )


    # -----------------------------------------------------
    # RECEIVER
    # -----------------------------------------------------

    socketio.emit(

        "new_message",

        saved,

        room="user_" + str(receiver_id)

    )


    # -----------------------------------------------------
    # SENDER
    # -----------------------------------------------------

    socketio.emit(

        "message_sent",

        saved,

        room="user_" + str(sender_id)

    )


    return jsonify({

        "success":
            True,

        "message":
            saved

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


    try:

        cur.execute("""
            UPDATE messages

            SET is_read = 1

            WHERE
                sender_id = %s

                AND

                receiver_id = %s

                AND

                is_read = 0
        """, (
            contact_id,
            user_id
        ))


        conn.commit()


        # -------------------------------------------------
        # Notify sender that messages were read
        # -------------------------------------------------

        socketio.emit(

            "messages_read",

            {
                "user_id":
                    user_id,

                "contact_id":
                    contact_id

            },

            room="user_" + str(contact_id)

        )


        return jsonify({
            "success": True
        })


    except Exception as e:

        conn.rollback()

        print(
            "MARK READ ERROR:",
            repr(e)
        )


        return jsonify({
            "success": False
        }), 500


    finally:

        cur.close()
        conn.close()


# =========================================================
# SOCKET CONNECT
# =========================================================

@socketio.on("connect")
def socket_connect():

    user_id = session.get(
        "user_id"
    )


    if user_id:

        room_name = (
            "user_"
            +
            str(user_id)
        )


        join_room(
            room_name
        )


        print(
            "User connected:",
            user_id
        )


        print(
            "Joined room:",
            room_name
        )


    else:

        print(
            "Socket connected without login"
        )

        return False


# =========================================================
# SOCKET DISCONNECT
# =========================================================

@socketio.on("disconnect")
def socket_disconnect():

    user_id = session.get(
        "user_id"
    )


    print(
        "User disconnected:",
        user_id
    )


# =========================================================
# INITIALIZE DATABASE
# =========================================================

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is missing. "
        "Add your Render PostgreSQL DATABASE_URL to the web service."
    )

init_db()


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    print("=" * 50)

    print(
        "                  MyChat"
    )

    print("=" * 50)

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

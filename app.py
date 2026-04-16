#------------------------------start-------------------

from groq import Groq
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import sqlite3
import re
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import os
import PyPDF2
import pytesseract
from PIL import Image
import webbrowser
import uuid
import subprocess
from pdf2image import convert_from_path
from deep_translator import GoogleTranslator

# ---------------- AI ---------------- #
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Chat storage
all_chats = {}
chat_titles = {}
current_chat_id = None

# File memory
file_memories = {}
user_memory = {}
current_file = None
file_order = []

# ---------------- FLASK ---------------- #
app = Flask(__name__)
app.secret_key = "aura_super_secret_123"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# OCR path
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Allowed file types
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

def allowed_file(filename):
    """Check valid file type"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS




def translate_text(text, dest):
    """Translate text"""
    try:
        return GoogleTranslator(source='auto', target=dest).translate(text)
    except:
        return text


# ---------------- READERS ---------------- #
def read_pdf(path):
    """Read normal PDF"""
    text = ""
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text


def read_image(path):
    """OCR image"""
    img = Image.open(path).convert("L")
    img = img.point(lambda x: 0 if x < 140 else 255)

    return pytesseract.image_to_string(img, lang='eng', config='--oem 3 --psm 6')


def read_scanned_pdf(path):
    """OCR scanned PDF"""
    images = convert_from_path(path)
    text = ""

    for img in images:
        img = img.convert("L")
        text += pytesseract.image_to_string(img, lang='eng', config='--oem 3 --psm 6')

    return text


# ---------------- IMAGE DESCRIPTION ---------------- #
import base64

def describe_image(path):
    """AI image description"""
    try:
        with open(path, "rb") as img_file:
            base64_image = base64.b64encode(img_file.read()).decode("utf-8")

        response = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image clearly in 5 points."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }]
        )

        return response.choices[0].message.content

    except Exception as e:
        print("VISION ERROR:", e)
        return "Unable to analyze image."


# ---------------- CLEAN + FORMAT ---------------- #
def clean_text(text):
    return text.replace("**", "")


def format_points(text):
    """Format bullet points"""
    text = text.replace("**", "")
    text = re.sub(r'Here are.*?:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+\.)\s*', r'\n\1 ', text)
    text = re.sub(r'[-•]\s*', r'\n- ', text)
    text = re.sub(r'\n+', '\n', text)
    return text.strip()


# ---------------- DB ---------------- #
def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        email TEXT UNIQUE,
        password TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        title TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        role TEXT,
        content TEXT
    )
    """)

    # 🔥 NEW MEMORY TABLE (VERY IMPORTANT)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS memory (
        user_id INTEGER,
        key TEXT,
        value TEXT,
        PRIMARY KEY (user_id, key)
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------------- TITLE ---------------- #
def generate_title(chat_messages):
    try:
        first_msg = ""

        for msg in chat_messages:
            if msg["role"] == "user":
                first_msg = msg["content"]
                break

        if not first_msg:
            return "New Chat"

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Generate a very short chat title (max 5 words)."},
                {"role": "user", "content": first_msg}
            ]
        )

        title = response.choices[0].message.content.strip()

        return title[:30]

    except:
        return first_msg[:20] if first_msg else "New Chat"
# ---------------- AI ENGINE ---------------- #
def process_message(msg, user_id=None):
    global all_chats, current_chat_id, chat_titles

    original_msg = msg.strip()

    # ---------------- SAFETY ---------------- #
    if not current_chat_id or current_chat_id not in all_chats:
        create_new_chat(user_id)

    msg_lower = msg.lower().strip()

    import random

    # -------- JARVIS GREETING --------
    if msg_lower in ["hi", "hello", "hey"]:
        responses = [
            "Hello boss 😎",
            "Hi boss, ready to assist 🔥",
            "Greetings boss 🤖",
            "Hey boss, what can I do for you?"
        ]
        return random.choice(responses)

    # -------- WEATHER FEATURE (FINAL FIX) --------
    if "weather" in msg_lower:
        import requests
        from bs4 import BeautifulSoup

        city = re.sub(r"(what is|wt is|how is|weather|now|in)", "", msg_lower)
        city = city.strip()

        if city == "":
            return "Tell me the city name boss 🌍"

        try:
            url = f"https://www.google.com/search?q=weather+{city}"
            headers = {"User-Agent": "Mozilla/5.0"}

            res = requests.get(url, headers=headers)
            soup = BeautifulSoup(res.text, "html.parser")

            temp_tag = soup.find("span", {"id": "wob_tm"})
            desc_tag = soup.find("span", {"id": "wob_dc"})

            if temp_tag and desc_tag:
                temp = temp_tag.text
                desc = desc_tag.text
                return f"🌦️ {city.title()}: {temp}°C, {desc}"
            else:
                return f"Sorry boss 😓 Weather not found for {city.title()}"

        except Exception as e:
            print("WEATHER ERROR:", e)
            return "Unable to fetch weather right now boss 😓"

    # -------- TRANSLATE --------
    msg = translate_text(msg, "en")
    msg = msg[:1000]

    print("USER ID:", user_id)

    # ---------------- MEMORY ---------------- #
    memory = {}

    if user_id:
        mem = extract_memory(original_msg)

        if mem:
            key, value = mem
            old_memory = load_memory(user_id)

            if key not in old_memory or old_memory[key] != value:
                print(f"MEMORY UPDATED: {key} = {value}")
                save_memory(user_id, key, value)

        memory = load_memory(user_id)

    print("LOADED MEMORY:", memory)

    # ---------------- BASIC COMMANDS ---------------- #
    if "time" in msg_lower:
        return datetime.datetime.now().strftime("%H:%M:%S")

    if "date" in msg_lower:
        return str(datetime.date.today())

    # ---------------- OPEN COMMAND ---------------- #
    if "open" in msg_lower:
        try:
            site = msg_lower.split("open", 1)[1].strip()
            site = site.replace("the ", "").replace("please ", "")
            site = site.split()[0]

            if "whatsapp" in site:
                url = "https://web.whatsapp.com"
            elif "youtube" in site:
                url = "https://www.youtube.com"
            elif "instagram" in site:
                url = "https://www.instagram.com"
            else:
                url = f"https://{site}.com"

            return {
                "action": "open_url",
                "url": url,
                "reply": f"Opening {site}..."
            }

        except Exception as e:
            print("OPEN ERROR:", e)

    # ---------------- SEARCH + READ ---------------- #
    if "search" in msg_lower and "read" in msg_lower:
        query = msg_lower.replace("search", "").replace("read", "").strip()

        if query:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            return {
                "action": "open_url",
                "url": url,
                "reply": f"Here is what I found about {query}"
            }

    # ---------------- SEARCH ---------------- #
    if msg_lower.startswith("search"):
        query = msg_lower.replace("search", "").strip()

        if query:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            return {
                "action": "open_url",
                "url": url,
                "reply": f"Searching for {query}..."
            }

    # ---------------- PLAY ---------------- #
    if msg_lower.startswith("play"):
        query = msg_lower.replace("play", "").strip()

        if query:
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            return {
                "action": "open_url",
                "url": url,
                "reply": f"Playing {query}..."
            }

    # ---------------- STYLE ---------------- #
    use_points = any(word in msg_lower for word in [
        "points", "list", "steps", "explain", "advantages", "features", "summarize"
    ])

    msg += "\n\nGive only clean numbered points." if use_points else "\n\nGive normal answer."

    # ---------------- SAVE USER ---------------- #
    all_chats[current_chat_id].append({
        "role": "user",
        "content": original_msg
    })

    if user_id:
        conn = get_db()
        conn.execute(
            "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
            (current_chat_id, "user", original_msg)
        )
        conn.commit()
        conn.close()

    # ---------------- TEMP CHAT ---------------- #
    temp_chat = all_chats[current_chat_id][-3:].copy()
    temp_chat[-1] = {"role": "user", "content": msg}

    # ---------------- MEMORY TO AI ---------------- #
    memory_text = ""
    for i, (k, v) in enumerate(memory.items()):
        if i >= 3:
            break
        memory_text += f"{k} = {v}\n"

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{
                "role": "system",
                "content": f"You are Aura AI. Reply clearly.\nUser memory:\n{memory_text}"
            }] + temp_chat
        )

        reply = clean_text(response.choices[0].message.content)

        if use_points:
            reply = format_points(reply)

        # ---------------- SAVE AI ---------------- #
        all_chats[current_chat_id].append({
            "role": "assistant",
            "content": reply
        })

        if user_id:
            conn = get_db()
            conn.execute(
                "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                (current_chat_id, "assistant", reply)
            )
            conn.commit()
            conn.close()

        # ---------------- AUTO TITLE ---------------- #
        if chat_titles.get(current_chat_id) == "New Chat":
            new_title = generate_title(all_chats[current_chat_id])
            chat_titles[current_chat_id] = new_title

            if user_id:
                conn = get_db()
                conn.execute(
                    "UPDATE chats SET title=? WHERE id=?",
                    (new_title, current_chat_id)
                )
                conn.commit()
                conn.close()

        return reply

    except Exception as e:
        print("AI ERROR:", e)
        return "Something went wrong"
#----------------meomary------------------#
def extract_memory(text):
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract ONLY important personal user info.\n"
                        "Return STRICTLY: key:value\n\n"
                        "Examples:\n"
                        "my name is irfan → name:irfan\n"
                        "call me rahul → name:rahul\n"
                        "my favourite colour is red → color:red\n"
                        "i love blue → color:blue\n"
                        "i am from india → place:india\n"
                        "i live in chennai → place:chennai\n\n"
                        "If user changes info, return new value.\n"
                        "If nothing important, return: NONE"
                        )
                    
                 },
                {"role": "user", "content": text}
            ]
        )

        result = response.choices[0].message.content.strip().lower()

        print("MEMORY DEBUG:", result)  # 🔥

        if result == "none":
            return None

        if ":" in result:
            key, value = result.split(":", 1)
            return key.strip(), value.strip()

    except Exception as e:
        print("MEMORY ERROR:", e)
        return None

def load_memory(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT key, value FROM memory WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()

    memory = {}
    for r in rows:
        memory[r["key"]] = r["value"]

    return memory    


def save_memory(user_id, key, value):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO memory (user_id, key, value) VALUES (?, ?, ?)",
        (user_id, key, value)
    )
    conn.commit()
    conn.close()


# ---------------- ROUTES ---------------- #
from flask import session   # ✅ make sure this import exists

@app.route("/login_user", methods=["POST"])
def login_user():
    email = request.form.get("email")
    password = request.form.get("password")

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE email=? AND password=?",
        (email, password)
    ).fetchone()
    conn.close()

    if user:
        session["user_id"] = user["id"]   # 🔥 VERY IMPORTANT
        return redirect("/chat")
    else:
        return render_template("login.html", msg="Invalid email or password")
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                (username, email, password)
            )
            conn.commit()
            conn.close()

            return redirect("/")
        except:
            return render_template("signup.html", msg="Email already exists")

    return render_template("signup.html")


@app.route("/")
def login():
    return render_template("login.html")


@app.route("/chat")
def chat():
    global current_chat_id

    user_id = session.get("user_id")
    if not user_id:
        return redirect("/")

    chat_id = session.get("chat_id")

    # ✅ IF CHAT EXISTS → REUSE
    if chat_id and chat_id in all_chats:
        current_chat_id = chat_id

    else:
        # 🔥 CHECK DB FOR LAST CHAT
        conn = get_db()
        row = conn.execute(
            "SELECT id FROM chats WHERE user_id=? ORDER BY ROWID DESC LIMIT 1",
            (user_id,)
        ).fetchone()
        conn.close()

        if row:
            chat_id = row["id"]
            current_chat_id = chat_id
            session["chat_id"] = chat_id

            if chat_id not in all_chats:
                all_chats[chat_id] = []

        else:
            # 🔥 FIRST TIME USER
            chat_id = create_new_chat(user_id)
            current_chat_id = chat_id
            session["chat_id"] = chat_id

    return render_template("chat.html")

@app.route("/api/chat", methods=["POST"])
def chat_api():
    msg = request.form.get("message")

    user_id = session.get("user_id")   # ✅ HERE ONLY

    reply = process_message(msg, user_id)

    # 🔥 HANDLE ACTION RESPONSE
    if isinstance(reply, dict) and "action" in reply:
        return jsonify(reply)

    return jsonify({"reply": reply})

# ---------------- CHAT MANAGEMENT ---------------- #
def create_new_chat(user_id=None):
    global all_chats, current_chat_id, chat_titles

    chat_id = str(uuid.uuid4())
    all_chats[chat_id] = []
    chat_titles[chat_id] = "New Chat"

    current_chat_id = chat_id

    # 🔥 SAVE TO DB
    if user_id:
        conn = get_db()
        conn.execute(
            "INSERT INTO chats (id, user_id, title) VALUES (?, ?, ?)",
            (chat_id, user_id, "New Chat")
        )
        conn.commit()
        conn.close()

    return chat_id

@app.route("/get_chats")
def get_chats():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify([])   # 🔥 prevent crash

    conn = get_db()
    rows = conn.execute(
        "SELECT id, title FROM chats WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()

    return jsonify([{"id": r["id"], "title": r["title"]} for r in rows])

@app.route("/load_chat/<chat_id>")
def load_chat(chat_id):
    global current_chat_id

    user_id = session.get("user_id")   # 🔥 ADD THIS

    if not user_id:
        return jsonify([])   # prevent crash

    current_chat_id = chat_id

    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE chat_id=?",
        (chat_id,)
    ).fetchall()
    conn.close()

    chat = []
    for r in rows:
        chat.append({"role": r["role"], "content": r["content"]})

    return jsonify(chat)

@app.route("/new_chat", methods=["POST"])
def new_chat():
    user_id = session.get("user_id")   # ✅ HERE ONLY

    chat_id = create_new_chat(user_id)

    session["chat_id"] = chat_id

    return jsonify({"chat_id": chat_id})


@app.route("/rename_chat/<chat_id>", methods=["POST"])
def rename_chat(chat_id):
    global chat_titles

    new_title = request.form.get("title")

    if not new_title:
        return jsonify({"status": "error"})

    new_title = new_title.strip()[:30]

    # 🔥 UPDATE DATABASE
    conn = get_db()
    conn.execute(
        "UPDATE chats SET title=? WHERE id=?",
        (new_title, chat_id)
    )
    conn.commit()
    conn.close()

    # 🔥 UPDATE MEMORY (UI cache)
    chat_titles[chat_id] = new_title

    return jsonify({"status": "ok"})

@app.route("/delete_chat/<chat_id>", methods=["POST"])
def delete_chat(chat_id):
    global all_chats, chat_titles, current_chat_id

    try:
        conn = get_db()

        # 🔥 DELETE FROM DATABASE
        conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE id=?", (chat_id,))

        conn.commit()
        conn.close()

        # 🔥 DELETE FROM RAM (VERY IMPORTANT)
        if chat_id in all_chats:
            del all_chats[chat_id]

        if chat_id in chat_titles:
            del chat_titles[chat_id]

        # 🔥 RESET CURRENT CHAT
        if current_chat_id == chat_id:
            current_chat_id = None
            session.pop("chat_id", None)

        return jsonify({"status": "deleted"})

    except Exception as e:
        print("DELETE ERROR:", e)
        return jsonify({"error": str(e)}), 500
    
def load_user_chats(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT message, response FROM messages WHERE user_id=?",
        (user_id,)
    ).fetchall()
    conn.close()

    chat = []
    for r in rows:
        chat.append({"role": "user", "content": r["message"]})
        chat.append({"role": "assistant", "content": r["response"]})

    return chat

@app.route("/get_memory")
def get_memory():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({})

    memory = load_memory(user_id)
    return jsonify(memory)

@app.route("/delete_memory/<key>", methods=["POST"])
def delete_memory(key):
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"status": "error"})

    conn = get_db()
    conn.execute(
        "DELETE FROM memory WHERE user_id=? AND key=?",
        (user_id, key)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


@app.route("/update_memory", methods=["POST"])
def update_memory():
    user_id = session.get("user_id")

    if not user_id:
        return jsonify({"status": "error"})

    key = request.form.get("key")
    value = request.form.get("value")

    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO memory (user_id, key, value) VALUES (?, ?, ?)",
        (user_id, key, value)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})
# ---------------- RUN ---------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

#----------------------end-------------------
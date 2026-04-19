#------------------------------start-------------------

from groq import Groq
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import re
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import os
import json
import PyPDF2
from PIL import Image
import uuid
from pdf2image import convert_from_path
from deep_translator import GoogleTranslator
import firebase_admin
from firebase_admin import credentials, firestore
import base64
import random

# ---------------- FIREBASE ---------------- #
firebase_key = os.environ.get("FIREBASE_KEY")

if not firebase_admin._apps:
    if firebase_key:
        # 🔥 Render / Production
        cred = credentials.Certificate(json.loads(firebase_key))
    else:
        # 🔥 Local (VS Code)
        cred = credentials.Certificate("firebase_key.json")

    firebase_admin.initialize_app(cred)

db = firestore.client()
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


ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def translate_text(text, dest):
    try:
        return GoogleTranslator(source='auto', target=dest).translate(text)
    except:
        return text

# ---------------- CLEAN + FORMAT ---------------- #
def clean_text(text):
    return text.replace("**", "")

def format_points(text):
    text = text.replace("**", "")
    text = re.sub(r'Here are.*?:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+\.)\s*', r'\n\1 ', text)
    text = re.sub(r'[-•]\s*', r'\n- ', text)
    text = re.sub(r'\n+', '\n', text)
    return text.strip()

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
                {"role": "system", "content": "Generate a very short chat title in 2-4 words only. No markdown, no asterisks, no symbols, no full stops. Plain text only. Examples: 'About Physics', 'Python Basics', 'Weather Query'"},
                {"role": "user", "content": first_msg}
            ]
        )

        title = response.choices[0].message.content.strip()
        title = title.replace("**", "").replace("*", "").replace("#", "").replace("`", "").replace(".", "").strip()

        # ✅ max 20 chars
        return title[:20]

    except:
        return first_msg[:15] if first_msg else "New Chat"
# ---------------- MEMORY (FIREBASE) ---------------- #
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
        print("MEMORY DEBUG:", result)

        if result == "none":
            return None

        if ":" in result:
            key, value = result.split(":", 1)
            return key.strip(), value.strip()

    except Exception as e:
        print("MEMORY ERROR:", e)
        return None

def load_memory(user_id):
    try:
        docs = db.collection("users").document(str(user_id))\
                 .collection("memory").stream()
        memory = {}
        for doc in docs:
            data = doc.to_dict()
            memory[doc.id] = data.get("value", "")
        return memory
    except Exception as e:
        print("LOAD MEMORY ERROR:", e)
        return {}

def save_memory(user_id, key, value):
    try:
        db.collection("users").document(str(user_id))\
          .collection("memory").document(key)\
          .set({"value": value})
    except Exception as e:
        print("SAVE MEMORY ERROR:", e)

# ---------------- CHAT MANAGEMENT ---------------- #
def create_new_chat(user_id=None):
    global current_chat_id, chat_titles, all_chats

    chat_id = str(uuid.uuid4())
    current_chat_id = chat_id
    chat_titles[chat_id] = "New Chat"
    all_chats[chat_id] = []

    if user_id:
        db.collection("users").document(str(user_id))\
          .collection("chats").document(chat_id)\
          .set({
              "title": "New Chat",
              "created_at": firestore.SERVER_TIMESTAMP
          })

    return chat_id



# ---------------- AI ENGINE ---------------- #
def process_message(msg, user_id=None):
    global all_chats, current_chat_id, chat_titles

    original_msg = msg.strip()

    # ---------------- SAFETY ---------------- #
    if not current_chat_id or current_chat_id not in all_chats:
        create_new_chat(user_id)

    msg_lower = msg.lower().strip()

    # -------- GREETING --------
    if msg_lower in ["hi", "hello", "hey", "hllo", "helo", "hlo"]:
        greeting_responses = [
            "Hello boss 😎",
            "Hi boss, ready to assist 🔥",
            "Greetings boss 🤖",
            "Hey boss, what can I do for you?"
        ]
        greeting_reply = random.choice(greeting_responses)

        all_chats[current_chat_id].append({"role": "user", "content": original_msg})
        all_chats[current_chat_id].append({"role": "assistant", "content": greeting_reply})

        if user_id:
            doc = db.collection("users").document(str(user_id))\
                     .collection("chats").document(current_chat_id).get()
            existing_title = doc.to_dict().get("title", "New Chat") if doc.exists else "New Chat"

            if existing_title == "New Chat":
                new_title = generate_title(all_chats[current_chat_id])
                new_title = new_title.replace("**","").replace("*","").strip()
            else:
                new_title = existing_title

            chat_ref = db.collection("users").document(str(user_id))\
                         .collection("chats").document(current_chat_id)

            chat_ref.set({
                "title": new_title,
                "created_at": firestore.SERVER_TIMESTAMP
            }, merge=True)

            chat_ref.collection("messages").add({
                "user_message": original_msg,
                "ai_reply": greeting_reply,
                "time": firestore.SERVER_TIMESTAMP
            })

        return greeting_reply

    # -------- WEATHER --------
    if "weather" in msg_lower:
        import requests

        city = re.sub(r"(what is|wt is|how is|weather|now|in|the|tell me|about)", "", msg_lower).strip()

        if city == "":
            return "Tell me the city name boss 🌍"

        try:
            url = f"https://wttr.in/{city}?format=j1"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=5)
            data = res.json()

            temp = data["current_condition"][0]["temp_C"]
            feels = data["current_condition"][0]["FeelsLikeC"]
            desc = data["current_condition"][0]["weatherDesc"][0]["value"]
            humidity = data["current_condition"][0]["humidity"]
            wind = data["current_condition"][0]["windspeedKmph"]

            return (
                f"🌦️ {city.title()} Weather:\n"
                f"🌡️ Temp: {temp}°C (Feels {feels}°C)\n"
                f"☁️ {desc}\n"
                f"💧 Humidity: {humidity}%\n"
                f"💨 Wind: {wind} km/h"
            )

        except Exception as e:
            print("WEATHER ERROR:", e)
            return f"Sorry boss 😓 Weather not found for {city.title()}"

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
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        return datetime.datetime.now(ist).strftime("%H:%M:%S")

    if "date" in msg_lower:
        return str(datetime.date.today())

    # ---------------- OPEN ---------------- #
    if "open" in msg_lower:
        try:
            site = msg_lower.split("open", 1)[1].strip()
            site = site.replace("the ", "").replace("please ", "").split()[0]

            if "whatsapp" in site:
                url = "https://web.whatsapp.com"
            elif "youtube" in site:
                url = "https://www.youtube.com"
            elif "instagram" in site:
                url = "https://www.instagram.com"
            else:
                url = f"https://{site}.com"

            return {"action": "open_url", "url": url, "reply": f"Opening {site}..."}

        except Exception as e:
            print("OPEN ERROR:", e)

    # ---------------- SEARCH + READ ---------------- #
    if "search" in msg_lower and "read" in msg_lower:
        query = msg_lower.replace("search", "").replace("read", "").strip()
        if query:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            return {"action": "open_url", "url": url, "reply": f"Here is what I found about {query}"}

    # ---------------- SEARCH ---------------- #
    if msg_lower.startswith("search"):
        query = msg_lower.replace("search", "").strip()
        if query:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            return {"action": "open_url", "url": url, "reply": f"Searching for {query}..."}

    # ---------------- PLAY ---------------- #
    if msg_lower.startswith("play"):
        query = msg_lower.replace("play", "").strip()
        if query:
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            return {"action": "open_url", "url": url, "reply": f"Playing {query}..."}

    # ---------------- STYLE ---------------- #
    use_points = any(word in msg_lower for word in [
        "points", "list", "steps", "explain", "advantages", "features", "summarize"
    ])
    msg += "\n\nGive only clean numbered points." if use_points else "\n\nGive normal answer."

    # ---------------- SAVE USER MESSAGE ---------------- #
    all_chats[current_chat_id].append({"role": "user", "content": original_msg})

    # ---------------- TEMP CHAT ---------------- #
    temp_chat = all_chats[current_chat_id][-3:].copy()
    temp_chat[-1] = {"role": "user", "content": msg}

    # ---------------- MEMORY TEXT ---------------- #
    memory_text = ""
    for i, (k, v) in enumerate(memory.items()):
        if i >= 3:
            break
        memory_text += f"{k} = {v}\n"

    # ---------------- AI CALL ---------------- #
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

        # ---------------- SAVE AI REPLY ---------------- #
        all_chats[current_chat_id].append({"role": "assistant", "content": reply})

        # ---------------- AUTO TITLE ---------------- #
        if user_id:
            doc = db.collection("users").document(str(user_id))\
                     .collection("chats").document(current_chat_id).get()
            existing_title = doc.to_dict().get("title", "New Chat") if doc.exists else "New Chat"

            if existing_title == "New Chat":
                new_title = generate_title(all_chats[current_chat_id])
                new_title = new_title.replace("**","").replace("*","").strip()
            else:
                new_title = existing_title

        # ---------------- SAVE TO FIREBASE ---------------- #
        if user_id:
            chat_ref = db.collection("users").document(str(user_id))\
                         .collection("chats").document(current_chat_id)

            chat_ref.set({
                "title": new_title,
                "created_at": firestore.SERVER_TIMESTAMP
            }, merge=True)

            chat_ref.collection("messages").add({
                "user_message": original_msg,
                "ai_reply": reply,
                "time": firestore.SERVER_TIMESTAMP
            })

        return reply

    except Exception as e:
        print("AI ERROR:", e)
        return "Something went wrong"
# ---------------- ROUTES ---------------- #
@app.route("/")
def login():
    return render_template("login.html")

@app.route("/login_user", methods=["POST"])
def login_user():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()

    users = db.collection("users").where("email", "==", email).stream()

    for user in users:
        data = user.to_dict()

        stored_password = str(data.get("password", "")).strip()

        if stored_password == password:
            session["user_id"] = user.id
            session["username"] = data["email"]
            return redirect("/chat")

    return render_template("login.html", msg="Invalid email or password")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        try:
            # check existing user
            existing = db.collection("users").where("email", "==", email).stream()
            for doc in existing:
                return render_template("signup.html", msg="Email already exists")

            # create new user
            db.collection("users").add({
                "username": username,
                "email": email.strip().lower(),  # ✅ lowercase
                "password": password.strip()     # ✅ trim spaces
            })

            return redirect("/")

        except Exception as e:
            print("SIGNUP ERROR:", e)
            return render_template("signup.html", msg="Error creating account")

    return render_template("signup.html")


@app.route("/chat")
def chat():
    global current_chat_id

    user_id = session.get("user_id")
    if not user_id:
        return redirect("/")

    chat_id = session.get("chat_id")

    if chat_id and chat_id in all_chats:
        current_chat_id = chat_id
    else:
        # Get last chat from Firebase
        docs = db.collection("users").document(str(user_id))\
                 .collection("chats").order_by("created_at", direction=firestore.Query.DESCENDING).limit(1).stream()

        last_chat = None
        for doc in docs:
            last_chat = doc.id

        if last_chat:
            current_chat_id = last_chat
            session["chat_id"] = last_chat
            if last_chat not in all_chats:
                all_chats[last_chat] = []
        else:
            chat_id = create_new_chat(user_id)
            current_chat_id = chat_id
            session["chat_id"] = chat_id

    return render_template("chat.html")

@app.route("/api/chat", methods=["POST"])
def chat_api():
    global current_chat_id

    msg = request.form.get("message")
    user_id = session.get("user_id")

    # ✅ get chat_id directly from frontend
    chat_id_from_js = request.form.get("chat_id")
    if chat_id_from_js:
        current_chat_id = chat_id_from_js
        session["chat_id"] = chat_id_from_js
        if chat_id_from_js not in all_chats:
            all_chats[chat_id_from_js] = []

    reply = process_message(msg, user_id)

    if isinstance(reply, dict) and "action" in reply:
        return jsonify(reply)

    return jsonify({"reply": reply})


@app.route("/new_chat", methods=["POST"])
def new_chat():
    user_id = session.get("user_id")
    chat_id = create_new_chat(user_id)
    session["chat_id"] = chat_id
    return jsonify({"status": "new", "chat_id": chat_id})

@app.route("/get_chats")
def get_chats():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify([])

    docs = db.collection("users").document(str(user_id))\
             .collection("chats")\
             .order_by("created_at", direction=firestore.Query.DESCENDING)\
             .stream()  # ✅ newest first

    chats = []
    for doc in docs:
        data = doc.to_dict()
        chats.append({"id": doc.id, "title": data.get("title", "New Chat")})

    return jsonify(chats)

@app.route("/load_chat/<chat_id>")
def load_chat(chat_id):
    global current_chat_id, all_chats

    user_id = session.get("user_id")
    if not user_id:
        return jsonify([])

    # Switch active chat
    current_chat_id = chat_id
    session["chat_id"] = chat_id

    docs = db.collection("users").document(str(user_id))\
             .collection("chats").document(chat_id)\
             .collection("messages").order_by("time", direction=firestore.Query.ASCENDING).stream()

    chat = []
    all_chats[chat_id] = []

    for doc in docs:
        data = doc.to_dict()
        chat.append({"role": "user", "content": data.get("user_message", "")})
        chat.append({"role": "assistant", "content": data.get("ai_reply", "")})

    all_chats[chat_id] = chat  # restore context for AI
    return jsonify(chat)

@app.route("/rename_chat/<chat_id>", methods=["POST"])
def rename_chat(chat_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"status": "error"})

    new_title = request.form.get("title", "").strip()[:30]
    if not new_title:
        return jsonify({"status": "error"})

    db.collection("users").document(str(user_id))\
      .collection("chats").document(chat_id)\
      .set({"title": new_title}, merge=True)

    chat_titles[chat_id] = new_title
    return jsonify({"status": "ok"})

@app.route("/delete_chat/<chat_id>", methods=["POST"])
def delete_chat(chat_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"status": "error"})

    try:
        chat_ref = db.collection("users").document(str(user_id))\
                     .collection("chats").document(chat_id)

        messages = chat_ref.collection("messages").stream()
        for msg in messages:
            msg.reference.delete()

        chat_ref.delete()
        return jsonify({"status": "deleted"})

    except Exception as e:
        print("DELETE ERROR:", e)
        return jsonify({"error": str(e)})

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

    db.collection("users").document(str(user_id))\
      .collection("memory").document(key).delete()

    return jsonify({"status": "ok"})

@app.route("/update_memory", methods=["POST"])
def update_memory():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"status": "error"})

    key = request.form.get("key")
    value = request.form.get("value")

    db.collection("users").document(str(user_id))\
      .collection("memory").document(key)\
      .set({"value": value})

    return jsonify({"status": "ok"})

# ---------------- RUN ---------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

#----------------------end-------------------
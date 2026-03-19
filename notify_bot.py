import requests
import time
import os
import subprocess
from datetime import datetime

from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= LOAD ENV =================
load_dotenv()  # MUST FIRST

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE")

print("ENV FILE:", GOOGLE_CREDS_FILE)

# Convert OWNER_ID safely
if OWNER_ID:
    OWNER_ID = int(OWNER_ID)

if not all([BOT_TOKEN, OWNER_ID, SHEET_ID, GOOGLE_CREDS_FILE]):
    raise RuntimeError("❌ Missing environment variables")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0

MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1GB
pending_quality = {}

# ================= GOOGLE SHEETS =================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = ServiceAccountCredentials.from_json_keyfile_name(
    GOOGLE_CREDS_FILE, scope
)

gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID)

try:
    ws = sheet.worksheet("telegram")
except Exception:
    ws = sheet.add_worksheet("telegram", 1000, 10)
    ws.append_row(["Time", "Name", "Username", "UserID", "Action", "Content"])

# ================= TELEGRAM HELPERS =================
def send_message(chat_id, text):
    r = requests.post(f"{TG_API}/sendMessage", data={"chat_id": chat_id, "text": text}).json()
    return r.get("result", {}).get("message_id")


def edit_message(chat_id, msg_id, text):
    requests.post(f"{TG_API}/editMessageText", data={
        "chat_id": chat_id,
        "message_id": msg_id,
        "text": text
    })


def send_keyboard(chat_id, text, keyboard):
    r = requests.post(f"{TG_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {"inline_keyboard": keyboard},
    }).json()
    return r.get("result", {}).get("message_id")


def answer_callback(callback_query_id):
    requests.post(f"{TG_API}/answerCallbackQuery", data={"callback_query_id": callback_query_id})


def delete_message(chat_id, msg_id):
    requests.post(f"{TG_API}/deleteMessage", data={"chat_id": chat_id, "message_id": msg_id})


def send_document(chat_id, file_path):
    with open(file_path, "rb") as f:
        requests.post(f"{TG_API}/sendDocument",
                      data={"chat_id": chat_id},
                      files={"document": f})


def log(user, action, content):
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user.get("first_name", ""),
        user.get("username", ""),
        user.get("id"),
        action,
        content,
    ])


def notify_owner(user):
    send_message(
        OWNER_ID,
        f"👤 New user\n\n"
        f"Name: {user.get('first_name')}\n"
        f"Username: @{user.get('username', 'N/A')}\n"
        f"User ID: {user['id']}"
    )

# ================= DOWNLOAD =================
def cleanup(chat_id, platform):
    base = f"dl_{platform}_{chat_id}"
    for f in os.listdir("."):
        if f.startswith(base):
            try:
                os.remove(f)
            except:
                pass


def download_and_send(chat_id, user, url, quality, platform):
    is_audio = quality == "audio"
    base_name = f"dl_{platform}_{chat_id}"
    out_template = f"{base_name}.%(ext)s"

    msg_id = send_message(chat_id, f"⬇️ Downloading ({quality})...")

    try:
        if is_audio:
            cmd = [
                "yt-dlp", "--no-playlist",
                "-x", "--audio-format", "mp3",
                "-o", out_template, url
            ]
        else:
            height = {"360p": 360, "720p": 720, "1080p": 1080}.get(quality, 720)
            fmt = f"bestvideo[height<={height}]+bestaudio/best"
            cmd = [
                "yt-dlp", "--no-playlist",
                "-f", fmt,
                "--merge-output-format", "mp4",
                "-o", out_template, url
            ]

        subprocess.run(cmd, check=True, timeout=600)

        files = [f for f in os.listdir(".") if f.startswith(base_name)]
        if not files:
            raise Exception("File not found")

        file_path = files[0]
        size = os.path.getsize(file_path)

        if size > MAX_UPLOAD_SIZE:
            edit_message(chat_id, msg_id, "❌ File too large")
        else:
            edit_message(chat_id, msg_id, "📤 Uploading...")
            send_document(chat_id, file_path)
            edit_message(chat_id, msg_id, "✅ Done!")

        log(user, f"{platform}_{quality}", url)

    except Exception as e:
        edit_message(chat_id, msg_id, f"❌ Error: {str(e)}")

    finally:
        cleanup(chat_id, platform)


def ask_quality(chat_id, url, platform):
    keyboard = [
        [{"text": "🎵 Audio", "callback_data": f"dl|{platform}|audio"}],
        [
            {"text": "360p", "callback_data": f"dl|{platform}|360p"},
            {"text": "720p", "callback_data": f"dl|{platform}|720p"},
            {"text": "1080p", "callback_data": f"dl|{platform}|1080p"},
        ],
    ]
    send_keyboard(chat_id, "Choose quality:", keyboard)
    pending_quality[chat_id] = {"url": url, "platform": platform}

# ================= MAIN LOOP =================
print("🤖 Bot started")

while True:
    try:
        updates = requests.get(
            f"{TG_API}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 30},
            timeout=35,
        ).json()
    except Exception as e:
        print("Poll error:", e)
        time.sleep(2)
        continue

    for upd in updates.get("result", []):
        last_update_id = upd["update_id"]

        if "callback_query" in upd:
            cb = upd["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            data = cb.get("data", "")

            answer_callback(cb["id"])

            if data.startswith("dl|"):
                _, platform, quality = data.split("|")
                pending = pending_quality.pop(chat_id, None)

                if pending:
                    download_and_send(chat_id, cb["from"], pending["url"], quality, platform)
                else:
                    send_message(chat_id, "❌ Session expired")
            continue

        if "message" not in upd:
            continue

        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text == "/start":
            notify_owner(msg["from"])
            send_message(chat_id, "Send YouTube / Instagram link")
            continue

        if "youtube.com" in text or "youtu.be" in text:
            ask_quality(chat_id, text, "yt")
        elif "instagram.com" in text:
            ask_quality(chat_id, text, "ig")
        else:
            send_message(chat_id, "❌ Invalid input")

    time.sleep(1)

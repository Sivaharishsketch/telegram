from dotenv import load_dotenv
import os
import requests
import time
import subprocess
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= LOAD ENV =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE")

if not all([BOT_TOKEN, OWNER_ID, SHEET_ID, GOOGLE_CREDS_FILE]):
    raise RuntimeError("❌ Missing environment variables")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0
MAX_UPLOAD_SIZE = 1024 * 1024 * 1024
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
except:
    ws = sheet.add_worksheet("telegram", 1000, 10)
    ws.append_row(["Time", "Name", "Username", "UserID", "Action", "Content"])

# ================= TELEGRAM =================
def send_message(chat_id, text):
    requests.post(f"{TG_API}/sendMessage", data={"chat_id": chat_id, "text": text})


def send_document(chat_id, file_path):
    with open(file_path, "rb") as f:
        requests.post(f"{TG_API}/sendDocument",
                      data={"chat_id": chat_id},
                      files={"document": f})


def send_keyboard(chat_id, text, keyboard):
    requests.post(f"{TG_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {"inline_keyboard": keyboard},
    })


def answer_callback(callback_query_id):
    requests.post(f"{TG_API}/answerCallbackQuery",
                  data={"callback_query_id": callback_query_id})


def log(user, action, content):
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user.get("first_name", ""),
        user.get("username", ""),
        user.get("id"),
        action,
        content,
    ])

# ================= DOWNLOAD =================
def cleanup(prefix):
    for f in os.listdir("."):
        if f.startswith(prefix):
            try:
                os.remove(f)
            except:
                pass


def download_and_send(chat_id, user, url, quality, platform):
    base = f"dl_{platform}_{chat_id}"
    out = f"{base}.%(ext)s"

    send_message(chat_id, "⬇️ Downloading...")

    try:
        # ===== AUDIO =====
        if quality == "audio":
            cmd = [
                "yt-dlp", "--no-playlist",
                "-x", "--audio-format", "mp3",
                "-o", out, url
            ]

        # ===== VIDEO =====
        else:
            if platform == "ig":
                # ✅ FIX: bestvideo+bestaudio merge பண்ணி mp4 ஆக remux பண்றோம்
                # இதனால் m4a பதிலா .mp4 வரும்
                fmt = "bestvideo+bestaudio/best"
            else:
                # ✅ FIX: bestvideo+bestaudio use பண்றோம் - இதனால் 1080p சரியா வரும்
                # முன்னாடி best[height<=1080] என்பது pre-merged stream மட்டும் எடுக்கும் (480p)
                height = {"360p": 360, "720p": 720, "1080p": 1080}.get(quality, 720)
                fmt = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"

            cmd = [
                "yt-dlp",
                "--no-playlist",
                "-f", fmt,
                "--merge-output-format", "mp4",
                "--remux-video", "mp4",   # ✅ FIX: எந்த format வந்தாலும் mp4 ஆக convert ஆகும்
                "-o", out,
                url
            ]

        subprocess.run(cmd, check=True, timeout=600)

        files = [f for f in os.listdir(".") if f.startswith(base)]
        if not files:
            raise Exception("File not found")

        file_path = sorted(files, key=lambda x: os.path.getmtime(x), reverse=True)[0]
        size = os.path.getsize(file_path)

        if size > MAX_UPLOAD_SIZE:
            send_message(chat_id, "❌ File too large")
        else:
            send_message(chat_id, "📤 Uploading...")
            send_document(chat_id, file_path)
            send_message(chat_id, "✅ Done!")

        log(user, f"{platform}_{quality}", url)

    except Exception as e:
        send_message(chat_id, f"❌ Error: {str(e)}")

    finally:
        cleanup(base)


# ================= QUALITY =================
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


# ================= MAIN =================
print("🤖 Bot started")

while True:
    try:
        updates = requests.get(
            f"{TG_API}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 30},
            timeout=35,
        ).json()
    except:
        time.sleep(2)
        continue

    for upd in updates.get("result", []):
        last_update_id = upd["update_id"]

        # ===== CALLBACK =====
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

        # ===== MESSAGE =====
        if "message" not in upd:
            continue

        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        user = msg["from"]
        text = msg.get("text", "")

        if text == "/start":
            send_message(chat_id, "👋 Send YouTube or Instagram link")
            continue

        # ===== YOUTUBE =====
        if "youtube.com" in text or "youtu.be" in text:
            ask_quality(chat_id, text, "yt")

        # ===== INSTAGRAM (AUTO) =====
        elif "instagram.com" in text:
            download_and_send(chat_id, user, text, "720p", "ig")

        else:
            send_message(chat_id, "❌ Send valid link")

    time.sleep(1)
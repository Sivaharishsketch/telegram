import requests
import time
import os
import json
import subprocess
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = os.getenv("OWNER_ID")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDENTIALS")

missing = []
for k in ["BOT_TOKEN", "OWNER_ID", "SHEET_ID", "GOOGLE_CREDENTIALS"]:
    if not os.getenv(k):
        missing.append(k)

if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0

# ================= GOOGLE SHEETS =================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    json.loads(GOOGLE_CREDS_RAW), scope
)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID)

try:
    ws = sheet.worksheet("telegram")
except:
    ws = sheet.add_worksheet("telegram", 1000, 10)
    ws.append_row(["Time", "Name", "Username", "UserID", "Action", "Content"])

# ================= HELPERS =================
def send_message(chat_id, text):
    requests.post(f"{TG_API}/sendMessage", data={"chat_id": chat_id, "text": text})

def send_document(chat_id, path):
    with open(path, "rb") as f:
        requests.post(
            f"{TG_API}/sendDocument",
            data={"chat_id": chat_id},
            files={"document": f},
        )

def log(user, action, content):
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user.get("first_name", ""),
        user.get("username", ""),
        user.get("id", ""),
        action,
        content
    ])

def notify_owner(user):
    send_message(
        OWNER_ID,
        f"👤 New user\n\n"
        f"Name: {user.get('first_name')}\n"
        f"Username: @{user.get('username','N/A')}\n"
        f"User ID: {user['id']}"
    )

# ================= BOT LOOP =================
print("🤖 Bot started")

while True:
    updates = requests.get(
        f"{TG_API}/getUpdates",
        params={"offset": last_update_id + 1, "timeout": 30}
    ).json()

    if not updates.get("ok"):
        time.sleep(2)
        continue

    for upd in updates["result"]:
        last_update_id = upd["update_id"]

        if "message" not in upd:
            continue

        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        user = msg["from"]

        # ===== START =====
        if msg.get("text") == "/start":
            notify_owner(user)
            log(user, "START", "")
            send_message(chat_id, "👋 Hi! Send YouTube link or forward any file")
            continue

        # ===== FORWARDED / UPLOADED FILE =====
        if "document" in msg or "video" in msg:
            file = msg.get("document") or msg.get("video")
            file_id = file["file_id"]

            file_info = requests.get(
                f"{TG_API}/getFile",
                params={"file_id": file_id}
            ).json()

            file_path = file_info["result"]["file_path"]
            download_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

            send_message(chat_id, f"⬇️ Direct download link:\n{download_link}")
            log(user, "FILE", download_link)
            continue

        # ===== YOUTUBE =====
        text = msg.get("text", "")
        if "youtube.com" in text or "youtu.be" in text:
            send_message(chat_id, "⬇️ Downloading YouTube video...")
            log(user, "YOUTUBE", text)

            out = f"yt_{chat_id}.mp4"
            try:
                subprocess.run(
                    ["yt-dlp", "-f", "best[ext=mp4]/best", "-o", out, text],
                    check=True
                )
                send_document(chat_id, out)   # 👈 IMPORTANT
                os.remove(out)
            except Exception as e:
                send_message(chat_id, "❌ YouTube download failed")
            continue

        send_message(chat_id, "❌ Send YouTube link or forward a file")

    time.sleep(1)

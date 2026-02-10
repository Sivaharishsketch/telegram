import requests
import time
import os
import json
import subprocess
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDS_RAW = os.getenv("GOOGLE_CREDENTIALS")

if not all([BOT_TOKEN, OWNER_ID, SHEET_ID, GOOGLE_CREDS_RAW]):
    raise RuntimeError("❌ Missing environment variables")

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
    r = requests.post(
        f"{TG_API}/sendMessage",
        data={"chat_id": chat_id, "text": text}
    ).json()
    return r["result"]["message_id"] if r.get("ok") else None

def edit_message(chat_id, msg_id, text):
    requests.post(
        f"{TG_API}/editMessageText",
        data={
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": text
        }
    )

def send_document(chat_id, file_path):
    with open(file_path, "rb") as f:
        requests.post(
            f"{TG_API}/sendDocument",
            data={"chat_id": chat_id},
            files={"document": f}
        )

def log(user, action, content):
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user.get("first_name", ""),
        user.get("username", ""),
        user.get("id"),
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
        text = msg.get("text", "")

        # ===== START =====
        if text == "/start":
            notify_owner(user)
            log(user, "START", "")
            send_message(chat_id, "👋 Hi!\nSend YouTube / Instagram link or forward any file")
            continue

        # ===== FILE (ANY SIZE) =====
        if "document" in msg or "video" in msg:
            file = msg.get("document") or msg.get("video")
            file_id = file["file_id"]

            r = requests.get(
                f"{TG_API}/getFile",
                params={"file_id": file_id}
            ).json()

            if not r.get("ok"):
                send_message(chat_id, "❌ Unable to get file")
                continue

            path = r["result"]["file_path"]
            link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}"

            send_message(chat_id, f"⬇️ Direct download link:\n{link}")
            log(user, "FILE", link)
            continue

        # ===== YOUTUBE =====
        if "youtube.com" in text or "youtu.be" in text:
            log(user, "YOUTUBE", text)

            msg_id = send_message(chat_id, "⏳ Preparing download...")
            out = f"yt_{chat_id}.mp4"

            try:
                edit_message(chat_id, msg_id, "⬇️ Downloading YouTube video...")
                subprocess.run(
                    ["yt-dlp", "-f", "best[ext=mp4]/best", "-o", out, text],
                    check=True
                )

                edit_message(chat_id, msg_id, "📤 Uploading to Telegram...")

                if os.path.getsize(out) <  1000 * 1024 * 1024:
                    send_document(chat_id, out)
                else:
                    send_message(chat_id, "⚠️ File >45MB, sending link only")

                edit_message(chat_id, msg_id, "✅ Done")
                os.remove(out)

            except:
                edit_message(chat_id, msg_id, "❌ YouTube download failed")
            continue

        # ===== INSTAGRAM =====
        if "instagram.com" in text:
            log(user, "INSTAGRAM", text)

            msg_id = send_message(chat_id, "⏳ Preparing Instagram download...")
            out = f"ig_{chat_id}.mp4"

            try:
                edit_message(chat_id, msg_id, "⬇️ Downloading Instagram media...")
                subprocess.run(["yt-dlp", "-o", out, text], check=True)

                edit_message(chat_id, msg_id, "📤 Uploading to Telegram...")

                if os.path.getsize(out) < 45 * 1024 * 1024:
                    send_document(chat_id, out)
                else:
                    send_message(chat_id, "⚠️ File too large, cannot upload")

                edit_message(chat_id, msg_id, "✅ Done")
                os.remove(out)

            except:
                edit_message(chat_id, msg_id, "❌ Instagram download failed")
            continue

        send_message(chat_id, "❌ Send YouTube / Instagram link or forward a file")

    time.sleep(1)

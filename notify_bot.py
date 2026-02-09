import requests
import time
import os
import json
import subprocess
from datetime import datetime

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ================= CONFIG =================
BOT_TOKEN = os.environ.get("BOT_TOKEN")      # Telegram bot token
OWNER_ID = os.environ.get("OWNER_ID")        # Your Telegram user ID
SPREADSHEET_ID = os.environ.get("SHEET_ID")  # Google Sheet ID

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0

# ================= GOOGLE SHEETS AUTH =================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds_json = json.loads(os.environ["GOOGLE_CREDENTIALS"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
gc = gspread.authorize(creds)

sheet = gc.open_by_key(SPREADSHEET_ID)

# get or create "telegram" sheet
try:
    ws = sheet.worksheet("telegram")
except gspread.WorksheetNotFound:
    ws = sheet.add_worksheet(title="telegram", rows="1000", cols="10")
    ws.append_row(
        ["Time", "Name", "Username", "UserID", "Action", "Content"]
    )

# ================= HELPERS =================
def send_message(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    requests.post(f"{TELEGRAM_API}/sendMessage", data=data)

def send_video(chat_id, file_path):
    with open(file_path, "rb") as f:
        requests.post(
            f"{TELEGRAM_API}/sendVideo",
            data={"chat_id": chat_id},
            files={"video": f}
        )

def log_to_sheet(user, action, content):
    ws.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user.get("first_name", ""),
        user.get("username", ""),
        user.get("id", ""),
        action,
        content
    ])

def notify_owner(user):
    text = (
        "👤 New user using the bot\n\n"
        f"Name: {user.get('first_name','')}\n"
        f"Username: @{user.get('username','N/A')}\n"
        f"User ID: {user['id']}"
    )
    send_message(OWNER_ID, text)

def main_menu():
    return {
        "inline_keyboard": [
            [{"text": "📸 Instagram", "callback_data": "INSTAGRAM"}],
            [{"text": "▶️ YouTube", "callback_data": "YOUTUBE"}],
            [{"text": "💸 Cashflow", "callback_data": "CASHFLOW"}],
        ]
    }

# ================= MAIN LOOP =================
print("🤖 Bot started...")

while True:
    try:
        res = requests.get(
            f"{TELEGRAM_API}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 30}
        ).json()

        if not res.get("ok"):
            time.sleep(2)
            continue

        for update in res["result"]:
            last_update_id = update["update_id"]

            # ---------- CALLBACK ----------
            if "callback_query" in update:
                cb = update["callback_query"]
                chat_id = cb["message"]["chat"]["id"]
                action = cb["data"]

                if action == "INSTAGRAM":
                    send_message(chat_id, "📸 Instagram reel / video link anuppu")

                elif action == "YOUTUBE":
                    send_message(chat_id, "▶️ YouTube video link anuppu")

                elif action == "CASHFLOW":
                    send_message(chat_id, "💸 Cashflow – coming soon 😄")

                continue

            # ---------- MESSAGE ----------
            if "message" not in update:
                continue

            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user = msg["from"]

            if "text" not in msg:
                continue

            text = msg["text"].strip()

            # /start
            if text == "/start":
                notify_owner(user)
                log_to_sheet(user, "START", "")
                send_message(chat_id, f"👋 Hi @{user.get('username','user')}")
                send_message(chat_id, "👇 Choose an option", main_menu())
                continue

            # Instagram
            if "instagram.com" in text:
                send_message(chat_id, "⬇️ Downloading Instagram video...")
                log_to_sheet(user, "INSTAGRAM", text)

                output = f"ig_{chat_id}.mp4"
                try:
                    subprocess.run(
                        ["yt-dlp", "-f", "mp4", "-o", output, text],
                        check=True
                    )
                    send_video(chat_id, output)
                    os.remove(output)
                except Exception as e:
                    send_message(chat_id, "❌ Instagram download failed")

                continue

            # YouTube
            if "youtube.com" in text or "youtu.be" in text:
                send_message(chat_id, "⬇️ Downloading YouTube video (best quality)...")
                log_to_sheet(user, "YOUTUBE", text)

                output = f"yt_{chat_id}.mp4"
                try:
                    subprocess.run(
                        ["yt-dlp", "-f", "bestvideo+bestaudio/best", "-o", output, text],
                        check=True
                    )
                    send_video(chat_id, output)
                    os.remove(output)
                except Exception as e:
                    send_message(chat_id, "❌ YouTube download failed")

                continue

            # default
            send_message(chat_id, "❌ Please use /start")

        time.sleep(1)

    except Exception as e:
        print("ERROR:", e)
        time.sleep(5)

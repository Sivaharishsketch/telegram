import requests
import time
import os
import subprocess
import json

BOT_TOKEN = "8272387883:AAEFAt7lMX0EjX6BvL9tVVETNXUkfhzASXE"
OWNER_ID = "609150604"

URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0

# ---------- HELPERS ----------
def send_message(chat_id, text, keyboard=None):
    data = {"chat_id": chat_id, "text": text}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    requests.post(f"{URL}/sendMessage", data=data)

def send_video(chat_id, file_path):
    with open(file_path, "rb") as video:
        requests.post(
            f"{URL}/sendVideo",
            data={"chat_id": chat_id},
            files={"video": video}
        )

def main_menu():
    return {
        "inline_keyboard": [
            [{"text": "📸 Instagram", "callback_data": "INSTAGRAM"}],
            [{"text": "▶️ YouTube", "callback_data": "YOUTUBE"}],
            [{"text": "💸 Cashflow", "callback_data": "CASHFLOW"}],
        ]
    }

def notify_owner(user):
    text = (
        "👤 New user using the bot\n\n"
        f"Name: {user.get('first_name','')}\n"
        f"Username: @{user.get('username','N/A')}\n"
        f"User ID: {user['id']}"
    )
    send_message(OWNER_ID, text)

# ---------- MAIN LOOP ----------
while True:
    res = requests.get(f"{URL}/getUpdates?offset={last_update_id + 1}").json()

    if res.get("ok"):
        for update in res["result"]:
            last_update_id = update["update_id"]

            # ===== INLINE BUTTON CLICK =====
            if "callback_query" in update:
                cb = update["callback_query"]
                chat_id = cb["message"]["chat"]["id"]
                action = cb["data"]

                if action == "INSTAGRAM":
                    send_message(chat_id, "📸 Instagram video / reel link anuppu")
                elif action == "YOUTUBE":
                    send_message(chat_id, "▶️ YouTube video link anuppu")
                elif action == "CASHFLOW":
                    send_message(chat_id, "💸 Cashflow – coming soon 😄")

                continue

            # ===== NORMAL MESSAGE =====
            if "message" not in update:
                continue

            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user = msg["from"]

            if "text" not in msg:
                continue

            text = msg["text"].strip()

            # ----- START -----
            if text == "/start":
                notify_owner(user)  # 👈 OWNER ONLY
                send_message(chat_id, f"👋 Hi {user.get('first_name','user')}")
                send_message(chat_id, "👇 Choose an option", main_menu())
                continue

            # ----- INSTAGRAM -----
            if "instagram.com" in text:
                send_message(chat_id, "⬇️ Downloading Instagram video...")
                output = f"ig_{chat_id}.mp4"
                try:
                    subprocess.run(["yt-dlp", "-o", output, text], check=True)
                    send_video(chat_id, output)
                    os.remove(output)
                except:
                    send_message(chat_id, "❌ Instagram download failed")
                continue

            # ----- YOUTUBE -----
            if "youtube.com" in text or "youtu.be" in text:
                send_message(chat_id, "🎥 YouTube download feature active (quality select next step)")
                continue

            send_message(chat_id, "❌ Please use /start and choose an option")

    time.sleep(2)

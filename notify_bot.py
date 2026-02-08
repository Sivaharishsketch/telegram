import requests
import time
import os
import subprocess
import json

BOT_TOKEN = "8272387883:AAEFAt7lMX0EjX6BvL9tVVETNXUkfhzASXE"
OWNER_ID = "609150604"

URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0

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

def send_main_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "📸 Instagram", "callback_data": "INSTAGRAM"}],
            [{"text": "▶️ YouTube", "callback_data": "YOUTUBE"}],
            [{"text": "💸 Cashflow", "callback_data": "CASHFLOW"}],
        ]
    }
    send_message(chat_id, "👇 Choose an option", keyboard)

def notify_owner(user):
    name = user.get("first_name", "")
    username = user.get("username", "N/A")
    user_id = user["id"]

    text = (
        "👤 New user using the bot\n\n"
        f"Name: {name}\n"
        f"Username: @{username}\n"
        f"User ID: {user_id}"
    )
    send_message(OWNER_ID, text)

while True:
    res = requests.get(f"{URL}/getUpdates?offset={last_update_id + 1}").json()

    if res.get("ok"):
        for update in res["result"]:
            last_update_id = update["update_id"]

            # ---------- CALLBACK (BUTTON CLICKS) ----------
            if "callback_query" in update:
                cb = update["callback_query"]
                chat_id = cb["message"]["chat"]["id"]
                action = cb["data"]

                if action == "INSTAGRAM":
                    send_message(chat_id, "📸 Instagram video/reel link anuppu")
                elif action == "YOUTUBE":
                    send_message(chat_id, "▶️ YouTube video link anuppu")
                elif action == "CASHFLOW":
                    send_message(chat_id, "💸 Cashflow – coming soon 😄")

                elif action.startswith("YT|"):
                    _, quality, url = action.split("|")
                    send_message(chat_id, f"⬇️ Downloading {quality}p video...")

                    output = f"yt_{chat_id}.mp4"
                    try:
                        subprocess.run(
                            ["yt-dlp", "-f", f"bestvideo[height<={quality}]+bestaudio/best", "-o", output, url],
                            check=True
                        )
                        send_video(chat_id, output)
                        os.remove(output)
                    except:
                        send_message(chat_id, "❌ YouTube download failed")

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

            # START
            if text == "/start":
                notify_owner(user)      # 👈 WHO is using
                send_main_menu(chat_id)
                continue

            # INSTAGRAM
            if "instagram.com" in text:
                send_message(chat_id, "⬇️ Downloading Instagram video...")
                output_file = f"ig_{chat_id}.mp4"
                try:
                    subprocess.run(
                        ["yt-dlp", "-o", output_file, text],
                        check=True
                    )
                    send_video(chat_id, output_file)
                    os.remove(output_file)
                except:
                    send_message(chat_id, "❌ Instagram download failed")
                continue

            # YOUTUBE
            if "youtube.com" in text or "youtu.be" in text:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "360p", "callback_data": f"YT|360|{text}"}],
                        [{"text": "720p", "callback_data": f"YT|720|{text}"}],
                        [{"text": "1080p", "callback_data": f"YT|1080|{text}"}],
                    ]
                }
                send_message(chat_id, "🎥 Choose video quality", keyboard)
                continue

            send_message(chat_id, "❌ Please choose option from /start menu")

    time.sleep(2)

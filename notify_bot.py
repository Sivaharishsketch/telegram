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

def get_youtube_qualities(url):
    result = subprocess.run(
        ["yt-dlp", "-J", url],
        capture_output=True,
        text=True
    )

    data = json.loads(result.stdout)
    formats = data.get("formats", [])

    qualities = {}
    for f in formats:
        if f.get("vcodec") != "none":
            height = f.get("height")
            fps = f.get("fps", 30)
            if height:
                key = f"{height}p{fps if fps > 30 else ''}"
                qualities[key] = height, fps

    return sorted(
        qualities.items(),
        key=lambda x: (x[1][0], x[1][1])
    )

while True:
    res = requests.get(f"{URL}/getUpdates?offset={last_update_id + 1}").json()

    if res.get("ok"):
        for update in res["result"]:
            last_update_id = update["update_id"]

            # ---------- CALLBACK ----------
            if "callback_query" in update:
                cb = update["callback_query"]
                chat_id = cb["message"]["chat"]["id"]
                action = cb["data"]

                if action.startswith("YT|"):
                    _, height, fps, url = action.split("|")
                    send_message(chat_id, f"⬇️ Downloading {height}p {fps}fps video...")

                    output = f"yt_{chat_id}.mp4"
                    try:
                        subprocess.run(
                            [
                                "yt-dlp",
                                "-f",
                                f"bestvideo[height<={height}][fps<={fps}]+bestaudio/best",
                                "-o",
                                output,
                                url
                            ],
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
                notify_owner(user)
                username = user.get("username", "")
                send_message(chat_id, f"👋 Hi @{username}")
                continue

            # INSTAGRAM
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

            # YOUTUBE
            if "youtube.com" in text or "youtu.be" in text:
                qualities = get_youtube_qualities(text)

                buttons = []
                for label, (h, fps) in qualities:
                    buttons.append(
                        [{"text": label, "callback_data": f"YT|{h}|{fps}|{text}"}]
                    )

                send_message(
                    chat_id,
                    "🎥 Available video qualities",
                    {"inline_keyboard": buttons}
                )
                continue

    time.sleep(2)

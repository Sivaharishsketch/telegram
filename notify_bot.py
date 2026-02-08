import requests
import time
import os
import subprocess

BOT_TOKEN = "8272387883:AAEFAt7lMX0EjX6BvL9tVVETNXUkfhzASXE"
URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

last_update_id = 0

def send_message(chat_id, text):
    requests.post(
        f"{URL}/sendMessage",
        data={"chat_id": chat_id, "text": text}
    )

def send_video(chat_id, file_path):
    with open(file_path, "rb") as video:
        requests.post(
            f"{URL}/sendVideo",
            data={"chat_id": chat_id},
            files={"video": video}
        )

while True:
    res = requests.get(f"{URL}/getUpdates?offset={last_update_id + 1}").json()

    if res.get("ok"):
        for update in res["result"]:
            last_update_id = update["update_id"]

            if "message" not in update:
                continue

            msg = update["message"]
            chat_id = msg["chat"]["id"]

            if "text" not in msg:
                continue

            text = msg["text"].strip()

            # START command
            if text == "/start":
                send_message(chat_id, "👋 Instagram video link anuppu, naa download pannuren 😄")
                continue

            # Instagram link check
            if "instagram.com" not in text:
                send_message(chat_id, "❌ Please send a valid Instagram video link")
                continue

            send_message(chat_id, "⬇️ Downloading video... Please wait")

            try:
                # Download video using yt-dlp
                output_file = f"ig_{chat_id}.mp4"
                subprocess.run(
                    ["yt-dlp", "-f", "mp4", "-o", output_file, text],
                    check=True
                )

                # Send video
                send_video(chat_id, output_file)

                # Cleanup
                os.remove(output_file)

            except Exception as e:
                send_message(chat_id, "❌ Failed to download video")

    time.sleep(2)

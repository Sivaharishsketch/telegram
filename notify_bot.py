import requests
import time
import os
import subprocess
import json
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials

BOT_TOKEN = "8272387883:AAEFAt7lMX0EjX6BvL9tVVETNXUkfhzASXE"
OWNER_ID = "609150604"
SHEET_ID = "1brwMcSQCSH5Ehl7PUQ8ys64BdR0bLfL5tD2tRGmpyU8"

URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
last_update_id = 0

# ---------- GOOGLE SHEET ----------
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gs_client = gspread.authorize(creds)
sheet = gs_client.open_by_key(SHEET_ID).worksheet("telegram")

def log_to_sheet(user, action, content):
    sheet.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user.get("first_name",""),
        user.get("username",""),
        user["id"],
        action,
        content
    ])

# ---------- TELEGRAM HELPERS ----------
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

# ---------- YOUTUBE ----------
def get_youtube_qualities(url):
    result = subprocess.run(["yt-dlp", "-J", url], capture_output=True, text=True)
    data = json.loads(result.stdout)
    formats = data.get("formats", [])

    seen = {}
    for f in formats:
        if f.get("vcodec") != "none" and f.get("height"):
            h = f["height"]
            fps = int(f.get("fps", 30))
            label = f"{h}p{fps if fps > 30 else ''}"
            seen[label] = (h, fps)

    return sorted(seen.items(), key=lambda x: (x[1][0], x[1][1]))

# ---------- MAIN LOOP ----------
while True:
    res = requests.get(f"{URL}/getUpdates?offset={last_update_id + 1}").json()

    if res.get("ok"):
        for update in res["result"]:
            last_update_id = update["update_id"]

            # ===== CALLBACK =====
            if "callback_query" in update:
                cb = update["callback_query"]
                chat_id = cb["message"]["chat"]["id"]
                action = cb["data"]

                if action == "INSTAGRAM":
                    send_message(chat_id, "📸 Instagram link anuppu")

                elif action == "YOUTUBE":
                    send_message(chat_id, "▶️ YouTube video link anuppu")

                elif action == "CASHFLOW":
                    send_message(chat_id, "💸 Cashflow – coming soon")

                elif action.startswith("YT|"):
                    _, h, fps, url = action.split("|")
                    send_message(chat_id, f"⬇️ Downloading {h}p {fps}fps...")

                    output = f"yt_{chat_id}.mp4"
                    try:
                        subprocess.run(
                            [
                                "yt-dlp",
                                "-f",
                                f"bestvideo[height<={h}][fps<={fps}][filesize_approx<1500M]+bestaudio/best",
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

            # ===== MESSAGE =====
            if "message" not in update:
                continue

            msg = update["message"]
            chat_id = msg["chat"]["id"]
            user = msg["from"]

            # FILE / FORWARD
            if "document" in msg or "video" in msg or "audio" in msg:
                file_obj = msg.get("document") or msg.get("video") or msg.get("audio")
                file_id = file_obj["file_id"]
                file_name = file_obj.get("file_name", "file")

                r = requests.get(f"{URL}/getFile", params={"file_id": file_id}).json()
                file_path = r["result"]["file_path"]
                download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

                send_message(chat_id, f"⬇️ Download link:\n{download_url}")
                log_to_sheet(user, "FILE", file_name)
                continue

            if "text" not in msg:
                continue

            text = msg["text"].strip()

            # START
            if text == "/start":
                notify_owner(user)
                send_message(chat_id, f"👋 Hi @{user.get('username','user')}")
                send_message(chat_id, "👇 Choose an option", main_menu())
                log_to_sheet(user, "START", "")
                continue

            # INSTAGRAM
            if "instagram.com" in text:
                send_message(chat_id, "⬇️ Downloading Instagram video...")
                output = f"ig_{chat_id}.mp4"
                try:
                    subprocess.run(["yt-dlp", "-o", output, text], check=True)
                    send_video(chat_id, output)
                    os.remove(output)
                    log_to_sheet(user, "INSTAGRAM", text)
                except:
                    send_message(chat_id, "❌ Instagram download failed")
                continue

            # YOUTUBE
            if "youtube.com" in text or "youtu.be" in text:
                qualities = get_youtube_qualities(text)
                buttons = [
                    [{"text": label, "callback_data": f"YT|{h}|{fps}|{text}"}]
                    for label, (h, fps) in qualities
                ]
                send_message(chat_id, "🎥 Available qualities", {"inline_keyboard": buttons})
                log_to_sheet(user, "YOUTUBE", text)
                continue

            send_message(chat_id, "❌ Use /start and choose an option")

    time.sleep(2)

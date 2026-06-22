import os
import json
import threading
import gspread
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from google.oauth2.service_account import Credentials

# ─────────────────────────────────────────────
# LOAD ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# Channel ID for bfi-summer-2026
STANDUP_CHANNEL_ID = "C0B7L91PYD7"

# ─────────────────────────────────────────────
# TINY WEB SERVER (keeps Render happy on free tier)
# ─────────────────────────────────────────────

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Standup bot is running!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ─────────────────────────────────────────────
# GOOGLE SHEETS SETUP
# ─────────────────────────────────────────────

def get_google_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if GOOGLE_CREDENTIALS_JSON:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
    return gspread.authorize(creds)

def get_sheet():
    client = get_google_client()
    return client.open_by_key(SPREADSHEET_ID).sheet1

def get_clients():
    """Reads the client list from the Config tab in Google Sheets."""
    try:
        client = get_google_client()
        config_sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Config")
        values = config_sheet.col_values(1)
        # Skip the header row and filter out empty cells
        clients = [v.strip() for v in values[1:] if v.strip()]
        return clients if clients else ["General BFI"]
    except Exception as e:
        print(f"Error reading clients from Config tab: {e}")
        return ["General BFI"]

def log_to_sheet(user_name, responses):
    sheet = get_sheet()
    row = [
        datetime.now().strftime("%Y-%m-%d"),
        user_name,
        responses.get("client", ""),
        responses.get("tasks_and_time", ""),
        responses.get("blockers", "")
    ]
    sheet.append_row(row)

# ─────────────────────────────────────────────
# BOT STATE
# ─────────────────────────────────────────────

user_sessions = {}

def build_client_question():
    clients = get_clients()
    client_list = "\n".join([f"{i+1}. {c}" for i, c in enumerate(clients)])
    return f"😸 Hello! Time for your daily standup.\n\n*Which client is this work for?*\n_If you worked on multiple clients today, complete this standup for each one — the bot will prompt you at the end!_\n\n{client_list}"

def build_another_client_question():
    clients = get_clients()
    client_list = "\n".join([f"{i+1}. {c}" for i, c in enumerate(clients)])
    return f"*Did you work on any other clients today?*\n\nType *no* if you're done, or pick another client:\n{client_list}"

QUESTIONS = [
    ("client",         None),  # built dynamically from sheet
    ("tasks_and_time", "*What tasks did you complete today and how long did you spend on each?*\n\nList each task on a new line:\n```Task name - 3h\nTask name - 45min```"),
    ("blockers",       "*Any blockers or anything you need help with?* (type 'none' if all good 👍)")
]

# ─────────────────────────────────────────────
# SLACK APP
# ─────────────────────────────────────────────

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)

def get_next_question(session):
    for key, text in QUESTIONS:
        if key not in session:
            return key, text
    return None, None

def parse_client(text):
    """Match a number or text to a client from the Config sheet."""
    clients = get_clients()
    text = text.strip()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(clients):
            return clients[index]
    for client in clients:
        if client.lower() in text.lower():
            return client
    return text

def start_standup(user_id, client):
    user_sessions[user_id] = {"awaiting_another_client": False}
    client.chat_postMessage(channel=user_id, text=build_client_question())

def trigger_channel_standups(client):
    response = client.conversations_members(channel=STANDUP_CHANNEL_ID)
    members = response["members"]
    for user_id in members:
        user_info = client.users_info(user=user_id)
        user = user_info["user"]
        if not user.get("is_bot") and not user.get("deleted") and user_id != "USLACKBOT":
            start_standup(user_id, client)

@app.message("")
def handle_dm(message, client, say):
    user_id = message["user"]
    text = message.get("text", "").strip()
    channel_type = message.get("channel_type", "")

    if channel_type != "im":
        return

    if user_id not in user_sessions:
        start_standup(user_id, client)
        return

    session = user_sessions[user_id]

    if session.get("awaiting_another_client"):
        if text.lower() in ["no", "nope", "n", "done", "no thanks"]:
            say("✅ All done! Thanks for your standups today, have a great rest of your day! 😺")
            del user_sessions[user_id]
        else:
            blockers = session.get("blockers", "none")
            user_sessions[user_id] = {
                "awaiting_another_client": False,
                "blockers": blockers
            }
            session = user_sessions[user_id]
            session["client"] = parse_client(text)
            say(QUESTIONS[1][1])
        return

    next_key, _ = get_next_question(session)

    if next_key is None:
        start_standup(user_id, client)
        return

    if next_key == "client":
        session["client"] = parse_client(text)
        # Ask the next question (tasks and time)
        say(QUESTIONS[1][1])
    else:
        session[next_key] = text
        next_key2, next_question = get_next_question(session)

        if next_question:
            say(next_question)
        else:
            user_info = client.users_info(user=user_id)
            user_name = user_info["user"]["real_name"]

            try:
                log_to_sheet(user_name, session)
                say(
                    f"✅ Logged!\n\n"
                    f"*Summary:*\n"
                    f"• *Client:* {session['client']}\n"
                    f"• *Tasks & Time:* {session['tasks_and_time']}\n"
                    f"• *Blockers:* {session['blockers']}"
                )
            except Exception as e:
                say(f"⚠️ Something went wrong logging to Google Sheets: {str(e)}")

            session["awaiting_another_client"] = True
            say(build_another_client_question())

@app.command("/standup")
def handle_standup_command(ack, body, client):
    ack()
    user_id = body["user_id"]
    start_standup(user_id, client)

@app.command("/standup-all")
def handle_standup_all_command(ack, body, client):
    ack()
    trigger_channel_standups(client)

# ─────────────────────────────────────────────
# SCHEDULER — 3:00pm Central Time (San Antonio) Mon-Fri
# ─────────────────────────────────────────────

def schedule_standups():
    import pytz
    import schedule
    import time
    from slack_sdk import WebClient

    sdk_client = WebClient(token=SLACK_BOT_TOKEN)
    central = pytz.timezone("America/Chicago")

    def check_and_trigger():
        now = datetime.now(central)
        if now.weekday() < 5 and now.hour == 15 and now.minute == 0:
            trigger_channel_standups(sdk_client)

    schedule.every().minute.do(check_and_trigger)

    while True:
        schedule.run_pending()
        time.sleep(60)

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    scheduler_thread = threading.Thread(target=schedule_standups, daemon=True)
    scheduler_thread.start()

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
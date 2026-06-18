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
# CLIENTS — add new clients here as needed
# ─────────────────────────────────────────────

CLIENTS = [
    "VIA",
    "SA Digital Connects (SADC)",
    "Future Workforce Summit",
    "General BFI",
    "Other"
]

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

def get_sheet():
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

    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

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
    client_list = "\n".join([f"{i+1}. {c}" for i, c in enumerate(CLIENTS)])
    return f"👋 Hey! Time for your daily standup.\n\n*Which client is this work for?*\n{client_list}"

def build_another_client_question():
    client_list = "\n".join([f"{i+1}. {c}" for i, c in enumerate(CLIENTS)])
    return f"*Did you work on any other clients today?*\n\nType *no* if you're done, or pick another client:\n{client_list}"

QUESTIONS = [
    ("client",         build_client_question()),
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
    text = text.strip()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(CLIENTS):
            return CLIENTS[index]
    for client in CLIENTS:
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

    # Handle "another client?" follow-up
    if session.get("awaiting_another_client"):
        if text.lower() in ["no", "nope", "n", "done", "no thanks"]:
            say("✅ All done! Thanks for your standups today, have a great rest of your day! 👋")
            del user_sessions[user_id]
        else:
            # They want to log another client — reset for a new entry but keep blockers
            blockers = session.get("blockers", "none")
            user_sessions[user_id] = {
                "awaiting_another_client": False,
                "blockers": blockers  # carry blockers over so we don't ask again
            }
            # Parse their client selection
            session = user_sessions[user_id]
            session["client"] = parse_client(text)
            say(QUESTIONS[1][1])  # ask tasks and time
        return

    next_key, _ = get_next_question(session)

    if next_key is None:
        start_standup(user_id, client)
        return

    if next_key == "client":
        session["client"] = parse_client(text)
    else:
        session[next_key] = text

    next_key2, next_question = get_next_question(session)

    if next_question:
        say(next_question)
    else:
        # All questions answered — log to sheet
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

        # Ask if they worked on another client
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
# SCHEDULER — DMs bfi-summer-2026 at 3pm Mon-Fri
# ─────────────────────────────────────────────

def schedule_standups():
    import schedule
    import time
    from slack_sdk import WebClient

    sdk_client = WebClient(token=SLACK_BOT_TOKEN)

    def trigger_all():
        trigger_channel_standups(sdk_client)

    schedule.every().monday.at("15:00").do(trigger_all)
    schedule.every().tuesday.at("15:00").do(trigger_all)
    schedule.every().wednesday.at("15:00").do(trigger_all)
    schedule.every().thursday.at("15:00").do(trigger_all)
    schedule.every().friday.at("15:00").do(trigger_all)

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
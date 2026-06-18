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
        responses.get("project", ""),
        responses.get("tasks", ""),
        responses.get("time", ""),
        responses.get("blockers", "")
    ]
    sheet.append_row(row)

# ─────────────────────────────────────────────
# BOT STATE
# ─────────────────────────────────────────────

user_sessions = {}

QUESTIONS = [
    ("project",  "👋 Hey! Time for your daily standup.\n\n*What project are you currently working on?*"),
    ("tasks",    "*What tasks did you complete today?* (list them out, one per line is great)"),
    ("time",     "*How long did you spend on each task?* (e.g. 'Bug fix — 2h, Code review — 1h')"),
    ("blockers", "*Any blockers or anything you need help with?* (type 'none' if all good 👍)")
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

def start_standup(user_id, client):
    user_sessions[user_id] = {}
    _, first_question = QUESTIONS[0]
    client.chat_postMessage(channel=user_id, text=first_question)

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
    next_key, _ = get_next_question(session)

    if next_key is None:
        start_standup(user_id, client)
        return

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
                f"✅ Got it, thanks {user_name.split()[0]}! Your standup has been logged.\n\n"
                f"*Summary:*\n"
                f"• *Project:* {session['project']}\n"
                f"• *Tasks:* {session['tasks']}\n"
                f"• *Time spent:* {session['time']}\n"
                f"• *Blockers:* {session['blockers']}"
            )
        except Exception as e:
            say(f"⚠️ Something went wrong logging to Google Sheets: {str(e)}")

        del user_sessions[user_id]

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
    # Run Flask in background thread (keeps Render free tier happy)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Run scheduler in background thread
    scheduler_thread = threading.Thread(target=schedule_standups, daemon=True)
    scheduler_thread.start()

    # Start the Slack bot
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
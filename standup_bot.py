import os
import gspread
from datetime import datetime
from dotenv import load_dotenv
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
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# ─────────────────────────────────────────────
# GOOGLE SHEETS SETUP
# ─────────────────────────────────────────────

def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=scopes)
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
# BOT STATE (tracks where each user is in the flow)
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

def trigger_all_standups(team_user_ids: list):
    from slack_sdk import WebClient
    client = WebClient(token=SLACK_BOT_TOKEN)
    for user_id in team_user_ids:
        start_standup(user_id, client)

# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
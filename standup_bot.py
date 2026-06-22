import os
import json
import threading
import gspread
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from google.oauth2.service_account import Credentials
import pytz

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

# Timezone
CENTRAL = pytz.timezone("America/Chicago")

# ─────────────────────────────────────────────
# WORKDAY DATE LOGIC
# 12pm today to 11:59am tomorrow = same workday
# ─────────────────────────────────────────────

def get_workday_date():
    now = datetime.now(CENTRAL)
    if now.hour < 12:
        workday = now - timedelta(days=1)
    else:
        workday = now
    return workday.strftime("%Y-%m-%d")

# ─────────────────────────────────────────────
# TINY WEB SERVER (keeps Render happy on free tier)
# ─────────────────────────────────────────────

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "BRIEFI is running!", 200

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
    try:
        client = get_google_client()
        config_sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Config")
        values = config_sheet.col_values(1)
        clients = [v.strip() for v in values[1:] if v.strip()]
        return clients if clients else ["General BFI"]
    except Exception as e:
        print(f"Error reading clients from Config tab: {e}")
        return ["General BFI"]

def log_to_sheet(user_name, responses):
    sheet = get_sheet()
    row = [
        get_workday_date(),
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

RESTART_KEYWORDS = ["restart", "start over", "reset", "redo", "begin again"]

def build_welcome_message():
    clients = get_clients()
    client_list = "\n".join([f"{i+1}. {c}" for i, c in enumerate(clients)])
    return (
        "😸 Hi! I'm *BRIEFI*, the Better Futures Institute's daily standup bot.\n\n"
        "I'll walk you through *3 quick questions* about your work today.\n\n"
        "If you worked on *multiple clients* today, I'll ask you to complete a standup for each one — I'll prompt you at the end.\n\n"
        "Made a mistake? Type *restart* at any time to start over.\n\n"
        "You have until *12pm tomorrow* to complete today's standup.\n\n"
        "─────────────────────\n\n"
        "*Question 1 of 3 — Which client did you work on today?*\n"
        "Reply with the number next to your client:\n\n"
        f"{client_list}"
    )

def build_another_client_question():
    clients = get_clients()
    client_list = "\n".join([f"{i+1}. {c}" for i, c in enumerate(clients)])
    return (
        "*Did you work on any other clients today?*\n\n"
        "Type *NO* if you are all done.\n"
        "Or reply with the number of the next client:\n\n"
        f"{client_list}"
    )

def build_task_modal(num_tasks=1, existing_tasks=None, private_metadata=""):
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Enter each task you completed today and how long it took.*\n\nUse the *Add Task* button at the bottom to add more rows. When you are done, click *Submit*."
            }
        },
        {"type": "divider"}
    ]

    for i in range(num_tasks):
        task_val = ""
        time_val = ""
        if existing_tasks and i < len(existing_tasks):
            task_val = existing_tasks[i].get("task", "")
            time_val = existing_tasks[i].get("time", "")

        blocks.append({
            "type": "input",
            "block_id": f"task_block_{i}",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": f"task_input_{i}",
                "placeholder": {"type": "plain_text", "text": "e.g. Updated client report"},
                "initial_value": task_val
            },
            "label": {"type": "plain_text", "text": f"Task {i+1}"}
        })
        blocks.append({
            "type": "input",
            "block_id": f"time_block_{i}",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": f"time_input_{i}",
                "placeholder": {"type": "plain_text", "text": "e.g. 2h or 45min"},
                "initial_value": time_val
            },
            "label": {"type": "plain_text", "text": f"Time spent on Task {i+1}"}
        })
        blocks.append({"type": "divider"})

    blocks.append({
        "type": "actions",
        "block_id": "add_task_block",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "+ Add Another Task"},
                "action_id": "add_task_button",
                "value": str(num_tasks)
            }
        ]
    })

    return {
        "type": "modal",
        "callback_id": "task_modal",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Today's Tasks"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks
    }

# ─────────────────────────────────────────────
# SLACK APP
# ─────────────────────────────────────────────

app = App(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)

def get_next_question(session):
    questions = ["client", "tasks_and_time", "blockers"]
    for key in questions:
        if key not in session:
            return key
    return None

def parse_client(text):
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
    client.chat_postMessage(channel=user_id, text=build_welcome_message())

def trigger_channel_standups(client):
    response = client.conversations_members(channel=STANDUP_CHANNEL_ID)
    members = response["members"]
    for user_id in members:
        user_info = client.users_info(user=user_id)
        user = user_info["user"]
        if not user.get("is_bot") and not user.get("deleted") and user_id != "USLACKBOT":
            start_standup(user_id, client)

def open_task_modal(client, trigger_id, user_id, num_tasks=1, existing_tasks=None):
    metadata = json.dumps({"user_id": user_id, "num_tasks": num_tasks})
    client.views_open(
        trigger_id=trigger_id,
        view=build_task_modal(num_tasks, existing_tasks, private_metadata=metadata)
    )

def send_task_button(say):
    say(
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Question 2 of 3 — What tasks did you complete today?*\n\nClick the button below to open the task form. You can log as many tasks as you need."
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Enter Tasks"},
                        "action_id": "open_task_modal_button",
                        "style": "primary"
                    }
                ]
            }
        ],
        text="Click the button below to log your tasks."
    )

@app.message("")
def handle_dm(message, client, say):
    user_id = message["user"]
    text = message.get("text", "").strip()
    channel_type = message.get("channel_type", "")

    if channel_type != "im":
        return

    # Handle restart at any point
    if text.lower() in RESTART_KEYWORDS:
        user_sessions[user_id] = {"awaiting_another_client": False}
        say("😼 No problem! Let's start over.\n\n" + build_welcome_message())
        return

    if user_id not in user_sessions:
        start_standup(user_id, client)
        return

    session = user_sessions[user_id]

    # Handle "another client?" follow-up
    if session.get("awaiting_another_client"):
        if text.lower() in ["no", "nope", "n", "done", "no thanks"]:
            say(
                "😺 All done! Your standup has been logged for today.\n\n"
                "See you tomorrow!"
            )
            del user_sessions[user_id]
        else:
            blockers = session.get("blockers", "none")
            user_sessions[user_id] = {
                "awaiting_another_client": False,
                "blockers": blockers
            }
            session = user_sessions[user_id]
            session["client"] = parse_client(text)
            session["tasks_and_time"] = "__PENDING__"
            session["awaiting_task_modal"] = True
            send_task_button(say)
        return

    next_key = get_next_question(session)

    if next_key is None:
        start_standup(user_id, client)
        return

    if next_key == "client":
        session["client"] = parse_client(text)
        session["tasks_and_time"] = "__PENDING__"
        session["awaiting_task_modal"] = True
        send_task_button(say)

    elif next_key == "blockers":
        session["blockers"] = text

        user_info = client.users_info(user=user_id)
        user_name = user_info["user"]["real_name"]

        try:
            log_to_sheet(user_name, session)
            say(
                f"Logged! Here is your summary:\n\n"
                f"*Client:* {session['client']}\n"
                f"*Tasks & Time:*\n{session['tasks_and_time']}\n"
                f"*Blockers:* {session['blockers']}\n\n"
                f"Logged for workday: *{get_workday_date()}*"
            )
        except Exception as e:
            say(f"Something went wrong logging to Google Sheets: {str(e)}")

        session["awaiting_another_client"] = True
        say(build_another_client_question())

@app.action("open_task_modal_button")
def handle_open_modal_button(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    trigger_id = body["trigger_id"]
    open_task_modal(client, trigger_id, user_id)

@app.action("add_task_button")
def handle_add_task(ack, body, client):
    ack()
    current_view = body["view"]
    metadata = json.loads(current_view.get("private_metadata", "{}"))
    num_tasks = int(body["actions"][0]["value"]) + 1

    existing_tasks = []
    state_values = current_view["state"]["values"]
    for i in range(num_tasks - 1):
        task_val = state_values.get(f"task_block_{i}", {}).get(f"task_input_{i}", {}).get("value", "") or ""
        time_val = state_values.get(f"time_block_{i}", {}).get(f"time_input_{i}", {}).get("value", "") or ""
        existing_tasks.append({"task": task_val, "time": time_val})

    metadata["num_tasks"] = num_tasks
    client.views_update(
        view_id=current_view["id"],
        view=build_task_modal(num_tasks, existing_tasks, private_metadata=json.dumps(metadata))
    )

@app.view("task_modal")
def handle_task_submission(ack, body, client, view):
    ack()
    user_id = body["user"]["id"]
    metadata = json.loads(view.get("private_metadata", "{}"))
    num_tasks = metadata.get("num_tasks", 1)
    state_values = view["state"]["values"]

    task_lines = []
    for i in range(num_tasks):
        task_val = state_values.get(f"task_block_{i}", {}).get(f"task_input_{i}", {}).get("value", "") or ""
        time_val = state_values.get(f"time_block_{i}", {}).get(f"time_input_{i}", {}).get("value", "") or ""
        if task_val.strip():
            if time_val.strip():
                task_lines.append(f"{task_val.strip()} - {time_val.strip()}")
            else:
                task_lines.append(task_val.strip())

    tasks_and_time = "\n".join(task_lines) if task_lines else "No tasks entered"

    if user_id in user_sessions:
        session = user_sessions[user_id]
        session["tasks_and_time"] = tasks_and_time
        session.pop("awaiting_task_modal", None)

        # Ask blockers next
        client.chat_postMessage(
            channel=user_id,
            text=(
                "*Question 3 of 3 — Any blockers or anything you need help with?*\n\n"
                "A blocker is anything stopping you from making progress — a missing resource, a decision that needs to be made, or something you need from someone else.\n\n"
                "Type *none* if everything is on track."
            )
        )

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
    import schedule
    import time
    from slack_sdk import WebClient

    sdk_client = WebClient(token=SLACK_BOT_TOKEN)

    def check_and_trigger():
        now = datetime.now(CENTRAL)
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
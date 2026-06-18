# Slack Standup Bot

A Slack bot that conducts daily standups with each team member via DM and logs their responses to a Google Sheet automatically.

## What It Does

The bot walks each team member through 4 questions:

1. What project are you currently working on?
2. What tasks did you complete today?
3. How long did you spend on each task?
4. Any blockers or anything you need help with?

Once they answer all four, the bot sends a summary back to the user and logs a new row to a shared Google Sheet.

## How to Trigger a Standup

Team members have two options:
- **DM the bot directly** — it will start the flow automatically
- **Type `/standup`** in any channel

## Project Structure

```
standup-bot/
├── standup_bot.py       # Main bot code
├── requirements.txt     # Python dependencies
├── .env                 # Secret tokens (not pushed to GitHub)
├── .gitignore           # Keeps secrets out of Git
└── credentials.json     # Google service account key (not pushed to GitHub)
```

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/victoriamjohnson/standup-bot.git
cd standup-bot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create a Slack App

- Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
- Under **OAuth & Permissions**, add these bot token scopes:
  - `chat:write`
  - `im:write`
  - `im:read`
  - `im:history`
  - `users:read`
  - `channels:read`
- Under **App Home**, enable the Messages tab
- Under **Settings → Socket Mode**, enable Socket Mode
- Under **Basic Information → App-Level Tokens**, generate a token with the `connections:write` scope
- Install the app to your workspace

### 4. Set up Google Sheets

- Create a Google Cloud project and enable the **Google Sheets API** and **Google Drive API**
- Create a service account and download the JSON credentials file
- Rename it to `credentials.json` and place it in the project folder
- Create a new Google Sheet with these headers in row 1:
  `Date | Name | Project | Tasks Completed | Time Spent | Blockers`
- Share the sheet with the service account email (found in `credentials.json` under `client_email`)

### 5. Configure environment variables

Create a `.env` file in the project root:

```
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_APP_TOKEN=xapp-your-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
GOOGLE_CREDENTIALS_FILE=credentials.json
SPREADSHEET_ID=your-spreadsheet-id-here
```

### 6. Run the bot

```bash
python standup_bot.py
```

You should see `⚡️ Bolt app is running!` in the terminal when it's live.

## Google Sheet Output

Each standup response is logged as a new row:

| Date | Name | Project | Tasks Completed | Time Spent | Blockers |
|------|------|---------|----------------|------------|---------|
| 2026-06-18 | Alex Johnson | Website redesign | Fixed nav bug, wrote tests | Bug fix — 2h, Tests — 1h | None |

## Tech Stack

- [Slack Bolt for Python](https://slack.dev/bolt-python/)
- [gspread](https://docs.gspread.org/)
- [Google Auth](https://google-auth.readthedocs.io/)
- [python-dotenv](https://pypi.org/project/python-dotenv/)
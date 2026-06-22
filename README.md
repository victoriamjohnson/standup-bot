<img src="slack_pfp.jpg" alt="BRIEFI" width="50" align="left" style="margin-right: 12px;"/>

# BRIEFI — BFI Daily Standup Bot

BRIEFI is a Slack bot built for the Better Futures Institute that conducts daily standups with each team member via DM and automatically logs their responses to a shared Google Sheet. Project managers can track hours per client, flag missing time entries, and monitor team progress — all without leaving Google Sheets.

---

## What It Does

At 3:00pm Central Time every Monday through Friday, BRIEFI automatically DMs every member of the `bfi-summer-2026` Slack channel and walks them through a quick standup:

1. **Which client is this work for?** — pulled live from the Config tab in Google Sheets
2. **What tasks did you complete today and how long did you spend on each?**
3. **Any blockers or anything you need help with?**

After logging, BRIEFI asks if they worked on any other clients and loops through the standup again if needed. Every response is logged as a new row in the Google Sheet.

---

## Features

- Daily standup DMs sent automatically at 3:00pm Central Time (Monday through Friday)
- Multi-client support — loops through standup for each client worked on
- Client list managed directly in Google Sheets — no code changes needed to add or remove clients
- Missing time entries flagged automatically for the project manager to follow up
- Summary tab with hours per client broken down by today, this week, and total
- `/standup` command for individuals to trigger their own standup anytime
- `/standup-all` command to manually trigger standups for the whole channel
- Hosted on Render with UptimeRobot keeping it live 24/7 on the free tier

---

## Slack Commands

| Command | Description |
|--------|-------------|
| `/standup` | Start your own standup anytime |
| `/standup-all` | Trigger standups for all members of your standup channel |

---

## Project Structure

```
standup-bot/
├── standup_bot.py       # Main bot code
├── requirements.txt     # Python dependencies
├── .env                 # Secret tokens (not pushed to GitHub)
├── .gitignore           # Keeps secrets out of Git
└── credentials.json     # Google service account key (not pushed to GitHub)
```

---

## Google Sheet Setup

The bot uses a single Google Sheet with four tabs: **Sheet1**, **Parsed**, **Summary**, and **Config**.

### Sheet1 — Main Data

This is where all standup responses are logged. Set up these headers in row 1:

```
Date | Name | Client | Tasks & Time | Blockers | Flag
```

The **Flag** column (F) automatically marks any entry missing a time value. Paste this formula in F2 and drag it down:

```
=IF(D2="","",IF(REGEXMATCH(D2,"[0-9]+(h|min)"),"","⚠️ Missing time"))
```

### Parsed — Time Conversion

This tab converts time entries like "3h" and "45min" into decimal hours for calculations. Set up three columns with these headers: `Date | Name | Hours`

In A2:
```
=ARRAYFORMULA(IF(Sheet1!A2:A="","",Sheet1!A2:A))
```

In B2:
```
=ARRAYFORMULA(IF(Sheet1!B2:B="","",Sheet1!B2:B))
```

In C2 (converts all time formats to decimal hours):
```
=ARRAYFORMULA(IF(Sheet1!E2:E="","", IFERROR(SUMPRODUCT((IFERROR(REGEXEXTRACT(TRIM(SPLIT(Sheet1!E2:E,CHAR(10))),"([0-9]+)h")*1,0))+ (IFERROR(REGEXEXTRACT(TRIM(SPLIT(Sheet1!E2:E,CHAR(10))),"([0-9]+)min")/60,0))),0)))
```

### Summary — Hours by Client

This is the project manager's view. Set up these headers in row 1:

```
Client | Hours Today | Hours This Week | Total Hours
```

In A2 (pulls unique clients automatically):
```
=UNIQUE(Sheet1!C2:C)
```

In B2 (hours today):
```
=SUMPRODUCT((Sheet1!C$2:Sheet1!C$1000=A2)*(TEXT(Sheet1!A$2:Sheet1!A$1000,"YYYY-MM-DD")=TEXT(TODAY(),"YYYY-MM-DD"))*(IFERROR(REGEXEXTRACT(Sheet1!D$2:Sheet1!D$1000,"([0-9]+)h")*1,0))+(IFERROR(REGEXEXTRACT(Sheet1!D$2:Sheet1!D$1000,"([0-9]+)min")/60,0))*(Sheet1!C$2:Sheet1!C$1000=A2)*(TEXT(Sheet1!A$2:Sheet1!A$1000,"YYYY-MM-DD")=TEXT(TODAY(),"YYYY-MM-DD")))
```

In C2 (hours this week):
```
=SUMPRODUCT((Sheet1!C$2:Sheet1!C$1000=A2)*(WEEKNUM(Sheet1!A$2:Sheet1!A$1000)=WEEKNUM(TODAY()))*(IFERROR(REGEXEXTRACT(Sheet1!D$2:Sheet1!D$1000,"([0-9]+)h")*1,0))+(IFERROR(REGEXEXTRACT(Sheet1!D$2:Sheet1!D$1000,"([0-9]+)min")/60,0))*(Sheet1!C$2:Sheet1!C$1000=A2))
```

In D2 (total hours):
```
=SUMPRODUCT((Sheet1!C$2:Sheet1!C$1000=A2)*(IFERROR(REGEXEXTRACT(Sheet1!D$2:Sheet1!D$1000,"([0-9]+)h")*1,0))+(IFERROR(REGEXEXTRACT(Sheet1!D$2:Sheet1!D$1000,"([0-9]+)min")/60,0))*(Sheet1!C$2:Sheet1!C$1000=A2))
```

Drag all three formulas down for as many rows as you have clients. Format columns B, C, and D as `0.00` for 2 decimal places: **Format → Number → Custom number format → type `0.00`**

### Config — Client List

This is where the project manager manages the client list. The bot reads from this tab live — no redeployment needed when clients change.

Set up one column:

```
A1: Clients
A2: Client 1
A3: Client 2
A4: Client 3
A5: Client 4
A6: Other
```

To **add a client** — type it in the next empty row under the list.
To **remove a client** — delete the row.
To **rename a client** — edit the cell directly.

Changes take effect on the next standup automatically.

---

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
  - `groups:read`
- Under **App Home**, enable the Messages tab
- Under **Settings → Socket Mode**, enable Socket Mode
- Under **Basic Information → App-Level Tokens**, generate a token with the `connections:write` scope
- Under **Slash Commands**, add `/standup` and `/standup-all`
- Install the app to your workspace and invite it to your standup channel

### 4. Set up Google Sheets

- Create a Google Cloud project and enable the **Google Sheets API** and **Google Drive API**
- Create a service account and download the JSON credentials file
- Rename it to `credentials.json` and place it in the project folder
- Create your Google Sheet and set up the four tabs as described above
- Share the sheet with the service account email found in `credentials.json` under `client_email` as an Editor

### 5. Configure environment variables

Create a `.env` file in the project root:

```
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_APP_TOKEN=xapp-your-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
GOOGLE_CREDENTIALS_FILE=credentials.json
SPREADSHEET_ID=your-spreadsheet-id-here
```

### 6. Run locally

```bash
python standup_bot.py
```

You should see `⚡️ Bolt app is running!` in the terminal.

---

## Deployment (Render)

The bot is hosted on Render as a Web Service on the free tier, with UptimeRobot pinging it every 5 minutes to prevent spin-down.

When deploying to Render, add these environment variables in the Render dashboard instead of a `.env` file:

```
SLACK_BOT_TOKEN
SLACK_APP_TOKEN
SLACK_SIGNING_SECRET
SPREADSHEET_ID
GOOGLE_CREDENTIALS_JSON  ← paste the full contents of credentials.json here
```

Set the build command to `pip install -r requirements.txt` and the start command to `python standup_bot.py`.

To keep the free tier awake, create a free account at [uptimerobot.com](https://uptimerobot.com) and add an HTTP monitor pointing to your Render URL set to ping every 5 minutes.

---

## Using This for Your Own Organization

This bot is built to be reused! If you want to set it up for your own team outside of BFI, here are the only things you need to change:

### 1. Update the Slack channel

In `standup_bot.py`, find this line near the top:

```python
STANDUP_CHANNEL_ID = "C0B7L91PYD7"
```

Replace it with your own channel ID. To find it, open your Slack channel, click the channel name at the top, and scroll to the bottom of the details panel — it starts with a `C`.

### 2. Update the standup time

Find this line in the scheduler:

```python
if now.weekday() < 5 and now.hour == 15 and now.minute == 0:
```

Change `15` (hour) and `0` (minute) to whatever time you want in 24-hour format. For example, 9:30am would be `now.hour == 9 and now.minute == 30`.

### 3. Update the timezone

Find this line:

```python
central = pytz.timezone("America/Chicago")
```

Replace `"America/Chicago"` with your timezone. Common options:
- `"America/New_York"` — Eastern
- `"America/Chicago"` — Central
- `"America/Denver"` — Mountain
- `"America/Los_Angeles"` — Pacific
- `"Europe/London"` — GMT/BST
- Full list at [en.wikipedia.org/wiki/List_of_tz_database_time_zones](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)

### 4. Update your client list

Go to the `Config` tab in your Google Sheet and replace the existing clients with your own. The bot picks them up automatically — no code changes needed.

### 5. Rename the bot

Go to [api.slack.com/apps](https://api.slack.com/apps), select your app, go to **Basic Information → Display Information**, and give it whatever name fits your organization.

That's it — everything else works out of the box!

---

## Tech Stack

- [Slack Bolt for Python](https://slack.dev/bolt-python/)
- [gspread](https://docs.gspread.org/)
- [Google Auth](https://google-auth.readthedocs.io/)
- [Flask](https://flask.palletsprojects.com/)
- [python-dotenv](https://pypi.org/project/python-dotenv/)
- [schedule](https://pypi.org/project/schedule/)
- [pytz](https://pypi.org/project/pytz/)
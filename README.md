# 🌾 Shetkari Journal Bot

Telegram bot for Marathwada farmers to track crop expenses in Marathi.
Logs to Google Sheets, saves bill photos to Google Drive.

**Crops tracked:** Cotton 🌿 · Soybean 🫘 · Haldi 🟡 · Wheat 🌾

## Quick Start

### 1. Clone & install
```bash
git clone https://github.com/YOUR_USERNAME/shetkari-journal.git
cd shetkari-journal
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Run locally (dev)
```bash
# Install ngrok for local webhook testing
ngrok http 8000

# In another terminal
python main.py
```

### 4. Deploy to Render
- Push to GitHub
- Connect repo on render.com → New Web Service
- Set all env vars (see .env.example)
- Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

## Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `ALLOWED_CHAT_ID` | Your Telegram numeric ID (security) |
| `OPENAI_API_KEY` | From platform.openai.com |
| `GOOGLE_SHEET_ID` | Google Sheet URL ID |
| `GOOGLE_DRIVE_ROOT_FOLDER_ID` | Drive folder URL ID |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full JSON string of service account key |
| `WEBHOOK_URL` | Your Render app URL |

## Bot Commands

| Message | Action |
|---|---|
| Any Marathi/Hindi expense text | Logs expense |
| Bill photo | Extracts data + saves to Drive |
| Voice note | Transcribes + logs |
| आजचा हिशोब | Today's summary |
| महिन्याचा हिशोब | Month summary |
| season summary / report | Full P&L |
| /help | Help in Marathi |

## Cost
~₹80/month (OpenAI API only). Everything else is free.

## Google Sheet Structure
`Date | Season | Crop | Category | Description | Amount | Type | Payment | Bill_Link | Notes`

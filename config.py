import os
import json
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID")  # Optional, single user security

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_DRIVE_ROOT_FOLDER_ID = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID")

# Service account JSON can be stored as env var string or file path
_sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
if _sa_json.startswith("{"):
    SERVICE_ACCOUNT_INFO = json.loads(_sa_json)
else:
    # treat as file path
    with open(_sa_json) as f:
        SERVICE_ACCOUNT_INFO = json.load(f)

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PORT = int(os.getenv("PORT", 8000))

# Season detection
from datetime import date

def get_current_season():
    today = date.today()
    m = today.month
    y = today.year
    if 6 <= m <= 10:
        return f"Kharif-{y}"
    else:
        # Rabi spans Nov-May; year label is the start year
        return f"Rabi-{y if m >= 11 else y - 1}"

# Crop keywords for auto-detection
CROP_KEYWORDS = {
    "Cotton":   ["cotton", "कापूस", "kapus", "miyus", "miyush", "bt"],
    "Soybean":  ["soy", "सोयाबीन", "soybean", "soya"],
    "Haldi":    ["haldi", "हळद", "turmeric"],
    "Wheat":    ["wheat", "गहू", "gahu"],
}

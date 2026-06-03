"""
bot_handlers.py
Route incoming Telegram messages by type: text, photo, voice.
"""

import logging
import httpx
from datetime import date

from telegram import Update, Bot
from telegram.ext import ContextTypes

from config import TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, get_current_season
from gpt_parser import parse_expense_text
from vision_parser import parse_bill_image
from whisper_handler import transcribe_voice
from sheets_client import append_expense
from drive_client import upload_image
import summary as sm

logger = logging.getLogger(__name__)

# Temp store for pending photo entries (waiting for amount confirmation)
_pending_photo: dict = {}

SUMMARY_KEYWORDS = [
    "आजचा", "महिन्याचा", "हिशोब", "खर्च किती", "उत्पन्न किती",
    "report", "summary", "total", "एकूण", "सीझन", "season",
]

HELP_TEXT = """🌾 *शेतकरी जर्नल बॉट*

*खर्च नोंदवा:*
टाइप करा: "आज खत घेतली 2 बॅग ₹850"
आवाज पाठवा: व्हॉइस नोट
बिल फोटो: फोटो पाठवा

*अहवाल:*
• आजचा हिशोब
• महिन्याचा हिशोब  
• सीझन summary
• एकूण किती

*पीके:* कापूस 🌿 | सोयाबीन 🫘 | हळद 🟡 | गहू 🌾"""


def _is_authorized(chat_id: int) -> bool:
    if not ALLOWED_CHAT_ID:
        return True  # No restriction set
    return str(chat_id) == str(ALLOWED_CHAT_ID)


def _detect_summary_intent(text: str) -> str | None:
    """Return summary type if message is a summary request."""
    lower = text.lower()
    if any(kw in lower for kw in ["आजचा", "today", "aaj"]):
        return "today"
    if any(kw in lower for kw in ["महिन्याचा", "month", "mahina"]):
        return "month"
    if any(kw in lower for kw in ["सीझन", "season", "एकूण", "total", "report", "summary"]):
        return "season"
    if any(kw in lower for kw in SUMMARY_KEYWORDS):
        return "running"
    return None


async def _download_file(bot: Bot, file_id: str) -> bytes:
    """Download a Telegram file by file_id and return bytes."""
    tg_file = await bot.get_file(file_id)
    async with httpx.AsyncClient() as client:
        response = await client.get(tg_file.file_path)
        return response.content


async def _log_and_reply(bot: Bot, chat_id: int, row: dict, extra_msg: str = "") -> None:
    """Append row to Sheets and send confirmation reply."""
    success = append_expense(row)
    if success:
        t = row.get("type", "expense")
        cat = row.get("category", "")
        amt = row.get("amount", 0)
        desc = row.get("description", "")
        crop = row.get("crop", "")
        payment = f" | {row.get('payment')}" if row.get("payment") else ""

        icon = "✅" if t == "expense" else "💰"
        crop_tag = f" ({crop})" if crop and crop != "General" else ""

        msg = f"{icon} नोंद झाली!{crop_tag}\n{cat}: ₹{int(float(amt)):,}\n📝 {desc}{payment}"
        if extra_msg:
            msg += f"\n{extra_msg}"
    else:
        msg = "❌ नोंद झाली नाही, पुन्हा पाठवा"

    await bot.send_message(chat_id=chat_id, text=msg)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    chat_id = update.effective_chat.id
    text = update.message.text or ""

    if not _is_authorized(chat_id):
        return

    # Help command
    if text.strip().lower() in ["/start", "/help", "help", "मदत"]:
        await bot.send_message(chat_id=chat_id, text=HELP_TEXT, parse_mode="Markdown")
        return

    # Check if user is responding with amount for a pending photo
    if chat_id in _pending_photo:
        pending = _pending_photo.pop(chat_id)
        try:
            amount = float(text.replace("₹", "").replace(",", "").strip())
            pending["amount"] = amount
            pending["description"] = pending.get("description") or "Bill (amount added manually)"
            await _log_and_reply(bot, chat_id, pending)
        except ValueError:
            await bot.send_message(chat_id=chat_id, text="❌ फक्त नंबर पाठवा (उदा: 850)")
        return

    # Check for summary intent
    summary_type = _detect_summary_intent(text)
    if summary_type:
        if summary_type == "today":
            msg = sm.today_summary()
        elif summary_type == "month":
            msg = sm.month_summary()
        elif summary_type == "season":
            msg = sm.season_summary()
        else:
            msg = sm.running_total()
        await bot.send_message(chat_id=chat_id, text=msg)
        return

    # Parse as expense
    await bot.send_chat_action(chat_id=chat_id, action="typing")
    parsed = parse_expense_text(text)

    if not parsed or not parsed.get("amount"):
        await bot.send_message(
            chat_id=chat_id,
            text="समजले नाही 🙏\nउदाहरण: 'आज DAP 2 बॅग घेतल्या ₹1200'\nकिंवा /help टाइप करा"
        )
        return

    parsed["season"] = parsed.get("season") or get_current_season()
    parsed["date"] = parsed.get("date") or date.today().strftime("%d-%m-%Y")
    await _log_and_reply(bot, chat_id, parsed)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    chat_id = update.effective_chat.id

    if not _is_authorized(chat_id):
        return

    await bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    # Get highest quality photo
    photo = update.message.photo[-1]
    image_bytes = await _download_file(bot, photo.file_id)

    # Get caption if any
    caption = update.message.caption or ""

    season = get_current_season()

    # Upload to Drive first (always save the bill)
    drive_link = upload_image(image_bytes, season)

    # Parse bill with Vision
    vision_data = parse_bill_image(image_bytes)

    if not vision_data or vision_data.get("error") == "not_a_bill":
        # Not a recognizable bill — save to Drive and ask for details
        if drive_link:
            _pending_photo[chat_id] = {
                "date": date.today().strftime("%d-%m-%Y"),
                "season": season,
                "crop": "General",
                "category": "Other",
                "description": "फोटो बिल",
                "type": "expense",
                "payment": "",
                "bill_link": drive_link,
                "notes": caption,
            }
            await bot.send_message(
                chat_id=chat_id,
                text=f"📸 फोटो Drive मध्ये सेव्ह झाला!\nरक्कम किती होती? (फक्त नंबर पाठवा)\n📎 {drive_link}"
            )
        else:
            await bot.send_message(chat_id=chat_id, text="❌ फोटो सेव्ह झाला नाही, पुन्हा प्रयत्न करा")
        return

    # Build row from vision data
    row = {
        "date": vision_data.get("date") or date.today().strftime("%d-%m-%Y"),
        "season": season,
        "crop": vision_data.get("crop") or "General",
        "category": vision_data.get("category") or "Other",
        "description": vision_data.get("items") or vision_data.get("shop_name") or "Bill",
        "amount": vision_data.get("amount") or 0,
        "type": "expense",
        "payment": vision_data.get("payment") or "",
        "bill_link": drive_link,
        "notes": f"Shop: {vision_data.get('shop_name', '')} | {caption}".strip(" |"),
    }

    # If amount couldn't be extracted, ask user
    if not row["amount"]:
        _pending_photo[chat_id] = row
        shop = vision_data.get("shop_name", "")
        items = vision_data.get("items", "")
        shop_info = f"🏪 {shop}\n📦 {items}" if shop else f"📦 {items}"
        await bot.send_message(
            chat_id=chat_id,
            text=f"📸 बिल सेव्ह झाले!\n{shop_info}\n💭 रक्कम दिसली नाही — किती होती? (फक्त नंबर)"
        )
        return

    await _log_and_reply(
        bot, chat_id, row,
        extra_msg=f"📎 बिल पाहा: {drive_link}" if drive_link else ""
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot
    chat_id = update.effective_chat.id

    if not _is_authorized(chat_id):
        return

    await bot.send_chat_action(chat_id=chat_id, action="typing")

    voice = update.message.voice
    audio_bytes = await _download_file(bot, voice.file_id)

    # Transcribe
    transcript = await transcribe_voice(audio_bytes)
    if not transcript:
        await bot.send_message(chat_id=chat_id, text="❌ आवाज ऐकू आला नाही, पुन्हा पाठवा")
        return

    # Parse transcribed text
    parsed = parse_expense_text(transcript)
    if not parsed or not parsed.get("amount"):
        await bot.send_message(
            chat_id=chat_id,
            text=f'🎤 ऐकले: "{transcript}"\n\n❓ समजले नाही, पुन्हा सांगा'
        )
        return

    parsed["season"] = parsed.get("season") or get_current_season()
    parsed["date"] = parsed.get("date") or date.today().strftime("%d-%m-%Y")
    parsed["notes"] = f'Voice: "{transcript}"'

    await _log_and_reply(
        bot, chat_id, parsed,
        extra_msg=f'🎤 "{transcript}"'
    )

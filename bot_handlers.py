"""
bot_handlers.py
Route incoming Telegram messages by type: text, photo, voice.
"""

import logging
import httpx
from datetime import date

from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from config import TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_ID, get_current_season
from gpt_parser import parse_expense_text
from vision_parser import parse_bill_image
from whisper_handler import transcribe_voice
from supabase_client import (
    append_expense,
    upload_image,
    update_expense_cell,
    get_expense_row
)
import summary as sm

logger = logging.getLogger(__name__)

# Temp store for pending photo entries (waiting for amount confirmation)
_pending_photo: dict = {}
# Active editing correction states
_pending_edits: dict = {}

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


MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 आजचा हिशोब"), KeyboardButton("📅 महिन्याचा हिशोब")],
        [KeyboardButton("🌾 सीझन summary"), KeyboardButton("➕ नवीन नोंद")],
        [KeyboardButton("❓ मदत")]
    ],
    resize_keyboard=True
)

# State tracking for button-guided logging
_interactive_entry: dict = {}

def get_edit_keyboard(row_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ रक्कम (Amount)", callback_data=f"edit:{row_id}:amount"),
            InlineKeyboardButton("📝 टीप (Note)", callback_data=f"edit:{row_id}:desc")
        ],
        [
            InlineKeyboardButton("🌾 पीक (Crop)", callback_data=f"edit:{row_id}:crop"),
            InlineKeyboardButton("🛠️ वर्ग (Category)", callback_data=f"edit:{row_id}:cat")
        ],
        [
            InlineKeyboardButton("✅ पूर्ण झाले (Done)", callback_data=f"edit:{row_id}:done")
        ]
    ])

def get_edit_crop_keyboard(row_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("कापूस 🌿", callback_data=f"edit_val:{row_id}:crop:Cotton"),
         InlineKeyboardButton("सोयाबीन 🫘", callback_data=f"edit_val:{row_id}:crop:Soybean")],
        [InlineKeyboardButton("हळद 🟡", callback_data=f"edit_val:{row_id}:crop:Haldi"),
         InlineKeyboardButton("गहू 🌾", callback_data=f"edit_val:{row_id}:crop:Wheat")],
        [InlineKeyboardButton("General 🚜", callback_data=f"edit_val:{row_id}:crop:General")],
        [InlineKeyboardButton("⬅️ मागे (Back)", callback_data=f"edit_back:{row_id}")]
    ])

def get_edit_category_keyboard(row_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠️ मशागत (Tillage)", callback_data=f"edit_val:{row_id}:category:Tillage"),
         InlineKeyboardButton("🌱 पेरणी/लागवड (Sowing)", callback_data=f"edit_val:{row_id}:category:Sowing")],
        [InlineKeyboardButton("🌿 खत (Fertilizer)", callback_data=f"edit_val:{row_id}:category:Fertilizer"),
         InlineKeyboardButton("🌾 बियाणे (Seeds)", callback_data=f"edit_val:{row_id}:category:Seeds")],
        [InlineKeyboardButton("💊 फवारणी (Spray)", callback_data=f"edit_val:{row_id}:category:Spray"),
         InlineKeyboardButton("👷 मजुरी (Labor)", callback_data=f"edit_val:{row_id}:category:Labor")],
        [InlineKeyboardButton("💧 सिंचन (Irrigation)", callback_data=f"edit_val:{row_id}:category:Irrigation"),
         InlineKeyboardButton("🚜 वाहतूक (Transport)", callback_data=f"edit_val:{row_id}:category:Transport")],
        [InlineKeyboardButton("📦 इतर (Other)", callback_data=f"edit_val:{row_id}:category:Other")],
        [InlineKeyboardButton("⬅️ मागे (Back)", callback_data=f"edit_back:{row_id}")]
    ])

def get_crop_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("कापूस 🌿", callback_data="crop:Cotton"),
         InlineKeyboardButton("सोयाबीन 🫘", callback_data="crop:Soybean")],
        [InlineKeyboardButton("हळद 🟡", callback_data="crop:Haldi"),
         InlineKeyboardButton("गहू 🌾", callback_data="crop:Wheat")],
        [InlineKeyboardButton("General 🚜", callback_data="crop:General")],
        [InlineKeyboardButton("❌ रद्द (Cancel)", callback_data="interactive:cancel")]
    ])

def get_category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛠️ मशागत (Tillage)", callback_data="cat:Tillage"),
         InlineKeyboardButton("🌱 पेरणी/लागवड (Sowing)", callback_data="cat:Sowing")],
        [InlineKeyboardButton("🌿 खत (Fertilizer)", callback_data="cat:Fertilizer"),
         InlineKeyboardButton("🌾 बियाणे (Seeds)", callback_data="cat:Seeds")],
        [InlineKeyboardButton("💊 फवारणी (Spray)", callback_data="cat:Spray"),
         InlineKeyboardButton("👷 मजुरी (Labor)", callback_data="cat:Labor")],
        [InlineKeyboardButton("💧 सिंचन (Irrigation)", callback_data="cat:Irrigation"),
         InlineKeyboardButton("🚜 वाहतूक (Transport)", callback_data="cat:Transport")],
        [InlineKeyboardButton("📦 इतर (Other)", callback_data="cat:Other")],
        [InlineKeyboardButton("⬅️ मागे (Back)", callback_data="back:CROP"),
         InlineKeyboardButton("❌ रद्द (Cancel)", callback_data="interactive:cancel")]
    ])

def get_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("खर्च 💸 (Expense)", callback_data="type:expense"),
         InlineKeyboardButton("उत्पन्न 💰 (Income)", callback_data="type:income")],
        [InlineKeyboardButton("⬅️ मागे (Back)", callback_data="back:CATEGORY"),
         InlineKeyboardButton("❌ रद्द (Cancel)", callback_data="interactive:cancel")]
    ])

def get_skip_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Skip ⏩ (वगळा)", callback_data="desc:skip")],
        [InlineKeyboardButton("❌ रद्द (Cancel)", callback_data="interactive:cancel")]
    ])


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()
        
        chat_id = query.message.chat_id
        data = query.data
        bot = context.bot

        if not _is_authorized(chat_id):
            return

        # Check for cancel
        if data == "interactive:cancel":
            _interactive_entry.pop(chat_id, None)
            await query.edit_message_text("❌ नोंद रद्द करण्यात आली.")
            return

        # Initialize if missing
        if chat_id not in _interactive_entry:
            _interactive_entry[chat_id] = {"step": "CROP"}

        state = _interactive_entry[chat_id]

        if data.startswith("crop:"):
            crop = data.split(":", 1)[1]
            state["crop"] = crop
            state["step"] = "CATEGORY"
            
            crop_emoji = {"Cotton": "कापूस 🌿", "Soybean": "सोयाबीन 🫘", "Haldi": "हळद 🟡", "Wheat": "गहू 🌾", "General": "General 🚜"}.get(crop, crop)
            await query.edit_message_text(
                f"🌾 नवीन नोंद - २/५\n\n📌 पीक: *{crop_emoji}*\n\n👉 वर्ग निवडा (Select Category):",
                parse_mode="Markdown",
                reply_markup=get_category_keyboard()
            )

        elif data.startswith("cat:"):
            cat = data.split(":", 1)[1]
            state["category"] = cat
            state["step"] = "TYPE"
            
            crop_emoji = {"Cotton": "कापूस 🌿", "Soybean": "सोयाबीन 🫘", "Haldi": "हळद 🟡", "Wheat": "गहू 🌾", "General": "General 🚜"}.get(state.get("crop"), "")
            cat_emoji = sm.CATEGORY_EMOJI.get(cat, ("📦", cat))
            cat_display = f"{cat_emoji[0]} {cat_emoji[1]}"
            
            await query.edit_message_text(
                f"🌾 नवीन नोंद - ३/५\n\n📌 पीक: *{crop_emoji}*\n📌 वर्ग: *{cat_display}*\n\n👉 प्रकार निवडा (Select Type):",
                parse_mode="Markdown",
                reply_markup=get_type_keyboard()
            )

        elif data.startswith("type:"):
            t = data.split(":", 1)[1]
            state["type"] = t
            state["step"] = "AMOUNT"
            
            crop_emoji = {"Cotton": "कापूस 🌿", "Soybean": "सोयाबीन 🫘", "Haldi": "हळद 🟡", "Wheat": "गहू 🌾", "General": "General 🚜"}.get(state.get("crop"), "")
            cat_emoji = sm.CATEGORY_EMOJI.get(state.get("category"), ("📦", state.get("category")))
            cat_display = f"{cat_emoji[0]} {cat_emoji[1]}"
            type_display = "खर्च 💸 (Expense)" if t == "expense" else "उत्पन्न 💰 (Income)"
            
            await query.edit_message_text(
                f"🌾 नवीन नोंद - ४/५\n\n📌 पीक: *{crop_emoji}*\n📌 वर्ग: *{cat_display}*\n📌 प्रकार: *{type_display}*\n\n💬 *कृपया रक्कम (Amount) टाईप करा (उदा. 1500):*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ रद्द (Cancel)", callback_data="interactive:cancel")]])
            )

        elif data.startswith("back:"):
            prev = data.split(":", 1)[1]
            state["step"] = prev
            if prev == "CROP":
                await query.edit_message_text(
                    "🌾 नवीन नोंद - १/५\n\n👉 पीक निवडा (Select Crop):",
                    reply_markup=get_crop_keyboard()
                )
            elif prev == "CATEGORY":
                crop_emoji = {"Cotton": "कापूस 🌿", "Soybean": "सोयाबीन 🫘", "Haldi": "हळद 🟡", "Wheat": "गहू 🌾", "General": "General 🚜"}.get(state.get("crop"), "")
                await query.edit_message_text(
                    f"🌾 नवीन नोंद - २/५\n\n📌 पीक: *{crop_emoji}*\n\n👉 वर्ग निवडा (Select Category):",
                    parse_mode="Markdown",
                    reply_markup=get_category_keyboard()
                )

        elif data == "desc:skip":
            if state.get("step") == "DESC":
                state["description"] = state.get("category", "Other")
                state["season"] = get_current_season()
                state["date"] = date.today().strftime("%d-%m-%Y")
                
                _interactive_entry.pop(chat_id, None)
                
                await query.edit_message_text("📝 डेटा सेव्ह होत आहे...")
                await _log_and_reply(bot, chat_id, state)

        elif data.startswith("edit:"):
            parts = data.split(":")
            row_id = int(parts[1])
            action = parts[2]
            
            if action == "done":
                _pending_edits.pop(chat_id, None)
                row = get_expense_row(row_id)
                if row:
                    t = row.get("Type", "expense")
                    cat = row.get("Category", "")
                    amt = row.get("Amount", 0)
                    desc = row.get("Description", "")
                    crop = row.get("Crop", "")
                    bill_link = row.get("Bill_Link", "")
                    
                    icon = "✅" if t == "expense" else "💰"
                    crop_tag = f" ({crop})" if crop and crop != "General" else ""
                    
                    try:
                        clean_amt = str(amt).replace("₹", "").replace(",", "").strip()
                        parsed_amt = int(float(clean_amt))
                        amt_str = f"{parsed_amt:,}"
                    except Exception:
                        amt_str = str(amt)
                        
                    msg = f"{icon} नोंद झाली!{crop_tag}\n{cat}: ₹{amt_str}\n📝 {desc}"
                    if bill_link:
                        msg += f"\n📎 बिल: {bill_link}"
                    msg += "\n\n💾 बदल सेव्ह झाले!"
                else:
                    msg = "💾 बदल सेव्ह झाले!"
                
                await query.edit_message_text(msg, reply_markup=None)
                
            elif action == "amount":
                _pending_edits[chat_id] = {"row_id": row_id, "field": "amount"}
                await query.edit_message_text(
                    f"✏️ रक्कम दुरुस्त करणे:\n\n💬 *कृपया नवीन रक्कम (Amount) टाईप करा (उदा. 1500):*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ मागे (Back)", callback_data=f"edit_back:{row_id}")]])
                )
                
            elif action == "desc":
                _pending_edits[chat_id] = {"row_id": row_id, "field": "desc"}
                await query.edit_message_text(
                    f"✏️ टीप / वर्णन दुरुस्त करणे:\n\n💬 *नवीन टीप / वर्णन टाईप करा:*",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ मागे (Back)", callback_data=f"edit_back:{row_id}")]])
                )
                
            elif action == "crop":
                await query.edit_message_text(
                    f"✏️ पीक दुरुस्त करणे:\n\n👉 नवीन पीक निवडा:",
                    reply_markup=get_edit_crop_keyboard(row_id)
                )
                
            elif action == "cat":
                await query.edit_message_text(
                    f"✏️ वर्ग (Category) दुरुस्त करणे:\n\n👉 नवीन वर्ग निवडा:",
                    reply_markup=get_edit_category_keyboard(row_id)
                )

        elif data.startswith("edit_val:"):
            parts = data.split(":")
            row_id = int(parts[1])
            field = parts[2]
            val = parts[3]
            
            col_name = "Crop" if field == "crop" else "Category"
            success = update_expense_cell(row_id, col_name, val)
            if success:
                display_val = val
                if field == "crop":
                    display_val = {"Cotton": "कापूस 🌿", "Soybean": "सोयाबीन 🫘", "Haldi": "हळद 🟡", "Wheat": "गहू 🌾", "General": "General 🚜"}.get(val, val)
                elif field == "category":
                    cat_emoji = sm.CATEGORY_EMOJI.get(val, ("📦", val))
                    display_val = f"{cat_emoji[0]} {cat_emoji[1]}"
                
                await query.edit_message_text(
                    f"✅ {col_name} बदलून *{display_val}* करण्यात आला आहे.",
                    parse_mode="Markdown",
                    reply_markup=get_edit_keyboard(row_id)
                )
            else:
                await query.edit_message_text(
                    "❌ बदल करताना त्रुटी आली.",
                    reply_markup=get_edit_keyboard(row_id)
                )

        elif data.startswith("edit_back:"):
            row_id = int(data.split(":")[1])
            _pending_edits.pop(chat_id, None)
            
            row = get_expense_row(row_id)
            if row:
                t = row.get("Type", "expense")
                cat = row.get("Category", "")
                amt = row.get("Amount", 0)
                desc = row.get("Description", "")
                crop = row.get("Crop", "")
                bill_link = row.get("Bill_Link", "")
                
                icon = "✅" if t == "expense" else "💰"
                crop_tag = f" ({crop})" if crop and crop != "General" else ""
                
                try:
                    clean_amt = str(amt).replace("₹", "").replace(",", "").strip()
                    parsed_amt = int(float(clean_amt))
                    amt_str = f"{parsed_amt:,}"
                except Exception:
                    amt_str = str(amt)
                
                msg = f"{icon} नोंद अपडेट झाली!{crop_tag}\n{cat}: ₹{amt_str}\n📝 {desc}"
                if bill_link:
                    msg += f"\n📎 बिल: {bill_link}"
            else:
                msg = "✏️ नोंद दुरुस्त करा:"
                
            await query.edit_message_text(
                msg,
                reply_markup=get_edit_keyboard(row_id)
            )
    except Exception as e:
        logger.error(f"Error in handle_callback_query: {e}", exc_info=True)
        try:
            await query.edit_message_text("⚠️ प्रक्रिया करताना एरर आली. कृपया नंतर प्रयत्न करा.")
        except Exception:
            pass


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
    """Append row to database and send confirmation reply with edit inline buttons."""
    try:
        row_id = append_expense(row)
        if row_id is not None:
            t = row.get("type", "expense") or row.get("Type", "expense")
            cat = row.get("category", "") or row.get("Category", "")
            amt = row.get("amount", 0) or row.get("Amount", 0)
            desc = row.get("description", "") or row.get("Description", "")
            crop = row.get("crop", "") or row.get("Crop", "")
            payment = f" | {row.get('payment')}" if row.get("payment") else ""

            icon = "✅" if t == "expense" else "💰"
            crop_tag = f" ({crop})" if crop and crop != "General" else ""

            try:
                clean_amt = str(amt).replace("₹", "").replace(",", "").strip()
                parsed_amt = int(float(clean_amt))
                amt_str = f"{parsed_amt:,}"
            except Exception:
                amt_str = str(amt)

            msg = f"{icon} नोंद झाली!{crop_tag}\n{cat}: ₹{amt_str}\n📝 {desc}{payment}"
            if extra_msg:
                msg += f"\n{extra_msg}"
            
            await bot.send_message(
                chat_id=chat_id,
                text=msg,
                reply_markup=get_edit_keyboard(row_id)
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ नोंद झाली नाही, पुन्हा पाठवा",
                reply_markup=MAIN_MENU_KEYBOARD
            )
    except Exception as e:
        logger.error(f"Error in _log_and_reply: {e}", exc_info=True)
        await bot.send_message(
            chat_id=chat_id,
            text="⚠️ नोंद करताना एरर आली, पण डेटा सेव्ह होऊ शकला नाही.",
            reply_markup=MAIN_MENU_KEYBOARD
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        bot = context.bot
        chat_id = update.effective_chat.id
        text = update.message.text or ""

        if not _is_authorized(chat_id):
            return

        # Check if user is responding with a correction
        if chat_id in _pending_edits:
            pending = _pending_edits.pop(chat_id)
            row_id = pending["row_id"]
            field = pending["field"]
            
            if field == "amount":
                try:
                    amt_clean = text.replace("₹", "").replace(",", "").strip()
                    amount = float(amt_clean)
                    success = update_expense_cell(row_id, "Amount", amount)
                    if success:
                        row = get_expense_row(row_id)
                        t = row.get("Type", "expense")
                        cat = row.get("Category", "")
                        desc = row.get("Description", "")
                        crop = row.get("Crop", "")
                        
                        icon = "✅" if t == "expense" else "💰"
                        crop_tag = f" ({crop})" if crop and crop != "General" else ""
                        
                        await bot.send_message(
                            chat_id=chat_id,
                            text=f"✅ रक्कम बदलून *₹{amount:,.0f}* करण्यात आली आहे.\n\n"
                                 f"{icon} नोंद: {crop_tag}\n{cat}: ₹{amount:,.0f}\n📝 {desc}",
                            parse_mode="Markdown",
                            reply_markup=get_edit_keyboard(row_id)
                        )
                    else:
                        await bot.send_message(
                            chat_id=chat_id, 
                            text="❌ बदल करता आला नाही.",
                            reply_markup=get_edit_keyboard(row_id)
                        )
                except ValueError:
                    _pending_edits[chat_id] = pending
                    await bot.send_message(
                        chat_id=chat_id, 
                        text="❌ फक्त संख्या (नंबर) टाईप करा (उदा: 1500):",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ मागे (Back)", callback_data=f"edit_back:{row_id}")]])
                    )
                return

            elif field == "desc":
                success = update_expense_cell(row_id, "Description", text)
                if success:
                    row = get_expense_row(row_id)
                    t = row.get("Type", "expense")
                    cat = row.get("Category", "")
                    amt = row.get("Amount", 0)
                    crop = row.get("Crop", "")
                    
                    icon = "✅" if t == "expense" else "💰"
                    crop_tag = f" ({crop})" if crop and crop != "General" else ""
                    
                    try:
                        clean_amt = str(amt).replace("₹", "").replace(",", "").strip()
                        parsed_amt = int(float(clean_amt))
                        amt_str = f"{parsed_amt:,}"
                    except Exception:
                        amt_str = str(amt)
                        
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ टीप बदलून *{text}* करण्यात आली आहे.\n\n"
                             f"{icon} नोंद: {crop_tag}\n{cat}: ₹{amt_str}\n📝 {text}",
                        parse_mode="Markdown",
                        reply_markup=get_edit_keyboard(row_id)
                    )
                else:
                    await bot.send_message(
                        chat_id=chat_id, 
                        text="❌ बदल करता आला नाही.",
                        reply_markup=get_edit_keyboard(row_id)
                    )
                return

        # Help command / Main Menu Help
        if text.strip().lower() in ["/start", "/help", "help", "मदत", "❓ मदत"]:
            await bot.send_message(
                chat_id=chat_id,
                text=HELP_TEXT,
                parse_mode="Markdown",
                reply_markup=MAIN_MENU_KEYBOARD
            )
            return

        # Start interactive button-guided logging
        if text.strip() == "➕ नवीन नोंद" or text.strip().lower() in ["/new", "new", "नोंद"]:
            _interactive_entry[chat_id] = {"step": "CROP"}
            await bot.send_message(
                chat_id=chat_id,
                text="🌾 नवीन नोंद - १/५\n\n👉 पीक निवडा (Select Crop):",
                reply_markup=get_crop_keyboard()
            )
            return

        # Check if user is currently in interactive entry flow
        if chat_id in _interactive_entry:
            state = _interactive_entry[chat_id]
            step = state.get("step")

            if step == "AMOUNT":
                try:
                    # Clean and parse amount
                    amt_clean = text.replace("₹", "").replace(",", "").strip()
                    amount = float(amt_clean)
                    state["amount"] = amount
                    state["step"] = "DESC"

                    crop_emoji = {"Cotton": "कापूस 🌿", "Soybean": "सोयाबीन 🫘", "Haldi": "हळद 🟡", "Wheat": "गहू 🌾", "General": "General 🚜"}.get(state.get("crop"), "")
                    cat_emoji = sm.CATEGORY_EMOJI.get(state.get("category"), ("📦", state.get("category")))
                    cat_display = f"{cat_emoji[0]} {cat_emoji[1]}"
                    type_display = "खर्च 💸 (Expense)" if state.get("type") == "expense" else "उत्पन्न 💰 (Income)"

                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"🌾 नवीन नोंद - ५/५\n\n📌 पीक: *{crop_emoji}*\n📌 वर्ग: *{cat_display}*\n📌 प्रकार: *{type_display}*\n📌 रक्कम: *₹{amount:,.0f}*\n\n💬 *काही वर्णन / टीप (Description)?*\nटाईप करा किंवा खालील Skip बटन दाबा:",
                        parse_mode="Markdown",
                        reply_markup=get_skip_keyboard()
                    )
                except ValueError:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="❌ फक्त संख्या (नंबर) टाईप करा (उदा: 1500):",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ रद्द (Cancel)", callback_data="interactive:cancel")]])
                    )
                return

            elif step == "DESC":
                state["description"] = text
                state["season"] = get_current_season()
                state["date"] = date.today().strftime("%d-%m-%Y")

                _interactive_entry.pop(chat_id, None)

                await bot.send_message(chat_id=chat_id, text="📝 डेटा सेव्ह होत आहे...")
                await _log_and_reply(bot, chat_id, state)
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
            await bot.send_message(chat_id=chat_id, text=msg, reply_markup=MAIN_MENU_KEYBOARD)
            return

        # Parse as expense
        await bot.send_chat_action(chat_id=chat_id, action="typing")
        parsed = parse_expense_text(text)

        if not parsed or not parsed.get("amount"):
            await bot.send_message(
                chat_id=chat_id,
                text="समजले नाही 🙏\nउदाहरण: 'आज DAP 2 बॅग घेतल्या ₹1200'\nकिंवा /help टाइप करा",
                reply_markup=MAIN_MENU_KEYBOARD
            )
            return

        parsed["season"] = parsed.get("season") or get_current_season()
        parsed["date"] = parsed.get("date") or date.today().strftime("%d-%m-%Y")
        await _log_and_reply(bot, chat_id, parsed)
    except Exception as e:
        logger.error(f"Error in handle_text: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ संदेश प्रक्रिया करताना एरर आली. कृपया नंतर प्रयत्न करा.",
                reply_markup=MAIN_MENU_KEYBOARD
            )
        except Exception:
            pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
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
    except Exception as e:
        logger.error(f"Error in handle_photo: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ फोटो प्रक्रिया करताना एरर आली. कृपया नंतर प्रयत्न करा."
            )
        except Exception:
            pass


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
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
    except Exception as e:
        logger.error(f"Error in handle_voice: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ आवाज प्रक्रिया करताना एरर आली. कृपया नंतर प्रयत्न करा."
            )
        except Exception:
            pass

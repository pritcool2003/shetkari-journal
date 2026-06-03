"""
main.py
FastAPI app — receives Telegram webhook updates and routes them.
"""

import json
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, Request, Response
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters

from config import TELEGRAM_BOT_TOKEN, WEBHOOK_URL, PORT
from bot_handlers import handle_text, handle_photo, handle_voice

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Telegram Application ──────────────────────────────────────────────────────
application = (
    Application.builder()
    .token(TELEGRAM_BOT_TOKEN)
    .updater(None)          # webhook mode — no polling
    .build()
)

# Register handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(MessageHandler(filters.COMMAND, handle_text))        # /start /help
application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
application.add_handler(MessageHandler(filters.VOICE, handle_voice))


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Set Telegram webhook on startup, clean up on shutdown."""
    await application.initialize()
    await application.start()

    if WEBHOOK_URL:
        webhook_endpoint = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        try:
            await application.bot.set_webhook(
                url=webhook_endpoint,
                allowed_updates=["message"],
                drop_pending_updates=True,
            )
            logger.info(f"✅ Webhook set: {webhook_endpoint}")
        except Exception as e:
            logger.error(f"❌ Failed to set webhook: {e}")
    else:
        logger.warning("⚠️  WEBHOOK_URL not set — webhook not registered")

    print("🌾 Shetkari Journal Bot is running!")
    yield

    await application.stop()
    await application.shutdown()


# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Shetkari Journal Bot",
    description="Telegram bot for Marathwada farmer expense tracking",
    lifespan=lifespan,
)


@app.get("/")
async def health():
    return {
        "status": "running",
        "service": "Shetkari Journal Bot 🌾",
        "time": datetime.now().isoformat(),
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram update and process it."""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return Response(status_code=200)  # Always 200 to Telegram


@app.get("/status")
async def status():
    """Show bot info and webhook status."""
    try:
        bot_info = await application.bot.get_me()
        webhook_info = await application.bot.get_webhook_info()
        return {
            "bot": {
                "name": bot_info.full_name,
                "username": bot_info.username,
            },
            "webhook": {
                "url": webhook_info.url,
                "pending_updates": webhook_info.pending_update_count,
                "last_error": webhook_info.last_error_message,
            },
        }
    except Exception as e:
        return {"error": str(e)}


# ── Entry point (local dev) ───────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)

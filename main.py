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
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters

from config import TELEGRAM_BOT_TOKEN, WEBHOOK_URL, PORT
from bot_handlers import handle_text, handle_photo, handle_voice, handle_callback_query

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
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
application.add_handler(CallbackQueryHandler(handle_callback_query))
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
                allowed_updates=["message", "callback_query"],
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


@app.get("/debug-logs")
async def debug_logs():
    import os
    if os.path.exists("app.log"):
        with open("app.log", "r", encoding="utf-8") as f:
            content = f.read()
            if len(content) > 8000:
                content = "...\n[TRUNCATED]\n" + content[-8000:]
            return Response(content=content, media_type="text/plain")
    return Response(content="No logs found.", media_type="text/plain")


@app.get("/test-connections")
async def test_connections():
    import os
    import json
    import traceback
    from datetime import date
    output = []
    output.append("=== Shetkari Journal Bot Diagnostic Tool ===")

    # 1. Check Env Variables
    required_vars = [
        "TELEGRAM_BOT_TOKEN",
        "OPENAI_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_KEY"
    ]

    all_set = True
    for var in required_vars:
        val = os.getenv(var)
        if val:
            display_val = val[:10] + "..." if len(val) > 10 else val
            output.append(f"[OK] {var} is set (starts with: '{display_val}')")
        else:
            output.append(f"[MISSING] {var} is MISSING!")
            all_set = False

    if not all_set:
        output.append("\n[WARNING] Please configure all missing environment variables in Render Dashboard.")
        return Response(content="\n".join(output), media_type="text/plain")

    # 2. Test OpenAI connection
    output.append("\n--- Testing OpenAI API ---")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=5
        )
        output.append("[OK] OpenAI API: Connection successful!")
        output.append(f"   Response: {response.choices[0].message.content.strip()}")
    except Exception as e:
        output.append(f"[ERROR] OpenAI API: Failed! Error: {e}")

    # 3. Test Supabase Database Connection
    output.append("\n--- Testing Supabase Connection ---")
    try:
        from supabase_client import _get_client
        supabase = _get_client()
        
        # Test table check
        output.append("   Fetching expenses table data to verify read permission...")
        res = supabase.table("expenses").select("id").limit(1).execute()
        output.append(f"[OK] Supabase DB: Successfully connected! Found records: {len(res.data)}")
        
        # Test Storage
        output.append("   Checking Supabase Storage bucket 'bills' exists...")
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if "bills" in bucket_names:
            output.append("[OK] Supabase Storage: 'bills' bucket exists and is accessible!")
            
            # Check public access
            bill_bucket = next(b for b in buckets if b.name == "bills")
            is_public = bill_bucket.public
            output.append(f"   Bucket 'bills' public status: {is_public} (Should be True for public view links)")
        else:
            output.append("[WARNING] Supabase Storage: 'bills' bucket not found! Please create a public bucket named 'bills' in your Supabase console.")
    except Exception as e:
        output.append(f"[ERROR] Supabase Connection: Failed! Error: {e}")
        output.append(traceback.format_exc())


    output.append("\n=== Diagnostics Completed ===")
    return Response(content="\n".join(output), media_type="text/plain")


# ── Entry point (local dev) ───────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)

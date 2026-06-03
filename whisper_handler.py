"""
whisper_handler.py
Transcribe Telegram voice notes (OGG) using OpenAI Whisper API.
"""

import logging
from openai import OpenAI
from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)


async def transcribe_voice(audio_bytes: bytes) -> str | None:
    """
    Transcribe OGG audio bytes to text using Whisper.
    Returns transcribed string or None on failure.
    """
    import io

    try:
        # Whisper needs a file-like object with a name
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "voice.ogg"

        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="mr",  # Marathi hint
            prompt="Marathwada farmer expense journal. Marathi or Hindi words: खत, मजुरी, बियाणे, ट्रॅक्टर, फवारणी, रुपये",
        )
        text = transcript.text.strip()
        logger.info(f"Whisper transcript: {text}")
        return text
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return None

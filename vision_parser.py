"""
vision_parser.py
Extract expense data from bill/receipt photos using GPT-4o Mini Vision.
"""

import base64
import json
import logging
from datetime import date
from openai import OpenAI
from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)

VISION_PROMPT = """You are analyzing a bill or receipt photo for an Indian farmer's expense journal in Marathwada, Maharashtra.
The bill may be handwritten or printed, in Marathi, Hindi, or English.

Extract and return ONLY a JSON object:
{
  "shop_name": "",
  "date": "DD-MM-YYYY",
  "items": "",
  "amount": 0,
  "category": "",
  "crop": "",
  "payment": ""
}

CATEGORY: Fertilizer | Seeds | Spray | Labor | Irrigation | Transport | Equipment | Other
CROP: Cotton | Soybean | Haldi | Wheat | General

- Use today's date if bill date is not visible: {today}
- amount = total amount on the bill (look for "Total", "एकूण", circled/boxed numbers)
- If the image is NOT a bill/receipt at all, return: {{"error": "not_a_bill"}}
- Return ONLY JSON. No explanation."""


def parse_bill_image(image_bytes: bytes) -> dict | None:
    """
    Send image to GPT-4o Mini Vision and extract bill data.
    Returns dict or None on failure. Returns {"error": "not_a_bill"} if not a receipt.
    """
    today = date.today().strftime("%d-%m-%Y")
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": VISION_PROMPT.format(today=today),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=400,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"Vision JSON parse error: {e} | raw: {raw}")
        return None
    except Exception as e:
        logger.error(f"Vision API error: {e}")
        return None

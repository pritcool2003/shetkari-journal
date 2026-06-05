"""
gpt_parser.py
Parse Marathi/Hindi/English expense text → structured JSON using GPT-4o Mini.
"""

import json
import logging
from datetime import date
from openai import OpenAI
from config import OPENAI_API_KEY, get_current_season

logger = logging.getLogger(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """You are an expense logging assistant for a Marathi-speaking farmer in Marathwada, Maharashtra, India.
The farmer tracks expenses for Cotton, Soybean, Haldi (turmeric), and Wheat crops.

Parse the farmer's message (in Marathi, Hindi, or broken English) and return ONLY a JSON object.

JSON fields:
{{
  "date": "DD-MM-YYYY",
  "season": "",
  "crop": "",
  "category": "",
  "description": "",
  "amount": 0,
  "type": "expense",
  "payment": "",
  "notes": ""
}}

CATEGORY RULES (pick exactly one):
- खत / khat / DAP / urea / potash / niboli / fertilizer → "Fertilizer"
- बियाणे / biyane / seeds / soybean seeds / cotton seeds → "Seeds"
- फवारणी / fawrani / spray / sanjivani / driching / BioR / pesticide / roundup / insecticide → "Spray"
- मजुरी / majuri / labour / labor / nigan / chinai / nidhan / workers / माणसं → "Labor"
- ड्रिप / drip / pump / पंप / MSEB / electricity / पाणी / pipe → "Irrigation"
- ट्रॅक्टर / tractor / vahatuk / transport / truck / वाहतूक → "Transport"
- विकला / sold / mandi / उत्पन्न / miyus / kevani / cotton sale / soy sale → "Sale"
- haldi machine / हळद / turmeric harvest → "Harvesting"
- vet / veterinary / पशु → "Veterinary"
- wire / fence / equipment / machine → "Equipment"
- anything else → "Other"

CROP RULES:
- cotton / कापूस / kapus / miyus / bt → "Cotton"
- soy / सोयाबीन / soya / soybean → "Soybean"
- haldi / हळद / turmeric → "Haldi"
- wheat / गहू / gahu → "Wheat"
- general farm / not crop specific → "General"

TYPE RULES:
- विकला, sold, mandi income, sale → "income"
- everything else → "expense"

PAYMENT RULES:
- online / UPI / gpay → "Online"
- cash → "Cash"
- yogesh → "Cash-Yogesh"
- prathik / pratik → "Online-Prathik"
- preman → "Online-Preman"
- not mentioned → ""

TODAY'S DATE: {today}
CURRENT SEASON: {season}

Use today's date if no date is mentioned. Use current season if not specified.
Return ONLY the JSON. No explanation, no markdown, no backticks."""


def parse_expense_text(text: str) -> dict | None:
    """Parse expense text and return structured dict. Returns None on failure."""
    today = date.today().strftime("%d-%m-%Y")
    season = get_current_season()

    prompt = SYSTEM_PROMPT.format(today=today, season=season)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text},
                ],
                max_tokens=300,
                temperature=0,
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown fences if present
            raw = raw.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(raw)
            return parsed
        except json.JSONDecodeError as e:
            logger.warning(f"GPT JSON parse error (attempt {attempt+1}): {e} | raw: {raw}")
        except Exception as e:
            logger.error(f"GPT API error: {e}")
            return None

    return None

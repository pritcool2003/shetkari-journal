"""
supabase_client.py
Read/write expenses and upload bill photos using Supabase.

Table: "expenses"
Columns: id | created_at | date | season | crop | category | description | amount | type | payment | bill_link | notes
"""

import logging
import io
from datetime import date, datetime
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

_client: Client = None

def _get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be configured in environment variables.")
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def _db_to_row(record: dict) -> dict:
    """Map Supabase lowercase database record to capitalized row dictionary."""
    if not record:
        return {}
    return {
        "id": record.get("id"),
        "Date": record.get("date", ""),
        "Season": record.get("season", ""),
        "Crop": record.get("crop", "General"),
        "Category": record.get("category", "Other"),
        "Description": record.get("description", ""),
        "Amount": record.get("amount", 0),
        "Type": record.get("type", "expense"),
        "Payment": record.get("payment", ""),
        "Bill_Link": record.get("bill_link", ""),
        "Notes": record.get("notes", ""),
    }

def _row_to_db(row: dict) -> dict:
    """Map capitalized row dictionary to Supabase lowercase database record."""
    # Handle both capitalized and lowercase keys for robustness
    return {
        "date": row.get("date") or row.get("Date") or date.today().strftime("%d-%m-%Y"),
        "season": row.get("season") or row.get("Season") or "",
        "crop": row.get("crop") or row.get("Crop") or "General",
        "category": row.get("category") or row.get("Category") or "Other",
        "description": row.get("description") or row.get("Description") or "",
        "amount": row.get("amount") or row.get("Amount") or 0,
        "type": row.get("type") or row.get("Type") or "expense",
        "payment": row.get("payment") or row.get("Payment") or "",
        "bill_link": row.get("bill_link") or row.get("Bill_Link") or "",
        "notes": row.get("notes") or row.get("Notes") or "",
    }

def append_expense(row: dict) -> int | None:
    """Insert one expense/income row. Returns the database id or None."""
    try:
        supabase = _get_client()
        db_data = _row_to_db(row)
        res = supabase.table("expenses").insert(db_data).execute()
        if res.data:
            return res.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Supabase insert failed: {e}")
        return None

def update_expense_cell(row_id: int, col_name: str, new_value) -> bool:
    """Update a specific column for the given database row ID."""
    try:
        supabase = _get_client()
        # Map capitalized col_name to lowercase db column
        db_col = col_name.lower().replace("bill_link", "bill_link")
        # Ensure correct type for Amount
        if col_name == "Amount":
            try:
                new_value = float(new_value)
            except ValueError:
                pass
        res = supabase.table("expenses").update({db_col: new_value}).eq("id", row_id).execute()
        return len(res.data) > 0
    except Exception as e:
        logger.error(f"Supabase update failed: {e}")
        return False

def get_expense_row(row_id: int) -> dict | None:
    """Retrieve a row by ID, returned as capitalized keys dict."""
    try:
        supabase = _get_client()
        res = supabase.table("expenses").select("*").eq("id", row_id).execute()
        if res.data:
            return _db_to_row(res.data[0])
        return None
    except Exception as e:
        logger.error(f"Supabase retrieve failed: {e}")
        return None

def get_all_rows() -> list[dict]:
    """Retrieve all rows, returned as capitalized keys dicts."""
    try:
        supabase = _get_client()
        res = supabase.table("expenses").select("*").order("id").execute()
        return [_db_to_row(record) for record in res.data]
    except Exception as e:
        logger.error(f"Supabase read failed: {e}")
        return []

def get_today_expenses() -> list[dict]:
    today_str = date.today().strftime("%d-%m-%Y")
    try:
        supabase = _get_client()
        res = supabase.table("expenses").select("*").eq("date", today_str).order("id").execute()
        return [_db_to_row(record) for record in res.data]
    except Exception as e:
        logger.error(f"Supabase read today failed: {e}")
        return []

def get_month_expenses(month: int = None, year: int = None) -> list[dict]:
    if not month:
        month = date.today().month
    if not year:
        year = date.today().year
    
    all_rows = get_all_rows()
    result = []
    for r in all_rows:
        try:
            d = datetime.strptime(r.get("Date", ""), "%d-%m-%Y")
            if d.month == month and d.year == year:
                result.append(r)
        except Exception:
            pass
    return result

def get_season_expenses(season: str = None) -> list[dict]:
    if not season:
        from config import get_current_season
        season = get_current_season()
    try:
        supabase = _get_client()
        res = supabase.table("expenses").select("*").eq("season", season).order("id").execute()
        return [_db_to_row(record) for record in res.data]
    except Exception as e:
        logger.error(f"Supabase read season failed: {e}")
        return []

def get_running_total(season: str = None) -> dict:
    """Return total expense and income for a season."""
    rows = get_season_expenses(season)
    total_expense = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "expense")
    total_income = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "income")
    bills_count = sum(1 for r in rows if r.get("Bill_Link"))
    return {
        "expense": total_expense,
        "income": total_income,
        "profit": total_income - total_expense,
        "bills": bills_count,
        "rows": len(rows),
    }

def upload_image(image_bytes: bytes, season: str, original_filename: str = "") -> str:
    """
    Upload image_bytes to Supabase storage bucket 'bills'.
    Returns public view link or empty string on failure.
    """
    try:
        supabase = _get_client()
        
        # Generate clean filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{season}/bill_{timestamp}.jpg"
        
        # Upload to bucket
        res = supabase.storage.from_("bills").upload(
            path=filename,
            file=image_bytes,
            file_options={"content-type": "image/jpeg"}
        )
        
        # Get public url
        public_url = supabase.storage.from_("bills").get_public_url(filename)
        logger.info(f"Uploaded bill to Supabase Storage: {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"Supabase Storage upload failed: {e}")
        return ""

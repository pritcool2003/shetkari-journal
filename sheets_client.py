"""
sheets_client.py
Read/write expenses to Google Sheets.

Sheet: "Expenses"
Columns: Date | Season | Crop | Category | Description | Amount | Type | Payment | Bill_Link | Notes
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import date, datetime
from config import SERVICE_ACCOUNT_INFO, GOOGLE_SHEET_ID
import logging

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Date", "Season", "Crop", "Category",
    "Description", "Amount", "Type", "Payment",
    "Bill_Link", "Notes"
]


def _get_sheet():
    creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

    # Ensure "Expenses" sheet exists
    try:
        sheet = spreadsheet.worksheet("Expenses")
    except gspread.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title="Expenses", rows=1000, cols=10)
        sheet.append_row(HEADERS)
        # Bold the header row
        sheet.format("A1:J1", {"textFormat": {"bold": True}})

    return sheet


def append_expense(row: dict) -> bool:
    """Append one expense/income row. row keys match HEADERS."""
    try:
        sheet = _get_sheet()
        row_data = [
            row.get("date", date.today().strftime("%d-%m-%Y")),
            row.get("season", ""),
            row.get("crop", "General"),
            row.get("category", "Other"),
            row.get("description", ""),
            row.get("amount", 0),
            row.get("type", "expense"),
            row.get("payment", ""),
            row.get("bill_link", ""),
            row.get("notes", ""),
        ]
        sheet.append_row(row_data, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        logger.error(f"Sheets append failed: {e}")
        return False


def get_all_rows() -> list[dict]:
    """Return all rows as list of dicts."""
    try:
        sheet = _get_sheet()
        records = sheet.get_all_records()
        return records
    except Exception as e:
        logger.error(f"Sheets read failed: {e}")
        return []


def get_today_expenses() -> list[dict]:
    today_str = date.today().strftime("%d-%m-%Y")
    return [r for r in get_all_rows() if r.get("Date") == today_str]


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
    return [r for r in get_all_rows() if r.get("Season") == season]


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

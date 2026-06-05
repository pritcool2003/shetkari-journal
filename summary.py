"""
summary.py
Generate Marathi-language expense summary messages for Telegram.
"""

from datetime import date
from sheets_client import (
    get_today_expenses,
    get_month_expenses,
    get_season_expenses,
    get_running_total,
)
from config import get_current_season

CATEGORY_EMOJI = {
    "Fertilizer":  ("🌿", "खत"),
    "Seeds":       ("🌱", "बियाणे"),
    "Spray":       ("💊", "फवारणी"),
    "Labor":       ("👷", "मजुरी"),
    "Tillage":     ("🛠️", "मशागत"),
    "Sowing":      ("🌱", "पेरणी/लागवड"),
    "Irrigation":  ("💧", "सिंचन/ड्रिप"),
    "Transport":   ("🚜", "वाहतूक"),
    "Harvesting":  ("🌾", "काढणी"),
    "Equipment":   ("🔧", "साधने"),
    "Veterinary":  ("🐄", "पशुवैद्य"),
    "Sale":        ("💰", "विक्री"),
    "Other":       ("📦", "इतर"),
}

MONTH_NAMES_MR = [
    "", "जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून",
    "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"
]


def _category_breakdown(rows: list[dict]) -> dict:
    """Sum amounts by category for expenses only."""
    breakdown = {}
    for r in rows:
        if r.get("Type") == "expense":
            cat = r.get("Category", "Other")
            breakdown[cat] = breakdown.get(cat, 0) + float(r.get("Amount", 0))
    return breakdown


def _crop_breakdown(rows: list[dict]) -> dict:
    """Sum amounts by crop."""
    breakdown = {}
    for r in rows:
        crop = r.get("Crop", "General")
        t = r.get("Type", "expense")
        key = f"{crop}_{t}"
        breakdown[key] = breakdown.get(key, 0) + float(r.get("Amount", 0))
    return breakdown


def format_inr(amount: float) -> str:
    """Format as ₹1,23,456"""
    # Indian number formatting
    amount = int(amount)
    s = str(amount)
    if len(s) <= 3:
        return f"₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while len(rest) > 2:
        parts.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.append(rest)
    parts.reverse()
    formatted = ",".join(parts) + "," + last3
    return f"₹{formatted}"


def today_summary() -> str:
    rows = get_today_expenses()
    if not rows:
        return "📋 आज कोणतीही नोंद नाही."

    total = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "expense")
    income = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "income")

    lines = [f"📊 आजचा हिशोब ({date.today().strftime('%d-%m-%Y')})", "─────────────────"]
    for r in rows:
        emoji = CATEGORY_EMOJI.get(r.get("Category", "Other"), ("📦", "इतर"))[0]
        desc = r.get("Description", "")[:30]
        amt = format_inr(float(r.get("Amount", 0)))
        t = "↑" if r.get("Type") == "income" else "↓"
        lines.append(f"{emoji} {t} {amt}  {desc}")

    lines.append("─────────────────")
    if total:
        lines.append(f"💸 खर्च: {format_inr(total)}")
    if income:
        lines.append(f"💰 उत्पन्न: {format_inr(income)}")
    return "\n".join(lines)


def month_summary(month: int = None, year: int = None) -> str:
    if not month:
        month = date.today().month
    if not year:
        year = date.today().year

    rows = get_month_expenses(month, year)
    if not rows:
        return f"📋 {MONTH_NAMES_MR[month]} मध्ये कोणतीही नोंद नाही."

    breakdown = _category_breakdown(rows)
    total_exp = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "expense")
    total_inc = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "income")
    bills = sum(1 for r in rows if r.get("Bill_Link"))

    lines = [f"📊 {MONTH_NAMES_MR[month]} {year} हिशोब", "═════════════════"]
    for cat, amount in sorted(breakdown.items(), key=lambda x: -x[1]):
        if amount > 0:
            emoji, label = CATEGORY_EMOJI.get(cat, ("📦", cat))
            lines.append(f"{emoji} {label}: {format_inr(amount)}")

    lines.append("─────────────────")
    lines.append(f"💸 एकूण खर्च: {format_inr(total_exp)}")
    if total_inc:
        lines.append(f"💰 एकूण उत्पन्न: {format_inr(total_inc)}")
        lines.append(f"✅ नफा: {format_inr(total_inc - total_exp)}")
    if bills:
        lines.append(f"📎 बिले जतन: {bills}")
    return "\n".join(lines)


def season_summary(season: str = None) -> str:
    if not season:
        season = get_current_season()

    rows = get_season_expenses(season)
    if not rows:
        return f"📋 {season} साठी कोणतीही नोंद नाही."

    breakdown = _category_breakdown(rows)
    crop_data = _crop_breakdown(rows)
    total_exp = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "expense")
    total_inc = sum(float(r.get("Amount", 0)) for r in rows if r.get("Type") == "income")
    bills = sum(1 for r in rows if r.get("Bill_Link"))

    lines = [f"🌾 {season} संपूर्ण हिशोब", "═════════════════"]

    # Crop-wise income
    crops_with_income = {k.split("_")[0]: v for k, v in crop_data.items() if k.endswith("_income")}
    if crops_with_income:
        lines.append("💰 पीक-निहाय उत्पन्न:")
        for crop, amt in crops_with_income.items():
            lines.append(f"   🌿 {crop}: {format_inr(amt)}")

    lines.append("─────────────────")
    lines.append("💸 खर्च तपशील:")
    for cat, amount in sorted(breakdown.items(), key=lambda x: -x[1]):
        if amount > 0:
            emoji, label = CATEGORY_EMOJI.get(cat, ("📦", cat))
            lines.append(f"  {emoji} {label}: {format_inr(amount)}")

    lines.append("═════════════════")
    lines.append(f"💸 एकूण खर्च: {format_inr(total_exp)}")
    lines.append(f"💰 एकूण उत्पन्न: {format_inr(total_inc)}")
    profit = total_inc - total_exp
    sign = "✅" if profit >= 0 else "❌"
    lines.append(f"{sign} निव्वळ नफा: {format_inr(abs(profit))}{'(नफा)' if profit >= 0 else '(तोटा)'}")
    if bills:
        lines.append(f"📎 बिले जतन: {bills}")
    return "\n".join(lines)


def running_total() -> str:
    season = get_current_season()
    data = get_running_total(season)
    lines = [
        f"💰 {season} चालू एकूण",
        "─────────────────",
        f"💸 खर्च: {format_inr(data['expense'])}",
        f"💰 उत्पन्न: {format_inr(data['income'])}",
    ]
    if data["income"]:
        sign = "✅" if data["profit"] >= 0 else "❌"
        lines.append(f"{sign} नफा/तोटा: {format_inr(abs(data['profit']))}")
    lines.append(f"📝 नोंदी: {data['rows']}")
    if data["bills"]:
        lines.append(f"📎 बिले: {data['bills']}")
    return "\n".join(lines)

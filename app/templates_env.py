from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.schemas import CATEGORY_METADATA

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

PT_MONTHS_SHORT = {
    1: "Jan",
    2: "Fev",
    3: "Mar",
    4: "Abr",
    5: "Mai",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Set",
    10: "Out",
    11: "Nov",
    12: "Dez",
}

PT_MONTHS_FULL = {
    1: "JANEIRO",
    2: "FEVEREIRO",
    3: "MARÇO",
    4: "ABRIL",
    5: "MAIO",
    6: "JUNHO",
    7: "JULHO",
    8: "AGOSTO",
    9: "SETEMBRO",
    10: "OUTUBRO",
    11: "NOVEMBRO",
    12: "DEZEMBRO",
}


def format_date_full(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return f"{PT_MONTHS_SHORT[dt.month]} {dt.day:02d}, {dt.year}"


def format_date_short(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return f"{PT_MONTHS_SHORT[dt.month]} {dt.day:02d}"


def format_date_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d")


def format_views(views: int) -> str:
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M"
    if views >= 1_000:
        return f"{views / 1_000:.1f}k"
    return str(views)


def category_label(slug: str) -> str:
    meta = CATEGORY_METADATA.get(slug)
    return meta["name"] if meta else slug.title()


def month_header_label(year: int, month: int) -> str:
    return f"{PT_MONTHS_FULL[month]} {year}"


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.autoescape = True
templates.env.filters["date_full"] = format_date_full
templates.env.filters["date_short"] = format_date_short
templates.env.filters["date_iso"] = format_date_iso
templates.env.filters["views_compact"] = format_views
templates.env.filters["category_label"] = category_label

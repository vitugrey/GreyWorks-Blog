from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import markdown
import nh3
import yaml

from app.schemas import CategoryEnum, normalize_tag_list, slugify

ALLOWED_MD_EXTENSIONS = {".md", ".markdown"}

ALLOWED_HTML_TAGS: set[str] = {
    "a",
    "abbr",
    "blockquote",
    "br",
    "code",
    "dd",
    "del",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "img",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}

ALLOWED_HTML_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title", "class"},
    "code": {"class"},
    "div": {"class"},
    "h1": {"id"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "h5": {"id"},
    "h6": {"id"},
    "img": {"src", "alt", "title", "loading"},
    "li": {"id", "class"},
    "ol": {"start"},
    "pre": {"class"},
    "span": {"class"},
    "sup": {"id"},
    "table": {"class"},
    "td": {"align"},
    "th": {"align"},
}

FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.DOTALL)
H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
PLAIN_TEXT_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RenderedMarkdown:
    content_html: str
    toc_html: str
    reading_time_min: int
    plain_excerpt: str


@dataclass(frozen=True)
class ParsedMarkdownDocument:
    title: str
    slug: str | None
    summary: str
    category: CategoryEnum
    tags: list[str]
    content_md: str
    is_published: bool
    published_at: datetime | None


def render_markdown(content_md: str) -> RenderedMarkdown:
    md = markdown.Markdown(
        extensions=[
            "extra",
            "sane_lists",
            "footnotes",
            "toc",
            "pymdownx.highlight",
            "pymdownx.superfences",
        ],
        extension_configs={
            "toc": {
                "permalink": False,
                "toc_depth": "2-3",
            },
            "pymdownx.highlight": {
                "use_pygments": True,
                "css_class": "codehilite",
                "linenums": False,
                "guess_lang": False,
            },
        },
        output_format="html",
    )

    raw_html = md.convert(content_md)
    raw_toc = getattr(md, "toc", "") or ""
    toc_tokens = getattr(md, "toc_tokens", []) or []

    safe_html = nh3.clean(
        raw_html,
        tags=ALLOWED_HTML_TAGS,
        attributes=ALLOWED_HTML_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        strip_comments=True,
    )

    safe_toc = ""
    if len(toc_tokens) >= 2 and raw_toc.strip():
        safe_toc = nh3.clean(
            raw_toc,
            tags={"div", "ul", "li", "a"},
            attributes={"div": {"class"}, "a": {"href"}},
            url_schemes={"http", "https"},
            strip_comments=True,
        )

    plain = WHITESPACE_RE.sub(" ", PLAIN_TEXT_RE.sub(" ", safe_html)).strip()
    words = len(plain.split()) if plain else 0
    reading_time_min = max(1, math.ceil(words / 200))

    excerpt = plain[:220].rsplit(" ", 1)[0].strip() + "..." if len(plain) > 220 else plain

    return RenderedMarkdown(
        content_html=safe_html,
        toc_html=safe_toc,
        reading_time_min=reading_time_min,
        plain_excerpt=excerpt,
    )


def validate_markdown_upload(filename: str | None, payload: bytes, max_bytes: int) -> str:
    if not filename:
        raise ValueError("Arquivo .md não informado.")

    safe_name = Path(filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_MD_EXTENSIONS:
        raise ValueError("Formato inválido. Envie apenas arquivos .md ou .markdown.")

    if not payload:
        raise ValueError("O arquivo .md enviado está vazio.")

    if len(payload) > max_bytes:
        raise ValueError(f"Arquivo excede o limite permitido de {max_bytes // (1024 * 1024)} MB.")

    if b"\x00" in payload:
        raise ValueError("Arquivo binário rejeitado. Envie apenas texto Markdown UTF-8.")

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Não foi possível decodificar o arquivo como UTF-8 válido.") from exc

    if not text.strip():
        raise ValueError("O arquivo Markdown não possui conteúdo legível.")

    return text


def _parse_category(raw_category: object, fallback: CategoryEnum) -> CategoryEnum:
    if not raw_category:
        return fallback
    value = str(raw_category).strip().lower()
    aliases = {
        "tec": CategoryEnum.TECNOLOGIA,
        "tech": CategoryEnum.TECNOLOGIA,
        "tecnologia": CategoryEnum.TECNOLOGIA,
        "geek": CategoryEnum.GEEK,
        "off-topic": CategoryEnum.OFF_TOPIC,
        "offtopic": CategoryEnum.OFF_TOPIC,
        "off_topic": CategoryEnum.OFF_TOPIC,
    }
    if value in aliases:
        return aliases[value]
    return fallback


def _parse_published_at(raw_date: object) -> datetime | None:
    if raw_date is None:
        return None
    if isinstance(raw_date, datetime):
        return (
            raw_date.replace(tzinfo=timezone.utc)
            if raw_date.tzinfo is None
            else raw_date.astimezone(timezone.utc)
        )
    if isinstance(raw_date, date):
        return datetime(raw_date.year, raw_date.month, raw_date.day, 12, 0, tzinfo=timezone.utc)
    if isinstance(raw_date, str) and raw_date.strip():
        text = raw_date.strip()
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        try:
            parsed_iso = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return (
                parsed_iso.replace(tzinfo=timezone.utc)
                if parsed_iso.tzinfo is None
                else parsed_iso.astimezone(timezone.utc)
            )
        except ValueError:
            return None
    return None


def parse_markdown_document(
    raw_text: str,
    *,
    fallback_title: str = "Novo Post",
    fallback_category: CategoryEnum = CategoryEnum.TECNOLOGIA,
) -> ParsedMarkdownDocument:
    meta: dict[str, object] = {}
    body = raw_text.lstrip("\ufeff")

    match = FRONTMATTER_RE.match(body)
    if match:
        yaml_block = match.group(1)
        body = body[match.end() :].lstrip()
        try:
            loaded = yaml.safe_load(yaml_block)
            if isinstance(loaded, dict):
                meta = {str(k).strip().lower(): v for k, v in loaded.items()}
        except yaml.YAMLError as exc:
            raise ValueError("YAML frontmatter inválido no arquivo .md.") from exc

    title = str(meta.get("title") or meta.get("titulo") or "").strip()
    if not title:
        h1_match = H1_RE.search(body)
        if h1_match:
            title = h1_match.group(1).strip()
            body = H1_RE.sub("", body, count=1).lstrip()
        else:
            title = fallback_title.strip() or "Novo Post"

    raw_slug = meta.get("slug")
    slug = slugify(str(raw_slug)) if raw_slug else None

    category = _parse_category(
        meta.get("category") or meta.get("categoria"),
        fallback=fallback_category,
    )

    raw_tags = meta.get("tags") or meta.get("hashtags") or []
    tags = normalize_tag_list(raw_tags if isinstance(raw_tags, (list, str)) else [])

    summary = str(meta.get("summary") or meta.get("resumo") or "").strip()
    if not summary and body.strip():
        summary = render_markdown(body).plain_excerpt[:400]

    published_flag = meta.get("is_published", meta.get("published", meta.get("publicado", True)))
    is_published = bool(published_flag)

    published_at = _parse_published_at(
        meta.get("published_at") or meta.get("date") or meta.get("data")
    )

    if not body.strip():
        raise ValueError("O corpo do arquivo Markdown está vazio.")

    return ParsedMarkdownDocument(
        title=title[:200],
        slug=slug,
        summary=summary[:420],
        category=category,
        tags=tags,
        content_md=body.strip(),
        is_published=is_published,
        published_at=published_at,
    )

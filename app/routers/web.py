from __future__ import annotations

from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.schemas import CATEGORY_METADATA, CategoryEnum, slugify
from app.security import get_client_ip
from app.services import media_service, post_service
from app.templates_env import templates

router = APIRouter()


def _resolve_view_mode(view: str | None) -> str:
    return "lista" if view == "lista" else "grade"


def _base_context(
    request: Request,
    settings: Settings,
    *,
    active_nav: str,
    page_title: str,
    page_description: str | None = None,
    search_query: str = "",
) -> dict[str, object]:
    return {
        "request": request,
        "settings": settings,
        "active_nav": active_nav,
        "page_title": page_title,
        "page_description": page_description or settings.site_description,
        "search_query": search_query,
        "categories": CATEGORY_METADATA,
    }


@router.get("/", response_class=HTMLResponse, name="home")
def home_page(
    request: Request,
    view: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    featured_posts = post_service.get_featured_posts(db, limit=3)
    all_posts = post_service.list_published_posts(db)
    month_groups = post_service.group_posts_by_month(all_posts)
    view_mode = _resolve_view_mode(view)

    context = _base_context(
        request,
        settings,
        active_nav="blog",
        page_title=settings.site_title,
    )
    context.update(
        {
            "featured_posts": featured_posts,
            "month_groups": month_groups,
            "total_posts": len(all_posts),
            "view_mode": view_mode,
        }
    )
    return templates.TemplateResponse(request, "index.html", context)


@router.get("/categoria/{category_slug}", response_class=HTMLResponse, name="category_page")
def category_page(
    request: Request,
    category_slug: str,
    view: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    normalized = category_slug.strip().lower()
    if normalized not in CATEGORY_METADATA:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    meta = CATEGORY_METADATA[normalized]
    posts = post_service.list_published_posts(db, category=normalized)
    month_groups = post_service.group_posts_by_month(posts)
    view_mode = _resolve_view_mode(view)

    context = _base_context(
        request,
        settings,
        active_nav=normalized,
        page_title=f"{meta['name']} — {settings.site_title}",
        page_description=meta["description"],
    )
    context.update(
        {
            "listing_heading": meta["name"],
            "listing_subtitle": meta["description"],
            "listing_badge": "Categoria",
            "month_groups": month_groups,
            "total_posts": len(posts),
            "view_mode": view_mode,
        }
    )
    return templates.TemplateResponse(request, "category.html", context)


@router.get("/tag/{tag_slug}", response_class=HTMLResponse, name="tag_page")
def tag_page(
    request: Request,
    tag_slug: str,
    view: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    clean_tag = slugify(tag_slug, max_length=48)
    posts = post_service.list_published_posts(db, tag_slug=clean_tag)
    month_groups = post_service.group_posts_by_month(posts)
    view_mode = _resolve_view_mode(view)

    context = _base_context(
        request,
        settings,
        active_nav="blog",
        page_title=f"#{clean_tag} — {settings.site_title}",
        page_description=f"Artigos marcados com #{clean_tag} no {settings.site_title}.",
    )
    context.update(
        {
            "listing_heading": f"#{clean_tag}",
            "listing_subtitle": f"Todos os artigos publicados com a tag #{clean_tag}.",
            "listing_badge": "Hashtag",
            "month_groups": month_groups,
            "total_posts": len(posts),
            "view_mode": view_mode,
        }
    )
    return templates.TemplateResponse(request, "category.html", context)


@router.get("/buscar", response_class=HTMLResponse, name="search_page")
def search_page(
    request: Request,
    q: str = Query(default="", max_length=120),
    view: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    clean_query = q.strip()
    posts = post_service.list_published_posts(db, query=clean_query) if clean_query else []
    month_groups = post_service.group_posts_by_month(posts)
    view_mode = _resolve_view_mode(view)

    heading = f'Resultados para "{clean_query}"' if clean_query else "Pesquisar artigos"
    subtitle = (
        f"{len(posts)} resultado(s) encontrado(s) em títulos, resumos, texto e hashtags."
        if clean_query
        else "Digite um termo, assunto ou #hashtag na barra acima para buscar."
    )

    context = _base_context(
        request,
        settings,
        active_nav="blog",
        page_title=f"Busca — {settings.site_title}",
        search_query=clean_query,
    )
    context.update(
        {
            "listing_heading": heading,
            "listing_subtitle": subtitle,
            "listing_badge": "Pesquisa",
            "month_groups": month_groups,
            "total_posts": len(posts),
            "view_mode": view_mode,
        }
    )
    return templates.TemplateResponse(request, "category.html", context)


@router.get("/post/{slug}", response_class=HTMLResponse, name="post_detail")
def post_detail(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    post = post_service.get_post_by_slug(db, slug)
    if post is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")

    viewer_fp = f"{get_client_ip(request)}:{request.headers.get('User-Agent', '')[:120]}"
    post_service.record_post_view(db, post, viewer_fp, settings.view_dedup_seconds)

    prev_post, next_post = post_service.get_adjacent_posts(db, post)

    context = _base_context(
        request,
        settings,
        active_nav=post.category,
        page_title=f"{post.title} — {settings.site_title}",
        page_description=post.summary or settings.site_description,
    )
    context.update(
        {
            "post": post,
            "prev_post": prev_post,
            "next_post": next_post,
        }
    )
    return templates.TemplateResponse(request, "post.html", context)


@router.get("/sobre", response_class=HTMLResponse, name="about_page")
def about_page(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    context = _base_context(
        request,
        settings,
        active_nav="sobre",
        page_title=f"Sobre — {settings.site_title}",
        page_description="Sobre Vitor Grey e a proposta minimalista do GreyWorks Blog.",
    )
    return templates.TemplateResponse(request, "about.html", context)


@router.get("/rss.xml", name="rss_feed")
def rss_feed(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    posts = post_service.list_published_posts(db)[:30]
    items_xml: list[str] = []
    for post in posts:
        link = f"{settings.site_url}/post/{escape(post.slug)}"
        pub_date = format_datetime(post.published_at)
        categories_xml = "".join(
            f"<category>{escape(tag.slug)}</category>" for tag in post.tags
        )
        items_xml.append(
            f"""    <item>
      <title>{escape(post.title)}</title>
      <link>{link}</link>
      <guid isPermaLink="true">{link}</guid>
      <pubDate>{escape(pub_date)}</pubDate>
      <description>{escape(post.summary)}</description>
      {categories_xml}
    </item>"""
        )

    xml_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape(settings.site_title)}</title>
    <link>{escape(settings.site_url)}</link>
    <description>{escape(settings.site_description)}</description>
    <language>pt-br</language>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
    return Response(content=xml_body, media_type="application/rss+xml; charset=utf-8")


@router.get("/sitemap.xml", name="sitemap_xml")
def sitemap_xml(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    posts = post_service.list_published_posts(db)
    urls = [
        f"  <url><loc>{escape(settings.site_url)}/</loc></url>",
        f"  <url><loc>{escape(settings.site_url)}/sobre</loc></url>",
    ]
    for category in CategoryEnum:
        urls.append(
            f"  <url><loc>{escape(settings.site_url)}/categoria/{escape(category.value)}</loc></url>"
        )
    for post in posts:
        lastmod = post.updated_at.strftime("%Y-%m-%d")
        urls.append(
            f"  <url><loc>{escape(settings.site_url)}/post/{escape(post.slug)}</loc>"
            f"<lastmod>{lastmod}</lastmod></url>"
        )

    xml_body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )
    return Response(content=xml_body, media_type="application/xml; charset=utf-8")


@router.get("/media/{filename}", name="serve_media")
def serve_media(
    filename: str,
    settings: Settings = Depends(get_settings),
):
    resolved = media_service.resolve_media_path(filename, Path(settings.upload_dir))
    if resolved is None:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    file_path, content_type = resolved
    # TODO(security): Imagens raster validadas por magic bytes (PNG/JPG/WebP/GIF, sem SVG)
    # são servidas inline para renderização em <img> com X-Content-Type-Options: nosniff.
    return FileResponse(
        path=file_path,
        media_type=content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@router.get("/health", name="healthcheck")
def healthcheck(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "error"}, status_code=503)
    return JSONResponse({"status": "ok"})

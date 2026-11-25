from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import AdminSession, AdminUser
from app.schemas import CATEGORY_METADATA, CategoryEnum, PostCreate, PostUpdate
from app.security import (
    clear_session_cookie,
    create_admin_session,
    get_active_admin_session,
    get_session_csrf_token,
    invalidate_user_sessions,
    issue_login_csrf_token,
    require_admin_session,
    set_session_cookie,
    verify_login_csrf_token,
    verify_password,
    verify_session_csrf_token,
)
from app.services import media_service, post_service
from app.templates_env import templates

router = APIRouter(prefix="/admin", tags=["admin"])


def _parse_datetime_input(raw_value: str | None) -> datetime | None:
    if not raw_value or not raw_value.strip():
        return None
    text = raw_value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(hour=12 if fmt == "%Y-%m-%d" else dt.hour, tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError("Data inválida. Utilize o formato AAAA-MM-DD.")


def _admin_context(
    request: Request,
    settings: Settings,
    *,
    page_title: str,
    csrf_token: str,
    admin_user: AdminUser | None = None,
) -> dict[str, object]:
    return {
        "request": request,
        "settings": settings,
        "active_nav": "admin",
        "page_title": f"{page_title} — Admin | {settings.site_title}",
        "page_description": "Painel editorial GreyWorks.",
        "search_query": "",
        "categories": CATEGORY_METADATA,
        "csrf_token": csrf_token,
        "admin_user": admin_user,
    }


@router.get("/login", response_class=HTMLResponse, name="admin_login_form")
def admin_login_form(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if get_active_admin_session(request, db, settings) is not None:
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)

    has_admin = db.execute(select(AdminUser.id).limit(1)).scalar_one_or_none() is not None
    context = _admin_context(request, settings, page_title="Login", csrf_token="")
    context.update({"error": None, "has_admin": has_admin})

    response = templates.TemplateResponse(request, "admin/login.html", context)
    token = issue_login_csrf_token(response, settings)
    context["csrf_token"] = token
    # Re-render with the issued token while preserving Set-Cookie header
    final_response = templates.TemplateResponse(request, "admin/login.html", context)
    for key, value in response.raw_headers:
        if key.lower() == b"set-cookie":
            final_response.raw_headers.append((key, value))
    return final_response


@router.post("/login", response_class=HTMLResponse, name="admin_login_submit")
def admin_login_submit(
    request: Request,
    username: str = Form(default=""),
    password: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not verify_login_csrf_token(request, csrf_token, settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF inválido.")

    clean_username = username.strip()
    user = db.execute(
        select(AdminUser).where(AdminUser.username == clean_username)
    ).scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(user.password_hash, password):
        has_admin = db.execute(select(AdminUser.id).limit(1)).scalar_one_or_none() is not None
        context = _admin_context(request, settings, page_title="Login", csrf_token="")
        context.update({"error": "Usuário ou senha inválidos.", "has_admin": has_admin})
        temp_resp = templates.TemplateResponse(request, "admin/login.html", context)
        new_token = issue_login_csrf_token(temp_resp, settings)
        context["csrf_token"] = new_token
        final_resp = templates.TemplateResponse(
            request, "admin/login.html", context, status_code=status.HTTP_401_UNAUTHORIZED
        )
        for key, value in temp_resp.raw_headers:
            if key.lower() == b"set-cookie":
                final_resp.raw_headers.append((key, value))
        return final_resp

    raw_token, _session = create_admin_session(db, user, settings)
    redirect = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(redirect, raw_token, settings)
    redirect.delete_cookie(
        key=settings.csrf_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return redirect


@router.post("/logout", name="admin_logout")
def admin_logout(
    csrf_token: str = Form(default=""),
    admin_session: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not verify_session_csrf_token(admin_session, csrf_token, settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF inválido.")

    invalidate_user_sessions(db, admin_session.user_id)
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response, settings)
    return response


@router.get("", response_class=HTMLResponse, name="admin_dashboard")
def admin_dashboard(
    request: Request,
    q: str = Query(default="", max_length=120),
    category: str = Query(default=""),
    msg: str | None = None,
    admin_session: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    clean_q = q.strip()
    clean_category = category.strip().lower()
    if clean_category not in CATEGORY_METADATA:
        clean_category = ""

    posts = post_service.list_all_posts_admin(
        db,
        category=clean_category or None,
        query=clean_q or None,
    )
    csrf_token = get_session_csrf_token(admin_session, settings)

    context = _admin_context(
        request,
        settings,
        page_title="Artigos",
        csrf_token=csrf_token,
        admin_user=admin_session.user,
    )
    context.update(
        {
            "posts": posts,
            "filter_q": clean_q,
            "filter_category": clean_category,
            "flash_msg": msg,
            "error": None,
        }
    )
    return templates.TemplateResponse(request, "admin/dashboard.html", context)


@router.get("/posts/new", response_class=HTMLResponse, name="admin_post_new")
def admin_post_new(
    request: Request,
    admin_session: AdminSession = Depends(require_admin_session),
    settings: Settings = Depends(get_settings),
):
    context = _admin_context(
        request,
        settings,
        page_title="Novo artigo",
        csrf_token=get_session_csrf_token(admin_session, settings),
        admin_user=admin_session.user,
    )
    context.update({"post": None, "error": None, "flash_msg": None, "form_data": {}})
    return templates.TemplateResponse(request, "admin/editor.html", context)


@router.post("/posts/new", response_class=HTMLResponse, name="admin_post_create")
def admin_post_create(
    request: Request,
    title: str = Form(default=""),
    summary: str = Form(default=""),
    category: str = Form(default="tecnologia"),
    tags: str = Form(default=""),
    published_at: str = Form(default=""),
    is_published: str | None = Form(default=None),
    content_md: str = Form(default=""),
    csrf_token: str = Form(default=""),
    admin_session: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not verify_session_csrf_token(admin_session, csrf_token, settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF inválido.")

    try:
        data = PostCreate(
            title=title.strip(),
            summary=summary.strip(),
            category=CategoryEnum(category),
            content_md=content_md.strip(),
            tags=tags,  # type: ignore[arg-type]
            is_published=is_published == "on",
            published_at=_parse_datetime_input(published_at),
        )
        post = post_service.create_post(db, data)
        return RedirectResponse(
            url=f"/admin/posts/{post.id}/edit?msg=created",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ValidationError) as exc:
        context = _admin_context(
            request,
            settings,
            page_title="Novo artigo",
            csrf_token=get_session_csrf_token(admin_session, settings),
            admin_user=admin_session.user,
        )
        context.update(
            {
                "post": None,
                "error": str(exc),
                "flash_msg": None,
                "form_data": {
                    "title": title,
                    "summary": summary,
                    "category": category,
                    "tags": tags,
                    "published_at": published_at,
                    "is_published": is_published == "on",
                    "content_md": content_md,
                },
            }
        )
        return templates.TemplateResponse(
            request, "admin/editor.html", context, status_code=status.HTTP_400_BAD_REQUEST
        )


@router.get("/posts/{post_id}/edit", response_class=HTMLResponse, name="admin_post_edit")
def admin_post_edit(
    request: Request,
    post_id: int,
    msg: str | None = None,
    admin_session: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    post = post_service.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")

    context = _admin_context(
        request,
        settings,
        page_title=f"Editar: {post.title}",
        csrf_token=get_session_csrf_token(admin_session, settings),
        admin_user=admin_session.user,
    )
    context.update({"post": post, "error": None, "flash_msg": msg, "form_data": {}})
    return templates.TemplateResponse(request, "admin/editor.html", context)


@router.post("/posts/{post_id}/edit", response_class=HTMLResponse, name="admin_post_update")
def admin_post_update(
    request: Request,
    post_id: int,
    title: str = Form(default=""),
    summary: str = Form(default=""),
    category: str = Form(default="tecnologia"),
    tags: str = Form(default=""),
    published_at: str = Form(default=""),
    is_published: str | None = Form(default=None),
    content_md: str = Form(default=""),
    csrf_token: str = Form(default=""),
    admin_session: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not verify_session_csrf_token(admin_session, csrf_token, settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF inválido.")

    post = post_service.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")

    try:
        data = PostUpdate(
            title=title.strip(),
            summary=summary.strip(),
            category=CategoryEnum(category),
            content_md=content_md.strip(),
            tags=tags,  # type: ignore[arg-type]
            is_published=is_published == "on",
            published_at=_parse_datetime_input(published_at) or post.published_at,
        )
        post_service.update_post(db, post, data)
        return RedirectResponse(
            url=f"/admin/posts/{post.id}/edit?msg=updated",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except (ValueError, ValidationError) as exc:
        context = _admin_context(
            request,
            settings,
            page_title=f"Editar: {post.title}",
            csrf_token=get_session_csrf_token(admin_session, settings),
            admin_user=admin_session.user,
        )
        context.update({"post": post, "error": str(exc), "flash_msg": None, "form_data": {}})
        return templates.TemplateResponse(
            request, "admin/editor.html", context, status_code=status.HTTP_400_BAD_REQUEST
        )


@router.post("/media/upload", name="admin_upload_image")
async def admin_upload_image(
    image: UploadFile = File(...),
    alt: str = Form(default="imagem"),
    csrf_token: str = Form(default=""),
    admin_session: AdminSession = Depends(require_admin_session),
    settings: Settings = Depends(get_settings),
):
    if not verify_session_csrf_token(admin_session, csrf_token, settings):
        return JSONResponse({"detail": "Token CSRF inválido."}, status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = await image.read(settings.max_image_upload_bytes + 1)
        saved = media_service.save_uploaded_image(
            filename=image.filename,
            payload=payload,
            upload_dir=Path(settings.upload_dir),
            max_bytes=settings.max_image_upload_bytes,
            alt_text=alt or Path(image.filename or "imagem").stem,
        )
        return JSONResponse(
            {
                "url": saved.url,
                "markdown": saved.markdown,
                "filename": saved.filename,
            },
            status_code=status.HTTP_201_CREATED,
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/posts/{post_id}/delete", name="admin_post_delete")
def admin_post_delete(
    post_id: int,
    csrf_token: str = Form(default=""),
    admin_session: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not verify_session_csrf_token(admin_session, csrf_token, settings):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF inválido.")

    post = post_service.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")

    post_service.delete_post(db, post)
    return RedirectResponse(url="/admin?msg=deleted", status_code=status.HTTP_303_SEE_OTHER)

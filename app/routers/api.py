from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.schemas import CategoryEnum, PostCreate, PostListItem, PostRead, PostUpdate
from app.security import require_api_token
from app.services import markdown_service, media_service, post_service

router = APIRouter(
    prefix="/api/v1",
    tags=["api"],
    dependencies=[Depends(require_api_token)],
)


@router.get("/posts", response_model=list[PostListItem])
def api_list_posts(
    category: CategoryEnum | None = Query(default=None),
    tag: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
):
    posts = post_service.list_published_posts(
        db,
        category=category.value if category else None,
        tag_slug=tag,
        query=q,
    )
    return posts


@router.get("/posts/featured", response_model=list[PostListItem])
def api_featured_posts(db: Session = Depends(get_db)):
    return post_service.get_featured_posts(db, limit=3)


@router.get("/posts/{slug}", response_model=PostRead)
def api_get_post(slug: str, db: Session = Depends(get_db)):
    post = post_service.get_post_by_slug(db, slug, include_unpublished=True)
    if post is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")
    return post


@router.post("/posts", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def api_create_post(payload: PostCreate, db: Session = Depends(get_db)):
    return post_service.create_post(db, payload)


@router.post("/posts/upload-md", response_model=PostRead, status_code=status.HTTP_201_CREATED)
async def api_upload_markdown(
    file: UploadFile = File(...),
    category: CategoryEnum = Form(default=CategoryEnum.TECNOLOGIA),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        raw_bytes = await file.read(settings.max_markdown_upload_bytes + 1)
        raw_text = markdown_service.validate_markdown_upload(
            file.filename, raw_bytes, settings.max_markdown_upload_bytes
        )
        fallback_title = Path(file.filename or "novo-post.md").stem.replace("-", " ").title()
        parsed = markdown_service.parse_markdown_document(
            raw_text,
            fallback_title=fallback_title,
            fallback_category=category,
        )
        data = PostCreate(
            title=parsed.title,
            slug=parsed.slug,
            summary=parsed.summary,
            category=parsed.category,
            content_md=parsed.content_md,
            tags=parsed.tags,
            is_published=parsed.is_published,
            published_at=parsed.published_at,
        )
        return post_service.create_post(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/media/upload", status_code=status.HTTP_201_CREATED)
async def api_upload_image(
    file: UploadFile = File(...),
    alt: str = Form(default="imagem"),
    settings: Settings = Depends(get_settings),
):
    try:
        payload = await file.read(settings.max_image_upload_bytes + 1)
        saved = media_service.save_uploaded_image(
            filename=file.filename,
            payload=payload,
            upload_dir=Path(settings.upload_dir),
            max_bytes=settings.max_image_upload_bytes,
            alt_text=alt or Path(file.filename or "imagem").stem,
        )
        return {
            "url": saved.url,
            "markdown": saved.markdown,
            "filename": saved.filename,
            "content_type": saved.content_type,
            "size_bytes": saved.size_bytes,
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/posts/{post_id}/update", response_model=PostRead)
def api_update_post(post_id: int, payload: PostUpdate, db: Session = Depends(get_db)):
    post = post_service.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")
    return post_service.update_post(db, post, payload)


@router.post("/posts/{post_id}/delete", status_code=status.HTTP_200_OK)
def api_delete_post(post_id: int, db: Session = Depends(get_db)):
    post = post_service.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Artigo não encontrado.")
    post_service.delete_post(db, post)
    return {"status": "deleted", "id": post_id}

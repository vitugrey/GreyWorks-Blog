from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Post, Tag, utc_now
from app.schemas import PostCreate, PostUpdate, slugify
from app.services.markdown_service import render_markdown
from app.templates_env import month_header_label


@dataclass(frozen=True)
class MonthGroup:
    year: int
    month: int
    label: str
    count_label: str
    posts: list[Post]


class ViewDeduplicator:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def should_count(self, post_id: int, viewer_fingerprint: str, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            return True
        now = time.monotonic()
        key = hashlib.sha256(f"{post_id}:{viewer_fingerprint}".encode("utf-8")).hexdigest()
        with self._lock:
            if len(self._seen) > 10_000:
                expired = [k for k, ts in self._seen.items() if now - ts > ttl_seconds]
                for k in expired:
                    self._seen.pop(k, None)
            last_seen = self._seen.get(key)
            if last_seen is not None and (now - last_seen) < ttl_seconds:
                return False
            self._seen[key] = now
            return True

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()


view_deduplicator = ViewDeduplicator()


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ensure_unique_slug(db: Session, base_slug: str, exclude_post_id: int | None = None) -> str:
    candidate = slugify(base_slug)
    suffix = 2
    while True:
        stmt = select(Post.id).where(Post.slug == candidate)
        if exclude_post_id is not None:
            stmt = stmt.where(Post.id != exclude_post_id)
        existing = db.execute(stmt).scalar_one_or_none()
        if existing is None:
            return candidate
        candidate = f"{slugify(base_slug, max_length=170)}-{suffix}"
        suffix += 1


def _resolve_tags(db: Session, tag_slugs: list[str]) -> list[Tag]:
    if not tag_slugs:
        return []
    existing_stmt = select(Tag).where(Tag.slug.in_(tag_slugs))
    existing_tags = {tag.slug: tag for tag in db.execute(existing_stmt).scalars().all()}
    tags: list[Tag] = []
    for slug in tag_slugs:
        tag = existing_tags.get(slug)
        if tag is None:
            tag = Tag(name=slug, slug=slug)
            db.add(tag)
            existing_tags[slug] = tag
        tags.append(tag)
    return tags


def get_featured_posts(db: Session, limit: int = 3) -> list[Post]:
    stmt = (
        select(Post)
        .options(selectinload(Post.tags))
        .where(Post.is_published.is_(True))
        .order_by(Post.views.desc(), Post.published_at.desc(), Post.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_published_posts(
    db: Session,
    *,
    category: str | None = None,
    tag_slug: str | None = None,
    query: str | None = None,
) -> list[Post]:
    stmt = (
        select(Post)
        .options(selectinload(Post.tags))
        .where(Post.is_published.is_(True))
    )

    if category:
        stmt = stmt.where(Post.category == category)

    if tag_slug:
        stmt = stmt.join(Post.tags).where(Tag.slug == tag_slug)

    if query and query.strip():
        escaped = f"%{_escape_like(query.strip())}%"
        tag_subquery = (
            select(Post.id)
            .join(Post.tags)
            .where(Tag.slug.ilike(escaped, escape="\\"))
        )
        stmt = stmt.where(
            or_(
                Post.title.ilike(escaped, escape="\\"),
                Post.summary.ilike(escaped, escape="\\"),
                Post.content_md.ilike(escaped, escape="\\"),
                Post.id.in_(tag_subquery),
            )
        )

    stmt = stmt.order_by(Post.published_at.desc(), Post.id.desc())
    return list(db.execute(stmt).scalars().unique().all())


def list_all_posts_admin(
    db: Session,
    *,
    category: str | None = None,
    query: str | None = None,
) -> list[Post]:
    stmt = select(Post).options(selectinload(Post.tags))

    if category:
        stmt = stmt.where(Post.category == category)

    if query and query.strip():
        escaped = f"%{_escape_like(query.strip())}%"
        tag_subquery = (
            select(Post.id)
            .join(Post.tags)
            .where(Tag.slug.ilike(escaped, escape="\\"))
        )
        stmt = stmt.where(
            or_(
                Post.title.ilike(escaped, escape="\\"),
                Post.summary.ilike(escaped, escape="\\"),
                Post.content_md.ilike(escaped, escape="\\"),
                Post.id.in_(tag_subquery),
            )
        )

    stmt = stmt.order_by(Post.published_at.desc(), Post.id.desc())
    return list(db.execute(stmt).scalars().unique().all())


def group_posts_by_month(posts: list[Post]) -> list[MonthGroup]:
    buckets: OrderedDict[tuple[int, int], list[Post]] = OrderedDict()
    for post in posts:
        key = (post.published_at.year, post.published_at.month)
        buckets.setdefault(key, []).append(post)

    groups: list[MonthGroup] = []
    for (year, month), items in buckets.items():
        count = len(items)
        count_label = "1 artigo" if count == 1 else f"{count} artigos"
        groups.append(
            MonthGroup(
                year=year,
                month=month,
                label=month_header_label(year, month),
                count_label=count_label,
                posts=items,
            )
        )
    return groups


def get_post_by_slug(db: Session, slug: str, *, include_unpublished: bool = False) -> Post | None:
    stmt = select(Post).options(selectinload(Post.tags)).where(Post.slug == slug)
    if not include_unpublished:
        stmt = stmt.where(Post.is_published.is_(True))
    return db.execute(stmt).scalar_one_or_none()


def get_post_by_id(db: Session, post_id: int) -> Post | None:
    stmt = select(Post).options(selectinload(Post.tags)).where(Post.id == post_id)
    return db.execute(stmt).scalar_one_or_none()


def get_adjacent_posts(db: Session, post: Post) -> tuple[Post | None, Post | None]:
    prev_stmt = (
        select(Post)
        .where(
            Post.is_published.is_(True),
            Post.id != post.id,
            Post.published_at <= post.published_at,
        )
        .order_by(Post.published_at.desc(), Post.id.desc())
        .limit(1)
    )
    next_stmt = (
        select(Post)
        .where(
            Post.is_published.is_(True),
            Post.id != post.id,
            Post.published_at >= post.published_at,
        )
        .order_by(Post.published_at.asc(), Post.id.asc())
        .limit(1)
    )
    return (
        db.execute(prev_stmt).scalar_one_or_none(),
        db.execute(next_stmt).scalar_one_or_none(),
    )


def record_post_view(
    db: Session,
    post: Post,
    viewer_fingerprint: str,
    ttl_seconds: int,
) -> bool:
    if not view_deduplicator.should_count(post.id, viewer_fingerprint, ttl_seconds):
        return False
    db.execute(update(Post).where(Post.id == post.id).values(views=Post.views + 1))
    db.commit()
    db.refresh(post)
    return True


def create_post(db: Session, data: PostCreate) -> Post:
    rendered = render_markdown(data.content_md)
    summary = data.summary.strip() or rendered.plain_excerpt[:400]
    slug = _ensure_unique_slug(db, data.slug or data.title)
    published_at = data.published_at or utc_now()

    post = Post(
        title=data.title,
        slug=slug,
        summary=summary,
        category=data.category.value,
        content_md=data.content_md,
        content_html=rendered.content_html,
        toc_html=rendered.toc_html,
        reading_time_min=rendered.reading_time_min,
        is_published=data.is_published,
        published_at=published_at,
    )
    post.tags = _resolve_tags(db, data.tags)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def update_post(db: Session, post: Post, data: PostUpdate) -> Post:
    if data.title is not None:
        post.title = data.title
    if data.slug is not None:
        post.slug = _ensure_unique_slug(db, data.slug, exclude_post_id=post.id)
    if data.category is not None:
        post.category = data.category.value
    if data.is_published is not None:
        post.is_published = data.is_published
    if data.published_at is not None:
        post.published_at = data.published_at
    if data.content_md is not None:
        rendered = render_markdown(data.content_md)
        post.content_md = data.content_md
        post.content_html = rendered.content_html
        post.toc_html = rendered.toc_html
        post.reading_time_min = rendered.reading_time_min
        if data.summary is None and not post.summary:
            post.summary = rendered.plain_excerpt[:400]
    if data.summary is not None:
        post.summary = data.summary.strip() or render_markdown(post.content_md).plain_excerpt[:400]
    if data.tags is not None:
        post.tags = _resolve_tags(db, data.tags)

    post.updated_at = utc_now()
    db.commit()
    db.refresh(post)
    return post


def delete_post(db: Session, post: Post) -> None:
    db.delete(post)
    db.commit()


def get_blog_stats(db: Session) -> dict[str, int]:
    total_posts = db.execute(select(func.count(Post.id))).scalar_one()
    published_posts = db.execute(
        select(func.count(Post.id)).where(Post.is_published.is_(True))
    ).scalar_one()
    total_views = db.execute(select(func.coalesce(func.sum(Post.views), 0))).scalar_one()
    total_tags = db.execute(select(func.count(Tag.id))).scalar_one()
    return {
        "total_posts": int(total_posts),
        "published_posts": int(published_posts),
        "draft_posts": int(total_posts - published_posts),
        "total_views": int(total_views),
        "total_tags": int(total_tags),
    }

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_greyworks.db"
os.environ["SECRET_KEY"] = "test-secret-key-with-at-least-32-characters-12345"
os.environ["API_TOKEN"] = "test-api-token-super-secret-value"
os.environ["COOKIE_SECURE"] = "false"
os.environ["UPLOAD_DIR"] = "test_uploads"

from app.config import get_settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import AdminUser  # noqa: E402
from app.schemas import CategoryEnum, PostCreate  # noqa: E402
from app.security import hash_password, rate_limiter  # noqa: E402
from app.services import post_service  # noqa: E402


@pytest.fixture()
def client():
    get_settings.cache_clear()
    rate_limiter.reset()
    post_service.view_deduplicator.reset()

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = AdminUser(
            username="vitor",
            password_hash=hash_password("SenhaForteGreyWorks!2026"),
            is_active=True,
        )
        db.add(admin)
        db.commit()

        posts_seed = [
            ("Post Tech 1", CategoryEnum.TECNOLOGIA, ["fastapi", "docker"], 300, datetime(2026, 11, 18, tzinfo=timezone.utc)),
            ("Post Geek 1", CategoryEnum.GEEK, ["retro", "games"], 500, datetime(2026, 11, 10, tzinfo=timezone.utc)),
            ("Post Off 1", CategoryEnum.OFF_TOPIC, ["design"], 200, datetime(2026, 10, 20, tzinfo=timezone.utc)),
            ("Post Tech 2", CategoryEnum.TECNOLOGIA, ["python"], 50, datetime(2026, 10, 5, tzinfo=timezone.utc)),
        ]
        for title, cat, tags, views, dt in posts_seed:
            post = post_service.create_post(
                db,
                PostCreate(
                    title=title,
                    category=cat,
                    tags=tags,
                    content_md=f"## {title}\n\nConteudo de teste sobre {title}.",
                    published_at=dt,
                ),
            )
            post.views = views
            db.commit()
    finally:
        db.close()

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if os.path.exists("test_greyworks.db"):
        os.remove("test_greyworks.db")
    if os.path.isdir("test_uploads"):
        import shutil
        shutil.rmtree("test_uploads")


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "CSRF token não encontrado no HTML"
    return match.group(1)


def _login_admin(client: TestClient) -> str:
    resp = client.get("/admin/login")
    assert resp.status_code == 200
    csrf = _extract_csrf(resp.text)
    post_resp = client.post(
        "/admin/login",
        data={"username": "vitor", "password": "SenhaForteGreyWorks!2026", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert post_resp.status_code == 303
    dash = client.get("/admin")
    assert dash.status_code == 200
    return _extract_csrf(dash.text)


def test_home_shows_top_3_destaques_and_monthly_groups(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text

    assert "Destaques" in body
    assert "Artigos recentes" in body
    assert "NOVEMBRO 2026" in body
    assert "OUTUBRO 2026" in body

    # Top 3 by views: Post Geek 1 (500), Post Tech 1 (300), Post Off 1 (200)
    featured_section = body.split("Artigos recentes")[0]
    assert "Post Geek 1" in featured_section
    assert "Post Tech 1" in featured_section
    assert "Post Off 1" in featured_section
    assert "Post Tech 2" not in featured_section

    # Security headers present
    assert "Content-Security-Policy" in resp.headers
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"


def test_category_pages_filter_posts_and_hide_destaques(client: TestClient):
    resp = client.get("/categoria/tecnologia")
    assert resp.status_code == 200
    assert "Destaques" not in resp.text
    assert "Post Tech 1" in resp.text
    assert "Post Tech 2" in resp.text
    assert "Post Geek 1" not in resp.text
    assert "Post Off 1" not in resp.text

    resp_geek = client.get("/categoria/geek?view=lista")
    assert resp_geek.status_code == 200
    assert "is-list" in resp_geek.text
    assert "Post Geek 1" in resp_geek.text
    assert "Post Tech 1" not in resp_geek.text


def test_post_detail_views_deduplication_and_search(client: TestClient):
    r1 = client.get("/post/post-tech-2")
    assert r1.status_code == 200
    assert "Post Tech 2" in r1.text
    assert "#python" in r1.text

    # Second immediate view from same client should be deduplicated
    r2 = client.get("/post/post-tech-2")
    assert r2.status_code == 200
    assert "51 visualizações" in r2.text

    search = client.get("/buscar?q=retro")
    assert search.status_code == 200
    assert "Post Geek 1" in search.text
    assert "Post Tech 1" not in search.text


def test_markdown_xss_sanitization(client: TestClient):
    csrf = _login_admin(client)
    malicious_md = (
        "## Seguro\n\n"
        '<script>alert("xss")</script>\n'
        '<a href="javascript:alert(1)">clique</a>\n'
        '<img src="x" onerror="alert(2)">\n'
    )
    resp = client.post(
        "/admin/posts/new",
        data={
            "title": "Teste XSS",
            "category": "tecnologia",
            "tags": "seguranca",
            "content_md": malicious_md,
            "is_published": "on",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    page = client.get("/post/teste-xss")
    assert page.status_code == 200
    assert "<script>" not in page.text
    assert "javascript:alert" not in page.text
    assert "onerror=" not in page.text


def test_admin_csrf_filter_and_upload_validation(client: TestClient):
    # Login without CSRF fails
    bad_login = client.post(
        "/admin/login",
        data={"username": "vitor", "password": "SenhaForteGreyWorks!2026", "csrf_token": "invalido"},
    )
    assert bad_login.status_code == 403

    csrf = _login_admin(client)

    # Admin search & category filter
    filtered = client.get("/admin?category=tecnologia&q=Tech+1")
    assert filtered.status_code == 200
    assert "Post Tech 1" in filtered.text
    assert "Post Geek 1" not in filtered.text
    assert "Post Tech 2" not in filtered.text

    # Disallowed image upload rejected
    bad_upload = client.post(
        "/admin/media/upload",
        data={"csrf_token": csrf},
        files={"image": ("shell.exe", b"MZ\x00\x01", "application/octet-stream")},
    )
    assert bad_upload.status_code == 400


def test_api_authentication_and_method_allowlist(client: TestClient):
    # Unauthenticated API rejected
    unauth = client.get("/api/v1/posts")
    assert unauth.status_code == 401

    headers = {"Authorization": "Bearer test-api-token-super-secret-value"}
    ok = client.get("/api/v1/posts", headers=headers)
    assert ok.status_code == 200
    assert len(ok.json()) == 4

    # Disallowed HTTP method rejected
    bad_method = client.delete("/api/v1/posts", headers=headers)
    assert bad_method.status_code == 405

    # RSS, Sitemap, About, Health
    assert client.get("/rss.xml").status_code == 200
    assert client.get("/sitemap.xml").status_code == 200
    assert client.get("/sobre").status_code == 200
    assert client.get("/health").status_code == 200


def test_auto_slug_and_image_upload_flow(client: TestClient):
    # Minimal valid PNG header + IHDR bytes
    valid_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    headers = {"Authorization": "Bearer test-api-token-super-secret-value"}

    # Upload valid image via API
    up = client.post(
        "/api/v1/media/upload",
        headers=headers,
        files={"file": ("diagrama.png", valid_png, "image/png")},
        data={"alt": "Diagrama GreyWorks"},
    )
    assert up.status_code == 201
    media = up.json()
    assert media["url"].startswith("/media/")
    assert media["markdown"] == f"![Diagrama GreyWorks]({media['url']})"

    # Image is served back with nosniff
    img_resp = client.get(media["url"])
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/png"
    assert img_resp.headers["x-content-type-options"] == "nosniff"

    # Fake PNG (wrong magic bytes) and SVG are rejected
    fake = client.post(
        "/api/v1/media/upload",
        headers=headers,
        files={"file": ("fake.png", b"<svg><script>alert(1)</script></svg>", "image/png")},
    )
    assert fake.status_code == 400

    # Create post without slug -> slug generated automatically from title + renders image
    created = client.post(
        "/api/v1/posts",
        headers=headers,
        json={
            "title": "Meu Artigo Com Imagem!",
            "category": "tecnologia",
            "tags": ["docker"],
            "content_md": f"## Foto\n\n{media['markdown']}",
        },
    )
    assert created.status_code == 201
    assert created.json()["slug"] == "meu-artigo-com-imagem"

    page = client.get("/post/meu-artigo-com-imagem")
    assert page.status_code == 200
    assert f'src="{media["url"]}"' in page.text

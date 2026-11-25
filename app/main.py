from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import admin, api, web
from app.schemas import CATEGORY_METADATA
from app.security import SecurityMiddleware, ensure_bootstrap_admin
from app.templates_env import templates

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_bootstrap_admin(db, settings)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.site_title,
        description=settings.site_description,
        docs_url="/api/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(SecurityMiddleware)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(web.router)
    app.include_router(admin.router)
    app.include_router(api.router)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=exc.headers,
            )
        if exc.status_code == 303 and exc.headers and "Location" in exc.headers:
            return HTMLResponse(
                content="",
                status_code=303,
                headers={"Location": exc.headers["Location"]},
            )
        context = {
            "request": request,
            "settings": get_settings(),
            "active_nav": "blog",
            "page_title": f"Erro {exc.status_code} — {get_settings().site_title}",
            "page_description": "Página não encontrada.",
            "search_query": "",
            "categories": CATEGORY_METADATA,
            "status_code": exc.status_code,
            "message": exc.detail if isinstance(exc.detail, str) else "Erro ao processar requisição.",
        }
        return templates.TemplateResponse(
            request, "error.html", context, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error while processing %s", request.url.path)
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"detail": "Erro interno do servidor."},
                status_code=500,
            )
        context = {
            "request": request,
            "settings": get_settings(),
            "active_nav": "blog",
            "page_title": f"Erro 500 — {get_settings().site_title}",
            "page_description": "Erro interno do servidor.",
            "search_query": "",
            "categories": CATEGORY_METADATA,
            "status_code": 500,
            "message": "Ocorreu um erro interno inesperado. Tente novamente em instantes.",
        }
        return templates.TemplateResponse(request, "error.html", context, status_code=500)

    return app


app = create_app()

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, PlainTextResponse

from app.config import Settings, get_settings
from app.database import get_db
from app.models import AdminSession, AdminUser, utc_now

password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
)

ALLOWED_HTTP_METHODS = {"GET", "HEAD", "POST", "OPTIONS"}


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise ValueError("A senha deve ter no mínimo 12 caracteres.")
    if len(password) > 128:
        raise ValueError("A senha deve ter no máximo 128 caracteres.")
    if not password.strip():
        raise ValueError("A senha não pode ser composta apenas por espaços.")
    # TODO(security): Integrar verificação de senhas vazadas (k-anonymity HIBP)
    # quando houver múltiplos usuários ou fluxo público de cadastro.


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, candidate: str) -> bool:
    try:
        return password_hasher.verify(password_hash, candidate)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sign_value(secret_key: str, value: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_admin_session(
    db: Session,
    user: AdminUser,
    settings: Settings,
) -> tuple[str, AdminSession]:
    raw_token = secrets.token_urlsafe(32)
    token_hash = _sha256_hex(raw_token)
    csrf_secret = secrets.token_hex(32)
    now = utc_now()
    expires_at = now + timedelta(hours=settings.session_ttl_hours)

    session = AdminSession(
        user_id=user.id,
        token_hash=token_hash,
        csrf_secret=csrf_secret,
        created_at=now,
        last_seen_at=now,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return raw_token, session


def set_session_cookie(response: Response, raw_token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def invalidate_user_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(AdminSession).where(AdminSession.user_id == user_id))
    db.commit()


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_active_admin_session(
    request: Request,
    db: Session,
    settings: Settings,
) -> AdminSession | None:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        return None

    token_hash = _sha256_hex(raw_token)
    stmt = select(AdminSession).where(AdminSession.token_hash == token_hash)
    session = db.execute(stmt).scalar_one_or_none()
    if session is None:
        return None

    now = utc_now()
    inactivity_limit = _as_utc(session.last_seen_at) + timedelta(
        minutes=settings.session_inactivity_minutes
    )
    if now > _as_utc(session.expires_at) or now > inactivity_limit:
        db.delete(session)
        db.commit()
        return None

    if not session.user or not session.user.is_active:
        invalidate_user_sessions(db, session.user_id)
        return None

    session.last_seen_at = now
    db.commit()
    return session


def get_session_csrf_token(session: AdminSession, settings: Settings) -> str:
    return _sign_value(settings.secret_key, f"session:{session.id}:{session.csrf_secret}")


def verify_session_csrf_token(
    session: AdminSession,
    submitted_token: str | None,
    settings: Settings,
) -> bool:
    if not submitted_token:
        return False
    expected = get_session_csrf_token(session, settings)
    return hmac.compare_digest(expected, submitted_token)


def issue_login_csrf_token(response: Response, settings: Settings) -> str:
    nonce = secrets.token_urlsafe(24)
    signature = _sign_value(settings.secret_key, f"login:{nonce}")
    token = f"{nonce}.{signature}"
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=1800,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return token


def verify_login_csrf_token(
    request: Request,
    submitted_token: str | None,
    settings: Settings,
) -> bool:
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    if not cookie_token or not submitted_token:
        return False
    if not hmac.compare_digest(cookie_token, submitted_token):
        return False
    if "." not in submitted_token:
        return False
    nonce, signature = submitted_token.split(".", 1)
    expected_sig = _sign_value(settings.secret_key, f"login:{nonce}")
    return hmac.compare_digest(expected_sig, signature)


def require_admin_session(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AdminSession:
    session = get_active_admin_session(request, db, settings)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"},
        )
    return session


def require_api_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    if not settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API token não configurado no servidor.",
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticação Bearer obrigatória.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    candidate = auth_header[7:].strip()
    if not candidate or not hmac.compare_digest(candidate, settings.api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "api-client"


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class SlidingWindowRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


rate_limiter = SlidingWindowRateLimiter()


class SecurityMiddleware(BaseHTTPMiddleware):
    """Enforces HTTP method allow-list, rate limits, and strict security headers."""

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() not in ALLOWED_HTTP_METHODS:
            return PlainTextResponse("Method Not Allowed", status_code=405)

        path = request.url.path
        client_ip = get_client_ip(request)

        if path == "/admin/login" and request.method.upper() == "POST":
            if not rate_limiter.allow(f"login:{client_ip}", limit=10, window_seconds=300):
                return PlainTextResponse(
                    "Muitas tentativas de login. Aguarde alguns minutos.",
                    status_code=429,
                )
        elif path.startswith("/api/"):
            if not rate_limiter.allow(f"api:{client_ip}", limit=60, window_seconds=60):
                return JSONResponse(
                    {"detail": "Limite de requisições excedido."},
                    status_code=429,
                )
        elif not path.startswith("/static/"):
            if not rate_limiter.allow(f"web:{client_ip}", limit=180, window_seconds=60):
                return PlainTextResponse("Limite de requisições excedido.", status_code=429)

        response = await call_next(request)

        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' https: data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )

        if path.startswith("/admin") or path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"

        return response


def ensure_bootstrap_admin(db: Session, settings: Settings) -> None:
    """Optionally creates the initial admin user if env vars are provided and none exists."""
    # TODO(security): Para ambientes com múltiplos autores, considerar OAuth 2.0 / OIDC e MFA.
    if not settings.admin_username or not settings.admin_password:
        return

    existing = db.execute(select(AdminUser).limit(1)).scalar_one_or_none()
    if existing is not None:
        return

    validate_password_strength(settings.admin_password)
    admin = AdminUser(
        username=settings.admin_username.strip(),
        password_hash=hash_password(settings.admin_password),
        is_active=True,
    )
    db.add(admin)
    db.commit()

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

ALLOWED_IMAGE_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

SAFE_MEDIA_FILENAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")


@dataclass(frozen=True)
class SavedMedia:
    filename: str
    url: str
    markdown: str
    content_type: str
    size_bytes: int


def _detect_image_type(payload: bytes) -> tuple[str, str] | None:
    """Validates image magic bytes strictly (allow-list: PNG, JPEG, WebP, GIF)."""
    if len(payload) < 12:
        return None
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    return None


def save_uploaded_image(
    *,
    filename: str | None,
    payload: bytes,
    upload_dir: Path,
    max_bytes: int,
    alt_text: str = "imagem",
) -> SavedMedia:
    if not filename:
        raise ValueError("Nenhuma imagem informada.")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Formato inválido. Use apenas PNG, JPG, WebP ou GIF.")

    if not payload:
        raise ValueError("O arquivo de imagem está vazio.")

    if len(payload) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise ValueError(f"Imagem excede o limite permitido de {limit_mb} MB.")

    detected = _detect_image_type(payload)
    if detected is None:
        raise ValueError("Conteúdo da imagem inválido ou corrompido.")

    canonical_ext, content_type = detected
    # Garante que extensão informada corresponde ao tipo real (ex: .jpeg == .jpg)
    expected_ext = ".jpg" if ext == ".jpeg" else ext
    if expected_ext != canonical_ext:
        raise ValueError("A extensão do arquivo não corresponde ao formato real da imagem.")

    # TODO(security): Em cenários multi-usuário, integrar scanner antivírus (ex: ClamAV)
    # em sandbox antes de persistir arquivos enviados.
    resolved_dir = upload_dir.resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}{canonical_ext}"
    target = (resolved_dir / stored_name).resolve()
    if not str(target).startswith(str(resolved_dir) + str(Path("/").anchor if False else "")) and target.parent != resolved_dir:
        raise ValueError("Caminho de destino inválido.")

    target.write_bytes(payload)

    clean_alt = re.sub(r"[\[\]\r\n]+", "", alt_text.strip()) or "imagem"
    url = f"/media/{stored_name}"
    return SavedMedia(
        filename=stored_name,
        url=url,
        markdown=f"![{clean_alt}]({url})",
        content_type=content_type,
        size_bytes=len(payload),
    )


def resolve_media_path(filename: str, upload_dir: Path) -> tuple[Path, str] | None:
    if not SAFE_MEDIA_FILENAME_RE.match(filename):
        return None

    resolved_dir = upload_dir.resolve()
    candidate = (resolved_dir / filename).resolve()
    if candidate.parent != resolved_dir or not candidate.is_file():
        return None

    content_type = ALLOWED_IMAGE_EXTENSIONS.get(candidate.suffix.lower())
    if not content_type:
        return None

    return candidate, content_type

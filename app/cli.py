from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.models import AdminUser
from app.schemas import CategoryEnum, PostCreate, PostUpdate
from app.security import hash_password, validate_password_strength
from app.services import markdown_service, post_service


def cmd_create_admin(args: argparse.Namespace) -> int:
    Base.metadata.create_all(bind=engine)
    username = (args.username or input("Usuário admin: ")).strip()
    if not username:
        print("Erro: usuário não pode ser vazio.", file=sys.stderr)
        return 1

    password = args.password or getpass.getpass("Senha (mín. 12 caracteres): ")
    try:
        validate_password_strength(password)
    except ValueError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        existing = db.execute(
            select(AdminUser).where(AdminUser.username == username)
        ).scalar_one_or_none()
        if existing is not None:
            existing.password_hash = hash_password(password)
            existing.is_active = True
            db.commit()
            print(f"Senha do administrador '{username}' atualizada com sucesso.")
            return 0

        admin = AdminUser(
            username=username,
            password_hash=hash_password(password),
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"Administrador '{username}' criado com sucesso.")
        return 0
    finally:
        db.close()


def _import_single_file(
    db,
    file_path: Path,
    default_category: CategoryEnum,
    *,
    update_existing: bool,
) -> str:
    resolved = file_path.resolve()
    if not resolved.is_file():
        raise ValueError(f"Arquivo não encontrado: {file_path}")

    settings = get_settings()
    raw_bytes = resolved.read_bytes()
    raw_text = markdown_service.validate_markdown_upload(
        resolved.name, raw_bytes, settings.max_markdown_upload_bytes
    )
    parsed = markdown_service.parse_markdown_document(
        raw_text,
        fallback_title=resolved.stem.replace("-", " ").title(),
        fallback_category=default_category,
    )

    if update_existing and parsed.slug:
        existing = post_service.get_post_by_slug(db, parsed.slug, include_unpublished=True)
        if existing is not None:
            post_service.update_post(
                db,
                existing,
                PostUpdate(
                    title=parsed.title,
                    summary=parsed.summary,
                    category=parsed.category,
                    content_md=parsed.content_md,
                    tags=parsed.tags,
                    is_published=parsed.is_published,
                    published_at=parsed.published_at,
                ),
            )
            return f"atualizado: /post/{existing.slug}"

    created = post_service.create_post(
        db,
        PostCreate(
            title=parsed.title,
            slug=parsed.slug,
            summary=parsed.summary,
            category=parsed.category,
            content_md=parsed.content_md,
            tags=parsed.tags,
            is_published=parsed.is_published,
            published_at=parsed.published_at,
        ),
    )
    return f"criado: /post/{created.slug}"


def cmd_import_md(args: argparse.Namespace) -> int:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        result = _import_single_file(
            db,
            Path(args.file),
            CategoryEnum(args.category),
            update_existing=args.update,
        )
        print(f"OK ({result})")
        return 0
    except Exception as exc:
        print(f"Erro ao importar: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_sync_dir(args: argparse.Namespace) -> int:
    Base.metadata.create_all(bind=engine)
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        print(f"Erro: diretório não encontrado: {directory}", file=sys.stderr)
        return 1

    md_files = sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in {".md", ".markdown"}
    )
    if not md_files:
        print("Nenhum arquivo .md encontrado no diretório.")
        return 0

    db = SessionLocal()
    try:
        for md_file in md_files:
            result = _import_single_file(
                db,
                md_file,
                CategoryEnum(args.category),
                update_existing=True,
            )
            print(f"- {md_file.name}: {result}")
        return 0
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="CLI GreyWorks Blog")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-admin", help="Cria ou atualiza um usuário administrador")
    p_admin.add_argument("--username", default=None)
    p_admin.add_argument("--password", default=None)
    p_admin.set_defaults(func=cmd_create_admin)

    p_import = sub.add_parser("import-md", help="Importa um arquivo .md para o banco")
    p_import.add_argument("file", help="Caminho para o arquivo .md")
    p_import.add_argument(
        "--category",
        choices=[c.value for c in CategoryEnum],
        default=CategoryEnum.TECNOLOGIA.value,
    )
    p_import.add_argument("--update", action="store_true", help="Atualiza se o slug já existir")
    p_import.set_defaults(func=cmd_import_md)

    p_sync = sub.add_parser("sync-dir", help="Sincroniza todos os arquivos .md de uma pasta")
    p_sync.add_argument("directory", help="Pasta contendo arquivos .md")
    p_sync.add_argument(
        "--category",
        choices=[c.value for c in CategoryEnum],
        default=CategoryEnum.TECNOLOGIA.value,
    )
    p_sync.set_defaults(func=cmd_sync_dir)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

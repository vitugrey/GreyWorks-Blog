# GreyWorks Blog

Blog minimalista e industrial construído com **FastAPI**, **Pydantic v2**, **SQLAlchemy 2.0**, **Jinja2** e **Markdown (.md)** sanitizado, seguindo a identidade visual oficial da **GreyWorks** (`identidade visual.md`) e pronto para deploy em **VPS com Docker + PostgreSQL + Caddy (HTTPS automático)**.

## Funcionalidades

- **Home (`Blog`)**: seção **Destaques** com os **3 posts mais visualizados** + lista completa em ordem cronológica agrupada por mês (`NOVEMBRO 2026`, etc.) com alternância entre **Lista** e **Grade**.
- **Categorias na Navbar**: `Tecnologia`, `Geek`, `Off-Topic` (filtradas sem a seção de Destaques), `Sobre` e barra de pesquisa instantânea (atalho `/` no teclado).
- **Artigos em Markdown (`.md`)**: título, `#hashtags` clicáveis abaixo do título, data de publicação, tempo estimado de leitura, barra de progresso, sumário (TOC) automático e destaque de sintaxe com botão **Copiar**.
- **Publicação flexível**:
  - **Painel Admin (`/admin`)** com autenticação Argon2id, sessão server-side em banco, proteção CSRF e upload direto de arquivos `.md` (com YAML frontmatter).
  - **CLI (`python -m app.cli`)** para criar admin, importar `.md` individual ou sincronizar uma pasta inteira.
  - **API REST autenticada (`/api/v1/posts`)** via Bearer Token.
- **SEO & Syndication**: `/rss.xml`, `/sitemap.xml` e meta tags OpenGraph.

## Rodando localmente

```bash
# 1. Ative o ambiente virtual e instale dependências (se ainda não instalado)
pip install -r requirements.txt

# 2. Copie o .env de exemplo
cp .env.example .env

# 3. Crie o usuário administrador
python -m app.cli create-admin

# 4. Inicie o servidor local (apenas 127.0.0.1)
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Acesse `http://127.0.0.1:8000` (e `/admin` para o painel editorial).

## Deploy na VPS com Docker

1. Clone o repositório na sua VPS e crie o arquivo `.env` a partir de `.env.example`:

```bash
cp .env.example .env
```

2. Preencha no `.env`:
   - `BLOG_DOMAIN=blog.seudominio.com.br` (aponte o registro DNS A para o IP da VPS)
   - `POSTGRES_PASSWORD=` (senha forte)
   - `SECRET_KEY=` (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`)
   - `API_TOKEN=` (opcional, se quiser publicar via API)

3. Suba toda a stack (PostgreSQL 16 + FastAPI + Caddy com HTTPS automático):

```bash
docker compose up -d --build
```

4. Crie seu usuário administrador dentro do container:

```bash
docker compose exec web python -m app.cli create-admin
```

5. (Opcional) Importe artigos `.md` pela CLI:

```bash
docker compose exec web python -m app.cli import-md /caminho/do/post.md --update
```

## Testes

```bash
pytest -v
```

---
title: Como organizar seus arquivos Markdown para o GreyWorks Blog
category: tecnologia
tags:
  - markdown
  - docker
  - fastapi
date: 2026-11-22
summary: Template pronto em Markdown com YAML frontmatter para importar artigos no painel admin ou via CLI.
published: true
---

## Estrutura recomendada

Cada post do **GreyWorks Blog** pode ser escrito no seu editor favorito (VS Code, Obsidian, Neovim) usando um cabeçalho YAML opcional seguido do texto em Markdown.

### Blocos de código com destaque automático

```python
from pydantic import BaseModel

class Artigo(BaseModel):
    titulo: str
    categoria: str
    tags: list[str]
```

### Citações e tabelas

> Escreva em texto puro, versione se quiser e publique em segundos.

| Comando | Ação |
|---|---|
| `python -m app.cli import-md examples/exemplo-post.md` | Importa um único `.md` |
| `python -m app.cli sync-dir ./meus-posts` | Sincroniza uma pasta inteira |

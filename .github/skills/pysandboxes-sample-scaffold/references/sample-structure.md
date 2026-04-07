# Structure d’un sample pysandboxes

Ce document décrit la structure commune des samples du dépôt pysandboxes (ex. `samples/mcp-client`, `samples/mcp-server`), à reproduire pour tout nouveau sample.

## Emplacement

- Chaque sample est un **sous-répertoire** de `samples/` à la racine du dépôt.
- Nom du répertoire : kebab-case, ex. `mcp-client`, `mcp-server`, `my-new-sample`.

## Fichiers obligatoires à la racine du sample

| Fichier | Rôle |
|--------|------|
| `Makefile` | Cibles : `help`, `tests`, `lint`, `format`, `validate`, `init`, `lock`, `clean`, `dist`. Utilise `uv` et `uvx`. |
| `pyproject.toml` | Projet Python : `uv`, dependency-groups `dev` et `test`, source éditable `pysandboxes` vers `../..`. |
| `README.md` | Installation (uv sync), usage, documentation du sample. |
| `AGENTS.md` | Règles pour les agents (ex. standards Packmind). Peut inclure uniquement le bloc Packmind si le repo parent les fournit. |
| `.gitignore` | Au minimum : `.local.py-sandboxes`, `.env`, `.venv`. |

## Makefile

- `SHELL=/bin/bash`, `.PHONY` pour les cibles principales.
- Variable `UV_GROUP?=--group dev --group test`.
- Cible par défaut : `all: help`.
- **Tests** : `tests` exécute `uv run pytest -v $(TEST_FILE)` (avec `set -a` et `source .env` si besoin).
- **Lint / format** : `lint`, `format` avec `uvx mypy`, `uvx black`, `uvx ruff check` sur `PYTHON_FILES=.`.
- **Nettoyage** : `clean` supprime `.ipynb_checkpoints`, `dist/`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`.
- **Aide** : `help` affiche les cibles avec les commentaires `##` du Makefile (séd + awk).
- **Lock / sync** : `uv.lock` dépend de `pyproject.toml` ; `lock` ; `init: _uv-init` avec `uv sync $(UV_GROUP)`.
- **Validation** : `validate: uv.lock format lint spell_check tests` (optionnel : `spell_check` avec codespell).
- **Build** : `dist` avec `uv build`.

Les commentaires `##` devant une cible servent de description pour `make help`.

## pyproject.toml

- `[project]` : `name`, `version`, `description`, `readme`, `requires-python = ">=3.10"`, `dependencies` (inclure `pysandboxes` si le sample l’utilise).
- `[dependency-groups]` : `dev` (mypy, black, ruff, pytest, etc.), `test` (pytest, pytest-asyncio, pytest-dotenv, pytest-mock, etc.), optionnel `codespell`.
- `[tool.uv.sources]` : `pysandboxes = { path = "../..", editable = true }` pour être dans le repo pysandboxes.
- `[build-system]` : `hatchling` ; `[tool.hatch.build.targets.wheel]` avec `packages = ["<package_dir>"]`.
- Outils : `[tool.ruff]` (line-length 120, py310), `[tool.pytest.ini_options]` (testpaths, addopts, asyncio si besoin), optionnel `[tool.pyright]`, `[tool.codespell]`.

Le nom du package Python (répertoire) est en snake_case, ex. `mcp_simple_chatbot`, `mcp_server`.

## README.md

- Titre et courte description du sample.
- **Installation** : `cd path/to/sample` puis `uv sync` (ou `uv sync --reinstall`).
- **Usage** : comment lancer l’appli ou les tests, variables d’environnement (`.env`), exemples de commandes.
- Liens vers d’autres samples ou doc du dépôt si pertinent (ex. mcp-client → mcp-server).

## AGENTS.md

- Inclure au minimum le bloc « Packmind standards » (début/fin) pour que les agents appliquent les standards du repo.
- Les standards listés (Python, FastAPI, etc.) dépendent du type de sample.

## .gitignore

Contenu minimal recommandé :

```
.local.py-sandboxes
.env
.venv
```

## Répertoires

- **Package Python** : un répertoire (snake_case) avec `__init__.py` et modules du sample (ex. `mcp_server/`, `mcp_simple_chatbot/`).
- **tests/** : `tests/` à la racine du sample avec `__init__.py` et modules `test_*.py` ; `TEST_FILE ?= tests` dans le Makefile.
- Optionnel : `resources/`, `.vscode/`, `.packmind/`, fichiers de config (`.env.example`, `packmind.json`, configs MCP, etc.).

## Conventions

- Chaque sample a son **environnement uv dédié** (`.venv` dans le répertoire du sample). Ne pas partager le venv du repo racine.
- Dans la doc racine (AGENTS.md), rappeler : « Each sample uses a dedicated directory and uv environment. Navigate to the sample directory before running its tests. »
- Pour les tests : `make tests` ou `make validate` depuis le répertoire du sample.

## Résumé des commandes utilisateur

```bash
cd samples/<sample-name>
uv sync
make help
make tests
make validate
```

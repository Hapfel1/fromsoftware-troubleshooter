# Development

## Requirements

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)

## Setup
```bash
uv sync --locked --dev
```

## Run
```bash
uv run python main.py
```

## Lint
```bash
uv run ruff check
uv run ruff format
```
## Release

1. Set the new version in `pyproject.toml` and
   `fromsoftware_troubleshooter/__init__.py`, then run `uv lock`.
2. Merge to `master`. The Build & Release workflow builds both platforms and
   creates a draft release `v<version>` with the AppImage and the Windows zip.
   Each later push to `master` replaces the draft.
3. Edit the notes if needed and publish the draft. Publishing starts the
   Nexus Mods upload of both files.

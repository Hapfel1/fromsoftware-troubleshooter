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

## Build exe
```bash
uv run pyinstaller "FromSoftware Troubleshooter.spec"
# Output: dist/FromSoftware Troubleshooter.exe
```
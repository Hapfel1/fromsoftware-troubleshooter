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

Releases are automatic. Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/): `feat:` bumps the
minor version, `fix:` and the other types the patch version, `ci:`, `build:`,
`style:` and `test:` commits are left out of the changelog.

1. A push to `master` with releasable commits creates the branch
   `release-v<version>` with the bumped version and the new `CHANGELOG.md`
   section, opens a release PR, and creates a draft GitHub release with the
   AppImage and the Windows zip. Later pushes update both.
2. Publish the draft. Publishing tags the release and uploads both files to
   Nexus Mods.
3. Merge the release PR.

To ship a different version than the commits give, run the workflow by hand
with a version, or set the repository variable `NEXT_VERSION_OVERRIDE`.

"""
Parse a filled-in game-update issue and open a PR updating
game_file_sizes.json with the new build_id and file sizes.

Triggered on issue "edited" events for issues labeled "game-update" (see
.github/workflows/apply-size-update.yml). Only acts once the "Ready"
checkbox in the issue body is checked; otherwise exits without doing
anything, so partial edits while filling in sizes don't spam PRs.

For every filled-in file size, exact/min/max are (re)computed as
exact +/- TOLERANCE, matching the existing convention in
game_file_sizes.json ("10 byte tolerance for DLL version variations").

Required env vars (all provided by GitHub Actions):
    GITHUB_TOKEN, GITHUB_REPOSITORY, ISSUE_NUMBER, ISSUE_BODY
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SIZES_PATH = ROOT / "game_file_sizes.json"
GITHUB_API = "https://api.github.com"
TOLERANCE = 10
BASE_BRANCH = "master"


def github_headers() -> dict[str, str]:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def parse_issue(body: str) -> tuple[str, int, dict[str, int]] | None:
    marker_match = re.search(r"game_key:\s*(\S+)\s*\n\s*build_id:\s*(\d+)", body)
    if not marker_match:
        print("No game_key/build_id marker found in issue body", file=sys.stderr)
        return None
    game_key = marker_match.group(1)
    build_id = int(marker_match.group(2))

    if not re.search(r"- \[[xX]\]\s*Ready", body):
        print("Ready checkbox not checked yet, nothing to do")
        return None

    sizes: dict[str, int] = {}
    for line in body.splitlines():
        m = re.match(r"^([\w.]+):\s*(\d+)\s*$", line.strip())
        if m and m.group(1) not in ("build_id", "game_key"):
            sizes[m.group(1)] = int(m.group(2))

    if not sizes:
        print("Ready checkbox checked but no numeric sizes found", file=sys.stderr)
        return None

    return game_key, build_id, sizes


def apply_update(game_key: str, build_id: int, sizes: dict[str, int]) -> bool:
    data = json.loads(SIZES_PATH.read_text(encoding="utf-8"))
    if game_key not in data:
        print(f"Unknown game_key {game_key!r} in game_file_sizes.json", file=sys.stderr)
        return False

    entry = data[game_key]
    entry["build_id"] = build_id
    for name, exact in sizes.items():
        entry[name] = {
            "exact": exact,
            "min": exact - TOLERANCE,
            "max": exact + TOLERANCE,
        }
    data[game_key] = entry

    SIZES_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, cwd=ROOT)


def open_pr(repo: str, issue_number: int, game_key: str, build_id: int) -> None:
    branch = f"game-update/{game_key}-{build_id}"
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"])
    run(["git", "checkout", "-b", branch])
    run(["git", "add", "game_file_sizes.json"])
    run(["git", "commit", "-m", f"chore(sizes): update {game_key} to build {build_id}"])
    run(["git", "push", "origin", branch, "--force"])

    payload = {
        "title": f"Update {game_key} file sizes for build {build_id}",
        "head": branch,
        "base": BASE_BRANCH,
        "body": f"Closes #{issue_number}\n\nAutomated size update from issue #{issue_number}.",
    }
    resp = requests.post(
        f"{GITHUB_API}/repos/{repo}/pulls",
        headers=github_headers(),
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    print(f"Opened PR: {resp.json()['html_url']}")


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    issue_number = os.environ.get("ISSUE_NUMBER")
    body = os.environ.get("ISSUE_BODY")
    if not repo or not issue_number or body is None:
        print("Missing GITHUB_REPOSITORY, ISSUE_NUMBER, or ISSUE_BODY", file=sys.stderr)
        return 1

    parsed = parse_issue(body)
    if not parsed:
        return 0

    game_key, build_id, sizes = parsed
    if not apply_update(game_key, build_id, sizes):
        return 1

    open_pr(repo, int(issue_number), game_key, build_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

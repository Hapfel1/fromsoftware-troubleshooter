"""
Check tracked games for a Steam build update and open a GitHub issue when one
is found, so a maintainer can fill in new file sizes.

Build IDs are read anonymously from Steam's PICS (Product Info and Content
System) via the `steam` package - the same mechanism SteamDB itself uses
(see https://steamdb.info/faq/#how-are-we-getting-this-information).
Build ID and depot/branch metadata are public and do not require owning the
app; only the actual manifest file listing (exact per-file sizes) requires
ownership, which is why this script only detects *that an update happened*
and leaves filling in sizes to a human via the created issue.

Usage (intended to run inside GitHub Actions):
    python scripts/check_game_updates.py

Required env vars:
    GITHUB_TOKEN        - token with issues:write on the repo
    GITHUB_REPOSITORY   - "owner/repo", set automatically by Actions
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
SIZES_PATH = ROOT / "game_file_sizes.json"
APPIDS_PATH = SCRIPT_DIR / "game_appids.json"

GITHUB_API = "https://api.github.com"
ISSUE_LABEL = "game-update"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_build_ids(appids: dict[str, str]) -> dict[str, int]:
    """
    Anonymously query Steam PICS for the current public-branch build_id of
    each app. Returns only the games that were successfully resolved; a
    missing entry means that app's info could not be parsed (logged to
    stderr) rather than silently treating it as unchanged.
    """
    from steam.client import SteamClient

    client = SteamClient()
    result = client.anonymous_login()
    if not client.logged_on:
        print(f"Steam anonymous login failed: {result}", file=sys.stderr)
        return {}

    build_ids: dict[str, int] = {}
    try:
        app_id_list = [int(v) for v in appids.values()]
        info = client.get_product_info(apps=app_id_list, timeout=30)
        apps = (info or {}).get("apps", {})

        for key, appid_str in appids.items():
            appid = int(appid_str)
            app_data = apps.get(appid)
            if not app_data:
                print(
                    f"{key} (appid {appid}): no product info returned", file=sys.stderr
                )
                continue
            try:
                branches = app_data["depots"]["branches"]
                build_id = int(branches["public"]["buildid"])
            except (KeyError, TypeError, ValueError) as e:
                print(
                    f"{key} (appid {appid}): could not read public buildid ({e}). "
                    f"Raw depots keys: {list(app_data.get('depots', {}).keys())}",
                    file=sys.stderr,
                )
                continue
            build_ids[key] = build_id
    finally:
        client.logout()

    return build_ids


def github_headers() -> dict[str, str]:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def has_open_issue(repo: str, game_key: str, build_id: int) -> bool:
    """True if an open issue already tracks this exact game_key + build_id."""
    marker = f"game_key: {game_key}\nbuild_id: {build_id}"
    url = f"{GITHUB_API}/repos/{repo}/issues"
    params = {"labels": ISSUE_LABEL, "state": "open", "per_page": 100}
    resp = requests.get(url, headers=github_headers(), params=params, timeout=15)
    resp.raise_for_status()
    for issue in resp.json():
        if marker in (issue.get("body") or ""):
            return True
    return False


def create_issue(
    repo: str,
    game_key: str,
    game_name: str,
    old_build: int | None,
    new_build: int,
    tracked_files: list[str],
) -> None:
    fields = "\n".join(f"{name}: " for name in tracked_files)
    body = (
        f"<!--\ngame_key: {game_key}\nbuild_id: {new_build}\n-->\n"
        f"**{game_name}** updated on Steam.\n\n"
        f"Previous build: `{old_build if old_build is not None else 'unknown'}`\n"
        f"New build: `{new_build}`\n\n"
        "Fill in the new sizes below in bytes (Properties > Details on the "
        "file, or SteamDB's file list for the depot), then check the box.\n\n"
        f"{fields}\n\n"
        "- [ ] Ready - sizes filled in above\n"
    )
    payload = {
        "title": f"Game update: {game_name} (build {new_build})",
        "body": body,
        "labels": [ISSUE_LABEL],
    }
    url = f"{GITHUB_API}/repos/{repo}/issues"
    resp = requests.post(url, headers=github_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    print(f"Created issue for {game_name}: {resp.json()['html_url']}")


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print(
            "GITHUB_REPOSITORY not set, refusing to run outside Actions",
            file=sys.stderr,
        )
        return 1

    appids = load_json(APPIDS_PATH)
    sizes = load_json(SIZES_PATH)
    live_build_ids = fetch_build_ids(appids)

    if not live_build_ids:
        print("Could not resolve any build ids from Steam", file=sys.stderr)
        return 1

    exit_code = 0
    for game_key, new_build in live_build_ids.items():
        entry = sizes.get(game_key, {})
        old_build = entry.get("build_id")
        if old_build == new_build:
            continue

        try:
            if has_open_issue(repo, game_key, new_build):
                print(f"{game_key}: update already has an open issue, skipping")
                continue

            game_name = game_key.replace("_", " ").title()
            tracked_files = [k for k in entry.keys() if k != "build_id"]
            if not tracked_files:
                tracked_files = ["exe", "steam_api64.dll"]
            create_issue(repo, game_key, game_name, old_build, new_build, tracked_files)
        except requests.HTTPError as e:
            print(f"{game_key}: GitHub API error: {e}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

"""
Run this locally to read current Steam build IDs from your ACF manifests.
Prints values to paste into game_file_sizes.json.

Usage: python fetch_build_ids.py
"""

import re
from pathlib import Path

APP_IDS = {
    "elden_ring": "1245620",
    "nightreign": "2622380",
    "dark_souls_remastered": "570940",
    "dark_souls_2": "335300",
    "dark_souls_3": "374320",
    "sekiro": "814380",
    "armored_core_6": "1888160",
}


def get_steam_library_folders() -> list[Path]:
    libraries: list[Path] = []
    candidates = [
        Path.home() / ".local" / "share" / "Steam" / "steamapps",
        Path.home() / ".steam" / "steam" / "steamapps",
        Path.home()
        / ".var"
        / "app"
        / "com.valvesoftware.Steam"
        / ".local"
        / "share"
        / "Steam"
        / "steamapps",
    ]
    for c in candidates:
        if c.exists():
            libraries.append(c)

    # Windows fallback
    for drive in "CDEF":
        for stem in (
            Path(f"{drive}:/Program Files (x86)/Steam/steamapps"),
            Path(f"{drive}:/Steam/steamapps"),
        ):
            if stem.exists():
                libraries.append(stem)

    expanded = list(libraries)
    for root in libraries:
        for vdf in (
            root / "libraryfolders.vdf",
            root.parent / "config" / "libraryfolders.vdf",
        ):
            if vdf.exists():
                try:
                    text = vdf.read_text(encoding="utf-8", errors="ignore")
                    for path_str in re.findall(r'"path"\s+"([^"]+)"', text):
                        extra = Path(path_str) / "steamapps"
                        if extra.exists() and extra not in expanded:
                            expanded.append(extra)
                except Exception:
                    pass
                break

    seen: set[Path] = set()
    result: list[Path] = []
    for p in expanded:
        try:
            rp = p.resolve()
        except Exception:
            rp = p
        if rp not in seen:
            seen.add(rp)
            result.append(p)
    return result


def read_acf_value(acf_path: Path, key: str) -> str | None:
    try:
        text = acf_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(rf'"{re.escape(key)}"\s+"([^"]+)"', text, re.IGNORECASE)
        return m.group(1) if m else None
    except Exception:
        return None


results: dict[str, str] = {}
libraries = get_steam_library_folders()

for key, app_id in APP_IDS.items():
    found = False
    for root in libraries:
        acf = root / f"appmanifest_{app_id}.acf"
        if acf.exists():
            build_id = read_acf_value(acf, "buildid")
            if build_id:
                results[key] = build_id
                found = True
                break
    if not found:
        results[key] = "NOT INSTALLED"

print("Paste these build_id values into game_file_sizes.json:\n")
for key, build_id in results.items():
    print(f"  {key}: {build_id}")

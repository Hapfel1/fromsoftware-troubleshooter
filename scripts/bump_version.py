"""Set the version in pyproject.toml and fromsoftware_troubleshooter/__init__.py.

Usage: python scripts/bump_version.py <version>   (e.g. 1.9.0 or v1.9.0)
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "fromsoftware_troubleshooter"
TARGETS = {
    ROOT / "pyproject.toml": r'(?m)^(version\s*=\s*")[^"]+(")',
    PACKAGE / "__init__.py": r'(__version__\s*=\s*")[^"]+(")',
}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 1
    version = sys.argv[1].removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        print(f"Not a major.minor.patch version: {version}", file=sys.stderr)
        return 1
    for path, pattern in TARGETS.items():
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(pattern, rf"\g<1>{version}\g<2>", text, count=1)
        if count != 1:
            print(f"No version found in {path}", file=sys.stderr)
            return 1
        path.write_text(updated, encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

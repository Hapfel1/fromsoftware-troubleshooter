"""Convert a CHANGELOG.md release section (stdin) into plain lines for Nexus Mods.

Headings, the release date, commit links and PR references are dropped; each
entry becomes one line.
"""

import re
import sys

_COMMIT_LINK = re.compile(r"\s*\(\[[0-9a-f]{7,40}\]\([^)]*\)\)")
_PR_REF = re.compile(r"\s*\(#\d+\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# GitHub's generated release notes: "Title by @user in https://..."
_GENERATED_TAIL = re.compile(r" by @\S+ in https://\S+$")


def convert(markdown: str) -> str:
    lines = []
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "**Released:**", "**Full Changelog**")):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:]
        line = _COMMIT_LINK.sub("", line)
        line = _GENERATED_TAIL.sub("", line)
        line = _LINK.sub(r"\1", _PR_REF.sub("", line)).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    print(convert(sys.stdin.read()))

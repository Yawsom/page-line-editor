#!/usr/bin/env python3
"""Fail when Git tracks manuscript data or generated correction artefacts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath

PRIVATE_SUFFIXES = {
    ".xml",
    ".docx",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
}
PRIVATE_PARTS = {"correction_history", "backups"}
GENERATED_NAMES = {"alignment.json", "index.html", "manifest.json"}
GENERATED_SUFFIXES = {".html"}
DATA_DIRS = {
    "local_data",
    # Retain these legacy locations as protected names so an accidental move
    # back to the repository root can never add private data to Git.
    "ground_truth",
    "transcribed_xml",
    "corrected_xml",
    "reports",
}
ALLOWED_ROOTS = {"docs"}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def violation(path_text: str) -> str | None:
    path = PurePosixPath(path_text)
    if path.parts and path.parts[0] in ALLOWED_ROOTS:
        return None
    lower_suffix = path.suffix.lower()
    if lower_suffix in PRIVATE_SUFFIXES:
        return f"private data extension {lower_suffix}"
    if PRIVATE_PARTS.intersection(path.parts):
        return "correction history or backup path"
    name = path.name.lower()
    if name in GENERATED_NAMES:
        return "generated correction report"
    if name.endswith(".page-editor.json"):
        return "generated editor project file"
    if lower_suffix in GENERATED_SUFFIXES:
        return f"generated artefact {lower_suffix}"
    if path.parts and path.parts[0] in DATA_DIRS and path.name != ".gitkeep":
        return "content inside a private/generated data directory"
    return None


def main() -> int:
    problems = [(path, reason) for path in tracked_files() if (reason := violation(path))]
    if not problems:
        print("Data guard passed: Git tracks no manuscript or generated correction data.")
        return 0
    print("Refusing tracked private/generated data:", file=sys.stderr)
    for path, reason in problems:
        print(f"  {path}: {reason}", file=sys.stderr)
    print("Remove these paths from the Git index before continuing.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

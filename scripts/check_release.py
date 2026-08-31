"""Validate metadata that must agree before creating a tagged release."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    return str(project["version"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Git tag being released, e.g. v0.1.0a1")
    args = parser.parse_args(argv)

    version = project_version()
    errors: list[str] = []
    if args.tag != f"v{version}":
        errors.append(f"tag {args.tag!r} does not match pyproject version v{version}")
    if "a" not in version:
        errors.append(f"version {version!r} is not an alpha prerelease")
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        errors.append("CHANGELOG.md is required for a release")
    elif f"## {version}" not in changelog.read_text(encoding="utf-8"):
        errors.append(f"CHANGELOG.md has no entry for version {version}")
    if not (ROOT / "LICENSE").is_file():
        errors.append("LICENSE is required before publishing a release")

    if errors:
        for error in errors:
            print(f"Release check failed: {error}", file=sys.stderr)
        return 1
    print(f"Release metadata is valid for {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

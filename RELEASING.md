# Releasing PAGE Line Editor

## Alpha release prerequisites

1. Confirm that the Apache License 2.0 file at `LICENSE` remains present. The
   release workflow deliberately blocks publication without a license file.
2. Ensure the default branch is green in the **CI** workflow.
3. Update `pyproject.toml` to the intended PEP 440 alpha version and add matching
   notes under that version in `CHANGELOG.md`.
4. Run the local checks below. Do not stage manuscript data or generated reports.

```bash
python scripts/check_no_private_data.py
ruff check .
mypy src/page_line_editor
pytest
python -m build
python -m twine check dist/*
```

## Publishing an alpha

Choose an unused PEP 440 alpha version and matching tag. Never move or reuse a
published tag. For example:

```bash
VERSION=0.1.0a3
git tag -a "v$VERSION" -m "PAGE Line Editor $VERSION"
git push origin "v$VERSION"
```

Pushing a `v*` tag invokes the **Release** workflow. It verifies that the tag,
package version, changelog, and license agree; builds an sdist and wheel; checks
their metadata; and creates a GitHub release with both artifacts attached.

Use **Run workflow** on the Release workflow to build artifacts manually without
publishing a release.

### If publishing fails

The release publisher needs GitHub Actions **Workflow permissions** set to
**Read and write permissions** in the repository's **Settings → Actions →
General**. After correcting that setting, rerun the failed **Release** workflow
for the existing tag; do not create a replacement tag merely to retry publishing.

## Artifact scope

Alpha artifacts are installable Python distributions:

```bash
python -m pip install ./page_line_editor-<version>-py3-none-any.whl
page-line-editor
```

The workflow attaches these artifacts to GitHub Releases. It deliberately does
not publish to PyPI; adding PyPI trusted publishing is a separate maintainer
decision. Native desktop installers, signing, notarization, update delivery,
and an SBOM also remain post-alpha release work.

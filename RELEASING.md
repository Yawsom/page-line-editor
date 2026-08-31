# Releasing PAGE Line Editor

## Alpha release prerequisites

1. Add a maintainer-approved `LICENSE`. The release workflow deliberately blocks
   publication without one.
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

Choose the matching PEP 440 alpha version and tag. For example:

```bash
VERSION=0.1.0a2
git tag -a "v$VERSION" -m "PAGE Line Editor $VERSION"
git push origin "v$VERSION"
```

Pushing a `v*` tag invokes the **Release** workflow. It verifies that the tag,
package version, changelog, and license agree; builds an sdist and wheel; checks
their metadata; and creates a GitHub release with both artifacts attached.

Use **Run workflow** on the Release workflow to build artifacts manually without
publishing a release.

## Artifact scope

Alpha artifacts are installable Python distributions:

```bash
python -m pip install ./page_line_editor-0.1.0a2-py3-none-any.whl
page-line-editor
```

The workflow attaches these artifacts to GitHub Releases. It deliberately does
not publish to PyPI; adding PyPI trusted publishing is a separate maintainer
decision. Native installer signing, notarization, update delivery, and an SBOM
also remain post-alpha release work.

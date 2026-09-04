# Development

The plugin was developed using Claude Code.
I am not claiming to be a Blender plugin expert, nor do I have experience with the mathematics and algorithms involved.
My input in this is guiding the user experience towards something comfortable and intuitive.

## Commands

```bash
python scripts/run_tests.py     # headless test suite (needs Blender only)
python scripts/deploy.py        # copy into Blender's addons folder
python scripts/deploy.py --list # show detected Blender config dirs
```

Plasticity is **not** needed to develop or test: the tests build synthetic meshes
carrying the same custom properties the bridge writes.

Blender is found via `--blender`, `$BLENDER`, `PATH`, then the usual install
paths. There may be no system Python — both scripts are stdlib-only, so Blender's
bundled interpreter runs them.

## Testing 
Testing covers the addon's precision and robustness when creating shapes.
Some basic shapes were created in Plasticity and exported to a .blend file.

[RESULTS.md](https://github.com/Kernivel/Plasticty-Retopo-Tool/blob/main/RESULTS.md) is the golden table of results.

## The two rules that cost the most when broken

**Bump `version.py` on every change.** The panel shows it, and it is the only
reliable way to confirm a reload actually took. See
[Troubleshooting](../reference/troubleshooting.md#i-deployed-and-nothing-changed).

**`--factory-startup` is not optional** on any script run against
`tests/fixtures/TestCases.blend`, however read-only the script looks. Run without
it and every installed addon loads too — one of them once *saved the fixture over
itself* on quit (it leaves a `.blend1` beside it, which is the tell). The file is
frozen: `git status` after any run against it.

## Generated documents

`RESULTS.md` and the golden table in `tests/test_fixtures.py` are **generated —
never hand-edit either**:

```bash
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/gen_results.py
blender tests/fixtures/TestCases.blend --background --factory-startup --python scripts/gen_expectations.py
```

A re-export of the fixture renumbers every Plasticity face id even when no vertex
moves, so a stale table makes "the fixture changed" indistinguishable from "the
code regressed". Regenerate and read the diff instead.

## Working on the docs

The site is MkDocs Material, in `docs/`, published to GitHub Pages by
`.github/workflows/docs.yml` on every push to `main` that touches it.

```bash
pip install -r requirements-docs.txt
mkdocs serve        # live reload on http://127.0.0.1:8000
mkdocs build --strict
```

`--strict` is what CI runs: a dead internal link fails the build. That is the
only thing that keeps a docs site honest as pages get renamed.

Nothing in `docs/` ships with the addon — `scripts/deploy.py` skips it, along
with `mkdocs.yml`, `site/` and `requirements-docs.txt`.

!!! tip "Prefer prose that says *why*"

    The addon's own comments and CLAUDE.md are written that way, and the docs
    should match: a setting's default is discoverable from the panel, but the
    failure it exists to prevent is not.

### One-time GitHub setup

`Settings > Pages > Build and deployment > Source` must be set to **GitHub
Actions**. No `gh-pages` branch is involved.

### A custom domain later

Buy the domain, point a `CNAME` record at `kernivel.github.io`, and set it under
`Settings > Pages`. Then update `site_url` in `mkdocs.yml`. Nothing else changes
— that is all `machin3.io` is doing.

### Versioned docs later

The site is single-version today. If users start sitting on old releases,
[mike](https://github.com/jimporter/mike) adds `/latest/`, `/1.2/` and a version
switcher on top of Material without restructuring anything.

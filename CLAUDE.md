**Before writing files, check if CLAUDE.md, design docs, or tests need updating to reflect your changes.**

## Git workflow

- Make clean, atomic commits — one feature or fix per commit.
- Run `pre-commit run --files <staged files>` before attempting `git commit` to catch formatting issues early.
- **Default branch is `yo`, not `main`.** The repo also has a `main` branch but it is not the line of development. `yo` is what PRs target and what feature branches should be compared/merged against.

## Python

- Always import at the top of the file unless there's a good reason not to.

## Project

yolo runs Claude Code safely in a rootless Podman container with full autonomy.

Currently being rewritten from bash to Python. Legacy code is in `design/legacy/`.

## Key files

- `SPEC.md` — current specification (source of truth for behavior)
- `design/HACK_DECISIONS.md` — locked design decisions, do not revisit
- `design/LEGACY_SPEC.md` — spec of the legacy bash implementation
- `tests/features_to_test.md` — checklist of things that need tests

## Development

```
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

Entry point is `yo` (temporary, becomes `yolo` at cutover).

**Global vs local install:** `yo` is installed globally via `uv tool install`.
During development, the global install will shadow the local venv unless
`.venv/bin` is earlier in PATH. If the global version is winning, run
`uv tool uninstall con-yolo` before dev work, and reinstall after:
`uv tool install ~/devel/yo`.

## Architecture

- `src/yolo/config.py` — YAML config loading from 5 locations (defaults + 4 user)
- `src/yolo/secrets.py` — loads `~/.config/yolo/secrets.yaml` (mode 0600) and resolves `@secrets:<key>` env refs
- `src/yolo/images.py` — image definition loading, validation, topo-sort from images.yaml
- `src/yolo/builder.py` — resolves extras, assembles build context, invokes podman
- `src/yolo/cli.py` — click CLI (yo build, yo run, yo clip, yo demo)
- `src/yolo/launcher.py` — assembles podman run command
- `src/yolo/defaults/config.yaml` — default config (image selection, env, etc.)
- `src/yolo/defaults/images.yaml` — default image definitions (yolo-base, yolo-default)
- `src/yolo/images/Containerfile.base` — minimal debian base image
- `src/yolo/images/Containerfile.extras` — layers image-extras on top
- `src/yolo/image-extras/` — composable install scripts (apt.sh, python.sh, etc.)
- `.local-notes/` — gitignored local working notes (issues, PRs, etc.)

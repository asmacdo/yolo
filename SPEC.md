# YOLO Specification

Working spec for the Python rewrite. Locked decisions in `design/HACK_DECISIONS.md`.

## Overview

yolo runs Claude Code inside a rootless Podman container with
`--dangerously-skip-permissions`. The container is the sandbox — no
permission prompts needed.

## Components

| Component | Path | Purpose |
|-----------|------|---------|
| CLI | `src/yolo/cli.py` | `yo build`, `yo run` |
| Config | `src/yolo/config.py` | YAML loading from 5 locations |
| Images | `src/yolo/images.py` | Image definition loading, validation, topo-sort |
| Builder | `src/yolo/builder.py` | Resolves extras, assembles build context, invokes podman |
| Launcher | `src/yolo/launcher.py` | Assembles podman run command |
| Base image | `images/Containerfile.base` | Minimal debian + Claude Code |
| Extras image | `images/Containerfile.extras` | Layers image-extras on base |
| Scripts | `image-extras/` | Composable install scripts |
| Config defaults | `src/yolo/defaults/config.yaml` | Default config (image selection, env, etc.) |
| Image defaults | `src/yolo/defaults/images.yaml` | Default image definitions (yolo-base, yolo-default) |

---

## Config

### Format

YAML. Not sourced bash — declarative only to prevent prompt injection
across sessions.

### Locations (later overrides earlier)

| # | Path | Scope |
|---|------|-------|
| 0 | Package defaults | Builtin |
| 1 | `/etc/yolo/config.yaml` | System/org |
| 2 | `~/.config/yolo/config.yaml` | User |
| 3 | `.yolo/config.yaml` | Project (committed) |
| 4 | `.git/yolo/config.yaml` | Project (local) |

CLI args override everything.

### Merge rules

- **Lists**: append
- **Dicts**: recurse
- **Scalars**: replace
- **`!replace` tag**: TBD — per-key override to replace instead of append

---

## Images

Images are defined in `images.yaml` files (separate from `config.yaml`).
Image definitions are collected from all locations into a flat namespace
— no merging. `config.yaml` selects which image to run via the `image:`
scalar key (default: `yolo-default`).

### `images.yaml` locations

Same locations as `config.yaml`:

| # | Path | Scope |
|---|------|-------|
| 0 | Package defaults (`src/yolo/defaults/images.yaml`) | Builtin |
| 1 | `/etc/yolo/images.yaml` | System/org |
| 2 | `~/.config/yolo/images.yaml` | User |
| 3 | `.yolo/images.yaml` | Project (committed) |
| 4 | `.git/yolo/images.yaml` | Project (local) |

### Image entry schema

```yaml
images:
  - name: myimage           # required — IS the podman tag
    from: yolo-default       # optional, default: yolo-base
    containerfile: Containerfile.extras  # optional
    build_args:
      - KEY=value
    extras:
      - name: apt
        packages: [zsh, fzf]
```

### Image naming

Image names **are** the podman tags. No synthesis, no prefix.

### `from` key

Can be a yo-defined image name or any podman image reference.
Default is `yolo-base`. Yo builds dependencies first (topo-sorted).

### Validation

- No duplicate names across all `images.yaml` files
- No self-reference (`from: <own-name>`)
- No cycles in the `from:` chain
- `extras` + `containerfile: Containerfile.base` is invalid

---

## Container-extras

### Contract

Every extras entry uses the `name:` form. Additional params become
environment variables prefixed with `YOLO_{SCRIPTNAME}_{KEY}` (uppercased,
hyphens replaced with underscores).

```yaml
- name: apt
  packages: [zsh, fzf]
- name: python
  version: "3.12"
- name: datalad
```

Becomes:
- `YOLO_APT_PACKAGES="zsh fzf" bash apt.sh`
- `YOLO_PYTHON_VERSION=3.12 bash python.sh`
- `bash datalad.sh`

### Script resolution

Search path (later wins):

1. `<package>/image-extras/` — builtins
2. `~/.config/yolo/image-extras/` — user
3. `.yolo/image-extras/` — project (committed)
4. `.git/yolo/image-extras/` — project (local)

### Script requirements

- Self-contained bash scripts
- Validate own env vars, fail with clear message if missing
- No cross-script dependencies (duplicate is OK, idempotent is better)

### Build mechanism

Static Containerfiles, dynamic build context. No Dockerfile generation.

`Containerfile.base`: minimal debian + Claude Code + tini + essential tools.

`Containerfile.extras`: `FROM ${BASE_IMAGE}`, copies build context,
runs `run.sh` manifest. The manifest is the only generated file — a
list of `bash script.sh` calls with env var prefixes.

---

## Launcher

### Default behavior

Mounts claude config (rw), gitconfig (ro), workspace (rw). Sets up
env vars. Runs `claude --dangerously-skip-permissions`.

### Config keys

```yaml
volumes:
  - /host/path:/container/path:opts
```

### CLI flags

| Flag | Description |
|------|-------------|
| `-v, --volume` | Extra bind mount (repeatable) |
| `--entrypoint` | Override container command |
| `--image` | Run a specific named image |
| `[CLAUDE_ARGS]` | Passed through to claude |

### Entrypoint override

Custom entrypoint skips `--dangerously-skip-permissions`.
TODO: make skip_permissions a separate config value.

### Clipboard bridge

Host-side clipboard access for container Claude. A shared directory
(`~/.local/share/yolo/clip/`) is mounted at `/tmp/yolo-clip` in the
container. Container writes to `/tmp/yolo-clip/content`, host reads
via `yo clip`.

`host_clipboard_command` config key (default: `xclip -selection clipboard`)
controls what the host pipes into.

Not multi-instance safe — multiple containers share one clip file.
Practically fine: user only has one clipboard.

### Container naming

`<cwd>-<pid>` with `$HOME/` stripped and non-alphanumeric chars
replaced with `_`.

### Multiple simultaneous containers

Multiple `yo run` instances may run concurrently. Each gets a unique
container name (`<cwd>-<pid>`). Shared state (clipboard bridge, claude
config dir) is not isolated between instances.

---

## Security

### Posture

Secure by default. Flexible enough to weaken deliberately.

- No SSH keys mounted
- No cloud credentials accessible
- Workspace mounted read-write
- Network unrestricted (known gap)

### Config as attack surface

Claude can write to `.yolo/config.yaml` inside the container.
Modified config takes effect on next launch — between-session escape
vector. Mitigations under consideration (none implemented):

- Mount `.yolo/` read-only inside container
- Diff-on-launch warning
- Exit warning if config modified during session

---

## Still open

- pip.sh may be unnecessary if project venv is bound in
- Singularity/apptainer runtime abstraction
- Registry story (GHCR for base image)
- `!replace` YAML tag for per-key merge override
- Hooks / extensible launch behavior
- Context injection (tell Claude about its environment) — DONE
- Claude-to-Claude messaging via clip bridge (needs per-instance UUID or named channels)
- Installer redesign (setup-yolo.sh successor)
- `dangerously_skip_permissions` as separate config value

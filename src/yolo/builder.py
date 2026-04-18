"""Build container images with image-extras."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from yolo.images import resolve_build_order, validate_images

_PKG_DIR = Path(__file__).resolve().parent
CONTAINERFILE_BASE = _PKG_DIR / "images" / "Containerfile.base"
CONTAINERFILE_EXTRAS = _PKG_DIR / "images" / "Containerfile.extras"
BUILTIN_EXTRAS = _PKG_DIR / "image-extras"

DEFAULT_FROM = "yolo-base"


def _extras_search_path() -> list[Path]:
    """Return image-extras directories in precedence order (lowest first)."""
    from yolo.config import _find_git_dir

    paths = [BUILTIN_EXTRAS]

    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        paths.append(Path(xdg) / "yolo" / "image-extras")
    else:
        paths.append(Path.home() / ".config" / "yolo" / "image-extras")

    paths.append(Path.cwd() / ".yolo" / "image-extras")

    git_dir = _find_git_dir()
    if git_dir:
        paths.append(git_dir / "yolo" / "image-extras")

    return paths


def _resolve_script(name: str, search_path: list[Path]) -> Path | None:
    """Find a script by name in the search path. Later paths win."""
    found = None
    for directory in search_path:
        candidate = directory / f"{name}.sh"
        if candidate.is_file():
            found = candidate
    return found


def _parse_extra(entry) -> tuple[str, dict[str, str]]:
    """Parse a single image-extras entry into (name, env_vars).

    Entry must be a dict with a 'name' key, or a string (name only):
      {"name": "apt", "packages": "zsh fzf"}  -> ("apt", {"YOLO_APT_PACKAGES": "zsh fzf"})
      {"name": "python", "version": "3.12"}   -> ("python", {"YOLO_PYTHON_VERSION": "3.12"})
      {"name": "datalad"}                      -> ("datalad", {})
    """
    if isinstance(entry, str):
        return (entry, {})

    if not isinstance(entry, dict) or "name" not in entry:
        raise ValueError(f"Invalid container-extra: {entry!r} (must have 'name' key)")

    name = entry["name"]
    env_vars = {}
    for key, value in entry.items():
        if key == "name":
            continue
        env_key = f"YOLO_{name}_{key}".upper().replace("-", "_")
        if isinstance(value, list):
            env_vars[env_key] = " ".join(str(v) for v in value)
        else:
            env_vars[env_key] = str(value)

    return (name, env_vars)


def assemble_build_context(extras_config: list, verify: bool = False) -> Path:
    """Create a temp directory with scripts and run.sh for podman build.

    Returns the path to the temp directory. Caller must clean up.
    """
    search_path = _extras_search_path()

    build_dir = Path(tempfile.mkdtemp(prefix="yolo-build-"))
    scripts_dir = build_dir / "build" / "scripts"
    scripts_dir.mkdir(parents=True)

    run_lines = ["#!/bin/bash", "export PS4='+ [yolo] '", "set -eux"]
    if verify:
        run_lines.append("export YOLO_VERIFY=1")

    for entry in extras_config:
        name, env_vars = _parse_extra(entry)

        script = _resolve_script(name, search_path)
        if script is None:
            raise FileNotFoundError(
                f"No script found for '{name}' in search path: "
                + ", ".join(str(p) for p in search_path)
            )

        dest = scripts_dir / f"{name}.sh"
        if not dest.exists():
            shutil.copy2(script, dest)

        run_lines.append(f"echo '==> {name}'")
        env_prefix = " ".join(f'{k}="{v}"' for k, v in env_vars.items())
        if env_prefix:
            run_lines.append(f"{env_prefix} bash /tmp/yolo-build/scripts/{name}.sh")
        else:
            run_lines.append(f"bash /tmp/yolo-build/scripts/{name}.sh")

    run_sh = build_dir / "build" / "run.sh"
    run_sh.write_text("\n".join(run_lines) + "\n")

    return build_dir


def _image_exists(tag: str) -> bool:
    """Check if a podman image exists locally."""
    result = subprocess.run(
        ["podman", "image", "exists", tag],
        capture_output=True,
    )
    return result.returncode == 0


def _containerfile(name: str) -> Path:
    """Resolve a containerfile name to its path."""
    if name == "Containerfile.base":
        return CONTAINERFILE_BASE
    return CONTAINERFILE_EXTRAS


def build_image(
    image_entry: dict,
    verify: bool = False,
    build_args: list[str] | None = None,
    rebuild: bool = False,
) -> str:
    """Build a single image from its definition. Returns the tag (= name)."""
    name = image_entry["name"]
    from_ref = image_entry.get("from", DEFAULT_FROM)
    containerfile = image_entry.get("containerfile", "Containerfile.extras")
    extras = image_entry.get("extras", [])
    all_args = image_entry.get("build_args", []) + (build_args or [])

    if not rebuild and _image_exists(name):
        print(f"  {name}: already exists, skipping")
        return name

    print(f"\n  Image: {name}", flush=True)
    print(f"  From:  {from_ref}", flush=True)
    print(f"  Containerfile: {containerfile}", flush=True)

    cf_path = _containerfile(containerfile)

    if containerfile == "Containerfile.base":
        # Base images: no extras, just build the containerfile directly
        print(flush=True)
        cmd = [
            "podman",
            "build",
            "-f",
            str(cf_path),
            "-t",
            name,
        ]
        if rebuild:
            cmd.append("--no-cache")
        for arg in all_args:
            cmd += ["--build-arg", arg]
        cmd.append(str(_PKG_DIR / "images"))
        subprocess.run(cmd, check=True)
    else:
        # Extras images: assemble build context and layer on top
        if extras:
            print("  Extras:", flush=True)
            for extra in extras:
                extra_name = extra["name"] if isinstance(extra, dict) else extra
                script = _resolve_script(extra_name, _extras_search_path())
                source = str(script.parent) if script else "not found"
                print(f"    - {extra_name} ({source})", flush=True)
        print(flush=True)

        build_dir = assemble_build_context(extras, verify=verify)
        try:
            cmd = [
                "podman",
                "build",
                "--build-arg",
                f"BASE_IMAGE={from_ref}",
                "-f",
                str(cf_path),
                "-t",
                name,
            ]
            if rebuild:
                cmd.append("--no-cache")
            for arg in all_args:
                cmd += ["--build-arg", arg]
            cmd.append(str(build_dir))
            subprocess.run(cmd, check=True)
        finally:
            shutil.rmtree(build_dir)

    print(f"  Built {name}\n")
    return name


def build(
    images: list[dict],
    target: str | None = None,
    all_images: bool = False,
    verify: bool = False,
    build_args: list[str] | None = None,
    rebuild: bool = False,
) -> None:
    """Build images in dependency order.

    target: build this image and its from: chain.
    all_images: build everything.
    Neither: caller should pass target from config's image: key.
    """
    validate_images(images)

    if all_images:
        to_build = resolve_build_order(images)
    elif target:
        to_build = resolve_build_order(images, target)
    else:
        print("No images to build.")
        return

    if not to_build:
        print("Nothing to build.")
        return

    for entry in to_build:
        build_image(entry, verify=verify, build_args=build_args, rebuild=rebuild)

"""CLI entry point for yolo."""

import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

import click

from yolo.builder import build as builder_build
from yolo.config import load_config
from yolo.images import load_images, validate_images
from yolo.launcher import run as launcher_run

CONFIG_TEMPLATE = Path(__file__).parent / "defaults" / "config.template.yaml"


@click.group()
@click.version_option(version("con-yolo"), "--version", "-V", prog_name="yo")
@click.option(
    "--no-config", is_flag=True, default=False, help="Ignore all config files"
)
@click.pass_context
def main(ctx, no_config):
    """Run Claude Code safely in a container with full autonomy."""
    ctx.ensure_object(dict)
    ctx.obj["no_config"] = no_config


@main.command()
@click.option("--name", default=None, help="Build a specific image by name")
@click.option(
    "--all", "all_images", is_flag=True, default=False, help="Build all images"
)
@click.option("--verify", is_flag=True, default=False, help="Run extras in verify mode")
@click.option(
    "--build-arg", multiple=True, help="Pass build arg to podman build (repeatable)"
)
@click.option(
    "--rebuild", is_flag=True, default=False, help="Rebuild from scratch (no cache)"
)
@click.pass_context
def build(ctx, name, all_images, verify, build_arg, rebuild):
    """Build the container image with configured extras."""
    no_config = ctx.obj["no_config"]
    config = load_config(no_config=no_config)
    images = load_images(no_config=no_config)
    validate_images(images)

    if all_images:
        target = None
    else:
        target = name or config.get("image", "yolo-default")

    builder_build(
        images,
        target=target,
        all_images=all_images,
        verify=verify,
        build_args=list(build_arg),
        rebuild=rebuild,
    )


@main.command()
@click.option("--local", "target", flag_value="local", help="Write to .git/yolo/")
@click.option("--user", "target", flag_value="user", help="Write to ~/.config/yolo/")
@click.option("--path", "custom_path", default=None, help="Write to custom location")
@click.option(
    "--project",
    "target",
    flag_value="project",
    default=True,
    help="Write to .yolo/ (default)",
)
def init(target, custom_path):
    """Create a config file from the default template."""
    if custom_path:
        dest = Path(custom_path) / "config.yaml"
    elif target == "local":
        from yolo.config import _find_git_dir

        git_dir = _find_git_dir()
        if not git_dir:
            raise click.ClickException("Not in a git repository")
        dest = git_dir / "yolo" / "config.yaml"
    elif target == "user":
        import os

        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"
        dest = base / "yolo" / "config.yaml"
    else:
        dest = Path.cwd() / ".yolo" / "config.yaml"

    if dest.exists():
        click.echo(f"Config already exists: {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CONFIG_TEMPLATE, dest)
    click.echo(f"Created {dest}")


@main.command()
@click.pass_context
def images(ctx):
    """List configured images and their build status."""
    no_config = ctx.obj["no_config"]
    all_images = load_images(no_config=no_config)
    validate_images(all_images)
    config = load_config(no_config=no_config)
    selected = config.get("image", "yolo-default")

    for entry in all_images:
        name = entry["name"]
        result = subprocess.run(
            ["podman", "image", "exists", name], capture_output=True
        )
        status = "built" if result.returncode == 0 else "not built"
        marker = " *" if name == selected else ""
        click.echo(f"  {name} — {status}{marker}")


@main.command()
@click.pass_context
def clip(ctx):
    """Copy container clipboard content to host clipboard."""
    clip_file = Path.home() / ".local" / "share" / "yolo" / "clip" / "content"
    if not clip_file.exists():
        raise click.ClickException("Nothing to clip (no content written yet)")
    config = load_config(no_config=ctx.obj["no_config"])
    clipboard_cmd = config.get("host_clipboard_command", "xclip -selection clipboard")
    content = clip_file.read_text()
    subprocess.run(clipboard_cmd.split(), input=content, text=True, check=True)
    click.echo(f"Copied {len(content)} chars to clipboard")


@main.command()
def demo():
    """Run the interactive yolo demo."""
    import os
    import tempfile
    from importlib.resources import files

    demo_src = files("yolo") / "demo"
    if not (demo_src / "demo.md").is_file():
        raise click.ClickException("Demo files not found in package")

    with tempfile.TemporaryDirectory(prefix="yolo-demo-") as tmp:
        tmp_path = Path(tmp) / "demo"
        shutil.copytree(str(demo_src), str(tmp_path))
        os.chdir(tmp_path)
        # Mount yolo source tree so demo can show real code/config
        repo_root = Path(__file__).resolve().parent.parent.parent
        extra_volumes = []
        if (
            repo_root / "src" / "yolo" / "image-extras"
        ).is_dir():  # sanity check: are we in a source tree?
            extra_volumes.append(f"{repo_root}:/opt/yolo:ro")
        launcher_run(
            ["Read demo.md and follow it."],
            extra_volumes=extra_volumes,
        )


@main.command(context_settings={"ignore_unknown_options": True})
@click.option(
    "-v", "--volume", multiple=True, help="Extra bind mount (host:container[:opts])"
)
@click.option("--entrypoint", default=None, help="Override container entrypoint")
@click.option("--image", default=None, help="Run a specific named image")
@click.option(
    "--worktree",
    type=click.Choice(["ask", "bind", "skip", "error"]),
    default=None,
    help="Git worktree handling mode",
)
@click.option(
    "--nvidia",
    is_flag=True,
    default=False,
    help="Enable NVIDIA GPU passthrough via CDI",
)
@click.option(
    "--container-arg",
    multiple=True,
    help="Pass raw arg to container engine (repeatable)",
)
@click.argument("claude_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def run(ctx, volume, entrypoint, image, worktree, nvidia, container_arg, claude_args):
    """Launch Claude Code in a container."""
    launcher_run(
        list(claude_args),
        no_config=ctx.obj["no_config"],
        extra_volumes=list(volume),
        entrypoint=entrypoint,
        image_name=image,
        worktree=worktree,
        nvidia=nvidia,
        container_args=list(container_arg),
    )

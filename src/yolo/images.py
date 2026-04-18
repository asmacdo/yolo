"""Load, validate, and topo-sort image definitions from images.yaml files."""

import os
from pathlib import Path

from ruamel.yaml import YAML

IMAGES_FILENAME = "images.yaml"
DEFAULTS_IMAGES = Path(__file__).parent / "defaults" / IMAGES_FILENAME

VALID_CONTAINERFILES = {"Containerfile.base", "Containerfile.extras"}
DEFAULT_FROM = "yolo-base"
DEFAULT_CONTAINERFILE = "Containerfile.extras"

_yaml = YAML()
_yaml.preserve_quotes = True


def _images_paths() -> list[Path]:
    """Return images.yaml file paths in precedence order (lowest first)."""
    from yolo.config import _find_git_dir

    paths = [Path("/etc/yolo") / IMAGES_FILENAME]

    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        paths.append(Path(xdg) / "yolo" / IMAGES_FILENAME)
    else:
        paths.append(Path.home() / ".config" / "yolo" / IMAGES_FILENAME)

    paths.append(Path.cwd() / ".yolo" / IMAGES_FILENAME)

    git_dir = _find_git_dir()
    if git_dir:
        paths.append(git_dir / "yolo" / IMAGES_FILENAME)

    return paths


def _load_yaml(path: Path) -> list[dict]:
    """Load images from a YAML file. Returns list of image entries."""
    if not path.is_file():
        return []
    data = _yaml.load(path)
    if not data:
        return []
    images = data.get("images", [])
    if not isinstance(images, list):
        raise ValueError(f"{path}: 'images' must be a list")
    return images


def load_images(no_config: bool = False) -> list[dict]:
    """Collect all image definitions from all images.yaml locations.

    No merging -- each entry is taken as-is. Duplicate names are caught
    by validate_images().
    """
    images = _load_yaml(DEFAULTS_IMAGES)
    if no_config:
        return images
    for path in _images_paths():
        images.extend(_load_yaml(path))
    return images


def validate_images(images: list[dict]) -> None:
    """Validate collected image definitions. Raises ValueError on problems."""
    names = {}
    for img in images:
        name = img.get("name")
        if not name:
            raise ValueError(f"Image entry missing 'name': {img!r}")
        if name in names:
            raise ValueError(f"Duplicate image name '{name}'")
        names[name] = img

    for name, img in names.items():
        from_ref = img.get("from", DEFAULT_FROM)
        containerfile = img.get("containerfile", DEFAULT_CONTAINERFILE)
        extras = img.get("extras", [])

        # Self-reference
        if from_ref == name:
            raise ValueError(f"Image '{name}' references itself in 'from'")

        # Extras + Containerfile.base
        if extras and containerfile == "Containerfile.base":
            raise ValueError(
                f"Image '{name}': extras are not supported with Containerfile.base"
            )

    # Cycle detection via topological sort
    _topo_sort(images)


def _topo_sort(images: list[dict]) -> list[dict]:
    """Topological sort of images by from: dependencies.

    Returns images in build order (dependencies first).
    Only considers from: references that point to yo-defined names.
    External refs (podman tags, registry URLs) are ignored for ordering.
    Raises ValueError if a cycle is detected.
    """
    by_name = {img["name"]: img for img in images}
    order = []
    visited = set()
    in_stack = set()

    def visit(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in in_stack:
            cycle_start = path.index(name)
            cycle = path[cycle_start:] + [name]
            raise ValueError(f"Cycle in from: chain: {' -> '.join(cycle)}")
        in_stack.add(name)
        path.append(name)

        from_ref = by_name[name].get("from", DEFAULT_FROM)
        if from_ref in by_name:
            visit(from_ref, path)

        path.pop()
        in_stack.remove(name)
        visited.add(name)
        order.append(by_name[name])

    for name in by_name:
        visit(name, [])

    return order


def resolve_build_order(images: list[dict], target: str | None = None) -> list[dict]:
    """Return images in build order for a target (and its from: chain).

    If target is None, returns all images in topo-sorted order.
    """
    all_sorted = _topo_sort(images)

    if target is None:
        return all_sorted

    by_name = {img["name"]: img for img in images}
    if target not in by_name:
        raise ValueError(f"Image '{target}' not defined in any images.yaml")

    # Walk the from: chain to find which yo-defined images are needed
    needed = set()

    def collect(name: str) -> None:
        if name not in by_name or name in needed:
            return
        needed.add(name)
        from_ref = by_name[name].get("from", DEFAULT_FROM)
        collect(from_ref)

    collect(target)

    return [img for img in all_sorted if img["name"] in needed]

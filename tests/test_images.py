"""Tests for yolo images: loading, validation, and topo-sort."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from yolo.images import (
    _topo_sort,
    load_images,
    resolve_build_order,
    validate_images,
)


def _write_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    YAML().dump(data, path)


@pytest.fixture(autouse=True)
def _no_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr("yolo.images.DEFAULTS_IMAGES", tmp_path / "no-defaults.yaml")


# ── validate_images ──────────────────────────────────────────


class TestValidateImages:
    def test_valid_images(self):
        images = [
            {
                "name": "base",
                "from": "debian:bookworm",
                "containerfile": "Containerfile.base",
            },
            {"name": "default", "from": "base"},
        ]
        validate_images(images)  # should not raise

    def test_missing_name(self):
        with pytest.raises(ValueError, match="missing 'name'"):
            validate_images([{"extras": []}])

    def test_duplicate_name(self):
        images = [{"name": "foo"}, {"name": "foo"}]
        with pytest.raises(ValueError, match="Duplicate image name 'foo'"):
            validate_images(images)

    def test_self_reference(self):
        images = [{"name": "loop", "from": "loop"}]
        with pytest.raises(ValueError, match="references itself"):
            validate_images(images)

    def test_extras_with_base_containerfile(self):
        images = [
            {
                "name": "bad",
                "containerfile": "Containerfile.base",
                "extras": [{"name": "apt"}],
            }
        ]
        with pytest.raises(ValueError, match="extras are not supported"):
            validate_images(images)

    def test_extras_with_extras_containerfile_ok(self):
        images = [
            {
                "name": "ok",
                "containerfile": "Containerfile.extras",
                "extras": [{"name": "apt"}],
            }
        ]
        validate_images(images)  # should not raise

    def test_no_extras_with_base_containerfile_ok(self):
        images = [{"name": "base", "containerfile": "Containerfile.base"}]
        validate_images(images)  # should not raise


# ── _topo_sort ───────────────────────────────────────────────


class TestTopoSort:
    def test_linear_chain(self):
        images = [
            {"name": "c", "from": "b"},
            {"name": "b", "from": "a"},
            {"name": "a", "from": "debian:bookworm"},
        ]
        order = [img["name"] for img in _topo_sort(images)]
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_diamond(self):
        images = [
            {"name": "d", "from": "b"},
            {"name": "c", "from": "a"},
            {"name": "b", "from": "a"},
            {"name": "a", "from": "debian:bookworm"},
        ]
        order = [img["name"] for img in _topo_sort(images)]
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")

    def test_cycle_detected(self):
        images = [
            {"name": "a", "from": "b"},
            {"name": "b", "from": "a"},
        ]
        with pytest.raises(ValueError, match="Cycle"):
            _topo_sort(images)

    def test_longer_cycle(self):
        images = [
            {"name": "a", "from": "c"},
            {"name": "b", "from": "a"},
            {"name": "c", "from": "b"},
        ]
        with pytest.raises(ValueError, match="Cycle"):
            _topo_sort(images)

    def test_external_from_ignored(self):
        images = [
            {"name": "base", "from": "debian:bookworm"},
            {"name": "app", "from": "base"},
        ]
        order = [img["name"] for img in _topo_sort(images)]
        assert order == ["base", "app"]

    def test_default_from(self):
        """Images with no from: default to yolo-base."""
        images = [
            {"name": "yolo-base", "from": "debian:bookworm"},
            {"name": "app"},  # implicit from: yolo-base
        ]
        order = [img["name"] for img in _topo_sort(images)]
        assert order.index("yolo-base") < order.index("app")


# ── resolve_build_order ──────────────────────────────────────


class TestResolveBuildOrder:
    def test_target_with_chain(self):
        images = [
            {"name": "base", "from": "debian:bookworm"},
            {"name": "mid", "from": "base"},
            {"name": "top", "from": "mid"},
        ]
        order = resolve_build_order(images, "top")
        names = [img["name"] for img in order]
        assert names == ["base", "mid", "top"]

    def test_target_only_chain(self):
        """Unrelated images are excluded."""
        images = [
            {"name": "base", "from": "debian:bookworm"},
            {"name": "unrelated", "from": "base"},
            {"name": "target", "from": "base"},
        ]
        order = resolve_build_order(images, "target")
        names = [img["name"] for img in order]
        assert "unrelated" not in names
        assert "base" in names
        assert "target" in names

    def test_all_images(self):
        images = [
            {"name": "b", "from": "a"},
            {"name": "a", "from": "debian:bookworm"},
        ]
        order = resolve_build_order(images, None)
        assert len(order) == 2

    def test_unknown_target(self):
        with pytest.raises(ValueError, match="not defined"):
            resolve_build_order([{"name": "a"}], "nope")

    def test_external_from_not_included(self):
        """from: pointing to non-yo image doesn't add it to the chain."""
        images = [
            {"name": "app", "from": "debian:bookworm"},
        ]
        order = resolve_build_order(images, "app")
        assert len(order) == 1
        assert order[0]["name"] == "app"


# ── load_images ──────────────────────────────────────────────


class TestLoadImages:
    def test_empty_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
        assert load_images() == []

    def test_loads_from_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-xdg"))
        _write_yaml(
            tmp_path / ".yolo" / "images.yaml",
            {"images": [{"name": "proj-img", "from": "debian:bookworm"}]},
        )
        images = load_images()
        assert len(images) == 1
        assert images[0]["name"] == "proj-img"

    def test_collects_from_multiple_layers(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

        _write_yaml(
            xdg / "yolo" / "images.yaml",
            {"images": [{"name": "user-img", "from": "debian:bookworm"}]},
        )
        _write_yaml(
            tmp_path / ".yolo" / "images.yaml",
            {"images": [{"name": "proj-img", "from": "user-img"}]},
        )

        images = load_images()
        names = [img["name"] for img in images]
        assert "user-img" in names
        assert "proj-img" in names

    def test_no_config_returns_defaults_only(self, tmp_path, monkeypatch):
        # Set up defaults
        defaults = tmp_path / "defaults.yaml"
        _write_yaml(defaults, {"images": [{"name": "builtin"}]})
        monkeypatch.setattr("yolo.images.DEFAULTS_IMAGES", defaults)

        # Set up user config that should be ignored
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        _write_yaml(
            tmp_path / ".yolo" / "images.yaml",
            {"images": [{"name": "proj-img"}]},
        )

        images = load_images(no_config=True)
        assert len(images) == 1
        assert images[0]["name"] == "builtin"

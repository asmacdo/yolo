"""Tests for secrets.yaml loader and @secrets: env resolver."""

import os

import pytest

from yolo.secrets import (
    SecretsError,
    load_secrets,
    resolve_env,
    resolve_env_entry,
)


def _write(path, text, mode=0o600):
    path.write_text(text)
    os.chmod(path, mode)


class TestLoadSecrets:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_secrets(tmp_path / "nope.yaml") == {}

    def test_valid_600(self, tmp_path):
        p = tmp_path / "secrets.yaml"
        _write(p, "gh-ro: ghp_abc\nother: xyz\n", 0o600)
        assert load_secrets(p) == {"gh-ro": "ghp_abc", "other": "xyz"}

    def test_wrong_mode_refused(self, tmp_path):
        p = tmp_path / "secrets.yaml"
        _write(p, "gh-ro: ghp_abc\n", 0o644)
        with pytest.raises(SecretsError, match="0644"):
            load_secrets(p)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "secrets.yaml"
        _write(p, "", 0o600)
        assert load_secrets(p) == {}

    def test_non_map_refused(self, tmp_path):
        p = tmp_path / "secrets.yaml"
        _write(p, "- just\n- a list\n", 0o600)
        with pytest.raises(SecretsError, match="flat YAML map"):
            load_secrets(p)

    def test_values_stringified(self, tmp_path):
        p = tmp_path / "secrets.yaml"
        _write(p, "numeric: 12345\n", 0o600)
        assert load_secrets(p) == {"numeric": "12345"}

    def test_chmod_hint_in_error(self, tmp_path):
        p = tmp_path / "secrets.yaml"
        _write(p, "a: b\n", 0o640)
        with pytest.raises(SecretsError, match="chmod 600"):
            load_secrets(p)


class TestResolveEntry:
    def test_bare_name_passthrough(self):
        assert resolve_env_entry("HOME", {}) == "HOME"

    def test_literal_value_passthrough(self):
        assert resolve_env_entry("FOO=bar", {}) == "FOO=bar"

    def test_resolves_reference(self):
        secrets = {"gh-ro": "ghp_abc"}
        assert (
            resolve_env_entry("GITHUB_TOKEN=@secrets:gh-ro", secrets)
            == "GITHUB_TOKEN=ghp_abc"
        )

    def test_missing_key_errors(self):
        with pytest.raises(SecretsError, match="'gh-ro' not found"):
            resolve_env_entry("GITHUB_TOKEN=@secrets:gh-ro", {"other": "x"})

    def test_missing_file_errors(self, tmp_path):
        path = tmp_path / "secrets.yaml"
        with pytest.raises(SecretsError, match="does not exist"):
            resolve_env_entry("GITHUB_TOKEN=@secrets:gh-ro", {}, secrets_path=path)

    def test_empty_secret_errors(self):
        with pytest.raises(SecretsError, match="empty"):
            resolve_env_entry("GITHUB_TOKEN=@secrets:gh-ro", {"gh-ro": ""})

    def test_empty_reference_errors(self):
        with pytest.raises(SecretsError, match="Empty secret key"):
            resolve_env_entry("FOO=@secrets:", {"x": "y"})


class TestResolveEnv:
    def test_no_refs_no_file_load(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        # No secrets.yaml exists — should not error since nothing references it.
        assert resolve_env(["FOO=bar", "HOME"]) == ["FOO=bar", "HOME"]

    def test_resolves_mixed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        secrets_dir = tmp_path / "yolo"
        secrets_dir.mkdir()
        _write(secrets_dir / "secrets.yaml", "gh-ro: ghp_abc\n", 0o600)
        result = resolve_env(["FOO=bar", "TOKEN=@secrets:gh-ro", "HOME"])
        assert result == ["FOO=bar", "TOKEN=ghp_abc", "HOME"]

    def test_ref_without_file_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        with pytest.raises(SecretsError, match="does not exist"):
            resolve_env(["TOKEN=@secrets:gh-ro"])

    def test_ref_with_bad_perms_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        secrets_dir = tmp_path / "yolo"
        secrets_dir.mkdir()
        _write(secrets_dir / "secrets.yaml", "gh-ro: ghp_abc\n", 0o644)
        with pytest.raises(SecretsError, match="0644"):
            resolve_env(["TOKEN=@secrets:gh-ro"])

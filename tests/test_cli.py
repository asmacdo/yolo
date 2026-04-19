"""Tests for yolo CLI commands."""

from importlib.metadata import version
from unittest.mock import patch

from click.testing import CliRunner

from yolo.cli import main


def test_version_flag():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert version("con-yolo") in result.output


class TestClip:
    def test_clip_no_content(self, tmp_path):
        with patch("yolo.cli.Path.home", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(main, ["clip"])
            assert result.exit_code != 0
            assert "Nothing to clip" in result.output

    def test_clip_copies_content(self, tmp_path):
        clip_dir = tmp_path / ".local" / "share" / "yolo" / "clip"
        clip_dir.mkdir(parents=True)
        (clip_dir / "content").write_text("hello world")

        with (
            patch("yolo.cli.Path.home", return_value=tmp_path),
            patch("yolo.cli.subprocess.run") as mock_run,
            patch("yolo.cli.load_config", return_value={}),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["clip"])
            assert result.exit_code == 0
            assert "11 chars" in result.output
            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs["input"] == "hello world"

    def test_clip_custom_command(self, tmp_path):
        clip_dir = tmp_path / ".local" / "share" / "yolo" / "clip"
        clip_dir.mkdir(parents=True)
        (clip_dir / "content").write_text("test")

        with (
            patch("yolo.cli.Path.home", return_value=tmp_path),
            patch("yolo.cli.subprocess.run") as mock_run,
            patch(
                "yolo.cli.load_config",
                return_value={"host_clipboard_command": "wl-copy"},
            ),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["clip"])
            assert result.exit_code == 0
            assert mock_run.call_args[0][0] == ["wl-copy"]


class TestBuild:
    @patch("yolo.cli.builder_build")
    @patch("yolo.cli.load_images", return_value=[{"name": "yolo-default"}])
    @patch("yolo.cli.load_config", return_value={"image": "yolo-default"})
    def test_default_builds_config_image(self, mock_config, mock_images, mock_build):
        runner = CliRunner()
        result = runner.invoke(main, ["build"])
        assert result.exit_code == 0
        mock_build.assert_called_once()
        assert mock_build.call_args.kwargs["target"] == "yolo-default"

    @patch("yolo.cli.builder_build")
    @patch("yolo.cli.load_images", return_value=[{"name": "foo"}])
    @patch("yolo.cli.load_config", return_value={})
    def test_name_overrides_default(self, mock_config, mock_images, mock_build):
        runner = CliRunner()
        result = runner.invoke(main, ["build", "--name", "foo"])
        assert result.exit_code == 0
        assert mock_build.call_args.kwargs["target"] == "foo"

    @patch("yolo.cli.builder_build")
    @patch("yolo.cli.load_images", return_value=[{"name": "a"}, {"name": "b"}])
    @patch("yolo.cli.load_config", return_value={})
    def test_all_flag(self, mock_config, mock_images, mock_build):
        runner = CliRunner()
        result = runner.invoke(main, ["build", "--all"])
        assert result.exit_code == 0
        assert mock_build.call_args.kwargs["all_images"] is True
        assert mock_build.call_args.kwargs["target"] is None

from pathlib import Path
import yaml
import pytest
from lenka_sync.cli import main


def test_plan_without_credentials_or_upload(tmp_path, capsys):
    assert main(["plan", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "[]"
    assert not (tmp_path / "variants").exists()


@pytest.mark.parametrize("arguments", [["import"], ["upload", "--workers", "7"], ["upload", "--limit", "0"]])
def test_invalid_cli_arguments_are_rejected(arguments):
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_workflows_keep_preparation_and_upload_state_separate():
    directory = Path(__file__).parents[1] / ".github/workflows"
    prepare = yaml.safe_load((directory / "prepare.yml").read_text())
    upload = yaml.safe_load((directory / "upload.yml").read_text())
    assert prepare["concurrency"]["group"] != upload["concurrency"]["group"]
    assert upload["concurrency"]["cancel-in-progress"] is False
    assert "PREHRAJTO_PASSWORD" not in prepare["jobs"]["prepare"]["env"]
    assert "AUTOMATION_ENABLED" in upload["jobs"]["upload"]["if"]

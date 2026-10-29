import pytest
from lenka_sync import cli


def test_error_diagnostics_do_not_expose_authenticated_urls(monkeypatch, capsys):
    secret = "private-test-credential"

    def failure():
        raise ValueError("https://source.invalid/?api_key=" + secret)

    monkeypatch.setattr(cli, "main", failure)
    with pytest.raises(SystemExit):
        cli.entrypoint()
    output = capsys.readouterr().out
    assert secret not in output and "source.invalid" not in output
    assert "ValueError" in output and "frames" in output

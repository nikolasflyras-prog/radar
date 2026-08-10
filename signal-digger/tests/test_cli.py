import json

from click.testing import CliRunner

from digger.cli import main


def test_list_sources_shows_every_registered_source():
    result = CliRunner().invoke(main, ["list-sources"])
    assert result.exit_code == 0
    for name in ("sec_edgar", "job_boards", "domain_whois"):
        assert name in result.output


def test_run_requires_exactly_one_target_mode():
    result = CliRunner().invoke(main, ["run"])
    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_run_rejects_multiple_target_modes():
    result = CliRunner().invoke(main, ["run", "Acme", "--person", "Jane Chen"])
    assert result.exit_code != 0
    assert "exactly one" in result.output


def test_run_rejects_unknown_source_name():
    result = CliRunner().invoke(main, ["run", "Acme", "--sources", "not_a_real_source"])
    assert result.exit_code != 0
    assert "Unknown source" in result.output


def test_publish_command_uses_saved_feed_and_fresh_environment_token(tmp_path, monkeypatch):
    feed = tmp_path / "latest.json"
    feed.write_text(json.dumps({"schema_version": 1, "findings": []}), encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "daily:\n  publish_url: https://example.com/ingest\n  publish_token_env: TEST_INGEST_TOKEN\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_INGEST_TOKEN", "fresh-token")
    captured = {}

    def fake_publish(payload, url, token, timeout):
        captured.update(payload=payload, url=url, token=token, timeout=timeout)

    monkeypatch.setattr("digger.cli.publish_daily_payload", fake_publish)
    result = CliRunner().invoke(main, ["publish", str(feed), "--config", str(config)])
    assert result.exit_code == 0
    assert captured["url"] == "https://example.com/ingest"
    assert captured["token"] == "fresh-token"
    assert captured["payload"]["schema_version"] == 1

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

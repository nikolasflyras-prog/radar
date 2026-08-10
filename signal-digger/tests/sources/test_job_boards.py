from digger.models import Target
from digger.sources.job_boards import detect_surge, is_founding_role, slugs_for


def test_is_founding_role():
    assert is_founding_role("Founding Engineer")
    assert is_founding_role("founding designer")
    assert not is_founding_role("Senior Software Engineer")


def test_detect_surge_requires_prior_baseline():
    assert detect_surge(None, 10, threshold=3) is False


def test_detect_surge_true_above_threshold():
    assert detect_surge(5, 9, threshold=3) is True


def test_detect_surge_false_below_threshold():
    assert detect_surge(5, 6, threshold=3) is False


def test_slugs_for_uses_override():
    config = {"job_boards": {"slug_overrides": {"Acme Corp": {"greenhouse": ["acme"], "lever": []}}}}
    target = Target(mode="company", query="Acme Corp")
    assert slugs_for(config, target) == {"greenhouse": ["acme"], "lever": []}


def test_slugs_for_guesses_from_query_when_unconfigured():
    target = Target(mode="company", query="Acme Corp!")
    slugs = slugs_for({}, target)
    assert slugs["greenhouse"] == ["acmecorp"]
    assert slugs["lever"] == ["acmecorp"]


def test_slugs_for_sector_uses_only_explicitly_configured_boards():
    target = Target(mode="sector", query="semiconductor packaging")
    config = {"job_boards": {"greenhouse_slugs": ["nvidia"], "lever_slugs": ["groq"]}}

    assert slugs_for(config, target) == {"greenhouse": ["nvidia"], "lever": ["groq"]}


def test_slugs_for_sector_does_not_guess_when_unconfigured():
    target = Target(mode="sector", query="semiconductor packaging")

    assert slugs_for({}, target) == {"greenhouse": [], "lever": []}

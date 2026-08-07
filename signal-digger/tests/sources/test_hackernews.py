from digger.sources.hackernews import classify_hit


def test_classify_hit_story():
    signal_type, title = classify_hit({"title": "Acme raises Series B"}, "story")
    assert signal_type == "story_mention"
    assert title == "Acme raises Series B"


def test_classify_hit_hiring_thread_comment():
    signal_type, title = classify_hit({"story_title": "Ask HN: Who is hiring? (March 2026)"}, "comment")
    assert signal_type == "hiring_thread_comment"
    assert "Who is hiring" in title


def test_classify_hit_ordinary_comment():
    signal_type, title = classify_hit({"story_title": "Show HN: My new tool"}, "comment")
    assert signal_type == "comment_mention"

from digger.sources.github_people import company_change


def test_company_change_detects_new_employer():
    current, changed = company_change({"company": "@NewCo"}, "Old Company")
    assert current == "NewCo"
    assert changed is True


def test_company_change_no_change_when_same_employer():
    current, changed = company_change({"company": "Old Company"}, "Old Company")
    assert changed is False


def test_company_change_blank_company_field():
    current, changed = company_change({"company": None}, "Old Company")
    assert current == ""
    assert changed is False


def test_company_change_no_prior_employer_known():
    current, changed = company_change({"company": "NewCo"}, "")
    assert current == "NewCo"
    assert changed is False

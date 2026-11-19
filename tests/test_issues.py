from enacit4r_contrib import Issue, Report


def test_warnings_alone_keep_a_report_valid():
    r = Report([Issue("odd", severity="warning")])
    assert r.valid
    assert r.to_dict()["issues"][0]["severity"] == "warning"


def test_one_error_makes_it_invalid():
    assert not Report([Issue("bad", file="a.csv", row=5)]).valid

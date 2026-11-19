import re

import pytest
from pydantic import ValidationError

from enacit4r_contrib import Contributor, Issue, Pipeline, QueueFull, Receipt
from enacit4r_contrib.testing import FakeRepo

ADA = Contributor(name="Ada", email="ada@example.org", institution="EPFL")
PERSON = {"name": "Ada", "email": "ada@example.org", "institution": "EPFL"}


class RecordingSink:
    def __init__(self, open_now=0):
        self.open_now = open_now
        self.calls = []

    async def submit(self, bundle, contributor, report):
        self.calls.append((bundle, contributor, report))
        return Receipt("r1", "https://example.org/r1")

    async def open_count(self):
        return self.open_now


def validator(*issues):
    async def validate(bundle):
        return list(issues)

    return validate


async def test_check_returns_the_validator_issues():
    bad = Issue("bad")
    report = await Pipeline(validator(bad), RecordingSink()).check({"a": b""})
    assert report.issues == [bad] and not report.valid


async def test_invalid_report_skips_the_sink():
    sink = RecordingSink()
    report, receipt = await Pipeline(validator(Issue("bad")), sink).submit({}, ADA)
    assert receipt is None and not report.valid
    assert sink.calls == []


async def test_intake_warnings_come_first_and_reach_the_sink():
    sink = RecordingSink()
    intake = Issue("skipped", severity="warning")
    found = Issue("odd", severity="warning")
    report, receipt = await Pipeline(validator(found), sink).submit({}, ADA, [intake])
    assert report.issues == [intake, found]
    assert receipt == Receipt("r1", "https://example.org/r1")
    assert sink.calls[0][2].issues == [intake, found]


async def test_full_queue_raises():
    sink = RecordingSink(open_now=2)
    with pytest.raises(QueueFull):
        await Pipeline(validator(), sink, max_open=2).submit({}, ADA)
    assert sink.calls == []


async def test_below_max_open_submits():
    sink = RecordingSink(open_now=1)
    _, receipt = await Pipeline(validator(), sink, max_open=2).submit({}, ADA)
    assert receipt.id == "r1"


@pytest.mark.parametrize(
    "change",
    [
        {"orcid": "0000-0002-1825-009"},
        {"orcid": "0000-0002-1825-009Y"},
        {"email": "not-an-email"},
        {"email": "a b@example.org"},
        {"name": "Ada\nLovelace"},
        {"institution": "EPFL\rENAC"},
        {"note": "x" * 2001},
        {"name": ""},
    ],
)
def test_contributor_rejects(change):
    with pytest.raises(ValidationError):
        Contributor(**{**PERSON, **change})


def test_contributor_accepts_and_strips():
    c = Contributor(
        name="  Ada Lovelace ",
        email=" ada@example.org\n",
        institution="EPFL",
        orcid="0000-0002-1825-009X",
        note="first line\nsecond line",
    )
    assert c.name == "Ada Lovelace" and c.email == "ada@example.org"
    assert c.note == "first line\nsecond line"
    assert Contributor(**PERSON, note="x" * 2000).note == "x" * 2000


async def test_fake_repo_get_file():
    repo = FakeRepo(files={"a.txt": b"main"}, branches={"dev": {"a.txt": b"dev"}})
    assert await repo.get_file("a.txt") == b"main"
    assert await repo.get_file("a.txt", ref="dev") == b"dev"
    assert await repo.get_file("a.txt", ref="unknown") == b"main"
    with pytest.raises(FileNotFoundError):
        await repo.get_file("missing.txt")


async def test_fake_repo_branch_commit_carries_base_files():
    repo = FakeRepo(files={"schema.json": b"{}"})
    sha = await repo.create_branch_commit("b1", "main", {"new.csv": b"1"}, "msg")
    assert re.fullmatch(r"[0-9a-f]{40}", sha)
    assert repo.branches["b1"] == {"schema.json": b"{}", "new.csv": b"1"}
    assert await repo.get_file("new.csv", ref="b1") == b"1"
    await repo.create_branch_commit("b2", "b1", {"more.csv": b"2"}, "msg")
    assert set(repo.branches["b2"]) == {"schema.json", "new.csv", "more.csv"}
    assert repo.commits[0] == {
        "branch": "b1",
        "base": "main",
        "message": "msg",
        "files": {"new.csv": b"1"},
    }
    with pytest.raises(RuntimeError):
        await repo.create_branch_commit("b1", "main", {}, "again")


async def test_fake_repo_pulls_and_cleanup():
    repo = FakeRepo()
    await repo.create_branch_commit("b1", "main", {}, "msg")
    pull = await repo.open_pull("b1", "main", "T", "body")
    assert (pull.number, pull.url) == (1, "https://github.test/pull/1")
    await repo.request_reviewers(1, ["alice"])
    assert repo.reviewers == {1: ["alice"]}
    assert await repo.open_pull_heads() == ["b1"]
    await repo.delete_branch("b1")
    assert repo.branches == {} and repo.deleted == ["b1"]


@pytest.mark.parametrize(
    "method,args",
    [
        ("get_file", ("a",)),
        ("create_branch_commit", ("b", "main", {}, "m")),
        ("open_pull", ("b", "main", "t", "")),
        ("request_reviewers", (1, [])),
        ("open_pull_heads", ()),
        ("delete_branch", ("b",)),
    ],
)
async def test_fake_repo_fail_on(method, args):
    repo = FakeRepo(fail_on=method)
    with pytest.raises(RuntimeError, match=method):
        await getattr(repo, method)(*args)

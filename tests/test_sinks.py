import re
from datetime import date

import pytest

from enacit4r_contrib import Contributor, Issue, Report
from enacit4r_contrib.sinks import GitHubPRSink, build_pr_body, slug
from enacit4r_contrib.testing import FakeRepo
from enacit4r_contrib.trailers import INSTITUTION, ORCID, SUBMITTED_BY, parse_trailers

ADA = Contributor(name="Ada Lovelace", email="ada@example.org", institution="EPFL")
BUNDLE = {"data/a.csv": b"id\n1\n", "readme.md": b"hi"}
EMPTY = Report([])


def sink(repo, **kwargs):
    return GitHubPRSink(repo, base="main", today=lambda: date(2026, 11, 19), **kwargs)


async def test_submit_commits_files_and_opens_a_pull():
    repo = FakeRepo()
    receipt = await sink(repo).submit(BUNDLE, ADA, EMPTY)

    assert re.match(r"^2026-11-19-ada-lovelace-[0-9a-f]{6}$", receipt.id)
    commit = repo.commits[0]
    assert commit["branch"] == f"contrib/{receipt.id}"
    assert commit["base"] == "main"
    assert commit["files"] == {
        f"submissions/{receipt.id}/{path}": data for path, data in BUNDLE.items()
    }
    assert "author_name" not in commit  # the contributor is not the git author
    assert parse_trailers(commit["message"]) == {
        SUBMITTED_BY: ["Ada Lovelace <ada@example.org>"],
        INSTITUTION: ["EPFL"],
    }
    assert ORCID not in parse_trailers(commit["message"])
    pull = repo.pulls[0]
    assert pull["title"] == "Data contribution: Ada Lovelace (EPFL)"
    assert receipt.url == pull["url"]
    assert repo.reviewers == {}


async def test_reviewers_are_requested():
    repo = FakeRepo()
    await sink(repo, reviewers=("alice", "bob")).submit(BUNDLE, ADA, EMPTY)
    assert repo.reviewers == {1: ["alice", "bob"]}


async def test_reviewer_failure_does_not_raise():
    repo = FakeRepo(fail_on="request_reviewers")
    receipt = await sink(repo, reviewers=("alice",)).submit(BUNDLE, ADA, EMPTY)
    assert receipt.url == repo.pulls[0]["url"]


@pytest.mark.parametrize("method", ["open_pull", "create_branch_commit"])
async def test_failure_deletes_the_branch_and_reraises(method):
    repo = FakeRepo(fail_on=method)
    deleted = []
    delete = repo.delete_branch

    async def recording_delete(branch):
        deleted.append(branch)
        await delete(branch)

    repo.delete_branch = recording_delete
    with pytest.raises(RuntimeError, match=method):
        await sink(repo).submit(BUNDLE, ADA, EMPTY)
    assert len(deleted) == 1 and deleted[0].startswith("contrib/2026-11-19-")
    assert repo.branches == {}


async def test_delete_failure_keeps_the_original_error():
    repo = FakeRepo(fail_on="open_pull")

    async def broken_delete(branch):
        raise OSError("gone")

    repo.delete_branch = broken_delete
    with pytest.raises(RuntimeError, match="open_pull"):
        await sink(repo).submit(BUNDLE, ADA, EMPTY)


async def test_open_count_counts_only_its_prefix():
    repo = FakeRepo()
    s = sink(repo)
    await s.submit(BUNDLE, ADA, EMPTY)
    await repo.open_pull("feature/x", "main", "other", "")
    await sink(repo, branch_prefix="other/").submit(BUNDLE, ADA, EMPTY)
    assert await s.open_count() == 1


def test_slug():
    assert slug("Ève Ñoño") == "eve-nono"
    assert slug("北京") == "contribution"
    assert slug("  --Ada  Lovelace!!  ") == "ada-lovelace"
    long = slug("a" * 39 + " b" * 10)
    assert len(long) <= 40 and not long.endswith("-")
    assert slug("x" * 100) == "x" * 40


def test_pr_body_breaks_mentions_but_not_emails():
    c = ADA.model_copy(
        update={"note": "Thanks @octocat!\nSecond line", "orcid": "0000-0002-1825-0097"}
    )
    report = Report(
        [
            Issue(
                "odd value", file="data/a.csv", row=3, column="x", severity="warning"
            ),
            Issue("blocking", severity="error"),
        ]
    )
    body = build_pr_body(c, list(BUNDLE), report)
    assert "@\u200boctocat" in body and "@octocat" not in body
    assert "ada@example.org" in body
    assert "0000-0002-1825-0097" in body
    assert "> Thanks" in body and "> Second line" in body
    assert "<details>" in body and "data/a.csv" in body and "readme.md" in body
    assert "odd value" in body and "row 3" in body and "column x" in body
    assert "blocking" not in body
    assert body.splitlines()[-1] == "Checked by enacit4r-contrib"


async def test_table_merge_commits_at_own_paths():
    from enacit4r_contrib.tables import TableMerge

    repo = FakeRepo(files={"data/a.csv": b"id,src\n1,x\n"})
    bundle = {"data/a.csv": b"id\n2\n", "readme.md": b"hi"}
    t = TableMerge("data/a.csv", fixed={"src": "web"})
    await sink(repo, table=t).submit(bundle, ADA, EMPTY)
    assert repo.commits[0]["files"] == {
        "data/a.csv": b"id,src\n1,x\n2,web\n",
        "readme.md": b"hi",
    }


async def test_table_merge_duplicate_makes_no_branch():
    from enacit4r_contrib.tables import DuplicateIds, TableMerge

    repo = FakeRepo(files={"data/a.csv": b"id\n1\n"})
    with pytest.raises(DuplicateIds) as e:
        await sink(repo, table=TableMerge("data/a.csv")).submit(BUNDLE, ADA, EMPTY)
    assert e.value.ids == ["1"]
    assert repo.branches == {}


async def test_table_merge_needs_the_file_in_the_bundle():
    from enacit4r_contrib.tables import TableError, TableMerge

    repo = FakeRepo(files={"data/b.csv": b"id\n1\n"})
    with pytest.raises(TableError, match="data/b.csv"):
        await sink(repo, table=TableMerge("data/b.csv")).submit(BUNDLE, ADA, EMPTY)

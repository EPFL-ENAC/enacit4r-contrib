from enacit4r_contrib import open_contributions
from enacit4r_contrib.issues import Report
from enacit4r_contrib.pipeline import Contributor
from enacit4r_contrib.repo import CommentInfo
from enacit4r_contrib.sinks import GitHubPRSink
from enacit4r_contrib.testing import FakeRepo

ADA = Contributor(name="Ada", email="ada@example.org", institution="EPFL")
BOB = Contributor(
    name="Bob", email="bob@example.org", institution="ETH", orcid="0000-0002-1825-0097"
)


async def test_open_contributions_reads_the_submitter_from_the_trailers():
    repo = FakeRepo(files={"s.json": b"{}"})
    sink = GitHubPRSink(repo, base="main")
    await sink.submit({"a.csv": b"1"}, ADA, Report([]))
    await sink.submit({"b.csv": b"2"}, BOB, Report([]))
    await repo.create_branch_commit("fix/x", "main", {"x": b"x"}, "fix")
    await repo.open_pull("fix/x", "main", "Fix", "")

    got = await open_contributions(repo)
    assert [c.pull.number for c in got] == [2, 1]
    bob, ada = got
    assert (bob.submitter_name, bob.submitter_email) == ("Bob", "bob@example.org")
    assert bob.trailers["ORCID"] == ["0000-0002-1825-0097"]
    assert (ada.submitter_name, ada.submitter_email) == ("Ada", "ada@example.org")
    assert ada.trailers["Institution"] == ["EPFL"]

    everything = await open_contributions(repo, branch_prefix="")
    assert [c.pull.number for c in everything] == [3, 2, 1]
    assert everything[0].trailers == {} and everything[0].submitter_name == ""


async def test_fake_repo_reads():
    repo = FakeRepo(files={"d/a.json": b"a", "d/sub/b.json": b"b", "top": b"t"})
    await repo.create_branch_commit("c", "main", {"d/n.json": b"n"}, "add")
    head = repo.heads["c"]
    await repo.commit_on_branch(
        "c", head, {"d/a.json": b"A"}, "edit", author=("E", "e@x")
    )
    await repo.open_pull("c", "main", "T", "B")
    await repo.create_branch_commit("old", "main", {}, "old")
    await repo.open_pull("old", "main", "Old", "")
    repo.pulls[1]["open"] = False
    note = CommentInfo(1, "u", "User", "ok", "h", "c", "u")
    repo.comments[1] = [note]

    pulls = await repo.open_pulls()
    assert [p.number for p in pulls] == [1]
    assert pulls[0].head_ref == "c" and pulls[0].head_sha == repo.heads["c"]
    assert await repo.open_pulls("dev") == []
    assert (await repo.get_pull(2)).state == "closed"
    commits = await repo.pull_commits(1)
    assert [c.message for c in commits] == ["add", "edit"]
    assert (commits[1].author_name, commits[1].author_email) == ("E", "e@x")
    assert commits[0].author_name == "" and commits[0].sha != commits[1].sha
    assert await repo.pull_comments(1) == [note]
    assert await repo.pull_comments(2) == []
    assert await repo.list_dir("d") == ["a.json"]
    assert await repo.list_dir("d", ref="c") == ["a.json", "n.json"]
    assert await repo.list_dir("") == ["top"]

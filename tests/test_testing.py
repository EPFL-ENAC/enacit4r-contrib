import pytest

from enacit4r_contrib.repo import BranchMoved, PullFile, blob_sha
from enacit4r_contrib.testing import FakeRepo


async def make():
    repo = FakeRepo(files={"a.txt": b"a", "b.txt": b"b"})
    head = await repo.create_branch_commit("c", "main", {"new.txt": b"n"}, "m")
    await repo.open_pull("c", "main", "T", "B")
    return repo, head


async def test_commit_on_branch_adds_a_commit_and_moves_the_head():
    repo, head = await make()
    assert repo.heads["c"] == head
    sha = await repo.commit_on_branch(
        "c", head, {"a.txt": b"A"}, "edit", deletions=["b.txt"], author=("A", "a@x")
    )
    assert sha != head
    assert repo.heads["c"] == sha
    assert repo.branches["c"] == {"a.txt": b"A", "new.txt": b"n"}
    assert repo.commits[-1] == {
        "branch": "c",
        "head": head,
        "message": "edit",
        "files": {"a.txt": b"A"},
        "deletions": ["b.txt"],
        "author": ("A", "a@x"),
    }
    assert await repo.pull_files(1) == [
        PullFile("a.txt", "modified", blob_sha(b"A")),
        PullFile("new.txt", "added", blob_sha(b"n")),
    ]


async def test_commit_on_branch_raises_when_the_branch_moved():
    repo, _ = await make()
    with pytest.raises(BranchMoved) as info:
        await repo.commit_on_branch("c", "old", {"a.txt": b"A"}, "edit")
    assert info.value.branch == "c"


async def test_commit_on_branch_with_nothing_to_write_returns_head():
    repo, head = await make()
    known = {"a.txt": blob_sha(b"A")}
    assert (
        await repo.commit_on_branch("c", head, {"a.txt": b"A"}, "m", known=known)
        == head
    )
    assert await repo.commit_on_branch("c", head, {"new.txt": b"n"}, "m") == head
    assert len(repo.commits) == 1


async def test_update_pull_body():
    repo, _ = await make()
    await repo.update_pull_body(1, "new")
    assert repo.pulls[0]["body"] == "new"

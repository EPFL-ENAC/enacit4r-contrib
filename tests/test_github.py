import asyncio
import base64
from types import SimpleNamespace

import httpx
import pytest
from githubkit import (
    AppInstallationAuthStrategy,
    GitHub,
    Response,
    TokenAuthStrategy,
)
from githubkit.exception import RequestFailed

from enacit4r_contrib.github import GitHubRepo, blob_sha
from enacit4r_contrib.repo import PullRef


def ok(data):
    parsed = SimpleNamespace(**data) if isinstance(data, dict) else data
    return SimpleNamespace(json=lambda: data, parsed_data=parsed)


def failed(status):
    request = httpx.Request("GET", "https://api.github.com/x")
    return RequestFailed(Response(httpx.Response(status, request=request), dict))


class FakeGit:
    def __init__(self):
        self.calls = []
        self.blobs = {}
        self.in_flight = 0
        self.max_in_flight = 0
        self.stored_blobs = {}

    async def async_get_ref(self, owner, repo, ref):
        self.calls.append(("get_ref", ref))
        return ok({"object": {"sha": "base-sha"}})

    async def async_get_commit(self, owner, repo, sha):
        self.calls.append(("get_commit", sha))
        return ok({"sha": sha, "tree": {"sha": "base-tree"}})

    async def async_create_blob(self, owner, repo, *, content, encoding):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        sha = f"blob{len(self.blobs)}"
        self.blobs[sha] = (content, encoding)
        return ok({"sha": sha})

    async def async_create_tree(self, owner, repo, *, base_tree, tree):
        self.tree = {"base_tree": base_tree, "tree": tree}
        return ok({"sha": "new-tree"})

    async def async_create_commit(self, owner, repo, **kwargs):
        self.commit = kwargs
        return ok({"sha": "new-commit"})

    async def async_create_ref(self, owner, repo, *, ref, sha):
        self.ref = (ref, sha)
        return ok({})

    async def async_get_blob(self, owner, repo, sha):
        return ok({"content": self.stored_blobs[sha], "encoding": "base64"})

    async def async_delete_ref(self, owner, repo, ref):
        self.calls.append(("delete_ref", ref))
        raise failed(422)


class FakeRepos:
    def __init__(self):
        self.contents = {}
        self.kwargs = None

    async def async_get_content(self, owner, repo, path, **kwargs):
        self.kwargs = kwargs
        if path not in self.contents:
            raise failed(404)
        return ok(self.contents[path])


class FakePulls:
    def __init__(self):
        self.calls = []
        self.open = []

    async def async_create(self, owner, repo, **kwargs):
        self.calls.append(("create", kwargs))
        return ok({"number": 7, "html_url": "https://github.com/o/r/pull/7"})

    async def async_request_reviewers(self, owner, repo, number, *, reviewers):
        self.calls.append(("reviewers", number, reviewers))

    async def async_list(self, owner, repo, *, state, per_page, page):
        self.calls.append(("list", page))
        start = (page - 1) * per_page
        return ok([{"head": {"ref": b}} for b in self.open[start : start + per_page]])


@pytest.fixture
def repo():
    r = GitHubRepo("owner/name", token="t")
    r._gh = SimpleNamespace(
        rest=SimpleNamespace(git=FakeGit(), repos=FakeRepos(), pulls=FakePulls())
    )
    return r


async def test_create_branch_commit_sends_binary_as_base64_on_base_tree(repo):
    png = b"\x89PNG\x00\xff"
    sha = await repo.create_branch_commit(
        "contrib/x",
        "main",
        {"img.png": png, "a.csv": b"id\n1\n"},
        "msg",
    )
    git = repo._gh.rest.git
    assert sha == "new-commit"
    assert ("get_ref", "heads/main") in git.calls
    assert ("get_commit", "base-sha") in git.calls
    sent = {base64.b64decode(c) for c, enc in git.blobs.values() if enc == "base64"}
    assert sent == {png, b"id\n1\n"}
    assert git.tree["base_tree"] == "base-tree"
    entries = {e["path"]: e for e in git.tree["tree"]}
    assert set(entries) == {"img.png", "a.csv"}
    assert all(e["mode"] == "100644" and e["type"] == "blob" for e in entries.values())
    assert base64.b64decode(git.blobs[entries["img.png"]["sha"]][0]) == png
    assert git.commit["tree"] == "new-tree"
    assert git.commit["parents"] == ["base-sha"]
    assert "author" not in git.commit  # the App is the author
    assert git.commit["message"] == "msg"
    assert git.ref == ("refs/heads/contrib/x", "new-commit")


async def test_at_most_8_blob_uploads_in_flight(repo):
    files = {f"f{i}.txt": bytes([i]) for i in range(30)}
    await repo.create_branch_commit("b", "main", files, "m")
    assert repo._gh.rest.git.max_in_flight == 8
    assert len(repo._gh.rest.git.blobs) == 30


async def test_get_file_decodes_newline_wrapped_base64(repo):
    encoded = base64.b64encode(b"x" * 100).decode()
    wrapped = "\n".join(encoded[i : i + 60] for i in range(0, len(encoded), 60)) + "\n"
    repo._gh.rest.repos.contents["a.txt"] = {
        "type": "file",
        "content": wrapped,
        "sha": "s",
    }
    assert await repo.get_file("a.txt") == b"x" * 100
    assert repo._gh.rest.repos.kwargs == {}
    await repo.get_file("a.txt", ref="dev")
    assert repo._gh.rest.repos.kwargs == {"ref": "dev"}


async def test_get_file_falls_back_to_blob_api_for_large_files(repo):
    repo._gh.rest.repos.contents["big.bin"] = {
        "type": "file",
        "content": "",
        "sha": "big",
    }
    repo._gh.rest.git.stored_blobs["big"] = base64.b64encode(b"\x00\xffbig").decode()
    assert await repo.get_file("big.bin") == b"\x00\xffbig"


async def test_get_file_directory_and_missing(repo):
    repo._gh.rest.repos.contents["data"] = [{"type": "file", "name": "a.csv"}]
    with pytest.raises(IsADirectoryError):
        await repo.get_file("data")
    with pytest.raises(FileNotFoundError):
        await repo.get_file("nope.csv")


async def test_open_pull(repo):
    ref = await repo.open_pull("b", "main", "T", "B")
    assert ref == PullRef(7, "https://github.com/o/r/pull/7")
    assert repo._gh.rest.pulls.calls == [
        ("create", {"head": "b", "base": "main", "title": "T", "body": "B"})
    ]


async def test_open_pull_heads_reads_all_pages(repo):
    repo._gh.rest.pulls.open = [f"b{i}" for i in range(101)]
    heads = await repo.open_pull_heads()
    assert heads == [f"b{i}" for i in range(101)]
    assert repo._gh.rest.pulls.calls == [("list", 1), ("list", 2)]


async def test_request_reviewers(repo):
    await repo.request_reviewers(7, [])
    assert repo._gh.rest.pulls.calls == []
    await repo.request_reviewers(7, ["alice"])
    assert repo._gh.rest.pulls.calls == [("reviewers", 7, ["alice"])]


async def test_delete_branch_swallows_github_error(repo, caplog):
    await repo.delete_branch("b")
    assert ("delete_ref", "heads/b") in repo._gh.rest.git.calls
    assert "could not delete branch b" in caplog.text


def test_constructor_picks_auth_strategy():
    assert isinstance(GitHubRepo("o/r", token="t")._gh.auth, TokenAuthStrategy)
    app = GitHubRepo(
        "o/r", app_id="1", private_key="-----BEGIN\\nKEY", installation_id=2
    )
    assert isinstance(app._gh.auth, AppInstallationAuthStrategy)
    assert app._gh.auth.private_key == "-----BEGIN\nKEY"
    assert app._gh.config.timeout == httpx.Timeout(30)


@pytest.mark.parametrize(
    "repo_name, kwargs",
    [
        ("o/r", {}),
        ("o/r", {"app_id": "1", "private_key": "k"}),
        ("o/r", {"app_id": "1", "installation_id": 2, "token": "t"}),
        ("noslash", {"token": "t"}),
        ("a/b/c", {"token": "t"}),
        ("/r", {"token": "t"}),
    ],
)
def test_constructor_rejects(repo_name, kwargs):
    with pytest.raises(ValueError):
        GitHubRepo(repo_name, **kwargs)


async def test_permission_maps_404_to_none_and_reads_the_role(repo):
    roles = {
        "ada": {"permission": "write", "role_name": "maintain"},
        "bob": {"permission": "read", "role_name": "custom-role"},
    }

    async def get_level(owner, name, username):
        if username not in roles:
            raise failed(404)
        return ok(roles[username])

    repo._gh.rest.repos.async_get_collaborator_permission_level = get_level
    assert await repo.permission("nobody") == "none"
    assert await repo.permission("ada") == "maintain"
    assert await repo.permission("bob") == "read"


def test_blob_sha_matches_git_hash_object():
    # printf 'one\n' | git hash-object --stdin
    assert blob_sha(b"one\n") == "5626abf0f72e58d7a153368ba57db4c673c0e171"


async def test_commit_tree_uploads_every_file_without_known(repo):
    png = b"\x89PNG\x00\xff"
    sha = await repo.commit_tree("p", {"a.csv": b"id\n1\n", "img.png": png}, "m")
    git = repo._gh.rest.git
    assert sha == "new-commit"
    assert git.tree["base_tree"] == "p"
    assert [e["path"] for e in git.tree["tree"]] == ["a.csv", "img.png"]
    blobs = {e["path"]: git.blobs[e["sha"]] for e in git.tree["tree"]}
    assert blobs["a.csv"] == ("id\n1\n", "utf-8")
    assert blobs["img.png"] == (base64.b64encode(png).decode(), "base64")
    assert git.commit["parents"] == ["p"]
    assert git.commit["tree"] == "new-tree"
    assert "author" not in git.commit
    assert not hasattr(git, "ref")


async def test_commit_tree_skips_known_unchanged_and_appends_deletions(repo):
    files = {"same.txt": b"one\n", "new.txt": b"two\n"}
    known = {"same.txt": blob_sha(b"one\n"), "new.txt": blob_sha(b"old\n")}
    await repo.commit_tree(
        "p", files, "m", known=known, deletions=["gone.txt"], author=("A", "a@x")
    )
    git = repo._gh.rest.git
    assert len(git.blobs) == 1
    assert [(e["path"], e["sha"]) for e in git.tree["tree"]] == [
        ("new.txt", "blob0"),
        ("gone.txt", None),
    ]
    assert git.commit["author"] == {"name": "A", "email": "a@x"}


async def test_commit_tree_with_nothing_to_write_returns_parent(repo):
    known = {"a.txt": blob_sha(b"x")}
    assert await repo.commit_tree("p", {"a.txt": b"x"}, "m", known=known) == "p"
    git = repo._gh.rest.git
    assert git.blobs == {}
    assert not hasattr(git, "tree")
    assert not hasattr(git, "commit")


def test_constructor_uses_injected_github_and_rejects_credentials_with_it():
    gh = GitHub(TokenAuthStrategy("t"))
    assert GitHubRepo("o/r", github=gh)._gh is gh
    with pytest.raises(ValueError):
        GitHubRepo("o/r", github=gh, token="t")
    with pytest.raises(ValueError):
        GitHubRepo("o/r", github=gh, app_id="1")

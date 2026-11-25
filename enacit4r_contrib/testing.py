"""An in-memory `Repo` for your own tests.

    repo = FakeRepo(files={"schema.json": b"{}"})
    sink = GitHubPRSink(repo, base="main")
    ...
    assert repo.pulls[0]["title"] == "Data contribution: Ada (EPFL)"

`files` is the default branch. Each method records what it did in `branches`,
`commits`, `pulls`, `reviewers` or `deleted`. `comments` maps a pull request
number to its comments. `heads` maps a branch to its last
commit sha. `permissions` maps a GitHub
login to its role on the repository (absent: "none"). Set `fail_on` to a method name
to make that method raise RuntimeError.
"""

import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field

from enacit4r_contrib.repo import (
    BranchMoved,
    CommentInfo,
    CommitInfo,
    PullFile,
    PullInfo,
    PullRef,
    blob_sha,
)


@dataclass
class FakeRepo:
    files: dict[str, bytes] = field(default_factory=dict)
    branches: dict[str, dict[str, bytes]] = field(default_factory=dict)
    commits: list[dict] = field(default_factory=list)
    pulls: list[dict] = field(default_factory=list)
    reviewers: dict[int, list[str]] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    permissions: dict[str, str] = field(default_factory=dict)
    heads: dict[str, str] = field(default_factory=dict)
    comments: dict[int, list[CommentInfo]] = field(default_factory=dict)
    fail_on: str | None = None

    def _maybe_fail(self, method: str) -> None:
        if self.fail_on == method:
            raise RuntimeError(f"{method} failed (fail_on)")

    async def get_file(self, path: str, ref: str | None = None) -> bytes:
        self._maybe_fail("get_file")
        tree = self.branches.get(ref, self.files) if ref else self.files
        if path not in tree:
            raise FileNotFoundError(path)
        return tree[path]

    async def create_branch_commit(
        self, branch: str, base: str, files: dict[str, bytes], message: str
    ) -> str:
        self._maybe_fail("create_branch_commit")
        if branch in self.branches:
            raise RuntimeError(f"branch {branch} exists")
        self.branches[branch] = {**self.branches.get(base, self.files), **files}
        self.commits.append(
            {"branch": branch, "base": base, "message": message, "files": files}
        )
        sha = secrets.token_hex(20)
        self.heads[branch] = sha
        return sha

    async def commit_on_branch(
        self,
        branch: str,
        head: str,
        files: dict[str, bytes],
        message: str,
        *,
        deletions: Sequence[str] = (),
        author: tuple[str, str] | None = None,
        known: dict[str, str] | None = None,
    ) -> str:
        self._maybe_fail("commit_on_branch")
        if self.heads.get(branch) != head:
            raise BranchMoved(branch)
        known = known or {}
        tree = self.branches[branch]
        changed = {
            p: data for p, data in files.items() if known.get(p) != blob_sha(data)
        }
        changed = {p: data for p, data in changed.items() if tree.get(p) != data}
        gone = [p for p in deletions if p in tree]
        if not changed and not gone:
            return head
        tree.update(changed)
        for p in gone:
            del tree[p]
        self.commits.append(
            {
                "branch": branch,
                "head": head,
                "message": message,
                "files": changed,
                "deletions": gone,
                "author": author,
            }
        )
        sha = secrets.token_hex(20)
        self.heads[branch] = sha
        return sha

    async def update_pull_body(self, number: int, body: str) -> None:
        self._maybe_fail("update_pull_body")
        self.pulls[number - 1]["body"] = body

    async def pull_files(self, number: int) -> list[PullFile]:
        self._maybe_fail("pull_files")
        pull = self.pulls[number - 1]
        base = self.branches.get(pull["base"], self.files)
        return [
            PullFile(p, "modified" if p in base else "added", blob_sha(data))
            for p, data in self.branches[pull["branch"]].items()
            if base.get(p) != data
        ]

    async def open_pull(self, branch: str, base: str, title: str, body: str) -> PullRef:
        self._maybe_fail("open_pull")
        number = len(self.pulls) + 1
        url = f"https://github.test/pull/{number}"
        self.pulls.append(
            {
                "number": number,
                "branch": branch,
                "base": base,
                "title": title,
                "body": body,
                "url": url,
                "open": True,
            }
        )
        return PullRef(number, url)

    async def request_reviewers(self, number: int, logins: list[str]) -> None:
        self._maybe_fail("request_reviewers")
        self.reviewers[number] = list(logins)

    async def open_pull_heads(self) -> list[str]:
        self._maybe_fail("open_pull_heads")
        return [p["branch"] for p in self.pulls if p.get("open")]

    async def delete_branch(self, branch: str) -> None:
        self._maybe_fail("delete_branch")
        self.branches.pop(branch, None)
        self.deleted.append(branch)

    async def permission(self, login: str) -> str:
        self._maybe_fail("permission")
        return self.permissions.get(login, "none")

    def _pull_info(self, p: dict) -> PullInfo:
        return PullInfo(
            number=p["number"],
            url=p["url"],
            title=p["title"],
            body=p["body"],
            state="open" if p.get("open") else "closed",
            draft=False,
            author="",
            author_type="",
            head_ref=p["branch"],
            head_sha=self.heads.get(p["branch"], ""),
            head_repo="",
            base_ref=p["base"],
            created_at="",
            updated_at="",
        )

    async def open_pulls(
        self, base: str | None = None, *, limit: int = 100
    ) -> list[PullInfo]:
        self._maybe_fail("open_pulls")
        pulls = [
            p
            for p in reversed(self.pulls)
            if p.get("open") and (not base or p["base"] == base)
        ]
        return [self._pull_info(p) for p in pulls[:limit]]

    async def get_pull(self, number: int) -> PullInfo:
        self._maybe_fail("get_pull")
        return self._pull_info(self.pulls[number - 1])

    async def pull_commits(self, number: int) -> list[CommitInfo]:
        self._maybe_fail("pull_commits")
        branch = self.pulls[number - 1]["branch"]
        out = []
        for c in self.commits:
            if c["branch"] != branch:
                continue
            name, email = c.get("author") or ("", "")
            sha = c.get("sha") or blob_sha(f"{branch}\0{len(out)}".encode())
            out.append(CommitInfo(sha, c["message"], name, email, ""))
        return out

    async def pull_comments(self, number: int) -> list[CommentInfo]:
        self._maybe_fail("pull_comments")
        return list(self.comments.get(number, []))

    async def list_dir(self, path: str, ref: str | None = None) -> list[str]:
        self._maybe_fail("list_dir")
        tree = self.branches.get(ref, self.files) if ref else self.files
        prefix = path.strip("/") + "/" if path.strip("/") else ""
        return sorted(
            p[len(prefix) :]
            for p in tree
            if p.startswith(prefix) and "/" not in p[len(prefix) :]
        )

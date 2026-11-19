"""An in-memory `Repo` for your own tests.

    repo = FakeRepo(files={"schema.json": b"{}"})
    sink = GitHubPRSink(repo, base="main")
    ...
    assert repo.pulls[0]["title"] == "Data contribution: Ada (EPFL)"

`files` is the default branch. Each method records what it did in `branches`,
`commits`, `pulls`, `reviewers` or `deleted`. Set `fail_on` to a method name
to make that method raise RuntimeError.
"""

import secrets
from dataclasses import dataclass, field

from enacit4r_contrib.repo import PullRef


@dataclass
class FakeRepo:
    files: dict[str, bytes] = field(default_factory=dict)
    branches: dict[str, dict[str, bytes]] = field(default_factory=dict)
    commits: list[dict] = field(default_factory=list)
    pulls: list[dict] = field(default_factory=list)
    reviewers: dict[int, list[str]] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
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
        return secrets.token_hex(20)

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

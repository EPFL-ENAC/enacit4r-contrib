"""What a submission needs from a git host. `github.GitHubRepo` implements it,
`testing.FakeRepo` fakes it in memory."""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

# GitHub repository roles, from the lowest to the highest.
ROLES = ("none", "read", "triage", "write", "maintain", "admin")


def blob_sha(data: bytes) -> str:
    """The git blob id of `data`, the same as `git hash-object`."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class BranchMoved(Exception):
    """The branch head is not the commit the edit started from."""

    def __init__(self, branch: str) -> None:
        super().__init__(f"branch {branch} moved")
        self.branch = branch


@dataclass(frozen=True)
class PullFile:
    path: str
    status: str
    sha: str | None


@dataclass(frozen=True)
class PullRef:
    number: int
    url: str


class Repo(Protocol):
    async def get_file(self, path: str, ref: str | None = None) -> bytes:
        """The file's bytes at `ref` (default: the default branch)."""

    async def create_branch_commit(
        self,
        branch: str,
        base: str,
        files: dict[str, bytes],
        message: str,
    ) -> str:
        """Create `branch` from the head of `base` with one commit that adds
        `files` (path -> bytes, text or binary). The authenticated identity
        (the App or the token owner) is the author: a contributor is not a
        verified GitHub user, so they are named in the message trailers only.
        Return the commit sha."""

    async def open_pull(self, branch: str, base: str, title: str, body: str) -> PullRef:
        """Open a pull request from `branch` into `base`."""

    async def request_reviewers(self, number: int, logins: list[str]) -> None:
        """Ask these GitHub users to review the pull request."""

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
        """Add one commit on top of `head` to `branch` and return its sha.
        Skip each file whose blob sha equals `known[path]`. Return `head` and
        move nothing when there is nothing to write. Raise `BranchMoved` when
        the head of `branch` is no longer `head`."""

    async def update_pull_body(self, number: int, body: str) -> None:
        """Replace the body of the pull request."""

    async def pull_files(self, number: int) -> list[PullFile]:
        """The files the pull request changes (at most 3000)."""

    async def open_pull_heads(self) -> list[str]:
        """The head branch names of every open pull request."""

    async def delete_branch(self, branch: str) -> None:
        """Delete the branch (cleanup after a failed submission)."""


class Permissions(Protocol):
    async def permission(self, login: str) -> str:
        """The GitHub user's role on the repository: "admin", "maintain",
        "write", "triage", "read" or "none" (not a collaborator)."""

"""What a submission needs from a git host. `github.GitHubRepo` implements it,
`testing.FakeRepo` fakes it in memory."""

from dataclasses import dataclass
from typing import Protocol


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

    async def open_pull_heads(self) -> list[str]:
        """The head branch names of every open pull request."""

    async def delete_branch(self, branch: str) -> None:
        """Delete the branch (cleanup after a failed submission)."""

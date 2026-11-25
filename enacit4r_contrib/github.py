"""`Repo` on the GitHub REST API, through githubkit (install the `github` extra)."""

import asyncio
import base64
import logging
from collections.abc import Sequence

from githubkit import AppInstallationAuthStrategy, GitHub, TokenAuthStrategy
from githubkit.exception import RequestFailed

from enacit4r_contrib.repo import (
    ROLES,
    BranchMoved,
    CommentInfo,
    CommitInfo,
    PullFile,
    PullInfo,
    PullRef,
    blob_sha,
)

log = logging.getLogger(__name__)

MAX_BLOB_UPLOADS = 8
PAGE_SIZE = 100


__all__ = ["GitHubRepo", "blob_sha"]
MAX_PULL_FILE_PAGES = 30  # GitHub lists at most 3000 files.
MAX_PULL_COMMIT_PAGES = 3  # GitHub lists at most 250 commits.
MAX_COMMENT_PAGES = 10


def _pull_info(p) -> PullInfo:
    user, head_repo = p.user, p.head.repo
    return PullInfo(
        number=p.number,
        url=p.html_url,
        title=p.title,
        body=p.body or "",
        state=p.state,
        draft=bool(p.draft),
        author=user.login if user else "",
        author_type=user.type if user else "",
        head_ref=p.head.ref,
        head_sha=p.head.sha,
        head_repo=head_repo.full_name if head_repo else "",
        base_ref=p.base.ref,
        created_at=str(p.created_at),
        updated_at=str(p.updated_at),
    )


class GitHubRepo:
    """Authenticates as a GitHub App installation, or with a token."""

    def __init__(
        self,
        repo: str,
        *,
        app_id: str | None = None,
        private_key: str | None = None,
        installation_id: int | None = None,
        token: str | None = None,
        github: GitHub | None = None,
    ) -> None:
        owner, sep, name = repo.partition("/")
        if not sep or not owner or not name or "/" in name:
            raise ValueError(f"repo must be 'owner/name', got {repo!r}")
        self.owner, self.name = owner, name

        app = (app_id, private_key, installation_id)
        if github is not None:
            if token is not None or any(v is not None for v in app):
                raise ValueError("give github or the credentials, not both")
            self._gh = github
            return
        if all(v is not None for v in app):
            # Env vars often carry the PEM on one line with literal "\n".
            auth = AppInstallationAuthStrategy(
                app_id, private_key.replace("\\n", "\n"), installation_id
            )
        elif any(v is not None for v in app):
            raise ValueError("app_id, private_key and installation_id go together")
        elif token:
            auth = TokenAuthStrategy(token)
        else:
            raise ValueError("give a token or the GitHub App credentials")
        self._gh = GitHub(auth, timeout=30)

    async def get_file(self, path: str, ref: str | None = None) -> bytes:
        kwargs = {"ref": ref} if ref else {}
        try:
            resp = await self._gh.rest.repos.async_get_content(
                self.owner, self.name, path, **kwargs
            )
        except RequestFailed as e:
            if e.response.status_code == 404:
                raise FileNotFoundError(path) from e
            raise
        data = resp.json()
        if isinstance(data, list) or data.get("type") == "dir":
            raise IsADirectoryError(path)
        if data.get("content"):
            return base64.b64decode(data["content"])
        # Files over 1 MB come without inline content.
        blob = await self._gh.rest.git.async_get_blob(
            self.owner, self.name, data["sha"]
        )
        return base64.b64decode(blob.json()["content"])

    async def create_branch_commit(
        self,
        branch: str,
        base: str,
        files: dict[str, bytes],
        message: str,
    ) -> str:
        git = self._gh.rest.git
        ref = await git.async_get_ref(self.owner, self.name, f"heads/{base}")
        base_sha = ref.json()["object"]["sha"]
        base_commit = await git.async_get_commit(self.owner, self.name, base_sha)
        base_tree = base_commit.json()["tree"]["sha"]

        slots = asyncio.Semaphore(MAX_BLOB_UPLOADS)

        async def upload(content: bytes) -> str:
            async with slots:
                blob = await git.async_create_blob(
                    self.owner,
                    self.name,
                    content=base64.b64encode(content).decode(),
                    encoding="base64",
                )
            return blob.json()["sha"]

        paths = list(files)
        shas = await asyncio.gather(*(upload(files[p]) for p in paths))
        tree = await git.async_create_tree(
            self.owner,
            self.name,
            base_tree=base_tree,
            tree=[
                {"path": p, "mode": "100644", "type": "blob", "sha": s}
                for p, s in zip(paths, shas, strict=True)
            ],
        )
        commit = await git.async_create_commit(
            self.owner,
            self.name,
            message=message,
            tree=tree.json()["sha"],
            parents=[base_sha],
        )
        sha = commit.json()["sha"]
        await git.async_create_ref(
            self.owner, self.name, ref=f"refs/heads/{branch}", sha=sha
        )
        return sha

    async def commit_tree(
        self,
        parent: str,
        files: dict[str, bytes],
        message: str,
        *,
        deletions: list[str] = (),
        author: tuple[str, str] | None = None,
        known: dict[str, str] | None = None,
    ) -> str:
        """Make one commit on top of the commit `parent` and return its sha.

        Move no ref. Skip each file whose blob sha equals `known[path]`.
        Return `parent` when there is nothing to write."""
        git = self._gh.rest.git
        known = known or {}
        paths = [p for p, data in files.items() if known.get(p) != blob_sha(data)]
        slots = asyncio.Semaphore(MAX_BLOB_UPLOADS)

        async def upload(data: bytes) -> str:
            try:
                kwargs = {"content": data.decode(), "encoding": "utf-8"}
            except UnicodeDecodeError:
                kwargs = {
                    "content": base64.b64encode(data).decode(),
                    "encoding": "base64",
                }
            async with slots:
                blob = await git.async_create_blob(self.owner, self.name, **kwargs)
            return blob.parsed_data.sha

        shas = await asyncio.gather(*(upload(files[p]) for p in paths))
        entries = [
            {"path": p, "mode": "100644", "type": "blob", "sha": s}
            for p, s in zip(paths, shas, strict=True)
        ] + [
            {"path": p, "mode": "100644", "type": "blob", "sha": None}
            for p in deletions
        ]
        if not entries:
            return parent
        tree = await git.async_create_tree(
            self.owner, self.name, base_tree=parent, tree=entries
        )
        extra = {"author": {"name": author[0], "email": author[1]}} if author else {}
        commit = await git.async_create_commit(
            self.owner,
            self.name,
            message=message,
            tree=tree.parsed_data.sha,
            parents=[parent],
            **extra,
        )
        return commit.parsed_data.sha

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
        sha = await self.commit_tree(
            head, files, message, deletions=deletions, author=author, known=known
        )
        if sha == head:
            return head
        try:
            await self._gh.rest.git.async_update_ref(
                self.owner,
                self.name,
                ref=f"heads/{branch}",
                data={"sha": sha, "force": False},
            )
        except RequestFailed as e:
            if e.response.status_code == 422:
                raise BranchMoved(branch) from e
            raise
        return sha

    async def update_pull_body(self, number: int, body: str) -> None:
        await self._gh.rest.pulls.async_update(
            self.owner, self.name, number, data={"body": body}
        )

    async def pull_files(self, number: int) -> list[PullFile]:
        out: list[PullFile] = []
        for page in range(1, MAX_PULL_FILE_PAGES + 1):
            resp = await self._gh.rest.pulls.async_list_files(
                self.owner, self.name, number, per_page=PAGE_SIZE, page=page
            )
            items = resp.parsed_data
            out += [PullFile(f.filename, f.status, f.sha) for f in items]
            if len(items) < PAGE_SIZE:
                break
        return out

    async def open_pull(self, branch: str, base: str, title: str, body: str) -> PullRef:
        resp = await self._gh.rest.pulls.async_create(
            self.owner, self.name, head=branch, base=base, title=title, body=body
        )
        data = resp.json()
        return PullRef(number=data["number"], url=data["html_url"])

    async def request_reviewers(self, number: int, logins: list[str]) -> None:
        if not logins:
            return
        await self._gh.rest.pulls.async_request_reviewers(
            self.owner, self.name, number, data={"reviewers": logins}
        )

    async def open_pull_heads(self) -> list[str]:
        heads: list[str] = []
        page = 1
        while True:
            resp = await self._gh.rest.pulls.async_list(
                self.owner, self.name, state="open", per_page=PAGE_SIZE, page=page
            )
            pulls = resp.json()
            heads += [p["head"]["ref"] for p in pulls]
            if len(pulls) < PAGE_SIZE:
                return heads
            page += 1

    async def open_pulls(
        self, base: str | None = None, *, limit: int = 100
    ) -> list[PullInfo]:
        """The open pull requests, newest first, at most `limit`."""
        per_page = min(limit, PAGE_SIZE)
        extra = {"base": base} if base else {}
        out: list[PullInfo] = []
        page = 1
        while len(out) < limit:
            resp = await self._gh.rest.pulls.async_list(
                self.owner,
                self.name,
                state="open",
                sort="created",
                direction="desc",
                per_page=per_page,
                page=page,
                **extra,
            )
            items = resp.parsed_data
            out += [_pull_info(p) for p in items]
            if len(items) < per_page:
                break
            page += 1
        return out[:limit]

    async def get_pull(self, number: int) -> PullInfo:
        resp = await self._gh.rest.pulls.async_get(self.owner, self.name, number)
        return _pull_info(resp.parsed_data)

    async def pull_commits(self, number: int) -> list[CommitInfo]:
        out: list[CommitInfo] = []
        for page in range(1, MAX_PULL_COMMIT_PAGES + 1):
            resp = await self._gh.rest.pulls.async_list_commits(
                self.owner, self.name, number, per_page=PAGE_SIZE, page=page
            )
            items = resp.parsed_data
            for item in items:
                author = item.commit.author
                out.append(
                    CommitInfo(
                        sha=item.sha,
                        message=item.commit.message or "",
                        author_name=getattr(author, "name", "") or "",
                        author_email=getattr(author, "email", "") or "",
                        author_date=str(getattr(author, "date", "") or ""),
                    )
                )
            if len(items) < PAGE_SIZE:
                break
        return out

    async def pull_comments(self, number: int) -> list[CommentInfo]:
        out: list[CommentInfo] = []
        for page in range(1, MAX_COMMENT_PAGES + 1):
            resp = await self._gh.rest.issues.async_list_comments(
                self.owner, self.name, number, per_page=PAGE_SIZE, page=page
            )
            items = resp.parsed_data
            out += [
                CommentInfo(
                    id=c.id,
                    author=c.user.login if c.user else "",
                    author_type=c.user.type if c.user else "",
                    body=c.body if isinstance(c.body, str) else "",
                    url=c.html_url,
                    created_at=str(c.created_at),
                    updated_at=str(c.updated_at),
                )
                for c in items
            ]
            if len(items) < PAGE_SIZE:
                break
        return out

    async def list_dir(self, path: str, ref: str | None = None) -> list[str]:
        """The names of the files (not folders) at `path`."""
        kwargs = {"ref": ref} if ref else {}
        try:
            resp = await self._gh.rest.repos.async_get_content(
                self.owner, self.name, path, **kwargs
            )
        except RequestFailed as e:
            if e.response.status_code == 404:
                return []
            raise
        items = resp.parsed_data
        if not isinstance(items, list):
            return []
        return [i.name for i in items if i.type == "file"]

    async def permission(self, login: str) -> str:
        try:
            resp = await self._gh.rest.repos.async_get_collaborator_permission_level(
                self.owner, self.name, login
            )
        except RequestFailed as e:
            if e.response.status_code == 404:
                return "none"
            raise
        data = resp.json()
        # `permission` holds only the legacy roles (maintain shows as write,
        # triage as read): `role_name` has the exact role, or a custom name.
        if data.get("role_name") in ROLES:
            return data["role_name"]
        return data["permission"]

    async def delete_branch(self, branch: str) -> None:
        # Runs during cleanup: raising here would hide the error that caused it,
        # so any error is logged, not only the ones githubkit raises.
        try:
            await self._gh.rest.git.async_delete_ref(
                self.owner, self.name, f"heads/{branch}"
            )
        except Exception:
            log.exception("could not delete branch %s", branch)

"""`Repo` on the GitHub REST API, through githubkit (install the `github` extra)."""

import asyncio
import base64
import hashlib
import logging

from githubkit import AppInstallationAuthStrategy, GitHub, TokenAuthStrategy
from githubkit.exception import GitHubException, RequestFailed

from enacit4r_contrib.repo import ROLES, PullRef

log = logging.getLogger(__name__)

MAX_BLOB_UPLOADS = 8
PAGE_SIZE = 100


def blob_sha(data: bytes) -> str:
    """The git blob id of `data`, the same as `git hash-object`."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


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
            self.owner, self.name, number, reviewers=logins
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
        # Runs during cleanup: raising here would hide the error that caused it.
        try:
            await self._gh.rest.git.async_delete_ref(
                self.owner, self.name, f"heads/{branch}"
            )
        except GitHubException:
            log.exception("could not delete branch %s", branch)

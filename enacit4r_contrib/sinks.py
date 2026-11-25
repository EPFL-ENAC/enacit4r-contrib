"""A sink that submits each contribution as a GitHub pull request."""

import logging
import re
import secrets
import unicodedata
from collections.abc import Callable, Sequence
from datetime import date

from enacit4r_contrib.issues import Report
from enacit4r_contrib.pipeline import Bundle, Contributor, Receipt
from enacit4r_contrib.repo import Repo
from enacit4r_contrib.tables import TableError, TableMerge, merge_rows
from enacit4r_contrib.trailers import build_commit_message

log = logging.getLogger(__name__)

_MENTION = re.compile(r"(?<![A-Za-z0-9_.])@")


def slug(value: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    cut = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:40].strip("-")
    return cut or "contribution"


def build_pr_body(contributor: Contributor, paths: list[str], report: Report) -> str:
    c = contributor
    lines = [
        "## Contributor",
        "",
        f"- Name: {c.name}",
        f"- Email: {c.email}",
        f"- Institution: {c.institution}",
    ]
    if c.orcid:
        lines.append(f"- ORCID: {c.orcid}")
    if c.note:
        lines += ["", *(f"> {line}" for line in c.note.splitlines())]
    lines += [
        "",
        f"<details><summary>Files ({len(paths)})</summary>",
        "",
        *(f"- `{p}`" for p in paths),
        "",
        "</details>",
    ]
    warnings = [i for i in report.issues if i.severity == "warning"]
    if warnings:
        lines += ["", "## Warnings", ""]
        for w in warnings:
            where = ", ".join(
                f"{label} {value}"
                for label, value in (
                    ("file", w.file),
                    ("row", w.row),
                    ("column", w.column),
                )
                if value is not None
            )
            lines.append(f"- {w.message}" + (f" ({where})" if where else ""))
    lines += ["", "Checked by enacit4r-contrib"]
    # A zero-width space after a word-initial "@" stops GitHub from pinging anyone.
    return _MENTION.sub("@\u200b", "\n".join(lines))


class GitHubPRSink:
    """Submits a contribution as one branch, one commit and one pull request."""

    def __init__(
        self,
        repo: Repo,
        *,
        base: str,
        folder: str = "submissions",
        branch_prefix: str = "contrib/",
        reviewers: Sequence[str] = (),
        title: str = "Data contribution",
        today: Callable[[], date] = date.today,
        table: TableMerge | None = None,
    ):
        self.repo = repo
        self.base = base
        self.folder = folder
        self.branch_prefix = branch_prefix
        self.reviewers = reviewers
        self.title = title
        self.today = today
        self.table = table

    async def submit(
        self, bundle: Bundle, contributor: Contributor, report: Report
    ) -> Receipt:
        c = contributor
        id_ = f"{self.today():%Y-%m-%d}-{slug(c.name)}-{secrets.token_hex(3)}"
        branch = self.branch_prefix + id_
        if self.table is None:
            files = {
                f"{self.folder}/{id_}/{path}": data for path, data in bundle.items()
            }
        else:
            files = await self._merged(bundle)
        try:
            await self.repo.create_branch_commit(
                branch,
                self.base,
                files,
                build_commit_message(f"{self.title} from {c.name}", c),
            )
            pull = await self.repo.open_pull(
                branch,
                self.base,
                f"{self.title}: {c.name} ({c.institution})",
                build_pr_body(c, list(bundle), report),
            )
        except Exception:
            try:
                await self.repo.delete_branch(branch)
            except Exception:
                log.exception("could not delete branch %s", branch)
            raise
        if self.reviewers:
            try:
                await self.repo.request_reviewers(pull.number, list(self.reviewers))
            except Exception:
                log.exception("could not request reviewers on #%s", pull.number)
        return Receipt(id_, pull.url)

    async def _merged(self, bundle: Bundle) -> dict[str, bytes]:
        t = self.table
        if t.path not in bundle:
            raise TableError(f"The bundle has no file {t.path!r}")
        current = await self.repo.get_file(t.path, ref=self.base)
        merged = merge_rows(
            current, bundle[t.path], id_column=t.id_column, fill=t.fill, fixed=t.fixed
        )
        return {**bundle, t.path: merged}

    async def open_count(self) -> int:
        heads = await self.repo.open_pull_heads()
        return sum(h.startswith(self.branch_prefix) for h in heads)

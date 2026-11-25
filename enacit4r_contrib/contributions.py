"""Read the open contributions of a repository, for a curation page."""

import asyncio

from enacit4r_contrib.repo import Contribution, PullInfo
from enacit4r_contrib.trailers import SUBMITTED_BY, parse_trailers, split_address

MAX_IN_FLIGHT = 8


async def open_contributions(
    repo, base: str | None = None, *, branch_prefix: str = "contrib/", limit: int = 100
) -> list[Contribution]:
    """The open pull requests whose head branch starts with `branch_prefix`,
    each with the trailers of its first commit that has a `Submitted-by`.

    `repo` needs `open_pulls` and `pull_commits` (see `Repo`)."""
    pulls = await repo.open_pulls(base, limit=limit)
    pulls = [p for p in pulls if p.head_ref.startswith(branch_prefix)]
    slots = asyncio.Semaphore(MAX_IN_FLIGHT)

    async def one(pull: PullInfo) -> Contribution:
        async with slots:
            commits = await repo.pull_commits(pull.number)
        trailers: dict[str, list[str]] = {}
        for c in commits:
            parsed = parse_trailers(c.message)
            if parsed.get(SUBMITTED_BY):
                trailers = parsed
                break
        name, email = split_address(trailers[SUBMITTED_BY][0]) if trailers else ("", "")
        return Contribution(pull, trailers, name, email)

    return list(await asyncio.gather(*(one(p) for p in pulls)))

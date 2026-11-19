"""Git trailers that record who submitted a contribution."""

import re

from enacit4r_contrib.pipeline import Contributor

SUBMITTED_BY = "Submitted-by"
INSTITUTION = "Institution"
ORCID = "ORCID"

_TRAILER = re.compile(r"^([A-Za-z0-9-]+): (.*)$")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def build_commit_message(title: str, c: Contributor) -> str:
    name = _one_line(c.name.replace("<", "").replace(">", ""))
    lines = [
        f"{SUBMITTED_BY}: {name} <{_one_line(c.email)}>",
        f"{INSTITUTION}: {_one_line(c.institution)}",
    ]
    if c.orcid:
        lines.append(f"{ORCID}: {_one_line(c.orcid)}")
    return f"{_one_line(title)}\n\n" + "\n".join(lines)


def parse_trailers(message: str) -> dict[str, list[str]]:
    """The `Key: value` lines of the last paragraph, or {} if it holds anything else."""
    paragraphs = [p for p in re.split(r"\n\s*\n", message.strip()) if p.strip()]
    if not paragraphs:
        return {}
    trailers: dict[str, list[str]] = {}
    for line in paragraphs[-1].splitlines():
        if not line.strip():
            continue
        match = _TRAILER.match(line.strip())
        if not match:
            return {}
        trailers.setdefault(match[1], []).append(match[2])
    return trailers

"""Git trailers that record who submitted a contribution."""

import re
from collections.abc import Sequence

from enacit4r_contrib.pipeline import Contributor

SUBMITTED_BY = "Submitted-by"
INSTITUTION = "Institution"
ORCID = "ORCID"

_TRAILER = re.compile(r"^([A-Za-z0-9-]+):[ \t]*(.*)$")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def format_trailers(title: str, trailers: Sequence[tuple[str, str]]) -> str:
    """The title, a blank line, then one `Key: value` line per pair.

    Values are made one line. A pair with an empty value is left out."""
    lines = [f"{k}: {v}" for k, v in ((k, _one_line(v)) for k, v in trailers) if v]
    if not lines:
        return _one_line(title)
    return f"{_one_line(title)}\n\n" + "\n".join(lines)


def address(name: str, email: str) -> str:
    """`Name <email>`, with `<` and `>` removed from the name."""
    return f"{_one_line(name.replace('<', '').replace('>', ''))} <{_one_line(email)}>"


def split_address(value: str) -> tuple[str, str]:
    """The inverse of `address`: `(name, email)`, email "" if absent."""
    match = re.fullmatch(r"\s*(.*?)\s*<([^<>]*)>\s*", value)
    if not match:
        return value.strip(), ""
    return match[1], match[2].strip()


def build_commit_message(
    title: str, c: Contributor, *, extra: Sequence[tuple[str, str]] = ()
) -> str:
    return format_trailers(
        title,
        [
            (SUBMITTED_BY, address(c.name, c.email)),
            (INSTITUTION, c.institution),
            (ORCID, c.orcid or ""),
            *extra,
        ],
    )


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
        trailers.setdefault(match[1], []).append(match[2].strip())
    return trailers

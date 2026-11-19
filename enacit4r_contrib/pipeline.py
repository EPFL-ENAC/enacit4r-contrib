"""The core: check a bundle, then hand a valid one to a sink."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from enacit4r_contrib.issues import Issue, Report

Bundle = dict[str, bytes]
"""The submitted files: relative POSIX path -> content."""

_ONE_LINE = r"^[^\r\n]+$"


class Contributor(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200, pattern=_ONE_LINE)
    email: str = Field(
        min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )
    institution: str = Field(min_length=1, max_length=200, pattern=_ONE_LINE)
    orcid: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
    note: str | None = Field(default=None, max_length=2000)


Validator = Callable[[Bundle], Awaitable[list[Issue]]]


@dataclass(frozen=True)
class Receipt:
    id: str
    url: str


class Sink(Protocol):
    async def submit(
        self, bundle: Bundle, contributor: Contributor, report: Report
    ) -> Receipt: ...

    async def open_count(self) -> int:
        """Contributions submitted and not reviewed yet."""
        ...


class QueueFull(Exception):
    """Too many contributions wait for review."""


class Pipeline:
    def __init__(self, validate: Validator, sink: Sink, *, max_open: int = 25):
        self.validate = validate
        self.sink = sink
        self.max_open = max_open

    async def check(self, bundle: Bundle) -> Report:
        return Report(await self.validate(bundle))

    async def submit(
        self, bundle: Bundle, contributor: Contributor, intake: Sequence[Issue] = ()
    ) -> tuple[Report, Receipt | None]:
        report = Report([*intake, *await self.validate(bundle)])
        if not report.valid:
            return report, None
        if await self.sink.open_count() >= self.max_open:
            raise QueueFull
        return report, await self.sink.submit(bundle, contributor, report)

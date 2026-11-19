"""The one problem format every stage returns: browser, backend and CI."""

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class Issue:
    message: str
    file: str | None = None
    row: int | None = None  # 1-based line in the file, header rows included
    column: str | None = None
    value: str | None = None
    severity: Literal["error", "warning"] = "error"


@dataclass
class Report:
    issues: list[Issue]

    @property
    def valid(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def to_dict(self) -> dict:
        return {"valid": self.valid, "issues": [asdict(i) for i in self.issues]}

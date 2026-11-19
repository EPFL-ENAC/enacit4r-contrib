"""Helpers for a project's ingest command: check every change, then write.

A project keeps only its domain rules. These helpers read the submission,
number the new rows, append to a CSV without rewriting its bytes, and
apply the file changes only when all of them can succeed.
"""

import argparse
import csv
import io
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path

from enacit4r_contrib.issues import Issue
from enacit4r_contrib.pipeline import Bundle

__all__ = [
    "IngestError",
    "Plan",
    "csv_lines",
    "format_issue",
    "next_number",
    "read_folder",
    "run",
]


class IngestError(Exception):
    def __init__(self, message: str, issues: list[Issue] | None = None):
        super().__init__(message)
        self.message = message
        self.issues = issues or []


def read_folder(folder: Path) -> Bundle:
    """Every file under `folder`, keyed by its relative POSIX path."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in folder.rglob("*")
        if p.is_file()
    }


def format_issue(issue: Issue) -> str:
    """One line: `error: file.csv:5 [Column]: message`."""
    where = ":".join(str(x) for x in (issue.file, issue.row) if x is not None)
    col = f" [{issue.column}]" if issue.column else ""
    return f"{issue.severity}: {where}{col}: {issue.message}"


def next_number(values: Iterable[str]) -> int:
    """1 + the largest value that parses as a number, or 1 when none does."""
    numbers = []
    for v in values:
        try:
            numbers.append(int(float(v)))
        except (ValueError, OverflowError):
            pass  # text, empty, and NaN/inf are not numbers here
    return max(numbers, default=0) + 1


def csv_lines(path: Path, rows: list[list[str]]) -> bytes:
    """The bytes to append to the CSV at `path` so that `rows` follow its last line.

    Uses the line ending of the file (CRLF if it has one, else LF) and UTF-8.
    """
    old = path.read_bytes()
    eol = "\r\n" if b"\r\n" in old else "\n"
    out = io.StringIO()
    csv.writer(out, lineterminator=eol).writerows(rows)
    lead = eol if old and not old.endswith(b"\n") else ""
    return (lead + out.getvalue()).encode("utf-8")


class Plan:
    """File changes checked as a whole before the first write."""

    def __init__(self) -> None:
        self.appends: list[tuple[Path, list[list[str]]]] = []
        self.creates: list[tuple[Path, bytes]] = []
        self.removes: list[Path] = []

    def append(self, path: Path, rows: list[list[str]]) -> None:
        """Append `rows` to the existing CSV at `path`."""
        self.appends.append((path, rows))

    def create(self, path: Path, content: bytes) -> None:
        """Write a new file at `path`. The file must not exist."""
        self.creates.append((path, content))

    def remove(self, folder: Path) -> None:
        """Delete `folder` after all the other changes."""
        self.removes.append(folder)

    def check(self) -> None:
        """Raise IngestError that names every problem of the plan."""
        problems = []
        seen: set[Path] = set()
        for path, _ in self.creates:
            if path in seen:
                problems.append(Issue("is created twice", file=str(path)))
            elif path.exists():
                problems.append(Issue("already exists", file=str(path)))
            seen.add(path)
        for path, _ in self.appends:
            if not path.is_file():
                problems.append(Issue("does not exist", file=str(path)))
        if problems:
            raise IngestError("the ingest plan cannot be applied", problems)

    def apply(self) -> None:
        """Check, then append, then create, then remove."""
        self.check()
        for path, rows in self.appends:
            lines = csv_lines(path, rows)
            with path.open("ab") as f:
                f.write(lines)
        for path, content in self.creates:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        for folder in self.removes:
            shutil.rmtree(folder)


def run(ingest: Callable[[Path], list[str]], argv: list[str] | None = None) -> int:
    """Command line `prog <submission>`: print the lines of `ingest`, or its errors."""
    ap = argparse.ArgumentParser()
    ap.add_argument("submission", type=Path)
    a = ap.parse_args(argv)
    try:
        lines = ingest(a.submission)
    except IngestError as e:
        print(e.message)
        for i in e.issues:
            print(format_issue(i))
        return 1
    for line in lines:
        print(line)
    return 0

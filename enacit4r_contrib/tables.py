"""Merge contributed CSV rows into one main table per data type."""

import csv
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from enacit4r_contrib.issues import Issue


class TableError(ValueError):
    pass


class DuplicateIds(TableError):
    def __init__(self, ids: list[str]):
        self.ids = ids
        super().__init__(f"Duplicate identifiers: {', '.join(ids)}")


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]
    newline: str


@dataclass(frozen=True)
class TableMerge:
    path: str
    id_column: str = "id"
    fill: str = ""
    fixed: Mapping[str, str] = field(default_factory=dict)


def _text(data: bytes) -> str:
    return data.decode("utf-8").removeprefix("﻿")


def read_table(data: bytes) -> Table:
    text = _text(data)
    records = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if not records:
        raise TableError("The table is empty")
    newline = "\r\n" if "\r\n" in text else "\n"
    return Table(records[0], records[1:], newline)


def _index(header: list[str], id_column: str) -> int:
    if id_column not in header:
        raise TableError(f"The table has no column {id_column!r}")
    return header.index(id_column)


def table_ids(data: bytes, id_column: str = "id") -> set[str]:
    t = read_table(data)
    i = _index(t.header, id_column)
    return {v for r in t.rows if i < len(r) and (v := r[i].strip())}


def escape_formula(cell: str) -> str:
    if not cell.startswith(("=", "+", "-", "@", "\t", "\r")):
        return cell
    try:
        Decimal(cell)
        return cell
    except InvalidOperation:
        return "'" + cell


def _cell(row: list[str], i: int) -> str:
    return row[i] if i < len(row) else ""


def merge_rows(
    table: bytes,
    rows: bytes,
    *,
    id_column: str = "id",
    fill: str = "",
    fixed: Mapping[str, str] | None = None,
    replace: Iterable[str] = (),
    escape: bool = True,
) -> bytes:
    fixed = fixed or {}
    replace = set(replace)
    base, new = read_table(table), read_table(rows)
    unknown = [c for c in new.header if c not in base.header and c not in fixed]
    if unknown:
        raise TableError(f"Columns not in the table: {', '.join(unknown)}")
    if id_column not in new.header:
        raise TableError(f"The new rows have no column {id_column!r}")
    base_id = _index(base.header, id_column)
    kept = [r for r in base.rows if _cell(r, base_id).strip() not in replace]
    kept_ids = {_cell(r, base_id).strip() for r in kept}

    positions = {c: i for i, c in enumerate(new.header)}
    out_rows, seen, dupes = [], set(), []
    for r in new.rows:
        id_ = _cell(r, positions[id_column]).strip()
        if not id_:
            raise TableError(f"A new row has an empty {id_column!r}")
        if (id_ in seen or id_ in kept_ids) and id_ not in dupes:
            dupes.append(id_)
        seen.add(id_)
        line = []
        for col in base.header:
            if col in fixed:
                line.append(fixed[col])
                continue
            value = _cell(r, positions[col]).strip() if col in positions else ""
            if not value:
                line.append(fill)
            else:
                line.append(escape_formula(value) if escape else value)
        out_rows.append(line)
    if dupes:
        raise DuplicateIds(dupes)

    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator=base.newline)
    writer.writerow(base.header)
    writer.writerows(kept)
    writer.writerows(out_rows)
    return buf.getvalue().encode("utf-8")


def duplicate_id_issues(
    rows: bytes,
    existing: set[str],
    *,
    file: str,
    id_column: str = "id",
    message: str = "Identifier {id} already exists in the data repository",
) -> list[Issue]:
    records = list(csv.reader(io.StringIO(_text(rows))))
    if not records:
        return []
    i = _index(records[0], id_column)
    issues = []
    for n, r in enumerate(records[1:], start=2):
        id_ = _cell(r, i).strip()
        if id_ in existing:
            issues.append(
                Issue(
                    message.format(id=id_),
                    file=file,
                    row=n,
                    column=id_column,
                    value=id_,
                )
            )
    return issues

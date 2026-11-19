import csv
import hashlib
import io
from pathlib import Path

import pytest

from enacit4r_contrib.ingest import (
    IngestError,
    Plan,
    csv_lines,
    format_issue,
    next_number,
    read_folder,
    run,
)
from enacit4r_contrib.issues import Issue


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(p.relative_to(root).as_posix().encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def parse(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))


def test_read_folder_relative_paths(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "top.csv").write_bytes(b"x")
    (tmp_path / "a" / "b" / "c.txt").write_bytes(b"y")
    assert read_folder(tmp_path) == {"top.csv": b"x", "a/b/c.txt": b"y"}


def test_next_number():
    assert next_number(["", "NaN", "12", "7.0", "text"]) == 13
    assert next_number([]) == 1


def test_format_issue():
    issue = Issue("bad", file="file.csv", row=5, column="Column")
    assert format_issue(issue) == "error: file.csv:5 [Column]: bad"


@pytest.mark.parametrize(
    "old",
    [b"\xef\xbb\xbfid,name\n1,a\n", b"id,name\r\n1,a"],
    ids=["bom-lf", "crlf-no-final-newline"],
)
def test_csv_lines_appends_after_last_line(tmp_path, old):
    path = tmp_path / "t.csv"
    path.write_bytes(old)
    new = [["2", 'b, "quoted"'], ["3", "c"]]
    added = csv_lines(path, new)
    assert path.read_bytes() == old
    assert parse(old + added) == parse(old) + new
    eol = b"\r\n" if b"\r\n" in old else b"\n"
    assert added.endswith(eol)
    assert (b"\n" in added.replace(b"\r\n", b"")) == (eol == b"\n")


def test_csv_lines_quotes_comma_and_quote(tmp_path):
    path = tmp_path / "t.csv"
    path.write_bytes(b"id,name\n")
    assert csv_lines(path, [["1", 'a, "b"']]) == b'1,"a, ""b"""\n'


def make_data(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "table.csv").write_bytes(b"id,name\n1,a\n")
    sub = tmp_path / "submission"
    sub.mkdir()
    (sub / "x.txt").write_bytes(b"x")
    return data, sub


def test_plan_apply_writes_all(tmp_path):
    data, sub = make_data(tmp_path)
    plan = Plan()
    plan.append(data / "table.csv", [["2", "b"]])
    plan.create(data / "curves" / "0002.txt", b"curve")
    plan.remove(sub)
    plan.apply()
    assert (data / "table.csv").read_bytes() == b"id,name\n1,a\n2,b\n"
    assert (data / "curves" / "0002.txt").read_bytes() == b"curve"
    assert not sub.exists()


def test_plan_existing_create_target_changes_nothing(tmp_path):
    data, sub = make_data(tmp_path)
    (data / "taken.txt").write_bytes(b"old")
    before = tree_hash(tmp_path)
    plan = Plan()
    plan.append(data / "table.csv", [["2", "b"]])
    plan.create(data / "new.txt", b"new")
    plan.create(data / "taken.txt", b"new")
    plan.remove(sub)
    with pytest.raises(IngestError) as e:
        plan.apply()
    assert [i.file for i in e.value.issues] == [str(data / "taken.txt")]
    assert tree_hash(tmp_path) == before


def test_plan_names_every_problem(tmp_path):
    data, _ = make_data(tmp_path)
    plan = Plan()
    plan.create(data / "new.txt", b"1")
    plan.create(data / "new.txt", b"2")
    plan.append(data / "missing.csv", [["1"]])
    with pytest.raises(IngestError) as e:
        plan.check()
    assert [(i.file, i.message) for i in e.value.issues] == [
        (str(data / "new.txt"), "is created twice"),
        (str(data / "missing.csv"), "does not exist"),
    ]
    assert not (data / "new.txt").exists()


def test_plan_removes_after_creates(tmp_path):
    data, sub = make_data(tmp_path)
    plan = Plan()
    plan.remove(sub)
    plan.create(data / "copy.txt", (sub / "x.txt").read_bytes())
    plan.create(sub / "late.txt", b"late")
    plan.apply()
    assert (data / "copy.txt").read_bytes() == b"x"
    assert not sub.exists()


def test_run_exit_codes(tmp_path, capsys):
    assert run(lambda p: [f"ingested {p.name}"], [str(tmp_path / "s1")]) == 0
    assert capsys.readouterr().out == "ingested s1\n"

    def fail(p: Path) -> list[str]:
        raise IngestError("s1 does not pass", [Issue("bad", file="t.csv", row=3)])

    assert run(fail, ["s1"]) == 1
    assert capsys.readouterr().out == "s1 does not pass\nerror: t.csv:3: bad\n"


def retire(number):
    """Replace the row with id `number` by a row that holds only the id."""
    return lambda row: [row[0], ""] if row[0] == number else row


def test_rewrite_rows_crlf_bom_quoted_and_untouched_bytes(tmp_path):
    path = tmp_path / "t.csv"
    old = b'\xef\xbb\xbfid,name\r\n1,"a, ""x"""\r\n2,b\r\n3,"multi\r\nline"\r\n'
    path.write_bytes(old)
    plan = Plan()
    plan.rewrite_rows(path, retire("2"))
    plan.apply()
    assert path.read_bytes() == old.replace(b"2,b\r\n", b"2,\r\n")
    assert parse(path.read_bytes())[3] == ["3", "multi\r\nline"]


def test_rewrite_rows_replace_quoted_and_delete(tmp_path):
    path = tmp_path / "t.csv"
    path.write_bytes(b"id,name\n1,a\n2,b\n3,c")
    plan = Plan()
    plan.rewrite_rows(
        path,
        lambda r: None if r[0] == "1" else [r[0], 'q, "z"'] if r[0] == "3" else r,
    )
    plan.apply()
    assert path.read_bytes() == b'id,name\n2,b\n3,"q, ""z"""'


def test_rewrite_rows_header_rows_are_never_passed(tmp_path):
    path = tmp_path / "t.csv"
    path.write_bytes(b"id\nunit\n1\n")
    seen = []
    plan = Plan()
    plan.rewrite_rows(path, lambda r: seen.append(r) or None, header_rows=2)
    plan.apply()
    assert seen == [["1"]]
    assert path.read_bytes() == b"id\nunit\n"


def test_rewrite_rows_sees_appended_rows(tmp_path):
    path = tmp_path / "t.csv"
    path.write_bytes(b"id,name\n1,a\n")
    plan = Plan()
    plan.append(path, [["2", "b"]])
    plan.rewrite_rows(path, retire("2"))
    plan.apply()
    assert path.read_bytes() == b"id,name\n1,a\n2,\n"


def test_rewrite_no_match_and_missing_files_write_nothing(tmp_path):
    data, _ = make_data(tmp_path)
    before = tree_hash(tmp_path)
    plan = Plan()
    plan.rewrite_rows(data / "table.csv", lambda r: r)
    plan.rewrite_rows(data / "missing.csv", lambda r: None)
    plan.delete(data / "gone.csv")
    plan.create(data / "new.csv", b"x")
    with pytest.raises(IngestError) as e:
        plan.apply()
    messages = sorted((i.file, i.message) for i in e.value.issues)
    assert messages == [
        (str(data / "gone.csv"), "does not exist"),
        (str(data / "missing.csv"), "does not exist"),
        (str(data / "table.csv"), "no row matches the change"),
    ]
    assert tree_hash(tmp_path) == before


def test_rewrite_no_match_allowed(tmp_path):
    path = tmp_path / "t.csv"
    path.write_bytes(b"id\n1\n")
    plan = Plan()
    plan.rewrite_rows(path, lambda r: r, expect_match=False)
    plan.apply()
    assert path.read_bytes() == b"id\n1\n"


def test_delete_removes_the_file(tmp_path):
    path = tmp_path / "curve.csv"
    path.write_bytes(b"x")
    plan = Plan()
    plan.delete(path)
    plan.apply()
    assert not path.exists()

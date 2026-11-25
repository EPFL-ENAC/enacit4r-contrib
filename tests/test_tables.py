import pytest

from enacit4r_contrib.tables import (
    DuplicateIds,
    TableError,
    duplicate_id_issues,
    escape_formula,
    merge_rows,
    read_table,
    table_ids,
)

TABLE = b"id,name,unit\n1,a,kg\n2,b,m\n"


def test_read_table_bom_crlf_and_blank_rows():
    t = read_table(b"\xef\xbb\xbfid,name\r\n1,a\r\n , \r\n\r\n2,b\r\n")
    assert t.header == ["id", "name"]
    assert t.rows == [["1", "a"], ["2", "b"]]
    assert t.newline == "\r\n"
    assert read_table(b"id\n1\n").newline == "\n"


def test_read_table_empty():
    with pytest.raises(TableError, match="empty"):
        read_table(b"")


def test_table_ids():
    assert table_ids(b"id,x\n 1 ,a\n,b\n2,c\n") == {"1", "2"}
    with pytest.raises(TableError, match="code"):
        table_ids(TABLE, "code")


def test_merge_aligns_by_name_and_fills():
    out = merge_rows(TABLE, b"unit,id\n,3\nkg,4\n", fill="NA")
    assert out == b"id,name,unit\n1,a,kg\n2,b,m\n3,NA,NA\n4,NA,kg\n"


def test_fixed_overrides():
    out = merge_rows(TABLE, b"id,unit\n3,m\n", fixed={"unit": "kg"})
    assert out.endswith(b"3,,kg\n")


def test_unknown_column():
    with pytest.raises(TableError, match="colour"):
        merge_rows(TABLE, b"id,colour\n3,red\n")


def test_missing_and_empty_id():
    with pytest.raises(TableError, match="id"):
        merge_rows(TABLE, b"name\nx\n")
    with pytest.raises(TableError, match="empty"):
        merge_rows(TABLE, b"id,name\n ,x\n")


def test_duplicates_in_table_and_batch():
    with pytest.raises(DuplicateIds) as e:
        merge_rows(TABLE, b"id\n2\n3\n3\n1\n")
    assert e.value.ids == ["2", "3", "1"]


def test_replace_is_an_edit():
    out = merge_rows(TABLE, b"id,name\n2,new\n", replace=["2"])
    assert out == b"id,name,unit\n1,a,kg\n2,new,\n"


def test_crlf_table_keeps_crlf():
    out = merge_rows(b"id,name\r\n1,a\r\n", b"id,name\n2,b\n")
    assert out == b"id,name\r\n1,a\r\n2,b\r\n"


def test_escape_formula():
    assert escape_formula("=SUM(A1)") == "'=SUM(A1)"
    assert escape_formula("-5") == "-5"
    assert escape_formula("-x") == "'-x"
    assert escape_formula("abc") == "abc"
    out = merge_rows(TABLE, b"id,name\n3,=SUM(A1)\n")
    assert out.endswith(b"3,'=SUM(A1),\n")
    assert merge_rows(TABLE, b"id,name\n3,=1\n", escape=False).endswith(b"3,=1,\n")


def test_duplicate_id_issues_rows():
    issues = duplicate_id_issues(
        b"id,name\n1,a\n\n2,b\n9,c\n", {"1", "2"}, file="data/t.csv"
    )
    assert [(i.row, i.value, i.column, i.file) for i in issues] == [
        (2, "1", "id", "data/t.csv"),
        (4, "2", "id", "data/t.csv"),
    ]
    assert issues[0].message == "Identifier 1 already exists in the data repository"
    assert issues[0].severity == "error"

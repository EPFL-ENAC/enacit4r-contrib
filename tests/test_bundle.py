import io
import tarfile
import zipfile

import pytest

from enacit4r_contrib.bundle import BundleError, read_upload
from enacit4r_contrib.issues import Issue

ALLOW = ["*.csv", "*.zip"]


def make_zip(entries, compression=zipfile.ZIP_STORED):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def make_tgz(entries, symlinks=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        for name, target in symlinks:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tf.addfile(info)
    return buf.getvalue()


def test_loose_files_with_dot_slash():
    bundle, issues = read_upload([("./a.csv", b"1"), ("b.csv", b"2")], allow=ALLOW)
    assert bundle == {"a.csv": b"1", "b.csv": b"2"} and issues == []


def test_zip_with_directory_entry():
    data = make_zip([("d/", b""), ("d/a.csv", b"1"), ("e/b.csv", b"2")])
    bundle, issues = read_upload([("up.zip", data)], allow=["*/*.csv"])
    assert bundle == {"d/a.csv": b"1", "e/b.csv": b"2"} and issues == []


def test_tgz_skips_symlink():
    data = make_tgz([("a.csv", b"1")], symlinks=[("link.csv", "/etc/passwd")])
    bundle, issues = read_upload([("up.tgz", data)], allow=ALLOW)
    assert bundle == {"a.csv": b"1"} and issues == []


def test_tar_gz_suffix():
    data = make_tgz([("a.csv", b"1")])
    bundle, _ = read_upload([("UP.tar.gz", data)], allow=ALLOW)
    assert bundle == {"a.csv": b"1"}


@pytest.mark.parametrize("name", ["../x", "a/../b", "/etc/x", "a\\b", "a\x00b", "a//b"])
def test_hostile_loose_path_refuses_all(name):
    with pytest.raises(BundleError, match="Unsafe path"):
        read_upload([("ok.csv", b"1"), (name, b"x")], allow=["*"])


def test_hostile_zip_member():
    data = make_zip([("ok.csv", b"1"), ("../evil", b"x")])
    with pytest.raises(BundleError, match="Unsafe path"):
        read_upload([("up.zip", data)], allow=["*"])


def test_zip_bomb_stops_early():
    data = make_zip([("bomb.csv", b"0" * 10_000_000)], zipfile.ZIP_DEFLATED)
    assert len(data) < 100_000
    with pytest.raises(BundleError, match="too large"):
        read_upload([("up.zip", data)], allow=ALLOW, max_file_bytes=1000)


def test_per_file_limit():
    with pytest.raises(BundleError, match="File too large"):
        read_upload([("a.csv", b"12345")], allow=ALLOW, max_file_bytes=4)
    bundle, _ = read_upload([("a.csv", b"1234")], allow=ALLOW, max_file_bytes=4)
    assert bundle == {"a.csv": b"1234"}


def test_total_limit():
    items = [("a.csv", b"123"), ("b.csv", b"123")]
    with pytest.raises(BundleError, match="Upload too large"):
        read_upload(items, allow=ALLOW, max_total_bytes=5)
    bundle, _ = read_upload(items, allow=ALLOW, max_total_bytes=6)
    assert len(bundle) == 2


def test_count_limit():
    items = [(f"{i}.csv", b"1") for i in range(3)]
    with pytest.raises(BundleError, match="Too many files"):
        read_upload(items, allow=ALLOW, max_files=2)
    bundle, _ = read_upload(items, allow=ALLOW, max_files=3)
    assert len(bundle) == 3


@pytest.mark.parametrize("name", ["up.zip", "up.tgz", "up.tar.gz"])
def test_corrupt_archive(name):
    with pytest.raises(BundleError, match=f"Could not read archive {name}"):
        read_upload([(name, b"not an archive")], allow=ALLOW)


def test_corrupt_zip_member_data():
    data = bytearray(make_zip([("a.csv", b"hello world" * 100)], zipfile.ZIP_DEFLATED))
    data[40:60] = b"\xff" * 20
    with pytest.raises(BundleError, match="Could not read archive up.zip"):
        read_upload([("up.zip", bytes(data))], allow=ALLOW)


def test_top_folder_stripped():
    data = make_zip([("top/a.csv", b"1"), ("top/sub/b.csv", b"2")])
    bundle, issues = read_upload([("up.zip", data)], allow=["*.csv"])
    assert set(bundle) == {"a.csv", "sub/b.csv"} and issues == []


def test_top_folder_not_stripped():
    items = [("top/a.csv", b"1"), ("other/b.csv", b"2")]
    bundle, _ = read_upload(items, allow=["*.csv"])
    assert set(bundle) == {"top/a.csv", "other/b.csv"}
    bundle, _ = read_upload([("top/a.csv", b"1"), ("c.csv", b"3")], allow=["*.csv"])
    assert set(bundle) == {"top/a.csv", "c.csv"}


def test_unexpected_file_dropped():
    bundle, issues = read_upload([("a.csv", b"1"), ("n.txt", b"x")], allow=["*.csv"])
    assert bundle == {"a.csv": b"1"}
    assert issues == [Issue("Unexpected file: not part of the template", file="n.txt")]


def test_duplicate_keeps_first():
    items = [("a.csv", b"1"), ("up.zip", make_zip([("a.csv", b"2")]))]
    bundle, issues = read_upload(items, allow=["*.csv"])
    assert bundle == {"a.csv": b"1"}
    assert issues == [Issue("Duplicate file", file="a.csv")]


def test_unexpected_duplicate_reported_once_each():
    bundle, issues = read_upload([("n.txt", b"1"), ("n.txt", b"2")], allow=["*.csv"])
    assert [i.message for i in issues] == [
        "Unexpected file: not part of the template",
        "Duplicate file",
        "No files to submit",
    ]


def test_empty_bundle():
    bundle, issues = read_upload([], allow=ALLOW)
    assert bundle == {} and issues == [Issue("No files to submit")]


def test_junk_ignored_and_not_counted():
    junk = [
        "__MACOSX/top/._a.csv",
        "top/.DS_Store",
        "top/Thumbs.db",
        "top/desktop.ini",
        "top/._b.csv",
    ]
    data = make_zip([(n, b"x" * 100) for n in junk] + [("top/a.csv", b"1")])
    bundle, issues = read_upload(
        [("up.zip", data)], allow=ALLOW, max_files=1, max_total_bytes=1
    )
    assert bundle == {"a.csv": b"1"} and issues == []


def test_nested_zip_kept_as_file():
    inner = make_zip([("x.csv", b"1")])
    outer = make_zip([("inner.zip", inner)])
    bundle, issues = read_upload([("up.zip", outer)], allow=ALLOW)
    assert bundle == {"inner.zip": inner} and issues == []


def test_all_issues_are_errors():
    _, issues = read_upload([("a.txt", b"1"), ("a.txt", b"1")], allow=ALLOW)
    assert issues and all(i.severity == "error" for i in issues)


def test_skipped_files_are_dropped_with_a_warning():
    bundle, issues = read_upload(
        [("data.csv", b"a"), ("fig/photo.jpg", b"\xff\xd8")],
        allow=["*.csv"],
        skip=["*.jpg"],
    )
    assert list(bundle) == ["data.csv"]
    assert [(i.file, i.severity) for i in issues] == [("fig/photo.jpg", "warning")]


def test_ignore_case_false_refuses_upper_case_suffix():
    bundle, issues = read_upload([("X.PLY", b"p")], allow=["*.ply"])
    assert bundle == {}
    assert issues[0].message.startswith("Unexpected file")


def test_ignore_case_true_matches_and_keeps_the_case():
    bundle, issues = read_upload([("X.PLY", b"p")], allow=["*.ply"], ignore_case=True)
    assert bundle == {"X.PLY": b"p"} and issues == []


def test_ignore_case_true_applies_to_skip():
    bundle, issues = read_upload(
        [("a.ply", b"p"), ("B.TXT", b"t")],
        allow=["*.ply"],
        skip=["*.txt"],
        ignore_case=True,
    )
    assert bundle == {"a.ply": b"p"} and issues[0].severity == "warning"


def test_unexpected_message_can_be_set():
    _, issues = read_upload(
        [("a.txt", b"x"), ("b.ply", b"y")], allow=["*.ply"], unexpected="Not a 3D model"
    )
    assert [(i.file, i.message) for i in issues] == [("a.txt", "Not a 3D model")]

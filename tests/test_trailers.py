from enacit4r_contrib import Contributor
from enacit4r_contrib.trailers import (
    INSTITUTION,
    ORCID,
    SUBMITTED_BY,
    build_commit_message,
    parse_trailers,
)

ADA = Contributor(name="Ada Lovelace", email="ada@example.org", institution="EPFL")


def test_message_has_title_blank_line_and_trailers():
    message = build_commit_message("Data contribution", ADA)
    assert message == (
        "Data contribution\n\n"
        "Submitted-by: Ada Lovelace <ada@example.org>\n"
        "Institution: EPFL"
    )


def test_trailers_parse_back():
    c = ADA.model_copy(update={"orcid": "0000-0002-1825-0097"})
    assert parse_trailers(build_commit_message("T", c)) == {
        SUBMITTED_BY: ["Ada Lovelace <ada@example.org>"],
        INSTITUTION: ["EPFL"],
        ORCID: ["0000-0002-1825-0097"],
    }


def test_orcid_absent_when_unset():
    assert ORCID not in parse_trailers(build_commit_message("T", ADA))


def test_angle_brackets_in_name_cannot_break_the_trailer():
    c = ADA.model_copy(update={"name": "Ada <x>"})
    message = build_commit_message("T", c)
    assert parse_trailers(message)[SUBMITTED_BY] == ["Ada x <ada@example.org>"]
    assert message.count("<") == 1


def test_values_are_made_one_line():
    c = ADA.model_copy(update={"institution": "EPFL\nENAC   IT4R"})
    assert parse_trailers(build_commit_message("T", c))[INSTITUTION] == [
        "EPFL ENAC IT4R"
    ]


def test_prose_last_paragraph_gives_nothing():
    assert parse_trailers("Title\n\nJust some prose: here.\nAnd more.") == {}
    assert parse_trailers("") == {}


def test_repeated_keys_are_kept_in_order():
    assert parse_trailers("T\n\nA: 1\nB: 2\nA: 3") == {"A": ["1", "3"], "B": ["2"]}

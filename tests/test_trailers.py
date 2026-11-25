from enacit4r_contrib import Contributor
from enacit4r_contrib.trailers import (
    INSTITUTION,
    ORCID,
    SUBMITTED_BY,
    address,
    build_commit_message,
    format_trailers,
    parse_trailers,
    split_address,
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


def test_format_trailers_drops_empty_values_and_folds_whitespace():
    assert format_trailers(" A\n title ", [("K", " a\n  b "), ("E", " \n")]) == (
        "A title\n\nK: a b"
    )
    assert format_trailers("T", [("E", "")]) == "T"
    assert format_trailers("T", []) == "T"


def test_address_round_trip():
    value = address("Ada <x> Lovelace", " ada@example.edu ")
    assert value == "Ada x Lovelace <ada@example.edu>"
    assert split_address(value) == ("Ada x Lovelace", "ada@example.edu")
    assert split_address(" plain name ") == ("plain name", "")


def test_build_commit_message_is_unchanged_with_orcid():
    c = ADA.model_copy(update={"orcid": "0000-0002-1825-0097"})
    assert build_commit_message("Data contribution", c) == (
        "Data contribution\n\n"
        "Submitted-by: Ada Lovelace <ada@example.org>\n"
        "Institution: EPFL\n"
        "ORCID: 0000-0002-1825-0097"
    )


def test_build_commit_message_appends_extra_trailers():
    message = build_commit_message(
        "T", ADA, extra=[("Dataset", "walls"), ("Empty", " ")]
    )
    assert message == (
        "T\n\n"
        "Submitted-by: Ada Lovelace <ada@example.org>\n"
        "Institution: EPFL\n"
        "Dataset: walls"
    )


def test_parse_trailers_accepts_no_space_or_a_tab_after_the_colon():
    assert parse_trailers("T\n\nA:1\nB:\t2 \nC:   3") == {
        "A": ["1"],
        "B": ["2"],
        "C": ["3"],
    }

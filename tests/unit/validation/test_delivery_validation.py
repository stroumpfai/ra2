"""Cross-file validation: blocking and non-blocking (mvp-spec.md §4.3).

The organising idea is that **uniqueness is a property of the delivery, not of
a file**. One text file is the join target for every cantonal set, so a
`UnfallUid` shared between AG and BE would attach one canton's narrative to the
other canton's record — and each file, checked alone, would look perfect.
"""

from ra2.domain.delivery import FileKind
from ra2.domain.findings import FindingCode, Severity
from ra2.domain.parsing.headers import (
    OBJEKT_KEY_COLUMN,
    PERSON_KEY_COLUMN,
    TEXT_KEY_COLUMN,
    TEXT_NARRATIVE_COLUMN,
    UNFALL_KEY_COLUMN,
    UNFALL_OBJ_COUNT_COLUMN,
    UNFALL_PERS_COUNT_COLUMN,
)
from ra2.domain.validation import blocking_findings, validate_delivery

# --- duplicate keys, blocking ----------------------------------------------


def test_a_uid_repeated_inside_one_file_is_a_duplicate(build):
    key = build.uid("aa", 1)
    unfall = build.file(
        FileKind.UNFALL,
        [{UNFALL_KEY_COLUMN: key}, {UNFALL_KEY_COLUMN: key}],
    )
    finding = build.only(validate_delivery([unfall]), FindingCode.DUP_KEY_CROSS_SET)
    assert finding.key == key
    assert finding.severity is Severity.BLOCKING


def test_a_uid_repeated_across_two_files_is_the_dangerous_one(build):
    """Each file is internally unique, so only the delivery-wide check finds it."""
    key = build.uid("aa", 1)
    ag = build.file(
        FileKind.UNFALL,
        [{UNFALL_KEY_COLUMN: key}, {UNFALL_KEY_COLUMN: build.uid("aa", 2)}],
        name="ag.txt",
        canton="AG",
    )
    be = build.file(
        FileKind.UNFALL,
        [{UNFALL_KEY_COLUMN: build.uid("bb", 1)}, {UNFALL_KEY_COLUMN: key}],
        name="be.txt",
        canton="BE",
    )
    finding = build.only(validate_delivery([ag, be]), FindingCode.DUP_KEY_CROSS_SET)
    assert finding.key == key
    assert finding.detail["files"] == "ag.txt, be.txt"
    assert finding.detail["occurrences"] == "2"


def test_all_three_primary_keys_are_checked(build):
    """`UnfallUid`, `ObjektUid` and `PersonUid` — §4.3 names all three."""
    for kind, column in (
        (FileKind.UNFALL, UNFALL_KEY_COLUMN),
        (FileKind.OBJEKT, OBJEKT_KEY_COLUMN),
        (FileKind.PERSON, PERSON_KEY_COLUMN),
    ):
        key = build.uid("aa", 7)
        parsed = build.file(kind, [{column: key}, {column: key}])
        finding = build.only(validate_delivery([parsed]), FindingCode.DUP_KEY_CROSS_SET)
        assert finding.detail["key_kind"] == column, kind


def test_an_empty_key_is_not_a_duplicate_of_another_empty_key(build):
    """Empty means "no value provided" (§8.6), not "the same value twice"."""
    unfall = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: ""}, {UNFALL_KEY_COLUMN: ""}])
    assert build.of_code(validate_delivery([unfall]), FindingCode.DUP_KEY_CROSS_SET) == []


def test_the_same_uid_in_an_unfall_and_an_objekt_file_is_not_a_duplicate(build):
    """They are different key spaces. `objekt.UnfallUid` is a foreign key and is
    *supposed* to repeat its parent's value."""
    key = build.uid("aa", 1)
    unfall = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: key}], canton="AG")
    objekt = build.file(
        FileKind.OBJEKT, [{OBJEKT_KEY_COLUMN: build.uid("aa", 11), UNFALL_KEY_COLUMN: key}]
    )
    analysis = validate_delivery([unfall, objekt])
    assert build.of_code(analysis, FindingCode.DUP_KEY_CROSS_SET) == []


# --- orphan foreign keys, blocking -----------------------------------------


def test_an_objekt_row_with_no_parent_unfall_row_blocks(build):
    parent = build.uid("aa", 1)
    orphan = build.uid("ff", 9)
    child = build.uid("aa", 11)
    unfall = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: parent}], canton="AG")
    objekt = build.file(FileKind.OBJEKT, [{OBJEKT_KEY_COLUMN: child, UNFALL_KEY_COLUMN: orphan}])
    analysis = validate_delivery([unfall, objekt])
    finding = build.only(analysis, FindingCode.ORPHAN_FK)
    assert finding.severity is Severity.BLOCKING
    assert finding.key == child
    assert finding.detail["parent_value"] == orphan
    assert finding.detail["child_table"] == FileKind.OBJEKT.value
    assert finding in blocking_findings(analysis)


def test_a_person_row_hangs_off_objekt_never_off_unfall(build):
    """mvp-spec.md §4.1: person -> accident is a two-hop join, and a pedestrian
    still has an object row. So the FK checked is `person.ObjektUid`."""
    objekt_key = build.uid("aa", 11)
    objekt = build.file(FileKind.OBJEKT, [{OBJEKT_KEY_COLUMN: objekt_key}])
    person = build.file(
        FileKind.PERSON,
        [
            {PERSON_KEY_COLUMN: build.uid("aa", 21), OBJEKT_KEY_COLUMN: objekt_key},
            {PERSON_KEY_COLUMN: build.uid("aa", 22), OBJEKT_KEY_COLUMN: build.uid("ff", 9)},
        ],
    )
    finding = build.only(validate_delivery([objekt, person]), FindingCode.ORPHAN_FK)
    assert finding.key == build.uid("aa", 22)
    assert finding.detail["parent_key"] == OBJEKT_KEY_COLUMN


def test_an_empty_foreign_key_is_not_an_orphan(build):
    unfall = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: build.uid("aa", 1)}], canton="AG")
    objekt = build.file(
        FileKind.OBJEKT, [{OBJEKT_KEY_COLUMN: build.uid("aa", 11), UNFALL_KEY_COLUMN: ""}]
    )
    assert build.of_code(validate_delivery([unfall, objekt]), FindingCode.ORPHAN_FK) == []


# --- set membership, from the data (SD6) -----------------------------------


def test_a_set_is_named_by_its_unfall_files_canton(build):
    unfall = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: build.uid("aa", 1)}], canton="AG")
    analysis = validate_delivery([unfall])
    assert analysis.files[0].set_key == "AG"


def test_objekt_and_person_join_the_set_their_keys_reach(build):
    """Never from a filename (§12.5): the files below are named to mislead."""
    ag_key, be_key = build.uid("aa", 1), build.uid("bb", 1)
    objekt_key = build.uid("aa", 11)
    ag = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: ag_key}], name="z.txt", canton="AG")
    be = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: be_key}], name="a.txt", canton="BE")
    objekt = build.file(
        FileKind.OBJEKT,
        [{OBJEKT_KEY_COLUMN: objekt_key, UNFALL_KEY_COLUMN: be_key}],
        name="objekt_AG.txt",
    )
    person = build.file(
        FileKind.PERSON,
        [{PERSON_KEY_COLUMN: build.uid("aa", 21), OBJEKT_KEY_COLUMN: objekt_key}],
        name="person_AG.txt",
    )
    analysis = validate_delivery([ag, be, objekt, person])
    by_name = {f.filename: f.set_key for f in analysis.files}
    assert by_name["objekt_AG.txt"] == "BE"
    assert by_name["person_AG.txt"] == "BE"


def test_an_objekt_file_reaching_no_unfall_file_is_unresolved_and_blocks(build):
    objekt = build.file(
        FileKind.OBJEKT,
        [{OBJEKT_KEY_COLUMN: build.uid("aa", 11), UNFALL_KEY_COLUMN: build.uid("ff", 9)}],
        name="lonely.txt",
    )
    analysis = validate_delivery([objekt])
    finding = build.only(analysis, FindingCode.SET_UNRESOLVED)
    assert finding.severity is Severity.BLOCKING
    assert finding.detail["filename"] == "lonely.txt"


# --- count mismatches, reported --------------------------------------------


def test_anzobjfeld_against_the_real_child_count(build):
    parent = build.uid("aa", 1)
    unfall = build.file(
        FileKind.UNFALL,
        [{UNFALL_KEY_COLUMN: parent, UNFALL_OBJ_COUNT_COLUMN: "3", UNFALL_PERS_COUNT_COLUMN: "0"}],
        canton="AG",
    )
    objekt = build.file(
        FileKind.OBJEKT,
        [
            {OBJEKT_KEY_COLUMN: build.uid("aa", 11), UNFALL_KEY_COLUMN: parent},
            {OBJEKT_KEY_COLUMN: build.uid("aa", 12), UNFALL_KEY_COLUMN: parent},
        ],
    )
    finding = build.only(validate_delivery([unfall, objekt]), FindingCode.COUNT_MISMATCH_OBJ)
    assert finding.severity is Severity.REPORTED
    assert finding.key == parent
    assert (finding.detail["declared"], finding.detail["actual"]) == ("3", "2")


def test_person_totals_are_counted_through_objekt_not_directly(build):
    """`BeteiligtePersTotalFeld` is a count of `person` rows reached *via*
    `objekt` — the two-hop join, again."""
    parent = build.uid("aa", 1)
    objekt_key = build.uid("aa", 11)
    unfall = build.file(
        FileKind.UNFALL,
        [{UNFALL_KEY_COLUMN: parent, UNFALL_OBJ_COUNT_COLUMN: "1", UNFALL_PERS_COUNT_COLUMN: "5"}],
        canton="AG",
    )
    objekt = build.file(
        FileKind.OBJEKT, [{OBJEKT_KEY_COLUMN: objekt_key, UNFALL_KEY_COLUMN: parent}]
    )
    person = build.file(
        FileKind.PERSON,
        [
            {PERSON_KEY_COLUMN: build.uid("aa", 21), OBJEKT_KEY_COLUMN: objekt_key},
            {PERSON_KEY_COLUMN: build.uid("aa", 22), OBJEKT_KEY_COLUMN: objekt_key},
        ],
    )
    analysis = validate_delivery([unfall, objekt, person])
    finding = build.only(analysis, FindingCode.COUNT_MISMATCH_PERS)
    assert (finding.detail["declared"], finding.detail["actual"]) == ("5", "2")
    assert blocking_findings(analysis) == ()


def test_a_matching_count_reports_nothing(build):
    parent = build.uid("aa", 1)
    unfall = build.file(
        FileKind.UNFALL,
        [{UNFALL_KEY_COLUMN: parent, UNFALL_OBJ_COUNT_COLUMN: "1", UNFALL_PERS_COUNT_COLUMN: "0"}],
        canton="AG",
    )
    objekt = build.file(
        FileKind.OBJEKT, [{OBJEKT_KEY_COLUMN: build.uid("aa", 11), UNFALL_KEY_COLUMN: parent}]
    )
    analysis = validate_delivery([unfall, objekt])
    assert build.of_code(analysis, FindingCode.COUNT_MISMATCH_OBJ) == []
    assert build.of_code(analysis, FindingCode.COUNT_MISMATCH_PERS) == []


def test_a_non_numeric_declared_count_is_not_reported_as_a_mismatch(build):
    """An unparseable value in an integer column is a census concern. Reporting
    it here too would name the same cell twice, under a code that does not
    mean it."""
    unfall = build.file(
        FileKind.UNFALL,
        [
            {
                UNFALL_KEY_COLUMN: build.uid("aa", 1),
                UNFALL_OBJ_COUNT_COLUMN: "",
                UNFALL_PERS_COUNT_COLUMN: "n/a",
            }
        ],
        canton="AG",
    )
    analysis = validate_delivery([unfall])
    assert build.of_code(analysis, FindingCode.COUNT_MISMATCH_OBJ) == []
    assert build.of_code(analysis, FindingCode.COUNT_MISMATCH_PERS) == []


# --- the text join, reported -----------------------------------------------


def test_a_narrative_with_no_accident_and_an_accident_with_no_narrative(build):
    present, textless, narrative_only = (
        build.uid("aa", 1),
        build.uid("aa", 2),
        build.uid("ff", 9),
    )
    unfall = build.file(
        FileKind.UNFALL,
        [{UNFALL_KEY_COLUMN: present}, {UNFALL_KEY_COLUMN: textless}],
        canton="AG",
    )
    text = build.file(
        FileKind.TEXT,
        [
            {TEXT_KEY_COLUMN: present, TEXT_NARRATIVE_COLUMN: "ok"},
            {TEXT_KEY_COLUMN: narrative_only, TEXT_NARRATIVE_COLUMN: "orphan"},
        ],
        name="text.csv",
    )
    analysis = validate_delivery([unfall, text])

    assert build.only(analysis, FindingCode.TEXT_KEY_UNMATCHED).key == narrative_only
    assert build.only(analysis, FindingCode.UNFALL_WITHOUT_TEXT).key == textless
    assert blocking_findings(analysis) == ()


def test_no_text_file_means_no_text_findings_at_all(build):
    """Otherwise every `unfall` row in a structured-only selection would be
    reported as textless, which is noise, not information."""
    unfall = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: build.uid("aa", 1)}], canton="AG")
    analysis = validate_delivery([unfall])
    assert build.of_code(analysis, FindingCode.UNFALL_WITHOUT_TEXT) == []
    assert build.of_code(analysis, FindingCode.TEXT_KEY_UNMATCHED) == []


# --- selection --------------------------------------------------------------


def test_a_deselected_file_is_still_listed_but_takes_part_in_no_check(build):
    """Deselecting the file that carries a duplicate really does unblock the
    freeze, and the file stays in the import view (sw-design.md §8)."""
    key = build.uid("aa", 1)
    ag = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: key}], name="ag.txt", canton="AG")
    be = build.file(
        FileKind.UNFALL, [{UNFALL_KEY_COLUMN: key}], name="be.txt", canton="BE", selected=False
    )
    analysis = validate_delivery([ag, be])
    assert build.of_code(analysis, FindingCode.DUP_KEY_CROSS_SET) == []
    assert [f.filename for f in analysis.files] == ["ag.txt", "be.txt"]


def test_an_empty_delivery_validates_to_nothing(build):
    analysis = validate_delivery([])
    assert analysis.files == ()
    assert analysis.findings == ()
    assert blocking_findings(analysis) == ()


# --- what "blocking" means --------------------------------------------------


def test_blocking_findings_spans_per_file_and_cross_file_findings(build):
    """`DeliveryAnalysis.blocking` walks both: a header mismatch is per-file,
    a duplicate key is delivery-wide, and either must stop the freeze."""
    key = build.uid("aa", 1)
    ag = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: key}], name="ag.txt", canton="AG")
    be = build.file(FileKind.UNFALL, [{UNFALL_KEY_COLUMN: key}], name="be.txt", canton="BE")
    analysis = validate_delivery([ag, be])
    assert [f.code for f in blocking_findings(analysis)] == [FindingCode.DUP_KEY_CROSS_SET]
    assert all(f.severity is Severity.BLOCKING for f in blocking_findings(analysis))

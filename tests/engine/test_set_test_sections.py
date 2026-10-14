"""The marked-section script (scripts/set_test_sections.py) moves whole
sections and nothing else.

The convention is what lets a wave's branches meet in one test file without a
conflict, and the script is run at the two moments a mistake is most expensive:
on `main` before a fan-out, and on a link in the middle of an integration, with
branches still in flight against the file being rewritten. So what is held here
is what a branch in flight depends on — marker pairs stay where they were, an
existing line is never touched — and that the script reads the files the
convention has already produced.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import set_test_sections as sections_script  # noqa: E402
from set_test_sections import SectionError, marker  # noqa: E402


def _fill(path: Path, group: str, body: str) -> None:
    """Write *body* into *group*'s section, as a group's branch would."""
    text = path.read_bytes().decode("utf-8")
    placeholder = sections_script.placeholder(group)
    assert placeholder in text
    # Bytes, not text mode: a text-mode write turns every newline into the
    # platform's line ending, and the line-ending test below would then be
    # about this helper rather than about the script.
    path.write_bytes(text.replace(placeholder, placeholder + "\n" + body).encode("utf-8"))


def _opened(tmp_path, groups=("W1G1", "W1G2", "W1G3")) -> Path:
    sections_script.open_files(
        "TST", list(groups), types=("creatures",), directory=tmp_path, name="Test Set",
    )
    return tmp_path / "test_tst_creatures.py"


def test_the_script_reads_every_marked_file_the_convention_has_produced():
    """Apocalypse's and Odyssey's files are the convention; a script that
    could not parse one of them would be describing a different one."""
    marked = pairs = 0
    for path in sorted((REPO / "tests" / "sets").glob("test_*.py")):
        lines, _ = sections_script._split(path.read_bytes())
        if not any(line.startswith("# ==== ") for line in lines):
            continue
        marked += 1
        for line in lines:
            if line.startswith("# ==== "):
                assert sections_script.MARKER.match(line), (path.name, line)
        pairs += len(sections_script.sections(lines, path.name))
    assert marked >= 20, marked
    assert pairs >= 150, pairs


def test_a_marker_is_the_width_the_existing_files_use():
    assert marker("W1G1") == "# ==== W1G1 " + "=" * 58
    assert len(marker("W1G1")) == len(marker("W12G10", end=True)) == 70


def test_open_writes_one_empty_section_per_group(tmp_path):
    path = _opened(tmp_path)
    lines, eol = sections_script._split(path.read_bytes())
    assert eol == "\n"
    assert lines[0] == '"""Test Set creatures.'
    assert list(sections_script.sections(lines)) == ["W1G1", "W1G2", "W1G3"]
    assert 'set_pool("TST")' in path.read_text(encoding="utf-8")
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_opening_again_for_wave_two_appends_and_touches_nothing_else(tmp_path):
    path = _opened(tmp_path)
    _fill(path, "W1G2", "def test_w1g2_something():\n    assert True")
    before = path.read_bytes()

    added = sections_script.open_files(
        "TST", ["W1G1", "W2G1", "W2G2"], types=("creatures",), directory=tmp_path, name="Test Set",
    )
    assert added[path] == ["W2G1", "W2G2"]
    after = path.read_bytes()
    assert after.startswith(before.rstrip(b"\n"))
    lines, _ = sections_script._split(after)
    assert list(sections_script.sections(lines)) == ["W1G1", "W1G2", "W1G3", "W2G1", "W2G2"]

    again = sections_script.open_files(
        "TST", ["W2G1"], types=("creatures",), directory=tmp_path, name="Test Set",
    )
    assert again[path] == [] and path.read_bytes() == after


def test_a_move_takes_the_section_whole_and_leaves_its_marker_pair(tmp_path):
    path = _opened(tmp_path)
    body = "import pytest as _w1g2_pytest\n\n\ndef test_w1g2_something():\n    assert True"
    _fill(path, "W1G2", body)
    _fill(path, "W1G3", "def test_w1g3_stays():\n    assert True")
    before, _ = sections_script._split(path.read_bytes())

    destination = sections_script.move_sections(path, "later_groups", ["W1G2"])

    assert destination.name == "test_tst_creatures_later_groups.py"
    moved = destination.read_text(encoding="utf-8")
    assert body in moved and "Continued from `test_tst_creatures.py`" in moved
    assert 'set_pool("TST")' in moved
    kept = path.read_text(encoding="utf-8")
    assert "test_w1g2_something" not in kept and "test_w1g3_stays" in kept
    assert "(moved whole to test_tst_creatures_later_groups.py" in kept
    lines, _ = sections_script._split(path.read_bytes())
    # Every marker is where a branch in flight left it: same lines, same order.
    assert [l for l in lines if l.startswith("# ==== ")] == [l for l in before if l.startswith("# ==== ")]
    for text, name in ((kept, path), (moved, destination)):
        compile(text, str(name), "exec")


def test_a_second_move_appends_to_the_same_sibling(tmp_path):
    path = _opened(tmp_path)
    _fill(path, "W1G1", "def test_w1g1_one():\n    assert True")
    _fill(path, "W1G3", "def test_w1g3_three():\n    assert True")
    sections_script.move_sections(path, "later_groups", ["W1G3"])
    destination = sections_script.move_sections(path, "later_groups", ["W1G1"])
    lines, _ = sections_script._split(destination.read_bytes())
    assert list(sections_script.sections(lines)) == ["W1G3", "W1G1"]
    assert destination.read_text(encoding="utf-8").count('"""') == 2


def test_line_endings_are_kept(tmp_path):
    path = _opened(tmp_path)
    _fill(path, "W1G1", "def test_w1g1_one():\n    assert True")
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    destination = sections_script.move_sections(path, "later_groups", ["W1G1"])
    for written in (path, destination):
        raw = written.read_bytes()
        assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


@pytest.mark.parametrize("groups, why", [
    (["W9G9"], "no W9G9 section"),
    (["W1G2"], "nothing to move"),
    (["w1g1"], "not a group name"),
])
def test_a_move_refuses_what_is_not_there(tmp_path, groups, why):
    path = _opened(tmp_path)
    _fill(path, "W1G1", "def test_w1g1_one():\n    assert True")
    before = path.read_bytes()
    with pytest.raises(SectionError, match=why):
        sections_script.move_sections(path, "later_groups", groups)
    assert path.read_bytes() == before
    assert not (tmp_path / "test_tst_creatures_later_groups.py").exists()


def test_a_section_moved_once_cannot_be_moved_onto_itself(tmp_path):
    path = _opened(tmp_path)
    _fill(path, "W1G1", "def test_w1g1_one():\n    assert True")
    sections_script.move_sections(path, "later_groups", ["W1G1"])
    _fill(path, "W1G1", "def test_w1g1_late():\n    assert True")
    with pytest.raises(SectionError, match="already has a W1G1 section"):
        sections_script.move_sections(path, "later_groups", ["W1G1"])


def test_a_damaged_marker_pair_is_named_rather_than_moved(tmp_path):
    path = _opened(tmp_path)
    text = path.read_bytes().decode("utf-8").replace(marker("W1G2", end=True) + "\n", "")
    path.write_bytes(text.encode("utf-8"))
    with pytest.raises(SectionError, match="opens inside W1G2"):
        sections_script.move_sections(path, "later_groups", ["W1G1"])


def test_the_report_counts_against_the_cap_the_guard_enforces(tmp_path):
    path = _opened(tmp_path)
    _fill(path, "W1G2", "\n".join(f"# line {n}" for n in range(40)))
    rows = sections_script.report("TST", directory=tmp_path)
    assert [row[0] for row in rows] == [path]
    assert rows[0][2]["W1G2"] == 42 and rows[0][2]["W1G1"] == 2
    assert rows[0][1] == len(path.read_text(encoding="utf-8").splitlines())
    assert sections_script.per_set_cap() > 1000
    with pytest.raises(SectionError):
        sections_script.report("ZZZ", directory=tmp_path)


def test_an_unknown_set_code_names_the_codes_that_exist():
    with pytest.raises(SectionError, match="ODY"):
        sections_script.set_name("ZZZ")
    assert sections_script.set_name("ody") == "Odyssey"

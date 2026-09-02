from engine import build_support_report


def test_support_report_totals_match_card_count(all_cards):
    report = build_support_report(all_cards)
    assert report.total_cards == len(all_cards)
    assert report.supported_cards + report.unsupported_cards == report.total_cards


def test_support_report_includes_type_counts(all_cards):
    report = build_support_report(all_cards)
    assert "creature" in report.by_type
    assert "land" in report.by_type


def test_refusals_report_names_exactly_the_unsupported_cards():
    """`--refusals` is the census a backlog round is planned from, so its
    contract is exact coverage: one entry per unsupported card, none for a
    supported one. The plain census quotes only the first refused line per
    card (SET_PLAYBOOK.md Phase 1); this report exists to quote them all, and
    a card it skipped would be a card no round ever schedules."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from support_report import refusals_report

    from engine.card_loader import load_cards, manifest_measured_codes, manifest_set_path
    from engine.oracle import compile_card_oracle

    for code in manifest_measured_codes():
        cards = load_cards(manifest_set_path(code, include_measured=True))
        unsupported = {c.name for c in cards if not compile_card_oracle(c).supported}
        findings = refusals_report(cards)
        assert {name for name, _, _, _ in findings} == unsupported
        for _, _, headline, lines in findings:
            assert headline
            for status, line, detail in lines:
                assert status in {"refused", "unlowered", "clean"}
                # A refusal always names its site; "clean" never does.
                assert (detail != "") == (status != "clean")
                assert line


def test_refusals_report_is_empty_over_the_shipped_pool(catalog):
    """The shipped pool is held at 100% supported by the front-end-safety
    guard, so the refusals census over it must be empty — a finding here is
    either a supported card misreported or the guard about to fail."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from support_report import refusals_report

    assert refusals_report(catalog) == []


def test_refusal_rollup_counts_cards_per_site():
    """The rollup's third column: how many CARDS share a refusal site.

    Lines-per-distinct-sentence read 1.00 for four sets running ("no
    production here buys two cards") while Homelands held ten cards printing
    one untap-denial clause -- the leverage number a backlog round ranks by is
    cards per site, and this pins that it is counted and carried by name.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from support_report import refusal_rollup, refusals_json

    findings = [
        ("Card A", "creature", "reason A", [
            ("refused", "Doesn't  untap during X.", "site-1"),
            ("clean", "Flying", ""),
        ]),
        ("Card B", "creature", "reason B", [
            ("refused", "doesn't untap during X.", "site-1"),
        ]),
        ("Card C", "sorcery", "front-end headline", [
            ("clean", "Draw a card.", ""),
        ]),
    ]
    sites, front_end_only = refusal_rollup(findings)
    assert sites["site-1"]["lines"] == 2
    # One distinct sentence: whitespace and case fold together.
    assert len(sites["site-1"]["texts"]) == 1
    assert sites["site-1"]["cards"] == {"Card A", "Card B"}
    # Every line grammar-clean -> the refusal is the headline reason.
    assert front_end_only == [("Card C", "front-end headline")]

    payload = refusals_json(findings)
    assert payload["by_site"][0]["cards"] == ["Card A", "Card B"]
    assert payload["front_end_only"] == [
        {"name": "Card C", "headline": "front-end headline"}
    ]

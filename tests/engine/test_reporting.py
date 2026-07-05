from engine import build_support_report


def test_support_report_totals_match_card_count(all_cards):
    report = build_support_report(all_cards)
    assert report.total_cards == len(all_cards)
    assert report.supported_cards + report.unsupported_cards == report.total_cards


def test_support_report_includes_type_counts(all_cards):
    report = build_support_report(all_cards)
    assert "creature" in report.by_type
    assert "land" in report.by_type

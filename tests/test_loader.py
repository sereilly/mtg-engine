from engine import load_cards


def test_loader_reads_cards(lea_path):
    cards = load_cards(lea_path)
    assert len(cards) > 250
    assert any(card.name == "Black Lotus" for card in cards)


def test_loader_has_required_core_fields(all_cards):
    sample = all_cards[0]
    assert sample.name
    assert sample.type_line
    assert isinstance(sample.cmc, float)

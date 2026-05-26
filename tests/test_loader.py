from engine import load_cards




def test_loader_has_required_core_fields(all_cards):
    sample = all_cards[0]
    assert sample.name
    assert sample.type_line
    assert isinstance(sample.cmc, float)

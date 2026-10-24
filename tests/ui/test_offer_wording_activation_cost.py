"""An activated ability's cost is not one of an offer's two answers.

``web/prompt_values.offer_wording`` splits "X unless Y" into what declining
does and what accepting costs, because a bare Yes / No over "X unless Y" gets
the polarity backwards. It already dropped a *trigger's* opening ("At the
beginning of your upkeep, ") from the decline half; an activated ability's cost
("Discard a card at random: ", Barbarian Bully; "{T}: ", Dwarven Driller) was
left in, so the button for declining read "{T}: Destroy target land" — the
price of activating, which was paid before anybody was asked.

Pool-wide, because the shape is a printed one: on the tree before the fix this
named twenty cards (eighteen shipped, among them Mundungu, Vodalian Mage, both
Spiketails and Dwarven Driller), and the floor below keeps the scan honest
about how much it read.
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from web.prompt_values import offer_wording


class _Card:
    def __init__(self, text: str):
        self.oracle_text = text


class _Context:
    def __init__(self, text: str):
        self.card = _Card(text)
        self.ability_text = ""


def test_no_offer_declines_into_an_activation_cost():
    seen: set[str] = set()
    worded = 0
    leaked = []
    for path in manifest_set_paths(include_measured=True):
        # Each face of a split card in its place: the offer is printed on a
        # half, and the whole card's text box is empty (CR 709.3a).
        for card in compilation_units(load_cards(path)):
            if card.name in seen:
                continue
            seen.add(card.name)
            wording = offer_wording({"_context": _Context(card.oracle_text or "")})
            if "decline_text" not in wording:
                continue
            worded += 1
            if ":" in wording["decline_text"]:
                leaked.append((card.name, wording["decline_text"]))
    assert worded >= 200, f"only {worded} offers were read"
    assert leaked == []


def test_barbarian_bullys_two_answers():
    wording = offer_wording({"_context": _Context(
        "Discard a card at random: This creature gets +2/+2 until end of turn "
        "unless a player has this creature deal 4 damage to them. Activate only "
        "once each turn."
    )})
    assert wording["decline_text"] == "This creature gets +2/+2 until end of turn"
    assert wording["accept_text"] == "a player has this creature deal 4 damage to them"

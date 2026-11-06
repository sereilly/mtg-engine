"""The exile register (``engine/exiled_records.py``) is not a list of cards
whose abilities work from exile — found while giving Dimensional Breach its
pile (Scourge wave 2, W2G1).

**A battlefield upkeep trigger fired from exile.** The upkeep step scans the
register for "at the beginning of your upkeep" triggers of exiled cards, which
is All Hallow's Eve's ("…if this card is exiled with a scream counter on it").
It announced *every* ``upkeep_self`` trigger of every registered card, and the
register also holds the cards a face-down exile hides (Three Wishes, Suppress,
Memory Jar). So a Juzám Djinn among the top three cards of a Three Wishes
library dealt its owner 1 damage from exile at the next upkeep. CR 113.6: a
permanent card's abilities function on the battlefield unless they say
otherwise; CR 113.6k: a trigger condition that can't trigger from the
battlefield ("if this card is exiled") functions where it can. The scan now
asks ``exiled_records.functions_in_exile``.

**A held record came back to life.** CR 400.7 makes a card that leaves exile
and returns a new object, and the departure seam retires its record — but
``is_live`` asked only whether the card was in the pile, so a holder that kept
the record object (a trigger's context, a delayed ability's ``captured``) found
it live again the moment the same ``CardDefinition`` — any copy — was exiled by
something else. ``is_live`` now also asks the register.

Both validated backwards on the tree before the fix: the Djinn deals 1, and the
retired record reads live.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.exiled_records import (EXILE_ZONE_CONDITIONS, functions_in_exile,
                                   is_live, record_exiled_card)
from engine.faces import compilation_units
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _cards(code: str) -> dict:
    return {card.name: card for card in load_cards(manifest_set_path(code))}


def test_a_creature_hidden_by_three_wishes_deals_no_upkeep_damage_from_exile():
    """Juzám Djinn's "At the beginning of your upkeep, this creature deals 1
    damage to you" is a battlefield ability: face down in a Three Wishes pile
    at its owner's next upkeep it does nothing — the pile goes to the graveyard
    (the card's own delayed sentence) and its owner is still at 20."""
    lea, arn, vis = _cards("LEA"), _cards("ARN"), _cards("VIS")
    game = Game(players=[
        PlayerState(
            name="P1", hand=[vis["Three Wishes"]],
            library=[arn["Juzám Djinn"], lea["Island"], lea["Island"]]
            + [lea["Island"]] * 10,
        ),
        PlayerState(name="P2", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    assert game.cast_from_hand(0, "Three Wishes").supported
    resolve_stack(game)
    assert "Juzám Djinn" in [card.name for card in game.players[0].exile]
    assert any(record.card.name == "Juzám Djinn" for record in game.exiled_records)

    game.start_next_turn()   # P2's turn
    resolve_stack(game)
    game.start_next_turn()   # P1's next upkeep
    resolve_stack(game)

    assert game.players[0].life == 20
    assert not any("Juzám Djinn dealt 1 damage" in line for line in game.log)
    assert "Juzám Djinn" in [card.name for card in game.players[0].graveyard]


def test_every_exile_scanned_upkeep_trigger_in_the_pool_says_it_works_from_exile(
    set_codes,
):
    """The census behind the gate, both ways. Every ``upkeep_self`` trigger
    whose intervening "if" names exile is admitted (All Hallow's Eve among
    them — a floor, so a census over nothing cannot pass), and every one the
    gate admits names exile in its printed line, so the gate cannot be
    admitting a battlefield ability under some other spelling."""
    from engine.card_loader import manifest_set_paths

    admitted: dict[str, str] = {}
    printed_exiled: set[str] = set()
    seen = set()
    for path in manifest_set_paths(include_measured=True):
        for unit in compilation_units(load_cards(path)):
            if unit.name in seen:
                continue
            seen.add(unit.name)
            for trig in compile_card_oracle(unit).triggered_abilities:
                if trig.instruction is None or trig.condition.kind != "upkeep_self":
                    continue
                line = (trig.source_line or "").lower()
                if "if this card is exiled" in line or "if it's exiled" in line:
                    printed_exiled.add(unit.name)
                if functions_in_exile(trig):
                    admitted[unit.name] = line
    assert "All Hallow's Eve" in admitted
    assert printed_exiled <= set(admitted)
    for name, line in admitted.items():
        assert "exiled" in line or "in exile" in line, (name, line)
    assert EXILE_ZONE_CONDITIONS


def test_a_retired_record_stays_retired_when_its_card_is_exiled_again():
    """CR 400.7 / 406.7: the departure seam retires the record, and the same
    card object exiled again afterwards is a new object the old record does not
    speak for — read through a held reference, as a delayed ability holds it."""
    lea = _cards("LEA")
    bears = lea["Grizzly Bears"]
    game = Game(players=[
        PlayerState(name="P1", library=[lea["Island"]] * 5),
        PlayerState(name="P2", library=[lea["Island"]] * 5),
    ])
    game.players[0].exile.append(bears)
    held = record_exiled_card(game, bears, 0)
    assert is_live(game, held)

    assert game.take_card_from_exile(game.players[0], bears)
    game.players[0].exile.append(bears)

    assert not is_live(game, held)

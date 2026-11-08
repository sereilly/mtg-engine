"""A permanent whose own entry trigger sacrifices it unless a price is paid is
rehearsed before the AI casts it.

"When this creature enters, sacrifice it unless you sacrifice three Forests."
(Primeval Force, 8ED.) A permanent is scored by what it is, so before 8ED
nothing asked what its arrival does: driving the set's AI games found an 8/8
Force cast with two Forests (City of Brass the third green source) and
sacrificed at once, and a probe of the sentence's fourteen shipped siblings
found Phyrexian Dreadnought cast beside no creature and Hecatomb beside one —
each a card gone as it arrives. One of the twelve `sim_fingerprint` games
(MIR seed 7) made the Dreadnought play on turn two.

`ai_valuation.entry_may_remove_itself` names the shape off the compiled
program, and `ai_casts` rehearses such a cast as it rehearses a body the board
sizes: the rehearsal answers the offer on its default, and a permanent still
there at the end of the turn is the one proposed.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine import ai_casts
from engine.ai_policy import choose_cast_action
from engine.ai_valuation import entry_may_remove_itself
from engine.faces import compilation_units
from engine.models import Permanent


def _board(catalog_by_name, card: str, lands, creatures=()) -> Game:
    """Seat 0's precombat main phase with *card* and a Forest in hand."""
    me = PlayerState(
        name="Me", hand=[catalog_by_name[card], catalog_by_name["Forest"]],
        library=[catalog_by_name["Forest"]] * 10,
    )
    opp = PlayerState(name="Opp", library=[catalog_by_name["Island"]] * 10)
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for name in (*lands, *creatures):
        perm = Permanent(card=catalog_by_name[name])
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game


#: Boards on which the price cannot be paid, so the cast is a card gone.
UNPAYABLE = [
    ("Primeval Force", ["Forest", "Forest", "City of Brass", "Plains", "Plains"], []),
    ("Phyrexian Dreadnought", ["Island", "Island"], []),
    ("Hecatomb", ["Swamp"] * 4, ["Grizzly Bears"]),
]


@pytest.mark.parametrize(
    ("card", "lands", "creatures"), UNPAYABLE, ids=[row[0] for row in UNPAYABLE],
)
def test_a_permanent_its_own_entry_would_sacrifice_is_not_cast(
    catalog_by_name, card, lands, creatures,
):
    game = _board(catalog_by_name, card, lands, creatures)

    chosen = choose_cast_action(game, 0)

    assert chosen is None or chosen.card_name != card


@pytest.mark.parametrize(
    ("card", "lands", "creatures"), UNPAYABLE, ids=[row[0] for row in UNPAYABLE],
)
def test_backwards_without_the_rehearsal_each_was_cast(
    catalog_by_name, monkeypatch, card, lands, creatures,
):
    """The test above, run with the shape unnamed: each card is proposed again,
    so the test is about the rehearsal and not about a board that happens to
    make the card unaffordable."""
    monkeypatch.setattr(ai_casts, "entry_may_remove_itself", lambda card: False)
    game = _board(catalog_by_name, card, lands, creatures)

    chosen = choose_cast_action(game, 0)

    assert chosen is not None and chosen.card_name == card


@pytest.mark.parametrize(
    ("card", "lands"),
    [
        ("Primeval Force", ["Forest"] * 3 + ["Plains"] * 2),
        ("Balduvian Horde", ["Mountain"] * 4),
    ],
    ids=["three Forests", "a card to discard"],
)
def test_a_permanent_whose_price_can_be_paid_is_still_cast(catalog_by_name, card, lands):
    """The rehearsal pays on its default and the permanent stays, so the card
    is still proposed: the gate refuses a loss, not the shape."""
    game = _board(catalog_by_name, card, lands)

    chosen = choose_cast_action(game, 0)

    assert chosen is not None and chosen.card_name == card


def test_the_shape_is_read_off_the_program_for_every_printing_of_it(catalog_by_name):
    """Every shipped permanent printing "When this … enters, sacrifice it
    unless …" answers yes — fifteen with Primeval Force, a floor so the
    census cannot pass over nothing — and "whenever *another* creature enters,
    sacrifice this" (Mogg Bombers, Monkey Cage) is a different event and
    answers no, as does a plain entry trigger."""
    # Over the text that compiles (`faces.compilation_units`): a question about
    # printed sentences, so a split card is read by its faces, never whole.
    unless = {
        unit.name: unit
        for unit in compilation_units(catalog_by_name.values())
        if unit.primary_type != "land"
        and "enters, sacrifice it unless" in (unit.oracle_text or "").replace(
            "sacrifice this enchantment unless", "sacrifice it unless"
        )
    }
    assert len(unless) >= 15, sorted(unless)
    assert "Primeval Force" in unless and "Hecatomb" in unless
    assert sorted(name for name, unit in unless.items() if not entry_may_remove_itself(unit)) == []
    for name in ("Mogg Bombers", "Monkey Cage", "Vampiric Spirit", "Grizzly Bears"):
        assert not entry_may_remove_itself(catalog_by_name[name]), name

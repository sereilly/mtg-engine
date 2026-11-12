"""The tap seam's two derivations are held on what they read.

``land_mana_taps.is_tap_alone_mana_ability`` asks a question of a compiled
mana ability, and ``LandManaTapsMixin._land_mana_abilities`` walks the program
of a land's **effective** card for its tap-alone ability — and both were
derived again on every call: 3.2 million walks in one payment census, a third
of its time, each answering what it had answered the call before. The two
answers are held now on the object each is a function of
(``oracle.held_on_compiled``): the ability, and the effective card's program,
under the generation that program was compiled in. Three ways that could go
wrong, held here:

* **the printed card's answer read for a land that is no longer that card.**
  A Karplusan Forest's own program has a free "{T}: Add {C}"; under Blood Moon
  the Forest is a Mountain with no text (CR 305.7), whose program has none,
  and when the Moon leaves it is the Forest again. The answer is held on each
  program, so each reading is the card the land is at the time;
* **a held answer that is not the one derived now** — over every land and
  every activated ability in the pool, and as the same object: a caller
  compares the free instruction by identity (``board_payment._seam_abilities``
  asks ``ability.instruction is free``);
* **an answer that outlives the tables it was derived from.** Clearing the
  compilation caches is what a test that patches the compiler's tables does,
  and it is what re-derives a held answer.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine import mana_abilities
from engine.ai_valuation import mana_ability_symbols
from engine.mixins.land_mana_taps import (
    LandManaTapsMixin, _land_mana_abilities_of, _tap_alone_mana_ability,
    is_tap_alone_mana_ability,
)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.oracle_types import clear_compilation_caches
from tests.helpers import _nosick


def _seat(*permanents):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(permanents)),
        PlayerState(name="P2"),
    ])
    game.interactive_seats = set()
    game._settle()
    return game


def _pool(game):
    return {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}


def test_a_land_is_answered_by_the_card_it_is_now(set_pool):
    """Read before Blood Moon, under it, and after it leaves: three cards,
    three programs, three answers — and the tap under the Moon makes {R}
    with no damage, the Mountain's mana and not the Forest's."""
    forest = _nosick(Permanent(card=set_pool("ICE")["Karplusan Forest"]))
    game = _seat(forest)

    printed = game._land_mana_abilities(forest)
    assert printed[0] is not None and mana_ability_symbols(printed[0]) == {"C"}, printed
    assert game._land_mana_abilities(forest) == printed

    moon = Permanent(card=set_pool("DRK")["Blood Moon"])
    game._put_permanent_onto_battlefield(1, moon, None)
    game._settle()
    assert forest.effective_card is not forest.card
    assert game._land_mana_abilities(forest) == (None, False)
    game.tap_land_for_mana(0, "Karplusan Forest", "G", permanent_id=forest.permanent_id)
    assert _pool(game) == {"R": 1}, game.log
    assert game.players[0].life == 20

    game.sacrifice_permanent(moon)
    game._settle()
    forest.tapped = False
    game.players[0].mana_pool["R"] = 0
    assert game._land_mana_abilities(forest) == printed
    game.tap_land_for_mana(0, "Karplusan Forest", "C", permanent_id=forest.permanent_id)
    assert _pool(game) == {"C": 1}, game.log


def test_every_held_answer_is_the_one_derived_now(catalog):
    """Over every land's program and every activated ability in the pool,
    each read twice (the second is the held answer): equal to a fresh
    derivation, and the free instruction the very object the program holds."""
    lands = abilities = 0
    for card in catalog:
        program = compile_card_oracle(card)
        for ability in program.activated_abilities:
            abilities += 1
            fresh = _tap_alone_mana_ability(ability)
            assert is_tap_alone_mana_ability(ability) is fresh, (card.name, ability.source_line)
            assert is_tap_alone_mana_ability(ability) is fresh, (card.name, ability.source_line)
        if card.primary_type != "land":
            continue
        lands += 1
        land = Permanent(card=card)
        fresh = _land_mana_abilities_of(program) if program.supported else (None, True)
        for _ in range(2):
            held = LandManaTapsMixin._land_mana_abilities(land)
            assert held == fresh and held[0] is fresh[0], card.name
            if held[0] is not None:
                assert any(a.instruction is held[0] for a in program.activated_abilities)
    # 262 lands and 2,819 activated abilities in the shipped pool after Darksteel.
    assert lands >= 250 and abilities >= 2500, (lands, abilities)


def test_clearing_the_compilation_caches_derives_a_held_answer_again(set_pool, monkeypatch):
    """"{T}: Add one mana of any color. During your next untap step, as you
    untap your permanents, return this land to its owner's hand."
    (Undiscovered Paradise.) A mana ability because its zone step is one CR
    605.1a's library criterion has read (``LIBRARY_SAFE_ZONE_KINDS``); with
    that table emptied it is not one, and so not a tap-alone one either —
    once the caches are cleared, which is what re-derives the held answer.
    Before they are, the held answer is the one the table gave when it was
    derived, which is what a held answer is."""
    from tests.passes import rewarm_compile_cache

    program = compile_card_oracle(set_pool("VIS")["Undiscovered Paradise"])
    ability = next(a for a in program.activated_abilities if a.instruction is not None)
    assert is_tap_alone_mana_ability(ability)

    monkeypatch.setattr(mana_abilities, "LIBRARY_SAFE_ZONE_KINDS", frozenset())
    assert not _tap_alone_mana_ability(ability), "the table decides the fresh answer"
    assert is_tap_alone_mana_ability(ability), "held until the caches are cleared"
    clear_compilation_caches()
    try:
        assert not is_tap_alone_mana_ability(ability)
    finally:
        monkeypatch.undo()
        clear_compilation_caches()
        rewarm_compile_cache()
    assert is_tap_alone_mana_ability(ability)

"""Two Scourge statics read from their templates, with invented cards.

Covers:
  614.1a / 616.1e — "If a player would gain life, that player gains no life
           instead" (Sulfuric Vortex) is a replacement effect: beside another
           replacement of the same gain the affected player chooses, so Lich's
           "draw that many cards instead" can still apply — where CR 119.7's
           "can't gain life" stops it (``engine/life_prohibitions.py``).
  119.10 — a gain of 0 is no event, and nothing replaces it.
  500.5 / 106.4 — "Players don't lose unspent mana as steps and phases end"
           (Upwelling) switches the pool's emptying off while it is on the
           battlefield; the first step that ends without it empties the pool.

Invented names, so a table keyed by a card name could not pass; the printed
cards are driven in ``tests/sets/test_scg_enchantments.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent
from engine.replacements.life_gain import gains_no_life_instead_line
from engine.unspent_mana import seats_keeping_unspent_mana, unspent_mana_kept_line


def _enchantment(name: str, text: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Enchantment",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Enchantment"},
    )


def _game(p0=(), p1=(), library=()) -> Game:
    game = Game(players=[
        PlayerState(name="P0", battlefield=[Permanent(card=c) for c in p0],
                    library=list(library)),
        PlayerState(name="P1", battlefield=[Permanent(card=c) for c in p1],
                    library=list(library)),
    ])
    game.enforce_mana_costs = False
    return game


def _lich():
    return next(
        c for c in load_cards(manifest_set_path("2ED")) if c.name == "Lich"
    )


def _forest():
    return next(
        c for c in load_cards(manifest_set_path("2ED")) if c.name == "Forest"
    )


_OPPONENTS_GAIN_NOTHING = _enchantment(
    "Withering Ward", "If an opponent would gain life, that player gains no life instead."
)
_YOU_GAIN_NOTHING = _enchantment(
    "Hollow Vow", "If you would gain life, you gain no life instead."
)
_EVERYONE_GAINS_NOTHING = _enchantment(
    "Ashen Tithe", "If a player would gain life, that player gains no life instead."
)
_CANT_GAIN = _enchantment("Barren Oath", "Players can't gain life.")


@pytest.mark.cr("614.1a")
def test_the_scope_is_the_printed_subject():
    assert gains_no_life_instead_line(_EVERYONE_GAINS_NOTHING.oracle_text) == "each_player"
    assert gains_no_life_instead_line(_OPPONENTS_GAIN_NOTHING.oracle_text) == "opponents"
    assert gains_no_life_instead_line(_YOU_GAIN_NOTHING.oracle_text) == "you"
    # A crossed pronoun is a sentence no card prints, and stays unread.
    assert gains_no_life_instead_line(
        "If you would gain life, that player gains no life instead."
    ) is None
    game = _game(p0=[_OPPONENTS_GAIN_NOTHING])
    me, them = game.players
    game._gain_life(me, 3)
    game._gain_life(them, 3)
    assert (me.life, them.life) == (23, 20)
    assert them.life_gained_this_turn == 0


@pytest.mark.cr("614.1a", "616.1e")
def test_a_replaced_gain_contends_with_lich_where_a_ban_does_not():
    forest = _forest()
    # The replacement: Lich is a contender, and the default the gaining
    # player is taken to choose is its cards.
    game = _game(p0=[_lich(), _EVERYONE_GAINS_NOTHING], library=[forest] * 5)
    game._gain_life(game.players[0], 2)
    assert len(game.players[0].hand) == 2 and game.players[0].life == 20
    # Asked, the player may pick the replacement that gives nothing.
    game = _game(p0=[_lich(), _EVERYONE_GAINS_NOTHING], library=[forest] * 5)
    game.interactive_seats = {0}
    game._gain_life(game.players[0], 2)
    (order,) = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert game.resolve_pending_choice(
        "effect_order", 0, option_index=next(
            i for i, option in enumerate(order.data["options"])
            if option.startswith("Gain no life instead")
        ),
    )
    assert game.players[0].hand == [] and game.players[0].life == 20
    # The ban (CR 119.7): no replacement over the gain does anything.
    game = _game(p0=[_lich(), _CANT_GAIN], library=[forest] * 5)
    game._gain_life(game.players[0], 2)
    assert game.players[0].hand == [] and game.players[0].life == 20


@pytest.mark.cr("119.10")
def test_a_gain_of_nothing_is_not_replaced():
    game = _game(p0=[_EVERYONE_GAINS_NOTHING])
    game._gain_life(game.players[0], 0)
    assert not any("gains no life instead" in line for line in game.log)


_YOU_KEEP_MANA = _enchantment(
    "Brimming Font", "You don't lose unspent mana as steps and phases end."
)


@pytest.mark.cr("500.5", "106.4")
def test_kept_mana_is_the_printed_subjects_and_ends_with_its_source():
    assert unspent_mana_kept_line(
        "Players don't lose unspent mana as steps and phases end."
    ) == "each_player"
    assert unspent_mana_kept_line(_YOU_KEEP_MANA.oracle_text) == "you"
    game = _game(p0=[_YOU_KEEP_MANA])
    me, them = game.players
    assert seats_keeping_unspent_mana(game) == frozenset({0})
    me.mana_pool["U"] = 2
    them.mana_pool["U"] = 2
    game._on_step_or_phase_end("beginning", "upkeep")
    assert (me.mana_pool["U"], them.mana_pool["U"]) == (2, 0)
    font = next(iter(game.controlled_by(0)))
    game.remove_from_battlefield(font)
    assert me.mana_pool["U"] == 2
    game._on_step_or_phase_end("beginning", "draw")
    assert me.mana_pool["U"] == 0

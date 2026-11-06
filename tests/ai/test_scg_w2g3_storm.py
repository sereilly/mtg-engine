"""Storm, as an AI seat plays it: cast after the turn's other spells, and each
copy aimed where it does most (SCG W2G3).

W1G1 measured both halves in seeded games — 31 storm casts and 6 copies in
four games: the main-phase chooser cast a storm spell as soon as it was the
best card in hand, so its count was usually 0; and every copy kept its
original's target, because the copy-target offer's default declines (CR
707.10c's "may"), so Scattershot's copies hit one creature and Reaping the
Graves' copies were countered by the rules once the first had returned the
card (CR 608.2b).

* ``ai_policy._storm_spell_last``: a storm spell
  (``ai_valuation.copies_for_the_spells_before_it``) gives way to another
  proposed cast the seat can make first and still pay for the storm spell
  after.
* ``ai_prompts.choose_copy_target`` (the ``copy_spell_target`` default) and
  ``choose_copy_retarget`` (a copy aimed at a graveyard card or a spell):
  each offered target rehearsed against keeping the original's.

Validated backwards on ``843cf32a``: the census casts seven of the nine storm
spells it can propose before a Grizzly Bears it could have cast first, and
the two copy drives leave a creature alive and a card in the graveyard.
"""

from __future__ import annotations

from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, resolve_stack

#: How many storm spells the ordering census must see proposed on their own
#: (nine of Scourge's twelve on the base board; the rest have nothing to
#: counter, no attacker to answer or no Dragon to find).
_PROPOSED_FLOOR = 6

_BASICS = ("Plains", "Island", "Swamp", "Mountain", "Forest")


def _pool(set_pool) -> dict:
    return {**{card.name: card for card in load_catalog()}, **set_pool("SCG")}


def _table(pool, hand, own=(), other=(), graveyard=(), *, lands=None, enforce=True) -> Game:
    game = Game(players=[
        PlayerState(
            name="AI", hand=[pool[name] for name in hand],
            graveyard=[pool[name] for name in graveyard],
            library=[pool["Island"]] * 10,
        ),
        PlayerState(name="Opp", library=[pool["Island"]] * 10),
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set()
    lands = [name for name in _BASICS for _ in range(3)] if lands is None else lands
    for name in [*lands, *own]:
        game.players[0].battlefield.append(_nosick(Permanent(card=pool[name])))
    for name in other:
        game.players[1].battlefield.append(_nosick(Permanent(card=pool[name])))
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


def _prints_storm(card) -> bool:
    """The census's own reading of the keyword: a line that starts "Storm"."""
    return "\nStorm (" in f"\n{card.oracle_text}"


def test_every_storm_spell_reads_as_one(set_pool):
    from engine.ai_valuation import copies_for_the_spells_before_it

    storms = [card for card in set_pool("SCG").values() if _prints_storm(card)]
    assert len(storms) == 12 and all(copies_for_the_spells_before_it(card) for card in storms)
    assert not copies_for_the_spells_before_it(set_pool("LEA")["Lightning Bolt"])


def test_a_storm_spell_is_cast_after_a_spell_it_could_follow(set_pool):
    """Each storm spell beside a Grizzly Bears, with mana for both: when the
    storm spell is worth casting on its own, the Bears goes first — one copy
    more for the same two cards."""
    pool = _pool(set_pool)
    storms = sorted(
        (card for card in set_pool("SCG").values() if _prints_storm(card)),
        key=lambda card: card.name,
    )
    setting = dict(
        own=["Grizzly Bears"], other=["Llanowar Elves", "Llanowar Elves", "Hill Giant"],
        graveyard=["Hill Giant", "Grizzly Bears"],
    )
    proposed, first = [], []
    for card in storms:
        alone = choose_cast_action(_table(pool, [card.name], **setting), 0)
        if alone is None:
            continue
        proposed.append(card.name)
        both = choose_cast_action(_table(pool, [card.name, "Grizzly Bears"], **setting), 0)
        if both is None or both.card_name != "Grizzly Bears":
            first.append(card.name)
    assert len(proposed) >= _PROPOSED_FLOOR, proposed
    assert not first, first


def test_a_storm_spell_keeps_its_place_when_the_other_cast_would_spend_its_mana(set_pool):
    """Three Mountains and a Forest pay for Scattershot or for the Bears and
    two Mountains more, never for both: deferring would lose the storm spell,
    so the better card is cast."""
    pool = _pool(set_pool)
    game = _table(
        pool, ["Scattershot", "Grizzly Bears"], other=["Llanowar Elves", "Hill Giant"],
        lands=["Mountain", "Mountain", "Mountain", "Forest"],
    )
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Scattershot"


def _cast_after(game, *names) -> None:
    for name in names:
        assert game.cast_from_hand(0, name, target_player_index=1).supported
        resolve_stack(game)


def test_scattershots_copies_are_spread_over_the_creatures_they_can_kill(set_pool):
    """Two spells first, then Scattershot at one of three 1/1s: two copies,
    each re-aimed, and all three Elves die."""
    pool = _pool(set_pool)
    game = _table(
        pool, ["Lightning Bolt", "Shock", "Scattershot"],
        other=["Llanowar Elves"] * 3, lands=["Mountain"] * 5, enforce=False,
    )
    _cast_after(game, "Lightning Bolt", "Shock")
    elf = next(iter(game.controlled_by(1)))
    result = game.cast_from_hand(
        0, "Scattershot", target_player_index=1, target_permanent_ids=[elf.permanent_id],
    )
    assert result.supported
    resolve_stack(game)
    assert not list(game.controlled_by(1))
    assert [card.name for card in game.players[1].graveyard].count("Llanowar Elves") == 3


def test_reaping_the_graves_copy_returns_another_card(set_pool):
    """A Dark Ritual first, then Reaping the Graves at the Grizzly Bears with
    a Hill Giant beside it in the graveyard: the copy returns the Giant and
    the original the Bears."""
    pool = _pool(set_pool)
    game = _table(
        pool, ["Dark Ritual", "Reaping the Graves"],
        graveyard=["Grizzly Bears", "Hill Giant"], lands=["Swamp"] * 5, enforce=False,
    )
    assert game.cast_from_hand(0, "Dark Ritual").supported
    resolve_stack(game)
    assert game.cast_from_hand(0, "Reaping the Graves", target_player_index=0).supported
    resolve_stack(game)
    assert sorted(card.name for card in game.players[0].hand) == ["Grizzly Bears", "Hill Giant"]


def test_a_copy_aimed_well_already_keeps_its_target(set_pool):
    """Tendrils of Agony's copy has nothing better than the opponent it was
    aimed at: it keeps it, and the opponent loses 4."""
    pool = _pool(set_pool)
    game = _table(pool, ["Shock", "Tendrils of Agony"], lands=["Swamp"] * 5, enforce=False)
    _cast_after(game, "Shock", "Tendrils of Agony")
    assert (game.players[0].life, game.players[1].life) == (24, 14)

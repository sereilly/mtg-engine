"""Stronghold sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G3: combat triggers, delayed effects and retargeting ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w1g3_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_spell_game(set_pool, spell, mine, theirs):
    pool = set_pool("STH")
    p1 = PlayerState(
        name="P1", hand=[pool[spell]], life=20,
        battlefield=[Permanent(card=_w1g3_creature(n, 2, 2)) for n in mine],
    )
    p2 = PlayerState(
        name="P2", life=20,
        battlefield=[Permanent(card=_w1g3_creature(n, 2, 2)) for n in theirs],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game, p1, p2


def test_mogg_infestation_targets_a_player_not_an_opponent(set_pool):
    """"Destroy all creatures **target player** controls."

    The card is printed to be aimable either way — a caster with an empty board
    and a full graveyard wants their own creatures gone — so the seat word is
    ``player``, not ``opponent``, and the picker must offer both.
    """
    card = set_pool("STH")["Mogg Infestation"]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert derive_cast_spec(card, program) == {"kind": "player"}


def test_mogg_infestation_gives_the_goblins_to_the_player_it_named(set_pool):
    """"For each creature that died this way, **that player** creates two 1/1
    red Goblin creature tokens."

    Two 1/1s for each creature that actually died, on the *targeted* player's
    battlefield — "that player" is the seat the first sentence chose, not the
    caster. The loop iterates the permanents the sweep recorded, because by the
    time it runs they are cards in a graveyard.
    """
    game, caster, victim = _w1g3_spell_game(
        set_pool, "Mogg Infestation", ["Mine"], ["Theirs A", "Theirs B"],
    )
    assert game.cast_from_hand(0, "Mogg Infestation", target_player_index=1).supported
    game.resolve_stack()

    assert sorted(p.card.name for p in game.players[1].battlefield) == [
        "Goblin Token"
    ] * 4, game.log
    assert [p.card.name for p in game.players[0].battlefield] == ["Mine"], game.log
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Theirs A", "Theirs B"
    ], game.log


def test_mogg_infestation_makes_nothing_when_nothing_died(set_pool):
    """The count is what *died*, not what the sweep aimed at: a player with no
    creatures gets no Goblins, which is the difference between reading the
    record and reading the sentence."""
    game, _caster, _victim = _w1g3_spell_game(
        set_pool, "Mogg Infestation", ["Mine"], [],
    )
    assert game.cast_from_hand(0, "Mogg Infestation", target_player_index=1).supported
    game.resolve_stack()

    assert game.players[1].battlefield == [], game.log
    assert [p.card.name for p in game.players[0].battlefield] == ["Mine"], game.log

"""VIS wave 3 group 5 — the rules behind the mana-pool clauses.

Three printed sentences, one per rule, decomposed out of two fused card hooks
so that Pygmy Hippo (VIS) and Drain Power (LEA) read the same productions:

    <player> activates a mana ability of each land they control   CR 605.1a
    <player> loses all unspent mana                               CR 106.4 / 500.5
    you add the mana lost this way                                CR 106.13

The per-card behaviour is in ``tests/sets/``; what is here is the rule each
clause is an instance of.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _board(catalog_by_name, defender_lands, *, pool=None, restricted=None):
    """Seat 0 holding Drain Power, seat 1 holding *defender_lands*."""
    p0 = PlayerState(name="P0", hand=[catalog_by_name["Drain Power"]])
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=catalog_by_name[name]) for name in defender_lands
        ],
        mana_pool=dict(pool or {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}),
    )
    if restricted:
        p1.restricted_mana.update({k: dict(v) for k, v in restricted.items()})
    game = Game(players=[p0, p1])
    return game, p0, p1


@pytest.mark.cr("605.1a", "605.1")
def test_a_forced_activation_runs_the_lands_own_mana_ability(catalog_by_name):
    """"Activates a mana ability of each land they control" activates the
    **ability**, so what a land makes is what its ability says.

    Mishra's Workshop's is "{T}: Add {C}{C}{C}". Read off the card's list of
    producible symbols instead — which is what the fused handler this replaced
    did — a land making three mana makes one, and a land whose amount sits
    behind a condition cannot be read at all.
    """
    game, p0, p1 = _board(catalog_by_name, ["Mishra's Workshop"])

    assert game.cast_from_hand(0, "Drain Power", target_player_index=1).supported

    assert sum(
        sum(bucket.values()) for bucket in p0.restricted_mana.values()
    ) == 3, game.log


@pytest.mark.cr("106.4", "500.5")
def test_losing_all_unspent_mana_empties_the_pool_mid_resolution(catalog_by_name):
    """CR 500.5 empties a pool as a step or phase *ends*; these cards do it in
    the middle of a resolution, and CR 106.4 is what makes "lose" the word for
    it.

    "All" is the whole pool as it stands — the mana the same effect just made
    **and** whatever the player was already holding.
    """
    game, _p0, p1 = _board(
        catalog_by_name, ["Island"],
        pool={"W": 0, "U": 0, "B": 2, "R": 0, "G": 0, "C": 0},
    )

    game.cast_from_hand(0, "Drain Power", target_player_index=1)

    assert sum(p1.mana_pool.values()) == 0, game.log


@pytest.mark.cr("106.13")
def test_mana_lost_this_way_keeps_the_restrictions_it_arrived_with(catalog_by_name):
    """CR 106.13, a rule written about Drain Power by name: "Which permanents,
    spells, and/or abilities produced that mana are unchanged, as are any
    restrictions or additional effects associated with any of that mana."

    So a bucket that could pay only for artifact spells is still one after it
    changes hands, and the total is unchanged.
    """
    game, p0, p1 = _board(
        catalog_by_name, ["Island"], restricted={"creature": {"G": 2}},
    )

    game.cast_from_hand(0, "Drain Power", target_player_index=1)

    assert p0.mana_pool["U"] == 1, "the Island's mana is unrestricted"
    assert p0.restricted_mana.get("creature") == {"G": 2}, p0.restricted_mana
    assert not any(p1.restricted_mana.values()), "and the defender keeps none"


@pytest.mark.cr("106.4")
def test_a_pool_clause_records_zero_rather_than_nothing(catalog_by_name):
    """A player with no lands and an empty pool loses nothing, and the sentence
    behind the loss still has a record to read.

    The failure this rules out is the one a missing key gives: the reader adds
    whatever it finds, and a clause that found no key at all is a sentence
    reporting itself resolved having read nothing.
    """
    game, p0, p1 = _board(catalog_by_name, [])

    assert game.cast_from_hand(0, "Drain Power", target_player_index=1).supported
    assert sum(p0.mana_pool.values()) == 0
    assert not any(p0.restricted_mana.values())


@pytest.mark.cr("603.7b", "603.7")
def test_a_delayed_ability_printed_this_turn_expires_with_the_turn(set_pool):
    """CR 603.7b's "stated duration", printed at the *end* of the opener:
    "at the beginning of your next main phase **this turn**" (Pygmy Hippo).

    The same two words the openers already read from the front of a sentence
    ("this turn, when target creature you control attacks…"), and they narrow
    rather than widen: without them the entry is Mana Drain's, waiting for a
    main phase however many turns away.
    """
    from engine.grammar import parse_line
    from engine.grammar.lower import lower_ability

    windowed, = lower_ability(parse_line(
        "At the beginning of your next main phase this turn, you gain 1 life."
    ))
    open_ended, = lower_ability(parse_line(
        "At the beginning of your next main phase, you gain 1 life."
    ))

    assert windowed.payload["event"] == open_ended.payload["event"]
    assert windowed.payload["duration"] == "end_of_turn"
    assert open_ended.payload["duration"] == "until_it_triggers"
    # And the card is the reason the row exists.
    assert "this turn" in (set_pool("VIS")["Pygmy Hippo"].oracle_text or "")

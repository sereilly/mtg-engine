"""A printed target another seat picks as the effect resolves is still a
target (Mirrodin's promotion rehearsal, W2G0).

"At the beginning of each player's upkeep, that player puts a flood counter
on **target** non-Island land they control **of their choice**." (Quicksilver
Fountain.) This engine makes that pick at resolution, on the seat the firing
event froze — The Abyss's and Ley Line's recorded deviation from CR 603.3d —
and the candidates were every land the noun phrase admits: a land with
shroud was flooded. Whoever picks, the ability is what targets (CR 115.1d),
so the candidates are now held to what it could target
(``permanent_choice_candidates`` reading ``announced_target``): shroud
(CR 702.18a), hexproof against the ability's *controller* (CR 702.11b — not
the seat picking), protection from the source (CR 702.16b). The Abyss and
Echo Chamber print the same shape and are driven here too.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.keywords import grant_keyword, grant_protection_flag
from engine.models import Permanent
from engine.named_counters import counters_on
from tests.helpers import resolve_stack


def _table(set_pool, mine, theirs, *, interactive=()):
    """Seat 0 holds *mine*, seat 1 *theirs* (names from Mirrodin, else Alpha,
    Legends or Tempest); nothing has summoning sickness."""
    pools = [set_pool(code) for code in ("MRD", "LEA", "LEG", "TMP")]

    def card(name):
        return next(pool[name] for pool in pools if name in pool)

    game = Game(players=[
        PlayerState(name="A", library=[card("Plains")] * 8),
        PlayerState(name="B", library=[card("Plains")] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    return game, placed[0], placed[1]


def _upkeep(game, seat) -> None:
    game.turn += 1
    game.start_turn(seat)
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


@pytest.mark.cr("115.1d", "702.18a")
def test_the_fountain_never_floods_a_land_with_shroud(set_pool):
    """Seat 0's upkeep under seat 1's Fountain: the Forest has shroud, so the
    Plains is the only answer — asked, the Forest is refused and the Plains
    taken; unasked, the default takes the Plains."""
    for interactive in ((0,), ()):
        game, (forest, plains), _ = _table(
            set_pool, ["Forest", "Plains"], ["Quicksilver Fountain"],
            interactive=interactive,
        )
        grant_keyword(forest, "shroud")
        game.turn += 1
        game.start_turn(0)
        game._settle()
        owed = game.pending_choice_of("permanent_choice", 0)
        if interactive:
            assert owed is not None
            assert [p.card.name for p in game.live_permanent_choices(owed)] == ["Plains"]
            assert not game.confirm_permanent_choice(0, forest.permanent_id)
            assert game.confirm_permanent_choice(0, plains.permanent_id)
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        resolve_stack(game)
        assert counters_on(forest, "flood") == 0 and forest.has_type("forest")
        assert counters_on(plains, "flood") == 1 and plains.has_type("island")


@pytest.mark.cr("115.1d", "702.18a")
def test_with_only_a_shrouded_land_nothing_is_flooded(set_pool):
    game, (forest,), _ = _table(set_pool, ["Forest"], ["Quicksilver Fountain"])
    grant_keyword(forest, "shroud")

    _upkeep(game, 0)

    assert counters_on(forest, "flood") == 0 and forest.has_type("forest")


@pytest.mark.cr("702.11b")
def test_hexproof_stops_the_fountain_of_an_opponent_and_not_its_own(set_pool):
    """Hexproof is asked against the *ability's controller*. Seat 1's
    Fountain cannot target seat 0's hexproof Forest; on seat 1's own upkeep
    its own hexproof Forest is a legal target of its own ability."""
    game, (forest, plains), (fountain, own_forest) = _table(
        set_pool, ["Forest", "Plains"], ["Quicksilver Fountain", "Forest"],
    )
    grant_keyword(forest, "hexproof")
    grant_keyword(own_forest, "hexproof")

    _upkeep(game, 0)
    assert counters_on(forest, "flood") == 0
    assert counters_on(plains, "flood") == 1

    _upkeep(game, 1)
    assert counters_on(own_forest, "flood") == 1 and own_forest.has_type("island")


@pytest.mark.cr("702.16b")
def test_protection_from_artifacts_stops_the_fountain(set_pool):
    game, (forest, plains), _ = _table(
        set_pool, ["Forest", "Plains"], ["Quicksilver Fountain"],
    )
    grant_protection_flag(forest, "artifacts")

    _upkeep(game, 0)

    assert counters_on(forest, "flood") == 0
    assert counters_on(plains, "flood") == 1


@pytest.mark.cr("115.1d", "702.16b")
def test_the_abyss_cannot_target_a_creature_with_protection_from_black(set_pool):
    """"…destroy target nonartifact creature that player controls of their
    choice. It can't be regenerated." The Abyss is black, so White Knight
    (protection from black) is no answer: the Grizzly Bears is destroyed, and
    with only the Knight nothing is."""
    game, (knight, bears), _ = _table(set_pool, ["White Knight", "Grizzly Bears"], ["The Abyss"])
    _upkeep(game, 0)
    assert game.is_on_battlefield(knight)
    assert not game.is_on_battlefield(bears)

    game, (knight,), _ = _table(set_pool, ["White Knight"], ["The Abyss"])
    _upkeep(game, 0)
    assert game.is_on_battlefield(knight)


@pytest.mark.cr("602.3", "702.18a")
def test_echo_chamber_is_not_activated_into_an_untargetable_choice(set_pool):
    """"An opponent chooses target creature they control. Create a token
    that's a copy of that creature…" With the opponent's only creature
    shrouded the ability has no legal target, so it is refused before its {4}
    and {T} are paid (CR 601.2c through CR 602.2b)."""
    game, (chamber,), (bears,) = _table(set_pool, ["Echo Chamber"], ["Grizzly Bears"])
    grant_keyword(bears, "shroud")
    game.active_player_index = game.priority_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None

    refused = game.activate_permanent_ability(
        0, "Echo Chamber", permanent_index=game.battlefield_index_of(chamber),
    )

    assert not refused.supported and "no valid target" in refused.details
    assert not chamber.tapped

"""Tests for Free-For-All (3+ player) support: CR 802 (attack multiple players),
CR 800.4 (a player leaving the game), and the multiplayer-only mulligan rule
(CR 800.6). See ``tests/rules/test_combat_phase.py`` for the 2-player combat suite —
this file covers only what's genuinely different with 3+ players.
"""

import pytest

from engine import Game
from engine.models import CardDefinition, Permanent, PlayerState


def _mk_creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test", "power": str(power), "toughness": str(toughness)},
    )


def _p0_with_library(**kwargs) -> PlayerState:
    """A PlayerState for the active player in tests that call ``start_turn``
    (which draws a card) — needs at least one library card so the draw step
    doesn't trigger a 704.5b loss from drawing off an empty library."""
    kwargs.setdefault("library", [_mk_creature("Filler", 1, 1)])
    return PlayerState(name="P0", **kwargs)


def _to_declare_attackers(game: Game) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers


# ---------------------------------------------------------------------------
# CR 802.2/802.3 — declaring attackers against multiple defending players
# ---------------------------------------------------------------------------

@pytest.mark.cr("802.3")
def test_802_3_attacker_can_choose_a_different_defender_per_creature():
    a1 = Permanent(card=_mk_creature("Attacker One", 2, 2))
    a2 = Permanent(card=_mk_creature("Attacker Two", 2, 2))
    p0 = _p0_with_library(battlefield=[a1, a2])
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p0, p1, p2])
    _to_declare_attackers(game)

    ok, msg = game.declare_attackers(0, [0, 1], attacker_targets={0: 1, 1: 2})
    assert ok, msg
    assert game.combat_attackers == {0: 1, 1: 2}
    assert game.combat_defending_players() == {1, 2}
    # No single defender — the back-compat scalar is only meaningful with one.
    assert game.combat_defending_player_index is None


@pytest.mark.cr("802.2")
def test_802_2_get_combat_state_reports_every_defending_player():
    a1 = Permanent(card=_mk_creature("Attacker One", 2, 2))
    a2 = Permanent(card=_mk_creature("Attacker Two", 2, 2))
    p0 = _p0_with_library(battlefield=[a1, a2])
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p0, p1, p2])
    _to_declare_attackers(game)
    game.declare_attackers(0, [0, 1], attacker_targets={0: 1, 1: 2})

    state = game.get_combat_state()
    assert state["defending_player_indices"] == [1, 2]
    assert sorted((a["attacker_index"], a["defending_player_index"]) for a in state["attackers"]) == [
        (0, 1),
        (1, 2),
    ]


@pytest.mark.cr("802.3a")
def test_802_3_must_attack_if_able_checked_against_any_living_opponent():
    """A "must attack if able" creature is satisfied by attacking ANY opponent —
    not specifically a pre-picked one — when it's declared."""
    forced = Permanent(card=_mk_creature("Forced", 2, 2))
    forced.metadata["must_attack_until_eot"] = True
    p0 = _p0_with_library(battlefield=[forced])
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p0, p1, p2])
    _to_declare_attackers(game)

    # Declaring it against p2 alone (omitting it entirely would fail).
    ok, msg = game.declare_attackers(0, [0], attacker_targets={0: 2})
    assert ok, msg


@pytest.mark.cr("802.3", "800.4")
def test_802_attacker_cannot_target_an_eliminated_player():
    a1 = Permanent(card=_mk_creature("Attacker", 2, 2))
    p0 = _p0_with_library(battlefield=[a1])
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p2.lost = True
    game = Game(players=[p0, p1, p2])
    _to_declare_attackers(game)

    ok, msg = game.declare_attackers(0, [0], attacker_targets={0: 2})
    assert not ok
    assert "left the game" in msg


# ---------------------------------------------------------------------------
# CR 802.4 — APNAP-ordered blocking, each defender only blocking their own
# ---------------------------------------------------------------------------

def _to_declare_blockers_multi(game: Game, attacker_targets: dict[int, int]) -> None:
    _to_declare_attackers(game)
    ok, msg = game.declare_attackers(0, list(attacker_targets), attacker_targets=attacker_targets)
    assert ok, msg
    game.advance_combat_phase()  # declare_attackers -> declare_blockers (enters the step)
    if game.current_step == "declare_blockers" and not game.combat_blockers_locked:
        game.advance_combat_phase()  # process the declare_blockers auto-skip/APNAP logic


@pytest.mark.cr("802.4a")
def test_802_4_each_defender_blocks_only_attackers_aimed_at_them():
    a1 = Permanent(card=_mk_creature("Attacker One", 2, 2))
    a2 = Permanent(card=_mk_creature("Attacker Two", 2, 2))
    b1 = Permanent(card=_mk_creature("Blocker One", 2, 2))
    b2 = Permanent(card=_mk_creature("Blocker Two", 2, 2))
    p0 = _p0_with_library(battlefield=[a1, a2])
    p1 = PlayerState(name="P1", battlefield=[b1])
    p2 = PlayerState(name="P2", battlefield=[b2])
    game = Game(players=[p0, p1, p2])
    _to_declare_blockers_multi(game, {0: 1, 1: 2})
    assert game.current_step == "declare_blockers"

    # P1 can't block attacker 1 (aimed at P2), only attacker 0 (aimed at them).
    ok, msg = game.declare_blockers(1, {0: 1})
    assert not ok
    assert "not attacking this player" in msg

    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    ok, msg = game.declare_blockers(2, {0: 1})
    assert ok, msg

    # Both defenders' blocks survive — the second didn't erase the first's.
    assert game.combat_blockers == {1: {0: [0]}, 2: {0: [1]}}
    assert game.combat_blockers_locked is True


@pytest.mark.cr("802.4")
def test_802_4_apnap_second_defender_declares_after_first_without_erasing():
    """Regression: declare_blockers used to overwrite the whole combat_blockers
    dict, so a second defender's declaration would erase an earlier defender's
    blocks in the same combat."""
    a1 = Permanent(card=_mk_creature("Attacker One", 2, 2))
    a2 = Permanent(card=_mk_creature("Attacker Two", 2, 2))
    b1 = Permanent(card=_mk_creature("Blocker One", 2, 2))
    b2 = Permanent(card=_mk_creature("Blocker Two", 2, 2))
    p0 = _p0_with_library(battlefield=[a1, a2])
    p1 = PlayerState(name="P1", battlefield=[b1])
    p2 = PlayerState(name="P2", battlefield=[b2])
    game = Game(players=[p0, p1, p2])
    _to_declare_blockers_multi(game, {0: 1, 1: 2})

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    assert 1 in game.combat_blockers  # P1's block recorded

    ok, _ = game.declare_blockers(2, {0: 1})
    assert ok
    assert 1 in game.combat_blockers  # still there after P2 declares
    assert 2 in game.combat_blockers


# ---------------------------------------------------------------------------
# CR 510/802.5 — per-defender combat damage resolution
# ---------------------------------------------------------------------------

@pytest.mark.cr("802.5", "510.2")
def test_802_5_unblocked_damage_lands_on_each_attacker_own_defender():
    a1 = Permanent(card=_mk_creature("Attacker One", 3, 3))
    a2 = Permanent(card=_mk_creature("Attacker Two", 5, 5))
    p0 = _p0_with_library(battlefield=[a1, a2])
    p1 = PlayerState(name="P1", life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p0, p1, p2])
    _to_declare_blockers_multi(game, {0: 1, 1: 2})
    # No blockers on either side: declare_blockers auto-skips straight through.
    assert game.combat_attackers_locked is True
    assert game.combat_blockers_locked is True

    game.advance_combat_phase()  # -> combat_damage (or resolves automatically)
    if game.current_step == "combat_damage" and not game.combat_damage_resolved:
        ok, msg = game.resolve_combat_damage(0)
        assert ok, msg

    assert p1.life == 17  # took 3 from Attacker One
    assert p2.life == 15  # took 5 from Attacker Two


# ---------------------------------------------------------------------------
# CR 800.4 — a player leaving the game (elimination)
# ---------------------------------------------------------------------------

@pytest.mark.cr("800.4")
def test_800_4_eliminated_player_is_skipped_in_turn_rotation():
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p0, p1, p2])
    p1.lost = True
    game.active_player_index = 0
    game.normal_rotation_anchor = 0
    assert game._compute_next_active_player() == 2  # skips eliminated P1


@pytest.mark.cr("800.4")
def test_800_4_eliminated_player_is_skipped_for_priority():
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p0, p1, p2])
    p1.lost = True
    assert game._next_player_index(0) == 2


@pytest.mark.cr("800.4a")
def test_800_4a_eliminated_player_battlefield_is_cleared_in_multiplayer():
    dying = Permanent(card=_mk_creature("Doomed", 2, 2))
    p0 = PlayerState(name="P0", life=0, battlefield=[dying])
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p0, p1, p2])
    game.check_state_based_actions()
    assert p0.lost is True
    assert p0.battlefield == []


@pytest.mark.cr("800.4a")
def test_800_4a_2_player_loss_does_not_clear_battlefield():
    """CR 800.4 is explicitly a multiplayer concept — a 2-player game just ends
    instead, so nothing here should touch the loser's battlefield."""
    dying = Permanent(card=_mk_creature("Doomed", 2, 2))
    p0 = PlayerState(name="P0", life=0, battlefield=[dying])
    p1 = PlayerState(name="P1")
    game = Game(players=[p0, p1])
    game.check_state_based_actions()
    assert p0.lost is True
    assert p0.battlefield == [dying]


@pytest.mark.cr("104.2a")
def test_104_2a_get_winner_with_four_players():
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    p3 = PlayerState(name="P3")
    game = Game(players=[p0, p1, p2, p3])
    p1.lost = True
    p2.lost = True
    p3.lost = True
    assert game.get_winner() is p0
    assert game.is_game_over() is True


# ---------------------------------------------------------------------------
# CR 800.6 — first mulligan is free in multiplayer
# ---------------------------------------------------------------------------

@pytest.mark.cr("800.6")
def test_800_6_first_mulligan_free_in_multiplayer():
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p0, p1, p2])
    for _ in range(9):
        p0.library.append(_mk_creature("Filler", 1, 1))
    p0.hand = [c for c in [_mk_creature("H", 1, 1) for _ in range(7)]]

    assert game.mulligan_effective_count(0) == 0
    game.take_mulligan(0)
    assert p0.mulligans_taken == 1
    # First mulligan free: no cards bottomed, doesn't count toward the limit.
    assert game.mulligan_effective_count(0) == 0
    assert len(p0.hand) == 7

    game.take_mulligan(0)
    assert p0.mulligans_taken == 2
    # Second mulligan counts normally: 1 card bottomed.
    assert game.mulligan_effective_count(0) == 1
    assert len(p0.hand) == 6


@pytest.mark.cr("800.6", "103.5")
def test_800_6_two_player_mulligan_unaffected():
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    game = Game(players=[p0, p1])
    for _ in range(9):
        p0.library.append(_mk_creature("Filler", 1, 1))
    p0.hand = [_mk_creature("H", 1, 1) for _ in range(7)]

    game.take_mulligan(0)
    assert p0.mulligans_taken == 1
    # 2-player: no discount, matches the historical single-mulligan bottom count.
    assert game.mulligan_effective_count(0) == 1
    assert len(p0.hand) == 6


# ---------------------------------------------------------------------------
# CR 806 — the Free-for-All variant itself, and CR 802.1's "only one player"
# ---------------------------------------------------------------------------

@pytest.mark.cr("806.1")
def test_806_1_every_other_player_is_an_opponent():
    """In Free-for-All, players compete as individuals — there are no teams.

    So each player's opponent set is simply everyone else, symmetrically. This
    is the rule that makes every other 806/802 behaviour meaningful: with teams
    the sets would be smaller and asymmetric.
    """
    game = Game(players=[
        _p0_with_library(),
        PlayerState(name="P1"),
        PlayerState(name="P2"),
        PlayerState(name="P3"),
    ])

    assert set(game.opponents_of(0)) == {1, 2, 3}
    assert set(game.opponents_of(1)) == {0, 2, 3}
    assert set(game.opponents_of(3)) == {0, 1, 2}


@pytest.mark.cr("806.1", "104.2a")
def test_806_1_a_free_for_all_ends_only_when_one_individual_remains():
    """Competing as individuals means one elimination does not end the game —
    the game continues until a single player is left."""
    game = Game(players=[
        _p0_with_library(),
        PlayerState(name="P1", life=0),
        PlayerState(name="P2"),
    ])

    game.check_state_based_actions()
    assert game.players[1].lost is True
    assert game.is_game_over() is False
    assert game.get_winner() is None

    game.players[2].life = 0
    game.check_state_based_actions()
    assert game.is_game_over() is True
    assert game.get_winner() is game.players[0]


@pytest.mark.cr("806.2", "806.2b")
def test_806_2b_the_variant_uses_the_attack_multiple_players_option():
    """Exactly one of attack-left, attack-right and attack-multiple-players is
    used, and this engine uses the third: an attacker may be aimed at *any*
    living opponent, not only at a seat neighbour.

    Attacking "left" would make seat 1 the only legal target for seat 0; that
    seat 2 is equally legal is what identifies the option in force.
    """
    a1 = Permanent(card=_mk_creature("Free Attacker", 2, 2))
    game = Game(players=[
        _p0_with_library(battlefield=[a1]),
        PlayerState(name="P1"),
        PlayerState(name="P2"),
    ])
    _to_declare_attackers(game)

    ok, msg = game.declare_attackers(0, [0], attacker_targets={0: 2})

    assert ok, msg
    assert game.combat_attackers == {0: 2}


@pytest.mark.cr("806.2c")
def test_806_2c_creatures_are_not_deployed_to_another_player():
    """The deploy creatures option isn't used in Free-for-All: a creature is
    controlled by its own controller and attacks under them, so the attacking
    seat is the active player and nobody else."""
    a1 = Permanent(card=_mk_creature("Own Attacker", 2, 2))
    game = Game(players=[
        _p0_with_library(battlefield=[a1]),
        PlayerState(name="P1"),
        PlayerState(name="P2"),
    ])
    _to_declare_attackers(game)
    game.declare_attackers(0, [0], attacker_targets={0: 1})

    assert game.controller_index_of(a1) == 0
    assert game.active_player_index == 0


@pytest.mark.cr("802.1")
def test_802_1_the_attacker_may_choose_to_attack_only_one_player():
    """With the attack-multiple-players option in use, a player may still send
    every attacker at a single opponent in a particular combat — "multiple
    players" is a permission, not a requirement."""
    a1 = Permanent(card=_mk_creature("Attacker One", 2, 2))
    a2 = Permanent(card=_mk_creature("Attacker Two", 2, 2))
    game = Game(players=[
        _p0_with_library(battlefield=[a1, a2]),
        PlayerState(name="P1"),
        PlayerState(name="P2"),
    ])
    _to_declare_attackers(game)

    ok, msg = game.declare_attackers(0, [0, 1], attacker_targets={0: 2, 1: 2})

    assert ok, msg
    assert game.combat_defending_players() == {2}
    assert game.combat_attackers == {0: 2, 1: 2}


@pytest.mark.cr("802.1")
def test_802_1_a_single_defender_is_still_a_legal_whole_combat():
    """The scalar back-compat view is meaningful exactly when one player is
    being attacked — the case CR 802.1's second sentence describes."""
    a1 = Permanent(card=_mk_creature("Lone Attacker", 3, 3))
    game = Game(players=[
        _p0_with_library(battlefield=[a1]),
        PlayerState(name="P1"),
        PlayerState(name="P2"),
    ])
    _to_declare_attackers(game)
    game.declare_attackers(0, [0], attacker_targets={0: 1})

    assert game.combat_defending_player_index == 1

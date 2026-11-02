"""CR 508.1d's maximisation for attacks, on the boards the playbook named.

Each test drives a real board through ``Game.declare_attackers`` — the gate a
person's declaration and the AI's both reach — and reads the verdict, the
refusal and, where a cost is involved, what was paid. The census beside these
(``tests/engine/test_kg3_attacks_requirement_census.py``) judges every shipped
card against a brute force; these name the shapes one at a time.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

from tests.helpers import _mk_card, _mk_creature_card, _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def _perm(name_or_card, *, sick: bool = False) -> Permanent:
    card = _CARDS[name_or_card] if isinstance(name_or_card, str) else name_or_card
    perm = Permanent(card=card)
    return perm if sick else _nosick(perm)


def _declaring(mine, theirs, *, third=None, interactive=True):
    """Seat 0 in its declare attackers step, *mine* and *theirs* on the board
    (and a third seat's permanents when *third* is given)."""
    # A library each, because a multiplayer game's first player draws on its
    # first turn (CR 103.8a skips that draw only in a two-player game).
    def library():
        return [_mk_card("Top", "Land")] * 3

    players = [PlayerState(name="P0", battlefield=list(mine), library=library()),
               PlayerState(name="P1", battlefield=list(theirs), library=library())]
    if third is not None:
        players.append(
            PlayerState(name="P2", battlefield=list(third), library=library())
        )
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game._sync_control()
    sick = [p for p in mine if p.metadata.get("summoning_sickness_turn") != -99]
    game.start_turn(0)
    for perm in sick:
        # Entered this turn (CR 302.6): the stamp names the turn being taken.
        perm.metadata["summoning_sickness_turn"] = game.turn
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    return game


def _bear(name="Grizzly Bears"):
    return _perm(_mk_creature_card(name, 2, 2))


@pytest.mark.cr("508.1c", "508.1d")
def test_the_rules_own_example_under_dueling_grounds():
    """"A player controls two creatures: one that 'attacks if able' and one
    with no abilities. An effect states 'No more than one creature can attack
    each combat.' The only legal attack is for just the creature that 'attacks
    if able' to attack." (CR 508.1d, Example.) The plain creature attacking
    alone was accepted: the requirement loop cleared every requirement once
    the cap was reached."""
    def board():
        return _declaring(
            [_perm("Juggernaut"), _bear(), _perm("Dueling Grounds")], [],
        )

    assert board().declare_attackers(0, [], 1) == (
        False, "Juggernaut must attack if able"
    )
    assert board().declare_attackers(0, [1], 1) == (
        False, "Juggernaut must attack if able"
    )
    assert board().declare_attackers(0, [0, 1], 1) == (
        False, "no more than 1 creature(s) can attack each combat"
    )
    game = board()
    assert game.declare_attackers(0, [0], 1)[0], game.log
    assert game.players[0].battlefield[0].tapped


@pytest.mark.cr("508.1d")
def test_three_compelled_under_caverns_any_two_and_the_count_is_said():
    """Three requirements, two obeyable together: any two may attack, and a
    declaration obeying one is told how many it had to obey."""
    def board():
        return _declaring(
            [_perm("Juggernaut"), _perm("Juggernaut"), _perm("Juggernaut"),
             _perm("Caverns of Despair")], [],
        )

    ok, why = board().declare_attackers(0, [2], 1)
    assert not ok
    assert why == (
        "Juggernaut must attack if able (this declaration obeys 1 of the 2 "
        "attack requirements that can be obeyed together)"
    )
    for pair in ([0, 1], [0, 2], [1, 2]):
        game = board()
        assert game.declare_attackers(0, pair, 1)[0], (pair, game.log)


@pytest.mark.cr("508.1d", "508.1h")
def test_juggernaut_under_propaganda_is_not_compelled_to_pay():
    """"If there's a cost associated with having it attack, you're not forced
    to pay that cost, so it doesn't have to attack in that case either."
    (Juggernaut ruling, 2022-12-08.) Declaring nothing was refused."""
    def board():
        return _declaring(
            [_perm("Juggernaut"), _perm("Mountain"), _perm("Mountain")],
            [_perm("Propaganda")],
        )

    game = board()
    assert game.declare_attackers(0, [], 1) == (True, "declared attackers")
    # …and it may still attack, paying {2}.
    game = board()
    assert game.declare_attackers(0, [0], 1)[0], game.log
    assert all(perm.tapped for perm in game.players[0].battlefield[1:3])
    assert any("paid {2} to declare attackers" in line for line in game.log)


@pytest.mark.cr("508.1b", "508.1d")
def test_beside_propaganda_juggernaut_must_attack_the_planeswalker():
    """"Unless some effect explicitly says otherwise, a creature that can't
    attack you can still attack a planeswalker you control." (Propaganda
    ruling, 2014-02-01.) Attacking the planeswalker costs nothing, so the
    requirement can be obeyed for free — and must be. The old loop asked
    only about attacking a player."""
    def board():
        return _declaring(
            [_perm("Juggernaut")],
            [_perm("Propaganda"), _perm("Basri Ket")],
        )

    game = board()
    ok, why = game.declare_attackers(0, [], 1)
    assert (ok, why) == (False, "Juggernaut must attack if able")
    game = board()
    walker = next(p for p in game.players[1].battlefield if p.has_type("planeswalker"))
    assert game.declare_attackers(
        0, [0], 1, attacker_planeswalker_ids={0: walker.permanent_id},
    )[0], game.log
    assert game.combat_attacked_planeswalkers == {0: walker.permanent_id}
    assert not any("to declare attackers" in line for line in game.log)


@pytest.mark.cr("118.5", "508.1d")
def test_a_toll_of_zero_still_excuses_the_requirement():
    """"A cost of zero is not automatically paid, so the controller can
    choose to not pay." (War Tax ruling, 2004-10-04; CR 118.5.) A Collective
    Restraint whose controller has no basic land type charges {0} — the
    creature may attack for nothing, and need not."""
    def board():
        return _declaring(
            [_perm("Juggernaut")], [_perm("Collective Restraint")],
        )

    assert board().declare_attackers(0, [], 1) == (True, "declared attackers")
    game = board()
    assert game.declare_attackers(0, [0], 1)[0], game.log


@pytest.mark.cr("508.1d")
def test_a_conditional_requirement_is_disobeyed_only_where_its_condition_holds():
    """"If a creature you control attacks, this creature also attacks if
    able." (Ekundu Cyclops.) CR 508.1d's "attacks if some condition is met":
    a declaration that does not meet the condition does not disobey it."""
    def board(*extra):
        return _declaring([_perm("Ekundu Cyclops"), _bear(), *extra], [])

    assert board().declare_attackers(0, [], 1)[0]
    assert board().declare_attackers(0, [0], 1)[0]
    assert board().declare_attackers(0, [1], 1) == (
        False, "Ekundu Cyclops must attack if able"
    )
    assert board().declare_attackers(0, [0, 1], 1)[0]
    # Under Dueling Grounds the Cyclops cannot join the Bear, so the Bear
    # attacking alone disobeys the requirement while staying home does not.
    capped = _perm("Dueling Grounds")
    assert board(capped).declare_attackers(0, [1], 1) == (
        False, "Ekundu Cyclops must attack if able"
    )
    assert board(_perm("Dueling Grounds")).declare_attackers(0, [0], 1)[0]
    assert board(_perm("Dueling Grounds")).declare_attackers(0, [], 1)[0]


@pytest.mark.cr("508.1a", "508.1d")
def test_a_creature_that_cannot_attack_compels_nobody():
    """A summoning-sick Ekundu Cyclops is not able to attack (CR 508.1a), so
    its requirement imposes nothing — counted, it would forbid the Bear from
    ever meeting its condition."""
    game = _declaring([_perm("Ekundu Cyclops", sick=True), _bear()], [])
    assert game.declare_attackers(0, [1], 1)[0], game.log


@pytest.mark.cr("508.1d")
def test_each_source_is_a_requirement():
    """CR 508.1d counts requirements, not creatures: under Grand Melee a
    Juggernaut carries two and a Bear one, so with room for one attacker only
    the Juggernaut obeys the most."""
    def board():
        return _declaring(
            [_perm("Juggernaut"), _bear(), _perm("Grand Melee"),
             _perm("Dueling Grounds")], [],
        )

    ok, why = board().declare_attackers(0, [1], 1)
    assert not ok
    assert why.startswith("Juggernaut must attack if able"), why
    game = board()
    assert game.declare_attackers(0, [0], 1)[0], game.log


@pytest.mark.cr("508.1c", "508.1d")
def test_a_per_player_cap_sends_the_rest_at_another_opponent():
    """"No more than two creatures can attack you each combat." (Crawlspace.)
    Three compelled creatures and two opponents: two may attack the Crawlspace
    player and the third must attack the other — the old loop excused it once
    the capped seat was full, though another seat had room."""
    def board():
        return _declaring(
            [_perm("Juggernaut"), _perm("Juggernaut"), _perm("Juggernaut")],
            [_perm("Crawlspace")], third=[],
        )

    ok, why = board().declare_attackers(0, [0, 1], attacker_targets={0: 1, 1: 1})
    assert not ok
    assert why == "Juggernaut must attack if able"
    game = board()
    assert game.declare_attackers(
        0, [0, 1, 2], attacker_targets={0: 1, 1: 1, 2: 2},
    )[0], game.log


@pytest.mark.cr("508.1d")
def test_boiling_blood_cast_under_dueling_grounds():
    """The one-turn mark, put there by casting the card: Boiling Blood on the
    second Bear, and that Bear is the only creature that may attack."""
    blood = _CARDS["Boiling Blood"]
    first, second = _bear("First Bear"), _bear("Second Bear")
    game = Game(players=[
        PlayerState(
            name="P0", battlefield=[first, second, _perm("Dueling Grounds")],
            hand=[blood], library=[_mk_card("Top", "Land")] * 3,
        ),
        PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.start_turn(0)
    _nosick(first)
    _nosick(second)
    game._close_current_priority_step()
    result = game.cast_from_hand(
        0, "Boiling Blood", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(second),
    )
    assert result.supported, result.details
    resolve_stack(game)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    ok, why = game.declare_attackers(0, [game.battlefield_index_of(first)], 1)
    assert (ok, why) == (False, "Second Bear must attack if able")
    assert game.declare_attackers(0, [game.battlefield_index_of(second)], 1)[0]

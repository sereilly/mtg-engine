"""Per-card tests for Legends' instants, from round 35 onward.

Split from `test_legends_instants.py` at the 2,600-line readability cap, on the
axis `test_legends_creatures_round_30_onward.py` was cut on: every card in both
files is an instant, so the printed-type axis has no room left and the cut is a
**round boundary** (`tests/sets/README.md`). Each round section is
self-contained, so cutting between sections keeps every section whole and keeps
a test findable from its round.
"""

from __future__ import annotations

from engine import Game, PlayerState



def _r35_board(set_pool, catalog_by_name, seats: int = 2, sorceries: int = 2):
    """*sorceries* Fireballs in P1's hand and a Backdraft in P2's.

    Fireball because it is the one sorcery in the pool whose damage the caster
    sizes: two casts of it deal *different* amounts, which is what tells a
    per-cast record from a per-card one."""
    players = [PlayerState(name=f"P{i + 1}", life=20) for i in range(seats)]
    players[0].hand = [catalog_by_name["Fireball"]] * sorceries
    players[1].hand = [set_pool("LEG")["Backdraft"]]
    game = Game(players=players)
    game.enforce_mana_costs = False
    return game, players


def test_backdraft_deals_half_the_chosen_spells_damage(catalog_by_name, set_pool):
    """One sorcery cast this turn, so both choices are forced: half of 5,
    rounded down (CR 107.2)."""
    game, players = _r35_board(set_pool, catalog_by_name, sorceries=1)
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=5)

    result = game.cast_from_hand(1, "Backdraft")

    assert result.supported, result.details
    assert players[0].life == 18, game.log


def test_each_cast_of_one_sorcery_is_counted_separately(catalog_by_name, set_pool):
    """**The test this round exists for.** Two casts of the same card deal 4 and
    2; naming the second one deals 1.

    A record keyed on the damage's ``source`` would key both casts on the same
    ``CardDefinition`` — the card as printed, shared by every copy in every deck
    — and answer 6 for either choice, so Backdraft would deal 3 whichever spell
    the player named. The ledger keys a spell's damage on its ``StackItem``,
    which is one object per cast."""
    game, players = _r35_board(set_pool, catalog_by_name)
    game.interactive_seats = {1}
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=4)
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=2)

    game.cast_from_hand(1, "Backdraft")
    pending = game.pending_choice_of("cast_choice")
    assert pending is not None, game.log
    assert pending.data["damages"] == [4, 2], pending.data

    assert game.confirm_cast_choice(1, pending.data["options"][1]) is True
    assert players[0].life == 19, game.log


def test_a_non_interactive_seat_answers_both_prompts_itself(catalog_by_name, set_pool):
    """The stated default is the first option offered — deterministic rather
    than clever. A prompt an AI seat never answered would be a hang, not a
    failing assertion."""
    game, players = _r35_board(set_pool, catalog_by_name)
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=4)
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=2)

    result = game.cast_from_hand(1, "Backdraft")

    assert result.supported, result.details
    assert game.pending_choices == []
    assert players[0].life == 18, game.log


def test_nobody_cast_a_sorcery_so_nothing_is_chosen(catalog_by_name, set_pool):
    """"Choose a player who cast one or more sorcery spells this turn" with no
    such player names nobody, and no damage is dealt — rather than the spell
    falling back to whatever a targetless resolution points at."""
    game, players = _r35_board(set_pool, catalog_by_name, sorceries=0)

    result = game.cast_from_hand(1, "Backdraft")

    assert result.supported, result.details
    assert [p.life for p in players] == [20, 20], game.log


def test_the_player_is_chosen_before_the_spell_is(catalog_by_name, set_pool):
    """Two players cast sorceries, so the first decision is a real one — and the
    second is narrowed by it: the spells offered are the chosen player's alone.

    Casting Backdraft is itself no help to the chooser: it is an instant, so it
    never joins the set its own sentence describes."""
    game, players = _r35_board(set_pool, catalog_by_name, seats=3)
    players[2].hand = [catalog_by_name["Fireball"]]
    game.interactive_seats = {1}
    game.cast_from_hand(0, "Fireball", target_player_index=1, x_value=4)
    game.cast_from_hand(2, "Fireball", target_player_index=1, x_value=8)

    game.cast_from_hand(1, "Backdraft")
    pending = game.pending_choice_of("player_choice")
    assert pending is not None, game.log
    assert pending.data["seats"] == [0, 2], pending.data

    assert game.confirm_player_choice(1, 2) is True
    # One spell each, so the second choice is forced and never prompts.
    assert game.pending_choices == []
    # P2 took both Fireballs (12) on the way here; P3's 8-damage Fireball is
    # the one named, so P3 takes 4.
    assert [p.life for p in players] == [20, 8, 16], game.log

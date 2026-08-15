"""Core Set 2021 (M21) sorceries.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


def test_track_down_still_refuses_its_reveal_clause(set_pool):
    """Scry 3 parses now, but "then reveal the top card of your library" has no
    production — the sentence refuses whole rather than scrying and dropping
    the rest."""
    assert not compile_card_oracle(set_pool("M21")["Track Down"]).supported


# --- The counter round: +1/+1 counters on non-source subjects ---------------


def test_basris_solidarity_counters_each_of_your_creatures(set_pool):
    """"Put a +1/+1 counter on each creature you control." — the sweep counts
    the caster's side only, through the control seam."""
    solidarity = set_pool("M21")["Basri's Solidarity"]
    mine = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    theirs = Permanent(card=set_pool("M21")["Concordia Pegasus"])
    p1 = PlayerState(name="P1", battlefield=[mine], hand=[solidarity])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])

    base_mine = mine.effective_power
    base_theirs = theirs.effective_power
    game.cast_from_hand(0, "Basri's Solidarity")

    assert mine.effective_power == base_mine + 1
    assert theirs.effective_power == base_theirs


def test_see_the_truth_from_hand_keeps_one_and_bottoms_the_rest(set_pool):
    pool = set_pool("M21")
    library = [pool["Shock"], pool["Rewind"], pool["Island"], pool["Concordia Pegasus"]]
    p1 = PlayerState(name="P1", hand=[pool["See the Truth"]], library=list(library))
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(0, "See the Truth")
    assert result.supported, result.details
    # The pick suspends the resolution: the spell is not yet in the graveyard
    # (CR 608.2n) while its controller is looking.
    assert not any(c.name == "See the Truth" for c in p1.graveyard)
    assert game.confirm_look_top_pick(0, 1)
    assert [c.name for c in p1.hand] == ["Rewind"]
    # The other two looked-at cards went under the Pegasus.
    assert [c.name for c in p1.library] == ["Concordia Pegasus", "Shock", "Island"]
    assert any(c.name == "See the Truth" for c in p1.graveyard)


def test_see_the_truth_cast_from_exile_takes_all_three(set_pool):
    """The cast-zone conditional, fed by the permission seam: cast from
    anywhere but the hand, every looked-at card goes to the hand and there is
    no choice at all."""
    from engine.cast_permissions import grant_permission

    pool = set_pool("M21")
    truth = pool["See the Truth"]
    p1 = PlayerState(
        name="P1", exile=[truth],
        library=[pool["Shock"], pool["Rewind"], pool["Island"], pool["Concordia Pegasus"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    grant_permission(
        game, player_index=0, zone="exile", mode="cast",
        cards=[truth], duration="end_of_turn", source_name="Test Grant",
    )
    result = game.cast_from_hand(0, "See the Truth", from_zone="exile")
    assert result.supported, result.details
    assert not game.pending_choices_of("look_top_pick")
    assert sorted(c.name for c in p1.hand) == ["Island", "Rewind", "Shock"]
    assert [c.name for c in p1.library] == ["Concordia Pegasus"]


def test_read_the_tides_second_mode_bounces_both_chosen_creatures(set_pool):
    pool = set_pool("M21")
    bears = [Permanent(card=pool["Concordia Pegasus"]) for _ in range(3)]
    p1 = PlayerState(name="P1", hand=[pool["Read the Tides"]])
    p2 = PlayerState(name="P2", battlefield=list(bears))
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Read the Tides", target_player_index=1,
        target_permanent_index=[0, 2], mode_index=1,
    )
    assert result.supported, result.details
    assert len(p2.battlefield) == 1
    assert len(p2.hand) == 2


def test_pestilent_haze_second_mode_strips_loyalty_from_every_walker(set_pool):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    theirs = Permanent(card=pool["Garruk, Unleashed"], metadata={"loyalty_counters": 2})
    p1 = PlayerState(name="P1", hand=[pool["Pestilent Haze"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(0, "Pestilent Haze", mode_index=1)
    assert result.supported, result.details
    assert mine.metadata["loyalty_counters"] == 1
    # Garruk hit zero and the state-based sweep collected him (CR 704.5i).
    assert not game.is_on_battlefield(theirs)
    assert any(c.name == "Garruk, Unleashed" for c in p2.graveyard)


def test_destructive_tampering_second_mode_grounds_blockers_for_the_turn(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Destructive Tampering"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.cast_from_hand(0, "Destructive Tampering", mode_index=1)
    assert result.supported, result.details
    assert game.blocking_restrictions_until_eot
    # A ground attacker, so blocking legality turns on the restriction alone:
    # the grounded cat may not block, the flyer still may ("without flying"
    # spares it, asked of layer 6).
    attacker = Permanent(card=pool["Pridemalkin"])
    grounded = Permanent(card=pool["Pridemalkin"])
    flyer = Permanent(card=pool["Concordia Pegasus"])
    assert game._can_block_attacker(flyer, attacker) is True
    assert game._can_block_attacker(grounded, attacker) is False
    # CR 514.2: the restriction ends with the turn.
    game.resolve_cleanup_step(0)
    assert not game.blocking_restrictions_until_eot
    assert game._can_block_attacker(grounded, attacker) is True


def test_secure_the_scene_exiles_and_compensates_the_owner(set_pool):
    pool = set_pool("M21")
    theirs = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(name="P1", hand=[pool["Secure the Scene"]])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    result = game.cast_from_hand(
        0, "Secure the Scene", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert any(c.name == "Concordia Pegasus" for c in p2.exile)
    # The Soldier goes to the exiled permanent's controller — the opponent,
    # not the caster.
    assert [p.card.name for p in p2.battlefield] == ["Soldier Token"]
    assert p1.battlefield == []


def test_bad_deal_draws_discards_and_drains_every_life_total(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Bad Deal"]],
        library=[pool["Island"], pool["Swamp"], pool["Swamp"]],
    )
    p2 = PlayerState(name="P2", hand=[pool["Shock"], pool["Island"], pool["Swamp"]])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Bad Deal")
    assert result.supported, result.details
    game.auto_resolve_pending_choices()

    assert len(p1.hand) == 2, "the caster drew two"
    assert len(p2.hand) == 1, "the opponent discarded two of three"
    assert p1.life == 18, "each player includes the caster (CR 120.3)"
    assert p2.life == 18


def test_bad_deal_queues_a_choice_for_an_interactive_opponent(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Bad Deal"]], library=[pool["Island"]] * 3)
    p2 = PlayerState(name="P2", hand=[pool["Shock"], pool["Island"]])
    game = Game(players=[p1, p2])
    game.interactive_seats = {1}

    result = game.cast_from_hand(0, "Bad Deal")
    assert result.supported, result.details
    pending = game.pending_choices_of("discard", 1)
    assert pending and pending[0].data["count"] == 2
    assert game.confirm_discard(1, [0, 1])
    assert len(p2.hand) == 0


def test_crash_through_still_reaches_creatures_only(set_pool):
    """The wider reading is a payload key, not a widening of the old one: the
    lands stay out of a "creatures you control" grant."""
    pool = set_pool("M21")
    land = Permanent(card=pool["Forest"])
    creature = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(
        name="P1", battlefield=[land, creature], hand=[pool["Crash Through"]],
        library=[pool["Forest"]] * 3,
    )
    game = Game(players=[p1, PlayerState(name="P2")])

    result = game.cast_from_hand(0, "Crash Through")
    assert result.supported, result.details
    game._settle()

    assert game._has_keyword(creature, "trample")
    assert not game._has_keyword(land, "trample")

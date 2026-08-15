"""Core Set 2021 (M21) sorceries.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

import pytest

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


# --- One player chooses from another player's hidden zone --------------------


def test_duress_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Duress"])
    assert program.supported, program.reason


def _duress_game(set_pool, victim_hand, interactive=True):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Duress"]], library=[pool["Swamp"]] * 4)
    p2 = PlayerState(name="P2", hand=[pool[name] for name in victim_hand])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    result = game.cast_from_hand(0, "Duress", target_player_index=1)
    assert result.supported, result.details
    game._settle()
    return game, p1, p2


def test_duress_queues_its_choice_on_the_caster_not_the_victim(set_pool):
    """Every other pending choice in the engine is owed by the player it is
    about; this one is not. "**You** choose" is the caster, picking out of
    someone else's hidden zone — the capability this round added."""
    game, _, _ = _duress_game(
        set_pool, ["Alpine Watchdog", "Shock", "Island", "Volcanic Salvo"]
    )

    choice = game.pending_choices_of("revealed_hand_pick")[0]
    assert choice.player_index == 0, "the caster chooses"
    assert choice.data["victim_index"] == 1
    assert choice.data["legal_indices"] == [1, 3], "the two noncreature, nonland cards"


def test_duress_refuses_a_card_its_filter_excludes(set_pool):
    """The legal indices are re-checked against the record armed with the
    choice, never trusted from the wire — a client offering the whole hand would
    otherwise turn "a noncreature, nonland card" into "any card"."""
    game, _, p2 = _duress_game(
        set_pool, ["Alpine Watchdog", "Shock", "Island", "Volcanic Salvo"]
    )

    assert not game.confirm_revealed_hand_pick(0, 0), "a creature card"
    assert not game.confirm_revealed_hand_pick(0, 2), "a land card"
    assert p2.graveyard == [], "a rejected answer discards nothing"
    assert game.pending_choices_of("revealed_hand_pick"), "and leaves the prompt owed"

    assert game.confirm_revealed_hand_pick(0, 1)
    assert [c.name for c in p2.graveyard] == ["Shock"]
    assert [c.name for c in p2.hand] == ["Alpine Watchdog", "Island", "Volcanic Salvo"]


def test_duress_with_nothing_legal_to_take_queues_nothing(set_pool):
    """A choice with no legal answer is not a choice — leaving it queued would
    block the caster on a prompt they cannot satisfy."""
    game, _, p2 = _duress_game(set_pool, ["Alpine Watchdog", "Island"])

    assert game.pending_choices_of("revealed_hand_pick") == []
    assert p2.graveyard == []
    assert any("no card in that hand can be chosen" in line for line in game.log)


def test_a_non_interactive_caster_takes_the_costliest_legal_card(set_pool):
    """A stated policy, like the up-to-N maximum and the modal first mode: mana
    value is the one ranking every card in the pool answers."""
    game, _, p2 = _duress_game(
        set_pool, ["Shock", "Volcanic Salvo", "Island"], interactive=False
    )
    game.auto_resolve_pending_choices()

    assert [c.name for c in p2.graveyard] == ["Volcanic Salvo"]
    assert game.pending_choices == []


# --- The fused pair: target 1 is prepared, then acts on target 2 -------------


@pytest.mark.parametrize("name", ["Primal Might", "Hunter's Edge"])
def test_round_41_fused_pair_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def _fused_pair_game(set_pool, spell, x_value=None):
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])       # 2/2
    theirs = Permanent(card=pool["Concordia Pegasus"])   # 1/3
    p1 = PlayerState(
        name="P1", battlefield=[mine], hand=[pool[spell]], library=[pool["Forest"]] * 4
    )
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    result = game.queue_from_hand(
        0, spell,
        target_player_index=0, target_permanent_index=[0, 0],
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
        x_value=x_value,
    )
    assert result.supported, result.details
    game._settle()
    return game, mine, theirs


def test_primal_might_pumps_its_own_creature_then_fights(set_pool):
    """The two sentences are one instruction because the second one's subject
    *is* the first one's target. Lowered as two steps the card pumped whichever
    creature its single picker offered — the opponent's — and fought nobody."""
    game, mine, theirs = _fused_pair_game(set_pool, "Primal Might", x_value=2)

    assert (mine.effective_power, mine.effective_toughness) == (4, 4), "+X/+X first"
    assert theirs.damage_marked == 4, "and the pumped power is what it fights with"
    assert mine.damage_marked == 1, "a fight is mutual (CR 701.14a)"
    assert not game.is_on_battlefield(theirs)


def test_hunters_edge_is_the_one_way_half_of_the_same_shape(set_pool):
    """"…deals damage equal to its power to target creature you don't control"
    is a bite, not a fight: the counter goes on first, and only one side deals."""
    game, mine, theirs = _fused_pair_game(set_pool, "Hunter's Edge")

    assert mine.metadata["plus_counters"] == 1
    assert (mine.effective_power, mine.effective_toughness) == (3, 3)
    assert theirs.damage_marked == 3
    assert mine.damage_marked == 0, "one-way"
    assert not game.is_on_battlefield(theirs)


def test_the_preparation_happens_even_when_the_second_slot_names_nobody(set_pool):
    """"Up to one target creature you don't control" may legally name none
    (CR 601.2c), and the pump is not conditional on the fight."""
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(
        name="P1", battlefield=[mine], hand=[pool["Primal Might"]],
        library=[pool["Forest"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.queue_from_hand(
        0, "Primal Might", target_player_index=0, target_permanent_index=[0],
        target_permanent_ids=[mine.permanent_id], x_value=3,
    )
    game._settle()

    assert (mine.effective_power, mine.effective_toughness) == (5, 5)
    assert mine.damage_marked == 0


def test_the_second_slot_refuses_a_creature_its_own_filter_excludes(set_pool):
    """Per-slot filters are enforced at resolution, not only in the picker:
    "target creature you **don't** control" cannot be answered with one of the
    caster's own."""
    pool = set_pool("M21")
    mine = Permanent(card=pool["Alpine Watchdog"])
    also_mine = Permanent(card=pool["Concordia Pegasus"])
    p1 = PlayerState(
        name="P1", battlefield=[mine, also_mine], hand=[pool["Hunter's Edge"]],
        library=[pool["Forest"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    game.queue_from_hand(
        0, "Hunter's Edge", target_player_index=0, target_permanent_index=[0, 1],
        target_permanent_ids=[mine.permanent_id, also_mine.permanent_id],
    )
    game._settle()

    assert mine.metadata["plus_counters"] == 1, "the counter still lands"
    assert also_mine.damage_marked == 0, "but nothing is bitten"

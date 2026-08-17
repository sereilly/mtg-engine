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
from engine.grammar import compile_line
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


def test_track_down_composes_a_scry_a_reveal_and_a_conditional_draw(set_pool):
    """Three sentences, three instructions, composed rather than fused.

    The pool already had a *whole-template* reveal production — Garruk, Savage
    Herald's "reveal … put it into your hand … Otherwise, put it on the bottom"
    — whose docstring says every word of both destinations is the effect. Track
    Down's reveal is the opposite decomposition: the reveal records what it
    showed, and what follows is an ordinary conditional. Generalising Garruk's
    node would have made its own docstring untrue of half its cases, so this is a
    sibling node and the two templates stay honest.
    """
    program = compile_card_oracle(set_pool("M21")["Track Down"])

    assert program.supported, program.reason
    (sequence, *_rest) = program.instructions
    scry, reveal, branch = sequence.payload["steps"]
    assert (scry.kind, scry.payload["amount"]) == ("scry", 3)
    assert reveal.kind == "reveal_top_of_library"
    assert branch.payload["condition"] == {
        "kind": "revealed_card_is",
        "card_types": ["creature", "land"],
        "type_match": "any",
    }
    (drawn,) = branch.payload["then"]
    assert drawn.kind == "draw_controller_cards"


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


# --- The several-cards round: "up to two target" cards in a graveyard --------
#
# Sanguine Indulgence is the first card naming more than one target *card*.
# Every earlier "up to N" names permanents, which carry a `permanent_id`; a card
# in a graveyard has only a slot, so these pin what that slot is allowed to mean.


def _indulgence_game(set_pool, graveyard, *, life_gained=0, enforce=False, **mana):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Sanguine Indulgence"]],
        graveyard=[pool[n] for n in graveyard],
        library=[pool["Swamp"]] * 6,
    )
    p1.life_gained_this_turn = life_gained
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = enforce
    game.active_player_index = 0
    if enforce:
        p1.mana_pool = {sym: mana.get(sym, 0) for sym in ("W", "U", "B", "R", "G", "C")}
    return game, p1


def test_sanguine_indulgence_returns_both_cards_its_two_slots_named(set_pool):
    """The card the round buys. Two slots, two cards, and the card the caster
    did not name stays where it is."""
    game, p1 = _indulgence_game(
        set_pool, ["Alpine Watchdog", "Shock", "Garruk's Warsteed"]
    )

    result = game.cast_from_hand(
        0, "Sanguine Indulgence", target_player_index=0, target_permanent_index=[0, 2],
    )

    assert result.supported, result.details
    assert sorted(c.name for c in p1.hand) == ["Alpine Watchdog", "Garruk's Warsteed"]
    assert [c.name for c in p1.graveyard] == ["Shock", "Sanguine Indulgence"]


def test_sanguine_indulgence_reads_its_slots_before_anything_leaves_the_zone(set_pool):
    """Two *adjacent* slots, which is where a graveyard index stops being an
    identity: removing slot 0 slides every later card down one, so a handler
    removing in the order it was handed would take slot 1's neighbour instead.
    Slot 1 is Garruk's Warsteed, and Concordia Pegasus has to survive."""
    game, p1 = _indulgence_game(
        set_pool, ["Alpine Watchdog", "Garruk's Warsteed", "Concordia Pegasus"]
    )

    result = game.cast_from_hand(
        0, "Sanguine Indulgence", target_player_index=0, target_permanent_index=[0, 1],
    )

    assert result.supported, result.details
    assert sorted(c.name for c in p1.hand) == ["Alpine Watchdog", "Garruk's Warsteed"]
    assert [c.name for c in p1.graveyard] == ["Concordia Pegasus", "Sanguine Indulgence"]


def test_sanguine_indulgence_may_name_only_one(set_pool):
    """"Up to two" is a maximum, not a requirement (CR 601.2c) — one named slot
    returns one card and the spell still resolves."""
    game, p1 = _indulgence_game(set_pool, ["Shock", "Alpine Watchdog"])

    result = game.cast_from_hand(
        0, "Sanguine Indulgence", target_player_index=0, target_permanent_index=[1],
    )

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == ["Alpine Watchdog"]
    assert [c.name for c in p1.graveyard] == ["Shock", "Sanguine Indulgence"]


def test_sanguine_indulgence_is_castable_with_an_empty_graveyard(set_pool):
    """Naming zero targets is a legal announcement, so an empty graveyard is not
    a reason to refuse the cast the way it is for a spell requiring its one
    target."""
    game, p1 = _indulgence_game(set_pool, [])

    result = game.cast_from_hand(0, "Sanguine Indulgence", target_player_index=0)

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == []
    assert [c.name for c in p1.graveyard] == ["Sanguine Indulgence"]


def test_sanguine_indulgence_refuses_a_slot_that_is_not_a_creature_card(set_pool):
    """The picker's list is a hint and the cast re-checks it: a named slot
    holding an instant is refused by name rather than quietly skipped."""
    game, p1 = _indulgence_game(set_pool, ["Shock", "Alpine Watchdog"])

    result = game.cast_from_hand(
        0, "Sanguine Indulgence", target_player_index=0, target_permanent_index=[0, 1],
    )

    assert not result.supported
    assert result.details == "no valid target for Sanguine Indulgence"
    assert any(c.name == "Sanguine Indulgence" for c in p1.hand), "the spell was not cast"


def test_sanguine_indulgence_returns_one_card_for_a_repeated_slot(set_pool):
    """CR 601.2c: one instance of "target" cannot name the same object twice, so
    a doubled index is one choice however it arrives."""
    game, p1 = _indulgence_game(set_pool, ["Alpine Watchdog", "Garruk's Warsteed"])

    result = game.cast_from_hand(
        0, "Sanguine Indulgence", target_player_index=0, target_permanent_index=[0, 0],
    )

    assert result.supported, result.details
    assert [c.name for c in p1.hand] == ["Alpine Watchdog"]


def test_sanguine_indulgence_costs_three_less_after_three_life_gained(set_pool):
    """{3}{B} less {3} is {B} — one black mana casts it. The condition is
    computed from the caster's own life-gain record, so the discount is charged
    rather than assumed."""
    game, _ = _indulgence_game(set_pool, ["Alpine Watchdog"], enforce=True, B=1)
    assert not game.queue_from_hand(
        0, "Sanguine Indulgence", target_player_index=0
    ).supported

    discounted, _ = _indulgence_game(
        set_pool, ["Alpine Watchdog"], life_gained=3, enforce=True, B=1
    )
    assert discounted.queue_from_hand(
        0, "Sanguine Indulgence", target_player_index=0
    ).supported


def test_sanguine_indulgence_charges_full_price_below_three_life_gained(set_pool):
    """Two life gained is not three. The reduction is conditional, and reading
    an unmet condition as met is the one direction a cost error must never
    go — so the same board pays four mana here and one above."""
    full, player = _indulgence_game(
        set_pool, ["Alpine Watchdog"], life_gained=2, enforce=True, B=1, C=3
    )
    assert full.queue_from_hand(0, "Sanguine Indulgence", target_player_index=0).supported
    assert sum(player.mana_pool.values()) == 0

    discounted, discounted_player = _indulgence_game(
        set_pool, ["Alpine Watchdog"], life_gained=3, enforce=True, B=1, C=3
    )
    assert discounted.queue_from_hand(
        0, "Sanguine Indulgence", target_player_index=0
    ).supported
    assert sum(discounted_player.mana_pool.values()) == 3


def test_the_picker_offers_two_slots_of_the_casters_own_graveyard(set_pool):
    """What the client reads: the maximum it has to collect, and a legal-target
    list holding only creature cards in the caster's own graveyard."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Sanguine Indulgence"]],
        graveyard=[pool["Alpine Watchdog"], pool["Shock"], pool["Garruk's Warsteed"]],
    )
    p2 = PlayerState(name="P2", graveyard=[pool["Concordia Pegasus"]])
    game = Game(players=[p1, p2])

    spec = game.cast_target_spec(0, pool["Sanguine Indulgence"])

    assert spec["kind"] == "graveyard_creature"
    assert spec["max_targets"] == 2
    assert spec["own_graveyard_only"] is True
    assert [(t["seat"], t["index"], t["name"]) for t in spec["valid_targets"]] == [
        (0, 0, "Alpine Watchdog"),
        (0, 2, "Garruk's Warsteed"),
    ]


def test_the_ai_takes_the_maximum_out_of_its_own_graveyard(set_pool):
    """The stated policy for "up to N" (ROADMAP idiom #8), reached through the
    graveyard enumeration rather than the battlefield one — the AI's slot
    collector skipped every non-permanent entry until this card."""
    from engine.ai_policy import choose_cast_action

    game, _ = _indulgence_game(
        set_pool, ["Alpine Watchdog", "Shock", "Garruk's Warsteed"]
    )

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Sanguine Indulgence"
    assert action.target_player_index == 0
    assert action.target_permanent_index == [0, 2]


def test_rise_again_still_reanimates_exactly_one(set_pool):
    """Negative control: the destination is what picks the handler, so the
    several-cards branch must not reach the graveyard→battlefield one."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Rise Again"]],
        graveyard=[pool["Alpine Watchdog"], pool["Garruk's Warsteed"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])

    program = compile_card_oracle(pool["Rise Again"])
    assert [(i.kind, i.payload) for i in program.instructions][0] == (
        "reanimate_creature", {},
    )

    result = game.cast_from_hand(
        0, "Rise Again", target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert [p.card.name for p in game.controlled_by(0)] == ["Garruk's Warsteed"]
    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog", "Rise Again"]


# --- Round 80: a reveal that records, and the sentence that reads it --------


def _track_down_game(set_pool, top_name):
    """Track Down cast with *top_name* on top and the scry answered to keep it
    there, so what the reveal sees is what the test named."""
    pool = set_pool("M21")
    library = [pool[top_name], pool["Shock"], pool["Shock"]] + [pool["Shock"]] * 4
    p1 = PlayerState(name="P1", hand=[pool["Track Down"]], library=library)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Track Down")
    assert game.confirm_scry(0, card_order=[0, 1, 2], bottom_count=0) is True
    game._settle()
    return game, p1


def test_track_down_draws_when_the_revealed_card_is_a_creature(set_pool):
    game, player = _track_down_game(set_pool, "Alpine Watchdog")

    assert [c.name for c in player.hand] == ["Alpine Watchdog"]


def test_track_down_draws_when_the_revealed_card_is_a_land(set_pool):
    """"a creature **or** land card" is a union, so either type answers it."""
    game, player = _track_down_game(set_pool, "Island")

    assert [c.name for c in player.hand] == ["Island"]


def test_track_down_draws_nothing_for_any_other_card(set_pool):
    """The control. The reveal still happened â€” revealing moves nothing
    (CR 701.15) â€” so the card is still on top and the hand is empty."""
    game, player = _track_down_game(set_pool, "Shock")

    assert player.hand == []
    assert player.library[0].name == "Shock", "revealing does not move the card"
    assert any("revealed Shock" in line for line in game.log)


def test_the_condition_reads_the_revealed_card_and_not_the_library(set_pool):
    """Why the reveal records rather than the branch re-reading.

    The branch's own draw changes what is on top, and a re-read would then be
    asking about whichever card the draw uncovered. Here the revealed creature
    is drawn and a *non*-matching card sits underneath it: a re-reading engine
    would still be right by luck, so the assertion is that the drawn card is the
    one that was revealed."""
    game, player = _track_down_game(set_pool, "Alpine Watchdog")

    assert [c.name for c in player.hand] == ["Alpine Watchdog"]
    assert player.library[0].name == "Shock"


def test_the_conditional_refuses_with_no_reveal_before_it():
    """A back-reference names its producer or refuses (idiom #7): with nothing
    revealed there is no card for "it" to name, and the branch would answer
    False forever while the card compiled clean."""
    result = compile_line("If it's a creature card, draw a card.", card_name="Test")

    assert not result.usable


def test_the_present_tense_does_not_claim_a_state_test():
    """"as long as **it's** untapped" (Giant Tortoise) opens with the same two
    words and is not a card test. The revealed-card branch takes a sentence only
    when a noun phrase naming card types follows, and hands it back otherwise."""
    tortoise = compile_line(
        "This creature gets +0/+3 as long as it's untapped.", card_name="Test"
    )

    assert tortoise.parsed, tortoise.parse_error

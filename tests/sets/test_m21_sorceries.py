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


# --- Round 83: two computed halves, and a subject printed once --------------


def _peer_game(set_pool, *, library, life):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Peer into the Abyss"]])
    p2 = PlayerState(name="P2", library=[pool["Shock"]] * library, life=life)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Peer into the Abyss", target_player_index=1)
    game._settle()
    return p2


def test_peer_into_the_abyss_compiles_to_two_computed_halves(set_pool):
    """Two numbers the resolution computes, each travelling on the same spec a
    plain count does â€” one with a zone to read, one with a name, and the halving
    recorded on both rather than becoming a second amount vocabulary."""
    program = compile_card_oracle(set_pool("M21")["Peer into the Abyss"])

    assert program.supported, program.reason
    (sequence,) = [i for i in program.instructions if i.kind == "sequence"]
    draw, lose = sequence.payload["steps"]
    assert draw.payload["x_from_count"] == {
        "zone": "library", "owner": "owner", "filter": {}, "half": "up",
    }
    assert lose.payload["x_from_count"] == {
        "board_count": "their_life", "owner": "target", "half": "up",
    }


def test_peer_into_the_abyss_rounds_both_halves_up(set_pool):
    """"Round up **each time**" â€” per calculation, not once over the sentence.
    An odd library and an odd life total in the same cast is what tells the two
    readings apart."""
    victim = _peer_game(set_pool, library=7, life=21)

    assert len(victim.hand) == 4, "ceil(7/2)"
    assert victim.life == 21 - 11, "ceil(21/2) lost"


def test_peer_into_the_abyss_halves_an_even_library(set_pool):
    victim = _peer_game(set_pool, library=6, life=20)

    assert len(victim.hand) == 3
    assert victim.life == 10


def test_the_life_loss_does_not_read_a_library_the_draw_shrank(set_pool):
    """The two halves read different things â€” a zone and a life total â€” so the
    draw cannot change what the loss computes. Pinned because the obvious
    mis-implementation is to route both through one count."""
    victim = _peer_game(set_pool, library=7, life=20)

    assert len(victim.library) == 3, "4 of 7 drawn"
    assert victim.life == 10, "half of 20, not half of what was left"


def test_a_printed_player_subject_carries_across_and():
    """"Target player draws a card **and loses 1 life**." The subject is printed
    once and meant twice. Bare imperatives already worked ("You gain 1 life and
    draw a card") because their subject is implied by the verb; this is the
    printed half of the same shape."""
    result = compile_line("Target player draws a card and loses 1 life.", card_name="T")

    assert [i.kind for i in result.instructions] == [
        "draw_target_cards", "target_loses_life",
    ]


def test_only_a_player_subject_carries():
    """The narrowing that keeps the carry honest. "gains", "loses" and "wins"
    substitute "you" for a non-player subject rather than refusing, so carrying a
    *creature* into one would read a sentence nobody printed â€” here, a creature's
    controller winning the game."""
    result = compile_line(
        "Target creature gets +3/+3 until end of turn and wins the game.",
        card_name="T",
    )

    assert not result.parsed


def test_a_tail_that_names_its_own_subject_is_not_given_the_carried_one():
    """Rookie Mistake's second clause names a *different* creature, and the
    carried subject must not be read over it â€” the fuser claims that sentence,
    and it still does."""
    result = compile_line(
        "Until end of turn, target creature gets +0/+2 and another target "
        "creature gets -2/-0.",
        card_name="T",
    )

    assert [i.kind for i in result.instructions] == ["pump_targets_until_eot"]


def test_round_up_each_time_needs_something_to_round():
    """The rider changes how a computed value is rounded, so a sentence with no
    half in it is a wording this does not read â€” refused rather than consumed
    and ignored."""
    result = compile_line("Target player draws a card. Round up each time.", card_name="T")

    assert not result.parsed


# --- Round 96: a sweep over what something is attached to -------------------


def _slag_board(set_pool, attached=("Short Sword", "Malefic Scythe"), loose=("Short Sword",)):
    pool = set_pool("M21")
    victim = Permanent(card=pool["Warden of the Woods"])
    bystander = Permanent(card=pool["Gale Swooper"])
    worn = [Permanent(card=pool[name]) for name in attached]
    for equipment in worn:
        equipment.metadata["attached_to"] = victim
    p1 = PlayerState(
        name="P1",
        hand=[pool["Turn to Slag"]],
        battlefield=[Permanent(card=pool[name]) for name in loose],
    )
    p2 = PlayerState(name="P2", battlefield=[victim, bystander] + worn)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, victim, worn, bystander


def test_turn_to_slag_compiles_supported(set_pool):
    """A sweep over a *narrowed* set rather than a card type, so it carries the
    filter instead of naming a per-scope handler. The attachment rides beside
    the filter rather than in it: what an Equipment is attached to is a
    relation, and ``permanent_matches_filter`` answers about a permanent
    alone."""
    program = compile_card_oracle(set_pool("M21")["Turn to Slag"])
    assert program.supported, program.reason

    sweep = next(
        i for i in program.instructions[0].payload["steps"]
        if i.kind == "destroy_all_matching"
    ) if program.instructions[0].kind == "sequence" else program.instructions[1]
    assert sweep.payload["subtype_filter"] == "equipment"
    assert sweep.payload["attached_to"] == "target"


def test_it_damages_the_creature_and_slags_its_equipment(set_pool):
    game, _p1, _p2, victim, worn, _bystander = _slag_board(set_pool)

    result = game.cast_from_hand(
        0, "Turn to Slag", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()

    assert victim.damage_marked == 5
    assert all(not game.is_on_battlefield(equipment) for equipment in worn)


def test_equipment_attached_to_nothing_survives(set_pool):
    """"Attached to **that creature**" is read, not decoration."""
    game, p1, _p2, _victim, _worn, _bystander = _slag_board(set_pool)
    (loose,) = list(game.controlled_by(0))

    game.cast_from_hand(0, "Turn to Slag", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert game.is_on_battlefield(loose)


def test_the_sweep_takes_nothing_else_on_the_board(set_pool):
    game, _p1, _p2, _victim, _worn, bystander = _slag_board(set_pool)

    game.cast_from_hand(0, "Turn to Slag", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert game.is_on_battlefield(bystander)


def test_a_creature_dying_to_the_damage_still_loses_its_equipment(set_pool):
    """CR 704.3: state-based actions are checked only when a player would
    receive priority, so the lethally damaged creature is **still on the
    battlefield** while the rest of this spell resolves — and its Equipment is
    still attached. Both die, in that order. This is the case worth pinning,
    because "the creature is gone" is the intuitive reading and it is wrong."""
    pool = set_pool("M21")
    victim = Permanent(card=pool["Gale Swooper"])   # 3/2, dies to 5
    sword = Permanent(card=pool["Short Sword"])
    sword.metadata["attached_to"] = victim
    p1 = PlayerState(name="P1", hand=[pool["Turn to Slag"]])
    p2 = PlayerState(name="P2", battlefield=[victim, sword])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Turn to Slag", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert not game.is_on_battlefield(victim)
    assert not game.is_on_battlefield(sword)


# --- Round 98: a control change with a lifetime of its own ------------------


def _greed_board(set_pool, tapped=True):
    pool = set_pool("M21")
    victim = Permanent(card=pool["Gale Swooper"], tapped=tapped)
    p1 = PlayerState(name="P1", hand=[pool["Traitorous Greed"]])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, victim


def _cast_greed(game, colour="R"):
    return game.cast_from_hand(
        0, "Traitorous Greed",
        target_player_index=1, target_permanent_index=0, new_color=colour,
    )


def test_traitorous_greed_compiles_supported(set_pool):
    """Four sentences, and every one of them needed something. The control
    change is a *lifetime* rather than a link — the sorcery that granted it is
    in a graveyard before the turn ends, so there is no permanent to watch and
    CR 611.2c ends it at cleanup instead."""
    program = compile_card_oracle(set_pool("M21")["Traitorous Greed"])
    assert program.supported, program.reason


def test_it_takes_untaps_hastes_and_pays(set_pool):
    game, p1, victim = _greed_board(set_pool)

    result = _cast_greed(game)
    assert result.supported, result.details
    game._settle()

    assert game.controller_index_of(victim) == 0
    assert not victim.tapped
    assert game._has_keyword(victim, "haste")
    assert p1.mana_pool["R"] == 2


def test_the_pronoun_sentences_follow_the_creature_across_battlefields(set_pool):
    """"Untap **that creature**" is the same creature one sentence later — and
    it is on a different battlefield by then. A target is scoped to the seat it
    was chosen from, so a stale id cannot resolve to a permanent that changed
    hands; this effect is what changed those hands, one step ago, so the scope
    moves with it rather than being widened."""
    game, _p1, victim = _greed_board(set_pool)

    _cast_greed(game)
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Gale Swooper"]
    assert not victim.tapped, "the untap found it on its new battlefield"


def test_control_reverts_at_cleanup_without_moving_anything(set_pool):
    """Dropping the contribution *is* the reversion: the permanent never moved,
    so whatever contributions remain simply decide again.
    ``base_controller`` is untouched throughout, which is what makes the
    reversion correct and CR 108.3 ownership still read off the original seat."""
    from engine.control import base_controller

    game, _p1, victim = _greed_board(set_pool)
    _cast_greed(game)
    game._settle()
    assert base_controller(victim) == 1

    game.resolve_cleanup_step(0)

    assert game.controller_index_of(victim) == 1
    assert [p.card.name for p in game.controlled_by(1)] == ["Gale Swooper"]


def test_an_untimed_control_change_still_refuses(set_pool):
    """The duration is required, and required to be one the engine ends. An
    untimed steal is a permanent control change and reverts under completely
    different circumstances."""
    from engine.grammar import compile_line

    result = compile_line("Gain control of target creature.")

    assert not result.parsed


# --- Round 99: a search that finds twice and splits its finds ---------------


def _cultivate_board(set_pool, library=("Forest", "Shock", "Island", "Mountain")):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Cultivate"]],
        library=[pool[name] for name in library],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Cultivate")
    game._settle()
    return game, p1


def test_cultivate_compiles_supported(set_pool):
    """Two finds and two destinations are the *same fact*, so they travel
    together: a card that names two destinations cannot lower to a search that
    finds one."""
    program = compile_card_oracle(set_pool("M21")["Cultivate"])
    assert program.supported, program.reason

    (search,) = program.instructions
    assert search.payload["count"] == 2
    assert search.payload["destinations"] == ["battlefield", "hand"]
    assert search.payload["tapped"] == [True, False]
    assert search.payload["restrictions"]["supertypes"] == ["basic"]


def test_the_first_find_enters_tapped_and_the_second_goes_to_hand(set_pool):
    """The prompt is answered once per find and consumes the front of the
    destination list, so the second find cannot land where the first was meant
    to."""
    game, p1 = _cultivate_board(set_pool)

    assert game.confirm_search_library(0, 0)          # Forest
    library = [c.name for c in p1.library]
    assert game.confirm_search_library(0, library.index("Island"))

    assert [(p.card.name, p.tapped) for p in game.controlled_by(0)] == [("Forest", True)]
    assert [c.name for c in p1.hand] == ["Island"]
    assert game.pending_choices == []


def test_the_library_is_not_shuffled_between_the_two_finds(set_pool):
    """CR 701.19d shuffles when the *search* is over. Shuffling between two
    finds of one search would hide the second from the player still looking."""
    game, p1 = _cultivate_board(set_pool)
    before = [c.name for c in p1.library]

    game.confirm_search_library(0, 0)

    assert [c.name for c in p1.library] == [n for n in before if n != "Forest"]
    assert game.pending_choices, "the second find is still owed"


def test_a_nonbasic_card_is_not_a_legal_find(set_pool):
    """"A **basic** land card" — a supertype is printed on the type line, which
    is the whole test for what the picker may honour: a card in a library has no
    computed characteristics at all (CR 613.1)."""
    game, p1 = _cultivate_board(set_pool)
    shock = [c.name for c in p1.library].index("Shock")

    assert not game.confirm_search_library(0, shock)
    assert [c.name for c in p1.hand] == []


def test_finding_fewer_is_a_legal_answer(set_pool):
    """"Up to two" — and CR 701.19b makes fail-to-find legal regardless. The
    decline ends the whole search rather than one find of it, which is the
    player stating they are done."""
    game, p1 = _cultivate_board(set_pool)

    assert game.confirm_search_library(0, 0)
    assert game.decline_search_library(0)

    assert [(p.card.name, p.tapped) for p in game.controlled_by(0)] == [("Forest", True)]
    assert p1.hand == []
    assert game.pending_choices == []


def test_a_single_find_search_is_unchanged(set_pool):
    """The counted shape is additive: a search that names one destination keeps
    the payload — and the flow — it has always had. No "reveal" key either:
    Demonic Tutor's shape prints no reveal, so the flow shows nothing."""
    from engine.grammar import compile_line

    (search,) = compile_line(
        "Search your library for a card, put that card into your hand, then shuffle."
    ).instructions

    assert search.payload == {"count": 1, "card_type": "any"}


# --- The printed reveal: shown to every player as a structured event ---------


def test_cultivate_reveals_both_finds_as_one_event(set_pool):
    """"…**reveal those cards**…" (CR 701.20): the finds are shown to every
    player. One event for the whole search — "those cards" is one showing —
    recorded when the search ends, so the UI floats both faces together."""
    game, p1 = _cultivate_board(set_pool)

    assert game.confirm_search_library(0, 0)          # Forest
    assert game.reveal_events == [], "the showing is the search's, not one find's"
    library = [c.name for c in p1.library]
    assert game.confirm_search_library(0, library.index("Island"))

    (event,) = game.reveal_events
    assert event["seat"] == 0
    assert event["cards"] == ["Forest", "Island"]
    assert "P1 revealed Forest, Island" in game.log


def test_a_declined_search_still_reveals_what_it_found(set_pool):
    """Declining ends the search (CR 701.19b), but a find already made was
    already shown — backing out of the second find cannot unshow the first."""
    game, _p1 = _cultivate_board(set_pool)

    assert game.confirm_search_library(0, 0)
    assert game.decline_search_library(0)

    (event,) = game.reveal_events
    assert event["cards"] == ["Forest"]


def test_a_singular_printed_reveal_carries_the_same_flag(set_pool):
    """"…, reveal it, …" is the one-find spelling of the same word, and lowers
    to the same payload key the two-card search carries."""
    (search,) = compile_line(
        "Search your library for a basic land card, reveal it, put it into "
        "your hand, then shuffle."
    ).instructions

    assert search.payload["reveal"] is True


# --- Transmogrify: reveal until, as one procedure (round 117) ---------------


def _transmogrify_board(set_pool, library):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Transmogrify"]], life=20)
    p2 = PlayerState(name="P2", life=20, library=[pool[n] for n in library])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, Permanent(card=pool["Alpine Watchdog"]), None)
    return game, p1, p2


def _transmogrify(game):
    result = game.cast_from_hand(
        0, "Transmogrify", target_player_index=1, target_permanent_index=0,
    )
    game._settle()
    return result


def test_transmogrify_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Transmogrify"])
    assert program.supported, program.reason


def test_transmogrify_exiles_and_replaces_from_the_library(set_pool):
    """Three sentences, one procedure: "that card" is what the reveal stopped
    on and "the rest" is exactly what it turned over first."""
    game, _, p2 = _transmogrify_board(
        set_pool, ["Mountain", "Mountain", "Baneslayer Angel", "Mountain"],
    )

    assert _transmogrify(game).supported

    assert [c.name for c in p2.exile] == ["Alpine Watchdog"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Baneslayer Angel"]
    # Four cards in, one onto the battlefield, three shuffled back.
    assert len(p2.library) == 3


def test_transmogrify_reveals_the_card_it_stopped_on(set_pool):
    """The card the reveal stopped on was shown to every player (CR 701.20a),
    so it lands in the reveal-event feed under the *revealing* seat — the
    exiled creature's controller, not the caster."""
    game, _, _p2 = _transmogrify_board(
        set_pool, ["Mountain", "Baneslayer Angel", "Mountain"],
    )

    assert _transmogrify(game).supported

    (event,) = game.reveal_events
    assert event["seat"] == 1
    assert event["cards"] == ["Baneslayer Angel"]


def test_transmogrify_on_a_library_with_no_creature_finds_nothing(set_pool):
    """CR 701.20a's reveal is bounded by the library, so an empty one ends the
    search — anything else is an infinite loop on a real board. The player
    reveals everything, puts nothing into play, and shuffles it all back."""
    game, _, p2 = _transmogrify_board(set_pool, ["Mountain", "Mountain", "Mountain"])

    assert _transmogrify(game).supported

    assert [c.name for c in p2.exile] == ["Alpine Watchdog"]
    assert list(game.controlled_by(1)) == []
    assert len(p2.library) == 3


def test_the_replacement_reaches_the_exiled_creatures_controller(set_pool):
    """"That creature's controller" is the seat the *exile* step recorded, not
    the caster. The lowering demands that producer, because without it the
    effect would read the caster's library — the opposite player from the one
    the card names."""
    from engine.grammar import compile_line

    compiled = compile_line(
        "Exile target creature. That creature's controller reveals cards from "
        "the top of their library until they reveal a creature card. That "
        "player puts that card onto the battlefield, then shuffles the rest "
        "into their library."
    )
    kinds = [i.kind for i in compiled.instructions]

    assert kinds == ["exile_target_permanent", "reveal_until_match"]
    assert compiled.instructions[1].payload["whose"] == "exiled_permanent_controller"

    # Without the exile in front of it the back-reference names nobody.
    orphan = compile_line(
        "That creature's controller reveals cards from the top of their library "
        "until they reveal a creature card. That player puts that card onto the "
        "battlefield, then shuffles the rest into their library."
    )
    assert orphan.instructions == ()


# --- Experimental Overload: an X/X token and a spell exiling itself (118) ---


def _overload_board(set_pool, graveyard):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", life=20, hand=[pool["Experimental Overload"]],
        graveyard=[pool[n] for n in graveyard],
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    return game, p1


def test_experimental_overload_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Experimental Overload"])
    assert program.supported, program.reason


def test_the_weird_is_as_big_as_the_graveyard(set_pool):
    """The P/T is a count taken at resolution (CR 608.2) and then fixed onto the
    token's card — a token has no characteristic-defining ability, so a card
    later leaving the graveyard does not shrink it."""
    game, p1 = _overload_board(set_pool, ["Shock", "Transmogrify", "Mountain"])

    game.cast_from_hand(0, "Experimental Overload")
    game._settle()

    tokens = [p for p in game.controlled_by(0) if p.metadata.get("is_token")]
    assert [(t.card.name, t.effective_power, t.effective_toughness) for t in tokens] == [
        ("Weird Token", 2, 2)
    ]
    # The Mountain is not an instant or a sorcery, and Experimental Overload
    # itself is still resolving — CR 608.2n bins it last.
    assert len(p1.graveyard) == 3


def test_a_spell_can_exile_itself_as_it_resolves(set_pool):
    """"Exile Experimental Overload." There is no permanent — the object is the
    spell on the stack — so this is CR 608.2n's "where the card goes" and it
    routes through the same flag the "exile it instead" rider uses."""
    game, p1 = _overload_board(set_pool, ["Shock", "Transmogrify"])

    game.cast_from_hand(0, "Experimental Overload")
    game._settle()

    assert [c.name for c in p1.exile] == ["Experimental Overload"]
    assert "Experimental Overload" not in [c.name for c in p1.graveyard]


def test_the_optional_return_takes_a_card_from_your_own_graveyard(set_pool):
    """Chosen but not targeted (CR 115.1): the card is in the chooser's own
    graveyard, so nothing targeting protects — no shroud, no protection, no
    "changes target" effect reaches it — and the picker is the one the targeted
    spelling already uses."""
    game, p1 = _overload_board(set_pool, ["Shock", "Transmogrify"])

    game.cast_from_hand(0, "Experimental Overload")
    game._settle()
    assert p1.hand == []

    assert game.confirm_optional_pay(0, accept=True)
    game._settle()

    assert [c.name for c in p1.hand] == ["Shock"]
    assert [c.name for c in p1.graveyard] == ["Transmogrify"]


def test_an_empty_graveyard_makes_a_zero_zero_that_dies(set_pool):
    """X is 0, so the token is a 0/0 and state-based actions bin it at once
    (CR 704.5a). The token really was created — it is not that the effect was
    skipped."""
    game, p1 = _overload_board(set_pool, ["Mountain"])

    game.cast_from_hand(0, "Experimental Overload")
    game._settle()

    assert [p for p in game.controlled_by(0) if p.metadata.get("is_token")] == []
    # The control: the effect really did run, and on a graveyard with something
    # to count it leaves a token standing. Without it this holds on any engine
    # where the card is unsupported and nothing happens at all.
    assert [c.name for c in p1.exile] == ["Experimental Overload"]
    control, _ = _overload_board(set_pool, ["Shock"])
    control.cast_from_hand(0, "Experimental Overload")
    control._settle()
    assert [
        p.card.name for p in control.controlled_by(0) if p.metadata.get("is_token")
    ] == ["Weird Token"]


def test_a_token_with_two_different_variables_refuses(set_pool):
    """One repeated variable is the card's shape; two would give the token a
    toughness the where-clause never defined."""
    from engine.grammar import compile_line

    assert compile_line(
        "Create an X/X blue and red Weird creature token, where X is the number "
        "of instant and sorcery cards in your graveyard."
    ).instructions
    assert compile_line(
        "Create an X/Y blue and red Weird creature token, where X is the number "
        "of instant and sorcery cards in your graveyard."
    ).instructions == ()


# --- Volcanic Salvo: a cost that is a question (round 120) ------------------


def _salvo_board(set_pool, mine=(), theirs=()):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool["Volcanic Salvo"]])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)
    return game, p1, pool


def test_volcanic_salvo_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Volcanic Salvo"])
    assert program.supported, program.reason


def test_the_reduction_is_the_total_power_you_control(set_pool):
    """"{X} less to cast, where X is …" — the reduction is generic and its size
    is not in the text, which is why a bare {X} was refused outright: an amount
    this cannot compute is not an amount of zero."""
    from engine.cost_modifiers import CostReduction, cost_reduction_for_cast

    game, _, pool = _salvo_board(set_pool)
    assert cost_reduction_for_cast(game, 0, pool["Volcanic Salvo"])[0] == CostReduction(0)

    game, _, pool = _salvo_board(set_pool, mine=("Baneslayer Angel", "Alpine Watchdog"))
    assert cost_reduction_for_cast(game, 0, pool["Volcanic Salvo"])[0] == CostReduction(7)


def test_the_reduction_reads_computed_power(set_pool):
    """CR 613: a pumped creature counts for what it currently is, and negative
    power contributes nothing — CR 107.1b has no negative amounts, and a shrunk
    creature must not make the spell cost *more*."""
    from engine.cost_modifiers import cost_reduction_for_cast
    from engine.pt import add_pt_modifier

    game, _, pool = _salvo_board(set_pool, mine=("Alpine Watchdog",))
    watchdog = next(iter(game.controlled_by(0)))

    add_pt_modifier(watchdog, 3, 0)
    assert cost_reduction_for_cast(game, 0, pool["Volcanic Salvo"])[0].generic == 5

    add_pt_modifier(watchdog, -9, 0)
    assert cost_reduction_for_cast(game, 0, pool["Volcanic Salvo"])[0].generic == 0


def test_volcanic_salvo_hits_each_of_the_two_it_names(set_pool):
    """"…to **each of** up to two target creatures and/or planeswalkers": the
    full amount to each, because the card divides nothing. A third creature the
    caster did not choose is untouched."""
    game, _, pool = _salvo_board(
        set_pool, theirs=("Baneslayer Angel", "Alpine Watchdog", "Pridemalkin"),
    )
    board = list(game.controlled_by(1))
    chosen = [game.permanent_id_of(board[0]), game.permanent_id_of(board[1])]

    result = game.cast_from_hand(
        0, "Volcanic Salvo", target_player_index=1, target_permanent_ids=chosen,
    )
    game._settle()

    assert result.supported, result.details
    assert [p.card.name for p in game.controlled_by(1)] == ["Pridemalkin"]


def test_a_clause_the_table_cannot_compute_still_refuses(set_pool):
    """The refusal side, unchanged: a "where X is …" naming a count this table
    does not know leaves the card unsupported rather than quietly free."""
    from engine.cost_modifiers import self_cost_reduction

    assert self_cost_reduction(
        "This spell costs {X} less to cast, where X is the total power of "
        "creatures you control."
    ) is not None
    assert self_cost_reduction(
        "This spell costs {X} less to cast, where X is the number of chainsaws "
        "you have juggled."
    ) is None


# --- Necromentia: one choice, three zones, one subset (round 126) -----------


def _necromentia_board(set_pool, hand=(), graveyard=(), library=()):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool["Necromentia"]])
    p2 = PlayerState(
        name="P2", life=20,
        hand=[pool[n] for n in hand],
        graveyard=[pool[n] for n in graveyard],
        library=[pool[n] for n in library],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_necromentia_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Necromentia"])
    assert program.supported, program.reason


def test_necromentia_strips_every_copy_from_three_zones(set_pool):
    """One choice and one pile: "that name" is what the first sentence chose,
    and the search reaches all three zones in the printed order."""
    game, _, p2 = _necromentia_board(
        set_pool,
        hand=("Shock", "Shock", "Mountain"),
        graveyard=("Shock",),
        library=("Shock", "Island", "Forest"),
    )

    game.cast_from_hand(0, "Necromentia", target_player_index=1)
    game._settle()
    assert game.confirm_name_and_strip(0, "Shock")
    game._settle()

    assert [c.name for c in p2.exile] == ["Shock"] * 4
    assert [c.name for c in p2.hand] == ["Mountain"]
    assert p2.graveyard == []
    assert sorted(c.name for c in p2.library) == ["Forest", "Island"]


def test_only_the_cards_taken_from_hand_make_zombies(set_pool):
    """"…for each card exiled from their **hand** this way" is a strict subset
    of what was exiled. Counting the whole pile would make far more Zombies
    than the card promises."""
    game, _, p2 = _necromentia_board(
        set_pool,
        hand=("Shock", "Shock"),
        graveyard=("Shock",),
        library=("Shock",),
    )

    game.cast_from_hand(0, "Necromentia", target_player_index=1)
    game._settle()
    game.confirm_name_and_strip(0, "Shock")
    game._settle()

    tokens = [p for p in game.controlled_by(1) if p.metadata.get("is_token")]
    assert len(tokens) == 2, "four exiled, two of them from hand"
    assert all(
        (t.effective_power, t.effective_toughness) == (2, 2) for t in tokens
    )


def test_a_basic_lands_name_cannot_be_chosen(set_pool):
    """The one printed restriction on the choice, enforced where the choice is
    made — CR 202.1 otherwise lets a player name any card at all."""
    game, _, p2 = _necromentia_board(set_pool, hand=("Mountain",), library=("Mountain",))

    game.cast_from_hand(0, "Necromentia", target_player_index=1)
    game._settle()

    assert not game.confirm_name_and_strip(0, "Mountain")
    assert [c.name for c in p2.hand] == ["Mountain"]


def test_the_default_names_the_commonest_card_it_can_see(set_pool):
    """A non-interactive seat picks the name appearing most often in the
    searched zones — the choice a player would actually make — and never a
    basic land's, because the default has to obey the same restriction the
    prompt does."""
    game, _, _ = _necromentia_board(
        set_pool,
        hand=("Mountain", "Mountain", "Mountain"),
        library=("Shock", "Shock"),
    )

    game.cast_from_hand(0, "Necromentia", target_player_index=1)
    game._settle()

    (choice,) = game.pending_choices
    assert choice.data["default_name"] == "Shock"

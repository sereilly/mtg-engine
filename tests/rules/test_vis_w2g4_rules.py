"""CR rules VIS wave 2 group 4 reached: skipping a turn, a fight between two
chosen creatures, and a keyword removal on the other half of a block.

Its own file rather than a block appended to the shared rules modules, for the
reason SET_PLAYBOOK.md gives for the per-set test blocks: a merge that only ever
adds a file cannot lose an import or reorder an ``elif`` chain.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.grammar import parse_line
from engine.grammar.lower import lower_ability
from engine.models import CardDefinition, Permanent


def _body(name, power=2, toughness=2, keywords=(), oracle_text=""):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text=oracle_text, colors=(), color_identity=(),
        keywords=tuple(keywords), produced_mana=(), raw={"name": name},
        power=str(power), toughness=str(toughness),
    )


def _duel(mine=(), theirs=()):
    p0 = PlayerState(name="P0", life=20, battlefield=[Permanent(card=c) for c in mine])
    p1 = PlayerState(name="P1", life=20, battlefield=[Permanent(card=c) for c in theirs])
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._settle()
    return game, p0, p1


# ---------------------------------------------------------------------------
# CR 500.11 — skipping a turn
# ---------------------------------------------------------------------------

_SKIPPER = "{0}: This creature gets +3/+3 until end of turn. You skip your next turn."


@pytest.mark.cr("500.11")
def test_500_11_a_skipped_turn_is_proceeded_past_as_though_it_did_not_exist():
    """"To skip a step, phase, or turn is to proceed past it as though it
    didn't exist."

    Read off the turn order rather than off the counter: the seat that would
    have taken the skipped turn simply does not become the active player, and
    the rotation continues from the seat after it.
    """
    game, _p0, _p1 = _duel(mine=[_body("Skipper", oracle_text=_SKIPPER)])
    game.start_turn(0)
    game.players[0].battlefield[0].metadata["summoning_sickness_turn"] = -99

    assert game.activate_permanent_ability(0, "Skipper").supported, game.log

    assert game.start_next_turn() == 1
    assert game.start_next_turn() == 1, "seat 0's next turn never begins"
    assert game.start_next_turn() == 0


@pytest.mark.cr("500.11")
def test_500_11_skipped_turns_are_counted_not_flagged():
    """Two activations skip two turns. A flag could not say so, and the record
    is a per-seat count for exactly that reason."""
    game, _p0, _p1 = _duel(mine=[_body("Skipper", oracle_text=_SKIPPER)])
    game.start_turn(0)
    game.players[0].battlefield[0].metadata["summoning_sickness_turn"] = -99

    game.activate_permanent_ability(0, "Skipper")
    game.activate_permanent_ability(0, "Skipper")

    assert game.skip_turn_counts.get(0) == 2, game.log
    assert game.start_next_turn() == 1
    assert game.start_next_turn() == 1
    assert game.start_next_turn() == 1
    assert game.start_next_turn() == 0


@pytest.mark.cr("500.7")
def test_500_7_a_skipped_turn_and_a_skipped_step_are_different_records():
    """CR 500.7's steps and CR 500.11's turns are counted in different buckets,
    and the lowering is what keeps them apart: a turn is not one of the steps
    ``_phase_steps`` walks, so a turn skip filed as a step skip would be a
    record nothing ever consumes."""
    turn = lower_ability(parse_line("You skip your next turn."))
    step = lower_ability(parse_line("You skip your next draw step."))

    assert [i.kind for i in turn] == ["skip_next_turn"]
    assert [i.kind for i in step] == ["skip_next_step"]


# ---------------------------------------------------------------------------
# CR 701.14 — a fight between two creatures the ability chose
# ---------------------------------------------------------------------------

_TRIANGLE = (
    "{0}: Target creature you control fights target creature an opponent "
    "controls."
)


def _triangle_board(mine_pt, theirs_pt):
    artifact = CardDefinition(
        name="Arbiter", mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text=_TRIANGLE, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Arbiter"}, power=None, toughness=None,
    )
    game, p0, p1 = _duel(
        mine=[artifact, _body("Mine", *mine_pt)], theirs=[_body("Theirs", *theirs_pt)]
    )
    game.start_turn(0)
    for perm in list(p0.battlefield) + list(p1.battlefield):
        perm.metadata["summoning_sickness_turn"] = -99
    return game, p0.battlefield[1], p1.battlefield[0]


@pytest.mark.cr("701.14a")
def test_701_14a_two_chosen_creatures_each_deal_damage_equal_to_their_power():
    """The same exchange as a source-shaped fight, with **neither** fighter
    being the ability's source: CR 601.2c announces both independently."""
    game, mine, theirs = _triangle_board((3, 5), (2, 6))

    result = game.activate_permanent_ability(
        0, "Arbiter", target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    assert result.supported, result.details
    game._settle()

    assert theirs.damage_marked == 3
    assert mine.damage_marked == 2


@pytest.mark.cr("701.14a")
def test_701_14a_both_powers_are_read_before_either_half_is_dealt_for_two_targets():
    """A 1/1 and a 5/5 trade: the fighter killed by the first half has still
    dealt its own power. The shared ``_exchange_fight_damage`` body is what
    makes this true of the two-target kind without a second reading of the
    rule."""
    game, mine, theirs = _triangle_board((1, 1), (5, 5))

    game.activate_permanent_ability(
        0, "Arbiter", target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    game._settle()

    assert theirs.damage_marked == 1, "the dying fighter still dealt its power"
    assert not game.is_on_battlefield(mine)


@pytest.mark.cr("701.14d")
def test_701_14d_a_two_target_fights_damage_is_not_combat_damage():
    """It goes through the ordinary creature-damage path, so a blanket combat
    shield does not see it."""
    game, mine, theirs = _triangle_board((3, 5), (2, 6))
    game.players[1].combat_damage_prevented_this_turn = True

    game.activate_permanent_ability(
        0, "Arbiter", target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    game._settle()

    assert theirs.damage_marked == 3


@pytest.mark.cr("601.2c")
def test_601_2c_a_two_target_fight_announces_both_slots_under_their_own_filters():
    """Each slot carries its own noun phrase, and the picker enumerates the
    **union** — a creature is offered when some slot admits it. One filter for
    both would hide every opponent's creature from the second pick.
    """
    lowered = lower_ability(parse_line(
        "Target creature you control fights target creature an opponent controls."
    ))
    assert [i.kind for i in lowered] == ["target_fights_target"]
    targets = lowered[0].payload["targets"]
    assert targets["count"] == 2
    assert [f.get("controller") for f in targets["filters"]] == ["you", "opponent"]


# ---------------------------------------------------------------------------
# CR 509.1 / CR 613.1f — the other half of a block, and a keyword taken away
# ---------------------------------------------------------------------------

_STRIPPER = (
    "Whenever this creature blocks or becomes blocked by a creature, that "
    "creature loses first strike until end of turn."
)


def _block(attacker_cards, blocker_cards, blocks):
    game, p0, p1 = _duel(mine=attacker_cards, theirs=blocker_cards)
    game.start_turn(0)
    for perm in list(p0.battlefield) + list(p1.battlefield):
        perm.metadata["summoning_sickness_turn"] = -99
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, list(range(len(attacker_cards))))[0], game.log
    game._settle()
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, blocks)[0], game.log
    game._settle()
    for _ in range(len(game.stack) + 8):
        if not game.stack or not game.resolve_top_of_stack():
            break
    game._settle()
    return game, p0, p1


@pytest.mark.cr("509.1g")
def test_509_1g_that_creature_names_the_other_half_of_the_block():
    """CR 509.1g makes the blocking creature a blocking creature and the
    attacker a blocked creature — a *pair*. "That creature" under a block
    trigger names the half the source is not, whichever half the source is.

    Read off the ids the fire site recorded rather than off the stack item's
    target: on the blocks half the target is the blocking creature itself, so
    the ordinary target reading would strip the source's own keyword.
    """
    game, p0, p1 = _block(
        [_body("Attacker", keywords=("first strike",))],
        [_body("Guard", keywords=("first strike",), oracle_text=_STRIPPER)],
        {0: [0]},
    )
    attacker = p0.battlefield[0]
    guard = p1.battlefield[0]

    assert not game._has_keyword(attacker, "first strike")
    assert game._has_keyword(guard, "first strike"), (
        "the source keeps its own; the sentence names the other half"
    )


@pytest.mark.cr("509.3d")
def test_509_3d_a_narrowed_block_trigger_names_exactly_one_creature():
    """"…becomes blocked **by a creature**" fires once for each creature the
    phrase admits, so "that creature" is the one that admitted this firing.

    The bare spelling (CR 509.3c) fires once however many creatures block, with
    no way to say which — which is why the lowering asks whether the trigger
    carried a printed narrowing rather than asking what kind it was.
    """
    lowered = lower_ability(parse_line(_STRIPPER))
    assert [i.kind for i in lowered] == ["remove_keyword_from_block_pair"]


@pytest.mark.cr("613.1f")
def test_613_1f_a_removed_keyword_leaves_through_layer_6():
    """Ability-adding and ability-removing effects are applied in layer 6, so a
    removal composes with grants by timestamp. The removal here goes through the
    same seam the grant does, which is what makes that true without either side
    knowing about the other."""
    game, p0, p1 = _block(
        [_body("Attacker", keywords=("first strike",))],
        [_body("Guard", oracle_text=_STRIPPER)],
        {0: [0]},
    )
    attacker = p0.battlefield[0]

    assert not game._has_keyword(attacker, "first strike")
    # A grant applied *after* the removal wins on timestamp, which is what says
    # the removal was a layer-6 contribution rather than a flag.
    from engine.keywords import grant_keyword

    grant_keyword(attacker, "first strike", duration="end_of_turn")
    game._recompute_continuous_effects()
    assert game._has_keyword(attacker, "first strike")


# ---------------------------------------------------------------------------
# CR 611.2c — a sweep's set is fixed at resolution
# ---------------------------------------------------------------------------

@pytest.mark.cr("611.2c")
def test_611_2c_a_narrowed_sweep_fixes_its_set_when_it_resolves():
    """"Each creature without flanking blocking this creature gets -1/-1 until
    end of turn."

    The set is decided as the effect begins, so the handler walks the board
    once. Both narrowings are answered by the one matcher — the keyword because
    CR 613.1f makes it a layer-6 question, the block because it is a relation to
    the ability's own source — and a creature that starts blocking afterwards is
    not in the set.
    """
    knight = _body(
        "Warden", keywords=("flanking",),
        oracle_text=(
            "Flanking\n{0}: Each creature without flanking blocking this "
            "creature gets -1/-1 until end of turn."
        ),
    )
    game, p0, p1 = _block(
        [knight, _body("Escort", 3, 3)],
        [_body("Blocker"), _body("Flanker", keywords=("flanking",))],
        {0: [0], 1: [0]},
    )
    blocker, flanker = p1.battlefield[0], p1.battlefield[1]
    escort = p0.battlefield[1]
    before = {p.card.name: (p.effective_power, p.effective_toughness)
              for p in (blocker, flanker)}

    assert game.activate_permanent_ability(0, "Warden").supported, game.log
    game._settle()

    assert (blocker.effective_power, blocker.effective_toughness) == (
        before["Blocker"][0] - 1, before["Blocker"][1] - 1
    )
    assert (flanker.effective_power, flanker.effective_toughness) == before["Flanker"]
    assert (escort.effective_power, escort.effective_toughness) == (3, 3)

"""Core Set 2021 (M21) enchantments — the Auras among them.

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
from engine.auras import detach_aura
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- An Aura is more than its first line ------------------------------------


@pytest.mark.parametrize("name", ["Capture Sphere", "Dub", "Furor of the Bitten"])
def test_round_36_aura_cards_compile_supported(set_pool, name):
    program = compile_card_oracle(set_pool("M21")[name])
    assert program.supported, program.reason


def _enchant(set_pool, aura_name, victim_name, victim_seat=0):
    pool = set_pool("M21")
    victim = Permanent(card=pool[victim_name])
    hand = [pool[aura_name]]
    if victim_seat == 0:
        p1 = PlayerState(
            name="P1", battlefield=[victim], hand=hand, library=[pool["Plains"]] * 4
        )
        p2 = PlayerState(name="P2")
    else:
        p1 = PlayerState(name="P1", hand=hand, library=[pool["Plains"]] * 4)
        p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    result = game.cast_from_hand(
        0, aura_name, target_player_index=victim_seat, target_permanent_index=0
    )
    assert result.supported, result.details
    game._settle()
    aura = next(p for p in p1.battlefield if p.card.name == aura_name)
    return game, aura, victim


def test_capture_sphere_attaches_even_though_flash_is_printed_first(set_pool):
    """The enchant clause is *found*, not assumed to be line 0. Capture Sphere
    prints "Flash" above it, and every reader of that clause answered no — so
    the Aura resolved, entered the battlefield, and attached to nothing while
    reporting itself supported."""
    game, aura, victim = _enchant(set_pool, "Capture Sphere", "Alpine Watchdog", 1)

    assert aura.metadata.get("attached_to") is victim
    assert victim.tapped, "its enters trigger taps what it enchants"

    game.start_turn(1)
    assert victim.tapped, "and it does not untap during its controller's untap step"


def test_dub_grants_a_creature_type_alongside_its_pt_and_keyword(set_pool):
    """One printed line in three CR 613 layers — 7c, 6 and 4 — and each half is
    read by the reader that owns that layer. A Dog stays a Dog: the type is
    added, never replacing (which is what separates this from a land-type
    change, CR 305.7)."""
    game, aura, victim = _enchant(set_pool, "Dub", "Alpine Watchdog")

    assert (victim.effective_power, victim.effective_toughness) == (4, 4)
    assert game._has_keyword(victim, "first strike")
    assert victim.has_type("knight")
    assert victim.has_type("dog"), "'in addition to its other types'"


def test_dubs_grants_all_end_when_it_leaves(set_pool):
    """Derived from the Aura's own text on every recompute, so detaching is
    simply ceasing to contribute — there is no remembered delta to undo, which
    is the whole reason the type grant is a layer-4 effect and not a stamp."""
    game, aura, victim = _enchant(set_pool, "Dub", "Alpine Watchdog")

    detach_aura(aura, victim)
    game.remove_from_battlefield(aura)
    game._recompute_continuous_effects()

    assert (victim.effective_power, victim.effective_toughness) == (2, 2)
    assert not victim.has_type("knight")
    assert not game._has_keyword(victim, "first strike")


def test_furor_of_the_bitten_forces_its_creature_to_attack(set_pool):
    """CR 508.1a. The requirement is asked of the attached Auras rather than
    stamped on the creature, so it ends with the Aura."""
    pool = set_pool("M21")
    bitten = _nosick(Permanent(card=pool["Alpine Watchdog"]))
    other = _nosick(Permanent(card=pool["Concordia Pegasus"]))
    p1 = PlayerState(
        name="P1", battlefield=[bitten, other],
        hand=[pool["Furor of the Bitten"]], library=[pool["Swamp"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.cast_from_hand(
        0, "Furor of the Bitten", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert (bitten.effective_power, bitten.effective_toughness) == (4, 4), "the P/T half too"

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers

    ok, msg = game.declare_attackers(0, [1])
    assert not ok and "must attack" in msg
    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg


def test_an_invented_creature_type_refuses_the_whole_line(set_pool):
    """The gate and the grant read the same vocabulary. A type outside it would
    be claimed here and granted nothing — the hollow-support shape this module
    exists to prevent — so the line is unclaimed instead."""
    from engine.auras import aura_effect_claim, aura_type_grants
    from engine.oracle import normalize_creature_line

    real = normalize_creature_line(
        "Enchanted creature gets +2/+2, has flying, and is a Demon in addition to its other types."
    )
    invented = normalize_creature_line(
        "Enchanted creature gets +2/+2, has flying, and is a Glorb in addition to its other types."
    )

    assert aura_effect_claim(real) is not None
    assert aura_type_grants(real) == ("demon",)
    assert aura_effect_claim(invented) is None
    assert aura_type_grants(invented) == ()


# --- Round 54: the Shrine cycle's first two ---------------------------------
#
# "At the beginning of your first main phase, … where X is the number of Shrines
# you control." Two subsystems meet on one line: a trigger condition the tables
# did not have, and a where-clause that could only be read inside the pump
# production. Sanctum of Stone Fangs reported `supported` and did nothing until
# round 53 caught it; this is the round that makes the report true.


def _shrine_board(set_pool, *names: str):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool[n]) for n in names])
    p1.library = [pool["Swamp"]] * 10
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, game.players[1]


def test_sanctum_of_stone_fangs_drains_for_each_shrine(set_pool):
    """Both halves of the sentence read the same X. The clause used to be
    consumed by the *inner* parse of "and you gain X life", so the gain got the
    definition and the loss silently lost nothing — which is why this asserts
    both numbers rather than the one that moved."""
    game, p1, p2 = _shrine_board(
        set_pool, "Sanctum of Stone Fangs", "Sanctum of All", "Sanctum of Tranquil Light"
    )

    game._enter_main_phase(precombat=True)
    game._settle()

    assert (p1.life, p2.life) == (23, 17)


def test_the_shrine_count_is_taken_at_resolution(set_pool):
    """CR 608.2: a where-clause is counted when the effect happens, not when the
    trigger is put on the stack — so the same permanent drains a different
    amount on a later turn. That is the reason the count travels as a
    description rather than a number."""
    game, p1, p2 = _shrine_board(
        set_pool, "Sanctum of Stone Fangs", "Sanctum of All", "Sanctum of Tranquil Light"
    )
    game._enter_main_phase(precombat=True)
    game._settle()
    assert (p1.life, p2.life) == (23, 17)

    game.remove_from_battlefield(p1.battlefield[-1])
    game._enter_main_phase(precombat=True)
    game._settle()

    assert (p1.life, p2.life) == (25, 15), "two Shrines now, not three"


def test_the_second_main_phase_is_not_a_first_one(set_pool):
    """The control for the trigger, and the reason the fire site is in the
    precombat entry rather than in the shared ``_enter_main_phase``: both main
    phases run through that method."""
    game, p1, p2 = _shrine_board(set_pool, "Sanctum of Stone Fangs")
    before = (p1.life, p2.life)

    game._enter_main_phase(precombat=False)
    game._settle()

    assert (p1.life, p2.life) == before


def test_sanctum_of_calm_waters_is_supported(set_pool):
    """The second Shrine the pair of subsystems buys: "you may draw X cards …
    If you do, discard a card." The may wrapper and the discard were already
    there; only the trigger and the count were missing."""
    program = compile_card_oracle(set_pool("M21")["Sanctum of Calm Waters"])

    assert program.supported
    trigger = program.triggered_abilities[0]
    assert trigger.condition.kind == "main_phase_first"
    assert trigger.instruction is not None


# --- Round 57: a damage event that knows who dealt it -----------------------


def _emancipation_board(set_pool, *, opposing: bool = False):
    """Fiery Emancipation on one battlefield, a Shock in the other player's
    hand when *opposing*. The Emancipation is P1's either way, so the opposing
    case is the same board with the burn on the wrong side of it."""
    pool = set_pool("M21")
    emancipation = Permanent(card=pool["Fiery Emancipation"])
    p1 = PlayerState(name="P1", battlefield=[emancipation])
    p2 = PlayerState(name="P2")
    (p2 if opposing else p1).hand = [pool["Shock"]]
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 1 if opposing else 0
    return game, p1, p2, pool


def test_fiery_emancipation_triples_a_spell_you_control(set_pool):
    """The card round 53 found doing nothing, and the reason it could not be
    written before: a Shock reaches the damage paths as its printed
    ``CardDefinition``, which no player controls, so "a source **you** control"
    had no answer. Two damage becomes six."""
    game, p1, p2, pool = _emancipation_board(set_pool)

    game.cast_from_hand(0, "Shock", target_player_index=1)

    assert p2.life == 14


def test_fiery_emancipation_leaves_an_opponents_spell_alone(set_pool):
    """The control, and the half a Permanent-only reading would have got
    right by accident. P2 casts the Shock; P1 owns the Emancipation."""
    game, p1, p2, pool = _emancipation_board(set_pool, opposing=True)

    game.cast_from_hand(1, "Shock", target_player_index=0)

    assert p1.life == 18


def test_fiery_emancipation_triples_a_creature_you_control(set_pool):
    """The other kind of source. A permanent's controller is a layer-2 question
    the control seam already answered, so this half is the one that would have
    worked without the seat — which is exactly why it is worth pinning
    alongside the spell."""
    pool = set_pool("M21")
    emancipation = Permanent(card=pool["Fiery Emancipation"])
    pinger = Permanent(card=pool["Chandra's Magmutt"])
    p1 = PlayerState(name="P1", battlefield=[emancipation, pinger])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _nosick(pinger)

    game.activate_permanent_ability(
        0, "Chandra's Magmutt", permanent_index=1, target_player_index=1
    )
    game._settle()

    assert p2.life == 17, "1 damage tripled"


def test_two_emancipations_multiply_rather_than_replace_each_other(set_pool):
    """CR 616.1 would apply them one at a time; every copy is the same effect at
    the same order, so applying them together is the sequence the default choice
    produces. One registered interceptor that returned a flat ×3 would drop the
    second copy entirely — an effect applies once per event."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=pool["Fiery Emancipation"]),
            Permanent(card=pool["Fiery Emancipation"]),
        ],
        hand=[pool["Shock"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    game.cast_from_hand(0, "Shock", target_player_index=1)

    assert p2.life == 2, "2 damage, tripled twice"


def test_a_prevention_shield_is_spent_before_the_multiplier(set_pool):
    """CR 616.1e gives the order to the affected player, and this is the one
    they would pick: the shield absorbs from the printed damage rather than from
    three times as much. The default order is the difference between 0 dealt and
    6, so it is not a detail of the registry's numbering."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Fiery Emancipation"])],
                     hand=[pool["Shock"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    p2.damage_prevention_pool = 3

    game.cast_from_hand(0, "Shock", target_player_index=1)

    assert p2.life == 20, "the shield ate the 2 before it could become 6"


# --- Round 58: a draw replacement that changes how many ---------------------


def _insight_board(set_pool, *, library: int = 12):
    pool = set_pool("M21")
    insight = Permanent(card=pool["Teferi's Ageless Insight"])
    p1 = PlayerState(
        name="P1",
        battlefield=[insight],
        library=[pool["Island"]] * library,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1, insight, pool


def test_teferis_ageless_insight_doubles_an_ordinary_draw(set_pool):
    """The last of round 53's three, and the one that needed the seam to change
    rather than the gate: every other draw replacement *consumes* the event, so
    ``_draw_with_replacements`` took its local ``count`` at the end and a
    replacement that only changed the number could not be written at all."""
    game, p1, insight, pool = _insight_board(set_pool)

    game._draw_with_replacements(p1, 1)

    assert len(p1.hand) == 2


def test_the_first_draw_of_your_draw_step_is_exempt(set_pool):
    """The rider, and it is one *draw* rather than one event. The draw step
    draws once here, and that once is the one the card exempts."""
    game, p1, insight, pool = _insight_board(set_pool)
    game.turn = 3

    game.resolve_draw_step(0)

    assert len(p1.hand) == 1


def test_only_the_first_draw_of_the_draw_step_is_exempt(set_pool):
    """A Howling Mine makes the draw step draw 1 + 1 in **one call**. CR 121.2
    makes that two individual draws, and the exemption covers the first — so the
    second doubles and three cards arrive. An implementation exempting the
    *event* rather than the draw would have drawn two.

    The Mine is LEA's, which is the point of ``set_pool`` taking a code: the
    card under test is M21's and the Mine is a prop for the shape of its
    event."""
    game, p1, insight, pool = _insight_board(set_pool)
    p1.battlefield.append(Permanent(card=set_pool("LEA")["Howling Mine"]))
    game.turn = 3

    game.resolve_draw_step(0)

    assert len(p1.hand) == 3


def test_a_draw_later_in_your_own_draw_step_is_not_the_first_one(set_pool):
    """The control the flag exists for: "the first one you draw in each of your
    draw steps" is not "any draw during your draw step", and the engine cannot
    tell them apart from the phase alone — both are made by the active player
    while the step is the draw step."""
    game, p1, insight, pool = _insight_board(set_pool)
    game.turn = 3
    game.resolve_draw_step(0)

    game._draw_with_replacements(p1, 1)

    assert len(p1.hand) == 3, "one from the step, two from the instant-speed draw"


def test_an_opponents_draw_is_not_yours(set_pool):
    """"If **you** would draw a card" — the doubler is found on the drawing
    player's own battlefield (CR 109.5)."""
    game, p1, insight, pool = _insight_board(set_pool)
    p2 = game.players[1]
    p2.library = [pool["Island"]] * 4

    game._draw_with_replacements(p2, 1)

    assert len(p2.hand) == 1


# --- A line that compiled to nothing ----------------------------------------


def test_garruks_uprising_third_line_is_no_longer_dropped(set_pool):
    """It reported *supported* with this line compiling to nothing — the
    partial-implementation class, on a card whose other two lines work. The
    power bound is what decides, and it reads the layer-computed power."""
    pool = set_pool("M21")
    uprising = Permanent(card=pool["Garruk's Uprising"])
    p1 = PlayerState(
        name="P1", battlefield=[uprising],
        hand=[pool["Alpine Watchdog"], pool["Elder Gargaroth"]],
        library=[pool["Forest"]] * 4,
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    program = compile_card_oracle(uprising.card)
    assert any(
        t.condition.kind == "matching_permanent_enters" and t.supported
        for t in program.triggered_abilities
    ), "the line compiles to a real trigger"

    game.cast_from_hand(0, "Alpine Watchdog")   # 2/2 — below the bound
    game._settle()
    assert len(p1.hand) == 1, "no draw for a small creature"

    game.cast_from_hand(0, "Elder Gargaroth")   # 6/6
    game._settle()
    assert len(p1.hand) == 1, "cast one, drew one"


# --- Round 85: an activation cost that shrinks with the board ---------------

_OTHER_SHRINES = (
    "Sanctum of Calm Waters",
    "Sanctum of Stone Fangs",
    "Sanctum of Shattered Heights",
    "Sanctum of Fruitful Harvest",
    "Sanctum of All",
)


def _tranquil_board(set_pool, *, other_shrines=0, generic=5):
    """Tranquil Light with *other_shrines* distinct Shrines beside it.

    Distinct on purpose: two copies of one legendary Shrine is a different
    question (CR 704.5j, still an open block here) and would make the count the
    test asserts depend on it.
    """
    pool = set_pool("M21")
    light = Permanent(card=pool["Sanctum of Tranquil Light"])
    battlefield = [light] + [
        Permanent(card=pool[name]) for name in _OTHER_SHRINES[:other_shrines]
    ]
    victim = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", battlefield=battlefield)
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    p1.mana_pool = {"W": 1, "U": 0, "B": 0, "R": 0, "G": 0, "C": generic, "generic": 0}
    return game, victim


def _activate(game):
    return game.activate_permanent_ability(
        0, "Sanctum of Tranquil Light", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )


def test_sanctum_of_tranquil_light_compiles_supported(set_pool):
    """Two sentences on one printed line, and only one of them is an effect. The
    reduction is run by ``engine/cost_modifiers.py`` while the cost is paid, so
    the parser accounts for it by asking that registry whether it claims the
    sentence â€” never by restating its words, which would be free to drift."""
    program = compile_card_oracle(set_pool("M21")["Sanctum of Tranquil Light"])

    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    assert ability.instruction.kind == "tap_target_permanent"


def test_the_ability_costs_one_less_for_each_shrine(set_pool):
    """One Shrine (itself) discounts {1}, so {5}{W} is payable with four
    generic."""
    game, victim = _tranquil_board(set_pool, other_shrines=0, generic=4)

    assert _activate(game).supported
    game._settle()
    assert victim.tapped


def test_three_shrines_take_three_off(set_pool):
    game, victim = _tranquil_board(set_pool, other_shrines=2, generic=2)

    assert _activate(game).supported
    game._settle()
    assert victim.tapped


def test_the_discount_does_not_make_it_free_by_accident(set_pool):
    """One short is still one short. The reduction is counted, not assumed â€”
    reading an unrecognized narrowing as satisfied is the one direction a cost
    error must never go, which is why an untestable noun phrase records no
    reduction at all."""
    game, victim = _tranquil_board(set_pool, other_shrines=2, generic=1)

    assert not _activate(game).supported
    assert not victim.tapped


def test_the_cost_clamps_at_zero(set_pool):
    """Six Shrines is more discount than the ability costs, and a cost cannot go
    below {0} â€” the same clamp a spell's own reduction makes."""
    game, victim = _tranquil_board(set_pool, other_shrines=5, generic=0)

    assert _activate(game).supported
    game._settle()
    assert victim.tapped


def test_a_reduction_over_an_untestable_noun_phrase_is_not_claimed():
    """The gate that keeps the discount honest. The count asks
    ``permanent_matches_filter``, so a phrase carrying a key that matcher cannot
    answer would be counted over a wider set than the card names â€” a bigger
    discount than the card gives. It records no reduction, and the line is then
    not claimed at all."""
    from engine.cost_modifiers import ability_self_reduction

    assert ability_self_reduction(
        "This ability costs {1} less to activate for each Shrine you control."
    ) is not None
    assert ability_self_reduction(
        "This ability costs {1} less to activate for each wumpus you control."
    ) is None


# --- Round 87: a cost paid with a card the phrase names ---------------------


def _heights_board(set_pool, hand, shrines=("Sanctum of Shattered Heights",)):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=pool[name]) for name in shrines],
        hand=[pool[name] for name in hand],
    )
    victim = Permanent(card=pool["Gale Swooper"])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, victim


def _activate_heights(game, cost_hand_index=None):
    return game.activate_permanent_ability(
        0, "Sanctum of Shattered Heights", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
        cost_hand_index=cost_hand_index,
    )


def test_sanctum_of_shattered_heights_compiles_supported(set_pool):
    """The damage half already worked — X off a board count, a target that may be
    a creature or a planeswalker. The whole card was its *cost*: a discard the
    printed phrase narrows, which nothing in the engine could either admit or
    charge."""
    program = compile_card_oracle(set_pool("M21")["Sanctum of Shattered Heights"])
    assert program.supported, program.reason

    (ability,) = program.activated_abilities
    assert ability.cost.discard_cards == 1
    assert ability.cost.discard_filters == (
        {"type_filter": "land"}, {"subtype_filter": "shrine"},
    )


def test_a_land_card_pays_the_cost(set_pool):
    game, p1, victim = _heights_board(set_pool, ["Mountain", "Shock"])

    result = _activate_heights(game)
    assert result.supported, result.details
    game._settle()

    assert [c.name for c in p1.graveyard] == ["Mountain"]
    assert [c.name for c in p1.hand] == ["Shock"]
    assert victim.damage_marked == 1


def test_a_shrine_card_pays_it_too(set_pool):
    """The other side of the printed "or", and the reason the cost carries a
    *tuple* of filters: "land" and "Shrine" narrow different characteristics — a
    card type and a subtype — so one filter holding both would name a card that
    is a land *and* a Shrine, which is nothing at all."""
    game, p1, _ = _heights_board(set_pool, ["Sanctum of Calm Waters", "Shock"])

    result = _activate_heights(game)
    assert result.supported, result.details

    assert [c.name for c in p1.graveyard] == ["Sanctum of Calm Waters"]


def test_a_hand_of_neither_cannot_activate_it(set_pool):
    """CR 602.5c: an unpayable cost makes the ability unactivatable, not free.
    A full hand is not a payable one here — which is the whole difference the
    narrowing makes, since the charger used to take the first card in hand."""
    game, p1, victim = _heights_board(set_pool, ["Shock", "Gale Swooper"])

    result = _activate_heights(game)
    assert not result.supported

    assert [c.name for c in p1.hand] == ["Shock", "Gale Swooper"]
    assert victim.damage_marked == 0


def test_naming_a_card_the_phrase_does_not_name_is_refused(set_pool):
    """Not slid onto a legal card. A stale click that discarded whatever was
    payable would throw away the land the player meant to keep — the same silent
    repointing the bare index fallback was fixed for."""
    game, p1, _ = _heights_board(set_pool, ["Mountain", "Shock"])

    result = _activate_heights(game, cost_hand_index=1)
    assert not result.supported

    assert [c.name for c in p1.hand] == ["Mountain", "Shock"]


def test_x_counts_the_shrines_on_the_battlefield(set_pool):
    game, _p1, victim = _heights_board(
        set_pool, ["Mountain"],
        ("Sanctum of Shattered Heights", "Sanctum of Calm Waters", "Sanctum of Stone Fangs"),
    )

    assert _activate_heights(game).supported
    game._settle()

    assert victim.damage_marked == 3


def test_the_picker_offers_only_what_the_charger_accepts(set_pool):
    """A picker that offers a card the payment then refuses is the failure the
    enumerator exists to prevent, so both sides read the printed alternatives
    through the same matcher."""
    game, _p1, _victim = _heights_board(
        set_pool, ["Shock", "Mountain", "Sanctum of Calm Waters", "Gale Swooper"]
    )

    cost_spec = game.activation_target_spec(0, 0)["cost_spec"]

    assert [t["name"] for t in cost_spec["valid_targets"]] == [
        "Mountain", "Sanctum of Calm Waters",
    ]

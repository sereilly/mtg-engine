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


# --- Round 95: how much any-colour mana is data ----------------------------


def _harvest_board(set_pool, shrines):
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", battlefield=[Permanent(card=pool[name]) for name in shrines]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.active_player_index = 0
    return game, p1


_SHRINE_CYCLE = (
    "Sanctum of Fruitful Harvest",
    "Sanctum of Calm Waters",
    "Sanctum of Stone Fangs",
)


def test_sanctum_of_fruitful_harvest_compiles_supported(set_pool):
    """The whole card was one number. "Add X mana of any one color" refused
    because the handler probed its clause *text* for the literal "one mana of
    any color" and recognized no other count — right while that was true, and
    the reason the refusal was written rather than a guess."""
    program = compile_card_oracle(set_pool("M21")["Sanctum of Fruitful Harvest"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "main_phase_first"
    assert trigger.instruction.payload["any_color_count"] == "x"


@pytest.mark.parametrize("shrines", [1, 2, 3])
def test_the_mana_counts_the_shrines(set_pool, shrines):
    game, p1 = _harvest_board(set_pool, _SHRINE_CYCLE[:shrines])

    game._fire_first_main_phase_triggers()
    game._settle()

    assert sum(p1.mana_pool.values()) == shrines


def test_any_one_color_is_one_choice_for_the_whole_clause(set_pool):
    """"Any **one** color" — the count multiplies a single symbol rather than
    asking again per mana."""
    game, p1 = _harvest_board(set_pool, _SHRINE_CYCLE)

    game._fire_first_main_phase_triggers()
    game._settle()

    produced = [symbol for symbol, amount in p1.mana_pool.items() if amount]
    assert len(produced) == 1
    assert p1.mana_pool[produced[0]] == 3


# --- Furious Rise: a duration that is neither of the two (round 109) --------


def _rise_board(set_pool, *, power_four=True, copies=1):
    pool = set_pool("M21")
    rises = [Permanent(card=pool["Furious Rise"]) for _ in range(copies)]
    # Baneslayer Angel is 5/5; Alpine Watchdog is 2/2 and fails the intervening-if.
    watcher = Permanent(
        card=pool["Baneslayer Angel" if power_four else "Alpine Watchdog"]
    )
    p1 = PlayerState(
        name="P1", battlefield=[*rises, watcher],
        library=[pool["Concordia Pegasus"], pool["Daybreak Charger"], pool["Mountain"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1, rises


def test_furious_rise_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Furious Rise"])
    assert program.supported, program.reason


def test_furious_rise_exiles_and_permits_only_with_a_big_creature(set_pool):
    """CR 603.4's intervening-if, checked when the trigger would fire. The
    permission is the second step of the same resolution, so it does not happen
    either.

    The control runs first and in the same test: on any engine where the card is
    unsupported *nothing* fires, and the negative half would hold for the wrong
    reason."""
    control, controls_p1, _ = _rise_board(set_pool, power_four=True)
    control.resolve_end_step(0)
    control._settle()
    assert [c.name for c in controls_p1.exile] == ["Concordia Pegasus"]
    assert len(control.cast_permissions) == 1

    game, p1, _ = _rise_board(set_pool, power_four=False)

    game.resolve_end_step(0)
    game._settle()

    assert p1.exile == []
    assert game.cast_permissions == []


def test_furious_rise_permission_survives_the_cleanup_sweep(set_pool):
    """The reason this duration had to exist. "Until end of turn" is swept at
    cleanup (CR 514.2), and reading Furious Rise's clause as that one would
    throw the exiled card away on the very turn it was exiled — the card would
    never be playable at all, because it is exiled *in* the end step."""
    from engine.cast_permissions import expire_end_of_turn, permission_for

    game, p1, _ = _rise_board(set_pool)
    game.resolve_end_step(0)
    game._settle()
    exiled = p1.exile[0]
    assert permission_for(game, 0, exiled, "exile") is not None

    expire_end_of_turn(game)

    assert permission_for(game, 0, exiled, "exile") is not None


def test_furious_rise_retires_its_own_earlier_grant(set_pool):
    """"…until you exile **another** card with this enchantment." The ending
    event is this same permanent granting again, so the previous card stops
    being playable exactly when the next one is exiled — where a stated-duration
    reading of "no duration" (CR 611.2a) would leave every card it had ever
    exiled playable at once."""
    from engine.cast_permissions import permission_for

    game, p1, _ = _rise_board(set_pool)
    game.resolve_end_step(0)
    game._settle()
    first = p1.exile[0]

    game.resolve_end_step(0)
    game._settle()
    second = p1.exile[-1]

    assert [c.name for c in p1.exile] == ["Concordia Pegasus", "Daybreak Charger"]
    assert permission_for(game, 0, first, "exile") is None
    assert permission_for(game, 0, second, "exile") is not None


def test_two_furious_rises_are_two_independent_permissions(set_pool):
    """Why the grant is keyed by ``permanent_id`` and not by the card's name.
    Both enchantments exile in the same end step; neither retires the other,
    because "this enchantment" is one permanent and the name they share cannot
    tell them apart."""
    from engine.cast_permissions import permission_for

    game, p1, rises = _rise_board(set_pool, copies=2)

    game.resolve_end_step(0)
    game._settle()

    assert len(p1.exile) == 2
    assert all(permission_for(game, 0, card, "exile") is not None for card in p1.exile)
    ids = {p.source_permanent_id for p in game.cast_permissions}
    assert ids == {game.permanent_id_of(rise) for rise in rises}


def test_furious_rise_lets_the_exiled_card_actually_be_played(set_pool):
    """The permission is a play permission, not a cast one — Furious Rise says
    "play", which covers a land as well (CR 305.1 still charges the land drop).
    Driven end to end so the grant is not merely recorded."""
    game, p1, _ = _rise_board(set_pool)
    game.resolve_end_step(0)
    game._settle()
    exiled = p1.exile[0]

    result = game.cast_from_hand(0, exiled.name, from_zone="exile")
    game._settle()

    assert result.supported, result.details
    assert [p.card.name for p in game.controlled_by(0)][-1] == "Concordia Pegasus"
    assert p1.exile == []


# --- Enthralling Hold: a restriction on the choice (round 112) --------------


def _hold_board(set_pool, *, victim_tapped):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Enthralling Hold"]], life=20)
    victim = Permanent(card=pool["Baneslayer Angel"], tapped=victim_tapped)
    p2 = PlayerState(name="P2", battlefield=[victim], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, victim


def test_enthralling_hold_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Enthralling Hold"])
    assert program.supported, program.reason


def test_enthralling_hold_cannot_be_cast_at_an_untapped_creature(set_pool):
    """CR 601.2c: an illegal choice makes the spell **uncastable**, not merely
    ineffective — so the cast is refused rather than the Aura resolving and
    doing nothing."""
    game, p1, p2, victim = _hold_board(set_pool, victim_tapped=False)

    result = game.cast_from_hand(
        0, "Enthralling Hold", target_player_index=1, target_permanent_index=0,
    )
    game._settle()

    assert not result.supported
    assert "can't be chosen" in result.details
    assert [p.card.name for p in game.controlled_by(1)] == ["Baneslayer Angel"]
    assert [c.name for c in p1.hand] == ["Enthralling Hold"]


def test_enthralling_hold_takes_a_tapped_creature(set_pool):
    game, p1, p2, _ = _hold_board(set_pool, victim_tapped=True)

    result = game.cast_from_hand(
        0, "Enthralling Hold", target_player_index=1, target_permanent_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert "Baneslayer Angel" in [p.card.name for p in game.controlled_by(0)]
    assert list(game.controlled_by(1)) == []


def test_the_ai_is_not_offered_a_target_the_cast_would_refuse(set_pool):
    """Two callers, one rule. A restriction only the cast path knew about is an
    AI turn spent on an action the game then rejects."""
    from engine.ai_policy import _choose_aura_target

    pool = set_pool("M21")
    game, _, _, victim = _hold_board(set_pool, victim_tapped=False)
    assert _choose_aura_target(game, 0, pool["Enthralling Hold"]) is None

    victim.tapped = True
    assert _choose_aura_target(game, 0, pool["Enthralling Hold"]) == (1, 0)


def test_a_restriction_the_matcher_cannot_test_leaves_the_card_unsupported(set_pool):
    """The refusal side. The Aura gate asks the same reader the cast path calls,
    so a printed phrase the matcher cannot answer leaves the line unclaimed and
    the card unsupported — rather than admitted with the restriction absent,
    which would let the spell take exactly the target the card forbids."""
    from engine.target_restrictions import target_restriction_line

    assert target_restriction_line(
        "you can't choose an untapped creature as this spell's target as you cast it"
    )
    assert not target_restriction_line(
        "you can't choose an enchanted creature as this spell's target as you cast it"
    )


# --- Faith's Fetters, and three Auras whose ETB never fired (round 113) -----


def _fetters_board(set_pool, victim_card="Baneslayer Angel", victim_seat=1):
    pool = set_pool("M21")
    victim = Permanent(card=pool[victim_card])
    p1 = PlayerState(name="P1", hand=[pool["Faith's Fetters"]], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(victim_seat, victim, None)
    # After the entry, which stamps the sickness this clears.
    _nosick(victim)
    return game, p1, p2, victim


def _fetter(game, victim_seat=1):
    result = game.cast_from_hand(
        0, "Faith's Fetters",
        target_player_index=victim_seat, target_permanent_index=0,
    )
    game._settle()
    return result


def test_faiths_fetters_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Faith's Fetters"])
    assert program.supported, program.reason


def test_faiths_fetters_attaches_to_any_permanent(set_pool):
    """"Enchant **permanent**". The attach path was a cascade of per-noun
    branches — creature, land, Wall, artifact, enchantment — each re-deriving
    "does this answer the enchant clause?" from the noun it was written for. A
    sixth noun therefore needed a sixth branch, and without one the Aura entered
    play unattached and went straight to the graveyard."""
    from engine.auras import auras_attached_to

    game, _, _, victim = _fetters_board(set_pool)

    assert _fetter(game).supported
    assert [a.card.name for a in auras_attached_to(victim)] == ["Faith's Fetters"]


def test_faiths_fetters_gains_four_life(set_pool):
    """The Aura's own ETB trigger. Auras were skipped by the generic
    enters-the-battlefield path on the strength of the two whose entry text
    ``_apply_aura_effect`` performs itself, so an ordinary one did nothing."""
    game, p1, _, _ = _fetters_board(set_pool)

    _fetter(game)

    assert p1.life == 24


def test_a_fettered_permanent_cannot_attack_or_block(set_pool):
    pool = set_pool("M21")
    game, _, _, victim = _fetters_board(set_pool)
    assert game.can_attack(victim, 0), "the control: it could attack before"

    _fetter(game)

    assert not game.can_attack(victim, 0)
    attacker = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(0, attacker, None)
    _nosick(attacker)
    assert not game._can_block_attacker(victim, attacker)


def test_a_fettered_permanents_activated_abilities_are_shut_off(set_pool):
    """The restriction's second half."""
    from tests.helpers import _mk_creature_card

    pinger = _mk_creature_card(
        "Pinger", 1, 1, "{T}: This creature deals 1 damage to any target.",
    )
    perm = Permanent(card=pinger)
    p1 = PlayerState(name="P1", hand=[set_pool("M21")["Faith's Fetters"]], life=20)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, perm, None)
    _nosick(perm)

    _fetter(game)
    result = game.activate_permanent_ability(1, "Pinger", target_player_index=0)

    assert not result.supported
    assert "can't be activated" in result.details
    assert p1.life == 24, "the ping did not happen"


def test_a_fettered_permanent_may_still_use_a_mana_ability(set_pool):
    """CR 605.1a's exception, and the reason it is part of the restriction's
    name: without it an Aura on a land would lock its controller out of the
    game rather than shut off one ability."""
    from tests.helpers import _mk_creature_card

    elf = Permanent(card=_mk_creature_card("Mana Elf", 1, 1, "{T}: Add {G}."))
    p1 = PlayerState(name="P1", hand=[set_pool("M21")["Faith's Fetters"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, elf, None)
    _nosick(elf)

    _fetter(game)
    # The control: the Aura really is attached. Without it this holds on any
    # engine where Faith's Fetters never attaches and restricts nothing.
    from engine.auras import auras_attached_to
    assert [a.card.name for a in auras_attached_to(elf)] == ["Faith's Fetters"]

    result = game.activate_permanent_ability(1, "Mana Elf")

    assert result.supported, result.details
    assert p2.mana_pool.get("G") == 1


def test_a_fettered_land_still_taps_for_mana(set_pool):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Faith's Fetters"]])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, Permanent(card=pool["Mountain"]), None)

    _fetter(game)
    # The control: the Aura really is attached. Without it this holds on any
    # engine where Faith's Fetters never attaches and restricts nothing.
    from engine.auras import auras_attached_to
    land = next(iter(game.controlled_by(1)))
    assert [a.card.name for a in auras_attached_to(land)] == ["Faith's Fetters"]

    game.tap_land_for_mana(1, "Mountain")

    assert p2.mana_pool.get("R") == 1


@pytest.mark.parametrize(
    "name,expected_hand",
    [("Setessan Training", 1), ("Rousing Read", 2)],
)
def test_an_auras_ordinary_entry_trigger_fires(set_pool, name, expected_hand):
    """Two more Auras that reported supported and did nothing. Both compile
    their entry trigger to an ordinary instruction; nothing ran it, because the
    resolution path skipped the generic trigger for every Aura alike."""
    pool = set_pool("M21")
    victim = Permanent(card=pool["Alpine Watchdog"])
    p1 = PlayerState(name="P1", hand=[pool[name]], library=[pool["Mountain"]] * 5)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, victim, None)
    _nosick(victim)

    game.cast_from_hand(0, name, target_player_index=1, target_permanent_index=0)
    game._settle()

    assert len(p1.hand) == expected_hand


# --- Demonic Embrace: a permission the card grants itself (round 114) -------


def _embrace_board(set_pool, *, in_graveyard, life=20, spare_cards=1):
    pool = set_pool("M21")
    hand = [pool["Mountain"]] * spare_cards
    graveyard = []
    if in_graveyard:
        graveyard.append(pool["Demonic Embrace"])
    else:
        hand.insert(0, pool["Demonic Embrace"])
    p1 = PlayerState(name="P1", life=life, hand=hand, graveyard=graveyard)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    victim = Permanent(card=pool["Alpine Watchdog"])
    game._put_permanent_onto_battlefield(0, victim, None)
    _nosick(victim)
    return game, p1, victim


def _embrace(game, *, from_zone):
    result = game.cast_from_hand(
        0, "Demonic Embrace",
        target_player_index=0, target_permanent_index=0, from_zone=from_zone,
    )
    game._settle()
    return result


def test_demonic_embrace_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Demonic Embrace"])
    assert program.supported, program.reason


def test_demonic_embrace_from_hand_costs_no_extra(set_pool):
    """One card with two prices. The additional cost names a *zone*, so it
    cannot be a property of the card alone — from the hand this is an ordinary
    Aura."""
    from engine.auras import auras_attached_to

    game, p1, victim = _embrace_board(set_pool, in_graveyard=False)

    assert _embrace(game, from_zone="hand").supported
    assert p1.life == 20
    assert [c.name for c in p1.hand] == ["Mountain"]
    assert [a.card.name for a in auras_attached_to(victim)] == ["Demonic Embrace"]


def test_demonic_embrace_from_the_graveyard_pays_life_and_a_card(set_pool):
    """The permission is a static ability of the card while it sits in the zone
    (CR 113.6d) — nothing grants it and nothing takes it away, so it is derived
    from the text rather than stored on ``game.cast_permissions``."""
    from engine.auras import auras_attached_to

    game, p1, victim = _embrace_board(set_pool, in_graveyard=True)

    assert _embrace(game, from_zone="graveyard").supported
    assert p1.life == 17
    assert p1.hand == []
    assert [c.name for c in p1.graveyard] == ["Mountain"]
    assert [a.card.name for a in auras_attached_to(victim)] == ["Demonic Embrace"]
    # +3/+1 on a 2/2.
    assert (victim.effective_power, victim.effective_toughness) == (5, 3)


def test_exactly_enough_life_pays(set_pool):
    """CR 118.4: a player may pay life as long as the total is at least the
    amount, so paying down to 0 is legal and 3 life pays a 3-life cost."""
    game, p1, _ = _embrace_board(set_pool, in_graveyard=True, life=3)

    assert _embrace(game, from_zone="graveyard").supported
    assert p1.life == 0


def test_too_little_life_makes_the_spell_uncastable(set_pool):
    """CR 601.2h: an unpayable cost makes the spell uncastable, not free."""
    game, p1, _ = _embrace_board(set_pool, in_graveyard=True, life=2)

    result = _embrace(game, from_zone="graveyard")

    assert not result.supported
    assert "cannot pay 3 life" in result.details
    assert p1.life == 2
    assert [c.name for c in p1.graveyard] == ["Demonic Embrace"]


def test_an_empty_hand_makes_the_spell_uncastable(set_pool):
    game, p1, _ = _embrace_board(set_pool, in_graveyard=True, spare_cards=0)

    result = _embrace(game, from_zone="graveyard")

    assert not result.supported
    assert "not enough cards in hand" in result.details
    assert p1.life == 20


def test_the_permission_and_its_costs_are_read_from_one_line(set_pool):
    """Two readers of one sentence, which this codebase refuses elsewhere and
    accepts here because they answer different questions of it: one asks whether
    the zone is open, the other what must be paid. Held to the same line, so
    there can be no permission with no costs attached, nor costs with no
    permission behind them."""
    from engine.cast_costs import additional_costs
    from engine.cast_permissions import self_permission_zone

    card = set_pool("M21")["Demonic Embrace"]

    assert self_permission_zone(card) == "graveyard"
    (cost,) = additional_costs(card)
    assert (cost.from_zone, cost.pay_life, cost.discard_cards) == ("graveyard", 3, 1)


def test_a_cost_clause_the_table_cannot_charge_refuses_the_whole_line():
    """A clause outside the set makes the sentence unread, so the card reports
    unsupported rather than castable from the graveyard for less than it
    prints."""
    from engine.cast_costs import additional_cost_for_line

    assert additional_cost_for_line(
        "You may cast this card from your graveyard by paying 3 life and "
        "discarding a card in addition to paying its other costs."
    ) is not None
    assert additional_cost_for_line(
        "You may cast this card from your graveyard by paying 3 life and "
        "sacrificing a Zombie in addition to paying its other costs."
    ) is None


# --- Double Vision: an ordinal, a union, and "that spell" (round 123) -------


def _vision_board(set_pool, hand):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool[n] for n in hand])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(
        0, Permanent(card=pool["Double Vision"]), None,
    )
    return game, p1, p2


def test_double_vision_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Double Vision"])
    assert program.supported, program.reason


def test_the_first_instant_or_sorcery_is_copied_and_the_second_is_not(set_pool):
    """The ordinal is part of the *condition*: a card that fired on every such
    spell is a different card. Asked of the caster's own record of what they
    have cast this turn, counting only what the narrowing admits."""
    game, _, p2 = _vision_board(set_pool, ("Shock", "Shock"))

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()
    assert p2.life == 16, "2 from the Shock and 2 from its copy"

    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()
    assert p2.life == 14, "the second one is not copied"


def test_a_creature_spell_does_not_consume_the_ordinal(set_pool):
    """"your first **instant or sorcery** spell" counts instants and sorceries
    and nothing else — the narrowing and the count are the same set, which is
    why the count asks the same reader the filter does."""
    game, _, p2 = _vision_board(set_pool, ("Alpine Watchdog", "Shock"))

    game.cast_from_hand(0, "Alpine Watchdog")
    game._settle()
    game.cast_from_hand(0, "Shock", target_player_index=1)
    game._settle()

    assert p2.life == 16, "the Shock is still the first instant or sorcery"


def test_the_union_narrowing_admits_either_type(set_pool):
    """A printed union is read as "any of these" (CR 105.4), which is a
    different test from the single-type row's "this one" — folding them would
    make one of the two silently wrong."""
    from engine.oracle import compile_card_oracle
    from tests.helpers import _mk_creature_card

    program = compile_card_oracle(_mk_creature_card(
        "Watcher", 2, 2,
        "Whenever you cast your first instant or sorcery spell each turn, draw a card.",
    ))
    (trigger,) = program.triggered_abilities

    assert trigger.condition.kind == "you_cast_first_spell_each_turn"
    assert trigger.condition.payload["cast_types"] == "instant or sorcery"
    assert trigger.supported


def test_copying_a_spell_that_has_left_the_stack_copies_nothing(set_pool):
    """"That spell" is the object the trigger fired on, found on the stack by
    identity. By the time nothing is there, CR 707.10 has nothing to copy —
    which is the honest outcome rather than reaching for whatever else is up
    there."""
    from engine.grammar import compile_line

    compiled = compile_line(
        "Whenever you cast your first instant or sorcery spell each turn, copy "
        "that spell. You may choose new targets for the copy."
    )
    (instruction,) = compiled.instructions

    assert instruction.kind == "copy_triggering_spell"


# --- Runed Halo: a player protected from a name (round 125) -----------------


def _halo_board(set_pool, named=None, opponent_graveyard=()):
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", life=20, hand=[pool["Runed Halo"]])
    p2 = PlayerState(
        name="P2", life=20, hand=[pool["Shock"]],
        graveyard=[pool[n] for n in opponent_graveyard],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Runed Halo")
    game._settle()
    halo = next(iter(game.controlled_by(0)))
    if named is not None:
        halo.metadata["chosen_card_name"] = named
    return game, p1, p2, halo


def test_runed_halo_compiles_supported(set_pool):
    """Both lines are claimed: the entry choice by ``enter_effects`` and the
    protection by its own derivation table. The first alone would leave the card
    reporting supported with the protection unaccounted for."""
    program = compile_card_oracle(set_pool("M21")["Runed Halo"])

    assert program.supported, program.reason
    claims = {i.value for i in program.instructions if i.kind == "derived_static_rule"}
    assert claims == {"enter_effects", "named_protection"}


def test_the_name_is_chosen_as_it_enters(set_pool):
    """CR 614.1c: the choice is made *as* the permanent enters, so it is stamped
    at entry rather than by a trigger — by the time a trigger could resolve, the
    protection would already have failed to apply once."""
    _, _, _, halo = _halo_board(set_pool, opponent_graveyard=("Shock",))

    assert halo.metadata["chosen_card_name"] == "Shock"


def test_the_named_spell_cannot_target_the_protected_player(set_pool):
    """CR 702.16i's first consequence, and CR 601.2c makes an illegal choice
    make the spell uncastable rather than ineffective."""
    game, p1, _, _ = _halo_board(set_pool, named="Shock")

    result = game.cast_from_hand(1, "Shock", target_player_index=0)

    assert not result.supported
    assert "protection from Shock" in result.details
    assert p1.life == 20


def test_a_spell_with_another_name_still_gets_through(set_pool):
    game, p1, _, _ = _halo_board(set_pool, named="Lightning Bolt")

    result = game.cast_from_hand(1, "Shock", target_player_index=0)
    game._settle()

    assert result.supported
    assert p1.life == 18


def test_the_named_source_deals_no_damage(set_pool):
    """The second consequence. Checked on the player-damage path rather than as
    a shield, because protection is not prevention: nothing is consumed and no
    replacement contends — the damage simply is not dealt."""
    from tests.helpers import _mk_creature_card

    game, p1, _, _ = _halo_board(set_pool, named="Prodigal Sorcerer")
    pinger = Permanent(card=_mk_creature_card(
        "Prodigal Sorcerer", 1, 1,
        "{T}: This creature deals 1 damage to any target.",
    ))
    game._put_permanent_onto_battlefield(1, pinger, None)
    _nosick(pinger)

    game.activate_permanent_ability(1, "Prodigal Sorcerer", target_player_index=0)
    game._settle()

    assert p1.life == 20


def test_two_halos_protect_from_two_names(set_pool):
    """The protection is derived from the controlling permanents, so it is a
    *set* — and it ends when a Halo leaves, with nothing to clear."""
    from engine.named_protection import names_protecting

    pool = set_pool("M21")
    game, _, _, halo = _halo_board(set_pool, named="Shock")
    second = Permanent(card=pool["Runed Halo"])
    game._put_permanent_onto_battlefield(0, second, None)
    second.metadata["chosen_card_name"] = "Lightning Bolt"

    assert names_protecting(game, 0) == frozenset({"Shock", "Lightning Bolt"})

    game.remove_from_battlefield(second)
    assert names_protecting(game, 0) == frozenset({"Shock"})

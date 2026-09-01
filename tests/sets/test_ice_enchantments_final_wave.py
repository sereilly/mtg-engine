"""Ice Age (ICE) enchantment cards — the final wave.

ICE **ships** (SET_PLAYBOOK.md Phase 4 moved it from ``measured`` to ``sets``).
It was measured while these tests were written, and the pool resolves through
``set_pool("ICE")`` either way — that fixture is about which cards a test may
name, not about which a player may deck.

The third file of the printed type, and the split is the one
``test_ice_creatures_final_wave.py`` already made: tests/sets/README.md's axis
after the printed type is a round boundary, and for this set that is a *wave*
boundary. The serial rounds and the first parallel wave are in
``test_ice_enchantments_early_rounds.py``, the second and third waves in
``test_ice_enchantments.py`` — which reached 2,353 lines — and the final wave
here. Sections are named for the wave and group that bought them
(``W<wave>G<group>``) rather than for a round, because the work ran in parallel
worktrees from that point on.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- W4G1: a reanimation that names what it created, and cannot let it go ---
#
# Dreams of the Dead. "{1}{U}: Return target white or black creature card from
# your graveyard to the battlefield. That creature gains "Cumulative upkeep
# {2}." If the creature would leave the battlefield, exile it instead of
# putting it anywhere else."
#
# Three sentences, and the last two are about a permanent that did not exist
# when the ability was activated — the ability's *target* is a card in a
# graveyard. So the reanimation records what it created and the sentences
# behind it read that record.
#
# The third sentence is a CR 614 replacement with no single fire site: a
# permanent's card leaves the battlefield for a graveyard, a hand or a library,
# and each is its own seam. The completeness of that set is
# ``tests/engine/test_leave_battlefield_seam.py``'s job; what is checked here
# is that each destination actually exiles.


def _dreams_board(set_pool, *graveyard_names):
    """Dreams of the Dead on the battlefield with a named graveyard behind it."""
    pool = set_pool("ICE")
    dreams = Permanent(card=pool["Dreams of the Dead"])
    p1 = PlayerState(
        name="P1", battlefield=[dreams], life=20,
        graveyard=[pool[name] for name in graveyard_names],
    )
    p2 = PlayerState(name="P2", battlefield=[], life=20)
    game = Game(players=[p1, p2])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    return game, p1, p2


def _reanimate(game, graveyard_index=0):
    game.players[0].mana_pool = {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 1}
    game.activate_permanent_ability(
        0, "Dreams of the Dead", target_permanent_index=graveyard_index
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return next(
        (
            perm for perm in game.players[0].battlefield
            if perm.card.name != "Dreams of the Dead"
        ),
        None,
    )


def test_w4g1_dreams_of_the_dead_compiles_all_three_sentences(set_pool):
    """The colour narrowing is payload, the grant reads the reanimation's own
    record, and the replacement folds onto the move that creates its subject."""
    program = compile_card_oracle(set_pool("ICE")["Dreams of the Dead"])

    assert program.supported
    (ability,) = program.activated_abilities
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "reanimate_creature", "grant_target_ability_text",
    ]
    assert steps[0].payload == {"colors": ("W", "B"), "exile_on_leave": True}
    assert steps[1].payload["abilities"] == ("Cumulative upkeep {2}",)
    # Not a target: the ability's target is a card in a graveyard, and the
    # grant is about the permanent the first step created.
    assert "targets" not in steps[1].payload
    assert steps[1].payload["permanents_from"] == "reanimated_permanents"


def test_w4g1_the_picker_offers_only_white_and_black_creature_cards(set_pool):
    """The printed adjective, in the place a dropped one would be free: the
    list the player is offered."""
    from engine.targeting import derive_activation_spec

    program = compile_card_oracle(set_pool("ICE")["Dreams of the Dead"])
    spec = derive_activation_spec(program.activated_abilities[0])
    assert spec == {
        "kind": "graveyard_creature",
        "own_graveyard_only": True,
        "graveyard_colors": ["W", "B"],
    }

    game, _p1, _p2 = _dreams_board(
        set_pool, "Balduvian Bears", "Kjeldoran Skycaptain",
    )
    offered = game._enumerate_targets(
        0, set_pool("ICE")["Dreams of the Dead"], spec, for_cast=False,
    )
    assert [entry["name"] for entry in offered] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_green_creature_card_is_not_reanimated(set_pool):
    """The other end of the same narrowing: the resolution re-checks it, so a
    stale or invented index cannot slip a card past the picker."""
    game, p1, _p2 = _dreams_board(set_pool, "Balduvian Bears")

    assert _reanimate(game) is None
    assert [card.name for card in p1.graveyard] == ["Balduvian Bears"]


def test_w4g1_the_reanimated_creature_gains_cumulative_upkeep(set_pool):
    """The second sentence, and the whole reason the first records what it
    made: read as "the ability's target" the grant would land on a card in a
    graveyard and do nothing."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")

    revived = _reanimate(game)
    assert revived is not None and revived.card.name == "Kjeldoran Skycaptain"
    assert "Cumulative upkeep {2}" in revived.effective_card.oracle_text

    granted = compile_card_oracle(revived.effective_card)
    assert [
        (trigger.condition.kind, trigger.instruction.kind)
        for trigger in granted.triggered_abilities
    ] == [("upkeep_self", "cumulative_upkeep")]


def test_w4g1_an_unpaid_upkeep_exiles_it_rather_than_burying_it(set_pool):
    """Both new sentences at once, which is how the card actually plays: the
    granted upkeep sacrifices the creature and the replacement takes it out of
    the graveyard the sacrifice was heading for (CR 614.6). Without the second,
    the card is a two-mana loop."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    game.turn += 1
    game.resolve_upkeep(0)
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == ["Dreams of the Dead"]
    assert [card.name for card in p1.graveyard] == []
    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_bounce_exiles_it_too(set_pool):
    """The destination a "would die" reading would miss entirely. "Leave the
    battlefield" is four exits, and this clause is a drawback — the smaller
    reading is the one that hands the player a better card than the printed
    one."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    game._bounce_target_creature(revived)
    game._settle()

    assert [card.name for card in p1.hand] == []
    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_tuck_exiles_it_too(set_pool):
    """The third destination, through the library seam."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    game.remove_from_battlefield(revived)
    game.put_card_into_library(p1, revived.card, "top", from_battlefield=revived)

    assert p1.library == []
    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_creature_already_being_exiled_is_exiled_once(set_pool):
    """Exile is deliberately not one of the fire sites: a permanent already on
    its way there is going where "exile it instead" would send it, and an event
    fired at that destination would put the card in exile twice."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    game.remove_from_battlefield(revived)
    p1.exile.append(revived.card)

    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_an_ordinary_creature_beside_it_is_untouched(set_pool):
    """The marker is on the *permanent*, not on the card — a `CardDefinition`
    is shared between every copy of a card in a deck, so a record keyed to the
    card would divert a second copy's bounce as well."""
    pool = set_pool("ICE")
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    # A second, ordinary copy of the very same card object.
    twin = _nosick(Permanent(card=pool["Kjeldoran Skycaptain"]))
    p1.battlefield.append(twin)
    game._initialize_permanent_state(twin, 0, 0)

    game._bounce_target_creature(twin)
    game._settle()

    assert [card.name for card in p1.hand] == ["Kjeldoran Skycaptain"]
    assert [card.name for card in p1.exile] == []


def test_w4g1_the_leave_rider_refuses_a_move_that_cannot_arm_it(set_pool):
    """The rider is armed by one handler. On any other move the word would be
    consumed and dropped — and a *dropped drawback* is a card better than the
    one printed, so the line refuses instead.

    An invented sentence, because a guard aimed at a printed line stops
    guarding the day somebody implements it.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError, LoweringError
    from engine.grammar.lower import lower_ability

    line = (
        "Return target creature card from your graveyard to your hand. "
        "If the creature would leave the battlefield, exile it instead of "
        "putting it anywhere else."
    )
    with pytest.raises((GrammarError, LoweringError)):
        lower_ability(parse_line(line))
# --- end W4G1 ---


# --- ChaosMoon: a turn-scoped board mood ---
#
# Chaos Moon. "At the beginning of each upkeep, count the number of permanents.
# If the number is odd, until end of turn, red creatures get +1/+1 and whenever
# a player taps a Mountain for mana, that player adds an additional {R}. If the
# number is even, until end of turn, red creatures get -1/-1 and if a player
# taps a Mountain for mana, that Mountain produces colorless mana instead of any
# other type."
#
# The last card in the set, and four pieces of machinery: a counted number a
# sibling sentence reads back, a delayed triggered *mana* ability that composes
# with the anthem beside it, CR 605.4a's inline resolution, and a mana swap
# armed on every seat rather than on the enchantment's controller.


def _chaos_moon_board(set_pool, *, extra_mine=()):
    """Chaos Moon, a Mountain each, and one red creature on the far side.

    The permanent count is the whole of what this card branches on, so every
    test here states its own board size rather than inheriting one -- a fixture
    that quietly gained a permanent would flip every assertion at once.
    """
    ice = set_pool("ICE")
    lea = set_pool("LEA")
    moon = Permanent(card=ice["Chaos Moon"])
    mine = Permanent(card=lea["Mountain"])
    theirs = Permanent(card=lea["Mountain"])
    goblin = Permanent(card=lea["Mons's Goblin Raiders"])
    p0 = PlayerState(name="P0", battlefield=[moon, mine, *extra_mine], life=20)
    p1 = PlayerState(name="P1", battlefield=[theirs, goblin], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    return game, p0, p1, mine, goblin


def _odd_board(set_pool):
    """Five permanents: the board above plus a Plains, which is also the land
    the "a Mountain" narrowing has to leave alone."""
    return _chaos_moon_board(
        set_pool, extra_mine=[Permanent(card=set_pool("LEA")["Plains"])]
    )


def test_chaos_moon_compiles_its_whole_paragraph(set_pool):
    """Three sentences, one trigger, and no intervening "if".

    The shape is the assertion. CR 603.4 reads an "if" that *immediately follows
    a trigger condition* as the intervening-if of the whole ability, so a card
    printing one in the first sentence would gate both branches on it and the
    second could never run. Chaos Moon prints a count instead, and the two
    branches are siblings under a plain sequence.
    """
    program = compile_card_oracle(set_pool("ICE")["Chaos Moon"])
    assert program.supported

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "upkeep_each"
    assert trigger.instruction.kind == "sequence"
    assert "intervening_if" not in trigger.instruction.payload

    count, odd, even = trigger.instruction.payload["steps"]
    assert count.kind == "count_objects"
    assert count.payload["filter"] == {}, "CR 110.1: every permanent, whoever controls it"
    assert odd.payload["condition"] == {"kind": "counted_number", "op": "odd"}
    assert even.payload["condition"] == {"kind": "counted_number", "op": "even"}


def test_the_number_refuses_without_a_count_in_front_of_it(set_pool):
    """"The number" is a back-reference, not a second count.

    Its producer is declared (``lowering/_records._PRODUCES``) and the condition
    refuses without one -- which matters because an unproduced record answers
    False for *both* parities, so the card would silently do neither branch.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    with pytest.raises(LoweringError):
        lower_ability(parse_line(
            "If the number is odd, red creatures get +1/+1 until end of turn."
        ))


def test_chaos_moon_on_an_odd_board_pumps_red_and_doubles_a_mountain(set_pool):
    """Five permanents. "Red creatures get +1/+1 and whenever a player taps a
    Mountain for mana, that player adds an additional {R}."

    Both halves of one "and", which is the part the delayed trigger had to
    become composable for: the clause used to be readable only as a whole line.
    """
    game, p0, _p1, _mine, goblin = _odd_board(set_pool)
    assert len(list(game.all_permanents())) == 5

    game.resolve_upkeep(0)
    game._settle()

    assert (goblin.effective_power, goblin.effective_toughness) == (2, 2), game.log
    assert game.tap_land_for_mana(0, "Mountain"), game.log
    assert p0.mana_pool["R"] == 2, "the land's own {R} plus the additional one"


def test_chaos_moons_odd_mana_reaches_every_players_mountains(set_pool):
    """"whenever **a player** taps a Mountain" names no seat, so the ability
    answers to an opponent's Mountain exactly as it does to its controller's.

    The mirror of the even branch's test below, and the reason both exist: a
    test that taps only its own land passes whether or not the effect is
    seat-scoped.
    """
    game, _p0, p1, _mine, _goblin = _odd_board(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    assert game.tap_land_for_mana(1, "Mountain"), game.log
    assert p1.mana_pool["R"] == 2, game.log


def test_chaos_moons_odd_mana_leaves_a_non_mountain_alone(set_pool):
    """"a **Mountain**" is a printed noun phrase tested by the fire site, so the
    Plains beside it makes exactly what it always made."""
    game, p0, _p1, _mine, _goblin = _odd_board(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    assert game.tap_land_for_mana(0, "Plains"), game.log
    assert p0.mana_pool["W"] == 1 and p0.mana_pool["R"] == 0, game.log


@pytest.mark.cr("605.4a", "605.1b")
def test_chaos_moons_odd_mana_never_reaches_the_stack(set_pool):
    """CR 605.4a: a triggered mana ability does not go on the stack.

    The rule's own subject is exactly this clause. Every *other* delayed trigger
    in the engine is enqueued, so this one is announced through the enumerating
    half of that machinery and resolved where it stands -- inside the cost
    payment that tapped the land, before any spell it pays for is announced.
    """
    game, p0, _p1, _mine, _goblin = _odd_board(set_pool)

    game.resolve_upkeep(0)
    game._settle()
    assert game.stack == []

    assert game.tap_land_for_mana(0, "Mountain"), game.log
    assert game.stack == [], "a triggered mana ability resolves without the stack"
    assert p0.mana_pool["R"] == 2, "and it resolved"


def test_chaos_moon_on_an_even_board_shrinks_red_and_greys_a_mountain(set_pool):
    """Four permanents. "Red creatures get -1/-1 and if a player taps a Mountain
    for mana, that Mountain produces colorless mana instead of any other type."
    """
    game, p0, p1, _mine, goblin = _chaos_moon_board(set_pool)
    assert len(list(game.all_permanents())) == 4

    game.resolve_upkeep(0)
    game._settle()

    assert goblin not in p1.battlefield, "a 1/1 at -1/-1 is 0/0 (CR 704.5f)"
    assert game.tap_land_for_mana(0, "Mountain"), game.log
    assert p0.mana_pool["C"] == 1 and p0.mana_pool["R"] == 0, game.log


def test_chaos_moons_even_swap_reaches_every_players_mountains(set_pool):
    """The piece a one-sided test cannot see.

    ``land_mana_swaps.swapped_symbol`` asks the **land's own controller** for
    their records, so a swap armed only on Chaos Moon's controller would leave
    every opponent's Mountain making red on a board the card says is colourless.
    "A player taps" names no seat, so the effect arms one record per seat.
    """
    game, _p0, p1, _mine, _goblin = _chaos_moon_board(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    assert game.tap_land_for_mana(1, "Mountain"), game.log
    assert p1.mana_pool["C"] == 1 and p1.mana_pool["R"] == 0, game.log


@pytest.mark.cr("603.7b", "611.2c")
def test_chaos_moons_mood_is_gone_next_turn(set_pool):
    """"Until end of turn" over both halves.

    CR 611.2c locks the anthem's set in when it begins and the cleanup step ends
    it; CR 603.7b's stated duration is what expires the delayed ability, through
    the sweep that has always dropped a turn-scoped entry. Two mechanisms, one
    printed window, so both are asserted together.
    """
    game, p0, _p1, mine, goblin = _odd_board(set_pool)

    game.resolve_upkeep(0)
    game._settle()
    assert (goblin.effective_power, goblin.effective_toughness) == (2, 2)
    assert game.delayed_triggers

    game.resolve_cleanup_step(0)
    mine.tapped = False
    p0.mana_pool.clear()

    assert game.delayed_triggers == []
    assert (goblin.effective_power, goblin.effective_toughness) == (1, 1), game.log
    assert game.tap_land_for_mana(0, "Mountain"), game.log
    assert p0.mana_pool["R"] == 1, "the Mountain's own {R} and nothing more"


def test_a_delayed_mana_ability_refuses_without_a_stated_duration(set_pool):
    """An invented sentence, because a guard aimed at a printed line stops
    guarding the day somebody implements it.

    A repeating delayed ability with no window is one nothing ever lifts, and
    CR 603.7b's other reading -- "will trigger only once" -- is a different
    card. So the opener leaves the duration unstated and the lowering refuses
    unless a leading "until end of turn" filled it in.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    with pytest.raises(LoweringError):
        lower_ability(parse_line(
            "Whenever a player taps a Mountain for mana, "
            "that player adds an additional {R}."
        ))


def test_a_delayed_mana_opener_refuses_an_effect_the_seam_cannot_resolve(set_pool):
    """CR 605.4a is why: the seam that announces this event resolves its
    abilities inline, inside a cost payment, so it can only carry out a mana
    production. An effect it cannot perform refuses at the parse rather than
    arming an ability that would be found and skipped.
    """
    from engine.grammar import compile_line

    compiled = compile_line(
        "Until end of turn, whenever a player taps a Mountain for mana, "
        "that player draws a card."
    )
    assert not compiled.usable, compiled


@pytest.mark.cr("611.2c", "603.7")
def test_chaos_moons_two_halves_treat_a_latecomer_differently(set_pool):
    """One printed "and", two CR rules, and they disagree on purpose.

    The anthem is a continuous effect from a resolution, so CR 611.2c fixes its
    set of objects when it begins -- a red creature that enters afterwards gets
    nothing. The delayed ability is not a continuous effect at all: it answers
    to an *event*, so a Mountain that enters afterwards produces the extra {R}
    like any other.

    Reading either half as the other is the failure this asserts against, and
    the two are one sentence on the card.
    """
    lea = set_pool("LEA")
    game, p0, p1, _mine, goblin = _odd_board(set_pool)

    game.resolve_upkeep(0)
    game._settle()

    latecomer = Permanent(card=lea["Mountain"])
    p0.battlefield.append(latecomer)
    game._initialize_permanent_state(latecomer, 0, 0)
    late_goblin = Permanent(card=lea["Mons's Goblin Raiders"])
    p1.battlefield.append(late_goblin)
    game._initialize_permanent_state(late_goblin, 1, 1)
    game._sync_control()

    assert game.tap_land_for_mana(
        0, "Mountain", permanent_index=p0.battlefield.index(latecomer)
    ), game.log
    assert p0.mana_pool["R"] == 2, "the ability answers to the event, not to a set"

    assert (goblin.effective_power, goblin.effective_toughness) == (2, 2)
    assert (late_goblin.effective_power, late_goblin.effective_toughness) == (1, 1), (
        "CR 611.2c: the anthem's set was fixed when the effect began"
    )
# --- end ChaosMoon ---


# --- Promotion: an Enchant clause the picker could not read ---
def test_aggression_offers_a_creature_to_enchant(set_pool, catalog_by_name):
    """"Enchant non-Wall creature" is one of the two printed enchant clauses
    `targeting.py`'s noun vocabulary could not read, so it derived
    `kind: "none"` — and "none" is what the client tests to decide whether to
    ask for a target at all. It asked for none, sent a bare cast, and the engine
    refused it. The Aura was dead in hand, and no guard could see it: the card
    compiles supported, carries no hollow line and claims every printed
    sentence. (Faith's Fetters printed the other clause; its test is with the
    M21 enchantments.)

    Found at ICE's promotion by sweeping what the pickers *offer* rather than
    what the compiler accepts. The negated noun narrows to its head — the
    exclusion is the cast gate's to enforce, and the second half below keeps it
    enforcing it, because a picker that offered a Wall would be the same bug
    pointing the other way.
    """
    pool = set_pool("ICE")

    def cast(host_name):
        holder = PlayerState(
            name="P1", hand=[pool["Aggression"]],
            battlefield=[Permanent(card=catalog_by_name[host_name])],
        )
        game = Game(players=[holder, PlayerState(name="P2")])
        game.enforce_mana_costs = False
        game.start_turn(0)
        spec = game.cast_target_spec(0, pool["Aggression"])
        result = game.cast_from_hand(
            0, "Aggression", target_player_index=0, target_permanent_index=0
        )
        game._settle()
        return spec, result, game

    spec, result, game = cast("Grizzly Bears")
    assert spec["kind"] == "creature", spec
    assert [t["name"] for t in spec["valid_targets"]] == ["Grizzly Bears"]
    assert result.supported, game.log

    _spec, refused, _game = cast("Wall of Stone")
    assert not refused.supported
# --- end Promotion ---


# --- G4 (Fallen Empires wave): Hecatomb's ping had no cost ------------------
#
# The same missing article as Karplusan Giant one file over: "Tap **an**
# untapped Swamp you control" charged no tap at all, so the enchantment pinged
# once per priority window forever.

from engine import Game, PlayerState
from engine.models import Permanent


def _g4_hecatomb_board(set_pool, swamps=1):
    pool = set_pool("ICE")
    lea = set_pool("LEA")
    hecatomb = Permanent(card=pool["Hecatomb"])
    marsh = [Permanent(card=lea["Swamp"]) for _ in range(swamps)]
    p1 = PlayerState(name="P1", battlefield=[hecatomb, *marsh])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, game.players[1], hecatomb, marsh


def test_hecatomb_taps_a_swamp_to_deal_one_damage(set_pool):
    """"**Tap an untapped Swamp you control**: This enchantment deals 1 damage
    to any target."
    """
    game, _p1, p2, _hecatomb, marsh = _g4_hecatomb_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Hecatomb", permanent_index=0, target_player_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert p2.life == 19
    assert marsh[0].tapped


def test_hecatomb_cannot_ping_twice_off_one_swamp(set_pool):
    """A cost that matches nothing is a free ability, and a free ping is an
    unlimited one: with the Swamp already tapped the second activation is
    refused and the opponent takes no more damage.
    """
    game, _p1, p2, _hecatomb, _marsh = _g4_hecatomb_board(set_pool)
    assert game.activate_permanent_ability(
        0, "Hecatomb", permanent_index=0, target_player_index=1,
    ).supported
    game._settle()

    result = game.activate_permanent_ability(
        0, "Hecatomb", permanent_index=0, target_player_index=1,
    )
    game._settle()

    assert not result.supported
    assert p2.life == 19
# --- FEM wave, G5: an offer's seat under a player-subject trigger ---
from engine import Game as _G5Game, PlayerState as _G5PlayerState
from engine.models import Permanent as _G5Permanent


def test_mystic_remora_offers_the_toll_to_the_seat_that_cast_the_spell(set_pool):
    """The seat, in a game with more than one opponent in it.

    "…unless **that player** pays {4}" names the player the *event* was about,
    which the cast site freezes (CR 603.10). The offer used to reach
    ``_offered_seats``' fallback and read the resolution's target instead — the
    same seat in a duel by coincidence, and in a three-seat game a toll offered
    to a player who had cast nothing while the caster drew nothing and paid
    nothing.
    """
    pool = set_pool("ICE")
    remora = _G5Permanent(card=pool["Mystic Remora"])
    p0 = _G5PlayerState(name="P0", battlefield=[remora],
                        library=[pool["Balduvian Bears"]])
    # Four Islands each, so the toll is one both opponents could pay: an offer
    # nobody can afford is never armed (the decline branch runs at once), and
    # the question here is *which* seat gets asked.
    p1 = _G5PlayerState(
        name="P1",
        battlefield=[_G5Permanent(card=pool["Island"]) for _ in range(4)],
    )
    p2 = _G5PlayerState(
        name="P2", hand=[pool["Dark Ritual"]],
        battlefield=[_G5Permanent(card=pool["Island"]) for _ in range(4)],
    )
    game = _G5Game(players=[p0, p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(2)

    game.queue_from_hand(2, "Dark Ritual")
    while game.stack:
        game.resolve_top_of_stack()

    offered = [
        c.player_index for c in game.pending_choices
        if c.kind == "optional_pay" and c.data.get("card_name") == "Mystic Remora"
    ]
    assert offered == [2], game.log
# --- end FEM wave, G5 ---

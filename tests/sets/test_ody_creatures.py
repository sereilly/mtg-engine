"""Odyssey creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.control import change_control as _w1g1_change_control
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_table(set_pool, hand=(), mana=None):
    """A two-seat game with mana costs enforced; *hand* names Odyssey cards
    (or Alpha ones) in seat 0's hand."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[ody[name] if name in ody else lea[name] for name in hand],
        ),
        _W1G1PlayerState("Opponent", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    return game  # _w1g1_table (creatures)


def _w1g1_put(game, set_pool, seat, name):
    """*name* (Odyssey first, then Alpha) onto *seat*'s battlefield, able to
    act this turn."""
    ody = set_pool("ODY")
    card = ody[name] if name in ody else set_pool("LEA")[name]
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (creatures)


def _w1g1_graveyard(game, set_pool, seat, count):
    """Give *seat* exactly *count* cards in its graveyard, then let the
    state-based sweep recompute — a conditional static is re-asked there
    (CR 611.3a), and a probe that skips it reads last pass's answer."""
    game.players[seat].graveyard[:] = [set_pool("LEA")["Forest"]] * count
    game.check_state_based_actions()  # _w1g1_graveyard (creatures)


def _w1g1_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


@_w1g1_pytest.mark.parametrize(
    "name, printed, with_threshold",
    [
        ("Werebear", (1, 1), (4, 4)),
        ("Krosan Beast", (1, 1), (8, 8)),
        ("Metamorphic Wurm", (3, 3), (7, 7)),
        ("Nimble Mongoose", (1, 1), (3, 3)),
        ("Springing Tiger", (3, 3), (5, 5)),
    ],
)
def test_w1g1_threshold_bonus_turns_on_at_seven_and_off_again_below_it(
    set_pool, name, printed, with_threshold,
):
    """"Threshold — This creature gets +N/+N as long as there are seven or
    more cards in your graveyard." The bonus is there exactly while the count
    is: the seventh card arriving turns it on, an eighth changes nothing, and
    a card leaving turns it off — with no cast and no turn boundary between,
    and whatever the *opponent's* graveyard holds."""
    assert _w1g1_compile(set_pool("ODY")[name]).supported
    game = _w1g1_table(set_pool)
    creature = _w1g1_put(game, set_pool, 0, name)

    seen = []
    for count in (0, 6, 7, 8, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append(_w1g1_pt(creature))
    assert seen == [printed, printed, with_threshold, with_threshold, printed]

    _w1g1_graveyard(game, set_pool, 1, 9)
    assert _w1g1_pt(creature) == printed, "an opponent's graveyard is not yours"


def test_w1g1_a_creature_that_loses_threshold_with_damage_on_it_dies(set_pool):
    """A 4/4 Werebear carrying 2 damage is alive; the moment a card leaves its
    controller's graveyard it is a 1/1 with 2 damage and the same state-based
    sweep that recomputed its toughness puts it in the graveyard (CR 704.5g)."""
    game = _w1g1_table(set_pool)
    bear = _w1g1_put(game, set_pool, 0, "Werebear")
    _w1g1_graveyard(game, set_pool, 0, 7)
    game._mark_damage_on_permanent(bear, 2, source=None)
    game.check_state_based_actions()
    assert game.is_on_battlefield(bear) and _w1g1_pt(bear) == (4, 4)

    game.players[0].graveyard.pop()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(bear)
    assert game.players[0].graveyard[-1].name == "Werebear"


def test_w1g1_a_stolen_threshold_creature_counts_its_new_controllers_graveyard(
    set_pool,
):
    """"Your graveyard" is the controller's (CR 109.5), read through the
    control seam: a Werebear its owner has threshold for is a 1/1 the moment an
    opponent with an empty graveyard takes it, and a 4/4 again once *that*
    player has seven cards there."""
    game = _w1g1_table(set_pool)
    bear = _w1g1_put(game, set_pool, 0, "Werebear")
    _w1g1_graveyard(game, set_pool, 0, 7)
    assert _w1g1_pt(bear) == (4, 4)

    _w1g1_change_control(bear, 1, source="test")
    game._sync_control()
    game.check_state_based_actions()
    assert game.controller_index_of(bear) == 1
    assert _w1g1_pt(bear) == (1, 1)

    _w1g1_graveyard(game, set_pool, 1, 7)
    assert _w1g1_pt(bear) == (4, 4)


def test_w1g1_werebear_still_taps_for_green_beside_its_threshold_line(set_pool):
    """The mana ability on the line above the threshold sentence is untouched
    by it: {T}: Add {G}, with threshold or without."""
    game = _w1g1_table(set_pool)
    bear = _w1g1_put(game, set_pool, 0, "Werebear")
    _w1g1_graveyard(game, set_pool, 0, 7)

    result = game.activate_permanent_ability(0, "Werebear", ability_index=0)

    assert result.supported, result.details
    assert bear.tapped and game.players[0].mana_pool["G"] == 1


def test_w1g1_mystic_visionary_flies_only_with_threshold(set_pool):
    """"This creature has flying as long as there are seven or more cards in
    your graveyard." A keyword and no bonus: the 2/1 body never changes, and
    layer 6 has the word exactly while the count holds."""
    game = _w1g1_table(set_pool)
    visionary = _w1g1_put(game, set_pool, 0, "Mystic Visionary")

    seen = []
    for count in (6, 7, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append((game._has_keyword(visionary, "flying"), _w1g1_pt(visionary)))

    assert seen == [(False, (2, 1)), (True, (2, 1)), (False, (2, 1))]


def test_w1g1_gorilla_titan_is_bigger_only_with_an_empty_graveyard(set_pool):
    """"This creature gets +4/+4 as long as there are **no** cards in your
    graveyard." The same condition with a different comparison — exactly zero,
    so one card is enough to turn it off — and the printed trample is there
    throughout."""
    game = _w1g1_table(set_pool)
    titan = _w1g1_put(game, set_pool, 0, "Gorilla Titan")

    seen = []
    for count in (0, 1, 7, 0):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append(_w1g1_pt(titan))

    assert seen == [(8, 8), (4, 4), (4, 4), (8, 8)]
    assert game._has_keyword(titan, "trample")
    _w1g1_graveyard(game, set_pool, 1, 5)
    assert _w1g1_pt(titan) == (8, 8), "an opponent's graveyard is not yours"


def test_w1g1_nut_collector_buffs_every_squirrel_while_its_controller_has_threshold(
    set_pool,
):
    """"Threshold — All Squirrels get +2/+2 as long as there are seven or more
    cards in your graveyard." An anthem over *every* Squirrel on the table —
    the opponent's as well as its controller's — gated on the Collector's
    controller's graveyard. The Collector is a Human Druid and gets nothing."""
    from engine.tokens import make_token_card

    game = _w1g1_table(set_pool)
    collector = _w1g1_put(game, set_pool, 0, "Nut Collector")
    squirrel = make_token_card(
        "Squirrel", 1, 1, "Token Creature — Squirrel", colors=("G",)
    )
    mine = _W1G1Permanent(card=squirrel)
    theirs = _W1G1Permanent(card=squirrel)
    game._put_permanent_onto_battlefield(0, mine, None)
    game._put_permanent_onto_battlefield(1, theirs, None)

    seen = []
    for count in (6, 7, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append((_w1g1_pt(mine), _w1g1_pt(theirs), _w1g1_pt(collector)))
    assert seen == [
        ((1, 1), (1, 1), (1, 1)),
        ((3, 3), (3, 3), (1, 1)),
        ((1, 1), (1, 1), (1, 1)),
    ]

    _w1g1_graveyard(game, set_pool, 1, 7)
    assert _w1g1_pt(theirs) == (1, 1), "the opponent's graveyard is not the Collector's"


def test_w1g1_nut_collector_makes_a_squirrel_each_upkeep(set_pool):
    """"At the beginning of your upkeep, you may create a 1/1 green Squirrel
    creature token." Driven through the upkeep step and its "you may"; the
    token arrives 3/3 when its maker's controller already has threshold."""
    game = _w1g1_table(set_pool)
    _w1g1_put(game, set_pool, 0, "Nut Collector")
    _w1g1_graveyard(game, set_pool, 0, 7)
    game.active_player_index = 0

    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    squirrels = [p for p in game.controlled_by(0) if p.has_type("squirrel")]
    assert len(squirrels) == 1
    assert _w1g1_pt(squirrels[0]) == (3, 3)


# --- the fronted word order, and what a threshold static may carry ----------


def _w1g1_slot(game, seat, permanent):
    return list(game.controlled_by(seat)).index(permanent)  # _w1g1_slot (creatures)


def _w1g1_to_declare_attackers(game, seat=0, graveyards=None):
    """*seat*'s turn at the declare-attackers step, nobody summoning sick.
    *graveyards* is set before the turn starts, so the turn's own recompute is
    what reads it."""
    for index, count in (graveyards or {}).items():
        filler = game.players[index].library[0]
        game.players[index].graveyard[:] = [filler] * count
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step  # _w1g1_to_declare_attackers


def _w1g1_finish_combat(game):
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g1_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # _w1g1_finish_combat


def _w1g1_abilities(permanent):
    """The triggered and activated abilities *permanent* has right now, as the
    lines the compiler built them from."""
    program = _w1g1_compile(permanent.effective_card)
    return (
        [trigger.source_line for trigger in program.triggered_abilities],
        [ability.source_line for ability in program.activated_abilities],
    )  # _w1g1_abilities (creatures)


@_w1g1_pytest.mark.parametrize(
    "name, printed, with_threshold, always",
    [
        ("Mystic Crusader", (2, 1), (3, 2), ()),
        ("Mystic Enforcer", (3, 3), (6, 6), ()),
        ("Mystic Penitent", (1, 1), (2, 2), ("vigilance",)),
        ("Mystic Zealot", (2, 4), (3, 5), ()),
    ],
)
def test_w1g1_the_mystics_grow_and_fly_with_threshold(
    set_pool, name, printed, with_threshold, always,
):
    """Threshold: as long as there are seven or more cards in your graveyard,
    this creature gets +N/+N and has flying. The condition printed *first*:
    the same static as the trailing order, in two layers — the delta in 7c and
    the keyword in 6 — both there exactly while the count is."""
    assert _w1g1_compile(set_pool("ODY")[name]).supported
    game = _w1g1_table(set_pool)
    mystic = _w1g1_put(game, set_pool, 0, name)

    seen = []
    for count in (6, 7, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append((_w1g1_pt(mystic), game._has_keyword(mystic, "flying")))

    assert seen == [(printed, False), (with_threshold, True), (printed, False)]
    assert all(game._has_keyword(mystic, word) for word in always)


def test_w1g1_the_mystics_keep_the_protection_printed_above_their_threshold_line(
    set_pool,
):
    """Mystic Crusader's protection from black and from red and Mystic
    Enforcer's protection from black are lines of their own: a Terror — a
    black spell — is refused against either, with or without threshold."""
    for name in ("Mystic Crusader", "Mystic Enforcer"):
        game = _w1g1_table(set_pool, ["Terror"], {"B": 2})
        mystic = _w1g1_put(game, set_pool, 0, name)
        for count in (0, 7):
            _w1g1_graveyard(game, set_pool, 0, count)
            refused = game.cast_from_hand(
                0, "Terror", target_permanent_ids=[mystic.permanent_id],
            )
            assert not refused.supported, (name, count)
    game = _w1g1_table(set_pool, ["Lightning Bolt"], {"R": 1})
    crusader = _w1g1_put(game, set_pool, 0, "Mystic Crusader")
    assert not game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[crusader.permanent_id],
    ).supported, "protection from red as well"


def test_w1g1_crashing_centaur_has_shroud_with_threshold_and_tramples_on_request(
    set_pool,
):
    """Crashing Centaur: a green mana and a discard give it trample until end
    of turn, and with threshold it gets +2/+2 and has shroud. The ability
    charges its mana and its discard; the discard itself is a card in the
    graveyard — the seventh here, which is what turns the threshold line on."""
    game = _w1g1_table(set_pool, ["Forest", "Lightning Bolt"], {"G": 1, "R": 1})
    centaur = _w1g1_put(game, set_pool, 0, "Crashing Centaur")
    _w1g1_graveyard(game, set_pool, 0, 6)
    assert _w1g1_pt(centaur) == (3, 4) and not game._has_keyword(centaur, "shroud")

    result = game.activate_permanent_ability(
        0, "Crashing Centaur", ability_index=0, cost_hand_index=0,
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()

    assert game._has_keyword(centaur, "trample")
    assert len(game.players[0].graveyard) == 7
    assert _w1g1_pt(centaur) == (5, 6) and game._has_keyword(centaur, "shroud")
    assert not game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[centaur.permanent_id],
    ).supported, "shroud: it is no longer a legal target"
    refused = game.activate_permanent_ability(0, "Crashing Centaur", ability_index=0)
    assert not refused.supported, "no mana and no second card to discard"


@_w1g1_pytest.mark.parametrize(
    "name, printed, with_threshold",
    [
        ("Childhood Horror", (2, 2), (4, 4)),
        ("Dirty Wererat", (2, 3), (4, 5)),
        ("Frightcrawler", (1, 1), (3, 3)),
    ],
)
def test_w1g1_a_threshold_nightmare_is_bigger_and_cannot_block(
    set_pool, name, printed, with_threshold,
):
    """Threshold: this creature gets +2/+2 and can't block. Driven through the
    declare-blockers step: below threshold the creature blocks a Grizzly
    Bears; at seven cards the same declaration is refused, and the +2/+2 is
    there at the same moment."""
    blocks = []
    for count in (6, 7):
        game = _w1g1_table(set_pool)
        blocker = _w1g1_put(game, set_pool, 1, name)
        attacker = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
        _w1g1_to_declare_attackers(game, graveyards={1: count})
        slot = _w1g1_slot(game, 0, attacker)
        assert game.declare_attackers(0, [slot])[0]
        game.advance_combat_phase()
        declared = game.declare_blockers(1, {_w1g1_slot(game, 1, blocker): slot})
        blocks.append((count, _w1g1_pt(blocker), declared[0]))

    assert blocks == [(6, printed, True), (7, with_threshold, False)]


def test_w1g1_a_threshold_nightmare_may_still_attack(set_pool):
    """The sentence takes blocking away and nothing else: with threshold a
    Childhood Horror attacks as the 4/4 flier it is."""
    game = _w1g1_table(set_pool)
    horror = _w1g1_put(game, set_pool, 0, "Childhood Horror")
    _w1g1_to_declare_attackers(game, graveyards={0: 7})
    assert game.declare_attackers(0, [_w1g1_slot(game, 0, horror)])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    _w1g1_finish_combat(game)
    assert game.players[1].life == 16


def test_w1g1_dirty_wererat_regenerates_for_black_and_a_discard(set_pool):
    """Dirty Wererat's regeneration: the shield is bought with one black mana
    and a card, and a Lightning Bolt that would destroy the 2/3 leaves it
    tapped on the battlefield instead."""
    game = _w1g1_table(set_pool, ["Forest", "Lightning Bolt"], {"B": 1, "R": 1})
    rat = _w1g1_put(game, set_pool, 0, "Dirty Wererat")

    result = game.activate_permanent_ability(
        0, "Dirty Wererat", ability_index=0, cost_hand_index=0,
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert [card.name for card in game.players[0].graveyard] == ["Forest"]
    assert game.players[0].mana_pool["B"] == 0

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[rat.permanent_id],
    ).supported
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    assert game.is_on_battlefield(rat) and rat.tapped


def test_w1g1_frightcrawler_has_fear(set_pool):
    """Fear: a green Grizzly Bears cannot block it and a black Scathe Zombies
    can."""
    game = _w1g1_table(set_pool)
    crawler = _w1g1_put(game, set_pool, 0, "Frightcrawler")
    bears = _w1g1_put(game, set_pool, 1, "Grizzly Bears")
    zombies = _w1g1_put(game, set_pool, 1, "Scathe Zombies")
    _w1g1_to_declare_attackers(game)
    slot = _w1g1_slot(game, 0, crawler)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g1_slot(game, 1, bears): slot})[0]
    assert game.declare_blockers(1, {_w1g1_slot(game, 1, zombies): slot})[0]


def test_w1g1_otarian_juggernaut_must_attack_only_with_threshold(set_pool):
    """Otarian Juggernaut can't be blocked by Walls, and with threshold gets
    +3/+0 and attacks each combat if able. Below threshold its controller may
    keep the 2/3 home; at seven cards an empty declaration is refused
    (CR 508.1d), the 5/3 attacks, and a Wall of Stone may not block it."""
    game = _w1g1_table(set_pool)
    juggernaut = _w1g1_put(game, set_pool, 0, "Otarian Juggernaut")
    _w1g1_to_declare_attackers(game, graveyards={0: 6})
    assert _w1g1_pt(juggernaut) == (2, 3)
    assert game.declare_attackers(0, [])[0]

    game = _w1g1_table(set_pool)
    juggernaut = _w1g1_put(game, set_pool, 0, "Otarian Juggernaut")
    wall = _w1g1_put(game, set_pool, 1, "Wall of Stone")
    _w1g1_to_declare_attackers(game, graveyards={0: 7})
    assert _w1g1_pt(juggernaut) == (5, 3)
    refused = game.declare_attackers(0, [])
    assert not refused[0] and "must attack" in refused[1]
    slot = _w1g1_slot(game, 0, juggernaut)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g1_slot(game, 1, wall): slot})[0]
    assert game.declare_blockers(1, {})[0]
    _w1g1_finish_combat(game)
    assert game.players[1].life == 15


def test_w1g1_stone_tongue_basilisk_lures_every_blocker_with_threshold(set_pool):
    """Threshold: all creatures able to block this creature do so. Below
    threshold the defender may decline; at seven cards no block and one block
    are both refused and only the declaration with every able creature in it
    stands (CR 509.1c)."""
    game = _w1g1_table(set_pool)
    basilisk = _w1g1_put(game, set_pool, 0, "Stone-Tongue Basilisk")
    _w1g1_put(game, set_pool, 1, "Grizzly Bears")
    _w1g1_to_declare_attackers(game, graveyards={0: 6})
    assert game.declare_attackers(0, [_w1g1_slot(game, 0, basilisk)])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]

    game = _w1g1_table(set_pool)
    basilisk = _w1g1_put(game, set_pool, 0, "Stone-Tongue Basilisk")
    bears = _w1g1_put(game, set_pool, 1, "Grizzly Bears")
    giant = _w1g1_put(game, set_pool, 1, "Hill Giant")
    _w1g1_to_declare_attackers(game, graveyards={0: 7})
    slot = _w1g1_slot(game, 0, basilisk)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {})[0]
    assert not game.declare_blockers(1, {_w1g1_slot(game, 1, bears): slot})[0]
    assert game.declare_blockers(
        1, {_w1g1_slot(game, 1, bears): slot, _w1g1_slot(game, 1, giant): slot},
    )[0]


def test_w1g1_stone_tongue_basilisk_destroys_what_it_damaged_at_end_of_combat(
    set_pool,
):
    """Whenever the Basilisk deals combat damage to a creature, that creature
    is destroyed at end of combat. A Wall of Stone survives the 4 damage
    through the damage step and is destroyed by the delayed trigger as combat
    ends."""
    game = _w1g1_table(set_pool)
    basilisk = _w1g1_put(game, set_pool, 0, "Stone-Tongue Basilisk")
    wall = _w1g1_put(game, set_pool, 1, "Wall of Stone")
    _w1g1_to_declare_attackers(game)
    slot = _w1g1_slot(game, 0, basilisk)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {_w1g1_slot(game, 1, wall): slot})[0]
    game.advance_combat_phase()
    _w1g1_resolve_stack(game)
    assert game.is_on_battlefield(wall), "8 toughness: the damage alone does not kill it"

    _w1g1_finish_combat(game)

    assert not game.is_on_battlefield(wall)
    assert [card.name for card in game.players[1].graveyard] == ["Wall of Stone"]


def test_w1g1_wayward_angel_turns_black_and_hungry_with_threshold(set_pool):
    """Threshold: Wayward Angel gets +3/+3, is black, has trample, and has an
    upkeep trigger that sacrifices a creature. One static in four layers.
    Black *instead of* white, not as well as (the card's ruling of
    2004-10-04: "this card is black. It is not white and black"), and the
    quoted trigger is an ability the Angel has only while the count holds."""
    game = _w1g1_table(set_pool)
    angel = _w1g1_put(game, set_pool, 0, "Wayward Angel")
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")

    _w1g1_graveyard(game, set_pool, 0, 6)
    assert _w1g1_pt(angel) == (4, 4) and angel.effective_colors == {"W"}
    assert not game._has_keyword(angel, "trample")
    assert _w1g1_abilities(angel) == ([], [])
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    assert game.is_on_battlefield(bears), "no threshold, no upkeep trigger"

    _w1g1_graveyard(game, set_pool, 0, 7)
    assert _w1g1_pt(angel) == (7, 7) and angel.effective_colors == {"B"}
    assert all(
        game._has_keyword(angel, word) for word in ("flying", "vigilance", "trample")
    )
    assert _w1g1_abilities(angel) == (
        ["At the beginning of your upkeep, sacrifice a creature"], [],
    )
    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()
    assert [p.card.name for p in game.controlled_by(0)] == ["Wayward Angel"]
    assert game.players[0].graveyard[-1].name == "Grizzly Bears"


def test_w1g1_wayward_angels_upkeep_trigger_resolves_after_threshold_is_lost(
    set_pool,
):
    """The trigger is a stack object once it has triggered (CR 603.3): cards
    leaving the graveyard in response take the ability off the Angel — it is a
    4/4 white Angel again — and the sacrifice still happens."""
    game = _w1g1_table(set_pool)
    angel = _w1g1_put(game, set_pool, 0, "Wayward Angel")
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    _w1g1_graveyard(game, set_pool, 0, 7)
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)
    assert len(game.stack) == 1

    del game.players[0].graveyard[3:]
    game.check_state_based_actions()
    assert _w1g1_pt(angel) == (4, 4) and angel.effective_colors == {"W"}
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(bears)


def test_w1g1_a_lace_cast_at_a_threshold_angel_still_wins(set_pool):
    """Layer 5 by timestamp (CR 613.7): the Angel's "is black" has the Angel's
    own timestamp (CR 613.7a), so a Purelace resolved afterwards is the later
    effect and the Angel is white — with its threshold bonus intact."""
    game = _w1g1_table(set_pool, ["Purelace"], {"W": 1})
    angel = _w1g1_put(game, set_pool, 0, "Wayward Angel")
    _w1g1_graveyard(game, set_pool, 0, 7)
    assert angel.effective_colors == {"B"}

    assert game.cast_from_hand(
        0, "Purelace", target_permanent_ids=[angel.permanent_id],
    ).supported
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()

    assert angel.effective_colors == {"W"}
    assert _w1g1_pt(angel) == (7, 7)


def test_w1g1_repentant_vampire_is_white_and_destroys_black_creatures_with_threshold(
    set_pool,
):
    """Threshold: Repentant Vampire is white and has a tap ability that
    destroys target black creature. White instead of black (ruling,
    2004-10-04), and the quoted ability is one the Vampire's controller can
    activate only while it is there: its picker offers the black creature and
    not the white one."""
    game = _w1g1_table(set_pool)
    vampire = _w1g1_put(game, set_pool, 0, "Repentant Vampire")
    zombies = _w1g1_put(game, set_pool, 1, "Scathe Zombies")
    knight = _w1g1_put(game, set_pool, 1, "White Knight")

    _w1g1_graveyard(game, set_pool, 0, 6)
    assert vampire.effective_colors == {"B"} and _w1g1_abilities(vampire)[1] == []
    refused = game.activate_permanent_ability(
        0, "Repentant Vampire", ability_index=0,
        target_permanent_ids=[zombies.permanent_id],
    )
    assert not refused.supported and not vampire.tapped

    _w1g1_graveyard(game, set_pool, 0, 7)
    assert vampire.effective_colors == {"W"} and _w1g1_pt(vampire) == (3, 3)
    assert _w1g1_abilities(vampire)[1] == ["{T}: Destroy target black creature"]
    spec = game.activation_target_spec(0, _w1g1_slot(game, 0, vampire), 0)
    assert [target["name"] for target in spec["valid_targets"]] == ["Scathe Zombies"]
    assert not game.activate_permanent_ability(
        0, "Repentant Vampire", ability_index=0,
        target_permanent_ids=[knight.permanent_id],
    ).supported
    result = game.activate_permanent_ability(
        0, "Repentant Vampire", ability_index=0,
        target_permanent_ids=[zombies.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()

    assert vampire.tapped
    assert [card.name for card in game.players[1].graveyard] == ["Scathe Zombies"]
    assert game.is_on_battlefield(knight)


def test_w1g1_a_white_repentant_vampire_cannot_aim_at_a_black_knight(set_pool):
    """The colour is real, not a label: with threshold the Vampire is a white
    source, and Black Knight's protection from white keeps it out of the
    quoted ability's reach (CR 702.16b)."""
    game = _w1g1_table(set_pool)
    vampire = _w1g1_put(game, set_pool, 0, "Repentant Vampire")
    knight = _w1g1_put(game, set_pool, 1, "Black Knight")
    _w1g1_graveyard(game, set_pool, 0, 7)

    result = game.activate_permanent_ability(
        0, "Repentant Vampire", ability_index=0,
        target_permanent_ids=[knight.permanent_id],
    )

    assert not result.supported and not vampire.tapped


def test_w1g1_repentant_vampire_grows_when_a_creature_it_damaged_dies(set_pool):
    """Whenever a creature dealt damage by the Vampire this turn dies, it gets
    a +1/+1 counter. It kills the Birds of Paradise that blocks it and is a
    4/4 afterwards."""
    game = _w1g1_table(set_pool)
    vampire = _w1g1_put(game, set_pool, 0, "Repentant Vampire")
    birds = _w1g1_put(game, set_pool, 1, "Birds of Paradise")
    _w1g1_to_declare_attackers(game)
    slot = _w1g1_slot(game, 0, vampire)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {_w1g1_slot(game, 1, birds): slot})[0]
    _w1g1_finish_combat(game)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(birds)
    assert _w1g1_pt(vampire) == (4, 4)


def test_w1g1_bloodcurdler_mills_into_threshold_and_exiles_its_way_out(set_pool):
    """Bloodcurdler mills a card each upkeep, and with threshold gets +1/+1
    and has an end-step trigger that exiles two cards from its controller's
    graveyard. With six cards the upkeep mill is the seventh: the 1/1 is a 2/2
    with a trigger it did not have a moment ago. That trigger exiles two —
    exactly two — which takes the count to five and the ability away again."""
    assert _w1g1_compile(set_pool("ODY")["Bloodcurdler"]).supported
    game = _w1g1_table(set_pool)
    curdler = _w1g1_put(game, set_pool, 0, "Bloodcurdler")
    _w1g1_graveyard(game, set_pool, 0, 6)
    assert _w1g1_pt(curdler) == (1, 1) and game._has_keyword(curdler, "flying")
    assert len(_w1g1_abilities(curdler)[0]) == 1
    game.active_player_index = 0

    game.resolve_end_step(0)
    _w1g1_resolve_stack(game)
    assert len(game.players[0].graveyard) == 6, "no threshold, no end-step trigger"

    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    assert len(game.players[0].graveyard) == 7 and len(game.players[0].library) == 9
    assert _w1g1_pt(curdler) == (2, 2)
    assert _w1g1_abilities(curdler)[0][-1] == (
        "At the beginning of your end step, exile two cards from your graveyard"
    )

    game.resolve_end_step(0)
    assert len(game.stack) == 1, "the granted trigger is a stack object"
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.check_state_based_actions()

    assert len(game.players[0].graveyard) == 5 and len(game.players[0].exile) == 2
    assert _w1g1_pt(curdler) == (1, 1)
    assert len(_w1g1_abilities(curdler)[0]) == 1


def test_w1g1_bloodcurdlers_exile_asks_a_person_for_exactly_two_cards(set_pool):
    """The end-step exile is its controller's choice: an interactive seat is
    asked which two (the ``graveyard_exile_pick`` prompt), one card is not an
    answer, and the two named are the two that go."""
    game = _w1g1_table(set_pool)
    game.interactive_seats = {0}
    _w1g1_put(game, set_pool, 0, "Bloodcurdler")
    lea = set_pool("LEA")
    game.players[0].graveyard[:] = [lea["Forest"]] * 6 + [lea["Swamp"], lea["Island"]]
    game.check_state_based_actions()
    game.active_player_index = 0

    game.resolve_end_step(0)
    while game.stack and game.resolve_top_of_stack():
        pass
    (prompt,) = game.pending_choices_of("graveyard_exile_pick")
    assert prompt.player_index == 0
    assert (prompt.data["count"], prompt.data["up_to"]) == (2, False)

    assert not game.confirm_graveyard_exile_pick(0, [7])
    assert game.confirm_graveyard_exile_pick(0, [6, 7])
    _w1g1_resolve_stack(game)

    assert sorted(card.name for card in game.players[0].exile) == ["Island", "Swamp"]
    assert len(game.players[0].graveyard) == 6


def test_w1g1_chlorophant_grows_twice_an_upkeep_with_threshold(set_pool):
    """Chlorophant may take a +1/+1 counter each upkeep, and with threshold
    has a second ability that may take another. One optional trigger below
    threshold and two at it — "another" is one more counter, from a second
    ability — so the 1/1 is a 2/2 after the first upkeep and a 4/4 after the
    second."""
    assert _w1g1_compile(set_pool("ODY")["Chlorophant"]).supported
    game = _w1g1_table(set_pool)
    chlorophant = _w1g1_put(game, set_pool, 0, "Chlorophant")
    game.active_player_index = 0

    seen = []
    for count in (6, 7):
        _w1g1_graveyard(game, set_pool, 0, count)
        game.resolve_upkeep(0)
        offers = len(game.pending_choices)
        _w1g1_resolve_stack(game)
        game.auto_resolve_pending_choices()
        _w1g1_resolve_stack(game)
        game.check_state_based_actions()
        seen.append((offers, _w1g1_pt(chlorophant)))

    assert seen == [(1, (2, 2)), (2, (4, 4))]

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack

_W1G2_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9, "C": 9}

#: The six creatures whose last ability is "Threshold — <cost>: <effect>.
#: Activate only if there are seven or more cards in your graveyard.", with
#: the mana that ability's cost spends.
_W1G2_THRESHOLD_CREATURES = [
    ("Cabal Inquisitor", 2),
    ("Chainflinger", 3),
    ("Hallowed Healer", 0),
    ("Infected Vermin", 4),
    ("Krosan Avenger", 2),
    ("Nomad Decoy", 2),
]


def _w1g2_duel(set_pool, *, graveyard=0, opponent_hand=0):
    """A two-seat game that **charges mana**, seat 0's main phase, with
    *graveyard* cards in seat 0's graveyard. Costs are enforced because the
    refusal these tests are about is "nothing was paid": a rig that waives
    mana cannot tell a refused activation from a free one."""
    lea = set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState("Caster", library=[lea["Forest"]] * 10),
        _w1g2_PlayerState(
            "Bystander", library=[lea["Forest"]] * 10,
            hand=[lea["Island"]] * opponent_hand,
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G2_RICH)
    game.players[0].graveyard.extend([lea["Grizzly Bears"]] * graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game  # _w1g2_duel


def _w1g2_put(game, seat, card):
    """*card* onto *seat*'s battlefield without being cast, untapped and
    ready to act."""
    permanent = _w1g2_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put


def _w1g2_floating(game, seat=0) -> int:
    return sum(game.players[seat].mana_pool.values())  # _w1g2_floating


def _w1g2_threshold_index(card) -> int:
    """Which of *card*'s activated abilities prints the threshold clause."""
    abilities = _w1g2_compile(card).activated_abilities
    (index,) = [
        position for position, ability in enumerate(abilities)
        if "seven or more cards in your graveyard" in ability.source_line
    ]
    return index  # _w1g2_threshold_index


def _w1g2_aim(name, bears):
    """The announcement each threshold creature's ability needs."""
    if name in ("Chainflinger", "Cabal Inquisitor"):
        return {"target_player_index": 1}
    if name == "Hallowed Healer":
        return {"target_player_index": 0}
    if name == "Nomad Decoy":
        return {"target_permanent_ids": [bear.permanent_id for bear in bears]}
    return {}  # _w1g2_aim


@_w1g2_pytest.mark.parametrize("name, price", _W1G2_THRESHOLD_CREATURES)
def test_a_threshold_ability_is_refused_at_six_cards_and_nothing_is_paid(
    set_pool, name, price,
):
    """"Activate only if there are seven or more cards in your graveyard."
    With six the activation is refused before it begins (CR 602.5): no mana
    leaves the pool, the creature is not tapped, no card is exiled, and nothing
    reaches the stack. With seven the same announcement is accepted and its
    printed mana is spent."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    card = ody[name]
    assert _w1g2_compile(card).supported
    index = _w1g2_threshold_index(card)

    for graveyard, allowed in ((6, False), (7, True)):
        game = _w1g2_duel(set_pool, graveyard=graveyard, opponent_hand=2)
        source = _w1g2_put(game, 0, card)
        bears = [_w1g2_put(game, 1, lea["Grizzly Bears"]) for _ in range(2)]
        before = _w1g2_floating(game)

        result = game.queue_permanent_ability(
            0, name, ability_index=index, **_w1g2_aim(name, bears),
        )

        assert result.supported is allowed, (graveyard, result.details)
        if allowed:
            assert before - _w1g2_floating(game) == price
            assert len(game.stack) == 1
            continue
        assert "seven or more cards in your graveyard" in result.details
        assert _w1g2_floating(game) == before
        assert not source.tapped and game.stack == []
        assert len(game.players[0].graveyard) == 6
        assert game.players[0].exile == []


def test_chainflinger_pings_for_one_and_for_two_only_at_threshold(set_pool):
    """"{1}{R}, {T}: This creature deals 1 damage to any target." has no
    clause and works with an empty graveyard; the threshold ability deals 2."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=0)
    _w1g2_put(game, 0, ody["Chainflinger"])
    assert game.activate_permanent_ability(
        0, "Chainflinger", ability_index=0, target_player_index=1,
    ).supported
    assert game.players[1].life == 19

    game = _w1g2_duel(set_pool, graveyard=7)
    _w1g2_put(game, 0, ody["Chainflinger"])
    assert game.activate_permanent_ability(
        0, "Chainflinger", ability_index=1, target_player_index=1,
    ).supported
    assert game.players[1].life == 18


def test_threshold_is_asked_as_the_ability_is_activated_not_as_it_resolves(set_pool):
    """A restriction gates *beginning* to activate (CR 602.5). Once
    Chainflinger's threshold ability is on the stack, a graveyard emptied in
    response does not take it back — and neither does the creature leaving
    (CR 113.7a: an ability on the stack is independent of its source)."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=7)
    flinger = _w1g2_put(game, 0, ody["Chainflinger"])
    assert game.queue_permanent_ability(
        0, "Chainflinger", ability_index=1, target_player_index=1,
    ).supported

    game.players[0].graveyard.clear()
    game.remove_from_battlefield(flinger)
    _w1g2_resolve_stack(game)

    assert game.players[1].life == 18


def test_hallowed_healer_prevents_two_and_four_at_threshold(set_pool):
    """"{T}: Prevent the next 2 damage that would be dealt to any target this
    turn." / "Threshold — {T}: Prevent the next 4 damage …". Five damage dealt
    through each shield: three gets past the first, one past the second."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    for graveyard, ability, lost in ((0, 0, 3), (7, 1, 1)):
        game = _w1g2_duel(set_pool, graveyard=graveyard)
        _w1g2_put(game, 0, ody["Hallowed Healer"])
        assert game.activate_permanent_ability(
            0, "Hallowed Healer", ability_index=ability, target_player_index=0,
        ).supported
        game._deal_damage_to_player(game.players[0], 5, source=lea["Lightning Bolt"])
        assert game.players[0].life == 20 - lost, (graveyard, ability)


def test_hallowed_healers_threshold_shield_can_cover_a_creature(set_pool):
    """"…to **any target**": the shield is as happy on a creature as on a
    face, and the picker offers both."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7)
    healer = _w1g2_put(game, 0, ody["Hallowed Healer"])
    wurm = _w1g2_put(game, 0, lea["Craw Wurm"])
    spec = game.activation_target_spec(
        0, game.battlefield_index_of(healer), ability_index=1,
    )
    assert spec["kind"] == "any" and spec["requires_target"]
    assert game.activate_permanent_ability(
        0, "Hallowed Healer", ability_index=1,
        target_permanent_ids=[wurm.permanent_id],
    ).supported
    game._mark_damage_on_permanent(wurm, 7, source=lea["Lightning Bolt"])
    game._settle()
    assert game.is_on_battlefield(wurm), "7 less 4 prevented is not lethal to a 6/4"


def test_infected_vermin_sweeps_for_one_and_for_three_at_threshold(set_pool):
    """"{2}{B}: This creature deals 1 damage to each creature and each
    player." / "Threshold — {3}{B}: … 3 damage …". The Vermin is a creature
    too, so either one kills it; the big one takes the Bears with it."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=0)
    vermin = _w1g2_put(game, 0, ody["Infected Vermin"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.activate_permanent_ability(0, "Infected Vermin", ability_index=0).supported
    assert [p.life for p in game.players] == [19, 19]
    assert not game.is_on_battlefield(vermin), "a 1/1 dealt 1"
    assert game.is_on_battlefield(bears)

    game = _w1g2_duel(set_pool, graveyard=7)
    vermin = _w1g2_put(game, 0, ody["Infected Vermin"])
    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])
    assert game.activate_permanent_ability(0, "Infected Vermin", ability_index=1).supported
    assert [p.life for p in game.players] == [17, 17]
    assert not game.is_on_battlefield(vermin) and not game.is_on_battlefield(bears)
    assert game.is_on_battlefield(wurm), "a 6/4 survives 3"


def test_krosan_avenger_regenerates_only_at_threshold(set_pool):
    """"Threshold — {1}{G}: Regenerate this creature." The shield it buys
    replaces the next destruction: lethal damage leaves it tapped and alive."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7)
    avenger = _w1g2_put(game, 0, ody["Krosan Avenger"])
    assert game._has_keyword(avenger, "trample")
    assert game.activate_permanent_ability(0, "Krosan Avenger").supported

    game._mark_damage_on_permanent(avenger, 3, source=lea["Lightning Bolt"])
    game._settle()

    assert game.is_on_battlefield(avenger) and avenger.tapped


def test_nomad_decoy_taps_one_and_exactly_two_at_threshold(set_pool):
    """"{W}, {T}: Tap target creature." / "Threshold — {W}{W}, {T}: Tap **two**
    target creatures." A printed count is a count (CR 601.2c): the threshold
    ability named at one creature is refused with nothing paid."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_duel(set_pool, graveyard=7)
    decoy = _w1g2_put(game, 0, ody["Nomad Decoy"])
    first, second = (_w1g2_put(game, 1, lea["Grizzly Bears"]) for _ in range(2))
    before = _w1g2_floating(game)

    short = game.queue_permanent_ability(
        0, "Nomad Decoy", ability_index=1, target_permanent_ids=[first.permanent_id],
    )
    assert not short.supported, short.details
    assert _w1g2_floating(game) == before and not decoy.tapped

    assert game.activate_permanent_ability(
        0, "Nomad Decoy", ability_index=1,
        target_permanent_ids=[first.permanent_id, second.permanent_id],
    ).supported
    assert first.tapped and second.tapped and decoy.tapped
    assert before - _w1g2_floating(game) == 2

    game = _w1g2_duel(set_pool, graveyard=0)
    _w1g2_put(game, 0, ody["Nomad Decoy"])
    lone = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.activate_permanent_ability(
        0, "Nomad Decoy", ability_index=0, target_permanent_ids=[lone.permanent_id],
    ).supported
    assert lone.tapped


def test_cabal_inquisitor_may_pay_its_way_below_threshold(set_pool):
    """"Threshold — {1}{B}, {T}, Exile two cards from your graveyard: Target
    player discards a card." With exactly seven cards the clause holds when the
    activation begins; the cost then exiles two of them, and the ability still
    resolves with five in the graveyard — nothing re-asks the clause."""
    ody = set_pool("ODY")
    game = _w1g2_duel(set_pool, graveyard=7, opponent_hand=2)
    inquisitor = _w1g2_put(game, 0, ody["Cabal Inquisitor"])

    assert game.queue_permanent_ability(
        0, "Cabal Inquisitor", target_player_index=1,
    ).supported
    assert len(game.players[0].graveyard) == 5 and len(game.players[0].exile) == 2
    assert inquisitor.tapped

    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 1


def test_cabal_inquisitor_is_sorcery_speed_as_well_as_threshold(set_pool):
    """"Activate only as a sorcery **and only if** there are seven or more
    cards in your graveyard." Two restrictions in one sentence, both required:
    with seven cards it is still refused on the opponent's turn and with
    something on the stack, and nothing is exiled for either refusal."""
    ody, lea = set_pool("ODY"), set_pool("LEA")

    game = _w1g2_duel(set_pool, graveyard=7, opponent_hand=2)
    _w1g2_put(game, 0, ody["Cabal Inquisitor"])
    game.active_player_index = 1
    theirs = game.queue_permanent_ability(0, "Cabal Inquisitor", target_player_index=1)
    assert not theirs.supported and "sorcery" in theirs.details
    assert len(game.players[0].graveyard) == 7

    game = _w1g2_duel(set_pool, graveyard=7, opponent_hand=2)
    _w1g2_put(game, 0, ody["Cabal Inquisitor"])
    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    stacked = game.queue_permanent_ability(0, "Cabal Inquisitor", target_player_index=1)
    assert not stacked.supported and "sorcery" in stacked.details
    assert len(game.players[0].graveyard) == 7 and game.players[0].exile == []

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game, PlayerState as _w1g4_PlayerState
from engine.counted_names import card_answers_to_name as _w1g4_answers_to_name
from engine.counted_names import counts_as_line as _w1g4_counts_as_line
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.oracle import simple_card_keywords as _w1g4_simple_keywords
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names (ODY over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g4_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g4_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g4_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- Pardic Firecat / Diligent Farmhand: a card that counts as another's name -

def test_pardic_firecat_in_a_graveyard_is_a_flame_burst_to_flame_burst(set_pool):
    """2 plus the real Flame Burst plus a Firecat in each graveyard is 5. The
    count is of cards, so each Firecat is one."""
    game = _w1g4_duel(
        set_pool, hand0=["Flame Burst"], gy0=["Pardic Firecat", "Flame Burst"],
        gy1=["Pardic Firecat", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 15


def test_pardic_firecat_counts_only_while_it_is_in_a_graveyard(set_pool):
    """"If this card is in a graveyard" (CR 113.6b): one on the battlefield and
    one in a hand are not cards named Flame Burst to anything."""
    game = _w1g4_duel(
        set_pool, hand0=["Flame Burst", "Pardic Firecat"], bf1=["Pardic Firecat"],
    )
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 18


def test_each_helper_counts_for_its_own_burst_and_no_other(set_pool):
    """A Firecat and a Farmhand in one graveyard: Muscle Burst sees the
    Farmhand (3 + 1) and Flame Burst sees the Firecat (2 + 1)."""
    game = _w1g4_duel(
        set_pool, hand0=["Muscle Burst", "Flame Burst"],
        gy0=["Pardic Firecat", "Diligent Farmhand"], bf0=["Grizzly Bears"],
    )
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 17


def test_an_ability_counting_flame_bursts_does_not_count_a_firecat(set_pool):
    """"Effects from **spells** named Flame Burst": an activated ability asking
    the same count is not one, whatever its source is called."""
    counter = _w1g4_mk_card(
        "Burst Counter", "{R}", "Creature — Goblin",
        "{T}: This creature deals X damage to any target, where X is the "
        "number of cards named Flame Burst in all graveyards.",
    )
    assert _w1g4_compile(counter).supported
    game = _w1g4_duel(set_pool, gy0=["Pardic Firecat", "Flame Burst"])
    perm = _w1g4_Permanent(card=counter)
    game._put_permanent_onto_battlefield(0, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(
        0, "Burst Counter", target_player_index=1
    ).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 19


def test_the_counts_as_line_is_payload_not_two_card_names(set_pool):
    """An invented pair: a spell nobody printed and the helper that counts for
    it. Nothing in the engine knows either name."""
    burst = _w1g4_mk_card(
        "Frost Burst", "{U}", "Instant",
        "Frost Burst deals X damage to any target, where X is 1 plus the "
        "number of cards named Frost Burst in all graveyards.",
    )
    helper = _w1g4_mk_card(
        "Frost Otter", "{U}", "Creature — Otter",
        "If this card is in a graveyard, effects from spells named Frost Burst "
        "count it as a card named Frost Burst.",
    )
    assert _w1g4_compile(burst).supported and _w1g4_compile(helper).supported
    game = _w1g4_duel(set_pool, gy1=["Pardic Firecat"])
    game.players[0].hand.append(burst)
    game.players[1].graveyard.extend([helper, helper])
    assert game.cast_from_hand(0, "Frost Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 17


@_w1g4_pytest.mark.parametrize("line", [
    # A zone the table has no row for.
    "If this card is in your hand, effects from spells named Flame Burst "
    "count it as a card named Flame Burst.",
    # A second sentence on the line: a registry claims a whole line or none.
    "If this card is in a graveyard, effects from spells named Flame Burst "
    "count it as a card named Flame Burst. Draw a card.",
    "If this card is in a graveyard, effects count it as a card named Flame Burst.",
])
def test_a_counts_as_line_the_table_cannot_read_is_refused(line):
    """The refusing half: a creature whose line this module does not carry out
    in full is unsupported, never admitted with the sentence doing nothing."""
    assert _w1g4_counts_as_line(line) is None
    card = _w1g4_mk_card("Odd Cat", "{R}", "Creature — Cat", line)
    assert not _w1g4_compile(card).supported


def test_a_name_is_a_set_of_names_and_the_helper_gives_none(set_pool):
    """`card_answers_to_name` is CR 201.2a for a reader that is not a spell's
    effect: the Firecat is named Pardic Firecat and nothing else."""
    firecat = set_pool("ODY")["Pardic Firecat"]
    assert _w1g4_answers_to_name(firecat, "pardic firecat")
    assert not _w1g4_answers_to_name(firecat, "Flame Burst")
    assert not _w1g4_answers_to_name(firecat, "Flame Burst", zone="graveyard")
    assert not _w1g4_answers_to_name(
        firecat, "Flame Burst", zone="hand", effect_spell="Flame Burst"
    )
    assert not _w1g4_answers_to_name(
        firecat, "Muscle Burst", zone="graveyard", effect_spell="Muscle Burst"
    )
    assert _w1g4_answers_to_name(
        firecat, "flame burst", zone="graveyard", effect_spell="Flame Burst"
    )
    assert not _w1g4_answers_to_name(firecat, "", zone="graveyard")


def test_pardic_firecat_is_a_hasty_creature_with_a_line_of_its_own(set_pool):
    firecat = set_pool("ODY")["Pardic Firecat"]
    assert _w1g4_simple_keywords(firecat) is None, "not a keywords-only auto-pass"
    game = _w1g4_duel(set_pool)
    perm = _w1g4_Permanent(card=firecat)
    game._put_permanent_onto_battlefield(0, perm, None)
    assert game._has_keyword(perm, "haste")
    assert (perm.effective_power, perm.effective_toughness) == (2, 3)


def test_diligent_farmhand_is_sacrificed_for_a_tapped_basic_land(set_pool):
    game = _w1g4_duel(
        set_pool, bf0=["Diligent Farmhand"],
        lib0=["Grizzly Bears", "Bayou", "Forest", "Island"],
    )
    assert game.activate_permanent_ability(0, "Diligent Farmhand").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    (land,) = list(game.controlled_by(0))
    assert land.card.name == "Forest" and land.tapped
    assert _w1g4_names(game.players[0].graveyard) == ["Diligent Farmhand"]
    assert len(game.players[0].library) == 3


def test_diligent_farmhand_offers_only_basic_lands_to_a_person(set_pool):
    """The nonbasic land and the creature are in the library and not in the
    search: the prompt carries the restriction, so the picker cannot offer
    them and an answer naming one is refused."""
    game = _w1g4_duel(
        set_pool, bf0=["Diligent Farmhand"],
        lib0=["Grizzly Bears", "Bayou", "Forest"],
    )
    game.interactive_seats.add(0)
    assert game.activate_permanent_ability(0, "Diligent Farmhand").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["restrictions"] == {"supertypes": ["basic"]}
    assert prompt.data["card_type"] == "land" and prompt.data["enters_tapped"]


def test_diligent_farmhand_finding_no_basic_land_still_shuffles_and_is_gone(set_pool):
    game = _w1g4_duel(
        set_pool, bf0=["Diligent Farmhand"], lib0=["Grizzly Bears", "Bayou"],
    )
    assert game.activate_permanent_ability(0, "Diligent Farmhand").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert list(game.controlled_by(0)) == []
    assert sorted(_w1g4_names(game.players[0].library)) == ["Bayou", "Grizzly Bears"]


# --- The five -vores: a P/T counted over every graveyard (CR 604.3) ----------

@_w1g4_pytest.mark.parametrize("vore, counted, keyword", [
    ("Cantivore", "Animate Dead", "vigilance"),
    ("Cognivore", "Giant Growth", "flying"),
    ("Magnivore", "Fireball", "haste"),
    ("Mortivore", "Grizzly Bears", None),
    ("Terravore", "Forest", "trample"),
])
def test_a_vore_is_as_big_as_its_card_type_in_all_graveyards(
    set_pool, vore, counted, keyword
):
    """Two in its controller's graveyard and one in the opponent's: 3/3. A
    card of another type in each pile is not counted; a fourth arriving is
    (CR 611.3a: the count is never locked in); with none it is 0/0 and put
    into its owner's graveyard (CR 704.5f)."""
    game = _w1g4_duel(
        set_pool, gy0=[counted, counted, "Black Lotus"], gy1=[counted, "Black Lotus"],
        bf0=[vore],
    )
    perm = _w1g4_on_board(game, 0, vore)
    game.check_state_based_actions()
    assert (perm.effective_power, perm.effective_toughness) == (3, 3)
    if keyword:
        assert game._has_keyword(perm, keyword)
    game.players[1].graveyard.append(set_pool("LEA")[counted])
    game.check_state_based_actions()
    assert (perm.effective_power, perm.effective_toughness) == (4, 4)
    game.players[0].graveyard.clear()
    game.players[1].graveyard.clear()
    game.check_state_based_actions()
    assert not game.is_on_battlefield(perm)
    assert _w1g4_names(game.players[0].graveyard) == [vore]


def test_mortivore_regenerates_for_one_black_mana(set_pool):
    game = _w1g4_duel(
        set_pool, gy0=["Grizzly Bears", "Grizzly Bears"], bf0=["Mortivore"],
    )
    mortivore = _w1g4_on_board(game, 0, "Mortivore")
    assert game.activate_permanent_ability(0, "Mortivore").supported
    _w1g4_resolve_stack(game)
    assert any("regeneration shield" in line for line in game.log)
    assert game.is_on_battlefield(mortivore)


# --- Dwarven Recruiter ---------------------------------------------------------

def test_dwarven_recruiter_stacks_every_dwarf_on_top_of_a_shuffled_library(set_pool):
    """Its entry trigger is a stack object; the search finds the Dwarf cards
    and nothing else, reveals them (the log may name them), and they are the
    top of the library afterwards."""
    game = _w1g4_duel(
        set_pool, hand0=["Dwarven Recruiter"],
        lib0=["Forest", "Dwarven Warriors", "Grizzly Bears",
              "Dwarven Demolition Team", "Island"],
    )
    assert game.queue_from_hand(0, "Dwarven Recruiter").supported
    game.resolve_top_of_stack()
    assert [item.card.name for item in game.stack] == ["Dwarven Recruiter"]
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    library = _w1g4_names(game.players[0].library)
    assert sorted(library[:2]) == ["Dwarven Demolition Team", "Dwarven Warriors"]
    assert sorted(library[2:]) == ["Forest", "Grizzly Bears", "Island"]
    assert any(line.startswith("P0 revealed") for line in game.log)


def test_dwarven_recruiter_asks_a_person_for_up_to_every_dwarf(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Dwarven Recruiter"],
        lib0=["Forest", "Dwarven Warriors", "Dwarven Demolition Team"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Dwarven Recruiter").supported
    game.resolve_top_of_stack()
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["restrictions"] == {"subtypes": ["dwarf"]}
    assert prompt.data["up_to"] and prompt.data["count"] == 2
    assert prompt.data["reveal"] and prompt.data["destination"] == "library_top"

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), their_library=(),
    hand=(),
):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; the returned game has not started a turn."""
    def board(cards):
        permanents = [_W1G6Permanent(card=card) for card in cards]
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
        return permanents

    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", battlefield=board(mine), graveyard=list(yard),
            library=list(library), hand=list(hand), life=20,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=board(theirs), graveyard=list(their_yard),
            library=list(their_library), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    return game  # _w1g6_game


def _w1g6_named(game, seat, name):
    return next(
        permanent for permanent in game.controlled_by(seat)
        if permanent.card.name == name
    )  # _w1g6_named


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


# --- Zombie Assassin --------------------------------------------------------
# "{T}, Exile two cards from your graveyard and this creature: Destroy target
# nonblack creature. It can't be regenerated." A chosen set and the source
# under one printed verb — Sandstone Deadfall's "two lands and this artifact"
# with the exile's verb, and read by the charger through the same reader.

def test_w1g6_zombie_assassin_exiles_two_cards_and_itself(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    cost = _w1g6_compile(ody["Zombie Assassin"]).activated_abilities[0].cost
    assert cost.requires_tap and cost.exile_self
    assert (cost.exile_zone, cost.exile_zone_owner, cost.exile_count) == (
        "graveyard", "you", 2,
    )

    game = _w1g6_game(
        mine=[ody["Zombie Assassin"]],
        theirs=[lea["Grizzly Bears"], lea["Drudge Skeletons"]],
        yard=[lea["Forest"], lea["Forest"], lea["Lightning Bolt"]],
    )
    game.start_turn(0)
    bears = _w1g6_named(game, 1, "Grizzly Bears")

    # The payer names the Bolt; the second card is the first other one.
    used = game.activate_permanent_ability(
        0, "Zombie Assassin", target_permanent_ids=[bears.permanent_id],
        cost_permanent_index=2,
    )

    assert used.supported, used.details
    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Forest"], "exactly two of the three left"
    assert sorted(_w1g6_pile(game.players[0], "exile")) == [
        "Forest", "Lightning Bolt", "Zombie Assassin",
    ]
    assert _w1g6_names(game, 1) == ["Drudge Skeletons"]
    assert _w1g6_pile(game.players[1]) == ["Grizzly Bears"]


@_w1g6_pytest.mark.parametrize(
    "yard_size, tapped, named_slot, reason",
    [
        (1, False, None, "nothing available to exile"),
        (2, True, None, "already tapped"),
        (2, False, 5, "no card at graveyard position 5"),
    ],
)
def test_w1g6_zombie_assassin_refusals_pay_nothing(
    set_pool, yard_size, tapped, named_slot, reason
):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Zombie Assassin"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Forest"]] * yard_size,
    )
    game.start_turn(0)
    _w1g6_named(game, 0, "Zombie Assassin").tapped = tapped
    bears = _w1g6_named(game, 1, "Grizzly Bears")

    refused = game.activate_permanent_ability(
        0, "Zombie Assassin", target_permanent_ids=[bears.permanent_id],
        cost_permanent_index=named_slot,
    )

    assert not refused.supported
    assert reason in refused.details
    assert _w1g6_names(game, 0) == ["Zombie Assassin"]
    assert len(game.players[0].graveyard) == yard_size
    assert not game.players[0].exile
    assert _w1g6_names(game, 1) == ["Grizzly Bears"]


def test_w1g6_zombie_assassin_cannot_be_aimed_at_a_black_creature(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Zombie Assassin"]], theirs=[lea["Drudge Skeletons"]],
        yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    skeletons = _w1g6_named(game, 1, "Drudge Skeletons")

    refused = game.activate_permanent_ability(
        0, "Zombie Assassin", target_permanent_ids=[skeletons.permanent_id]
    )

    assert not refused.supported
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile


# --- Painbringer ------------------------------------------------------------
# "{T}, Exile any number of cards from your graveyard: Target creature gets
# -X/-X until end of turn, where X is the number of cards exiled this way."
# The count is the payer's (CR 601.2b) and is named by graveyard slot; X is
# read back off what the cost ate, not off any zone.

def test_w1g6_painbringer_shrinks_by_the_cards_its_payer_names(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    cost = _w1g6_compile(ody["Painbringer"]).activated_abilities[0].cost
    assert (cost.exile_zone, cost.exile_zone_owner, cost.exile_count) == (
        "graveyard", "you", "any",
    )

    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Craw Wurm"]],
        yard=[lea["Forest"], lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
    )
    game.start_turn(0)
    wurm = _w1g6_named(game, 1, "Craw Wurm")

    used = game.activate_permanent_ability(
        0, "Painbringer", target_permanent_ids=[wurm.permanent_id],
        cost_graveyard_indices=[0, 2, 3],
    )

    assert used.supported, used.details
    # One of the two Forests — one object in the pile twice — and exactly one.
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert sorted(_w1g6_pile(game.players[0], "exile")) == [
        "Forest", "Hill Giant", "Lightning Bolt",
    ]
    assert (wurm.effective_power, wurm.effective_toughness) == (3, 1)


def test_w1g6_painbringer_naming_no_cards_pays_the_cost_and_shrinks_by_zero(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Craw Wurm"]],
        yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    wurm = _w1g6_named(game, 1, "Craw Wurm")

    used = game.activate_permanent_ability(
        0, "Painbringer", target_permanent_ids=[wurm.permanent_id]
    )

    # Zero is a number: nothing is defaulted, so no graveyard is eaten for a
    # seat that named nothing.
    assert used.supported, used.details
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)
    assert _w1g6_named(game, 0, "Painbringer").tapped


@_w1g6_pytest.mark.parametrize(
    "named, reason",
    [([0, 5], "no card at graveyard position 5"), ([1, 1], "more than once")],
)
def test_w1g6_painbringer_an_unpayable_announcement_is_refused_with_nothing_paid(
    set_pool, named, reason
):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Craw Wurm"]],
        yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    wurm = _w1g6_named(game, 1, "Craw Wurm")

    refused = game.activate_permanent_ability(
        0, "Painbringer", target_permanent_ids=[wurm.permanent_id],
        cost_graveyard_indices=named,
    )

    assert not refused.supported and reason in refused.details
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile
    assert not _w1g6_named(game, 0, "Painbringer").tapped


def test_w1g6_painbringer_kills_what_it_shrinks_to_nothing(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Painbringer"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Forest"]] * 3,
    )
    game.start_turn(0)
    bears = _w1g6_named(game, 1, "Grizzly Bears")

    queued = game.queue_permanent_ability(
        0, "Painbringer", target_permanent_ids=[bears.permanent_id],
        cost_graveyard_indices=[0, 1],
    )
    assert queued.details == "queued"
    # The cost is paid before the ability is on the stack (CR 601.2h)…
    assert len(game.players[0].exile) == 2
    _w1g6_resolve_stack(game)
    game.check_state_based_actions()

    # …and X is still two when it resolves, with those cards long gone.
    assert _w1g6_names(game, 1) == []
    assert _w1g6_pile(game.players[1]) == ["Grizzly Bears"]


def test_w1g6_the_exile_cost_picker_offers_every_card_not_only_creatures(set_pool):
    """"Exile two cards from your graveyard" names no type, and a graveyard
    spec that names none is read as "a creature card". The picker offered a
    pile of lands nothing to click for a cost the charger takes any card for."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    for name, index in (("Psychatog", 1), ("Sarcatog", 0), ("Painbringer", 0)):
        game = _w1g6_game(
            mine=[ody[name]], theirs=[lea["Grizzly Bears"]],
            yard=[lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
            their_yard=[lea["Forest"]],
        )
        game.start_turn(0)
        spec = game.activation_target_spec(0, 0, ability_index=index)
        cost_spec = spec.get("cost_spec", spec)
        assert cost_spec["exile_cost"] and cost_spec["any_card"], (name, cost_spec)
        offered = [
            (entry["seat"], entry["name"]) for entry in cost_spec["valid_targets"]
        ]
        # The payer's own pile, all of it, and nobody else's.
        assert offered == [
            (0, "Forest"), (0, "Lightning Bolt"), (0, "Hill Giant"),
        ], (name, offered)
    assert cost_spec.get("any_number") is True and "count" not in cost_spec


# --- Psychatog, Sarcatog ----------------------------------------------------
# "Exile two cards from your graveyard: This creature gets +1/+1 until end of
# turn." Driven: two cards or nothing, the two the payer names.

def test_w1g6_psychatog_eats_the_two_cards_named_and_refuses_one(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Psychatog"]], hand=[lea["Forest"]],
        yard=[lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
    )
    game.start_turn(0)
    tog = _w1g6_named(game, 0, "Psychatog")

    grown = game.activate_permanent_ability(
        0, "Psychatog", ability_index=1, cost_graveyard_indices=[1, 2]
    )
    assert grown.supported, grown.details
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert (tog.effective_power, tog.effective_toughness) == (2, 3)

    # One card left: no payment of a two-card cost (CR 601.2h).
    refused = game.activate_permanent_ability(0, "Psychatog", ability_index=1)
    assert not refused.supported
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert (tog.effective_power, tog.effective_toughness) == (2, 3)

    # The discard half feeds the graveyard the exile half eats.
    fed = game.activate_permanent_ability(
        0, "Psychatog", ability_index=0, cost_hand_index=0
    )
    assert fed.supported, fed.details
    assert not game.players[0].hand and len(game.players[0].graveyard) == 2
    assert (tog.effective_power, tog.effective_toughness) == (3, 4)

    too_many = game.activate_permanent_ability(
        0, "Psychatog", ability_index=1, cost_graveyard_indices=[0, 1, 0]
    )
    assert not too_many.supported
    assert len(game.players[0].graveyard) == 2


def test_w1g6_sarcatog_pays_each_ability_with_its_own_resource(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Sarcatog"], lea["Sol Ring"]], yard=[lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)
    tog = _w1g6_named(game, 0, "Sarcatog")

    assert game.activate_permanent_ability(0, "Sarcatog", ability_index=0).supported
    assert not game.players[0].graveyard and len(game.players[0].exile) == 2
    assert game.activate_permanent_ability(0, "Sarcatog", ability_index=1).supported
    assert _w1g6_pile(game.players[0]) == ["Sol Ring"]
    assert (tog.effective_power, tog.effective_toughness) == (3, 4)

    # Both resources gone: neither ability activates, and the Sol Ring that
    # just arrived in the graveyard is one card, not two.
    assert not game.activate_permanent_ability(0, "Sarcatog", ability_index=1).supported
    assert not game.activate_permanent_ability(0, "Sarcatog", ability_index=0).supported
    assert (tog.effective_power, tog.effective_toughness) == (3, 4)


# --- Cabal Patriarch --------------------------------------------------------
# "{2}{B}, Exile a creature card from your graveyard: Target creature gets
# -2/-2 until end of turn." The narrowed twin of the costs above.

def test_w1g6_cabal_patriarch_exiles_a_creature_card_and_no_other(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Cabal Patriarch"], lea["Grizzly Bears"]],
        theirs=[lea["Hill Giant"]], yard=[lea["Forest"], lea["Craw Wurm"]],
    )
    game.start_turn(0)
    giant = _w1g6_named(game, 1, "Hill Giant")

    # The Forest is named and is not a creature card: refused, not swapped.
    refused = game.activate_permanent_ability(
        0, "Cabal Patriarch", ability_index=1,
        target_permanent_ids=[giant.permanent_id], cost_permanent_index=0,
    )
    assert not refused.supported
    assert _w1g6_pile(game.players[0]) == ["Forest", "Craw Wurm"]

    used = game.activate_permanent_ability(
        0, "Cabal Patriarch", ability_index=1,
        target_permanent_ids=[giant.permanent_id],
    )
    assert used.supported, used.details
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert _w1g6_pile(game.players[0], "exile") == ["Craw Wurm"]
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)

    # The other ability sacrifices a creature instead, for the same effect.
    again = game.activate_permanent_ability(
        0, "Cabal Patriarch", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
        cost_permanent_ids=[_w1g6_named(game, 0, "Grizzly Bears").permanent_id],
    )
    game.check_state_based_actions()
    assert again.supported, again.details
    assert _w1g6_names(game, 0) == ["Cabal Patriarch"]
    assert _w1g6_names(game, 1) == []


# --- combat helpers ---------------------------------------------------------

def _w1g6_slot(game, seat, permanent):
    return next(
        index for index, held in enumerate(game.controlled_by(seat))
        if held is permanent
    )  # _w1g6_slot


def _w1g6_to_declare_attackers(game, seat):
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step


def _w1g6_answer(game, *, accept, pick=None):
    """Resolve the stack, answering each prompt it stops for: a "may" by
    *accept*, a graveyard pick with *pick*."""
    for _ in range(12):
        if game.stack:
            game.resolve_top_of_stack()
        if not game.pending_choices:
            if not game.stack:
                return
            continue
        choice = game.pending_choices[0]
        if choice.kind == "optional_pay":
            assert game.confirm_optional_pay(choice.player_index, accept=accept)
        elif choice.kind == "graveyard_exile_pick":
            assert game.confirm_graveyard_exile_pick(choice.player_index, [pick])
        else:
            raise AssertionError(f"unexpected prompt {choice.kind}")
    raise AssertionError("the stack did not settle")  # _w1g6_answer


# --- Rotting Giant ----------------------------------------------------------
# "Whenever this creature attacks or blocks, sacrifice it unless you exile a
# card from your graveyard." A toll whose price is an action
# (``tolls.accept_graveyard_exile_price``): offered only where it can be paid.

def _w1g6_giant_attacks(set_pool, yard):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Rotting Giant"]], theirs=[lea["Grizzly Bears"]], yard=yard,
    )
    game.interactive_seats = {0, 1}
    _w1g6_to_declare_attackers(game, 0)
    giant = _w1g6_named(game, 0, "Rotting Giant")
    assert game.declare_attackers(0, [_w1g6_slot(game, 0, giant)])[0]
    assert len(game.stack) == 1 and game.stack[0].is_ability
    return game  # _w1g6_giant_attacks


def test_w1g6_rotting_giant_stays_when_its_controller_exiles_a_card(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_giant_attacks(set_pool, [lea["Forest"], lea["Lightning Bolt"]])

    _w1g6_answer(game, accept=True, pick=1)

    assert _w1g6_names(game, 0) == ["Rotting Giant"]
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert _w1g6_pile(game.players[0], "exile") == ["Lightning Bolt"]


def test_w1g6_rotting_giant_is_sacrificed_when_the_price_is_declined(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_giant_attacks(set_pool, [lea["Forest"]])

    _w1g6_answer(game, accept=False)

    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Forest", "Rotting Giant"]
    assert not game.players[0].exile


def test_w1g6_rotting_giant_with_an_empty_graveyard_is_not_offered_the_price(
    set_pool,
):
    game = _w1g6_giant_attacks(set_pool, [])

    game.resolve_top_of_stack()

    # Nothing to exile is not a choice: no prompt, and the penalty stands.
    assert not game.pending_choices
    assert _w1g6_names(game, 0) == []
    assert _w1g6_pile(game.players[0]) == ["Rotting Giant"]


def test_w1g6_rotting_giant_owes_the_same_toll_when_it_blocks(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Rotting Giant"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Forest"]],
    )
    game.interactive_seats = {0, 1}
    _w1g6_to_declare_attackers(game, 1)
    bears = _w1g6_named(game, 1, "Grizzly Bears")
    assert game.declare_attackers(1, [_w1g6_slot(game, 1, bears)])[0]
    game.advance_combat_phase()
    giant = _w1g6_named(game, 0, "Rotting Giant")
    blocked = game.declare_blockers(
        0, {_w1g6_slot(game, 0, giant): _w1g6_slot(game, 1, bears)}
    )
    assert blocked[0], blocked

    _w1g6_answer(game, accept=True, pick=0)

    assert _w1g6_names(game, 0) == ["Rotting Giant"]
    assert not game.players[0].graveyard
    assert _w1g6_pile(game.players[0], "exile") == ["Forest"]


# --- Zombie Cannibal --------------------------------------------------------
# "Whenever this creature deals combat damage to a player, you may exile
# target card from that player's graveyard." One card out of the pile the
# damage event named, picked by the Cannibal's controller as it resolves.

def _w1g6_cannibal_connects(set_pool, their_yard, *, blocked=False):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Zombie Cannibal"]], theirs=[lea["Grizzly Bears"]],
        yard=[lea["Craw Wurm"]], their_yard=their_yard,
    )
    game.interactive_seats = {0, 1}
    _w1g6_to_declare_attackers(game, 0)
    cannibal = _w1g6_named(game, 0, "Zombie Cannibal")
    assert game.declare_attackers(0, [_w1g6_slot(game, 0, cannibal)])[0]
    game.advance_combat_phase()
    blocks = (
        {_w1g6_slot(game, 1, _w1g6_named(game, 1, "Grizzly Bears")):
         _w1g6_slot(game, 0, cannibal)}
        if blocked else {}
    )
    assert game.declare_blockers(1, blocks)[0]
    for _ in range(4):
        if game.stack or game.pending_choices or game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
    return game  # _w1g6_cannibal_connects


def test_w1g6_zombie_cannibal_exiles_a_chosen_card_from_the_damaged_players_pile(
    set_pool,
):
    lea = set_pool("LEA")
    game = _w1g6_cannibal_connects(
        set_pool, [lea["Forest"], lea["Hill Giant"], lea["Lightning Bolt"]]
    )
    assert game.players[1].life == 19

    offer = game.pending_choices[0]
    assert (offer.kind, offer.player_index) == ("optional_pay", 0)
    assert game.confirm_optional_pay(0, accept=True)
    pick = game.pending_choices[0]
    assert (pick.kind, pick.player_index, pick.data["owner_index"]) == (
        "graveyard_exile_pick", 0, 1,
    )
    assert game.confirm_graveyard_exile_pick(0, [1])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Forest", "Lightning Bolt"]
    assert _w1g6_pile(game.players[1], "exile") == ["Hill Giant"]
    # Never the Cannibal's own graveyard.
    assert _w1g6_pile(game.players[0]) == ["Craw Wurm"]


def test_w1g6_zombie_cannibal_may_decline_and_asks_nothing_of_an_empty_pile(
    set_pool,
):
    lea = set_pool("LEA")
    declined = _w1g6_cannibal_connects(set_pool, [lea["Forest"]])
    assert declined.confirm_optional_pay(0, accept=False)
    _w1g6_resolve_stack(declined)
    assert _w1g6_pile(declined.players[1]) == ["Forest"]
    assert not declined.players[1].exile

    # Their graveyard is empty and the Cannibal's own is not: there is no
    # legal card, so nothing is offered and nothing is taken from anywhere.
    empty = _w1g6_cannibal_connects(set_pool, [])
    _w1g6_resolve_stack(empty)
    assert empty.players[1].life == 19
    assert not empty.pending_choices
    assert _w1g6_pile(empty.players[0]) == ["Craw Wurm"] and not empty.players[0].exile


def test_w1g6_zombie_cannibal_blocked_deals_no_damage_to_a_player(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_cannibal_connects(set_pool, [lea["Forest"]], blocked=True)
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g6_resolve_stack(game)

    assert game.players[1].life == 20 and not game.pending_choices
    assert _w1g6_pile(game.players[1]) == ["Forest"]


# --- Crypt Creeper, Famished Ghoul ------------------------------------------
# Driven. "Sacrifice this creature: Exile target card from a graveyard."

def test_w1g6_crypt_creeper_exiles_the_card_it_was_aimed_at(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Crypt Creeper"]], yard=[lea["Forest"]],
        their_yard=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    game.start_turn(0)
    spec = game.activation_target_spec(0, 0, ability_index=0)
    # Any card in any graveyard — and not itself, which is still a permanent
    # when the target is chosen (CR 601.2c precedes CR 601.2h).
    assert [(t["seat"], t["name"]) for t in spec["valid_targets"]] == [
        (0, "Forest"), (1, "Grizzly Bears"), (1, "Lightning Bolt"),
    ]

    used = game.activate_permanent_ability(
        0, "Crypt Creeper", target_player_index=1, target_permanent_index=1
    )

    assert used.supported, used.details
    assert _w1g6_pile(game.players[1]) == ["Grizzly Bears"]
    assert _w1g6_pile(game.players[1], "exile") == ["Lightning Bolt"]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Crypt Creeper"]


def test_w1g6_crypt_creeper_is_not_sacrificed_for_nothing(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    # No card in any graveyard: no legal target, so it cannot be activated.
    game = _w1g6_game(mine=[ody["Crypt Creeper"]])
    game.start_turn(0)
    assert not game.activate_permanent_ability(0, "Crypt Creeper").supported
    assert _w1g6_names(game, 0) == ["Crypt Creeper"]

    # A slot that names no card is refused with nothing paid.
    game = _w1g6_game(mine=[ody["Crypt Creeper"]], their_yard=[lea["Grizzly Bears"]])
    game.start_turn(0)
    refused = game.activate_permanent_ability(
        0, "Crypt Creeper", target_player_index=1, target_permanent_index=4
    )
    assert not refused.supported and _w1g6_names(game, 0) == ["Crypt Creeper"]


def test_w1g6_crypt_creeper_does_nothing_once_its_target_has_left(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Crypt Creeper"]],
        their_yard=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    game.start_turn(0)
    queued = game.queue_permanent_ability(
        0, "Crypt Creeper", target_player_index=1, target_permanent_index=0
    )
    assert queued.details == "queued"
    game.players[1].graveyard.pop(0)
    _w1g6_resolve_stack(game)

    # CR 608.2b: the Bolt is not exiled in the Bears' place.
    assert _w1g6_pile(game.players[1]) == ["Lightning Bolt"]
    assert not game.players[1].exile


def test_w1g6_famished_ghoul_exiles_up_to_two_cards_from_one_graveyard(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Famished Ghoul"]], yard=[lea["Forest"]],
        their_yard=[lea["Hill Giant"], lea["Lightning Bolt"], lea["Craw Wurm"]],
    )
    game.interactive_seats = {0, 1}
    game.start_turn(0)

    queued = game.queue_permanent_ability(0, "Famished Ghoul")
    assert queued.details == "queued"
    assert _w1g6_pile(game.players[0]) == ["Forest", "Famished Ghoul"]
    game.resolve_top_of_stack()
    assert game.confirm_graveyard_pile_choice(0, 1)
    pick = game.pending_choices[0]
    assert (pick.data["owner_index"], pick.data["count"], pick.data["up_to"]) == (
        1, 2, True,
    )
    assert not game.confirm_graveyard_exile_pick(0, [0, 1, 2])   # three is too many
    assert game.confirm_graveyard_exile_pick(0, [0, 2])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Lightning Bolt"]
    assert sorted(_w1g6_pile(game.players[1], "exile")) == ["Craw Wurm", "Hill Giant"]


# --- Anarchist, Auramancer, Cartographer, Gravedigger, Scrivener ------------
# Driven. "When this creature enters, you may return target <type> card from
# your graveyard to your hand." Five types, one template.

_W1G6_RETURNERS = [
    ("Anarchist", "Fireball", "LEA"),
    ("Auramancer", "Crusade", "LEA"),
    ("Cartographer", "Forest", "LEA"),
    ("Gravedigger", "Grizzly Bears", "LEA"),
    ("Scrivener", "Lightning Bolt", "LEA"),
]


def _w1g6_returner(set_pool, name, wanted, code, *, yard=None):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    found = set_pool(code)[wanted]
    # A card of a type none of the five returns sits in slot 0.
    game = _w1g6_game(
        hand=[ody[name]], yard=[lea["Sol Ring"], found, found] if yard is None else yard,
        their_yard=[found],
    )
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    return game, found  # _w1g6_returner


@_w1g6_pytest.mark.parametrize("name, wanted, code", _W1G6_RETURNERS)
def test_w1g6_an_entering_returner_takes_back_the_card_it_named(
    set_pool, name, wanted, code
):
    game, _found = _w1g6_returner(set_pool, name, wanted, code)
    spec = game.cast_target_spec(0, set_pool("ODY")[name])
    # Only its own type, and only your own graveyard.
    assert [(t["seat"], t["index"]) for t in spec["valid_targets"]] == [(0, 1), (0, 2)]

    cast = game.queue_from_hand(
        0, name, target_player_index=0, target_permanent_index=2
    )
    assert cast.supported, cast.details
    game.resolve_top_of_stack()
    # The entry trigger is its own stack object (CR 603.3).
    assert _w1g6_names(game, 0) == [name] and len(game.stack) == 1
    _w1g6_answer(game, accept=True)

    # Exactly one of the two copies came back.
    assert _w1g6_pile(game.players[0], "hand") == [wanted]
    assert _w1g6_pile(game.players[0]) == ["Sol Ring", wanted]
    assert _w1g6_pile(game.players[1]) == [wanted]


@_w1g6_pytest.mark.parametrize("name, wanted, code", _W1G6_RETURNERS)
def test_w1g6_an_entering_returner_may_decline_and_cannot_reach_other_piles(
    set_pool, name, wanted, code
):
    game, _found = _w1g6_returner(set_pool, name, wanted, code)
    assert game.queue_from_hand(
        0, name, target_player_index=0, target_permanent_index=1
    ).supported
    game.resolve_top_of_stack()
    _w1g6_answer(game, accept=False)
    assert not game.players[0].hand and len(game.players[0].graveyard) == 3

    # With no card of its type in your own graveyard there is no target: the
    # trigger leaves the stack and the opponent's copy stays where it is.
    lea = set_pool("LEA")
    game, found = _w1g6_returner(set_pool, name, wanted, code, yard=[lea["Sol Ring"]])
    assert game.queue_from_hand(0, name).supported
    _w1g6_answer(game, accept=True)
    assert _w1g6_names(game, 0) == [name]
    assert not game.players[0].hand
    assert _w1g6_pile(game.players[1]) == [wanted]


# --- Zoologist --------------------------------------------------------------
# Driven. "{3}{G}, {T}: Reveal the top card of your library. If it's a
# creature card, put it onto the battlefield. Otherwise, put it into your
# graveyard."

@_w1g6_pytest.mark.parametrize(
    "top, onto_battlefield",
    [("Craw Wurm", True), ("Forest", False), ("Lightning Bolt", False)],
)
def test_w1g6_zoologist_puts_a_creature_into_play_and_bins_anything_else(
    set_pool, top, onto_battlefield
):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(mine=[ody["Zoologist"]], library=[lea[top], lea["Island"]])
    game.start_turn(0)

    used = game.activate_permanent_ability(0, "Zoologist")

    assert used.supported, used.details
    assert len(game.players[0].library) == 1
    assert (top in _w1g6_names(game, 0)) is onto_battlefield
    assert _w1g6_pile(game.players[0]) == ([] if onto_battlefield else [top])


def test_w1g6_zoologist_with_an_empty_library_reveals_nothing(set_pool):
    game = _w1g6_game(mine=[set_pool("ODY")["Zoologist"]], library=[])
    game.start_turn(0)

    used = game.activate_permanent_ability(0, "Zoologist")

    assert used.supported, used.details
    assert _w1g6_names(game, 0) == ["Zoologist"] and not game.players[0].graveyard

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# The five creatures the group implemented. The twenty-odd it only *drove*
# (they compiled on the day of the ingest) are in
# `test_ody_creatures_driven_w1g8.py`, a file of the group's own, so this one
# keeps its room for the groups still to land.
import pytest as _w1g8_pytest

from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.sets import ody_w1g8_helpers as _w1g8


# --- Junk Golem -------------------------------------------------------------
# "At the beginning of your upkeep, sacrifice this creature unless you remove a
# +1/+1 counter from it." The toll's seventh currency: the removal is the
# offer's action, so the `may` every "unless" already is asks for it and the
# takeability gate decides whether there is anything to ask about.

def test_w1g8_junk_golem_pays_a_counter_each_upkeep_until_it_has_none(set_pool):
    game = _w1g8.table(set_pool)
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    assert _w1g8.pt(golem) == (3, 3), "enters with three +1/+1 counters"

    sizes = []
    for _ in range(3):
        _w1g8.upkeep(game)
        sizes.append(_w1g8.pt(golem) if game.is_on_battlefield(golem) else None)

    # The third counter leaves a 0/0, which state-based actions take.
    assert sizes == [(2, 2), (1, 1), None]
    assert _w1g8.pile(game, 0) == ["Junk Golem"]


@_w1g8_pytest.mark.parametrize("accept, left", [(True, (2, 2)), (False, None)])
def test_w1g8_junk_golem_asks_its_controller_and_obeys_the_answer(
    set_pool, accept, left
):
    game = _w1g8.table(set_pool, interactive=(0,))
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    game.active_player_index = 0
    game.resolve_upkeep(0)

    assert _w1g8.owed(game) == [("optional_pay", 0)]
    assert game.stack, "the ability waits on the stack for its answer (CR 608.2)"
    assert game.confirm_optional_pay(0, accept=accept)
    _w1g8.settle(game)

    if left is None:
        assert _w1g8.pile(game, 0) == ["Junk Golem"]
        assert "Junk Golem was sacrificed" in game.log
    else:
        assert _w1g8.pt(golem) == left


def test_w1g8_junk_golem_with_no_counter_is_not_offered_the_price(set_pool):
    """Kept alive at no counters by an anthem, the Golem has nothing to pay
    with: no prompt, and the sacrifice stands (CR 118.12a — the "unless" is an
    offer, and an action nobody can take is not offered)."""
    game = _w1g8.table(set_pool, interactive=(0,))
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    _w1g8.put(game, set_pool, 0, "Glorious Anthem")
    for _ in range(3):
        game.active_player_index = 0
        game.resolve_upkeep(0)
        assert game.confirm_optional_pay(0, accept=True)
        _w1g8.settle(game)
    assert _w1g8.pt(golem) == (1, 1), "the anthem alone"

    game.resolve_upkeep(0)
    assert _w1g8.owed(game) == []
    _w1g8.settle(game)

    assert _w1g8.names(game, 0) == ["Glorious Anthem"]
    assert _w1g8.pile(game, 0) == ["Junk Golem"]


def test_w1g8_junk_golem_gone_in_response_is_asked_nothing(set_pool):
    """Counters are not retained across a zone change (CR 122.2), so a Golem
    destroyed with its trigger on the stack has none to remove: nobody is
    asked, and there is nothing left to sacrifice."""
    game = _w1g8.table(set_pool, interactive=(0,))
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)
    assert [item.card.name for item in game.stack] == ["Junk Golem"]

    _w1g8.leave(game, golem)
    _w1g8.settle(game)

    assert _w1g8.owed(game) == []
    assert not any("Removed a +1/+1 counter" in line for line in game.log)


def test_w1g8_junk_golem_grows_for_one_mana_and_a_card_and_is_refused_without(
    set_pool,
):
    game = _w1g8.table(set_pool, hand=["Forest"], enforce=True)
    golem = _w1g8.put(game, set_pool, 0, "Junk Golem")
    game.players[0].mana_pool["C"] = 2

    used = game.activate_permanent_ability(0, "Junk Golem")
    _w1g8.settle(game)
    assert used.supported, used.details
    assert _w1g8.pt(golem) == (4, 4)
    assert _w1g8.pile(game, 0) == ["Forest"] and not game.players[0].hand

    refused = game.activate_permanent_ability(0, "Junk Golem")
    assert not refused.supported and "discard" in refused.details
    assert game.players[0].mana_pool["C"] == 1, "a refused activation spends nothing"
    assert _w1g8.pt(golem) == (4, 4)


@_w1g8_pytest.mark.parametrize(
    "price",
    [
        "remove all +1/+1 counters from it",        # a quantity nobody asks "can you?" of
        "remove a +1/+1 counter from target creature",  # a target is not a price
        "remove two +1/+1 counters from it",        # one handler, one counter
    ],
)
def test_w1g8_a_counter_removal_price_is_one_counter_off_the_source(price):
    """The refusing gate's refusal test: a price the offer cannot ask about is
    refused whole, never read as "remove one from this"."""
    from tests.helpers import _mk_card

    probe = _mk_card(
        "Probe Golem", "Artifact Creature — Golem",
        f"At the beginning of your upkeep, sacrifice this creature unless you {price}.",
    )
    assert not _w1g8_compile(probe).supported


# --- Mad Dog ----------------------------------------------------------------
# "At the beginning of your end step, if this creature didn't attack or come
# under your control this turn, sacrifice it." One negation over two records
# of the turn: an intervening-if (CR 603.4), so on a turn it attacked or
# arrived the ability does not trigger at all.

def _w1g8_end_step(game, seat):
    """*seat*'s end step, settled; returns the lines it logged."""
    before = len(game.log)
    game.resolve_end_step(seat)
    _w1g8.settle(game)
    return game.log[before:]


def _w1g8_next_turn(game, seat):
    game.turn += 1
    game.start_turn(seat)


def test_w1g8_mad_dog_stays_the_turn_it_arrives_and_dies_the_turn_it_idles(set_pool):
    game = _w1g8.table(set_pool, hand=["Mad Dog"])
    _w1g8_next_turn(game, 0)
    assert game.cast_from_hand(0, "Mad Dog").supported

    assert not any("Mad Dog" in line for line in _w1g8_end_step(game, 0)), (
        "it came under your control this turn, so nothing triggered"
    )
    _w1g8_next_turn(game, 1)
    _w1g8_end_step(game, 1)
    assert _w1g8.names(game, 0) == ["Mad Dog"], "an opponent's end step is not yours"

    _w1g8_next_turn(game, 0)
    assert "Mad Dog was sacrificed" in _w1g8_end_step(game, 0)
    assert _w1g8.pile(game, 0) == ["Mad Dog"]


def test_w1g8_mad_dog_that_attacked_is_kept(set_pool):
    game = _w1g8.table(set_pool)
    dog = _w1g8.put(game, set_pool, 0, "Mad Dog")
    _w1g8_next_turn(game, 0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared, why = game.declare_attackers(0, [0])
    assert declared, why

    assert not any("Mad Dog" in line for line in _w1g8_end_step(game, 0))
    assert game.is_on_battlefield(dog)


def test_w1g8_mad_dog_changing_hands_is_coming_under_control(set_pool):
    """Erg Raiders' 2018-03-16 ruling: a creature "comes under your control"
    if it enters under your control *or* you gain control of it while it is
    already on the battlefield. The thief keeps the Dog that turn and loses it
    the next one it sits out."""
    from engine.control import change_control

    game = _w1g8.table(set_pool)
    dog = _w1g8.put(game, set_pool, 0, "Mad Dog")
    _w1g8_next_turn(game, 0)
    _w1g8_next_turn(game, 1)
    change_control(dog, 1, source="a test's theft")
    game._sync_control()

    assert not any("Mad Dog" in line for line in _w1g8_end_step(game, 1))
    _w1g8_next_turn(game, 0)
    _w1g8_end_step(game, 0)
    assert _w1g8.names(game, 1) == ["Mad Dog"], "its old controller's end step is not 'yours'"

    _w1g8_next_turn(game, 1)
    assert "Mad Dog was sacrificed" in _w1g8_end_step(game, 1)
    assert _w1g8.pile(game, 0) == ["Mad Dog"], "to its owner's graveyard"


def test_w1g8_came_under_control_this_turn_is_only_read_on_your_own_turn():
    """The refusing gate's refusal test. The record is CR 302.6's, carried
    across other players' turns, so under "each end step" it could not tell
    this turn from the last one — the clause refuses there instead."""
    from tests.helpers import _mk_card

    def dog(step):
        return _mk_card(
            "Probe Dog", "Creature — Dog",
            f"At the beginning of {step}, if this creature didn't attack or "
            "come under your control this turn, sacrifice it.",
        )

    assert _w1g8_compile(dog("your end step")).supported
    assert not _w1g8_compile(dog("each end step")).supported


# --- Savage Firecat ---------------------------------------------------------
# "Whenever you tap a land for mana, remove a +1/+1 counter from this
# creature." The third seat the tap-for-mana event prints ("a player", "an
# opponent", "you"), narrowed at the tap seam against the Firecat's controller.
#
# Like every non-mana trigger under this event the removal is resolved at the
# tap seam rather than put on the stack (Manabarbs' convention; CR 603.3 and
# Manabarbs' own 2009-10-01 ruling say stack — measured and reported, not
# changed here: it is seven shipped cards' behaviour, not this one's).

def _w1g8_tap(game, seat, land):
    return game.tap_land_for_mana(seat, land.card.name, permanent_id=land.permanent_id)


def test_w1g8_savage_firecat_loses_a_counter_for_each_land_its_controller_taps(set_pool):
    game = _w1g8.table(set_pool)
    cat = _w1g8.put(game, set_pool, 0, "Savage Firecat")
    mine = [_w1g8.put(game, set_pool, 0, "Mountain") for _ in range(3)]
    theirs = _w1g8.put(game, set_pool, 1, "Forest")
    game.start_turn(0)
    assert _w1g8.pt(cat) == (7, 7), "a 0/0 with seven +1/+1 counters"

    assert _w1g8_tap(game, 0, mine[0]) and _w1g8_tap(game, 0, mine[1])
    assert _w1g8.pt(cat) == (5, 5)
    assert game.players[0].mana_pool["R"] == 2, "the mana is still made"

    assert _w1g8_tap(game, 1, theirs)
    assert _w1g8.pt(cat) == (5, 5), "\"you\" is the Firecat's controller, not any player"

    game.become_tapped(mine[2])
    assert _w1g8.pt(cat) == (5, 5), "tapped, but not for mana"


def test_w1g8_savage_firecat_follows_its_controller(set_pool):
    """CR 109.5: "you" is whoever controls the Firecat now. Stolen, it counts
    the thief's taps and stops counting its owner's."""
    from engine.control import change_control

    game = _w1g8.table(set_pool)
    cat = _w1g8.put(game, set_pool, 0, "Savage Firecat")
    mine = _w1g8.put(game, set_pool, 0, "Mountain")
    theirs = _w1g8.put(game, set_pool, 1, "Forest")
    game.start_turn(0)
    change_control(cat, 1, source="a test's theft")
    game._sync_control()

    assert _w1g8_tap(game, 0, mine)
    assert _w1g8.pt(cat) == (7, 7)
    assert _w1g8_tap(game, 1, theirs)
    assert _w1g8.pt(cat) == (6, 6)


def test_w1g8_savage_firecat_tapped_down_to_nothing_dies(set_pool):
    game = _w1g8.table(set_pool)
    cat = _w1g8.put(game, set_pool, 0, "Savage Firecat")
    lands = [_w1g8.put(game, set_pool, 0, "Mountain") for _ in range(8)]
    game.start_turn(0)

    for land in lands[:7]:
        assert _w1g8_tap(game, 0, land)
    game.check_state_based_actions()
    assert _w1g8.pile(game, 0) == ["Savage Firecat"]
    assert _w1g8_tap(game, 0, lands[7]), "with the Firecat gone a land is just a land"

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================

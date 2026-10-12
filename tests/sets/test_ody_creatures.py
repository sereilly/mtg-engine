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

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================

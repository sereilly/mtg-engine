"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.card_loader import manifest_set_path as _w1g1_manifest_set_path
from engine.cast_costs import KICKED as _W1G1_KICKED
from engine.cast_costs import KICKED_WITH as _W1G1_KICKED_WITH
from engine.cast_costs import kicker_costs as _w1g1_kicker_costs
from engine.mana_payment import mana_cost_from_symbols as _w1g1_symbols
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}

#: The two quoted abilities a kicked Volver may enter with, as printed.
_W1G1_REGENERATE = "Pay 3 life: Regenerate this creature."
_W1G1_DRAIN = "Whenever this creature deals damage, you gain that much life."

#: The five Volvers: name, printed body, then for each kicker in printed order
#: its key, the +1/+1 counters it buys and what the creature enters with.
_W1G1_VOLVERS = [
    ("Anavolver", (3, 3), ("{1}{U}", 2, "flying"), ("{B}", 1, _W1G1_REGENERATE)),
    ("Cetavolver", (1, 1), ("{1}{R}", 2, "first strike"), ("{G}", 1, "trample")),
    ("Degavolver", (1, 1), ("{1}{B}", 2, _W1G1_REGENERATE), ("{R}", 1, "first strike")),
    ("Necravolver", (2, 2), ("{1}{G}", 2, "trample"), ("{W}", 1, _W1G1_DRAIN)),
    ("Rakavolver", (2, 2), ("{1}{W}", 2, _W1G1_DRAIN), ("{U}", 1, "flying")),
]

#: Each Volver cast each of the four ways CR 702.33b allows: neither kicker,
#: either alone, both.
_W1G1_VOLVER_CASTS = [
    (name, body, first, second, taken)
    for name, body, first, second in _W1G1_VOLVERS
    for taken in ((), (0,), (1,), (0, 1))
]


def _w1g1_duel(set_pool, hand, pool=None):
    """A two-seat game that **charges mana**, seat 0 holding *hand* (cards)
    with *pool* floating. Costs are enforced because a kicker is a price: a rig
    that waives mana cannot tell a kicked cast from a free one."""
    forest = set_pool("LEA")["Forest"]
    game = _W1G1Game(players=[
        _W1G1PlayerState("Caster", library=[forest] * 10, hand=list(hand)),
        _W1G1PlayerState("Bystander", library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH if pool is None else pool)
    return game  # _w1g1_duel


def _w1g1_put(game, seat, card):
    """*card* onto *seat*'s battlefield without being cast, ready to act."""
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put


def _w1g1_floating(game, seat=0) -> int:
    return sum(game.players[seat].mana_pool.values())  # _w1g1_floating


def _w1g1_price(printed: str) -> int:
    return sum((_w1g1_symbols(printed) or {}).values())  # _w1g1_price


def _w1g1_cast(game, name, *, kick=(), **announced):
    """Cast *name* from seat 0 paying the kicker costs in *kick*, resolve it,
    and return the permanent it became (None for a spell)."""
    result = game.cast_from_hand(
        0, name, optional_cost_payments={key: 1 for key in kick} or None,
        **announced,
    )
    assert result.supported, result
    _w1g1_resolve_stack(game)
    return next(
        (p for p in game.controlled_by(0) if p.card.name == name), None
    )  # _w1g1_cast


def _w1g1_ability_lines(permanent) -> set:
    """Every activated and triggered ability *permanent* currently has, by its
    printed line — read off ``effective_card``, which is what the activation
    gate and the trigger scan read."""
    program = _w1g1_compile(permanent.effective_card)
    return {
        ability.source_line
        for ability in (*program.activated_abilities, *program.triggered_abilities)
    }  # _w1g1_ability_lines


def _w1g1_has(game, permanent, grant) -> bool:
    """Whether *permanent* has *grant*: a keyword, or a quoted ability line."""
    if grant in (_W1G1_REGENERATE, _W1G1_DRAIN):
        return grant in _w1g1_ability_lines(permanent)
    return bool(game._has_keyword(permanent, grant))  # _w1g1_has


def _w1g1_slot(game, seat, permanent) -> int:
    return next(
        index for index, perm in enumerate(game.controlled_by(seat))
        if perm is permanent
    )  # _w1g1_slot


def _w1g1_to_declare_attackers(game):
    """Seat 0's turn, at the declare-attackers step, nobody summoning sick."""
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
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


def _w1g1_fight(game, attacker, blocker=None):
    """Seat 0 attacks seat 1 with *attacker*, blocked by *blocker* or not at
    all, and combat runs to the second main phase."""
    _w1g1_to_declare_attackers(game)
    slot = _w1g1_slot(game, 0, attacker)
    declared = game.declare_attackers(0, [slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocks = {} if blocker is None else {_w1g1_slot(game, 1, blocker): slot}
    blocked = game.declare_blockers(1, blocks)
    assert blocked[0], blocked
    _w1g1_finish_combat(game)  # _w1g1_fight


# --- The Volvers ------------------------------------------------------------
# "Kicker {1}{U} and/or {B}. If this creature was kicked with its {1}{U}
# kicker, it enters with two +1/+1 counters on it and with flying. If this
# creature was kicked with its {B} kicker, it enters with a +1/+1 counter on it
# and with "Pay 3 life: Regenerate this creature.""


@_w1g1_pytest.mark.parametrize("name", [row[0] for row in _W1G1_VOLVERS])
def test_w1g1_a_volver_compiles_with_two_kickers_and_two_entry_lines(set_pool, name):
    """Supported, the kicker line read as two offers (CR 702.33b), and each
    "kicked with its [A] kicker" line read as an entry replacement keyed to
    that one cost (CR 702.33f)."""
    from engine.enter_effects import kicked_entry

    card = set_pool("APC")[name]
    assert _w1g1_compile(card).supported
    keys = _w1g1_kicker_costs(card.oracle_text)
    entries = [
        entry for line in card.oracle_text.split("\n")
        if (entry := kicked_entry(line, card.name)) is not None
    ]
    assert len(keys) == 2
    assert [entry["kicker"] for entry in entries] == list(keys)
    assert [entry["counters"] for entry in entries] == [(2, "+1/+1"), (1, "+1/+1")]


@_w1g1_pytest.mark.parametrize("name,body,first,second,taken", _W1G1_VOLVER_CASTS)
def test_w1g1_a_volver_enters_with_what_each_paid_kicker_buys(
    set_pool, name, body, first, second, taken
):
    """CR 702.33d/f through the real cast: each kicker is an offer of its own,
    the creature enters with the counters and the ability of exactly the ones
    paid — both of them when both were (three counters, two abilities) — and
    the mana spent is the mana cost plus those kickers and nothing else."""
    card = set_pool("APC")[name]
    kickers = (first, second)
    paid = tuple(kickers[index][0] for index in taken)
    game = _w1g1_duel(set_pool, [card])
    before = _w1g1_floating(game)

    volver = _w1g1_cast(game, name, kick=paid)

    counters = sum(kickers[index][1] for index in taken)
    assert (volver.effective_power, volver.effective_toughness) == (
        body[0] + counters, body[1] + counters,
    )
    assert int(volver.metadata.get("plus_counters", 0) or 0) == counters
    assert before - _w1g1_floating(game) == _w1g1_price(card.mana_cost) + sum(
        _w1g1_price(key) for key in paid
    )
    for index, (_key, _count, grant) in enumerate(kickers):
        assert _w1g1_has(game, volver, grant) is (index in taken), (grant, taken)
    assert bool(volver.metadata.get(_W1G1_KICKED)) is bool(taken)
    assert tuple(volver.metadata.get(_W1G1_KICKED_WITH) or ()) == paid
    assert (f"Caster kicked {name}" in game.log) is bool(taken)


@_w1g1_pytest.mark.parametrize("name,body,first,second", _W1G1_VOLVERS)
def test_w1g1_a_volver_nothing_cast_was_not_kicked(set_pool, name, body, first, second):
    """Put onto the battlefield without being cast (a reanimation): no cast, so
    no CR 601.2b, so neither kicker — the printed body and neither ability."""
    game = _w1g1_duel(set_pool, [])
    volver = _w1g1_put(game, 0, set_pool("APC")[name])
    assert (volver.effective_power, volver.effective_toughness) == body
    assert not _w1g1_has(game, volver, first[2])
    assert not _w1g1_has(game, volver, second[2])
    assert not volver.metadata.get(_W1G1_KICKED)


def test_w1g1_a_volver_kicker_the_pool_cannot_pay_is_refused_with_nothing_spent(set_pool):
    """CR 601.2h: Cetavolver is {1}{U} with kickers {1}{R} and {G}. Blue mana
    pays the creature and neither kicker, and a refused cast spends none."""
    card = set_pool("APC")["Cetavolver"]
    for kick in (("{G}",), ("{1}{R}",), ("{1}{R}", "{G}")):
        game = _w1g1_duel(set_pool, [card], pool={"U": 6})
        refused = game.cast_from_hand(
            0, "Cetavolver", optional_cost_payments={key: 1 for key in kick}
        )
        assert not refused.supported, kick
        assert _w1g1_floating(game) == 6
        assert [held.name for held in game.players[0].hand] == ["Cetavolver"]


def test_w1g1_both_volver_kickers_are_offered_by_name_and_priced_apart(set_pool):
    """The browser's cast-offer prompt is `cast_cost_offers`: two offers, each
    labelled "kicker", and each payable or not on its own — a pool with a
    black mana and no blue can take Anavolver's {B} and not its {1}{U}."""
    card = set_pool("APC")["Anavolver"]
    game = _w1g1_duel(set_pool, [card], pool={"G": 4, "B": 1})
    offers = {offer["symbols"]: offer for offer in game.cast_cost_offers(0, card)}
    assert sorted(offers) == ["{1}{U}", "{B}"]
    assert {offer["label"] for offer in offers.values()} == {"kicker"}
    assert (offers["{1}{U}"]["max_times"], offers["{B}"]["max_times"]) == (0, 1)


def test_w1g1_the_granted_regeneration_is_paid_in_life_and_saves_the_creature(set_pool):
    """Anavolver kicked with {B} has "Pay 3 life: Regenerate this creature.":
    activating costs exactly 3 life and no mana, and the shield replaces the
    next destruction — the creature is still there, tapped, after 7 damage."""
    game = _w1g1_duel(
        set_pool, [set_pool("APC")["Anavolver"], set_pool("LEA")["Fireball"]]
    )
    volver = _w1g1_cast(game, "Anavolver", kick=("{B}",))
    floating = _w1g1_floating(game)

    used = game.activate_permanent_ability(0, "Anavolver", ability_index=0)
    assert used.supported, used.details
    assert game.players[0].life == 17
    assert _w1g1_floating(game) == floating

    burned = game.cast_from_hand(
        0, "Fireball", target_player_index=0,
        target_permanent_ids=[volver.permanent_id], x_value=7,
    )
    assert burned.supported, burned.details
    _w1g1_resolve_stack(game)
    assert any(perm is volver for perm in game.controlled_by(0))
    assert volver.tapped
    assert "Anavolver regenerated" in game.log


def test_w1g1_the_granted_regeneration_needs_three_life_and_the_kicker(set_pool):
    """CR 119.4: a player may pay 3 life only with 3 or more. And the ability
    is the {B} kicker's — an Anavolver kicked only with {1}{U}, or not at all,
    has nothing to activate."""
    game = _w1g1_duel(set_pool, [set_pool("APC")["Anavolver"]])
    _w1g1_cast(game, "Anavolver", kick=("{B}",))
    game.players[0].life = 2
    refused = game.activate_permanent_ability(0, "Anavolver", ability_index=0)
    assert not refused.supported
    assert game.players[0].life == 2

    for kick in ((), ("{1}{U}",)):
        game = _w1g1_duel(set_pool, [set_pool("APC")["Anavolver"]])
        _w1g1_cast(game, "Anavolver", kick=kick)
        nothing = game.activate_permanent_ability(0, "Anavolver", ability_index=0)
        assert not nothing.supported, kick
        assert game.players[0].life == 20


@_w1g1_pytest.mark.parametrize("kick,gained", [((), 0), (("{1}{G}",), 0), (("{W}",), 3)])
def test_w1g1_the_granted_damage_trigger_gains_that_much_life(set_pool, kick, gained):
    """Necravolver kicked with {W} has "Whenever this creature deals damage,
    you gain that much life.": unblocked it deals its power to the player and
    its controller gains exactly that. Unkicked, or kicked only with {1}{G},
    it gains nothing."""
    game = _w1g1_duel(set_pool, [set_pool("APC")["Necravolver"]])
    volver = _w1g1_cast(game, "Necravolver", kick=kick)
    power = volver.effective_power

    _w1g1_fight(game, volver)

    assert game.players[1].life == 20 - power
    assert game.players[0].life == 20 + gained


def test_w1g1_the_granted_damage_trigger_counts_damage_dealt_to_a_creature(set_pool):
    """"Deals damage", not "deals combat damage to a player": blocked by a 2/2,
    a 3/3 Necravolver deals 3 to it and its controller gains 3."""
    game = _w1g1_duel(set_pool, [set_pool("APC")["Necravolver"]])
    volver = _w1g1_cast(game, "Necravolver", kick=("{W}",))
    bears = _w1g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])

    _w1g1_fight(game, volver, bears)

    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert (game.players[0].life, game.players[1].life) == (23, 20)


def test_w1g1_a_clone_of_a_kicked_volver_is_the_printed_volver(set_pool):
    """CR 707.2: a copy acquires the values "derived from the text printed on
    the object" — counters and other effects "are not copied", and whether a
    spell was kicked is copied only for an object on the stack. So a Clone of
    an Anavolver kicked both ways is a 3/3 Anavolver with no counters, no
    flying and no regeneration: it reads the kicker lines and was not kicked."""
    game = _w1g1_duel(
        set_pool, [set_pool("APC")["Anavolver"], set_pool("LEA")["Clone"]]
    )
    original = _w1g1_cast(game, "Anavolver", kick=("{1}{U}", "{B}"))
    assert (original.effective_power, original.effective_toughness) == (6, 6)

    cloned = game.cast_from_hand(
        0, "Clone", target_player_index=0,
        target_permanent_ids=[original.permanent_id],
    )
    assert cloned.supported, cloned.details
    _w1g1_resolve_stack(game)
    clone = next(p for p in game.controlled_by(0) if p.card.name == "Clone")

    assert clone.effective_card.name == "Anavolver"
    assert (clone.effective_power, clone.effective_toughness) == (3, 3)
    assert int(clone.metadata.get("plus_counters", 0) or 0) == 0
    assert not game._has_keyword(clone, "flying")
    assert _W1G1_REGENERATE not in _w1g1_ability_lines(clone)
    assert not clone.metadata.get(_W1G1_KICKED)


def test_w1g1_a_kicked_volver_under_humility_keeps_its_counters_and_cannot_regenerate(set_pool):
    """Counters are not abilities: under Humility a doubly kicked Anavolver is
    a 1/1 with three +1/+1 counters, and its granted regeneration cannot be
    activated."""
    game = _w1g1_duel(
        set_pool, [set_pool("APC")["Anavolver"], set_pool("TMP")["Humility"]]
    )
    volver = _w1g1_cast(game, "Anavolver", kick=("{1}{U}", "{B}"))
    _w1g1_cast(game, "Humility")

    assert (volver.effective_power, volver.effective_toughness) == (4, 4)
    refused = game.activate_permanent_ability(0, "Anavolver", ability_index=0)
    assert not refused.supported
    assert game.players[0].life == 20


def test_w1g1_the_ai_casts_and_kicks_volvers_without_a_refusal():
    """All five pinned into both decks of six simulated games: they are cast,
    some kicked, never refused and never left owing a prompt. (Apocalypse is a
    measured set, so other cards' lines are in the report; only the Volvers'
    are read, and the floors sit well under what the seed gives today.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [row[0] for row in _W1G1_VOLVERS]
    report = run_ai_simulation(
        [_w1g1_manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=18, required_cards=names,
    )
    assert report.games_completed == 6
    cast = {
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 3, sorted(cast)
    kicked = [
        line for line in report.log_lines if " kicked " in line and "volver" in line
    ]
    assert len(kicked) >= 2, kicked
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [i.message for i in report.issues if "volver" in i.message] == []
    w1g1_volvers_left_nothing_owing = not report.steps_left_owing
    assert w1g1_volvers_left_nothing_owing, report.steps_left_owing


# --- Desolation Angel / Desolation Giant -------------------------------------
# "When this creature enters, destroy all lands you control. If it was kicked,
# destroy all lands instead." One sentence printed twice, of which one runs.


def _w1g1_desolation_board(set_pool, name):
    """Both seats hold a Forest, a Mountain, a Grizzly Bears and a Sol Ring;
    seat 0 holds *name*."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, [set_pool("APC")[name]])
    for seat in (0, 1):
        for bystander in ("Forest", "Mountain", "Grizzly Bears", "Sol Ring"):
            _w1g1_put(game, seat, lea[bystander])
    return game  # _w1g1_desolation_board


def _w1g1_names(game, seat) -> list:
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g1_names


@_w1g1_pytest.mark.parametrize("kicked", [False, True])
def test_w1g1_desolation_angel_destroys_its_controllers_lands_or_everyones(set_pool, kicked):
    """Unkicked: only its controller's lands. Kicked ({W}{W}): every land —
    and in neither case both, and never a creature or an artifact."""
    game = _w1g1_desolation_board(set_pool, "Desolation Angel")
    before = _w1g1_floating(game)

    angel = _w1g1_cast(game, "Desolation Angel", kick=("{W}{W}",) if kicked else ())

    assert before - _w1g1_floating(game) == 5 + (2 if kicked else 0)
    assert _w1g1_names(game, 0) == ["Desolation Angel", "Grizzly Bears", "Sol Ring"]
    assert _w1g1_names(game, 1) == (
        ["Grizzly Bears", "Sol Ring"] if kicked
        else ["Forest", "Grizzly Bears", "Mountain", "Sol Ring"]
    )
    assert sorted(c.name for c in game.players[0].graveyard) == ["Forest", "Mountain"]
    assert sorted(c.name for c in game.players[1].graveyard) == (
        ["Forest", "Mountain"] if kicked else []
    )
    assert game._has_keyword(angel, "flying")
    assert (angel.effective_power, angel.effective_toughness) == (5, 4)


@_w1g1_pytest.mark.parametrize("kicked", [False, True])
def test_w1g1_desolation_giant_destroys_other_creatures_and_never_itself(set_pool, kicked):
    """Unkicked: its controller's *other* creatures. Kicked: everyone's other
    creatures. The Giant survives both, and no land or artifact is touched."""
    game = _w1g1_desolation_board(set_pool, "Desolation Giant")

    _w1g1_cast(game, "Desolation Giant", kick=("{W}{W}",) if kicked else ())

    assert _w1g1_names(game, 0) == ["Desolation Giant", "Forest", "Mountain", "Sol Ring"]
    assert _w1g1_names(game, 1) == (
        ["Forest", "Mountain", "Sol Ring"] if kicked
        else ["Forest", "Grizzly Bears", "Mountain", "Sol Ring"]
    )


@_w1g1_pytest.mark.parametrize("kicked", [False, True])
def test_w1g1_both_arms_of_desolation_angel_honour_a_regeneration_shield(set_pool, kicked):
    """The card says nothing about regeneration, so neither arm may skip it
    (CR 701.19a). A Mishra's Factory animated and given a shield is a land with
    one: it survives the unkicked Angel and the kicked Angel alike, tapped,
    while the Forest beside it is destroyed either way.

    The arms used to disagree — the kicked one lowered to the by-type land
    sweep, which skipped shields, and the unkicked one to the filtered sweep,
    which honoured them. They are one kind now, so they cannot."""
    lea = set_pool("LEA")
    game = _w1g1_duel(
        set_pool, [set_pool("APC")["Desolation Angel"], lea["Regeneration"]]
    )
    factory = _w1g1_put(game, 0, set_pool("ATQ")["Mishra's Factory"])
    _w1g1_put(game, 0, lea["Forest"])
    animated = game.activate_permanent_ability(0, "Mishra's Factory", ability_index=1)
    assert animated.supported and factory.is_creature, animated.details
    _w1g1_cast(
        game, "Regeneration", target_player_index=0,
        target_permanent_ids=[factory.permanent_id],
    )
    shielded = game.activate_permanent_ability(0, "Regeneration", ability_index=0)
    assert shielded.supported, shielded.details

    _w1g1_cast(game, "Desolation Angel", kick=("{W}{W}",) if kicked else ())

    assert any(perm is factory for perm in game.controlled_by(0))
    assert factory.tapped
    assert "Forest" not in _w1g1_names(game, 0)
    assert "Mishra's Factory regenerated" in game.log


def test_w1g1_desolation_angels_two_arms_are_one_instruction_kind(set_pool):
    """What `test_every_printed_instead_pair_acts_on_one_object` holds for the
    whole pool, said of this card: the kicked arm is the same sweep as the
    unkicked one with the seat narrowing taken off, not a second handler."""
    program = _w1g1_compile(set_pool("APC")["Desolation Angel"])
    (trigger,) = program.triggered_abilities
    then, otherwise = (
        trigger.instruction.payload["then"], trigger.instruction.payload["else"],
    )
    assert [(step.kind, step.payload) for step in then] == [
        ("destroy_all_matching", {"type_filter": "land"}),
    ]
    assert [(step.kind, step.payload) for step in otherwise] == [
        ("destroy_all_matching", {"type_filter": "land", "controller": "you"}),
    ]


# --- The Penumbra creatures --------------------------------------------------
# "When this creature dies, create a 2/1 black Cat creature token."

_W1G1_PENUMBRAS = [
    ("Penumbra Bobcat", "Cat", (2, 1), False),
    ("Penumbra Kavu", "Kavu", (3, 3), False),
    ("Penumbra Wurm", "Wurm", (6, 6), True),
]


@_w1g1_pytest.mark.parametrize("name,creature_type,body,tramples", _W1G1_PENUMBRAS)
def test_w1g1_a_penumbra_creature_leaves_a_black_token_when_it_dies(
    set_pool, name, creature_type, body, tramples
):
    """Destroyed, it goes to its owner's graveyard and its controller gets one
    token of the printed type and size — black, where the creature was green,
    and with trample only for the Wurm."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, [set_pool("APC")[name], lea["Terror"]])
    penumbra = _w1g1_cast(game, name)
    assert penumbra.effective_colors == {"G"}

    _w1g1_cast(
        game, "Terror", target_player_index=0,
        target_permanent_ids=[penumbra.permanent_id],
    )

    assert sorted(c.name for c in game.players[0].graveyard) == sorted([name, "Terror"])
    (token,) = list(game.controlled_by(0))
    assert token.is_creature and token.has_type(creature_type.lower())
    assert (token.effective_power, token.effective_toughness) == body
    assert token.effective_colors == {"B"}
    assert bool(game._has_keyword(token, "trample")) is tramples


@_w1g1_pytest.mark.parametrize("name,creature_type,body,tramples", _W1G1_PENUMBRAS)
def test_w1g1_a_penumbra_creature_that_is_exiled_leaves_nothing(
    set_pool, name, creature_type, body, tramples
):
    """"Dies" is the battlefield to the graveyard (CR 700.4). Swords to
    Plowshares exiles: no token, and the creature is in exile."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, [set_pool("APC")[name], lea["Swords to Plowshares"]])
    penumbra = _w1g1_cast(game, name)

    _w1g1_cast(
        game, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[penumbra.permanent_id],
    )

    assert list(game.controlled_by(0)) == []
    assert [c.name for c in game.players[0].exile] == [name]
    assert game.players[0].life == 20 + body[0]


def test_w1g1_penumbra_wurm_dying_in_combat_tramples_and_is_replaced(set_pool):
    """Blocked by a Craw Wurm (6/4): the Penumbra Wurm assigns lethal 4 to it
    and tramples 2 over, takes 6 back and dies — and the 6/6 black Wurm token
    with trample is there in its place."""
    game = _w1g1_duel(set_pool, [set_pool("APC")["Penumbra Wurm"]])
    wurm = _w1g1_cast(game, "Penumbra Wurm")
    blocker = _w1g1_put(game, 1, set_pool("LEA")["Craw Wurm"])

    _w1g1_fight(game, wurm, blocker)

    assert game.players[1].life == 18
    assert [c.name for c in game.players[1].graveyard] == ["Craw Wurm"]
    assert [c.name for c in game.players[0].graveyard] == ["Penumbra Wurm"]
    (token,) = list(game.controlled_by(0))
    assert (token.effective_power, token.effective_toughness) == (6, 6)
    assert token.effective_colors == {"B"} and game._has_keyword(token, "trample")


# --- Spiritmonger ------------------------------------------------------------


def test_w1g1_spiritmonger_grows_when_it_damages_a_creature_and_not_a_player(set_pool):
    """"Whenever this creature deals damage to a creature, put a +1/+1 counter
    on this creature." Blocked by a Grizzly Bears it ends combat a 7/7 with one
    counter; unblocked it deals 6 to the player and stays a 6/6."""
    apc = set_pool("APC")
    game = _w1g1_duel(set_pool, [apc["Spiritmonger"]])
    monger = _w1g1_cast(game, "Spiritmonger")
    bears = _w1g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    _w1g1_fight(game, monger, bears)
    assert (monger.effective_power, monger.effective_toughness) == (7, 7)
    assert int(monger.metadata.get("plus_counters", 0) or 0) == 1
    assert game.players[1].life == 20

    game = _w1g1_duel(set_pool, [apc["Spiritmonger"]])
    monger = _w1g1_cast(game, "Spiritmonger")
    _w1g1_fight(game, monger)
    assert (monger.effective_power, monger.effective_toughness) == (6, 6)
    assert game.players[1].life == 14


def test_w1g1_spiritmonger_regenerates_for_one_black_mana(set_pool):
    """"{B}: Regenerate this creature." One black mana, and the shield replaces
    the destruction 7 damage would cause: still there, tapped."""
    game = _w1g1_duel(
        set_pool, [set_pool("APC")["Spiritmonger"], set_pool("LEA")["Fireball"]]
    )
    monger = _w1g1_cast(game, "Spiritmonger")
    black = game.players[0].mana_pool["B"]
    floating = _w1g1_floating(game)

    used = game.activate_permanent_ability(0, "Spiritmonger", ability_index=0)
    assert used.supported, used.details
    assert black - game.players[0].mana_pool["B"] == 1
    assert floating - _w1g1_floating(game) == 1

    _w1g1_cast(
        game, "Fireball", target_player_index=0,
        target_permanent_ids=[monger.permanent_id], x_value=7,
    )
    assert any(perm is monger for perm in game.controlled_by(0))
    assert monger.tapped and "Spiritmonger regenerated" in game.log


def test_w1g1_spiritmonger_becomes_the_chosen_color_until_end_of_turn(set_pool):
    """"{G}: This creature becomes the color of your choice until end of turn."
    The choice is made as the ability resolves (CR 608.2d): an interactive seat
    is asked, the ability waits on the stack for the answer, and the creature
    is then *only* that colour — until the cleanup step gives black-green back."""
    game = _w1g1_duel(set_pool, [set_pool("APC")["Spiritmonger"]])
    monger = _w1g1_cast(game, "Spiritmonger")
    assert monger.effective_colors == {"B", "G"}
    game.interactive_seats = {0}
    green = game.players[0].mana_pool["G"]

    used = game.queue_permanent_ability(0, "Spiritmonger", ability_index=1)
    assert used.supported, used.details
    assert green - game.players[0].mana_pool["G"] == 1
    game.resolve_top_of_stack()
    (choice,) = game.pending_choices
    assert (choice.kind, choice.player_index) == ("color_choice", 0)
    assert game.waiting_prompt() is choice
    assert monger.effective_colors == {"B", "G"}

    assert game.confirm_color_choice(0, "R")
    assert not game.pending_choices and not game.stack
    assert monger.effective_colors == {"R"}

    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert monger.effective_colors == {"B", "G"}


# --- Lightning Angel / Gaea's Skyfolk ----------------------------------------


def test_w1g1_lightning_angel_attacks_the_turn_it_enters_and_does_not_tap(set_pool):
    """"Flying, vigilance, haste." Cast precombat, it attacks that same turn
    (haste), a ground creature cannot block it (flying), it deals 3 and is
    still untapped afterwards (vigilance)."""
    game = _w1g1_duel(set_pool, [set_pool("APC")["Lightning Angel"]])
    bears = _w1g1_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update(_W1G1_RICH)
    angel = _w1g1_cast(game, "Lightning Angel")
    assert (angel.effective_power, angel.effective_toughness) == (3, 4)
    game.advance_combat_phase()
    game.advance_combat_phase()

    declared = game.declare_attackers(0, [_w1g1_slot(game, 0, angel)])
    assert declared[0], declared
    assert not angel.tapped
    game.advance_combat_phase()
    grounded = game.declare_blockers(1, {_w1g1_slot(game, 1, bears): 0})
    assert not grounded[0], grounded
    assert game.declare_blockers(1, {})[0]
    _w1g1_finish_combat(game)

    assert game.players[1].life == 17
    assert not angel.tapped


def test_w1g1_gaeas_skyfolk_is_a_two_two_flier_of_both_its_colors(set_pool):
    """A green-blue 2/2 Elf Merfolk with flying: a Grizzly Bears cannot block
    it, a Birds of Paradise can — and dies to it."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, [set_pool("APC")["Gaea's Skyfolk"]])
    skyfolk = _w1g1_cast(game, "Gaea's Skyfolk")
    bears = _w1g1_put(game, 1, lea["Grizzly Bears"])
    birds = _w1g1_put(game, 1, lea["Birds of Paradise"])
    assert (skyfolk.effective_power, skyfolk.effective_toughness) == (2, 2)
    assert skyfolk.effective_colors == {"G", "U"}
    assert skyfolk.has_type("elf") and skyfolk.has_type("merfolk")

    _w1g1_to_declare_attackers(game)
    slot = _w1g1_slot(game, 0, skyfolk)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g1_slot(game, 1, bears): slot})[0]
    assert game.declare_blockers(1, {_w1g1_slot(game, 1, birds): slot})[0]
    _w1g1_finish_combat(game)

    assert [c.name for c in game.players[1].graveyard] == ["Birds of Paradise"]
    assert any(perm is skyfolk for perm in game.controlled_by(0))
    assert game.players[1].life == 20

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

import pytest as _w1g3_pytest

from engine import Game as _w1g3_Game, PlayerState as _w1g3_Player
from engine.game_types import CardDefinition as _w1g3_CardDefinition
from engine.models import Permanent as _w1g3_Permanent
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_card(name, type_line, power="2", toughness="2"):
    """A card that is nothing but a printed type line, which is the whole of
    what a recruiter reads off the cards it turns over."""
    return _w1g3_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": power, "toughness": toughness},
    )  # W1G3 creatures: a typed card


def _w1g3_duel(hand=(), library=(), *, mine=(), theirs=(), interactive=(), mana=False):
    """Seat 0 with *hand* over *library*; both boards placed and unsick."""
    board0 = [_w1g3_Permanent(card=card) for card in mine]
    board1 = [_w1g3_Permanent(card=card) for card in theirs]
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game = _w1g3_Game(players=[
        _w1g3_Player(name="P0", hand=list(hand), library=list(library), battlefield=board0),
        _w1g3_Player(name="P1", battlefield=board1),
    ])
    game.enforce_mana_costs = bool(mana)
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, board0, board1  # W1G3 creatures: the duel


def _w1g3_names(cards):
    return [card.name for card in cards]  # W1G3 creatures: names


_W1G3_RECRUITERS = (
    ("Enlistment Officer", "Soldier"),
    ("Goblin Ringleader", "Goblin"),
    ("Grave Defiler", "Zombie"),
    ("Kavu Howler", "Kavu"),
    ("Sylvan Messenger", "Elf"),
    ("Tidal Courier", "Merfolk"),
)


@_w1g3_pytest.mark.parametrize(("recruiter", "tribe"), _W1G3_RECRUITERS)
def test_w1g3_a_recruiter_takes_its_tribe_from_the_top_four_and_bottoms_the_rest(
    set_pool, recruiter, tribe,
):
    """"When this creature enters, reveal the top four cards of your library.
    Put all <Tribe> cards revealed this way into your hand and the rest on the
    bottom of your library in any order."

    One sentence on six cards with the subtype changed. Played through the
    stack, because the trigger is an object on it (CR 603.3): the creature is
    on the battlefield and nothing has been turned over until the trigger
    resolves. A second subtype on the card (a Human Soldier is a Soldier) and
    a second card type (an artifact creature) change nothing; the fifth card
    is of the tribe and is never seen.
    """
    first = _w1g3_card(f"{tribe} One", f"Creature — {tribe}")
    land = _w1g3_card("A Land", "Land")
    stranger = _w1g3_card("An Ox", "Creature — Ox")
    second = _w1g3_card(f"{tribe} Two", f"Artifact Creature — Human {tribe}")
    fifth = _w1g3_card(f"{tribe} Unseen", f"Creature — {tribe}")
    game, _, _ = _w1g3_duel(
        [set_pool("APC")[recruiter]], [first, land, stranger, second, fifth],
    )
    me = game.players[0]

    assert game.queue_from_hand(0, recruiter).supported
    assert game.resolve_top_of_stack()

    assert [p.card.name for p in game.controlled_by(0)] == [recruiter]
    assert [item.card.name for item in game.stack] == [recruiter], game.log
    assert me.hand == [] and len(me.library) == 5 and not game.reveal_events

    _w1g3_resolve_stack(game)

    assert _w1g3_names(me.hand) == [f"{tribe} One", f"{tribe} Two"], game.log
    assert _w1g3_names(me.library) == [f"{tribe} Unseen", "A Land", "An Ox"]
    assert game.reveal_events[-1]["seat"] == 0
    assert game.reveal_events[-1]["cards"] == [
        f"{tribe} One", "A Land", "An Ox", f"{tribe} Two",
    ]
    assert f"P0 revealed {tribe} One, A Land, An Ox, {tribe} Two" in game.log
    assert (
        f"P0 put {tribe} One, {tribe} Two into their hand and 2 card(s) on the "
        "bottom of their library"
    ) in game.log
    assert game.stack == [] and game.pending_choices == []


def test_w1g3_goblin_ringleader_reads_the_type_line_and_not_the_name(set_pool):
    """A "Goblin card" is a card with the subtype (CR 205.3): a card that only
    has the word in its name stays, and with nothing of the tribe in the four
    the whole pile goes under the library in the order it was revealed — the
    card that was fifth is now the next draw."""
    library = [
        _w1g3_card("Goblin Shrine", "Enchantment"),
        _w1g3_card("Goblin Mountaineer's Wall", "Creature — Wall"),
        _w1g3_card("A Land", "Land"),
        _w1g3_card("An Ox", "Creature — Ox"),
        _w1g3_card("Fifth", "Creature — Goblin"),
    ]
    game, _, _ = _w1g3_duel([set_pool("APC")["Goblin Ringleader"]], library)
    me = game.players[0]

    assert game.cast_from_hand(0, "Goblin Ringleader").supported

    assert me.hand == []
    assert _w1g3_names(me.library) == [
        "Fifth", "Goblin Shrine", "Goblin Mountaineer's Wall", "A Land", "An Ox",
    ]
    assert "P0 put no card into their hand and 4 card(s) on the bottom of their library" in game.log


def test_w1g3_a_recruiter_finds_the_real_cards_of_its_tribe(set_pool):
    """The same trigger over printed cards rather than built ones: a Kavu
    Howler turns up another Howler (Creature — Kavu) beside three cards that
    are not Kavu, and takes it."""
    apc = set_pool("APC")
    game, _, _ = _w1g3_duel(
        [apc["Kavu Howler"]],
        [apc["Goblin Ringleader"], apc["Kavu Howler"], apc["Helionaut"], apc["Index"]],
    )
    me = game.players[0]

    assert game.cast_from_hand(0, "Kavu Howler").supported

    assert _w1g3_names(me.hand) == ["Kavu Howler"]
    assert _w1g3_names(me.library) == ["Goblin Ringleader", "Helionaut", "Index"]


def test_w1g3_a_recruiter_over_a_short_library_reveals_what_is_there(set_pool):
    """CR 701.20a shows the cards the library holds. Two cards is an ordinary
    board, and an empty library is one too: nothing is revealed and nobody has
    drawn from it, so nobody loses (CR 704.5b is about a draw)."""
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Sylvan Messenger"]],
        [_w1g3_card("An Elf", "Creature — Elf Druid"), _w1g3_card("A Land", "Land")],
    )
    me = game.players[0]
    assert game.cast_from_hand(0, "Sylvan Messenger").supported
    assert _w1g3_names(me.hand) == ["An Elf"]
    assert _w1g3_names(me.library) == ["A Land"]

    game, _, _ = _w1g3_duel([set_pool("APC")["Sylvan Messenger"]], [])
    me = game.players[0]
    assert game.cast_from_hand(0, "Sylvan Messenger").supported
    assert me.hand == [] and me.library == [] and not game.reveal_events
    assert "P0 has no cards to reveal" in game.log
    assert not me.lost


def test_w1g3_the_order_of_the_rest_is_asked_of_the_player_who_owns_them(set_pool):
    """"…and the rest on the bottom of your library **in any order**."

    CR 401.4: cards put in one position in a library at one time are arranged
    by their owner. An interactive seat is asked — the trigger stays on the
    stack and the game waits (CR 608.2) — and is shown exactly the cards that
    went down. A wrong permutation and another seat's answer are refused;
    the answer reorders those cards and nothing above them."""
    library = [
        _w1g3_card("First Down", "Land"),
        _w1g3_card("A Merfolk", "Creature — Merfolk"),
        _w1g3_card("Second Down", "Creature — Ox"),
        _w1g3_card("Third Down", "Enchantment"),
        _w1g3_card("Untouched", "Land"),
    ]
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Tidal Courier"]], library, interactive={0},
    )
    me = game.players[0]

    assert game.cast_from_hand(0, "Tidal Courier").supported

    assert _w1g3_names(me.hand) == ["A Merfolk"]
    assert [item.card.name for item in game.stack] == ["Tidal Courier"], game.log
    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "reorder_library"
    assert waiting.player_index == 0 and waiting.data["position"] == "bottom"
    assert _w1g3_names(game.reorder_library_pile(waiting)) == [
        "First Down", "Second Down", "Third Down",
    ]

    assert not game.confirm_reorder_library(0, [0, 1])
    assert not game.confirm_reorder_library(0, [0, 0, 1])
    assert not game.confirm_reorder_library(1, [2, 1, 0])
    assert _w1g3_names(me.library) == [
        "Untouched", "First Down", "Second Down", "Third Down",
    ]

    assert game.confirm_reorder_library(0, [2, 0, 1])
    game._settle()

    assert _w1g3_names(me.library) == [
        "Untouched", "Third Down", "First Down", "Second Down",
    ]
    assert game.stack == [] and game.pending_choices == []
    assert "P0 put 3 cards on the bottom of their library in an order they chose" in game.log


def test_w1g3_a_seat_that_is_not_asked_lays_the_rest_down_as_revealed(set_pool):
    """The default order is the one the cards were turned over in, and a seat
    nobody is asking takes it without a prompt being queued — so a headless
    game and an AI seat never stall on a question about the bottom of a deck.
    One card left over has no order to ask about even of a human."""
    cards = [
        _w1g3_card("Down One", "Land"), _w1g3_card("Down Two", "Land"),
        _w1g3_card("Down Three", "Land"), _w1g3_card("Down Four", "Land"),
    ]
    game, _, _ = _w1g3_duel([set_pool("APC")["Grave Defiler"]], cards)
    assert game.cast_from_hand(0, "Grave Defiler").supported
    assert game.pending_choices == [] and game.stack == []
    assert _w1g3_names(game.players[0].library) == [
        "Down One", "Down Two", "Down Three", "Down Four",
    ]

    one_left = [
        _w1g3_card("Zombie A", "Creature — Zombie"),
        _w1g3_card("Zombie B", "Creature — Zombie"),
        _w1g3_card("Zombie C", "Creature — Zombie"),
        _w1g3_card("Down One", "Land"),
    ]
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Grave Defiler"]], one_left, interactive={0},
    )
    assert game.cast_from_hand(0, "Grave Defiler").supported
    assert game.pending_choices == [] and game.stack == []
    assert _w1g3_names(game.players[0].hand) == ["Zombie A", "Zombie B", "Zombie C"]
    assert _w1g3_names(game.players[0].library) == ["Down One"]


def test_w1g3_the_recruiters_keep_their_other_printed_lines(set_pool):
    """The reveal is one line of each card. The others still work: Enlistment
    Officer has first strike, Goblin Ringleader haste, Sylvan Messenger
    trample, Grave Defiler regenerates for {1}{B} and Tidal Courier flies for
    {3}{U} until end of turn."""
    apc = set_pool("APC")
    game, mine, _ = _w1g3_duel(mine=[
        apc["Enlistment Officer"], apc["Goblin Ringleader"],
        apc["Sylvan Messenger"], apc["Grave Defiler"], apc["Tidal Courier"],
    ], mana=True)
    officer, ringleader, messenger, defiler, courier = mine
    me = game.players[0]

    assert game._has_keyword(officer, "first strike")
    assert game._has_keyword(ringleader, "haste")
    assert game._has_keyword(messenger, "trample")

    assert not game.activate_permanent_ability(0, "Grave Defiler").supported
    assert defiler.regeneration_shield == 0
    me.mana_pool["B"] = 2
    assert game.activate_permanent_ability(0, "Grave Defiler").supported
    assert defiler.regeneration_shield == 1 and me.mana_pool["B"] == 0

    assert not game._has_keyword(courier, "flying")
    me.mana_pool["U"] = 4
    assert game.activate_permanent_ability(0, "Tidal Courier").supported
    assert game._has_keyword(courier, "flying") and me.mana_pool["U"] == 0


@_w1g3_pytest.mark.slow
def test_w1g3_the_ai_plays_recruiters_through_whole_games():
    """Three recruiters pinned into both decks of four simulated games: they
    are cast, each reveal is followed by its sort, and the sort accounts for
    every card it turned over — what went to the hand plus what went under the
    library is what was revealed. No prompt is left owing: an AI seat is never
    asked for the order of the rest.

    (The pool is a measured set, so other cards' unsupported casts are in the
    report; only the recruiters' lines are read. The floor is **one** cast, and
    that is the honesty check rather than a count: a seeded game's course moves
    every time another card of the set becomes castable — this seed gave seven
    recruiter casts on the group's own tree and two the day the Volvers
    compiled, with nothing about a recruiter changed — so a floor of four was
    a statement about the other 140 cards. What is asserted of each cast that
    did happen is unchanged.)"""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    names = ["Goblin Ringleader", "Kavu Howler", "Sylvan Messenger"]
    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=4, seed=1337, max_turns=16, required_cards=names,
    )
    assert report.games_completed == 4
    lines = [line.strip() for line in report.log_lines]
    casts = [
        line for line in lines
        if any(f" cast {name} -> resolved" in line for name in names)
    ]
    assert casts, "no recruiter was cast, so the run proves nothing"
    sorts = 0
    for position, line in enumerate(lines):
        if " put " not in line or "on the bottom of their library" not in line:
            continue
        reveal = lines[position - 1]
        seat = line.split(" put ")[0]
        assert reveal.startswith(f"{seat} revealed "), (reveal, line)
        # No Apocalypse card (and no basic land) has a comma in its name, so
        # the log's own separator splits the names.
        revealed = reveal.split(" revealed ", 1)[1].split(", ")
        kept_text = line.split(" put ", 1)[1].split(" into their hand and ")[0]
        kept = [] if kept_text == "no card" else kept_text.split(", ")
        bottomed = int(line.split(" into their hand and ")[1].split(" ")[0])
        assert len(kept) + bottomed == len(revealed) <= 4, (reveal, line)
        assert all(name in revealed for name in kept), (reveal, line)
        sorts += 1
    assert sorts >= len(casts), (sorts, casts)
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [
        i.message for i in report.issues if any(name in i.message for name in names)
    ] == []
    w1g3_recruiters_left_nothing_owing = not report.steps_left_owing
    assert w1g3_recruiters_left_nothing_owing, report.steps_left_owing


# --- The drive list: compiled on arrival, played here ------------------------


@_w1g3_pytest.mark.parametrize(("name", "drawn", "life"), [
    ("Jungle Barrier", 1, 20),
    ("Phyrexian Rager", 1, 19),
    ("Phyrexian Gargantua", 2, 18),
])
def test_w1g3_an_entry_draw_is_a_stack_object_and_then_draws(set_pool, name, drawn, life):
    """"When this creature enters, draw a card." / "…you draw a card and you
    lose 1 life." / "…you draw two cards and you lose 2 life."

    The creature is on the battlefield with its trigger above it before a
    card moves (CR 603.3); resolving it draws off the top and takes the life
    in the same resolution."""
    library = [_w1g3_card(f"Card {n}", "Land") for n in range(1, 5)]
    game, _, _ = _w1g3_duel([set_pool("APC")[name]], library)
    me = game.players[0]

    assert game.queue_from_hand(0, name).supported
    assert game.resolve_top_of_stack()
    assert [p.card.name for p in game.controlled_by(0)] == [name]
    assert [item.card.name for item in game.stack] == [name]
    assert me.hand == [] and me.life == 20

    _w1g3_resolve_stack(game)

    assert _w1g3_names(me.hand) == [f"Card {n}" for n in range(1, drawn + 1)]
    assert len(me.library) == 4 - drawn
    assert me.life == life, game.log
    assert game.players[1].life == 20 and game.players[1].hand == []


def test_w1g3_phyrexian_gargantua_over_one_card_draws_it_and_loses_the_game(set_pool):
    """Two draws off a one-card library: the card is drawn, the life is lost,
    and the second draw is the one from an empty library that CR 704.5b
    answers the next time state-based actions are checked."""
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Phyrexian Gargantua"]], [_w1g3_card("Last Card", "Land")],
    )
    me = game.players[0]

    assert game.cast_from_hand(0, "Phyrexian Gargantua").supported

    assert _w1g3_names(me.hand) == ["Last Card"] and me.life == 18
    assert me.lost
    assert "P0 lost the game (704.5b: drew from empty library)" in game.log


def test_w1g3_jungle_barrier_is_a_wall_that_cannot_attack(set_pool):
    """"Defender (This creature can't attack.)" A 2/6 that the declare
    attackers step refuses, with the turn actually in that step."""
    game, mine, _ = _w1g3_duel(mine=[set_pool("APC")["Jungle Barrier"]])
    barrier, = mine
    game.players[0].library = [_w1g3_card("Filler", "Land")] * 5
    game.players[1].library = [_w1g3_card("Filler", "Land")] * 5
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step

    assert (barrier.effective_power, barrier.effective_toughness) == (2, 6)
    assert game._has_keyword(barrier, "defender")
    assert not game.can_attack(barrier, 1)
    declared = game.declare_attackers(0, [0])
    assert not declared[0], declared
    assert not barrier.tapped


def test_w1g3_coastal_drake_returns_a_kavu_and_only_a_kavu(set_pool):
    """"{1}{U}, {T}: Return target Kavu to its owner's hand."

    The picker offers the Kavu on both boards and nothing else; a creature
    that is not one is refused before anything is paid; the Kavu named goes to
    its **owner's** hand and the Drake is tapped for it."""
    apc = set_pool("APC")
    game, mine, theirs = _w1g3_duel(
        mine=[apc["Coastal Drake"], apc["Kavu Howler"]],
        theirs=[apc["Kavu Howler"], apc["Helionaut"]],
        mana=True,
    )
    drake, my_kavu = mine
    their_kavu, helionaut = theirs
    me = game.players[0]
    me.mana_pool["U"] = 4

    assert game._has_keyword(drake, "flying")
    spec = game.activation_target_spec(0, 0, 0)
    assert spec["requires_target"]
    assert sorted((t["seat"], t["name"]) for t in spec["valid_targets"]) == [
        (0, "Kavu Howler"), (1, "Kavu Howler"),
    ]

    refused = game.activate_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[helionaut.permanent_id],
    )
    assert not refused.supported and not drake.tapped and me.mana_pool["U"] == 4

    bounced = game.activate_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[their_kavu.permanent_id],
    )
    assert bounced.supported, bounced.details
    assert drake.tapped and me.mana_pool["U"] == 2
    assert _w1g3_names(game.players[1].hand) == ["Kavu Howler"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Helionaut"]
    assert game.is_on_battlefield(my_kavu) and me.hand == []

    again = game.activate_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[my_kavu.permanent_id],
    )
    assert not again.supported and game.is_on_battlefield(my_kavu)
    assert me.mana_pool["U"] == 2


def test_w1g3_coastal_drake_needs_a_kavu_to_exist_and_to_still_be_there(set_pool):
    """With no Kavu on the battlefield the ability cannot be activated at all
    (CR 602.2b), nothing paid. And a Kavu that leaves in response is not
    replaced by the one beside it: the ability does nothing (CR 608.2b)."""
    apc = set_pool("APC")
    game, mine, _ = _w1g3_duel(mine=[apc["Coastal Drake"]], theirs=[apc["Helionaut"]])
    drake, = mine
    nothing = game.activate_permanent_ability(0, "Coastal Drake")
    assert not nothing.supported and not drake.tapped

    game, mine, theirs = _w1g3_duel(
        mine=[apc["Coastal Drake"]], theirs=[apc["Kavu Howler"], apc["Kavu Howler"]],
    )
    named, bystander = theirs
    queued = game.queue_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[named.permanent_id],
    )
    assert queued.supported, queued.details
    game.remove_from_battlefield(named)
    _w1g3_resolve_stack(game)

    assert game.is_on_battlefield(bystander)
    assert game.players[1].hand == []


def test_w1g3_living_airship_regenerates_from_lethal_damage(set_pool):
    """"{2}{G}: Regenerate this creature." A blue flier whose shield is green
    mana: paid, the next destruction this turn taps it, clears its damage and
    leaves it on the battlefield (CR 701.19a) — and the shield is spent, so
    the second bolt kills it."""
    game, mine, _ = _w1g3_duel(
        [set_pool("LEA")["Lightning Bolt"], set_pool("LEA")["Lightning Bolt"]],
        mine=[set_pool("APC")["Living Airship"]], mana=True,
    )
    airship, = mine
    me = game.players[0]

    assert game._has_keyword(airship, "flying")
    assert not game.activate_permanent_ability(0, "Living Airship").supported
    assert airship.regeneration_shield == 0

    me.mana_pool["G"] = 1
    me.mana_pool["U"] = 2
    assert game.activate_permanent_ability(0, "Living Airship").supported
    assert airship.regeneration_shield == 1
    assert me.mana_pool["G"] == 0 and me.mana_pool["U"] == 0

    game.enforce_mana_costs = False
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[airship.permanent_id],
    ).supported
    assert game.is_on_battlefield(airship), game.log
    assert airship.tapped and airship.damage_marked == 0 and airship.regeneration_shield == 0

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[airship.permanent_id],
    ).supported
    assert not game.is_on_battlefield(airship)
    assert "Living Airship" in _w1g3_names(me.graveyard)


def test_w1g3_helionaut_filters_one_mana_into_any_colour(set_pool):
    """"{1}, {T}: Add one mana of any color." A mana ability (CR 605.1a): it
    never uses the stack, it costs a mana to make one, and the colour is the
    one named. Without the {1} it is refused untapped; summoning sick it
    cannot be tapped for it (CR 302.6)."""
    game, mine, _ = _w1g3_duel(mine=[set_pool("APC")["Helionaut"]], mana=True)
    helionaut, = mine
    me = game.players[0]

    assert game._has_keyword(helionaut, "flying")
    broke = game.activate_permanent_ability(0, "Helionaut", mana_color="R")
    assert not broke.supported and not helionaut.tapped

    me.mana_pool["G"] = 1
    made = game.activate_permanent_ability(0, "Helionaut", mana_color="R")
    assert made.supported, made.details
    assert helionaut.tapped and game.stack == []
    assert {c: n for c, n in me.mana_pool.items() if n} == {"R": 1}

    game, mine, _ = _w1g3_duel(mine=[set_pool("APC")["Helionaut"]], mana=True)
    fresh, = mine
    fresh.metadata["summoning_sickness_turn"] = game.turn
    game.players[0].mana_pool["G"] = 1
    sick = game.activate_permanent_ability(0, "Helionaut", mana_color="W")
    assert not sick.supported and not fresh.tapped
    assert game.players[0].mana_pool["G"] == 1

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5_Game, PlayerState as _w1g5_Player
from engine.models import Permanent as _w1g5_Permanent
from engine.stack_targets import chosen_targets as _w1g5_chosen_targets
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import resolve_stack as _w1g5_resolve_stack

_W1G5_REQUIRED = "must be chosen as a target if able"


def _w1g5_duel(mine=(), theirs=(), *, hand0=(), hand1=(), active=0, interactive=()):
    """Two boards placed and unsick, *active*'s turn begun. Cards are card
    objects; returns ``(game, seat 0's permanents, seat 1's permanents)``."""
    board0 = [_w1g5_Permanent(card=card) for card in mine]
    board1 = [_w1g5_Permanent(card=card) for card in theirs]
    filler = _w1g5_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5_Game(players=[
        _w1g5_Player(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        _w1g5_Player(name="P1", battlefield=board1, hand=list(hand1), library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._settle()
    return game, board0, board1  # W1G5 creatures: the duel


def _w1g5_names(game, seat):
    return [permanent.card.name for permanent in game.controlled_by(seat)]  # W1G5 creatures


def test_standard_bearer_takes_the_bolt_meant_for_anything_else(set_pool):
    """Standard Bearer {1}{W} 1/1 Human Flagbearer: "While an opponent is
    choosing targets as part of casting a spell they control…, that player
    must choose at least one Flagbearer on the battlefield if able."

    Lightning Bolt against a board holding the Bearer: the picker offers the
    Bearer and nothing else, a Bolt at the face, at the Bears, or at nothing is
    refused with the card still in hand, and the Bolt that names the Bearer
    kills it — after which the second Bolt goes where its caster likes."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, _mine, theirs = _w1g5_duel(
        [], [apc["Standard Bearer"], lea["Grizzly Bears"]],
        hand0=[lea["Lightning Bolt"], lea["Lightning Bolt"]],
    )
    bearer, bears = theirs
    offered = game.cast_target_spec(0, lea["Lightning Bolt"])
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Standard Bearer"]
    assert [entry["id"] for entry in offered["required_targets"]] == [bearer.permanent_id]

    for announcement in (
        {"target_player_index": 1},
        {"target_permanent_ids": [bears.permanent_id]},
        {},
    ):
        refused = game.queue_from_hand(0, "Lightning Bolt", **announcement)
        assert not refused.supported and _W1G5_REQUIRED in refused.details, refused
        assert "Flagbearer" in refused.details and "Standard Bearer" in refused.details
    assert not game.stack and len(game.players[0].hand) == 2

    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bearer.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Grizzly Bears"]
    assert [card.name for card in game.players[1].graveyard] == ["Standard Bearer"]

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.players[1].life == 17


def test_a_flagbearer_binds_only_an_opponent_who_is_able(set_pool):
    """The three edges of "an opponent … if able". The Bearer's own controller
    casts at what they like; Royal Assassin's "target tapped creature" cannot
    name an untapped Bearer, so it is not bound; and a spell whose only target
    is a player never is."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, theirs = _w1g5_duel(
        [lea["Royal Assassin"]], [apc["Standard Bearer"], lea["Grizzly Bears"]],
        hand0=[lea["Ancestral Recall"]], hand1=[lea["Giant Growth"]],
    )
    bearer, bears = theirs
    # Its controller's own spell.
    assert game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)
    # "Target tapped creature": the untapped Bearer is no legal target.
    bears.tapped = True
    spec = game.activation_target_spec(0, game.battlefield_index_of(mine[0]), ability_index=0)
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]
    assert "required_targets" not in spec
    assert game.queue_permanent_ability(
        0, "Royal Assassin", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Standard Bearer"]
    # "Target player draws three cards."
    assert game.cast_from_hand(0, "Ancestral Recall", target_player_index=0).supported
    assert len(game.players[0].hand) == 3


def test_coalition_honor_guard_binds_an_activation_and_never_a_trigger(set_pool):
    """Coalition Honor Guard {3}{W} 2/4 Human Flagbearer, the same sentence.
    "…or activating an ability they control": Prodigal Sorcerer aimed at the
    face is refused, and a Sorcerer that names nothing has one legal
    announcement and makes it — the Guard takes the damage. "Triggered
    abilities … don't have to target a Flagbearer" (ruling, 2016-06-08):
    Nekrataal's entry trigger destroys the Bears beside it."""
    apc, lea, vis = set_pool("APC"), set_pool("LEA"), set_pool("VIS")
    game, _mine, theirs = _w1g5_duel(
        [lea["Prodigal Sorcerer"]],
        [apc["Coalition Honor Guard"], lea["Grizzly Bears"]],
        hand0=[vis["Nekrataal"]],
    )
    guard, bears = theirs
    refused = game.queue_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert not refused.supported and _W1G5_REQUIRED in refused.details, refused
    assert game.players[1].life == 20 and not game.stack

    assert game.queue_permanent_ability(0, "Prodigal Sorcerer").supported
    targets = _w1g5_chosen_targets(game, game.stack[-1])
    assert [target.permanent_id for target in targets] == [guard.permanent_id]
    _w1g5_resolve_stack(game)
    assert guard.damage_marked == 1 and game.players[1].life == 20

    assert game.queue_from_hand(
        0, "Nekrataal", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Coalition Honor Guard"]
    assert "Grizzly Bears" in [card.name for card in game.players[1].graveyard]


def test_any_players_flagbearer_answers_the_requirement(set_pool):
    """"Any player's Flagbearer may be targeted" (ruling, 2016-06-08): with a
    Flagbearer on each side, a Giant Growth its caster may not put on their own
    Bears goes on their own Honor Guard."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5_duel(
        [lea["Grizzly Bears"], apc["Coalition Honor Guard"]], [apc["Standard Bearer"]],
        hand0=[lea["Giant Growth"]],
    )
    bears, guard = mine
    offered = game.cast_target_spec(0, lea["Giant Growth"])["valid_targets"]
    assert sorted(entry["name"] for entry in offered) == [
        "Coalition Honor Guard", "Standard Bearer",
    ]
    refused = game.queue_from_hand(0, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and _W1G5_REQUIRED in refused.details
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[guard.permanent_id]
    ).supported
    assert (guard.effective_power, guard.effective_toughness) == (5, 7)


def test_a_flagbearer_without_its_ability_demands_nothing(set_pool):
    """The requirement is an ability of the Flagbearer, so Humility ("All
    creatures lose all abilities…") turns it off: the Bolt goes to the face
    with the Bearer — still a Flagbearer — sitting there."""
    apc, lea, tmp = set_pool("APC"), set_pool("LEA"), set_pool("TMP")
    game, _mine, theirs = _w1g5_duel(
        [], [apc["Standard Bearer"], tmp["Humility"]], hand0=[lea["Lightning Bolt"]],
    )
    assert theirs[0].has_type("flagbearer")
    assert "required_targets" not in game.cast_target_spec(0, lea["Lightning Bolt"])
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.players[1].life == 17


def test_a_target_chosen_before_the_flagbearer_arrived_stays_chosen(set_pool):
    """The rule is about *choosing* targets. A Bolt already on the stack aimed
    at the Bears is not made illegal by a Bearer that enters in response
    (CR 608.2b re-asks what the spell printed, not what a permanent demanded of
    the announcement), and resolves where it was aimed."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, _mine, theirs = _w1g5_duel([], [lea["Grizzly Bears"]], hand0=[lea["Lightning Bolt"]])
    bears = theirs[0]
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    game._put_permanent_onto_battlefield(
        1, _w1g5_Permanent(card=apc["Standard Bearer"]), None
    )
    _w1g5_resolve_stack(game)
    game._settle()
    assert _w1g5_names(game, 1) == ["Standard Bearer"]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_mystic_snake_counters_the_spell_its_caster_named(set_pool):
    """Mystic Snake {1}{G}{U}{U} 2/2, flash: "When this creature enters,
    counter target spell." Two spells are on the stack and the Snake is flashed
    in naming the **lower** one. The named Bolt is countered and the Shock
    above it resolves. The announcement used to be dropped between the cast and
    the trigger, which then countered whatever was on top."""
    apc, lea, sth = set_pool("APC"), set_pool("LEA"), set_pool("STH")
    game, _mine, _theirs = _w1g5_duel(
        hand0=[apc["Mystic Snake"]], hand1=[lea["Lightning Bolt"], sth["Shock"]], active=1,
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    offered = game.cast_target_spec(0, apc["Mystic Snake"])
    assert offered["kind"] == "stack"
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Lightning Bolt", "Shock"]

    bolt = game.stack[0]
    assert game.queue_from_hand(0, "Mystic Snake", target_stack_index=0).supported
    game.resolve_top_of_stack()
    trigger = game.stack[-1]
    assert trigger.is_ability and trigger.target_stack_item is bolt
    assert [t.kind for t in _w1g5_chosen_targets(game, trigger)] == ["stack"]
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 18  # the Shock resolved, the Bolt did not
    assert "Lightning Bolt was countered by Mystic Snake and moved to graveyard" in game.log
    assert _w1g5_names(game, 0) == ["Mystic Snake"]


def test_mystic_snake_with_no_spell_to_counter_loses_its_trigger(set_pool):
    """CR 603.3d: cast into an empty stack, the Snake's trigger has no legal
    target and is removed as it would be put on the stack. A 2/2 with flash and
    nothing else — it used to resolve "with no spell to counter"."""
    apc = set_pool("APC")
    game, _mine, _theirs = _w1g5_duel(hand0=[apc["Mystic Snake"]])
    assert game.cast_target_spec(0, apc["Mystic Snake"])["valid_targets"] == []
    assert game.queue_from_hand(0, "Mystic Snake").supported
    game.resolve_top_of_stack()
    assert not game.stack
    assert (
        "Mystic Snake's triggered ability was removed from the stack: "
        "it has no legal target (603.3d)"
    ) in game.log
    snake = next(iter(game.controlled_by(0)))
    assert (snake.effective_power, snake.effective_toughness) == (2, 2)


def test_a_snake_nobody_cast_chooses_for_itself_and_prefers_an_opponents_spell(set_pool):
    """Put onto the battlefield without being cast, the Snake's trigger chooses
    its target as it goes on the stack (CR 603.3d): with its controller's own
    Giant Growth on top of an opponent's Bolt, the default is the opponent's
    spell, and the Growth resolves."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    game, mine, _theirs = _w1g5_duel(
        [lea["Grizzly Bears"]], hand0=[lea["Giant Growth"]],
        hand1=[lea["Lightning Bolt"]], active=1,
    )
    bears = mine[0]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    bolt = game.stack[0]
    game._put_permanent_onto_battlefield(0, _w1g5_Permanent(card=apc["Mystic Snake"]), None)
    trigger = game.stack[-1]
    assert trigger.is_ability and trigger.target_stack_item is bolt
    assert "Mystic Snake: targets Lightning Bolt" in game.log
    game.resolve_top_of_stack()   # the trigger
    game.resolve_top_of_stack()   # Giant Growth
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)
    assert not game.stack and game.players[0].life == 20


def test_the_snake_chooses_again_when_the_spell_it_named_has_gone(set_pool):
    """The cast's announcement is a pre-answer to the trigger's own choice and
    has to be one that choice would accept: with the named Bolt countered while
    the Snake waited, the trigger says so and takes the Shock instead."""
    apc, lea, sth = set_pool("APC"), set_pool("LEA"), set_pool("STH")
    game, _mine, _theirs = _w1g5_duel(
        hand0=[apc["Mystic Snake"]], hand1=[lea["Lightning Bolt"], sth["Shock"]], active=1,
    )
    game.queue_from_hand(1, "Shock", target_player_index=0)
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    shock, bolt = game.stack
    assert game.queue_from_hand(0, "Mystic Snake", target_stack_index=1).supported
    game.counter_stack_object(bolt)
    game.resolve_top_of_stack()
    assert (
        "Mystic Snake's triggered ability can't target what was named as it "
        "was cast; it chooses again (603.3d)"
    ) in game.log
    assert game.stack[-1].target_stack_item is shock
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 20


def test_the_snakes_trigger_counters_nothing_once_its_spell_has_left(set_pool):
    """CR 608.2b at the other end: the trigger is on the stack naming the
    Shock, and the Shock leaves in response. The trigger's only target is gone,
    so it counters nothing — it used to fall back to the top of the stack and
    counter the Lightning Bolt nobody had named, which here resolves."""
    apc, lea, sth = set_pool("APC"), set_pool("LEA"), set_pool("STH")
    game, _mine, _theirs = _w1g5_duel(
        hand0=[apc["Mystic Snake"]], hand1=[lea["Lightning Bolt"], sth["Shock"]], active=1,
    )
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.queue_from_hand(1, "Shock", target_player_index=0)
    _bolt, shock = game.stack
    assert game.queue_from_hand(0, "Mystic Snake", target_stack_index=1).supported
    game.resolve_top_of_stack()
    assert game.stack[-1].target_stack_item is shock
    game.counter_stack_object(shock)
    _w1g5_resolve_stack(game)
    assert "Mystic Snake: the spell it would counter is no longer on the stack" in game.log
    assert not any("was countered by Mystic Snake" in line for line in game.log)
    assert game.players[0].life == 17   # the Bolt was never the Snake's target

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.card_loader import manifest_set_path as _w1g6_manifest_set_path
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import _damage_dealt as _w1g6_damage_dealt
from tests.helpers import resolve_stack as _w1g6_resolve_stack

#: Where the furniture these tests stand beside Apocalypse's creatures is
#: printed. Apocalypse first, so a name it prints is always its own card.
_W1G6_SETS = ("APC", "LEA", "LEG")

_W1G6_BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


def _w1g6_find(set_pool, name):
    for w1g6_code in _W1G6_SETS:
        w1g6_found = set_pool(w1g6_code).get(name)
        if w1g6_found is not None:
            return w1g6_found
    raise KeyError(name)  # _w1g6_find


def _w1g6_table(set_pool, mine=(), theirs=(), hand=(), their_hand=(), enforce=False,
                interactive=False, active=0):
    """A two-seat table in *active*'s first main phase, with *mine* / *theirs*
    on the battlefield and unsick, and *hand* / *their_hand* in hand."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="W1G6-A", hand=[_w1g6_find(set_pool, n) for n in hand]),
        _W1G6PlayerState(name="W1G6-B", hand=[_w1g6_find(set_pool, n) for n in their_hand]),
    ])
    w1g6_game.enforce_mana_costs = enforce
    w1g6_game.active_player_index = active
    w1g6_game.current_turn_phase = w1g6_game.current_step = "precombat_main"
    if interactive:
        w1g6_game.interactive_seats.add(0)
    w1g6_rows = []
    for w1g6_seat, w1g6_names in enumerate((mine, theirs)):
        w1g6_row = []
        for w1g6_name in w1g6_names:
            w1g6_perm = _W1G6Permanent(card=_w1g6_find(set_pool, w1g6_name))
            w1g6_game._put_permanent_onto_battlefield(w1g6_seat, w1g6_perm, None)
            w1g6_perm.metadata["summoning_sickness_turn"] = -99
            w1g6_row.append(w1g6_perm)
        w1g6_rows.append(w1g6_row)
    return w1g6_game, w1g6_rows[0], w1g6_rows[1]  # _w1g6_table


def _w1g6_upkeep(game, seat=0):
    """Run *seat*'s upkeep step and leave what triggered on the stack; returns
    the names of the sources there."""
    game.active_player_index = seat
    game.resolve_upkeep(seat, defer_priority=True)
    return [w1g6_item.card.name for w1g6_item in game.stack]  # _w1g6_upkeep


def _w1g6_tap_for(game, land, colour, seat=0):
    """Tap *land* for one mana of *colour* through the real mana ability."""
    w1g6_tapped = game.tap_land_for_mana(
        seat, land.card.name, colour, permanent_id=land.permanent_id,
    )
    assert w1g6_tapped, f"{land.card.name} did not tap for {colour}"
    return w1g6_tapped  # _w1g6_tap_for


def _w1g6_offered(game, permanent, ability_index):
    """What the activation picker offers for one ability of *permanent*, as
    card names and ``player<seat>`` entries."""
    w1g6_spec = game.activation_target_spec(
        0, game.battlefield_index_of(permanent), ability_index,
    )
    w1g6_names = []
    for w1g6_entry in w1g6_spec.get("valid_targets", []):
        if w1g6_entry.get("kind") == "permanent":
            w1g6_names.append(
                game.permanent_at(w1g6_entry["seat"], w1g6_entry["index"]).card.name
            )
        else:
            w1g6_names.append(f"player{w1g6_entry.get('seat')}")
    return w1g6_names  # _w1g6_offered


# Gerrard Capashen ------------------------------------------------------------


def test_w1g6_gerrard_capashen_gains_a_life_for_each_card_in_an_opponents_hand(set_pool):
    """"At the beginning of your upkeep, you gain 1 life for each card in
    target opponent's hand." The opponent is a target, chosen as the trigger
    goes on the stack, and only an opponent is offered; the count is of that
    hand, not of Gerrard's controller's."""
    program = _w1g6_compile(set_pool("APC")["Gerrard Capashen"])
    assert program.supported, program.reason

    game, _mine, _theirs = _w1g6_table(
        set_pool, mine=["Gerrard Capashen"], hand=["Forest"] * 5,
        their_hand=["Forest"] * 3, interactive=True,
    )
    assert _w1g6_upkeep(game) == ["Gerrard Capashen"]
    (prompt,) = game.pending_choices
    assert [(entry["kind"], entry["seat"]) for entry in prompt.data["targets"]] == [
        ("player", 1),
    ]
    assert not game.confirm_trigger_target(0, seat=0)
    assert game.confirm_trigger_target(0, seat=1)
    _w1g6_resolve_stack(game)

    assert [player.life for player in game.players] == [23, 20]
    assert "W1G6-A gained 3 life from Gerrard Capashen (20 -> 23)" in game.log

    # Not on the opponent's upkeep, and an empty hand is worth nothing.
    assert _w1g6_upkeep(game, seat=1) == []
    game, _mine, _theirs = _w1g6_table(set_pool, mine=["Gerrard Capashen"], hand=["Forest"])
    assert _w1g6_upkeep(game) == ["Gerrard Capashen"]
    _w1g6_resolve_stack(game)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g6_gerrard_capashen_taps_only_while_he_is_attacking(set_pool):
    """"{3}{W}: Tap target creature. Activate only if Gerrard Capashen is
    attacking." The clause names the card (CR 201.5) and is enforced: refused
    at home with nothing spent, legal once he is declared as an attacker, and
    the mana is charged."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Gerrard Capashen"] + ["Plains"] * 4,
        theirs=["Hill Giant", "Grizzly Bears"], enforce=True,
    )
    gerrard, giant = mine[0], theirs[0]
    for land in mine[1:]:
        _w1g6_tap_for(game, land, "W")

    refused = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[giant.permanent_id], ability_index=0,
    )
    assert not refused.supported
    assert refused.details == "Gerrard Capashen: this creature is not attacking"
    assert not giant.tapped and sum(game.players[0].mana_pool.values()) == 4

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(gerrard)])[0]
    assert gerrard.attacking
    # The picker offers creatures — every one, his own side's too — and a land
    # named anyway is refused before the cost is paid.
    assert _w1g6_offered(game, gerrard, 0) == [
        "Gerrard Capashen", "Hill Giant", "Grizzly Bears",
    ]
    wrong = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[mine[1].permanent_id], ability_index=0,
    )
    assert not wrong.supported and sum(game.players[0].mana_pool.values()) == 4

    tapped = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[giant.permanent_id], ability_index=0,
    )
    assert tapped.supported, tapped.details
    _w1g6_resolve_stack(game)
    assert giant.tapped and not theirs[1].tapped
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g6_gerrard_capashens_clause_is_read_as_a_self_reference_only():
    """The row reads "this <noun> is attacking" — the card's own name collapsed
    (CR 201.5) — so the clause is a restriction with the name in hand and an
    unread sentence without it. Some *other* creature's name is never the
    subject: read as one, the clause would be admitted and then ask about the
    wrong permanent."""
    from engine.activation_restrictions import activation_restriction_line

    clause = "Activate only if Gerrard Capashen is attacking."
    assert activation_restriction_line(clause, "Gerrard Capashen")
    assert not activation_restriction_line(clause)
    assert not activation_restriction_line(clause, "Dwarven Patrol")
    assert activation_restriction_line("Activate only if this creature is attacking.")
    assert not activation_restriction_line("Activate only if this creature is sleeping.")


def test_w1g6_gerrard_capashens_ability_costs_three_and_a_white(set_pool):
    """Attacking, with nothing in the pool: refused for the mana, and the
    Giant stays untapped."""
    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Gerrard Capashen"], theirs=["Hill Giant"], enforce=True,
    )
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0])[0]

    unpaid = game.activate_permanent_ability(
        0, "Gerrard Capashen", target_permanent_ids=[theirs[0].permanent_id], ability_index=0,
    )

    assert not unpaid.supported and "insufficient mana" in unpaid.details
    assert not theirs[0].tapped


# Dwarven Patrol ---------------------------------------------------------------


def test_w1g6_dwarven_patrol_stays_tapped_through_its_controllers_untap_step(set_pool):
    """"This creature doesn't untap during your untap step." The Bears beside
    it do."""
    game, mine, _theirs = _w1g6_table(set_pool, mine=["Dwarven Patrol", "Grizzly Bears"])
    for permanent in mine:
        permanent.tapped = True

    game.resolve_untap_step(0)

    assert [(permanent.card.name, permanent.tapped) for permanent in mine] == [
        ("Dwarven Patrol", True), ("Grizzly Bears", False),
    ]


@_w1g6_pytest.mark.parametrize("spell, untaps", [
    ("Grizzly Bears", True),               # green
    ("Giant Growth", True),                # an instant is a spell too
    ("Sol Ring", True),                    # colourless is not red (CR 105.2c)
    ("Goblin King", False),                # red
    ("Lightning Bolt", False),
    ("Jerrard of the Closed Fist", False), # red and green is red (CR 105.2b)
])
def test_w1g6_dwarven_patrol_untaps_when_its_controller_casts_a_nonred_spell(
    set_pool, spell, untaps,
):
    """"Whenever you cast a nonred spell, untap this creature." A trigger on
    the cast (it resolves before the spell does), narrowed by what the spell's
    colours are *not*."""
    program = _w1g6_compile(set_pool("APC")["Dwarven Patrol"])
    assert program.supported, program.reason

    game, mine, theirs = _w1g6_table(
        set_pool, mine=["Dwarven Patrol"], theirs=["Hill Giant"], hand=[spell],
    )
    patrol = mine[0]
    patrol.tapped = True
    aimed = {}
    if spell == "Giant Growth":
        aimed = {"target_permanent_ids": [patrol.permanent_id]}
    elif spell == "Lightning Bolt":
        aimed = {"target_player_index": 1}

    cast = game.queue_from_hand(0, spell, **aimed)
    assert cast.supported, cast.details
    on_stack = [item.card.name for item in game.stack]
    assert on_stack == ([spell, "Dwarven Patrol"] if untaps else [spell])
    _w1g6_resolve_stack(game)

    assert patrol.tapped is not untaps
    assert ("Dwarven Patrol untapped" in game.log) is untaps


def test_w1g6_dwarven_patrol_ignores_an_opponents_spell_and_a_land(set_pool):
    """"**You** cast": the opponent's green spell is not the trigger. And a
    land is played, not cast — "Remember that lands are not spells" (the card's
    ruling, 2004-10-04)."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=["Dwarven Patrol"], their_hand=["Grizzly Bears"], active=1,
    )
    mine[0].tapped = True
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    _w1g6_resolve_stack(game)
    assert mine[0].tapped

    game, mine, _theirs = _w1g6_table(set_pool, mine=["Dwarven Patrol"], hand=["Forest"])
    mine[0].tapped = True
    assert game.cast_from_hand(0, "Forest").supported
    assert [p.card.name for p in game.controlled_by(0)] == ["Dwarven Patrol", "Forest"]
    assert mine[0].tapped and not game.stack


# Bog Gnarr, Glade Gnarr --------------------------------------------------------


@_w1g6_pytest.mark.parametrize("gnarr, base, colour_spell, other_spell", [
    ("Bog Gnarr", (2, 2), "Black Knight", "Grizzly Bears"),
    ("Glade Gnarr", (4, 4), "Prodigal Sorcerer", "Black Knight"),
])
def test_w1g6_a_gnarr_grows_when_any_player_casts_its_colour(
    set_pool, gnarr, base, colour_spell, other_spell,
):
    """"Whenever **a player** casts a black/blue spell, this creature gets
    +2/+2 until end of turn." Either seat's spell of that colour, no other
    colour's, and the bonus is gone at cleanup."""
    grown = (base[0] + 2, base[1] + 2)
    for caster in (0, 1):
        for spell, expected in ((colour_spell, grown), (other_spell, base)):
            hands = {"hand": [spell]} if caster == 0 else {"their_hand": [spell]}
            game, mine, _theirs = _w1g6_table(set_pool, mine=[gnarr], active=caster, **hands)
            assert game.queue_from_hand(caster, spell).supported
            _w1g6_resolve_stack(game)
            size = (mine[0].effective_power, mine[0].effective_toughness)
            assert size == expected, (gnarr, caster, spell)

    game, mine, _theirs = _w1g6_table(set_pool, mine=[gnarr], hand=[colour_spell] * 2)
    assert game.queue_from_hand(0, colour_spell).supported
    assert game.queue_from_hand(0, colour_spell).supported
    _w1g6_resolve_stack(game)
    # Each cast is its own trigger.
    assert (mine[0].effective_power, mine[0].effective_toughness) == (
        base[0] + 4, base[1] + 4,
    )
    game.resolve_cleanup_step(0)
    assert (mine[0].effective_power, mine[0].effective_toughness) == base


# Minotaur Tactician ------------------------------------------------------------


@_w1g6_pytest.mark.parametrize("beside, size", [
    ((), (1, 1)),
    (("White Knight",), (2, 2)),
    (("Prodigal Sorcerer",), (2, 2)),
    (("White Knight", "Prodigal Sorcerer"), (3, 3)),
    # One white-and-blue creature answers both lines.
    (("Tobias Andrion",), (3, 3)),
    # "A white **creature**": a white enchantment is not one.
    (("Circle of Protection: Red",), (1, 1)),
])
def test_w1g6_minotaur_tactician_counts_each_colour_of_creature_once(set_pool, beside, size):
    """Two static lines, one per colour, each +1/+1 "as long as you control" a
    creature of it — yours, so the opponent's white and blue creatures across
    the table add nothing. Haste is printed."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=("Minotaur Tactician",) + beside,
        theirs=["White Knight", "Prodigal Sorcerer"],
    )
    tactician = mine[0]

    assert (tactician.effective_power, tactician.effective_toughness) == size
    assert game._has_keyword(tactician, "haste")


def test_w1g6_minotaur_tactician_shrinks_when_the_white_creature_leaves(set_pool):
    game, mine, _theirs = _w1g6_table(set_pool, mine=["Minotaur Tactician", "White Knight"])
    assert (mine[0].effective_power, mine[0].effective_toughness) == (2, 2)

    game.remove_from_battlefield(mine[1])
    game.check_state_based_actions()

    assert (mine[0].effective_power, mine[0].effective_toughness) == (1, 1)


# The Disciples ----------------------------------------------------------------

#: (card, ability index, the off-colour mana its cost asks for, what it does).
_W1G6_DISCIPLE_ABILITIES = [
    ("Ana Disciple", 0, "U", "flying"),
    ("Ana Disciple", 1, "B", "shrink"),
    ("Ceta Disciple", 0, "R", "grow"),
    ("Ceta Disciple", 1, "G", "mana"),
    ("Dega Disciple", 0, "B", "shrink"),
    ("Dega Disciple", 1, "R", "grow"),
    ("Necra Disciple", 0, "G", "mana"),
    ("Necra Disciple", 1, "W", "prevent"),
    ("Raka Disciple", 0, "W", "prevent"),
    ("Raka Disciple", 1, "U", "flying"),
]


@_w1g6_pytest.mark.parametrize("name, index, colour, effect", _W1G6_DISCIPLE_ABILITIES)
def test_w1g6_each_disciple_ability_is_paid_aimed_and_carried_out(
    set_pool, name, index, colour, effect,
):
    """Every Disciple prints two abilities, each costing one mana of an
    *enemy* colour and a tap. Each is refused with the mana unpaid, offers
    exactly what its sentence targets, does what it says to the creature named
    — the opponent's Hill Giant, not a bystander — and cannot be used again
    while the Disciple is tapped."""
    program = _w1g6_compile(set_pool("APC")[name])
    assert program.supported, program.reason

    game, mine, theirs = _w1g6_table(
        set_pool, mine=[name, _W1G6_BASICS[colour], "Grizzly Bears"],
        theirs=["Hill Giant"], enforce=True,
    )
    disciple, land, bears = mine
    giant = theirs[0]
    aimed = {"ability_index": index}
    if effect == "mana":
        aimed["mana_color"] = "W"
        assert _w1g6_offered(game, disciple, index) == []
    else:
        aimed["target_permanent_ids"] = [giant.permanent_id]
        creatures = [name, "Grizzly Bears", "Hill Giant"]
        assert _w1g6_offered(game, disciple, index) == (
            ["player0", "player1"] + creatures if effect == "prevent" else creatures
        )

    unpaid = game.activate_permanent_ability(0, name, **aimed)
    assert not unpaid.supported and "insufficient mana" in unpaid.details
    assert not disciple.tapped

    _w1g6_tap_for(game, land, colour)
    paid = game.activate_permanent_ability(0, name, **aimed)
    assert paid.supported, paid.details
    _w1g6_resolve_stack(game)
    assert disciple.tapped

    pool = {symbol: n for symbol, n in game.players[0].mana_pool.items() if n}
    size = (giant.effective_power, giant.effective_toughness)
    untouched = (bears.effective_power, bears.effective_toughness) == (2, 2)
    if effect == "mana":
        # A mana ability: one mana of the colour asked for, the {G} spent.
        assert pool == {"W": 1}
    else:
        assert pool == {}
    if effect == "flying":
        assert game._has_keyword(giant, "flying") and not game._has_keyword(bears, "flying")
        game.resolve_cleanup_step(0)
        assert not game._has_keyword(giant, "flying")
    elif effect == "shrink":
        assert size == (1, 3) and untouched
        game.resolve_cleanup_step(0)
        assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    elif effect == "grow":
        assert size == (5, 3) and untouched
    elif effect == "prevent":
        # "Prevent the next 1 damage": one of the next three, and then spent.
        assert _w1g6_damage_dealt(game, giant, 3) == 2
        assert _w1g6_damage_dealt(game, giant, 3) == 3
        assert _w1g6_damage_dealt(game, bears, 1) == 1

    again = game.activate_permanent_ability(0, name, **aimed)
    assert not again.supported and "already tapped" in again.details


@_w1g6_pytest.mark.parametrize("name, index, colour", [
    ("Necra Disciple", 1, "W"), ("Raka Disciple", 0, "W"),
])
def test_w1g6_a_disciples_shield_may_be_put_on_a_player(set_pool, name, index, colour):
    """"…dealt to **any target**": a player's face is one."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=[name, _W1G6_BASICS[colour]], enforce=True,
    )
    _w1g6_tap_for(game, mine[1], colour)

    shielded = game.activate_permanent_ability(
        0, name, ability_index=index, target_player_index=0,
    )
    assert shielded.supported, shielded.details
    _w1g6_resolve_stack(game)

    assert _w1g6_damage_dealt(game, game.players[0], 2) == 1
    assert _w1g6_damage_dealt(game, game.players[1], 2) == 2


@_w1g6_pytest.mark.parametrize("name, index, colour", [
    ("Ana Disciple", 0, "U"), ("Ceta Disciple", 0, "R"), ("Dega Disciple", 0, "B"),
])
def test_w1g6_a_disciple_refuses_a_target_its_sentence_does_not_name(
    set_pool, name, index, colour,
):
    """"Target **creature**": a land named anyway is refused at announcement
    with the mana still in the pool and the Disciple untapped."""
    game, mine, _theirs = _w1g6_table(
        set_pool, mine=[name, _W1G6_BASICS[colour], "Grizzly Bears"], enforce=True,
    )
    _w1g6_tap_for(game, mine[1], colour)

    refused = game.activate_permanent_ability(
        0, name, ability_index=index, target_permanent_ids=[mine[1].permanent_id],
    )

    assert not refused.supported
    assert not mine[0].tapped and game.players[0].mana_pool[colour] == 1
    bears = mine[2]
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(bears, "flying")


# The simulator ------------------------------------------------------------------


@_w1g6_pytest.mark.slow
def test_w1g6_the_ai_plays_the_groups_cards_through_whole_games():
    """Six of the group's cards pinned into both decks of six simulated games.
    They are cast, their upkeep triggers go on the stack and resolve, nothing
    is refused and no step is left owing a prompt. (Apocalypse is a measured
    set, so other cards' unsupported casts are in the report; only these
    cards' lines are read. The floors are well under what the seed gives.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [
        "Ceta Sanctuary", "Necra Sanctuary", "Raka Sanctuary",
        "Mask of Intolerance", "Dwarven Patrol", "Gerrard Capashen",
    ]
    report = run_ai_simulation(
        [_w1g6_manifest_set_path("APC", include_measured=True)],
        games=6, seed=4242, required_cards=names,
    )

    assert report.games_completed == 6
    cast = {
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 4, sorted(cast)
    resolved = {
        name for name in names
        if any(f"{name} ability resolved" in line for line in report.log_lines)
    }
    assert len(resolved) >= 3, sorted(resolved)
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [
        issue.message for issue in report.issues
        if any(name in issue.message for name in names)
    ] == []
    w1g6_nothing_left_owing = not report.steps_left_owing
    assert w1g6_nothing_left_owing, report.steps_left_owing

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.grammar import compile_line as _w1g7_compile_line
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_creature_duel(*, interactive=(0,)):
    """A two-seat game with costs off. Seat 0 is interactive by default, so a
    prompt one of these cards arms is *queued* rather than answered by its own
    default."""
    p0, p1 = _W1G7PlayerState(name="A"), _W1G7PlayerState(name="B")
    game = _W1G7Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p0, p1


def _w1g7_creature_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_activation_targets(game, seat, permanent, ability_index=None):
    """What the activation picker offers for *permanent*'s ability, as
    ``(kind, [names])`` — the engine's own list, which is also the gate."""
    slot = next(
        index for index, held in enumerate(game.players[seat].battlefield)
        if held is permanent
    )
    spec = game.activation_target_spec(seat, slot, ability_index)
    return spec["kind"], [entry["name"] for entry in spec["valid_targets"]]


def _w1g7_prompt(game, seat, key):
    """The payload a human at *seat* is shown for prompt *key*, through the web
    layer's own renderer."""
    from web.prompts import PromptContext, render_prompts

    context = PromptContext(
        game=game, viewer_seat=seat,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    )
    return render_prompts(context)[key]


# -- Vodalian Mystic ---------------------------------------------------------


def test_vodalian_mystic_can_only_be_aimed_at_an_instant_or_sorcery_spell(
    set_pool, catalog_by_name
):
    """"{T}: Target **instant or sorcery** spell becomes the color of your
    choice." The picker is the announcement gate: nothing on the stack, or only
    a creature spell, is nothing to name — and the Mystic stays untapped."""
    game, p0, p1 = _w1g7_creature_duel()
    mystic = _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    p1.hand = [catalog_by_name["Grizzly Bears"], catalog_by_name["Lightning Bolt"]]

    assert _w1g7_activation_targets(game, 0, mystic) == ("stack", [])
    assert not game.queue_permanent_ability(0, "Vodalian Mystic").supported

    game.queue_from_hand(1, "Grizzly Bears")
    assert _w1g7_activation_targets(game, 0, mystic) == ("stack", [])
    refused = game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0)
    assert not refused.supported
    assert mystic.tapped is False

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert _w1g7_activation_targets(game, 0, mystic) == ("stack", ["Lightning Bolt"])


def test_vodalian_mystic_asks_for_the_color_as_it_resolves(set_pool, catalog_by_name):
    """CR 608.2d: "the color of your choice" is named while the effect is
    applied, not announced with the activation. The Bolt is still red while the
    question stands, an answer that is not a colour is refused, and the spell
    is the chosen colour — and no other (CR 105.3) — once it is given."""
    game, p0, p1 = _w1g7_creature_duel()
    mystic = _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    bolt = game.stack[-1]

    assert game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0).supported
    assert mystic.tapped is True
    game.resolve_top_of_stack(pause_for_choices=True)

    asked = _w1g7_prompt(game, 0, "color_choice")
    assert asked is not None and asked["card_name"] == "Vodalian Mystic"
    assert game._stack_item_colors(bolt) == ("R",)
    assert game.resolve_pending_choice("color_choice", 0, mana_color="purple") is False
    assert game.resolve_pending_choice("color_choice", 0, mana_color="U") is True

    assert game._stack_item_colors(bolt) == ("U",)
    assert "Lightning Bolt (on the stack) became U (Vodalian Mystic)" in game.log
    # Only the colour changed: the Bolt still resolves as printed.
    _w1g7_resolve_stack(game)
    assert p0.life == 17


def test_a_spell_vodalian_mystic_recolored_is_that_color_to_every_reader(
    set_pool, catalog_by_name
):
    """One colour record for a spell (``_stack_item_colors``): the blue Bolt is
    a legal target for "counter target blue spell" and no longer one for
    "counter target red spell"."""
    game, p0, p1 = _w1g7_creature_duel()
    _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    red_blast = catalog_by_name["Red Elemental Blast"]
    blue_blast = catalog_by_name["Blue Elemental Blast"]

    def offered(card):
        spec = game.cast_target_spec(0, card, mode_index=0)
        return [entry["name"] for entry in spec["valid_targets"]]

    assert offered(blue_blast) == ["Lightning Bolt"] and offered(red_blast) == []

    game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    game.resolve_pending_choice("color_choice", 0, mana_color="U")

    assert offered(red_blast) == ["Lightning Bolt"] and offered(blue_blast) == []


def test_vodalian_mystic_recolors_nothing_when_its_spell_has_left(
    set_pool, catalog_by_name
):
    """CR 608.2b: the target is gone, so the ability does nothing — it does not
    reach for another spell or for a permanent."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    _w1g7_creature_put(game, 0, set_pool("APC")["Vodalian Mystic"])
    bears = _w1g7_creature_put(game, 1, catalog_by_name["Grizzly Bears"])
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    bolt = game.stack[-1]

    game.queue_permanent_ability(0, "Vodalian Mystic", target_stack_index=0)
    game.counter_stack_object(bolt)
    _w1g7_resolve_stack(game)

    assert "color_override" not in bolt.choices
    assert game._effective_colors(bears) == {"G"}
    assert not any("became" in line for line in game.log)


def test_a_recolored_spell_phrase_carries_its_types_or_refuses():
    """The lowering: the printed card types reach the stack picker, and a
    narrowing nothing tests, a duration or a colour *set* refuses rather than
    recolouring more — or for longer — than the sentence says."""
    typed = _w1g7_compile_line("Target instant spell becomes colorless.")
    assert typed.usable
    assert typed.instructions[0].payload["targets"] == {
        "quantifier": "target", "kind": "spell", "card_types": ["instant"],
    }

    for line, reason in (
        ("Target blue spell becomes the color of your choice.", "colors"),
        ("Target spell becomes the color of your choice until end of turn.",
         "one chosen colour"),
        ("Target spell becomes the color or colors of your choice.",
         "one chosen colour"),
    ):
        refused = _w1g7_compile_line(line)
        assert refused.parsed and not refused.usable
        assert reason in refused.lowering_error


# -- Tundra Kavu -------------------------------------------------------------


def test_tundra_kavu_offers_plains_or_island_and_refuses_any_other_type(
    set_pool, catalog_by_name
):
    """"{T}: Target land becomes **a Plains or an Island** until end of turn."
    The choice is made as the ability resolves (CR 608.2d), among the two the
    card prints: the prompt offers exactly those and a third is refused with
    the land untouched — a restriction on a choice is enforced where the
    choice is made."""
    game, p0, p1 = _w1g7_creature_duel()
    kavu = _w1g7_creature_put(game, 0, set_pool("APC")["Tundra Kavu"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])
    bears = _w1g7_creature_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g7_creature_put(game, 0, catalog_by_name["Swamp"])

    assert _w1g7_activation_targets(game, 0, kavu) == ("land", ["Swamp", "Forest"])
    assert not game.queue_permanent_ability(
        0, "Tundra Kavu", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert kavu.tapped is False

    assert game.queue_permanent_ability(
        0, "Tundra Kavu", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_prompt(game, 0, "land_type_choice")["options"] == ["plains", "island"]
    assert "Tundra Kavu: choose Plains or Island for Forest" in game.log
    for unprinted in ("swamp", "mountain", "forest", "desert"):
        assert game.confirm_land_type(0, unprinted) is False
    assert forest.basic_land_types == ("forest",)

    assert game.confirm_land_type(0, "plains") is True
    # CR 305.7: the land is a Plains *instead of* a Forest, and taps for white.
    assert forest.basic_land_types == ("plains",)
    assert not forest.has_type("forest")
    assert game._land_payment_colors(forest) == ("W",)


def test_tundra_kavus_change_ends_in_the_cleanup_step(set_pool, catalog_by_name):
    game, p0, p1 = _w1g7_creature_duel()
    _w1g7_creature_put(game, 0, set_pool("APC")["Tundra Kavu"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])
    game.queue_permanent_ability(0, "Tundra Kavu", target_permanent_ids=[forest.permanent_id])
    game.resolve_top_of_stack(pause_for_choices=True)
    game.confirm_land_type(0, "island")
    assert forest.basic_land_types == ("island",)

    game.resolve_cleanup_step(0)

    assert forest.basic_land_types == ("forest",)


def test_tundra_kavu_played_by_a_seat_nobody_asks_makes_an_island(
    set_pool, catalog_by_name
):
    """The stated default: an Island, which is one of the two printed types —
    the default has to be an answer the resolver accepts, or the ability would
    resolve having changed nothing."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    _w1g7_creature_put(game, 0, set_pool("APC")["Tundra Kavu"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])

    assert game.activate_permanent_ability(
        0, "Tundra Kavu", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.auto_resolve_pending_choices()

    assert forest.basic_land_types == ("island",)


def test_a_printed_choice_of_land_types_is_among_basic_land_types(set_pool):
    """The production reads the alternatives whole; the lowering admits them
    only where the prompt can carry them. "The basic land type of your choice"
    (Reef Shaman) prints no list and keeps the payload it had."""
    kavu = _w1g7_compile(set_pool("APC")["Tundra Kavu"])
    assert kavu.activated_abilities[0].instruction.payload["land_type_options"] == [
        "plains", "island",
    ]
    shaman = _w1g7_compile(set_pool("APC")["Reef Shaman"])
    assert "land_type_options" not in shaman.activated_abilities[0].instruction.payload

    three = _w1g7_compile_line(
        "Target land becomes a Plains or an Island or a Swamp until end of turn."
    )
    assert three.instructions[0].payload["land_type_options"] == [
        "plains", "island", "swamp",
    ]
    nonbasic = _w1g7_compile_line(
        "Target land becomes a Plains or a Desert until end of turn."
    )
    assert nonbasic.parsed and not nonbasic.usable
    not_a_land_type = _w1g7_compile_line(
        "Target land becomes a Plains or a Wall until end of turn."
    )
    assert not not_a_land_type.parsed


# -- Reef Shaman (driven) ----------------------------------------------------


def test_reef_shaman_makes_a_land_the_basic_land_type_its_controller_names(
    set_pool, catalog_by_name
):
    """"{T}: Target land becomes the basic land type of your choice until end
    of turn." All five are offered, the land is the named type *instead of* its
    own (CR 305.7) — an opponent's Forest made a Swamp taps for {B} whatever it
    is asked for — and the cleanup step gives the Forest back."""
    game, p0, p1 = _w1g7_creature_duel()
    shaman = _w1g7_creature_put(game, 0, set_pool("APC")["Reef Shaman"])
    forest = _w1g7_creature_put(game, 1, catalog_by_name["Forest"])
    bears = _w1g7_creature_put(game, 1, catalog_by_name["Grizzly Bears"])

    assert _w1g7_activation_targets(game, 0, shaman) == ("land", ["Forest"])
    assert not game.queue_permanent_ability(
        0, "Reef Shaman", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_permanent_ability(
        0, "Reef Shaman", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert shaman.tapped is True
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g7_prompt(game, 0, "land_type_choice")["options"] == [
        "plains", "island", "swamp", "mountain", "forest",
    ]
    assert forest.basic_land_types == ("forest",)
    assert game.confirm_land_type(0, "swamp") is True
    assert forest.basic_land_types == ("swamp",)

    game.enforce_mana_costs = True
    assert game.tap_land_for_mana(1, "Forest", "G", permanent_id=forest.permanent_id)
    assert {s: n for s, n in p1.mana_pool.items() if n} == {"B": 1}

    game.resolve_cleanup_step(0)
    assert forest.basic_land_types == ("forest",)


# -- Kavu Glider (driven) ----------------------------------------------------


def test_kavu_gliders_two_abilities_cost_what_they_print_and_end_with_the_turn(
    set_pool, catalog_by_name
):
    """"{W}: This creature gets +0/+1 until end of turn." / "{U}: This creature
    gains flying until end of turn." With costs on: nothing happens for free,
    each ability spends its own colour, and both wear off at cleanup."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    game.enforce_mana_costs = True
    glider = _w1g7_creature_put(game, 0, set_pool("APC")["Kavu Glider"])
    plains = _w1g7_creature_put(game, 0, catalog_by_name["Plains"])
    island = _w1g7_creature_put(game, 0, catalog_by_name["Island"])

    refused = game.activate_permanent_ability(0, "Kavu Glider", ability_index=0)
    assert not refused.supported
    assert (glider.effective_power, glider.effective_toughness) == (2, 1)

    game.tap_land_for_mana(0, "Plains", "W", permanent_id=plains.permanent_id)
    assert game.activate_permanent_ability(0, "Kavu Glider", ability_index=0).supported
    assert (glider.effective_power, glider.effective_toughness) == (2, 2)
    assert not game._has_keyword(glider, "flying")

    game.tap_land_for_mana(0, "Island", "U", permanent_id=island.permanent_id)
    assert game.activate_permanent_ability(0, "Kavu Glider", ability_index=1).supported
    assert game._has_keyword(glider, "flying")
    assert not any(p0.mana_pool.values())

    game.resolve_cleanup_step(0)
    assert (glider.effective_power, glider.effective_toughness) == (2, 1)
    assert not game._has_keyword(glider, "flying")


# -- Urborg Elf / Llanowar Dead (driven) -------------------------------------


@_w1g7_pytest.mark.parametrize("colour", ["B", "G", "U"])
def test_urborg_elf_taps_for_each_of_its_three_colors(set_pool, colour):
    """"{T}: Add {B}, {G}, or {U}." One mana of the colour asked for, and the
    Elf is tapped — a second activation is refused."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    game.enforce_mana_costs = True
    elf = _w1g7_creature_put(game, 0, set_pool("APC")["Urborg Elf"])

    assert game.activate_permanent_ability(0, "Urborg Elf", mana_color=colour).supported

    assert {s: n for s, n in p0.mana_pool.items() if n} == {colour: 1}
    assert elf.tapped is True
    assert not game.activate_permanent_ability(0, "Urborg Elf", mana_color=colour).supported
    assert sum(p0.mana_pool.values()) == 1


def test_urborg_elf_never_makes_a_color_it_does_not_print(set_pool):
    """Asked for red, it makes one of its own three: the request is not a way
    to a fourth colour."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    _w1g7_creature_put(game, 0, set_pool("APC")["Urborg Elf"])

    assert game.activate_permanent_ability(0, "Urborg Elf", mana_color="R").supported

    made = {s for s, n in p0.mana_pool.items() if n}
    assert len(made) == 1 and made <= {"B", "G", "U"}
    assert sum(p0.mana_pool.values()) == 1


def test_llanowar_dead_taps_for_black_and_not_while_summoning_sick(set_pool):
    """"{T}: Add {B}." A creature's {T} ability waits for CR 302.6: the copy
    that came in this turn cannot be tapped for mana."""
    game, p0, p1 = _w1g7_creature_duel(interactive=())
    game.enforce_mana_costs = True
    dead = _w1g7_creature_put(game, 0, set_pool("APC")["Llanowar Dead"])

    assert game.activate_permanent_ability(0, "Llanowar Dead", mana_color="G").supported
    assert {s: n for s, n in p0.mana_pool.items() if n} == {"B": 1}
    assert dead.tapped is True

    fresh = _w1g7_creature_put(game, 0, set_pool("APC")["Llanowar Dead"])
    fresh.metadata["summoning_sickness_turn"] = game.turn
    refused = game.activate_permanent_ability(
        0, "Llanowar Dead", permanent_index=len(p0.battlefield) - 1
    )
    assert not refused.supported and "summoning sickness" in refused.details
    assert fresh.tapped is False

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.helpers import _mk_card as _w1g8_mk_card
from tests.helpers import resolve_stack as _w1g8_resolve_stack

# Where the cards these tests borrow from other sets were first printed. Every
# other name is Apocalypse's.
_W1G8_HOMES = {
    "Forest": "LEA", "Island": "LEA", "Swamp": "LEA", "Terror": "LEA",
    "Grizzly Bears": "LEA", "Hill Giant": "LEA", "Wall of Wood": "LEA",
    "Sol Ring": "LEA", "Megrim": "STH",
}
_W1G8_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}


def _w1g8_card(set_pool, name: str):
    return set_pool(_W1G8_HOMES.get(name, "APC"))[name]


def _w1g8_table(set_pool, *, seats: int = 2, hand=(), opp_hand=(), library=(),
                interactive=()) -> _w1g8_Game:
    """*seats* players with costs enforced and mana to pay them. Seat 0 holds
    *hand*, seat 1 holds *opp_hand*."""
    forest = _w1g8_card(set_pool, "Forest")
    players = [
        _w1g8_PlayerState(name=f"P{seat}", library=[forest] * 12)
        for seat in range(seats)
    ]
    players[0].hand = [_w1g8_card(set_pool, n) for n in hand]
    players[1].hand = [_w1g8_card(set_pool, n) for n in opp_hand]
    if library:
        players[0].library = [_w1g8_card(set_pool, n) for n in library]
    game = _w1g8_Game(players=players)
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    for player in players:
        player.mana_pool.update(_W1G8_RICH)
    return game


def _w1g8_put(game, set_pool, seat: int, name: str) -> _w1g8_Permanent:
    perm = _w1g8_Permanent(card=_w1g8_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g8_names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _w1g8_lives(game) -> list[int]:
    return [player.life for player in game.players]


def _w1g8_settle(game) -> None:
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g8_resolve_stack(game)


def _w1g8_attack(game, attacker, *, blocker=None, defender: int = 1) -> None:
    """Step the real combat phase: *attacker* (seat 0's) attacks seat
    *defender*, *blocker* blocks it or nobody does, and combat damage is
    dealt. Stops there — a trigger the damage raised is on the stack."""
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.current_step == "declare_attackers", game.current_step
    assert game.declare_attackers(
        0, [game.battlefield_index_of(attacker)], defending_player_index=defender,
    )[0]
    game.advance_combat_phase()
    blocks = {} if blocker is None else {game.battlefield_index_of(blocker): 0}
    assert game.declare_blockers(defender, blocks)[0]
    game.advance_combat_phase()


def _w1g8_finish_combat(game) -> None:
    for _ in range(8):
        if game.current_turn_phase != "combat":
            return
        game.advance_combat_phase()
    raise AssertionError(f"combat never ended: {game.current_step}")


# --- Haunted Angel ----------------------------------------------------------------


def test_w1g8_haunted_angel_dying_is_exiled_and_gives_the_opponent_an_angel(set_pool):
    """"When this creature dies, exile it and each other player creates a 3/3
    black Angel creature token with flying." The card leaves the graveyard for
    exile, and the token is the *other* player's."""
    game = _w1g8_table(set_pool, hand=["Terror"])
    angel = _w1g8_put(game, set_pool, 0, "Haunted Angel")

    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[angel.permanent_id]).supported
    game.resolve_top_of_stack()
    assert _w1g8_names(game.players[0].graveyard) == ["Haunted Angel", "Terror"]
    assert _w1g8_names(game.stack) == ["Haunted Angel"], "the trigger is a stack object"
    _w1g8_settle(game)

    assert _w1g8_names(game.players[0].exile) == ["Haunted Angel"]
    assert _w1g8_names(game.players[0].graveyard) == ["Terror"]
    assert list(game.controlled_by(0)) == []
    (token,) = game.controlled_by(1)
    assert (token.effective_power, token.effective_toughness) == (3, 3)
    assert token.effective_colors == {"B"}
    assert token.has_type("creature") and "angel" in token.effective_card.type_line.lower()
    assert game._has_keyword(token, "flying")
    assert token.metadata.get("is_token")


def test_w1g8_haunted_angel_gives_every_other_player_a_token_and_its_controller_none(
    set_pool,
):
    """"Each **other** player" at three seats: both opponents of the Angel's
    controller get one, whoever killed it — here the controller did."""
    game = _w1g8_table(set_pool, seats=3, hand=["Terror"])
    angel = _w1g8_put(game, set_pool, 0, "Haunted Angel")

    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[angel.permanent_id]).supported
    _w1g8_settle(game)

    assert [_w1g8_names(game.controlled_by(seat)) for seat in range(3)] == [
        [], ["Angel Token"], ["Angel Token"],
    ]


def test_w1g8_haunted_angel_gone_from_the_graveyard_still_makes_the_tokens(set_pool):
    """CR 608.2: as much as possible. With the card already moved out of the
    graveyard in response, "exile it" finds nothing and the rest of the
    sentence happens anyway."""
    game = _w1g8_table(set_pool, hand=["Terror"])
    angel = _w1g8_put(game, set_pool, 0, "Haunted Angel")
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[angel.permanent_id]).supported
    game.resolve_top_of_stack()
    card = game.players[0].graveyard.pop(0)
    game.put_card_into_library(game.players[0], card, "top")
    _w1g8_settle(game)

    assert game.players[0].exile == []
    assert game.players[0].library[0].name == "Haunted Angel"
    assert _w1g8_names(game.controlled_by(1)) == ["Angel Token"]


def test_w1g8_each_other_player_is_read_where_each_opponent_is(set_pool):
    """The recipient in front of "creates" is a row beside "each opponent", so
    the two spellings compile to one program — and a recipient the table does
    not hold still refuses rather than making the token for the controller."""
    def program(text):
        return _w1g8_compile(_w1g8_mk_card(
            name="Probe", mana_cost="{1}", type_line="Sorcery", oracle_text=text,
        ))

    other = program("Each other player creates a 3/3 black Angel creature token with flying.")
    opponent = program("Each opponent creates a 3/3 black Angel creature token with flying.")
    assert other.supported and other.instructions == opponent.instructions
    assert not program(
        "Each other creature creates a 3/3 black Angel creature token with flying."
    ).supported


# --- Fungal Shambler (driven) -------------------------------------------------------


def test_w1g8_fungal_shambler_draws_for_its_controller_and_the_opponent_picks_a_discard(
    set_pool,
):
    """"Whenever this creature deals damage to an opponent, you draw a card and
    that opponent discards a card." The draw is mine; the discard is theirs to
    choose (CR 701.9b), so the trigger waits on them."""
    game = _w1g8_table(
        set_pool, opp_hand=["Forest", "Island"], library=["Swamp"] * 5,
        interactive=(0, 1),
    )
    shambler = _w1g8_put(game, set_pool, 0, "Fungal Shambler")

    _w1g8_attack(game, shambler)
    assert game.players[1].life == 14
    assert _w1g8_names(game.stack) == ["Fungal Shambler"]
    game.resolve_top_of_stack()
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert game.confirm_discard(1, [1])
    _w1g8_settle(game)
    _w1g8_finish_combat(game)

    assert _w1g8_names(game.players[1].hand) == ["Forest"]
    assert _w1g8_names(game.players[1].graveyard) == ["Island"]
    assert _w1g8_names(game.players[0].hand) == ["Swamp"], "drew exactly once"


def test_w1g8_fungal_shambler_needs_damage_to_reach_the_opponent(set_pool):
    """Trample over a 2/2 still hits the player for 4 and triggers; a blocker
    that soaks all six does not — damage to a creature is not damage to an
    opponent."""
    game = _w1g8_table(set_pool, opp_hand=["Forest"], library=["Swamp"] * 5)
    shambler = _w1g8_put(game, set_pool, 0, "Fungal Shambler")
    bears = _w1g8_put(game, set_pool, 1, "Grizzly Bears")
    _w1g8_attack(game, shambler, blocker=bears)
    _w1g8_settle(game)
    _w1g8_finish_combat(game)
    assert game.players[1].life == 16
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]
    assert game.players[1].hand == []

    game = _w1g8_table(set_pool, opp_hand=["Forest"], library=["Swamp"] * 5)
    shambler = _w1g8_put(game, set_pool, 0, "Fungal Shambler")
    walls = [_w1g8_put(game, set_pool, 1, "Wall of Wood") for _ in range(2)]
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0, 1: 0})[0]
    game.advance_combat_phase()
    if not game.combat_damage_resolved:
        assert game.resolve_combat_damage(0, attacker_damage={0: {0: 3, 1: 3}})[0]
    _w1g8_settle(game)
    _w1g8_finish_combat(game)
    assert game.players[1].life == 20, game.log
    assert game.players[0].hand == [] and _w1g8_names(game.players[1].hand) == ["Forest"]
    assert all(wall.damage_marked == 0 or not game.is_on_battlefield(wall) for wall in walls)


# --- Putrid Warrior (driven) ---------------------------------------------------------


@_w1g8_pytest.mark.parametrize("seats, mode, expected", [
    (2, 0, [19, 17]),
    (2, 1, [21, 19]),
    (3, 0, [19, 17, 19]),
    (3, 1, [21, 19, 21]),
])
def test_w1g8_putrid_warrior_changes_every_players_life_by_one(
    set_pool, seats, mode, expected,
):
    """"Whenever this creature deals damage, choose one — • Each player loses
    1 life. • Each player gains 1 life." **Each** player, both ways. The gain
    used to reach one seat: the quantifier fell through to a single target, so
    the prompt read "…targeting P0" and the opponent's life did not move."""
    game = _w1g8_table(set_pool, seats=seats, interactive=(0,))
    warrior = _w1g8_put(game, set_pool, 0, "Putrid Warrior")

    _w1g8_attack(game, warrior)
    (choice,) = game.pending_choices
    assert choice.kind == "mode_choice"
    assert choice.data["labels"] == [
        "Each player loses 1 life", "Each player gains 1 life",
    ]
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=mode)
    _w1g8_settle(game)
    _w1g8_finish_combat(game)

    assert _w1g8_lives(game) == expected, game.log
    assert not any("targeting" in line for line in game.log if "chose" in line)


def test_w1g8_putrid_warrior_triggers_on_damage_to_a_creature_too(set_pool):
    """"Deals damage", not "to a player": blocked by a Wall it deals its 2 to
    the Wall and the ability still triggers."""
    game = _w1g8_table(set_pool)
    warrior = _w1g8_put(game, set_pool, 0, "Putrid Warrior")
    wall = _w1g8_put(game, set_pool, 1, "Wall of Wood")

    _w1g8_attack(game, warrior, blocker=wall)
    _w1g8_settle(game)
    _w1g8_finish_combat(game)

    assert wall.damage_marked == 2 and game.is_on_battlefield(wall)
    assert _w1g8_lives(game) == [19, 19], game.log


# --- Quagmire Druid (driven) ----------------------------------------------------------


def test_w1g8_quagmire_druid_trades_a_creature_for_an_enchantment(set_pool):
    """"{G}, {T}, Sacrifice a creature: Destroy target enchantment." The
    picker offers enchantments and nothing else; the cost offers the Druid's
    own creatures, the Druid among them."""
    game = _w1g8_table(set_pool)
    druid = _w1g8_put(game, set_pool, 0, "Quagmire Druid")
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    megrim = _w1g8_put(game, set_pool, 1, "Megrim")
    _w1g8_put(game, set_pool, 1, "Sol Ring")

    spec = game.activation_target_spec(0, game.battlefield_index_of(druid))
    assert [t["name"] for t in spec["valid_targets"]] == ["Megrim"]
    assert {t["name"] for t in spec["cost_spec"]["valid_targets"]} == {
        "Quagmire Druid", "Grizzly Bears",
    }
    assert game.activate_permanent_ability(
        0, "Quagmire Druid", target_permanent_ids=[megrim.permanent_id],
        cost_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[1].graveyard) == ["Megrim"]
    assert _w1g8_names(game.players[0].graveyard) == ["Grizzly Bears"]
    assert druid.tapped and game.is_on_battlefield(druid)
    assert _w1g8_names(game.controlled_by(1)) == ["Sol Ring"]


def test_w1g8_quagmire_druid_refuses_a_target_that_is_not_an_enchantment(set_pool):
    """An artifact named as the target, and no target at all: both refused
    before any cost is paid (CR 602.2b) — the creature is still there, the
    Druid is untapped and the mana is unspent."""
    game = _w1g8_table(set_pool)
    druid = _w1g8_put(game, set_pool, 0, "Quagmire Druid")
    bears = _w1g8_put(game, set_pool, 0, "Grizzly Bears")
    ring = _w1g8_put(game, set_pool, 1, "Sol Ring")
    before = dict(game.players[0].mana_pool)

    for target in ([ring.permanent_id], None):
        result = game.activate_permanent_ability(
            0, "Quagmire Druid", target_permanent_ids=target,
            cost_permanent_ids=[bears.permanent_id],
        )
        assert not result.supported, result
    assert game.is_on_battlefield(bears) and game.is_on_battlefield(ring)
    assert not druid.tapped and dict(game.players[0].mana_pool) == before


def test_w1g8_quagmire_druid_may_be_the_creature_it_sacrifices(set_pool):
    game = _w1g8_table(set_pool)
    druid = _w1g8_put(game, set_pool, 0, "Quagmire Druid")
    megrim = _w1g8_put(game, set_pool, 1, "Megrim")

    assert game.activate_permanent_ability(
        0, "Quagmire Druid", target_permanent_ids=[megrim.permanent_id],
        cost_permanent_ids=[druid.permanent_id],
    ).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[0].graveyard) == ["Quagmire Druid"]
    assert _w1g8_names(game.players[1].graveyard) == ["Megrim"]


# --- Savage Gorilla (driven) -----------------------------------------------------------


def test_w1g8_savage_gorilla_shrinks_a_creature_and_draws(set_pool):
    """"{U}{B}, {T}, Sacrifice this creature: Target creature gets -3/-3 until
    end of turn. Draw a card." A Hill Giant dies to it, and the Gorilla is in
    the graveyard as the cost."""
    game = _w1g8_table(set_pool, library=["Swamp"] * 5)
    _w1g8_put(game, set_pool, 0, "Savage Gorilla")
    giant = _w1g8_put(game, set_pool, 1, "Hill Giant")

    assert game.activate_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8_settle(game)

    assert _w1g8_names(game.players[0].graveyard) == ["Savage Gorilla"]
    assert _w1g8_names(game.players[1].graveyard) == ["Hill Giant"]
    assert _w1g8_names(game.players[0].hand) == ["Swamp"]


def test_w1g8_savage_gorilla_only_weakens_a_bigger_creature_until_end_of_turn(set_pool):
    game = _w1g8_table(set_pool, library=["Swamp"] * 5)
    _w1g8_put(game, set_pool, 0, "Savage Gorilla")
    shambler = _w1g8_put(game, set_pool, 1, "Fungal Shambler")

    assert game.activate_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[shambler.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert (shambler.effective_power, shambler.effective_toughness) == (3, 1)

    game.resolve_cleanup_step(0)
    assert (shambler.effective_power, shambler.effective_toughness) == (6, 4)


# --- Mournful Zombie (driven) -----------------------------------------------------------


def test_w1g8_mournful_zombie_gives_the_named_player_one_life(set_pool):
    """"{W}, {T}: Target player gains 1 life." Either player may be named;
    tapped, it cannot be activated again, and it wants white mana."""
    for target, expected in ((0, [21, 20]), (1, [20, 21])):
        game = _w1g8_table(set_pool)
        zombie = _w1g8_put(game, set_pool, 0, "Mournful Zombie")
        spec = game.activation_target_spec(0, game.battlefield_index_of(zombie))
        assert [t["seat"] for t in spec["valid_targets"]] == [0, 1]
        assert game.activate_permanent_ability(
            0, "Mournful Zombie", target_player_index=target,
        ).supported
        _w1g8_settle(game)
        assert _w1g8_lives(game) == expected
        assert not game.activate_permanent_ability(
            0, "Mournful Zombie", target_player_index=target,
        ).supported, "it is tapped"
        assert _w1g8_lives(game) == expected

    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool, 0, "Mournful Zombie")
    game.players[0].mana_pool.update({"W": 0})
    assert not game.activate_permanent_ability(
        0, "Mournful Zombie", target_player_index=0,
    ).supported
    assert _w1g8_lives(game) == [20, 20]

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

import pytest as _w1g9_pytest

from engine import Game as _w1g9_Game
from engine import PlayerState as _w1g9_PlayerState
from engine.models import CardDefinition as _w1g9_CardDefinition
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_vanilla(name, power, toughness, *, subtype="Test", colors=()):
    """A creature carrying only its numbers, its type and its colour.

    Invented rather than pulled from a pool: every test below is about a
    relation between two creatures (who is blocking whom, which colour blocked),
    and a pool creature would bring its own printed line along with the answer.
    """
    type_line = f"Creature - {subtype}"
    return _w1g9_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=tuple(colors), color_identity=tuple(colors), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g9_ready(card):
    """*card* as a permanent that may attack and tap this turn."""
    permanent = _w1g9_Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g9_main(mine, theirs, *, libraries=((), ())):
    """A two-seat game in the first main phase of seat 0's turn, costs off."""
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name="P1", battlefield=list(mine), library=list(libraries[0])
        ),
        _w1g9_PlayerState(
            name="P2", battlefield=list(theirs), library=list(libraries[1])
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def _w1g9_to_attackers(game):
    """Advance *game* from a main phase to its declare-attackers step."""
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    return game


def _w1g9_slot(game, seat, permanent):
    """Where *permanent* sits on *seat*'s battlefield, for the two entry
    points (attackers, blockers) that still take a slot."""
    return next(
        slot for slot, found in enumerate(game.controlled_by(seat))
        if found is permanent
    )


# --- Cromat -----------------------------------------------------------------


def _w1g9_cromat_blocked(set_pool):
    """Cromat attacking, blocked by the first of two identical 5/5s.

    Two on the far side on purpose, and identical: one blocked and one did not,
    and nothing about either creature tells them apart — so a dropped relation
    shows up as the bystander being reachable.
    """
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    ally = _w1g9_ready(_w1g9_vanilla("Ally", 1, 1))
    blocker = _w1g9_ready(_w1g9_vanilla("Blocker", 5, 5))
    bystander = _w1g9_ready(_w1g9_vanilla("Bystander", 5, 5))
    filler = _w1g9_vanilla("Filler", 1, 1)
    game = _w1g9_to_attackers(_w1g9_main(
        [cromat, ally], [blocker, bystander], libraries=([filler, filler], [filler]),
    ))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    _w1g9_resolve_stack(game)
    return game, cromat, ally, blocker, bystander


def test_w1g9_cromat_compiles_all_five_abilities(set_pool):
    program = _w1g9_compile(set_pool("APC")["Cromat"])

    assert program.supported
    assert len(program.activated_abilities) == 5
    destroy = program.activated_abilities[0].instruction
    assert destroy.payload["targets"]["filter"]["in_combat_with_source"] is True


def test_w1g9_cromat_has_nothing_to_destroy_outside_a_block(set_pool):
    """"Destroy target creature **blocking or blocked by Cromat**." With no
    block there is no such creature, so the ability cannot be activated at all
    (CR 602.2b through CR 601.2c) — named target or not."""
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    foe = _w1g9_ready(_w1g9_vanilla("Foe", 5, 5))
    game = _w1g9_main([cromat], [foe])

    assert game.activation_target_spec(0, 0, 0)["valid_targets"] == []
    named = game.activate_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[foe.permanent_id],
    )
    bare = game.activate_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0
    )

    assert not named.supported and not bare.supported
    assert game.is_on_battlefield(foe) and not game.stack


def test_w1g9_cromat_is_offered_only_the_creature_blocking_it(set_pool):
    """The picker's list and the announcement gate are one list: the blocker
    and nothing else — not the identical creature beside it, not Cromat's own
    side, not Cromat."""
    game, cromat, ally, blocker, bystander = _w1g9_cromat_blocked(set_pool)

    offered = game.activation_target_spec(0, 0, 0)["valid_targets"]
    assert [(t["seat"], t["name"]) for t in offered] == [(1, "Blocker")]
    for illegal in (bystander, ally, cromat):
        refused = game.activate_permanent_ability(
            0, "Cromat", permanent_index=0, ability_index=0,
            target_permanent_ids=[illegal.permanent_id],
        )
        assert not refused.supported, illegal.card.name
    assert not game.stack

    result = game.activate_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocker.permanent_id],
    )

    assert result.supported, result.details
    assert not game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander)
    assert [card.name for card in game.players[1].graveyard] == ["Blocker"]
    assert "Cromat destroyed Blocker" in game.log


def test_w1g9_cromat_named_nothing_never_reaches_a_bystander(set_pool):
    """The headless convention — an activation that names no target resolves
    on the handler's pick — held to the printed phrase: the pick is the
    creature blocking Cromat, never the identical one standing beside it."""
    game, cromat, ally, blocker, bystander = _w1g9_cromat_blocked(set_pool)

    result = game.activate_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0
    )

    assert result.supported, result.details
    assert not game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander) and game.is_on_battlefield(ally)


def test_w1g9_cromat_blocking_destroys_the_attacker_it_blocked(set_pool):
    """The relation read from the other end: Cromat as the blocker, and the
    one legal target is the attacker it is blocking — not the attacker that got
    through beside it."""
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    blocked = _w1g9_ready(_w1g9_vanilla("Blocked", 5, 5))
    unblocked = _w1g9_ready(_w1g9_vanilla("Unblocked", 5, 5))
    game = _w1g9_to_attackers(_w1g9_main([blocked, unblocked], [cromat]))
    assert game.declare_attackers(0, [0, 1])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    offered = game.activation_target_spec(1, 0, 0)["valid_targets"]
    assert [(t["seat"], t["name"]) for t in offered] == [(0, "Blocked")]
    assert not game.activate_permanent_ability(
        1, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[unblocked.permanent_id],
    ).supported
    assert game.activate_permanent_ability(
        1, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocked.permanent_id],
    ).supported

    assert not game.is_on_battlefield(blocked)
    assert game.is_on_battlefield(unblocked)


def test_w1g9_cromat_a_target_that_left_the_fight_is_not_destroyed(set_pool):
    """CR 608.2b: the target is asked again as the ability resolves. A blocker
    removed from combat in response is no longer "blocking Cromat", and the
    destroy does not go looking for somebody else."""
    from engine.handlers.combat import _take_permanent_out_of_combat

    game, cromat, ally, blocker, bystander = _w1g9_cromat_blocked(set_pool)
    queued = game.queue_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocker.permanent_id],
    )
    assert queued.supported and len(game.stack) == 1

    _take_permanent_out_of_combat(game, blocker, frees_blocked_attackers=False)
    _w1g9_resolve_stack(game)

    assert game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander)
    assert not any("destroyed" in line for line in game.log)


def test_w1g9_cromat_tucked_in_response_still_destroys_its_blocker(set_pool):
    """Two of the five abilities on one stack: the destroy, then "{G}{U}: Put
    Cromat on top of its owner's library" in response. Cromat is gone when the
    destroy resolves, and CR 608.2h reads the block it was in as last known
    information — the creature that blocked it is still the creature named."""
    game, cromat, ally, blocker, bystander = _w1g9_cromat_blocked(set_pool)
    assert game.queue_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=0,
        target_permanent_ids=[blocker.permanent_id],
    ).supported
    assert game.queue_permanent_ability(
        0, "Cromat", permanent_index=0, ability_index=4
    ).supported
    _w1g9_resolve_stack(game)

    assert not game.is_on_battlefield(cromat)
    assert game.players[0].library[0].name == "Cromat"
    assert len(game.players[0].library) == 3
    assert not game.is_on_battlefield(blocker)
    assert game.is_on_battlefield(bystander)


def test_w1g9_cromat_flies_grows_and_regenerates(set_pool):
    """The three abilities that act on Cromat itself, in one combat: flying and
    +1/+1 until end of turn, and a regeneration shield that is spent when a
    7/7 deals it lethal damage — Cromat is tapped, out of combat, and alive."""
    cromat = _w1g9_ready(set_pool("APC")["Cromat"])
    wall = _w1g9_ready(_w1g9_vanilla("Big Wall", 7, 7))
    game = _w1g9_to_attackers(_w1g9_main([cromat], [wall]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]

    for ability in (1, 3, 2):
        assert game.activate_permanent_ability(
            0, "Cromat", permanent_index=0, ability_index=ability
        ).supported
    assert game._has_keyword(cromat, "flying")
    assert (cromat.effective_power, cromat.effective_toughness) == (6, 6)
    assert cromat.regeneration_shield == 1

    game.advance_combat_phase()   # combat damage

    assert game.is_on_battlefield(cromat)
    assert "Cromat regenerated" in game.log
    assert cromat.tapped and cromat.regeneration_shield == 0
    assert cromat.damage_marked == 0

    game.resolve_cleanup_step(0)
    assert not game._has_keyword(cromat, "flying")
    assert (cromat.effective_power, cromat.effective_toughness) == (5, 5)


# --- Zombie Boa ---------------------------------------------------------------


def _w1g9_boa_game(set_pool, *, interactive=False):
    boa = _w1g9_ready(set_pool("APC")["Zombie Boa"])
    green = _w1g9_ready(_w1g9_vanilla("Green One", 1, 1, colors=("G",)))
    red = _w1g9_ready(_w1g9_vanilla("Red One", 1, 1, colors=("R",)))
    game = _w1g9_main([boa], [green, red])
    if interactive:
        game.interactive_seats = {0}
    return game, boa, green, red


def _w1g9_boa_attacks_into(game, blockers):
    """The Boa attacks and each permanent in *blockers* blocks it."""
    _w1g9_to_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {_w1g9_slot(game, 1, blocker): 0 for blocker in blockers}
    )[0]
    _w1g9_resolve_stack(game)
    game._settle()


def test_w1g9_zombie_boa_destroys_only_a_blocker_of_the_chosen_color(set_pool):
    """"Choose a color. Whenever this creature becomes blocked by a creature
    **of that color** this turn, destroy that creature."

    A human seat is asked for the colour as the ability resolves (CR 608.2d),
    and the answer is what the delayed ability watches for: blocked by a green
    creature and a red one at once, with red chosen, the red one dies and the
    green one is left blocking.
    """
    game, boa, green, red = _w1g9_boa_game(set_pool, interactive=True)

    assert game.queue_permanent_ability(0, "Zombie Boa", permanent_index=0).supported
    game.resolve_top_of_stack()
    assert [choice.kind for choice in game.pending_choices] == ["color_choice"]
    assert not game.delayed_triggers, "nothing is armed before the colour is chosen"
    assert game.confirm_color_choice(0, "R")
    if game.stack:
        game.resolve_top_of_stack()

    (armed,) = game.delayed_triggers
    assert armed.event == "source_becomes_blocked_by"
    assert armed.agent_filter == {"type_filter": "creature", "color_filter": "R"}

    _w1g9_boa_attacks_into(game, [green, red])

    assert not game.is_on_battlefield(red)
    assert game.is_on_battlefield(green)
    assert "Zombie Boa destroyed Red One" in game.log


def test_w1g9_zombie_boa_leaves_another_colors_blocker_alone(set_pool):
    """The narrowing is the whole card: with green chosen, a red blocker
    triggers nothing at all — no ability goes on the stack."""
    game, boa, green, red = _w1g9_boa_game(set_pool, interactive=True)
    assert game.queue_permanent_ability(0, "Zombie Boa", permanent_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_color_choice(0, "G")
    if game.stack:
        game.resolve_top_of_stack()

    _w1g9_to_attackers(game)
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {_w1g9_slot(game, 1, red): 0})[0]

    assert not game.stack
    assert game.is_on_battlefield(red) and game.is_on_battlefield(green)


def test_w1g9_zombie_boa_a_headless_seat_chooses_and_the_trigger_fires(set_pool):
    """No prompt for a seat nobody is sitting in: the default colour is the one
    the opponents hold most of, and the ability is armed in the same
    resolution. One green creature and one red one is a tie the default breaks
    for green, which is the creature that then dies blocking."""
    game, boa, green, red = _w1g9_boa_game(set_pool)

    result = game.activate_permanent_ability(0, "Zombie Boa", permanent_index=0)
    assert result.supported, result.details
    (armed,) = game.delayed_triggers
    chosen = armed.agent_filter["color_filter"]
    victim, survivor = (green, red) if chosen == "G" else (red, green)

    _w1g9_boa_attacks_into(game, [victim])

    assert not game.is_on_battlefield(victim)
    assert game.is_on_battlefield(survivor)


def test_w1g9_zombie_boa_is_activated_only_as_a_sorcery(set_pool):
    """"Activate only as a sorcery." Refused in combat with nothing armed; the
    same seat in its main phase a moment earlier is allowed."""
    game, boa, green, red = _w1g9_boa_game(set_pool)
    _w1g9_to_attackers(game)

    refused = game.activate_permanent_ability(0, "Zombie Boa", permanent_index=0)

    assert not refused.supported
    assert "sorcery" in refused.details
    assert not game.delayed_triggers and not game.stack


def test_w1g9_zombie_boa_the_watch_ends_with_the_turn(set_pool):
    """"…this turn" is CR 603.7b's stated duration: the cleanup step takes the
    ability off the waiting list, so a block next turn destroys nothing."""
    game, boa, green, red = _w1g9_boa_game(set_pool)
    assert game.activate_permanent_ability(0, "Zombie Boa", permanent_index=0).supported
    assert len(game.delayed_triggers) == 1

    game.resolve_cleanup_step(0)

    assert not game.delayed_triggers


def test_w1g9_of_that_color_refuses_without_a_step_that_chose_one():
    """The refusal half of the production. "Of that color" on a delay's agent
    names a colour an earlier sentence of the same effect chose; with no such
    sentence the words name nothing, and the line must refuse rather than arm
    an ability that can never match."""
    from engine.grammar import compile_line

    bare = compile_line(
        "{1}{B}: Whenever this creature becomes blocked by a creature of that "
        "color this turn, destroy that creature.",
        card_name="Test",
    )
    assert bare.parsed and not bare.lowered
    assert "chose a color" in bare.lowering_error

    printed = compile_line(
        "{1}{B}: Whenever this creature becomes blocked by a black creature "
        "this turn, destroy that creature.",
        card_name="Test",
    )
    assert printed.lowered
    (created,) = printed.instructions
    assert created.payload["event"] == "source_becomes_blocked_by"
    assert created.payload["agent_filter"] == {
        "type_filter": "creature", "color_filter": "B",
    }

    windowless = compile_line(
        "{1}{B}: Whenever this creature becomes blocked by a black creature, "
        "destroy that creature.",
        card_name="Test",
    )
    assert not windowless.lowered, "an ability with no window is not a delay"


# --- Drive list: Kavu Mauler, Flowstone Charger, Spectral Lynx, the pumps ------


def test_w1g9_kavu_mauler_counts_the_other_attacking_kavu(set_pool):
    """"…it gets +1/+1 until end of turn for each **other attacking Kavu**."
    Two Kavu attack beside it, a third stays home and a Bear attacks too: +2/+2
    and no more. Trample then carries the excess over a chump blocker."""
    mauler = _w1g9_ready(set_pool("APC")["Kavu Mauler"])
    others = [
        _w1g9_ready(_w1g9_vanilla("Kavu A", 2, 2, subtype="Kavu")),
        _w1g9_ready(_w1g9_vanilla("Kavu B", 2, 2, subtype="Kavu")),
        _w1g9_ready(_w1g9_vanilla("Kavu Home", 2, 2, subtype="Kavu")),
        _w1g9_ready(_w1g9_vanilla("Bear", 2, 2, subtype="Bear")),
    ]
    chump = _w1g9_ready(_w1g9_vanilla("Chump", 1, 1))
    game = _w1g9_to_attackers(_w1g9_main([mauler, *others], [chump]))

    assert game.declare_attackers(0, [0, 1, 2, 4])[0]
    _w1g9_resolve_stack(game)
    assert (mauler.effective_power, mauler.effective_toughness) == (6, 6)

    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    # 5 trampled over the 1/1, plus 2 + 2 + 2 from the unblocked three.
    assert game.players[1].life == 9
    assert not game.is_on_battlefield(chump)
    game.resolve_cleanup_step(0)
    assert (mauler.effective_power, mauler.effective_toughness) == (4, 4)


def test_w1g9_flowstone_charger_trades_toughness_for_power(set_pool):
    """"Whenever this creature attacks, it gets +3/-3 until end of turn." A
    2/5 becomes a 5/2 for the turn — and one already carrying 2 damage dies of
    it as the trigger resolves (CR 704.5g)."""
    charger = _w1g9_ready(set_pool("APC")["Flowstone Charger"])
    game = _w1g9_to_attackers(_w1g9_main([charger], []))
    assert game.declare_attackers(0, [0])[0]
    _w1g9_resolve_stack(game)

    assert (charger.effective_power, charger.effective_toughness) == (5, 2)
    game.resolve_cleanup_step(0)
    assert (charger.effective_power, charger.effective_toughness) == (2, 5)

    hurt = _w1g9_ready(set_pool("APC")["Flowstone Charger"])
    hurt.damage_marked = 2
    game = _w1g9_to_attackers(_w1g9_main([hurt], []))
    assert game.declare_attackers(0, [0])[0]
    _w1g9_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(hurt)
    assert [card.name for card in game.players[0].graveyard] == ["Flowstone Charger"]


def test_w1g9_spectral_lynx_regenerates_and_is_protected_from_green(set_pool):
    """Both printed lines in play. "{B}: Regenerate" — a shield spent on lethal
    combat damage from a red 5/5, leaving the Lynx tapped and alive. And
    protection from green (CR 702.16): a green attacker it blocks deals it no
    damage, and a green creature may not block it."""
    lynx = _w1g9_ready(set_pool("APC")["Spectral Lynx"])
    red = _w1g9_ready(_w1g9_vanilla("Red Foe", 5, 5, colors=("R",)))
    game = _w1g9_to_attackers(_w1g9_main([red], [lynx]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.activate_permanent_ability(1, "Spectral Lynx", permanent_index=0).supported
    assert lynx.regeneration_shield == 1
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert game.is_on_battlefield(lynx)
    assert lynx.tapped and lynx.regeneration_shield == 0
    assert "Spectral Lynx regenerated" in game.log

    lynx = _w1g9_ready(set_pool("APC")["Spectral Lynx"])
    green = _w1g9_ready(_w1g9_vanilla("Green Foe", 5, 5, colors=("G",)))
    game = _w1g9_to_attackers(_w1g9_main([green], [lynx]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert game.is_on_battlefield(lynx) and lynx.damage_marked == 0
    assert green.damage_marked == 2

    lynx = _w1g9_ready(set_pool("APC")["Spectral Lynx"])
    green = _w1g9_ready(_w1g9_vanilla("Green Foe", 5, 5, colors=("G",)))
    game = _w1g9_to_attackers(_w1g9_main([lynx], [green]))
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    blocked, why = game.declare_blockers(1, {0: 0})
    assert not blocked and "cannot block" in why


@_w1g9_pytest.mark.parametrize(
    "name, pool, grown",
    [
        ("Angelfire Crusader", {"R": 2, "W": 1}, (4, 3)),
        ("Ebony Treefolk", {"B": 2, "G": 2, "R": 1}, (5, 5)),
    ],
)
def test_w1g9_the_two_pumps_cost_what_they_print(set_pool, name, pool, grown):
    """"{R}: +1/+0" and "{B}{G}: +1/+1", with costs enforced: nothing with an
    empty pool, twice with mana for two, refused a third time on the mana that
    is the wrong colour, and gone at cleanup."""
    creature = _w1g9_ready(set_pool("APC")[name])
    printed = (creature.effective_power, creature.effective_toughness)
    game = _w1g9_main([creature], [])
    game.enforce_mana_costs = True

    assert not game.activate_permanent_ability(0, name, permanent_index=0).supported
    game.players[0].mana_pool.update(pool)
    assert game.activate_permanent_ability(0, name, permanent_index=0).supported
    assert game.activate_permanent_ability(0, name, permanent_index=0).supported
    third = game.activate_permanent_ability(0, name, permanent_index=0)

    assert not third.supported and "insufficient mana" in third.details
    assert (creature.effective_power, creature.effective_toughness) == grown
    game.resolve_cleanup_step(0)
    assert (creature.effective_power, creature.effective_toughness) == printed

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================

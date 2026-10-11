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

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

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
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand=(), mana=None, opp_hand=(), opp_mana=None):
    """A two-seat game with mana costs enforced. *hand* and *opp_hand* are
    Alpha cards — these creatures are put onto the battlefield, not cast."""
    lea = set_pool("LEA")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in hand],
        ),
        _W1G2PlayerState(
            "Opponent", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in opp_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    game.players[1].mana_pool.update(opp_mana or {})
    return game  # _w1g2_table (creatures)


def _w1g2_put(game, set_pool, seat, name, code="LEA", sick=False):
    """*name* onto *seat*'s battlefield; able to act this turn unless *sick*."""
    permanent = _W1G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put (creatures)


def _w1g2_activate(game, permanent, **announcement):
    """Activate an ability of the caster's *permanent* and settle the stack."""
    return game.activate_permanent_ability(
        0, permanent.card.name,
        permanent_index=list(game.controlled_by(0)).index(permanent),
        **announcement,
    )  # _w1g2_activate


# The Bloodfire creatures ----------------------------------------------------


def _w1g2_bloodfire_board(set_pool, name):
    """*name* under the caster with {R} to pay, beside the caster's own Bears;
    across the table a Craw Wurm (6/4), an Air Elemental (4/4 flier) and
    Savannah Lions (2/1)."""
    game = _w1g2_table(set_pool, mana={"R": 1})
    source = _w1g2_put(game, set_pool, 0, name, code="APC")
    board = {
        "bears": _w1g2_put(game, set_pool, 0, "Grizzly Bears"),
        "wurm": _w1g2_put(game, set_pool, 1, "Craw Wurm"),
        "air": _w1g2_put(game, set_pool, 1, "Air Elemental"),
        "lions": _w1g2_put(game, set_pool, 1, "Savannah Lions"),
    }
    return game, source, board  # _w1g2_bloodfire_board


def test_w1g2_bloodfire_colossus_deals_six_to_each_creature_and_each_player(set_pool):
    """"{R}, Sacrifice this creature: It deals 6 damage to each creature and
    each player." Everything on the table dies, and both players — its own
    controller included — are at 14."""
    game, colossus, board = _w1g2_bloodfire_board(set_pool, "Bloodfire Colossus")

    result = _w1g2_activate(game, colossus)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert [player.life for player in game.players] == [14, 14]
    assert not list(game.all_permanents())
    assert "Bloodfire Colossus" in [card.name for card in game.players[0].graveyard]


def test_w1g2_bloodfire_dwarf_spares_the_creature_with_flying(set_pool):
    """"…It deals 1 damage to each creature without flying." One point on the
    Bears and the Wurm, the 2/1 Lions die, the Air Elemental is untouched, and
    no player is damaged."""
    game, dwarf, board = _w1g2_bloodfire_board(set_pool, "Bloodfire Dwarf")

    result = _w1g2_activate(game, dwarf)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert (board["bears"].damage_marked, board["wurm"].damage_marked) == (1, 1)
    assert board["air"].damage_marked == 0
    assert not game.is_on_battlefield(board["lions"])
    assert [player.life for player in game.players] == [20, 20]


def test_w1g2_bloodfire_kavu_deals_two_to_each_creature(set_pool):
    """"…It deals 2 damage to each creature." Fliers included, both sides: the
    caster's own Bears and the Lions die, the Wurm and the Elemental carry 2."""
    game, kavu, board = _w1g2_bloodfire_board(set_pool, "Bloodfire Kavu")

    result = _w1g2_activate(game, kavu)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert (board["wurm"].damage_marked, board["air"].damage_marked) == (2, 2)
    assert not game.is_on_battlefield(board["bears"])
    assert not game.is_on_battlefield(board["lions"])
    assert [player.life for player in game.players] == [20, 20]


@_w1g2_pytest.mark.parametrize(
    "name", ["Bloodfire Colossus", "Bloodfire Dwarf", "Bloodfire Kavu"],
)
def test_w1g2_a_bloodfire_creature_is_not_sacrificed_to_a_refused_activation(
    set_pool, name,
):
    """The sacrifice is a cost (CR 602.2b), paid with the {R} or not at all:
    with no mana the creature stays and nothing is damaged. With it, the
    ability works the turn the creature arrived — the cost has no {T}."""
    game, source, board = _w1g2_bloodfire_board(set_pool, name)
    game.players[0].mana_pool["R"] = 0

    assert not _w1g2_activate(game, source).supported
    assert game.is_on_battlefield(source)
    assert board["lions"].damage_marked == 0

    game = _w1g2_table(set_pool, mana={"R": 1})
    fresh = _w1g2_put(game, set_pool, 0, name, code="APC", sick=True)
    assert _w1g2_activate(game, fresh).supported
    assert not game.is_on_battlefield(fresh)


# Goblin Legionnaire ---------------------------------------------------------


def test_w1g2_goblin_legionnaire_red_ability_deals_two_to_any_target(set_pool):
    """"{R}, Sacrifice this creature: It deals 2 damage to any target." At a
    creature, which dies; at a face, which is at 18. The {W} is left alone."""
    game = _w1g2_table(set_pool, mana={"R": 1, "W": 1})
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    assert _w1g2_activate(
        game, legionnaire, ability_index=0, target_permanent_ids=[bears.permanent_id],
    ).supported
    game.check_state_based_actions()
    assert not game.is_on_battlefield(bears) and not game.is_on_battlefield(legionnaire)
    assert game.players[0].mana_pool["W"] == 1

    game = _w1g2_table(set_pool, mana={"R": 1})
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    assert _w1g2_activate(
        game, legionnaire, ability_index=0, target_player_index=1,
    ).supported
    assert game.players[1].life == 18


def test_w1g2_goblin_legionnaire_white_ability_prevents_the_next_two_damage(set_pool):
    """"{W}, Sacrifice this creature: Prevent the next 2 damage that would be
    dealt to any target this turn." A Lightning Bolt at the shielded Bears
    marks 1; one at the shielded player costs them 1."""
    game = _w1g2_table(
        set_pool, mana={"W": 1}, opp_hand=["Lightning Bolt"], opp_mana={"R": 1},
    )
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    assert _w1g2_activate(
        game, legionnaire, ability_index=1, target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    game.check_state_based_actions()
    assert bears.damage_marked == 1 and game.is_on_battlefield(bears)

    game = _w1g2_table(
        set_pool, mana={"W": 1}, opp_hand=["Lightning Bolt"], opp_mana={"R": 1},
    )
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    assert _w1g2_activate(
        game, legionnaire, ability_index=1, target_player_index=0,
    ).supported
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 19


def test_w1g2_goblin_legionnaire_each_ability_needs_its_own_colour(set_pool):
    """The red ability cannot be paid with {W}: refused, and the Legionnaire is
    not sacrificed. Nor may it be aimed at a creature with protection from
    white — the Legionnaire is red *and* white (CR 702.16b)."""
    game = _w1g2_table(set_pool, mana={"W": 1})
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    assert not _w1g2_activate(
        game, legionnaire, ability_index=0, target_player_index=1,
    ).supported
    assert game.is_on_battlefield(legionnaire) and game.players[1].life == 20

    game.players[0].mana_pool.update({"W": 0, "R": 1})
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    assert not _w1g2_activate(
        game, legionnaire, ability_index=0, target_permanent_ids=[knight.permanent_id],
    ).supported
    assert game.is_on_battlefield(legionnaire) and game.players[0].mana_pool["R"] == 1


# Minotaur Illusionist -------------------------------------------------------


def test_w1g2_minotaur_illusionist_gains_shroud_until_end_of_turn(set_pool):
    """"{1}{U}: This creature gains shroud until end of turn." A Lightning
    Bolt aimed at it afterwards is an illegal announcement and is not cast."""
    game = _w1g2_table(
        set_pool, mana={"U": 2}, opp_hand=["Lightning Bolt"], opp_mana={"R": 1},
    )
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")

    assert _w1g2_activate(game, illusionist, ability_index=0).supported
    assert game._has_keyword(illusionist, "shroud")

    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[illusionist.permanent_id],
    )
    assert not bolt.supported
    assert [card.name for card in game.players[1].hand] == ["Lightning Bolt"]
    assert illusionist.damage_marked == 0


def test_w1g2_minotaur_illusionist_deals_the_power_it_last_had(set_pool):
    """"{R}, Sacrifice this creature: It deals damage equal to its power to
    target creature." Its printed 3 kills a Hill Giant; pumped to 6 by a Giant
    Growth it kills a Craw Wurm, the power being the one it last had on the
    battlefield (CR 608.2h) — it is in the graveyard when the ability
    resolves."""
    game = _w1g2_table(set_pool, mana={"R": 1})
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")
    giant = _w1g2_put(game, set_pool, 1, "Hill Giant")
    assert _w1g2_activate(
        game, illusionist, ability_index=1, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert giant.damage_marked == 3
    assert "Minotaur Illusionist deals 3 damage to Hill Giant" in game.log
    assert not game.is_on_battlefield(illusionist)

    game = _w1g2_table(set_pool, hand=["Giant Growth"], mana={"R": 1, "G": 1})
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[illusionist.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_activate(
        game, illusionist, ability_index=1, target_permanent_ids=[wurm.permanent_id],
    ).supported
    game.check_state_based_actions()
    assert not game.is_on_battlefield(wurm)


def test_w1g2_minotaur_illusionist_is_not_sacrificed_at_an_illegal_target(set_pool):
    """A land is not a creature: the activation is refused before the cost is
    paid (CR 601.2c precedes 601.2h), so the Illusionist and the {R} stay."""
    game = _w1g2_table(set_pool, mana={"R": 1})
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")
    forest = _w1g2_put(game, set_pool, 1, "Forest")

    result = _w1g2_activate(
        game, illusionist, ability_index=1, target_permanent_ids=[forest.permanent_id],
    )

    assert not result.supported
    assert game.is_on_battlefield(illusionist)
    assert game.players[0].mana_pool["R"] == 1


# Razorfin Hunter ------------------------------------------------------------


def test_w1g2_razorfin_hunter_taps_to_deal_one_damage_to_any_target(set_pool):
    """"{T}: This creature deals 1 damage to any target." It taps, the 2/1
    Lions are marked 1; untapped again, a face takes 1. A land is no target,
    and that refusal leaves the Hunter untapped."""
    game = _w1g2_table(set_pool)
    hunter = _w1g2_put(game, set_pool, 0, "Razorfin Hunter", code="APC")
    lions = _w1g2_put(game, set_pool, 1, "Savannah Lions")
    forest = _w1g2_put(game, set_pool, 1, "Forest")

    assert _w1g2_activate(game, hunter, target_permanent_ids=[lions.permanent_id]).supported
    assert hunter.tapped and lions.damage_marked == 1
    assert not _w1g2_activate(game, hunter, target_player_index=1).supported, "tapped"

    hunter.tapped = False
    assert _w1g2_activate(game, hunter, target_player_index=1).supported
    assert game.players[1].life == 19

    hunter.tapped = False
    assert not _w1g2_activate(
        game, hunter, target_permanent_ids=[forest.permanent_id],
    ).supported
    assert not hunter.tapped


def test_w1g2_razorfin_hunter_cannot_tap_the_turn_it_arrives(set_pool):
    """CR 302.6: a {T} ability of a creature that came under its controller's
    control this turn cannot be activated."""
    game = _w1g2_table(set_pool)
    hunter = _w1g2_put(game, set_pool, 0, "Razorfin Hunter", code="APC", sick=True)

    assert not _w1g2_activate(game, hunter, target_player_index=1).supported
    assert game.players[1].life == 20 and not hunter.tapped

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
    # The recruiters that **entered**, not the casts: "cast … -> resolved" is
    # the cast call returning, and since round 4 the other seat can answer it
    # (in this seed one of the eight casts is countered, and has no sort).
    casts = [
        line for line in lines
        if any(line.endswith(f" put {name} onto battlefield") for name in names)
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

from engine import Game as _w1g4c_Game, PlayerState as _w1g4c_Player  # noqa: E402
from engine.models import Permanent as _w1g4c_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w1g4c_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g4c_resolve_stack  # noqa: E402

#: Where a name in these tests is looked for, in order — one pool per card.
_W1G4C_POOLS = ("APC", "LEA")


def _w1g4c_card(set_pool, name):
    """*name* out of the first of this section's pools that prints it."""
    for code in _W1G4C_POOLS:
        found = set_pool(code).get(name)
        if found is not None:
            return found
    raise KeyError(name)  # W1G4 creatures: no pool here prints that name


def _w1g4c_table(set_pool, *, mine=(), hand0=(), hand1=(), lib0=(), lib1=(),
                 interactive=()):
    """A duel with seat 0 in its precombat main phase and costs not enforced."""
    def cards(names):
        return [_w1g4c_card(set_pool, name) for name in names]

    board0 = [_w1g4c_Permanent(card=card) for card in cards(mine)]
    game = _w1g4c_Game(players=[
        _w1g4c_Player(name="P0", battlefield=board0, hand=cards(hand0),
                      library=cards(lib0)),
        _w1g4c_Player(name="P1", hand=cards(hand1), library=cards(lib1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board0  # W1G4 creatures: the table


def _w1g4c_names(cards):
    return [card.name for card in cards]  # W1G4 creatures: a zone, by name


def _w1g4c_whirlpool(game, seat, held_before):
    """The whirlpool, asserted off the zones: a hand of the same size as the
    one that went in, and every card that was in the hand or the library still
    in one of the two."""
    player = game.players[seat]
    assert len(player.hand) == held_before
    return sorted(_w1g4c_names(player.hand) + _w1g4c_names(player.library))  # W1G4


_W1G4C_LIBRARY = ["Grizzly Bears", "Hill Giant", "Black Lotus", "Mox Ruby", "Mox Jet"]


def test_w1g4_whirlpool_rider_trades_its_controllers_hand_for_a_new_one(set_pool):
    """"When this creature enters, shuffle the cards from your hand into your
    library, then draw that many cards." Three cards in hand as the Rider
    enters, three afterwards, the same eight cards between hand and library —
    and the trigger is a stack object, so nothing has moved until it resolves."""
    assert _w1g4c_compile(_w1g4c_card(set_pool, "Whirlpool Rider")).supported
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Rider", "Forest", "Island", "Sol Ring"],
        lib0=_W1G4C_LIBRARY, interactive=(0,),
    )
    assert game.queue_from_hand(0, "Whirlpool Rider").supported
    game.resolve_top_of_stack()

    assert [perm.card.name for perm in game.controlled_by(0)] == ["Whirlpool Rider"]
    assert len(game.stack) == 1, "the entry trigger is waiting to resolve"
    assert _w1g4c_names(game.players[0].hand) == ["Forest", "Island", "Sol Ring"]
    assert game.stack[-1].ability_effect_kind == "triggered_library"

    _w1g4c_resolve_stack(game)
    assert _w1g4c_whirlpool(game, 0, 3) == sorted(
        _W1G4C_LIBRARY + ["Forest", "Island", "Sol Ring"]
    )
    assert len(game.players[0].library) == 5
    assert "P0 shuffled 3 card(s) from their hand into their library" in game.log
    assert game.players[1].hand == [], "only the Rider's controller"


def test_w1g4_whirlpool_rider_with_an_empty_hand_draws_nothing(set_pool):
    """"That many" of none is none: the Rider cast as the last card in hand
    shuffles nothing in and draws nothing, and the library is still whole."""
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Rider"], lib0=_W1G4C_LIBRARY,
    )
    assert game.cast_from_hand(0, "Whirlpool Rider").supported
    _w1g4c_resolve_stack(game)

    assert game.players[0].hand == []
    assert sorted(_w1g4c_names(game.players[0].library)) == sorted(_W1G4C_LIBRARY)


def test_w1g4_whirlpool_drake_whirls_as_it_enters_and_again_as_it_dies(set_pool):
    """"Flying" and the Rider's trigger twice over: once as the Drake enters
    and once when it dies, each for the hand its controller holds *then*."""
    assert _w1g4c_compile(_w1g4c_card(set_pool, "Whirlpool Drake")).supported
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Drake", "Forest", "Island"], hand1=["Terror"],
        lib0=_W1G4C_LIBRARY,
    )
    everything = sorted(_W1G4C_LIBRARY + ["Forest", "Island"])
    assert game.cast_from_hand(0, "Whirlpool Drake").supported
    _w1g4c_resolve_stack(game)

    (drake,) = game.controlled_by(0)
    assert drake.has_keyword("flying")
    assert (drake.effective_power, drake.effective_toughness) == (2, 2)
    assert _w1g4c_whirlpool(game, 0, 2) == everything
    assert game.log.count("P0 shuffled 2 card(s) from their hand into their library") == 1

    game.players[0].hand.append(game.players[0].library.pop())
    assert game.cast_from_hand(
        1, "Terror", target_permanent_ids=[drake.permanent_id]
    ).supported
    _w1g4c_resolve_stack(game)
    game._settle()
    _w1g4c_resolve_stack(game)

    assert _w1g4c_names(game.players[0].graveyard) == ["Whirlpool Drake"]
    assert _w1g4c_whirlpool(game, 0, 3) == everything
    assert "P0 shuffled 3 card(s) from their hand into their library" in game.log
    assert "Whirlpool Drake triggered (died)" in game.log


def test_w1g4_whirlpool_warrior_sacrificed_whirls_every_players_hand(set_pool):
    """"{R}, Sacrifice this creature: **Each player** shuffles the cards from
    their hand into their library, then draws that many cards." Both seats,
    each for its own count out of its own library; the Warrior is the cost."""
    assert _w1g4c_compile(_w1g4c_card(set_pool, "Whirlpool Warrior")).supported
    theirs = ["Air Elemental", "Counterspell", "Time Walk", "Mox Pearl"]
    game, mine = _w1g4c_table(
        set_pool, mine=["Whirlpool Warrior"], hand0=["Forest", "Island"],
        hand1=["Swamp", "Plains", "Mountain"],
        lib0=["Grizzly Bears", "Hill Giant", "Black Lotus"], lib1=theirs,
    )
    result = game.activate_permanent_ability(0, "Whirlpool Warrior", ability_index=0)
    assert result.supported, result.details
    assert result.effect_kind == "activated_library"
    _w1g4c_resolve_stack(game)

    assert not game.is_on_battlefield(mine[0])
    assert _w1g4c_names(game.players[0].graveyard) == ["Whirlpool Warrior"]
    assert _w1g4c_whirlpool(game, 0, 2) == sorted(
        ["Forest", "Island", "Grizzly Bears", "Hill Giant", "Black Lotus"]
    )
    assert _w1g4c_whirlpool(game, 1, 3) == sorted(
        theirs + ["Swamp", "Plains", "Mountain"]
    )
    assert len(game.players[0].library) == 3 and len(game.players[1].library) == 4


def test_w1g4_whirlpool_warrior_enters_whirling_only_its_own_controller(set_pool):
    """The Warrior's *entry* trigger is the Rider's — "your hand", one seat —
    where its activated ability is every player's."""
    game, _ = _w1g4c_table(
        set_pool, hand0=["Whirlpool Warrior", "Forest"], hand1=["Swamp", "Plains"],
        lib0=["Grizzly Bears", "Hill Giant"], lib1=["Air Elemental"],
    )
    assert game.cast_from_hand(0, "Whirlpool Warrior").supported
    _w1g4c_resolve_stack(game)

    assert _w1g4c_whirlpool(game, 0, 1) == ["Forest", "Grizzly Bears", "Hill Giant"]
    assert _w1g4c_names(game.players[1].hand) == ["Swamp", "Plains"]
    assert _w1g4c_names(game.players[1].library) == ["Air Elemental"]

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
    Bearer and nothing else, a Bolt at the face or at the Bears is refused with
    the card still in hand, and a Bolt that names nothing is given the
    picker's one answer (``bare_announcements``) — the Bearer, which it kills.
    After that the second Bolt goes where its caster likes."""
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
    ):
        refused = game.queue_from_hand(0, "Lightning Bolt", **announcement)
        assert not refused.supported and _W1G5_REQUIRED in refused.details, refused
        assert "Flagbearer" in refused.details and "Standard Bearer" in refused.details
    assert not game.stack and len(game.players[0].hand) == 2

    assert game.queue_from_hand(0, "Lightning Bolt").supported
    assert game.stack[-1].target_permanent_id in (
        bearer.permanent_id, [bearer.permanent_id],
    ), game.stack[-1].target_permanent_id
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
    counter the Lightning Bolt nobody had named, which here resolves.

    (W2G3: the Shock was named as the Snake was cast and the trigger's own
    list accepted it, so it is a chosen target and the rule's gate removes the
    trigger above its instructions — the line asserted is the gate's, where it
    was the counter handler's own "…is no longer on the stack".)"""
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
    assert (
        "Mystic Snake ability was removed from the stack: "
        "every target is illegal (608.2b)"
    ) in game.log
    assert not any("was countered by Mystic Snake" in line for line in game.log)
    assert game.players[0].life == 17   # the Bolt was never the Snake's target

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests moved whole to test_apc_creatures_later_groups.py when this
# file crossed its size cap at integration (tests/sets/README.md).

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests moved whole to test_apc_creatures_later_groups.py when this
# file crossed its size cap at integration (tests/sets/README.md).

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests moved whole to test_apc_creatures_later_groups.py when this
# file crossed its size cap at integration (tests/sets/README.md).

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests moved whole to test_apc_creatures_later_groups.py when this
# file crossed its size cap at integration (tests/sets/README.md).

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.
from engine import Game as _w2g2_Game, PlayerState as _w2g2_Player
from engine.models import Permanent as _w2g2_Permanent
from tests.helpers import _mk_card as _w2g2_mk_card, resolve_stack as _w2g2_resolve_stack


def _w2g2_snake_game(set_pool, *, interactive=(0,)):
    """Seat 1's turn with seat 1's Lightning Bolt and then Shock on the stack,
    both aimed at seat 0, and nothing resolved. Returns ``(game, bolt item,
    shock item)`` — Shock is the topmost."""
    lea, sth = set_pool("LEA"), set_pool("STH")
    filler = _w2g2_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w2g2_Game(players=[
        _w2g2_Player(name="P0", library=[filler] * 10),
        _w2g2_Player(
            name="P1", hand=[lea["Lightning Bolt"], sth["Shock"]], library=[filler] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(1)
    game._settle()
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.queue_from_hand(1, "Shock", target_player_index=0).supported
    bolt, shock = game.stack
    return game, bolt, shock  # W2G2 creatures: two spells waiting


def test_w2g2_a_snake_that_was_not_cast_asks_its_controller_which_spell(set_pool):
    """Mystic Snake: "When this creature enters, counter target spell."

    Put onto the battlefield by an effect, with two spells on the stack, for a
    seat somebody can ask: the trigger chooses its target as it goes on the
    stack (CR 603.3d) and the choice is the controller's — the ``trigger_target``
    prompt, offering both spells, topmost first. Naming the **lower** one is
    the answer no default would give; it is the one countered, and the other
    resolves."""
    game, bolt, shock = _w2g2_snake_game(set_pool)
    game._put_permanent_onto_battlefield(
        0, _w2g2_Permanent(card=set_pool("APC")["Mystic Snake"]), None
    )

    trigger = game.stack[-1]
    assert trigger.is_ability and trigger.target_stack_item is None
    prompt = game.pending_choice_of("trigger_target", 0)
    assert prompt is not None, game.log
    assert [(t["kind"], t["name"]) for t in prompt.data["targets"]] == [
        ("stack", "Shock"), ("stack", "Lightning Bolt"),
    ]
    assert game.waiting_prompt().kind == "trigger_target"

    assert game.confirm_trigger_target(0, stack_item=bolt)
    assert trigger.target_stack_item is bolt
    assert "Mystic Snake: targets Lightning Bolt" in game.log
    assert game.pending_choices == []

    _w2g2_resolve_stack(game)
    assert "Lightning Bolt was countered by Mystic Snake and moved to graveyard" in game.log
    assert game.players[0].life == 18, "Shock still resolved"
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt", "Shock"]


def test_w2g2_the_snake_s_answer_is_held_to_the_spells_it_was_offered(set_pool):
    """An answer in another vocabulary names nothing this prompt offered: a
    seat, a permanent's id, the trigger itself and a spell that has left are
    each refused with the prompt still owed (CR 603.3d chooses from the list
    that was offered, and only from it)."""
    game, bolt, shock = _w2g2_snake_game(set_pool)
    snake = _w2g2_Permanent(card=set_pool("APC")["Mystic Snake"])
    game._put_permanent_onto_battlefield(0, snake, None)
    trigger = game.stack[-1]

    assert not game.confirm_trigger_target(0, seat=1)
    assert not game.confirm_trigger_target(0, permanent_id=snake.permanent_id)
    assert not game.confirm_trigger_target(0, stack_item=trigger)
    assert game.trigger_target_stack_item(0, 0) is None, "the trigger is not a spell"
    assert game.trigger_target_stack_item(0, 1) is shock
    assert game.trigger_target_stack_item(0, 2) is bolt
    assert game.trigger_target_stack_item(0, 3) is None
    assert game.trigger_target_stack_item(1, 1) is None, "not seat 1's prompt"
    assert game.pending_choice_of("trigger_target", 0) is not None
    assert trigger.target_stack_item is None

    # A spell that left the stack while the question was open is nobody's
    # target any more.
    game.stack.remove(shock)
    assert not game.confirm_trigger_target(0, stack_item=shock)
    assert game.confirm_trigger_target(0, stack_item=bolt)


def test_w2g2_a_seat_nobody_asks_still_takes_the_topmost_opposing_spell(set_pool):
    """The default did not move: with nobody to ask, the trigger names the
    topmost spell an opponent controls as it is put on the stack, queues
    nothing, and logs what it chose — what every seat got before the prompt
    carried a spell."""
    game, bolt, shock = _w2g2_snake_game(set_pool, interactive=())
    game._put_permanent_onto_battlefield(
        0, _w2g2_Permanent(card=set_pool("APC")["Mystic Snake"]), None
    )

    trigger = game.stack[-1]
    assert trigger.target_stack_item is shock
    assert "Mystic Snake: targets Shock" in game.log
    assert game.pending_choices == []

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

from engine import Game as _w2g3_Game, PlayerState as _w2g3_PlayerState
from engine.models import Permanent as _w2g3_Permanent
from tests.helpers import resolve_stack as _w2g3_resolve_stack

#: Where the borrowed cards were first printed; every other name is Apocalypse's.
_W2G3_HOMES = {"Swamp": "LEA", "Hill Giant": "LEA", "Grizzly Bears": "LEA"}

#: The line CR 608.2b's gate writes when an activated ability's every target
#: has become illegal (``legality_resolution.ability_targets_refusal``).
_W2G3_FIZZLE = (
    "Savage Gorilla ability was removed from the stack: "
    "every target is illegal (608.2b)"
)


def _w2g3_gorilla_table(set_pool, *names_for_seat_1):
    """Seat 0 controls a Savage Gorilla it can pay for, with five Swamps to
    draw from; seat 1 controls *names_for_seat_1*. Returns the game, the
    Gorilla and seat 1's permanents in order."""
    swamp = set_pool("LEA")["Swamp"]
    game = _w2g3_Game(players=[
        _w2g3_PlayerState(name="P0", library=[swamp] * 5),
        _w2g3_PlayerState(name="P1", library=[swamp] * 5),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.players[0].mana_pool.update({"U": 3, "B": 3})
    gorilla = _w2g3_Permanent(card=set_pool("APC")["Savage Gorilla"])
    game._put_permanent_onto_battlefield(0, gorilla, None)
    gorilla.metadata["summoning_sickness_turn"] = -99
    theirs = []
    for name in names_for_seat_1:
        perm = _w2g3_Permanent(card=set_pool(_W2G3_HOMES.get(name, "APC"))[name])
        game._put_permanent_onto_battlefield(1, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        theirs.append(perm)
    return game, gorilla, theirs


def _w2g3_zone_names(cards) -> list:
    return [card.name for card in cards]


def test_w2g3_savage_gorilla_draws_no_card_when_its_target_has_left(set_pool):
    """"{U}{B}, {T}, Sacrifice this creature: Target creature gets -3/-3 until
    end of turn. Draw a card." Its ruling (2004-10-04): "You do not get to draw
    a card if the target is not legal on resolution." CR 608.2b — with every
    target illegal the ability does not resolve, so the sentence printed
    *behind* the targeted one does not happen either. The cost stays paid, and
    the creature standing beside the departed target is not shrunk in its
    place."""
    game, _gorilla, (giant, bears) = _w2g3_gorilla_table(
        set_pool, "Hill Giant", "Grizzly Bears"
    )

    queued = game.queue_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[giant.permanent_id],
    )
    assert queued.supported and queued.details == "queued", queued
    # In response the Giant leaves the battlefield.
    game.remove_from_battlefield(giant)
    game.players[1].graveyard.append(giant.card)
    _w2g3_resolve_stack(game)

    assert _W2G3_FIZZLE in game.log, game.log[-5:]
    assert game.players[0].hand == [], "no card: the ability did not resolve"
    assert len(game.players[0].library) == 5
    assert _w2g3_zone_names(game.players[0].graveyard) == ["Savage Gorilla"], (
        "the sacrifice was a cost, and a cost is not refunded"
    )
    assert (bears.effective_power, bears.effective_toughness) == (2, 2), (
        "the creature beside the target is nobody's target"
    )
    assert not game.stack


def test_w2g3_savage_gorilla_aimed_at_itself_is_sacrificed_and_draws_nothing(set_pool):
    """The Gorilla is a creature, so it is a legal target for its own ability
    as that ability is announced (CR 601.2c comes before CR 601.2h) — and the
    cost then sacrifices it. By the time the ability resolves its one target is
    in a graveyard: illegal, so no card (CR 608.2b)."""
    game, gorilla, _theirs = _w2g3_gorilla_table(set_pool)

    queued = game.queue_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[gorilla.permanent_id],
    )
    assert queued.supported and queued.details == "queued", queued
    assert _w2g3_zone_names(game.players[0].graveyard) == ["Savage Gorilla"]
    _w2g3_resolve_stack(game)

    assert _W2G3_FIZZLE in game.log, game.log[-5:]
    assert game.players[0].hand == []
    assert len(game.players[0].library) == 5


def test_w2g3_savage_gorilla_does_nothing_to_a_target_that_gained_protection(set_pool):
    """The rule's own second example: "if the creature has gained protection
    from [the source's colour] or left the battlefield". The Gorilla is green,
    so a target given protection from green in response is no longer one its
    ability could name — it is not shrunk, and no card is drawn. The target is
    still on the battlefield, which is what no handler's own "is it still
    there?" could have noticed."""
    game, _gorilla, (giant,) = _w2g3_gorilla_table(set_pool, "Hill Giant")

    assert game.queue_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[giant.permanent_id],
    ).supported
    giant.metadata["protection_from_green"] = True
    _w2g3_resolve_stack(game)

    assert _W2G3_FIZZLE in game.log, game.log[-5:]
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)
    assert game.is_on_battlefield(giant)
    assert game.players[0].hand == []


def test_w2g3_savage_gorilla_still_shrinks_and_draws_when_its_target_is_legal(set_pool):
    """The other direction, through the same queue-then-resolve path: nothing
    happened in response, the target is exactly what was announced, and both
    printed sentences happen."""
    game, _gorilla, (giant,) = _w2g3_gorilla_table(set_pool, "Hill Giant")

    assert game.queue_permanent_ability(
        0, "Savage Gorilla", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w2g3_resolve_stack(game)
    game.check_state_based_actions()

    assert _W2G3_FIZZLE not in game.log
    assert _w2g3_zone_names(game.players[0].hand) == ["Swamp"]
    assert _w2g3_zone_names(game.players[1].graveyard) == ["Hill Giant"], (
        "a 3/3 given -3/-3 dies (CR 704.5f)"
    )

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.
from engine import Game as _w2g4_Game
from engine import PlayerState as _w2g4_PlayerState
from engine.models import Permanent as _w2g4_Permanent
from tests.helpers import _nosick as _w2g4_nosick


def _w2g4_creature_table(set_pool, catalog_by_name, mine, *, interactive=(0,)):
    """Seat 0 controls *mine* (Apocalypse cards first, the pool otherwise) at
    its main phase. Returns ``(game, seat 0's permanents)``."""
    def card(name):
        return set_pool("APC").get(name) or catalog_by_name[name]

    board = [_w2g4_nosick(_w2g4_Permanent(card=card(name))) for name in mine]
    game = _w2g4_Game(players=[
        _w2g4_PlayerState(name="Keeper", battlefield=board,
                          library=[catalog_by_name["Forest"]] * 6),
        _w2g4_PlayerState(name="Other", library=[catalog_by_name["Forest"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game, board  # W2G4: the creature table


# -- item 4: what holds an ability on the stack while a colour is chosen ------


def test_w2g4_spiritmongers_colour_ability_is_held_until_the_colour_is_named(
    set_pool, catalog_by_name
):
    """"{G}: This creature becomes the color of your choice until end of
    turn." On the paths a seat is on — ``activate_permanent_ability`` (which
    settles) and ``pass_priority`` — a resolution that stops to ask keeps its
    object on the stack (CR 608.2), the game waits (CR 117.3b), and the log
    does not say "resolved" until the answer arrives."""
    game, (monger,) = _w2g4_creature_table(set_pool, catalog_by_name, ["Spiritmonger"])
    mark = len(game.log)

    assert game.activate_permanent_ability(0, "Spiritmonger", ability_index=1).supported

    (held,) = game.stack
    assert held.is_ability and held.resolution_held
    (owed,) = game.pending_choices
    assert owed.kind == "color_choice" and owed.data["_stack_item"] is held
    assert game.waiting_prompt() is owed and game.effect_suspended
    assert game.log[mark:] == [
        "Spiritmonger ability added to stack",
        "Spiritmonger: Keeper chooses a color",
        "Spiritmonger ability is resolving, awaiting a choice",
    ]
    assert monger.effective_colors == {"B", "G"}

    assert game.resolve_pending_choice("color_choice", 0, mana_color="R")

    assert monger.effective_colors == {"R"}
    assert game.stack == [] and game.waiting_prompt() is None
    assert game.log[-1] == "Spiritmonger finished resolving"


def test_w2g4_a_bare_resolve_top_of_stack_is_the_headless_form_and_says_so(
    set_pool, catalog_by_name
):
    """The observation W1G1 made, pinned as what it is. ``resolve_top_of_stack``
    called with no ``pause_for_choices`` is the headless form — "the object
    resolves and pops immediately and the caller drains the prompts" — so with
    an interactive seat it logs "ability resolved" and empties the stack with
    the colour still owed. Nothing can be done in the gap: the prompt holds the
    game and the effect is applied by the answer. No seat is ever on this
    path; the two a seat is on are the test above."""
    game, (monger,) = _w2g4_creature_table(set_pool, catalog_by_name, ["Spiritmonger"])
    assert game.queue_permanent_ability(0, "Spiritmonger", ability_index=1).supported

    game.resolve_top_of_stack()

    assert game.stack == [] and game.log[-1] == "Spiritmonger ability resolved"
    (owed,) = game.pending_choices
    assert "_stack_item" not in owed.data
    assert game.waiting_prompt() is owed, "and the game waits all the same"
    assert monger.effective_colors == {"B", "G"}
    assert game.resolve_pending_choice("color_choice", 0, mana_color="R")
    assert monger.effective_colors == {"R"}


# -- item 5: a gift names its own seat ----------------------------------------


def test_w2g4_mournful_zombie_gives_its_life_to_the_seat_that_paid_for_it(
    set_pool, catalog_by_name
):
    """"{W}, {T}: Target player gains 1 life." The AI named an opponent — the
    policy's list of gift kinds said ``gain_life``, a name nothing compiles to,
    so the ability fell through to "aim it at them". It proposes its own seat
    now, and the activation it proposes gains that seat the life."""
    from engine.ai_abilities import choose_activation_action

    game, (zombie,) = _w2g4_creature_table(
        set_pool, catalog_by_name, ["Mournful Zombie"], interactive=(),
    )
    action = choose_activation_action(game, 0)

    assert action is not None and action.permanent_name == "Mournful Zombie"
    assert action.target_player_index == 0 and action.target_permanent_index is None
    assert game.activate_permanent_ability(
        0, "Mournful Zombie", target_player_index=action.target_player_index,
    ).supported
    assert [player.life for player in game.players] == [21, 20]
    assert zombie.tapped
    assert "Keeper gained 1 life from Mournful Zombie (20 -> 21)" in game.log


def test_w2g4_mournful_zombie_in_a_simulated_game_never_heals_the_other_seat():
    """The same through whole games, where it was first seen: every "gained 1
    life from Mournful Zombie" line names the seat whose activation it follows.
    The card is pinned into both decks; the test asks that it was activated at
    all, not how often."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    gains = []
    # Seeds 1-3 ahead of the three it was written with: once a precombat
    # cast was weighed through the turn's fight, those three games went
    # another way and none of them activated a Zombie; 1, 2 and 3 do, on
    # that tree, eleven, five and three times.
    for seed in (1, 2, 3, 7, 11, 1337):
        report = run_ai_simulation(
            cards_path=[manifest_set_path("APC", include_measured=True)],
            games=3, seed=seed, max_turns=18, required_cards=["Mournful Zombie"],
        )
        assert report.ok, report.issues[:3]
        activator = None
        for line in report.log_lines:
            if " activate Mournful Zombie" in line:
                activator = line.split(" activate ")[0].split()[-1]
            elif "gained 1 life from Mournful Zombie" in line:
                gains.append((activator, line.split()[0]))
        if gains:
            break

    assert gains, "no seed activated a Mournful Zombie"
    assert all(activator == gainer for activator, gainer in gains), gains

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================

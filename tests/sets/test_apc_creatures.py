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
    report; only the recruiters' lines are read. The floor is well under what
    the seed gives today — nine casts — so another card becoming castable does
    not move it.)"""
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
    assert len(casts) >= 4, casts
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
    assert sorts >= len(casts) >= 4, (sorts, casts)
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

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

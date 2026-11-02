"""An optional target slot is an optional **role** (CR 601.2c's "up to one").

"Target creature you control gets +X/+X until end of turn. Then it fights **up
to one** target creature you don't control." (Primal Might.) Two printed
instances of the word "target", each with its own narrowing, and the second may
be left unannounced. A roles walk used to answer every role or refuse, so
``target_descriptions._slot_roles_spec`` left such a description on one shared
list — and the intersection of "you control" and "you don't control" is
nothing, so the picker offered every creature for both slots and the cast gate
admitted an announcement aimed the wrong way round: the card was spent, and the
handler then declined to do anything with it.

The role now carries ``target_roles.OPTIONAL_ROLE``: the walk keeps a first
choice whose next role has nothing to offer, the gates accept an announcement
that stops before it (``target_roles.role_announcement``), and everything named
is held to its own slot's narrowing.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.control import change_control
from engine.grammar.lowering._roles import _announced_slots
from engine.models import Permanent
from engine.oracle import compiled_units
from engine.target_roles import OPTIONAL_ROLE, spec_roles
from engine.targeting import derive_activation_spec, derive_cast_spec
from tests.helpers import resolve_stack

#: Both manifest roles, first printing wins — a measured set's optional slot
#: is a card about to ship, and the census is about the shape.
_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _announcements(program):
    """(where, instructions, derived spec) for each announcement a program
    makes: the spell, and each activated ability."""
    yield "spell", program.instructions, None
    for index, ability in enumerate(program.activated_abilities):
        if ability.instruction is not None:
            yield f"activated {index}", (ability.instruction,), ability


def _optional_slot_descriptions():
    """Every compiled description in the pool that lets a slot go unnamed,
    with the spec the picker derives for its announcement."""
    found = []
    for card, program in compiled_units(_POOL.values()):
        for where, instructions, ability in _announcements(program):
            for described, _carrier in _announced_slots(instructions):
                if not described.get("optional_slots"):
                    continue
                spec = (
                    derive_activation_spec(ability) if ability is not None
                    else derive_cast_spec(card, program)
                )
                found.append((card.name, where, described, spec))
    return found


def test_every_optional_slot_in_the_pool_is_an_optional_role_with_its_own_narrowing():
    """The census. On the base this ran on, Primal Might's spec was
    ``{'kind': 'creature', 'max_targets': 2}`` — one list, no seat test on
    either slot."""
    found = _optional_slot_descriptions()
    assert found, "no optional slot in the pool — the census measured nothing"

    wrong = []
    for name, where, described, spec in found:
        roles = spec_roles(spec)
        slots = described.get("filters") or []
        if len(roles) != len(slots):
            wrong.append(f"{name} [{where}]: {spec!r} is not one role per slot")
            continue
        optional = set(described["optional_slots"])
        marked = {i for i, role in enumerate(roles) if role.get(OPTIONAL_ROLE)}
        if marked != optional:
            wrong.append(f"{name} [{where}]: optional roles {marked} != slots {optional}")
        for position, (slot, role) in enumerate(zip(slots, roles)):
            controller = (slot or {}).get("controller")
            if controller == "you" and not role.get("own_only"):
                wrong.append(f"{name} [{where}]: slot {position} lost 'you control'")
            if controller in ("not_you", "opponent") and not role.get("opponent_only"):
                wrong.append(f"{name} [{where}]: slot {position} lost 'you don't control'")
    assert not wrong, "; ".join(wrong)


def _table(*, theirs: bool = True):
    pool = _POOL
    mine = Permanent(card=pool["Grizzly Bears"])          # 2/2
    also = Permanent(card=pool["Hill Giant"])             # 3/3
    p2_board = [Permanent(card=pool["Gray Ogre"])] if theirs else []
    game = Game(players=[
        PlayerState("P1", battlefield=[mine, also], hand=[pool["Primal Might"]],
                    library=[pool["Forest"]] * 5),
        PlayerState("P2", battlefield=p2_board, library=[pool["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    return game, mine, also, (p2_board[0] if p2_board else None)


def _tree(entries):
    return {
        (entry["seat"], entry["name"]): _tree(entry.get("next") or [])
        for entry in entries
    }


def test_the_picker_offers_each_slot_its_own_side():
    """The walk the browser is handed: the first slot offers the caster's
    creatures only, the second the opponent's only."""
    game, _mine, _also, _theirs = _table()
    spec = game.cast_target_spec(0, _POOL["Primal Might"])

    assert _tree(spec["valid_targets"]) == {
        (0, "Grizzly Bears"): {(1, "Gray Ogre"): {}},
        (0, "Hill Giant"): {(1, "Gray Ogre"): {}},
    }


def test_with_nobody_to_fight_the_walk_still_offers_the_pump():
    """An empty second role ends the announcement rather than refusing the
    first choice (CR 601.2c: "up to one" may name none)."""
    game, _mine, _also, _theirs = _table(theirs=False)
    spec = game.cast_target_spec(0, _POOL["Primal Might"])

    assert _tree(spec["valid_targets"]) == {(0, "Grizzly Bears"): {}, (0, "Hill Giant"): {}}
    assert game.no_legal_cast_target_refusal(0, _POOL["Primal Might"]) is None


@pytest.mark.parametrize("label, named", [
    ("the slots swapped", lambda m, a, t: [t, m]),
    ("a second creature of the caster's own", lambda m, a, t: [m, a]),
    ("the opponent's creature alone", lambda m, a, t: [t]),
    ("one creature named twice", lambda m, a, t: [m, m]),
])
def test_a_wrong_side_announcement_is_refused_with_the_card_in_hand(label, named):
    """Each of these was accepted on the base, the card spent, and the
    resolution did nothing or only the pump."""
    game, mine, also, theirs = _table()
    ids = [perm.permanent_id for perm in named(mine, also, theirs)]

    result = game.cast_from_hand(0, "Primal Might", x_value=1, target_permanent_ids=ids)

    assert not result.supported, label
    assert [card.name for card in game.players[0].hand] == ["Primal Might"]
    assert not game.stack
    assert (mine.effective_power, theirs.damage_marked) == (2, 0)


def test_one_target_is_a_whole_announcement_and_pumps_without_a_fight():
    game, mine, _also, theirs = _table()

    result = game.cast_from_hand(
        0, "Primal Might", x_value=2, target_permanent_ids=[mine.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert (mine.effective_power, mine.effective_toughness) == (4, 4)
    assert theirs.damage_marked == 0
    assert "Primal Might: no second creature, so no damage is exchanged" in game.log


def test_an_empty_optional_slot_on_the_wire_is_the_same_announcement():
    """A hole in the optional role (``target_role_refs``-style ``None``) reads
    as the shorter announcement."""
    game, mine, _also, theirs = _table()

    result = game.cast_from_hand(
        0, "Primal Might", x_value=1, target_permanent_ids=[mine.permanent_id, None],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert mine.effective_power == 3 and theirs.damage_marked == 0


def test_two_targets_pump_then_fight():
    game, mine, _also, theirs = _table()

    result = game.cast_from_hand(
        0, "Primal Might", x_value=1,
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert theirs.damage_marked == 3 and mine.damage_marked == 2
    assert not game.is_on_battlefield(theirs)


@pytest.mark.cr("608.2b")
def test_a_second_target_gone_illegal_still_leaves_the_pump():
    """Scryfall 2020-06-23: "If that creature is a legal target but the
    creature you don't control isn't, it still gets +X/+X." The opponent's
    creature changes sides in response, so it no longer answers "you don't
    control"."""
    game, mine, _also, theirs = _table()
    queued = game.queue_from_hand(
        0, "Primal Might", x_value=2,
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    assert queued.supported, queued.details

    change_control(theirs, 0, source="test")
    game._sync_control()
    resolve_stack(game)

    assert (mine.effective_power, mine.effective_toughness) == (4, 4)
    assert theirs.damage_marked == 0 and mine.damage_marked == 0


@pytest.mark.cr("608.2b")
def test_a_first_target_gone_means_nobody_is_pumped_or_fought():
    """Scryfall 2020-06-23: "If the creature you control is an illegal target
    as Primal Might tries to resolve, no creature gets +X/+X." """
    game, mine, _also, theirs = _table()
    queued = game.queue_from_hand(
        0, "Primal Might", x_value=2,
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    )
    assert queued.supported, queued.details

    change_control(mine, 1, source="test")
    game._sync_control()
    resolve_stack(game)

    assert mine.effective_power == 2 and theirs.damage_marked == 0
    assert "Primal Might: no legal creature to affect" in game.log


def test_the_ai_skips_the_optional_role_when_its_side_has_nothing():
    """``ai_targets._role_chain`` answers an optional role where it can and
    stops where it cannot — a chain that refused it would leave the pump in
    hand."""
    from engine.ai_targets import _choose_role_targets

    game, mine, also, _theirs = _table(theirs=False)
    picked = _choose_role_targets(game, 0, _POOL["Primal Might"])

    assert picked, "no chain at all"
    _seat, indices, ids, _stack, _refs = picked
    assert len(ids) == 1 and ids[0] in (mine.permanent_id, also.permanent_id)


def test_the_ai_aims_the_fight_at_the_other_side():
    from engine.ai_targets import _choose_role_targets

    game, _mine, _also, theirs = _table()
    _seat, _indices, ids, _stack, _refs = _choose_role_targets(game, 0, _POOL["Primal Might"])

    assert len(ids) == 2 and ids[1] == theirs.permanent_id


@pytest.mark.full
def test_a_seeded_run_casts_primal_might():
    """Primal Might pinned into both decks of a seeded M21 run: a seat casts
    it at least once, nothing it proposed was refused, and no game raised."""
    report = run_ai_simulation(
        manifest_set_path("M21", include_measured=True), games=2, seed=3,
        max_turns=14, required_cards=["Primal Might"],
    )
    assert report.games_completed == 2
    assert not report.issues, report.issues
    assert not any("Primal Might" in reason for reason in report.refused_casts)
    assert any(
        "cast Primal Might -> resolved" in line for line in report.log_lines
    ), "no seat cast Primal Might; pick another seed"

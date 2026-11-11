"""A spell or ability whose one target is a **spell** can have that target
changed (CR 115.7, 115.7a, 115.9a).

    115.7a If an effect allows a player to "change the target(s)" of a spell
    or ability, each target can be changed only to another legal target. If a
    target can't be changed to another legal target, the original target is
    unchanged, even if the original target is illegal. …

"Target spell with a single target" counts a spell target like any other
(CR 115.9a counts "the number of targets chosen for" the object). The
Deflection family — the two-step change ``choose_new_spell_target`` /
``change_target_spell_target`` (Deflection, Misdirection, Divert, Willbender,
and the narrower Reflecting Mirror, Rebound, Meddle, Silver Wyvern, Quicksilver
Dragon) — answered the count through ``targeting.single_spell_target``, which
refused any object aimed at the stack, and offered new targets through
``handlers/retargeting._legal_new_targets``, which dropped every stack entry.
So a Counterspell could not be Deflected at all: "no valid target for
Deflection", the logs round's repro.

The census is by shape, over every pool card whose program carries the
two-step change (a floor on how many), each against three stacks — a spell
that targets a spell, a spell that targets a player, and an ability that
targets a spell — asking whether the card may target the object (its own cast
or activation picker) and, where it may, what the object is offered and what
it ends up targeting. Each card's expected answer is its printed restriction:
"with a single target" admits all three objects (spells only, unless it says
"or ability"); "if that target is you", "that targets only a player", "that
target is a creature" and "targets only this creature" admit none aimed at a
spell. The CR 115.7 changes that already went through ``stack_targets``'
general reader (Psychic Battle, Grip of Chaos, a Fork's copy) are the
controls, driven on the spell-at-a-spell stack.

Backwards on the base (8e42acee + the leftovers' earlier commits): every
"with a single target" card refuses the Counterspell and Willbender the
Daring Apprentice ability; the controls pass.

**The population is both manifest roles** (``_pool``), so a measured set's
retargeter is in the census before its promotion and a plain run and a
``MTG_PROMOTE`` rehearsal ask the same table: Darksteel's Shunt joined that
way (DST W1G3), Deflection's sentence and so Deflection's row.
"""
from __future__ import annotations

import random

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.face_down import face_down_card
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.special_actions import take_permanent_special_action
from tests.helpers import resolve_stack

def _pool() -> list:
    """Both manifest roles, first printing of a name kept."""
    cards: dict[str, object] = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return list(cards.values())


_C = {card.name: card for card in _pool()}


def _kinds(program) -> set:
    found: set = set()

    def walk(instruction):
        if instruction is None or not hasattr(instruction, "kind"):
            return
        found.add(instruction.kind)
        payload = getattr(instruction, "payload", None) or {}
        for value in payload.values():
            if hasattr(value, "kind"):
                walk(value)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    walk(child)

    for instruction in program.instructions:
        walk(instruction)
    for ability in program.activated_abilities:
        walk(getattr(ability, "instruction", None))
    for trigger in program.triggered_abilities:
        walk(getattr(trigger, "instruction", None))
    return found


#: What each card's printed restriction admits: (a spell aimed at a spell,
#: a spell aimed at its controller's opponent's face... — see ``_STACKS``).
#: ``how`` is how the card is put to work: cast from hand, an activated
#: ability of a permanent on the battlefield, or a face-up trigger.
_RETARGETERS = {
    # "Change the target of target spell with a single target."
    "Deflection": {"how": "cast", "spell_at_spell": True, "spell_at_player": True, "ability_at_spell": False},
    "Misdirection": {"how": "cast", "spell_at_spell": True, "spell_at_player": True, "ability_at_spell": False},
    # Darksteel (measured until its promotion): the same sentence.
    "Shunt": {"how": "cast", "spell_at_spell": True, "spell_at_player": True, "ability_at_spell": False},
    # "…unless that spell's controller pays {2}."
    "Divert": {"how": "cast", "spell_at_spell": True, "spell_at_player": True, "ability_at_spell": False},
    # "…target spell or ability with a single target."
    "Willbender": {"how": "face_up", "spell_at_spell": True, "spell_at_player": True, "ability_at_spell": True},
    # "…with a single target if that target is you. The new target must be a player."
    "Reflecting Mirror": {"how": "ability", "spell_at_spell": False, "spell_at_player": True, "ability_at_spell": False},
    # "…target spell that targets only a player. The new target must be a player."
    "Rebound": {"how": "cast", "spell_at_spell": False, "spell_at_player": True, "ability_at_spell": False},
    # "If target spell has only one target and that target is a creature…"
    "Meddle": {"how": "cast", "spell_at_spell": False, "spell_at_player": False, "ability_at_spell": False},
    # "…target spell or ability that targets only this creature."
    "Silver Wyvern": {"how": "ability", "spell_at_spell": False, "spell_at_player": False, "ability_at_spell": False},
    # "If target spell has only one target and that target is this creature…"
    "Quicksilver Dragon": {"how": "ability", "spell_at_spell": False, "spell_at_player": False, "ability_at_spell": False},
}


@pytest.mark.cr("115.7a")
def test_the_census_covers_every_two_step_retarget_in_the_pool():
    """The table is the pool's, not a sample: every card whose program carries
    the two-step change is in it, and there are at least eight."""
    printed = sorted({
        unit.name for unit in compilation_units(_pool())
        if "choose_new_spell_target" in _kinds(compile_card_oracle(unit))
    })
    assert len(printed) >= 8, printed
    assert printed == sorted(_RETARGETERS), printed


def _table() -> Game:
    """P2 (seat 1) owns the spells; P1 (seat 0) holds every retargeter and is
    the interactive seat, with a Grizzly Bears so a face has company."""
    game = Game(players=[
        PlayerState("P1", library=[_C["Island"]] * 10),
        PlayerState("P2", library=[_C["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    for seat, name in ((0, "Grizzly Bears"), (1, "Grizzly Bears")):
        permanent = Permanent(card=_C[name])
        permanent.metadata["summoning_sickness_turn"] = -99
        game._put_permanent_onto_battlefield(seat, permanent, None)
    game.start_turn(0)
    game._close_current_priority_step()
    game.interactive_seats = {0}
    return game


def _put(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _cast(game: Game, seat: int, name: str, **announcement):
    """Cast *name* and return its stack object -- by identity, because a
    trigger it set off (Psychic Battle, Grip of Chaos) sits above it."""
    card = _C[name]
    game.players[seat].hand.append(card)
    result = game.queue_from_hand(seat, name, **announcement)
    assert result.supported, (name, result.details, game.log[-4:])
    return next(
        item for item in reversed(game.stack)
        if item.card is card and not getattr(item, "is_ability", False)
    )


def _index_of(game: Game, obj) -> int:
    """*obj*'s engine (bottom-first) stack index, which ``queue_from_hand``'s
    ``target_stack_index`` names."""
    return next(i for i, item in enumerate(game.stack) if item is obj)


def _spell_at_spell(game: Game):
    """P2's Shock and Lightning Bolt at P1's face, P2's Giant Growth on its
    Bears, and P1's Counterspell at the Shock — the object to re-aim, with
    two other spells it could legally be aimed at instead."""
    shock = _cast(game, 1, "Shock", target_player_index=0)
    bolt = _cast(game, 1, "Lightning Bolt", target_player_index=0)
    bears = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
    growth = _cast(game, 1, "Giant Growth", target_permanent_ids=[bears.permanent_id])
    counter = _cast(game, 0, "Counterspell", target_stack_index=_index_of(game, shock))
    assert counter.target_stack_item is shock
    return counter, {"Shock": shock, "Lightning Bolt": bolt, "Giant Growth": growth}


def _spell_at_player(game: Game):
    """P2's Shock at P1's face."""
    shock = _cast(game, 1, "Shock", target_player_index=0)
    return shock, {}


def _ability_at_spell(game: Game):
    """P2's Shock and Lightning Bolt at P1's face, and P1's Daring Apprentice
    — "{T}, Sacrifice this creature: Counter target spell." — at the Shock."""
    shock = _cast(game, 1, "Shock", target_player_index=0)
    bolt = _cast(game, 1, "Lightning Bolt", target_player_index=0)
    _put(game, 0, _C["Daring Apprentice"])
    activated = game.queue_permanent_ability(
        0, "Daring Apprentice", target_stack_index=_index_of(game, shock),
    )
    assert activated.supported, (activated.details, game.log[-4:])
    ability = next(item for item in reversed(game.stack) if item.is_ability)
    assert ability.is_ability and ability.target_stack_item is shock
    return ability, {"Shock": shock, "Lightning Bolt": bolt}


_STACKS = {
    "spell_at_spell": _spell_at_spell,
    "spell_at_player": _spell_at_player,
    "ability_at_spell": _ability_at_spell,
}


def _offered_by_picker(game: Game, name: str, how: str, retargeter_permanent) -> list:
    """The stack objects *name*'s own picker offers as its target, as the
    objects themselves (top-first indices turned back into identity)."""
    if how == "cast":
        spec = game.cast_target_spec(0, _C[name])
    else:
        seat_index = next(
            index for index, permanent in enumerate(game.controlled_by(0))
            if permanent is retargeter_permanent
        )
        spec = game.activation_target_spec(0, seat_index)
    depth = len(game.stack)
    return [
        game.stack[depth - 1 - entry["stack_index"]]
        for entry in (spec or {}).get("valid_targets") or ()
        if entry.get("kind") == "stack"
    ]


def _the_object_offered(game, name, how, obj, permanent) -> bool:
    if how == "face_up":
        # Willbender's trigger chooses its target as it is put on the stack
        # (CR 603.3d): the interactive seat is asked, and the prompt lists
        # what it may name. A special action wants priority (CR 116.1).
        game.start_priority_window(0)
        assert take_permanent_special_action(game, 0, permanent, "turn_face_up") is None
        choice = game.pending_choice_of("trigger_target", 0)
        if choice is None:
            return False
        offered = [
            entry.get("stack_item") for entry in choice.data.get("targets") or ()
            if entry.get("kind") == "stack"
        ]
        return any(item is obj for item in offered)
    return any(item is obj for item in _offered_by_picker(game, name, how, permanent))


@pytest.mark.cr("115.7", "115.7a", "115.9a")
@pytest.mark.parametrize("stack", sorted(_STACKS))
@pytest.mark.parametrize("name", sorted(_RETARGETERS))
def test_a_retarget_may_name_what_its_printed_restriction_admits(name, stack):
    """Whether the card's own picker offers the object, against the card's
    printed restriction. The ``False`` rows are the narrowings that must keep
    refusing once a spell target is countable."""
    row = _RETARGETERS[name]
    game = _table()
    obj, _others = _STACKS[stack](game)
    permanent = None
    if row["how"] == "ability":
        permanent = _put(game, 0, _C[name])
    elif row["how"] == "face_up":
        permanent = _put(game, 0, face_down_card(_C[name]))
        game.players[0].mana_pool["U"] = game.players[0].mana_pool.get("U", 0) + 2
        game.players[0].mana_pool["C"] = game.players[0].mana_pool.get("C", 0) + 4
    assert _the_object_offered(game, name, row["how"], obj, permanent) is row[stack], (
        name, stack, game.log[-6:],
    )


def _retarget(game: Game, name: str, obj):
    """Put *name* to work against *obj* and resolve it alone, the interactive
    seat choosing nothing yet. The retargeting spell's own stack object, or
    None for Willbender's trigger."""
    row = _RETARGETERS[name]
    if row["how"] == "cast":
        spell = _cast(game, 0, name, target_stack_index=_index_of(game, obj))
        game.resolve_top_of_stack(pause_for_choices=True)
        return spell
    permanent = _put(game, 0, face_down_card(_C[name]))
    game.players[0].mana_pool["U"] = game.players[0].mana_pool.get("U", 0) + 2
    game.start_priority_window(0)
    assert take_permanent_special_action(game, 0, permanent, "turn_face_up") is None
    if game.pending_choice_of("trigger_target", 0) is not None:
        assert game.confirm_trigger_target(0, stack_item=obj), game.log[-4:]
    game.resolve_top_of_stack(pause_for_choices=True)
    return None


@pytest.mark.cr("115.7a")
@pytest.mark.parametrize("name", ["Deflection", "Misdirection", "Shunt", "Willbender"])
def test_a_counterspell_is_offered_the_other_spells_and_moved_onto_the_one_chosen(name):
    """The entry's board, with a third spell so the change is a question: the
    Counterspell aimed at the Shock is offered the Lightning Bolt and the Giant
    Growth — never the Shock it already names (CR 115.7a's "another"), never
    itself (CR 115.5) — and, answered, counters the Bolt. The Shock then
    resolves. A retargeting **spell** is offered too, being on the stack as
    it resolves (Deflection's and Misdirection's 2004-10-04 ruling);
    Willbender's trigger is an ability, which "target spell" cannot name."""
    game = _table()
    counter, others = _spell_at_spell(game)
    spell = _retarget(game, name, counter)

    choice = game.pending_choice_of("retarget_choice", 0)
    assert choice is not None, game.log[-6:]
    offered = [
        option.get("_stack_item") for option in choice.data["options"]
        if option.get("kind") == "stack"
    ]
    assert len(offered) == (3 if spell is not None else 2), choice.data["options"]
    assert any(item is others["Lightning Bolt"] for item in offered)
    assert any(item is others["Giant Growth"] for item in offered)
    assert spell is None or any(item is spell for item in offered)
    assert not any(item is others["Shock"] or item is counter for item in offered)
    bolt_at = next(
        position for position, option in enumerate(choice.data["options"])
        if option.get("_stack_item") is others["Lightning Bolt"]
    )
    assert game.confirm_retarget_choice(0, bolt_at)
    resolve_stack(game)

    assert counter.target_stack_item is others["Lightning Bolt"]
    assert any("Counterspell now targets" in line and "Lightning Bolt" in line for line in game.log), game.log[-8:]
    assert any(card.name == "Lightning Bolt" for card in game.players[1].graveyard)
    # The Shock resolved; the Bolt did not.
    assert game.players[0].life == 18, game.log[-8:]


@pytest.mark.cr("115.7a")
def test_divert_moves_a_counterspell_when_its_controller_does_not_pay():
    """"…unless that spell's controller pays {2}": P1 controls the
    Counterspell and has no mana, so the change is made."""
    game = _table()
    counter, others = _spell_at_spell(game)
    game.interactive_seats = set()
    _cast(game, 0, "Divert", target_stack_index=_index_of(game, counter))
    game.enforce_mana_costs = True
    game.resolve_top_of_stack()
    game.enforce_mana_costs = False
    game.auto_resolve_pending_choices()
    assert counter.target_stack_item is not others["Shock"], game.log[-6:]
    assert any(counter.target_stack_item is item for item in others.values())


@pytest.mark.cr("115.7a")
def test_willbender_moves_an_ability_aimed_at_a_spell():
    """"…target spell **or ability** with a single target": Daring
    Apprentice's ability countering the Shock is moved onto the Bolt, the
    only other spell."""
    game = _table()
    ability, others = _ability_at_spell(game)
    _retarget(game, "Willbender", ability)
    resolve_stack(game)
    assert ability.target_stack_item is others["Lightning Bolt"], game.log[-8:]
    assert any(card.name == "Lightning Bolt" for card in game.players[1].graveyard)
    assert game.players[0].life == 18, game.log[-8:]


@pytest.mark.cr("115.7a", "608.2b")
def test_a_counterspell_aimed_at_the_deflection_itself_is_countered():
    """"You can choose to make a spell on the stack target this spell … This
    spell is still on the stack when new targets are selected for the spell."
    (Deflection, 2004-10-04.) With only the Shock and the Counterspell on the
    stack, the Deflection is the one other legal target — taken without a
    prompt (``choose_new_spell_target``'s single-candidate shortcut) — and
    once it has resolved the Counterspell's target is gone: every target
    illegal, it does nothing (CR 608.2b), and the Shock resolves."""
    game = _table()
    shock = _cast(game, 1, "Shock", target_player_index=0)
    counter = _cast(game, 0, "Counterspell", target_stack_index=_index_of(game, shock))
    deflection = _cast(game, 1, "Deflection", target_stack_index=_index_of(game, counter))
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.pending_choice_of("retarget_choice", 1) is None
    assert counter.target_stack_item is deflection, game.log[-6:]
    resolve_stack(game)
    assert any(card.name == "Counterspell" for card in game.players[0].graveyard)
    assert any(card.name == "Shock" for card in game.players[1].graveyard)
    assert game.players[0].life == 18, game.log[-8:]


@pytest.mark.cr("115.7a")
def test_a_seat_nobody_asks_re_aims_a_counterspell_on_the_side_its_effect_cuts():
    """A seat nobody asks takes the stated default: the side the re-aimed
    object's effect cuts (``_retarget_preferred_seats``) — a counterspell is
    harmful, so the chooser's opponent's spell, here P2's Bolt, ahead of the
    Deflection itself (``_retarget_option_seat`` reads a spell's
    controller)."""
    game = _table()
    shock = _cast(game, 0, "Shock", target_player_index=1)
    bolt = _cast(game, 1, "Lightning Bolt", target_player_index=0)
    counter = _cast(game, 1, "Counterspell", target_stack_index=_index_of(game, shock))
    game.interactive_seats = set()
    _cast(game, 0, "Deflection", target_stack_index=_index_of(game, counter))
    game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    assert counter.target_stack_item is bolt, game.log[-6:]


# --- the controls: the general CR 115.7 reader already counted a spell target


@pytest.mark.cr("115.7", "115.7a")
def test_psychic_battle_offers_a_counterspell_the_other_spells():
    game = _table()
    _put(game, 0, _C["Psychic Battle"])
    game.players[0].library = [_C["Shivan Dragon"]] * 5
    game.players[1].library = [_C["Island"]] * 5
    counter, others = _spell_at_spell(game)
    for _ in range(8):
        if game.pending_choice_of("retarget_choice", 0) is not None:
            break
        if not game.resolve_top_of_stack(pause_for_choices=True):
            game.auto_resolve_pending_choices()
    choice = game.pending_choice_of("retarget_choice", 0)
    assert choice is not None, game.log[-8:]
    offered = [o.get("_stack_item") for o in choice.data["options"] if o.get("kind") == "stack"]
    assert any(item is others["Lightning Bolt"] for item in offered), choice.data["options"]


@pytest.mark.cr("115.7")
def test_grip_of_chaos_reselects_a_counterspells_target_among_the_spells():
    moved = 0
    for seed in range(12):
        random.seed(seed)
        game = _table()
        game.interactive_seats = set()
        _put(game, 1, _C["Grip of Chaos"])
        shock = _cast(game, 1, "Shock", target_player_index=0)
        bolt = _cast(game, 1, "Lightning Bolt", target_player_index=0)
        # Grip's triggers for the two burn spells resolve first; then the
        # Counterspell is cast at the Shock and Grip reselects its target.
        while game.stack and game.stack[-1].is_ability:
            game.resolve_top_of_stack()
        counter = _cast(game, 0, "Counterspell", target_stack_index=_index_of(game, shock))
        while game.stack and game.stack[-1] is not counter:
            game.resolve_top_of_stack()
        assert any(counter.target_stack_item is item for item in (shock, bolt)), game.log[-4:]
        moved += counter.target_stack_item is bolt
    assert moved >= 1

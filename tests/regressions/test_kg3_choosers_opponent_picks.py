"""An unnamed "an opponent" who chooses is named by the controller (CR 601.7a
for a spell, 602.3a for an ability, 700.2e for a mode, 608.2d for a choice
made as the effect is applied): "If there is more than one opponent who could
make such a choice, the [spell's / ability's] controller decides which of
those opponents will make the choice."

Callous Oppressor and Wormfang Crab asked since Onslaught. A mode chosen by an
opponent (Fatal Lore, Library of Lat-Nam, Misfortune) and a target of an
opponent's choice (Cuombajj Witches, Echo Chamber, Nova Pentacle, Preacher) —
and, beside them, Infernal Denizen's "an opponent may gain control of a
creature you control of their choice", which the census's wording missed —
went to the first opponent. All now go through one seam,
``handlers/player_choices.ask_which_opponent``: the seats offered are the
opponents who could make the choice ("…target creature **they** control"
offers nothing to an opponent with no creature), an interactive controller
names one through the ``player_choice`` prompt, and a controller nobody asks
takes the first of them, the seat every such pick went to before.

The census reads every compiled step whose chooser is the unnamed opponent in
both manifest roles: each is a kind whose handler asks
(``_ASKING_KINDS``), so a new kind spending "an opponent" without naming one
fails. The boards drive each card at four seats with the controller
interactive and with it a default.

Validated backwards: on the tree before the fix every board here fails (the
mode, the damage and the pick were owed by seat 1 at once), and Echo
Chamber's gate refused the activation whose only creature-holding opponent
was not the first.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_creature_card, resolve_stack

#: The step kinds an unnamed "an opponent" chooses in, each of whose handlers
#: names the seat through ``ask_which_opponent`` — and the mode chooser, which
#: the cast path names (``_arm_opponent_mode_choice``).
_ASKING_KINDS = frozenset({
    "choose_permanent", "deal_damage_and_opponent_choice", "mode_chooser",
})
#: Rows when this was written: four picks, Cuombajj Witches, three modes.
_ROW_FLOOR = 8


def _walk(instructions):
    for instruction in instructions or ():
        if instruction is None:
            continue
        yield instruction
        payload = instruction.payload if isinstance(instruction.payload, dict) else {}
        for value in payload.values():
            if isinstance(value, (tuple, list)):
                for inner in value:
                    if hasattr(inner, "kind") and hasattr(inner, "payload"):
                        yield from _walk((inner,))
                    elif isinstance(inner, dict) and hasattr(inner.get("instruction"), "kind"):
                        yield from _walk((inner["instruction"],))
            elif hasattr(value, "kind") and hasattr(value, "payload"):
                yield from _walk((value,))


def _roots(program):
    yield from program.instructions
    for ability in program.activated_abilities:
        yield ability.instruction
    for trigger in program.triggered_abilities:
        yield trigger.instruction
    for mode in program.modes or ():
        yield mode.instruction


def test_every_unnamed_opponent_pick_is_a_kind_that_names_the_seat():
    pool: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        pool.setdefault(card.name, card)
    rows: list[tuple[str, str]] = []
    for name, card in sorted(pool.items()):
        program = compile_card_oracle(card)
        if program.mode_chooser == "opponent":
            rows.append((name, "mode_chooser"))
        for step in _walk(tuple(_roots(program))):
            payload = step.payload if isinstance(step.payload, dict) else {}
            if payload.get("chooser") == "opponent" or (
                step.kind == "deal_damage_and_opponent_choice"
            ):
                rows.append((name, step.kind))
    assert len(rows) >= _ROW_FLOOR, rows
    unasked = sorted({row for row in rows if row[1] not in _ASKING_KINDS})
    assert not unasked, unasked


# -- The boards -------------------------------------------------------------


def _table(catalog_by_name, *, interactive, creatures=(1, 2, 3)) -> Game:
    plains = catalog_by_name["Plains"]
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[plains] * 10) for seat in range(4)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2, 3} if interactive else set()
    game.active_player_index = 0
    for seat in range(4):
        if seat == 0 or seat in creatures:
            bear = Permanent(card=_mk_creature_card(f"Bear{seat}", 2, 2))
            game._put_permanent_onto_battlefield(seat, bear, None)
            bear.metadata["summoning_sickness_turn"] = -99
    resolve_stack(game)
    game.pending_choices.clear()
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    resolve_stack(game)
    return permanent


def _owed(game) -> list[tuple[str, int]]:
    return [(choice.kind, choice.player_index) for choice in game.pending_choices]


def _name_opponent(game, seat: int, *, offered) -> None:
    (choice,) = [c for c in game.pending_choices if c.kind == "player_choice"]
    assert choice.player_index == 0, _owed(game)
    assert list(choice.data["seats"]) == list(offered), choice.data
    assert game.confirm_player_choice(0, seat), game.log[-6:]


def _advance(game) -> None:
    for _ in range(4):
        if game.pending_choices or not game.stack:
            return
        game.resolve_top_of_stack()


def _bear(game, seat) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == f"Bear{seat}")


@pytest.mark.parametrize("name", ["Fatal Lore", "Library of Lat-Nam", "Misfortune"])
def test_the_caster_names_the_opponent_who_chooses_the_mode(catalog_by_name, name):
    game = _table(catalog_by_name, interactive=True)
    game.players[0].hand.insert(0, catalog_by_name[name])
    assert game.cast_from_hand(0, name).supported
    _name_opponent(game, 2, offered=[1, 2, 3])
    assert _owed(game) == [("opponent_mode_choice", 2)], game.log[-6:]


def test_misfortune_s_that_player_is_the_named_opponent(catalog_by_name):
    game = _table(catalog_by_name, interactive=True)
    game.players[0].hand.insert(0, catalog_by_name["Misfortune"])
    assert game.cast_from_hand(0, "Misfortune").supported
    _name_opponent(game, 3, offered=[1, 2, 3])
    assert game.resolve_pending_choice("opponent_mode_choice", 3, mode_index=1)
    resolve_stack(game)
    assert game.players[3].life == 16, game.log[-8:]
    assert [game.players[seat].life for seat in (0, 1, 2)] == [20, 20, 20]
    # "…a -1/-1 counter on each creature **that player** controls": the seat
    # the caster named, and nobody else's.
    assert int(_bear(game, 3).effective_toughness) == 1, game.log[-8:]
    assert int(_bear(game, 1).effective_toughness) == 2
    assert int(_bear(game, 2).effective_toughness) == 2


def test_a_default_caster_hands_the_mode_to_the_first_opponent(catalog_by_name):
    game = _table(catalog_by_name, interactive=False)
    game.interactive_seats = {1, 2, 3}
    game.players[0].hand.insert(0, catalog_by_name["Fatal Lore"])
    assert game.cast_from_hand(0, "Fatal Lore").supported
    assert _owed(game) == [("opponent_mode_choice", 1)], game.log[-6:]


def test_preacher_offers_only_the_opponents_with_a_creature(catalog_by_name):
    game = _table(catalog_by_name, interactive=True, creatures=(1, 3))
    preacher = _put(game, 0, catalog_by_name["Preacher"])
    result = game.activate_permanent_ability(0, "Preacher", ability_index=0)
    assert result.supported, result.details
    _advance(game)
    _name_opponent(game, 3, offered=[1, 3])
    assert _owed(game) == [("permanent_choice", 3)], game.log[-6:]
    (pick,) = game.pending_choices
    offered = {p.card.name for p in game.live_permanent_choices(pick)}
    assert offered == {"Bear3"}, offered
    assert game.resolve_pending_choice(
        "permanent_choice", 3, permanent_id=_bear(game, 3).permanent_id
    )
    resolve_stack(game)
    assert any(p.card.name == "Bear3" for p in game.controlled_by(0)), game.log[-6:]
    assert preacher.tapped


def test_echo_chamber_is_activatable_when_only_a_later_opponent_has_a_creature(
    catalog_by_name,
):
    game = _table(catalog_by_name, interactive=True, creatures=(3,))
    _put(game, 0, catalog_by_name["Echo Chamber"])
    result = game.activate_permanent_ability(0, "Echo Chamber", ability_index=0)
    assert result.supported, result.details
    _advance(game)
    # One opponent could choose, so nobody is asked which.
    assert _owed(game) == [("permanent_choice", 3)], game.log[-6:]


def test_echo_chamber_s_copy_is_of_the_named_opponent_s_creature(catalog_by_name):
    game = _table(catalog_by_name, interactive=True)
    _put(game, 0, catalog_by_name["Echo Chamber"])
    assert game.activate_permanent_ability(0, "Echo Chamber", ability_index=0).supported
    _advance(game)
    _name_opponent(game, 2, offered=[1, 2, 3])
    assert game.resolve_pending_choice(
        "permanent_choice", 2, permanent_id=_bear(game, 2).permanent_id
    )
    resolve_stack(game)
    copies = [p for p in game.controlled_by(0) if p.card.name == "Bear2"]
    assert len(copies) == 1, game.log[-6:]


def test_nova_pentacle_s_recipient_is_picked_by_the_named_opponent(catalog_by_name):
    game = _table(catalog_by_name, interactive=True)
    _put(game, 0, catalog_by_name["Nova Pentacle"])
    assert game.activate_permanent_ability(0, "Nova Pentacle", ability_index=0).supported
    _advance(game)
    _name_opponent(game, 3, offered=[1, 2, 3])
    assert [kind for kind, seat in _owed(game) if seat == 3] == ["permanent_choice"]


def test_cuombajj_witches_second_target_is_the_named_opponent_s(catalog_by_name):
    game = _table(catalog_by_name, interactive=True)
    _put(game, 0, catalog_by_name["Cuombajj Witches"])
    result = game.activate_permanent_ability(
        0, "Cuombajj Witches", ability_index=0,
        target_permanent_ids=[_bear(game, 1).permanent_id],
    )
    assert result.supported, result.details
    _advance(game)
    _name_opponent(game, 2, offered=[1, 2, 3])
    assert _owed(game) == [("opponent_damage", 2)], game.log[-6:]


def test_a_default_controller_names_the_first_opponent_who_could_choose(
    catalog_by_name,
):
    game = _table(catalog_by_name, interactive=False, creatures=(2, 3))
    game.interactive_seats = {1, 2, 3}
    _put(game, 0, catalog_by_name["Preacher"])
    assert game.activate_permanent_ability(0, "Preacher", ability_index=0).supported
    _advance(game)
    # Seat 1 controls no creature, so it could not choose; seat 2 is first.
    assert _owed(game) == [("permanent_choice", 2)], game.log[-6:]


def test_infernal_denizen_s_controller_names_the_opponent_who_may_take_one(
    catalog_by_name,
):
    game = _table(catalog_by_name, interactive=True)
    _put(game, 0, catalog_by_name["Infernal Denizen"])
    game.pending_choices.clear()
    game.start_turn(0)
    for _ in range(6):
        if any(c.kind == "player_choice" for c in game.pending_choices):
            break
        if not game.stack:
            break
        game.resolve_top_of_stack()
    _name_opponent(game, 2, offered=[1, 2, 3])
    assert [kind for kind, seat in _owed(game) if seat == 2] == ["permanent_choice"]

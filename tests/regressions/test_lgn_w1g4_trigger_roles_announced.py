"""A triggered ability printing two "target"s announces both (CR 603.3d).

Chromeshell Crab ("…you may exchange control of target creature you control
and target creature an opponent controls") and Goblin Grenadiers ("…destroy
target creature and target land") lower to a **roles** description, and the
trigger picker had no roles arm: both went on the stack naming nothing and
resolved against empty slots — the Crab's exchange "could not be completed",
the Grenadiers destroyed nothing however the sacrifice was answered. The
census in ``tests/engine/test_stack_targets.py`` pinned the Grenadiers as "no
picker derived" and would have named the Crab the day Legions was measured.

Every supported trigger with a roles spec is asserted to announce on a board
that has a candidate for each role (a census with a floor), and the
Grenadiers is driven through a real unblocked attack, default and
interactive.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_instruction_spec
from tests.helpers import declare_attack


def _cards():
    found = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            found.setdefault(card.name, card)
    return found


_CARDS = _cards()


def _table(mine, theirs, *, interactive=False):
    game = Game(players=[PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)])
    game.interactive_seats = {0} if interactive else set()
    game.enforce_mana_costs = False
    game.start_turn(0)
    placed = []
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.append(permanent)
    return game, placed


def test_every_supported_roles_trigger_announces_its_roles():
    """Census, both manifest roles: each supported trigger whose target spec
    is a roles spec, enqueued from its source on a board holding a creature
    and a land on each side, goes on the stack with one target per role."""
    examined = 0
    for card in _CARDS.values():
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trig in program.triggered_abilities:
            if not trig.supported or trig.instruction is None:
                continue
            spec = derive_instruction_spec([trig.instruction])
            if not spec or spec.get("kind") != "roles":
                continue
            game, placed = _table(
                [card.name, "Grizzly Bears", "Forest"], ["Hill Giant", "Island"],
            )
            game._enqueue_triggered_ability(
                controller_index=0, source_permanent=placed[0],
                instruction=trig.instruction, effect_kind=trig.effect_kind,
                ability_text=trig.source_line,
            )
            (item,) = game.stack
            assert isinstance(item.target_permanent_id, list), card.name
            assert len(item.target_permanent_id) == len(spec["roles"]), card.name
            examined += 1
    assert examined >= 2, examined


def _unblocked_grenadiers(*, interactive):
    game, placed = _table(
        ["Goblin Grenadiers", "Mountain"], ["Hill Giant", "Forest", "Island"],
        interactive=interactive,
    )
    declare_attack(game, 0, blocks={})
    game.advance_combat_phase()
    return game, placed


def test_goblin_grenadiers_default_aims_at_the_opponent():
    """A seat nobody asks names the opponent's creature and land — never the
    Grenadiers itself, which it is about to sacrifice."""
    game, _placed = _unblocked_grenadiers(interactive=False)
    # With no interactive seat the combat runs on through the trigger's
    # resolution; the announcement is in the log as it was made.
    assert "Goblin Grenadiers: targets Hill Giant, Forest" in game.log


def test_goblin_grenadiers_interactive_destroys_what_it_names():
    """An interactive seat is offered each role's candidates, answers one per
    role in order, accepts the sacrifice, and both are destroyed."""
    game, placed = _unblocked_grenadiers(interactive=True)
    grenadiers, giant, island = placed[0], placed[2], placed[4]
    (choice,) = game.pending_choices
    assert choice.kind == "trigger_target"
    assert [role["kind"] for role in choice.data["roles"]] == ["creature", "land"]
    assert not game.resolve_pending_choice(
        "trigger_target", 0, permanent_ids=[island.permanent_id, giant.permanent_id],
    ), "the land is not a candidate for the creature role"
    assert game.resolve_pending_choice(
        "trigger_target", 0, permanent_ids=[giant.permanent_id, island.permanent_id],
    )
    for _ in range(10):
        if game.pending_choices:
            (offer,) = game.pending_choices
            assert offer.kind == "optional_pay"
            assert game.resolve_pending_choice("optional_pay", 0, accept=True)
            continue
        if not game.stack:
            break
        game.resolve_top_of_stack()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(grenadiers)
    assert not game.is_on_battlefield(giant)
    assert not game.is_on_battlefield(island)
    assert [p.card.name for p in game.controlled_by(1)] == ["Forest"]

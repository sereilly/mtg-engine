"""The player a trigger is about rides its own field, never its target's.

``StackItem.target_player_index`` held two meanings: the seat a player chose
(or the battlefield a chosen permanent stood on), and the seat a trigger's
firing event named for "that player" — whose upkeep it is, who caused the
discard, whom the attack was at, the seat a delayed ability is bound to, the
controller of an attachment or an unblocked attacker whose ability it is. kg
split the permanent half (``about_permanent_id``) and gated the discard site's
stamp (``trigger_utils.bound_event_seat``); the other stamps were right only
because no line beside them printed a player target, which the trigger picker
would have read as a choice already made (CR 603.3d).

Now every such seat rides ``StackItem.about_player_index``, and the context
builder hands it to the effect where nothing chose a seat — the way it hands
``about_permanent_id``. The census drives one board per fire site and holds
the invariant at the push: no triggered ability is put on the stack with a seat
in ``target_player_index`` that nobody chose. Validated backwards (the stamp
put back where it was, the census names every site), with a floor on the sites
it reached. Each board also reads the outcome: the seat the event named is the
one the effect reached.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_card, _nosick, resolve_stack

#: The fire sites a seat is stamped at, by the function that builds the
#: object (``_stack_push``'s caller, or ``_enqueue_triggered_ability``'s).
_SITES = (
    "upkeep", "discard", "unblocked", "one_or_more_attack", "attached_attack",
    "delayed",
)


class _Spy:
    """Every triggered object put on the stack: what its fire site wrote into
    the two seat fields before the push touched it, and whether anything was
    chosen for it."""

    def __init__(self, monkeypatch, *, put_back: bool = False):
        self.pushed: list[tuple] = []
        spy = self
        original = Game._stack_push

        def recording(game, item, *args, **kwargs):
            if item.is_ability and not item.activated:
                if put_back and getattr(item, "about_player_index", None) is not None:
                    # The base tree's channel: the event's seat in the target
                    # field, and nothing in its own.
                    item.target_player_index = item.about_player_index
                    item.about_player_index = None
                spy.pushed.append((
                    item.card.name, item.target_player_index,
                    getattr(item, "about_player_index", None),
                    bool(kwargs.get("announced_at_cast")) or item.targets_chosen,
                ))
            return original(game, item, *args, **kwargs)

        monkeypatch.setattr(Game, "_stack_push", recording)

    def stamped(self, name: str) -> list[tuple]:
        """Pushes of *name* whose target seat nobody chose."""
        return [
            row for row in self.pushed
            if row[0] == name and row[1] is not None and not row[3]
        ]

    def about(self, name: str) -> list:
        return [row[2] for row in self.pushed if row[0] == name]


def _game(*players: PlayerState) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    return game


def _put(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return _nosick(permanent)


def _library(pool) -> list:
    return [pool["Forest"]] * 10


# -- the boards, one per fire site -------------------------------------------


def _upkeep(pool) -> tuple[Game, str, int]:
    """"At the beginning of the upkeep of enchanted artifact's controller,
    this Aura deals 2 damage to that player unless that player sacrifices that
    artifact." (Curse Artifact.) On its own controller's artifact, so "that
    player" is the controller — the seat the default opposing seat is not.
    (Feedback's damage is dealt inline by the upkeep registry and never goes
    on the stack; this one does.)"""
    game = _game(
        PlayerState("P1", life=20, library=_library(pool), hand=[pool["Curse Artifact"]]),
        PlayerState("P2", life=20, library=_library(pool)),
    )
    ring = _put(game, 0, pool["Sol Ring"])
    assert game.cast_from_hand(
        0, "Curse Artifact", target_permanent_ids=[ring.permanent_id],
    ).supported
    resolve_stack(game)
    game.active_player_index = 0
    game.resolve_upkeep(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return game, "Curse Artifact", 0


def _discard(pool) -> tuple[Game, str, int]:
    """"When a spell or ability an opponent controls causes you to discard
    this card, that player loses 5 life." (Psychic Purge.)"""
    game = _game(
        PlayerState("P1", life=20, library=_library(pool),
                    hand=[pool["Psychic Purge"], pool["Forest"]]),
        PlayerState("P2", life=20, library=_library(pool), hand=[pool["Coercion"]]),
    )
    assert game.queue_from_hand(1, "Coercion", target_player_index=0).supported
    for _ in range(4):
        resolve_stack(game)
        game.auto_resolve_pending_choices()
    return game, "Psychic Purge", 1


def _combat(game: Game, attacker: Permanent, *, blocked_by: Permanent | None = None) -> None:
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [game.battlefield_index_of(attacker)])[0], game.log[-3:]
    resolve_stack(game)
    if game.current_step != "declare_blockers":
        game.advance_combat_phase()
    blocks = {}
    if blocked_by is not None:
        blocks = {game.battlefield_index_of(blocked_by): game.battlefield_index_of(attacker)}
    assert game.declare_blockers(1, blocks)[0], game.log[-3:]
    resolve_stack(game)
    game.advance_combat_phase()
    resolve_stack(game)


_SUBJECT = _mk_card(name="About Bear", type_line="Creature - Bear", power=2, toughness=2)


def _unblocked(pool) -> tuple[Game, str, int]:
    """"Whenever this creature attacks and isn't blocked, you gain 2 life."
    (Merchant Ship.) The attacker's own ability, about its controller's seat —
    which is the seat the life goes to: the effect resolves at the seat the
    event named, and the default opposing seat would have gained it."""
    game = _game(
        PlayerState("P1", life=20, library=_library(pool)),
        PlayerState("P2", life=20, library=_library(pool)),
    )
    # It attacks only into an Island, and is sacrificed without one of its own.
    _put(game, 0, pool["Island"])
    _put(game, 1, pool["Island"])
    ship = _put(game, 0, pool["Merchant Ship"])
    _combat(game, ship)
    return game, "Merchant Ship", 0


def _one_or_more_attack(pool) -> tuple[Game, str, int]:
    """"Whenever one or more creatures you control attack, …" — the seat the
    attack is at."""
    name = _ONE_OR_MORE_ATTACK
    game = _game(
        PlayerState("P1", life=20, library=_library(pool)),
        PlayerState("P2", life=20, library=_library(pool)),
    )
    _put(game, 0, pool[name])
    bear = _put(game, 0, _SUBJECT)
    _combat(game, bear)
    return game, name, 1


def _attached_attack(pool) -> tuple[Game, str, int]:
    """"Whenever enchanted creature attacks or blocks, …" — an Aura's ability
    on its host's attack, stamped with the Aura's controller."""
    name = _ATTACHED_ATTACK
    game = _game(
        PlayerState("P1", life=20, library=_library(pool)),
        PlayerState("P2", life=20, library=_library(pool), hand=[pool[name]]),
    )
    bear = _put(game, 0, _SUBJECT)
    assert game.cast_from_hand(1, name, target_permanent_ids=[bear.permanent_id]).supported
    resolve_stack(game)
    _combat(game, bear)
    return game, name, 1


def _delayed(pool) -> tuple[Game, str, int]:
    """"Target player draws a card at the beginning of the next turn's
    upkeep." (Sapphire Charm.) Aimed at its caster: the delayed ability is
    bound to that seat (CR 603.7c), the one the default opposing seat is not."""
    game = _game(
        PlayerState("P1", life=20, library=_library(pool), hand=[pool["Sapphire Charm"]]),
        PlayerState("P2", life=20, library=_library(pool)),
    )
    assert game.queue_from_hand(
        0, "Sapphire Charm", mode_index=0, target_player_index=0,
    ).supported
    resolve_stack(game)
    game.resolve_upkeep(1)
    resolve_stack(game)
    return game, "Sapphire Charm", 0


#: Two cards found by name for their condition (see the boards' docstrings).
_ONE_OR_MORE_ATTACK = "Raging River"
_ATTACHED_ATTACK = "Imprison"

_BOARDS = {
    "upkeep": _upkeep,
    "discard": _discard,
    "unblocked": _unblocked,
    "one_or_more_attack": _one_or_more_attack,
    "attached_attack": _attached_attack,
    "delayed": _delayed,
}


def _drive(pool, monkeypatch, *, put_back=False) -> tuple[dict, list[str]]:
    reached: dict[str, list] = {}
    findings: list[str] = []
    for site in _SITES:
        spy = _Spy(monkeypatch, put_back=put_back)
        _game, name, seat = _BOARDS[site](pool)
        reached[site] = spy.about(name)
        stamped = spy.stamped(name)
        if stamped:
            findings.append(f"{site}: {name} pushed with an unchosen target seat {stamped}")
        if seat not in spy.about(name) and not put_back:
            findings.append(f"{site}: {name} is not about seat {seat}: {spy.pushed}")
    return reached, findings


@pytest.mark.cr("603.3d", "115.10a", "603.2")
def test_every_seat_stamp_rides_about_player_index(catalog_by_name, monkeypatch):
    reached, findings = _drive(catalog_by_name, monkeypatch)
    assert findings == [], findings
    # A floor: every site put its trigger on the stack at least once.
    assert all(reached[site] for site in _SITES), reached


@pytest.mark.cr("603.3d")
def test_the_census_goes_red_with_the_stamp_put_back(catalog_by_name, monkeypatch):
    _reached, findings = _drive(catalog_by_name, monkeypatch, put_back=True)
    named = {line.split(":")[0] for line in findings}
    assert named == set(_SITES), findings


@pytest.mark.cr("603.2")
def test_curse_artifact_on_its_own_controllers_artifact_charges_that_player(catalog_by_name):
    game, _name, seat = _upkeep(catalog_by_name)
    ring_kept = any(p.card.name == "Sol Ring" for p in game.controlled_by(seat))
    assert game.players[seat].life == (18 if ring_kept else 20), game.log[-6:]
    assert game.players[seat].life == 18 or not ring_kept, game.log[-6:]
    assert game.players[1 - seat].life == 20, game.log[-6:]


@pytest.mark.cr("603.7c")
def test_a_delayed_draw_bound_to_its_caster_draws_for_its_caster(catalog_by_name):
    game, _name, seat = _delayed(catalog_by_name)
    assert len(game.players[seat].hand) == 1, game.log[-6:]
    assert len(game.players[1 - seat].hand) == 0, game.log[-6:]


@pytest.mark.cr("603.2")
def test_psychic_purge_charges_the_player_who_caused_the_discard(catalog_by_name):
    game, _name, seat = _discard(catalog_by_name)
    assert game.players[seat].life == 15, game.log[-6:]
    assert game.players[1 - seat].life == 20, game.log[-6:]


@pytest.mark.cr("603.2")
def test_merchant_ship_unblocked_gains_its_controller_the_life(catalog_by_name):
    game, _name, seat = _unblocked(catalog_by_name)
    assert game.players[seat].life == 22, game.log[-8:]
    assert game.players[1 - seat].life == 20 - 0, game.log[-8:]

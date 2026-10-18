"""A delayed ability's "that player" is the player its creating effect named.

CR 603.7a: a delayed triggered ability is created during the resolution of a
spell or ability, and CR 603.7c: one "that refers to a particular object still
affects it". The same holds of a player the creating effect was about — its
target, the owner of the graveyard it reached into, the seat an offer was put
to: that is who the words name when the ability finally resolves, a step or a
turn later.

The engine froze that seat only where a record said to (a chosen opponent, a
damaged player, a targeted player whose *turn* the event names). Every other
entry was left unbound, and an unbound trigger's target is the seat opposite
its controller. So the three cards in the pool whose delayed effect is about
the resolution's own player were right exactly when that player was the
opponent:

* **Lodestone Bauble** — "…from a player's graveyard on top of their library.
  That player draws a card at the beginning of the next turn's upkeep." Aimed
  at its controller's own graveyard, the opponent drew (Phase 5).
* **Sapphire Charm** — "Target player draws a card at the beginning of the
  next turn's upkeep." Aimed at oneself, the opponent drew.
* **Horn of Plenty** — "Whenever a player casts a spell, that player may pay
  {1}. If the player does, they draw a card at the beginning of the next end
  step." The other player drew the card that was paid for.

Census over the pool's 173 delayed triggers, both manifest roles: four have an
effect that is about the resolution's target player, and three of the four
named the wrong seat whenever it was the controller's own
(``test_every_delayed_effect_about_a_player_names_the_player_it_was_made_about``).
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.handlers.registry import EFFECT_HANDLERS
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

#: Floors, because a sweep that reaches nothing passes. 173 delayed triggers
#: on the day, four of them about the resolution's target player.
_MIN_DELAYED = 150
_MIN_ABOUT_A_PLAYER = 4


def _basic(name: str):
    return _mk_card(name=name, type_line=f"Basic Land — {name}")


def _duel(*, library=6) -> tuple[Game, PlayerState, PlayerState]:
    filler = _mk_card(name="Deck", type_line="Artifact")
    me = PlayerState(name="P0", life=20, library=[filler] * library)
    you = PlayerState(name="P1", life=20, library=[filler] * library)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    return game, me, you


def _ready(card) -> Permanent:
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


# -- Lodestone Bauble ---------------------------------------------------------

@pytest.mark.cr("603.7c", "603.7a")
@pytest.mark.parametrize("owner", [0, 1])
def test_603_7c_the_graveyards_owner_draws_at_the_next_turns_upkeep(set_pool, owner):
    """Whichever graveyard the cards came out of, its owner is "that player"
    — and the next turn's upkeep is the *other* player's whichever it is."""
    game, me, you = _duel()
    me.battlefield.append(_ready(set_pool("ALL")["Lodestone Bauble"]))
    pile = game.players[owner]
    pile.graveyard = [_basic("Mountain"), _mk_card(name="Black Lotus", type_line="Artifact")]

    assert game.activate_permanent_ability(
        0, "Lodestone Bauble", target_player_index=owner,
        target_permanent_index=[0],
    ).supported
    game._settle()
    assert [card.name for card in pile.library][:1] == ["Mountain"]

    hands = [len(me.hand), len(you.hand)]
    # The next turn is the opponent's: its upkeep is "the next turn's upkeep".
    game.resolve_upkeep(1)
    resolve_stack(game)

    drew = [len(me.hand) - hands[0], len(you.hand) - hands[1]]
    assert drew == [1 if owner == 0 else 0, 1 if owner == 1 else 0], game.log[-6:]
    assert [card.name for card in pile.hand][-1:] == ["Mountain"]


# -- Sapphire Charm -----------------------------------------------------------

@pytest.mark.cr("603.7c")
@pytest.mark.parametrize("named", [0, 1])
def test_603_7c_the_targeted_player_draws_at_the_next_turns_upkeep(set_pool, named):
    game, me, you = _duel()
    charm = set_pool("MIR")["Sapphire Charm"]
    me.hand = [charm]

    assert game.queue_from_hand(
        0, "Sapphire Charm", mode_index=0, target_player_index=named,
    ).supported
    resolve_stack(game)

    hands = [len(me.hand), len(you.hand)]
    game.resolve_upkeep(1)
    resolve_stack(game)

    drew = [len(me.hand) - hands[0], len(you.hand) - hands[1]]
    assert drew == [1 if named == 0 else 0, 1 if named == 1 else 0], game.log[-6:]


# -- The pool -----------------------------------------------------------------

def _walk(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _fresh(card, catalog_by_name):
    def seat(name):
        player = PlayerState(
            name=name, life=20, library=[catalog_by_name["Forest"]] * 12,
            hand=[catalog_by_name["Swamp"]] * 3,
            graveyard=[catalog_by_name["Plains"]] * 3,
        )
        player.battlefield.append(_ready(catalog_by_name["Grizzly Bears"]))
        return player

    game = Game(players=[seat("P0"), seat("P1")])
    game.enforce_mana_costs = False
    source = None
    type_line = (card.type_line or "").lower()
    if "instant" not in type_line and "sorcery" not in type_line:
        source = Permanent(card=card)
        game.players[0].battlefield.append(source)
    return game, source


def _state(game):
    return tuple(
        (p.life, len(p.hand), len(p.library), len(p.graveyard)) for p in game.players
    )


def _is_about_the_target_player(card, effect, catalog_by_name) -> bool:
    """Whether running *effect* with the target seat swapped changes who it
    happens to."""
    outcomes = []
    for target in (0, 1):
        game, source = _fresh(card, catalog_by_name)
        before = _state(game)
        try:
            game._execute_oracle_instruction(effect, OracleExecutionContext(
                caster=game.players[0], target=game.players[target], card=card,
                source_permanent=source, trigger_context={},
            ))
            game.auto_resolve_pending_choices()
        except Exception:  # noqa: BLE001 - an effect that needs its event
            return False
        after = _state(game)
        outcomes.append(tuple(
            tuple(now - then for now, then in zip(after[i], before[i]))
            for i in range(2)
        ))
    return outcomes[0] != outcomes[1]


def _seat_named(card, step, target: int, catalog_by_name):
    """The seat the fired ability names, armed by a resolution about *target*."""
    game, source = _fresh(card, catalog_by_name)
    bear = next(
        p for p in game.players[target].battlefield if p.card.name == "Grizzly Bears"
    )
    EFFECT_HANDLERS["create_delayed_trigger"](game, step, OracleExecutionContext(
        caster=game.players[0], target=game.players[target], card=card,
        source_permanent=source, trigger_context={},
        target_permanent_id=bear.permanent_id,
        results={"chosen_player": target},
    ))
    if not game.delayed_triggers:
        return None
    entry = game.delayed_triggers[-1]
    named = entry.trigger_event()["target_player_index"]
    return game._default_opposing_seat(entry.controller_index) if named is None else named


@pytest.mark.cr("603.7c")
def test_every_delayed_effect_about_a_player_names_the_player_it_was_made_about(
    catalog_by_name,
):
    pool = load_cards(manifest_set_paths(include_measured=True))
    delayed = 0
    about_a_player: list[str] = []
    wrong: list[str] = []
    for unit in compilation_units(pool):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [ability.instruction for ability in program.activated_abilities]
        roots += [trigger.instruction for trigger in program.triggered_abilities]
        seen: set[str] = set()
        for root in roots:
            for step in _walk(root):
                if step.kind != "create_delayed_trigger" or repr(step) in seen:
                    continue
                seen.add(repr(step))
                delayed += 1
                effect = step.payload.get("instruction")
                if effect is None or not _is_about_the_target_player(
                    unit, effect, catalog_by_name
                ):
                    continue
                about_a_player.append(unit.name)
                for target in (0, 1):
                    named = _seat_named(unit, step, target, catalog_by_name)
                    if named != target:
                        wrong.append(f"{unit.name}: made about seat {target}, names {named}")

    assert delayed >= _MIN_DELAYED, delayed
    assert len(about_a_player) >= _MIN_ABOUT_A_PLAYER, about_a_player
    assert not wrong, wrong

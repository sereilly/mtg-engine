"""Tithe searches once and shuffles once (CR 701.23h).

"Search your library for a Plains card. If target opponent controls more lands
than you, you may search your library for an additional Plains card. Reveal
those cards, put them into your hand, then shuffle." CR 701.23h: a player told
to search a library more than once before being told to shuffle searches it
once, so the library is shuffled once. The flow asks two prompts (the second
find exists only if the condition holds and its controller wants it), and each
prompt's answer used to shuffle as it was given: both finds made two
library-shuffled events, and Psychogenic Probe ("Whenever a spell or ability
causes a player to shuffle their library, this artifact deals 2 damage to that
player.") dealt 4 (Mirrodin W2G4's census named it; see
``test_mrd_w2g4_one_printed_shuffle.py``).

Now each search is lowered ``no_shuffle`` and the printed "then shuffle" is one
``shuffle_library`` step behind both; the search flow's end-of-search shuffles
all go through ``shuffle_after_search``, which honours the flag. Tithe is the
only effect in either manifest role that searches one library twice before one
shuffle (the census below).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _table(set_pool, *, opponent_lands: int, plains: int = 2):
    lea = set_pool("LEA")
    library = [lea["Plains"]] * plains + [lea["Island"]] * 4
    game = Game(players=[
        PlayerState(name="P0", life=20, library=list(library), hand=[set_pool("VIS")["Tithe"]]),
        PlayerState(
            name="P1", life=20, library=[lea["Island"]] * 6,
            battlefield=[Permanent(card=lea["Mountain"]) for _ in range(opponent_lands)],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._put_permanent_onto_battlefield(
        1, Permanent(card=set_pool("MRD")["Psychogenic Probe"]), None
    )
    game._settle()
    shuffles: list[int] = []
    original = game.shuffle_library_of

    def counting(player, *, below=0):
        shuffles.append(game.players.index(player))
        return original(player, below=below)

    game.shuffle_library_of = counting
    return game, shuffles


def _play(game, *, take_the_offer: bool) -> list[str]:
    assert game.cast_from_hand(0, "Tithe", target_player_index=1).supported
    game.resolve_stack()
    for _ in range(8):
        if not game.pending_choices:
            break
        pending = game.pending_choices[0]
        if pending.kind == "search_library":
            index = next(
                (i for i, card in enumerate(game.players[0].library) if card.name == "Plains"),
                None,
            )
            if index is None:
                game.decline_search_library(0)
            else:
                game.confirm_search_library(0, index)
        else:
            game.resolve_pending_choice(pending.kind, 0, accept=take_the_offer)
        game.resolve_stack()
    game.resolve_stack()
    assert not game.pending_choices and not game.stack, game.log[-6:]
    return [card.name for card in game.players[0].hand]


@pytest.mark.parametrize(
    ("opponent_lands", "take_the_offer", "plains", "found"),
    [
        # Both finds: the case the entry names.
        (2, True, 2, ["Plains", "Plains"]),
        # The second search offered and declined.
        (2, False, 2, ["Plains"]),
        # The condition false: no second offer at all.
        (0, True, 2, ["Plains"]),
        # Nothing to find: the library was still searched, so still shuffled.
        (2, True, 0, []),
    ],
)
def test_tithe_shuffles_its_library_once_however_many_searches_run(
    set_pool, opponent_lands, take_the_offer, plains, found,
):
    game, shuffles = _table(set_pool, opponent_lands=opponent_lands, plains=plains)
    assert _play(game, take_the_offer=take_the_offer) == found
    assert shuffles == [0], game.log
    # Psychogenic Probe heard one shuffle: 2 damage, not 4.
    assert game.players[0].life == 18, game.log
    assert len(game.players[0].library) == plains + 4 - len(found)


def _children(instruction):
    for value in instruction.payload.values():
        items = value if isinstance(value, tuple) else (value,)
        for item in items:
            if hasattr(item, "kind") and hasattr(item, "payload"):
                yield item


def _searches_on_one_road(instruction) -> int:
    """How many library searches one resolution can run: an ``if_then``'s two
    arms are exclusive ("If this spell was kicked, instead search…", Primal
    Growth, Far Wanderings), everything else runs in sequence."""
    if instruction.kind == "search_library":
        return 1
    if instruction.kind == "if_then":
        return max(
            sum(_searches_on_one_road(step) for step in instruction.payload.get(arm) or ())
            for arm in ("then", "else")
        )
    return sum(_searches_on_one_road(child) for child in _children(instruction))


def _walk(instruction):
    yield instruction
    for child in _children(instruction):
        yield from _walk(child)


def test_an_effect_that_searches_twice_before_its_shuffle_shuffles_once():
    """Every compiled effect in the pool that can run two library searches in
    one resolution: each of them ends without its own shuffle and one
    ``shuffle_library`` stands behind them (CR 701.23h). Tithe is the pool's
    one such effect today; an arriving card printing the shape is held to the
    same reading."""
    examined = 0
    twice = {}
    for unit in compilation_units(load_catalog()):
        program = compile_card_oracle(unit)
        roots = list(program.instructions) + [
            ability.instruction for ability in program.triggered_abilities
            if ability.instruction is not None
        ] + [
            ability.instruction for ability in program.activated_abilities
            if getattr(ability, "instruction", None) is not None
        ]
        for root in roots:
            examined += 1
            if _searches_on_one_road(root) >= 2:
                steps = list(_walk(root))
                twice[unit.name] = (
                    [bool(step.payload.get("no_shuffle")) for step in steps if step.kind == "search_library"],
                    [step.kind for step in steps].count("shuffle_library"),
                )
    assert examined >= 3000, examined
    assert "Tithe" in twice, "the census no longer sees the shape it is about"
    wrong = {
        name: shape for name, shape in twice.items()
        if not all(shape[0]) or shape[1] != 1
    }
    assert wrong == {}, wrong

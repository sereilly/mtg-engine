"""A graveyard target is read off its stamp; the slot channel never means a
graveyard slot.

kg4 / ``ids`` part 2. A card in a graveyard has no ``permanent_id``, so a
graveyard target is identified by a ``GraveyardTarget`` stamp
(``StackItem.target_graveyard_card``), recorded as the object is pushed. The
resolution then wrote the stamp *back into* ``target_permanent_index`` as a
graveyard slot — so the one field meant a battlefield slot on one object and a
graveyard slot on the next, and every reader had to know which object it was
looking at. A trigger's graveyard answer and a CR 115.7 change wrote a
graveyard slot there too, and a role scope handed one on.

Now the push consumes the announcement's slot into the stamp and clears the
slot channel, and every graveyard handler reads where the stamped card sits
*now* (``handlers/_targets.chosen_graveyard_slots`` →
``Game.chosen_graveyard_index``). These tests hold the static invariant (no
graveyard location is written into the slot channel anywhere in ``engine/``,
with a floor on what was read) and drive the three roads — a spell, an Aura
spell, an entry trigger — across a renumbering of the pile.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from engine import Game, PlayerState
from engine.faces import compilation_units
from tests.helpers import resolve_stack

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_LOCATORS = {"graveyard_index_of", "chosen_graveyard_index"}


@pytest.fixture(scope="module")
def cards(catalog):
    pool: dict = {}
    for unit in compilation_units(catalog):
        pool.setdefault(unit.name, unit)
    return pool


# ---------------------------------------------------------------------------
# Static census
# ---------------------------------------------------------------------------


def _calls_a_locator(node) -> bool:
    return any(
        isinstance(sub, ast.Call)
        and (getattr(sub.func, "attr", None) or getattr(sub.func, "id", None)) in _LOCATORS
        for sub in ast.walk(node)
    )


def _graveyard_slots_written_to_the_slot_channel():
    """Each write of a graveyard location into ``target_permanent_index`` —
    an assignment or a keyword whose value calls a locator, or names a local
    the same function assigned from one — and how many functions were read."""
    found, functions = [], 0
    for path in sorted((_ROOT / "engine").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "target_permanent_index" not in text:
            continue
        for function in ast.walk(ast.parse(text)):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            functions += 1
            tainted = {
                target.id
                for node in ast.walk(function) if isinstance(node, ast.Assign)
                and _calls_a_locator(node.value)
                for target in node.targets if isinstance(target, ast.Name)
            }

            def carries(value) -> bool:
                return _calls_a_locator(value) or any(
                    isinstance(sub, ast.Name) and sub.id in tainted
                    for sub in ast.walk(value)
                )

            for node in ast.walk(function):
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Attribute) and t.attr == "target_permanent_index"
                    for t in node.targets
                ) and carries(node.value):
                    found.append(f"{path.relative_to(_ROOT)}:{node.lineno}")
                if isinstance(node, ast.keyword) and node.arg == "target_permanent_index" \
                        and carries(node.value):
                    found.append(f"{path.relative_to(_ROOT)}:{node.value.lineno}")
    return found, functions


def test_no_graveyard_location_is_written_into_the_slot_channel():
    found, functions = _graveyard_slots_written_to_the_slot_channel()
    assert functions >= 100, f"the census read only {functions} functions"
    assert not found, "graveyard slots written into the slot channel: " + ", ".join(found)


# ---------------------------------------------------------------------------
# Driven: a spell, an Aura spell, an entry trigger
# ---------------------------------------------------------------------------


def _table(cards, hand, yard):
    p1 = PlayerState(name="P1", hand=[cards[name] for name in hand],
                     graveyard=[cards[name] for name in yard],
                     library=[cards["Island"]] * 10)
    p2 = PlayerState(name="P2", library=[cards["Island"]] * 10)
    return Game(players=[p1, p2])


def _renumber(game, seat, name):
    """Take *name* out of *seat*'s graveyard (into exile), so every card above
    it slides down a slot — the response that makes a slot name another card."""
    player = game.players[seat]
    card = next(card for card in player.graveyard if card.name == name)
    player.graveyard.remove(card)
    game.put_card_into_exile(player, card)


def _stamped(item):
    stamps = item.target_graveyard_card
    stamps = stamps if isinstance(stamps, list) else [stamps]
    return [stamp.card.name for stamp in stamps if stamp is not None]


def test_a_graveyard_spell_carries_its_card_as_a_stamp_and_returns_it(cards):
    """Raise Dead naming slot 1 (the Hill Giant, above a Grizzly Bears): on the
    stack the slot channel is empty and the stamp is the Giant; the Bears
    leaves in response, and the Giant — now in slot 0 — is what comes back."""
    game = _table(cards, ["Raise Dead"], ["Grizzly Bears", "Hill Giant"])
    assert game.queue_from_hand(
        0, "Raise Dead", target_player_index=0, target_permanent_index=1,
    ).supported
    item = game.stack[-1]
    assert item.target_permanent_index is None
    assert _stamped(item) == ["Hill Giant"]
    _renumber(game, 0, "Grizzly Bears")
    resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Hill Giant"]


def test_an_aura_reanimates_the_card_it_stamped(cards):
    """Animate Dead (CR 303.4a's one target, a card in a graveyard): the card
    it names is read off the stamp as the Aura's entry runs, not off a slot."""
    game = _table(cards, ["Animate Dead"], ["Grizzly Bears", "Hill Giant"])
    assert game.queue_from_hand(
        0, "Animate Dead", target_player_index=0, target_permanent_index=1,
    ).supported
    item = game.stack[-1]
    assert item.target_permanent_index is None
    assert _stamped(item) == ["Hill Giant"]
    _renumber(game, 0, "Grizzly Bears")
    resolve_stack(game)
    names = [perm.card.name for perm in game.controlled_by(0)]
    assert "Hill Giant" in names and "Grizzly Bears" not in names


def test_an_entry_trigger_returns_the_card_it_stamped(cards):
    """Gravedigger's "you may return target creature card from your graveyard
    to your hand", named as the creature is cast: the trigger on the stack
    holds the card's stamp and no slot, and — its controller saying yes —
    returns that card after the pile renumbers."""
    game = _table(cards, ["Gravedigger"], ["Grizzly Bears", "Hill Giant"])
    game.interactive_seats = {0}
    assert game.queue_from_hand(
        0, "Gravedigger", target_player_index=0, target_permanent_index=1,
    ).supported
    game.resolve_top_of_stack()
    trigger = next(
        (obj for obj in game.stack if obj.card.name == "Gravedigger" and obj.is_ability),
        None,
    )
    assert trigger is not None, game.log[-5:]
    assert trigger.target_permanent_index is None
    assert _stamped(trigger) == ["Hill Giant"]
    _renumber(game, 0, "Grizzly Bears")
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, "Gravedigger", accept=True)
    assert [card.name for card in game.players[0].hand] == ["Hill Giant"]

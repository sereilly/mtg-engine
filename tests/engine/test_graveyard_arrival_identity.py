"""Guard: no graveyard ever holds one object twice, and nothing reaches a
graveyard around the one arrival that keeps it so.

``Game.put_card_into_graveyard`` was already the graveyard's one road in
(``test_graveyard_seam.py`` bans the literal ``.graveyard.append``), but it
appended the object it was handed — and a deck repeats one immutable
``CardDefinition`` per copy, with the catalog shared between seats, so two
copies of a card in one graveyard were **one object at two positions**. Every
record about a card in a graveyard names its object, and each one answered for
whichever copy came first: "put there from the battlefield this turn" (No Rest
for the Wicked, Second Sunrise), a ``GraveyardTarget``'s stamp, CR 613.7d's
arrival stamps, a granted flashback (Recoup), "that card" on a dies trigger.
An old Grizzly Bears and one Bolted this turn were one object, so Raise Dead
returning the new one left No Rest for the Wicked a Bears to return.

Exile's rule (``test_exile_arrival_seam.py``), at this zone's arrival: a copy
arriving as an object some graveyard holds arrives as a new, equal one (CR
400.7), and the seam returns the object the pile now holds. These pin the
invariant, its two halves (a card arriving alone stays the caller's object;
the record and the stamps follow the copy that moved), and the two blind
spots a literal scan has: an add through a **computed** attribute name —
two of which put cards into a graveyard around the seam entirely (Gravegouger's
return, Vexing Arcanix's miss) — and a pile assigned whole.
"""

from __future__ import annotations

import ast
import functools
import pathlib

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.graveyard_order import graveyard_arrival_stamps, keep_graveyards_apart
from tests.source_index import source_tree

ROOT = pathlib.Path(__file__).resolve().parents[2]
_ADDERS = frozenset({"append", "extend", "insert"})


@functools.lru_cache(maxsize=1)
def _cards() -> dict:
    cards: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            cards.setdefault(card.name, card)
    return cards


def _game():
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    return game


def _all_held(game) -> list:
    return [held for player in game.players for held in player.graveyard]


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


def test_a_copy_arriving_where_its_object_already_lies_is_a_new_equal_object():
    game = _game()
    bears = _cards()["Grizzly Bears"]
    first = game.put_card_into_graveyard(0, bears)
    second = game.put_card_into_graveyard(0, bears)
    theirs = game.put_card_into_graveyard(1, bears)
    # A card put there alone stays the object its caller holds…
    assert first is bears
    # …and each later copy is its own object, equal by value, and the one the
    # seam handed back is the one the pile holds.
    assert second is not bears and second == bears
    assert theirs is not bears and theirs is not second and theirs == bears
    assert game.players[0].graveyard == [bears, second]
    assert game.players[0].graveyard[1] is second
    assert game.players[1].graveyard[0] is theirs
    held = _all_held(game)
    assert len({id(card) for card in held}) == len(held) == 3


def test_a_diverted_card_is_still_false():
    """The other half of the seam's answer: a card a replacement sent
    elsewhere did not arrive, and the seam says so with False (not None)."""
    game = _game()
    from engine.models import Permanent

    crypt = Permanent(card=_cards()["Forbidden Crypt"])
    game._put_permanent_onto_battlefield(0, crypt, None)
    assert game.put_card_into_graveyard(0, _cards()["Grizzly Bears"]) is False
    assert game.players[0].graveyard == []


def test_the_stamp_retired_is_the_stamp_of_the_copy_that_left():
    """CR 613.7d, per copy. With one object at two positions the record could
    not say which copy had left and kept the earlier stamp
    (``graveyard_order._held_arrivals``); with two objects it can."""
    game = _game()
    anger = _cards()["Anger"]
    game.put_card_into_graveyard(0, anger)
    game.put_card_into_graveyard(0, anger)
    older, newer = graveyard_arrival_stamps(game.players[0])
    assert newer > older
    game.players[0].graveyard.pop(0)
    assert graveyard_arrival_stamps(game.players[0]) == [newer]


def test_a_graveyard_target_is_gone_when_its_own_copy_leaves():
    """CR 608.2b. The stamp names one object; with two copies as one object
    the read clamped to the copy left behind and called the target legal."""
    game = _game()
    bears = _cards()["Grizzly Bears"]
    game.put_card_into_graveyard(0, bears)
    game.put_card_into_graveyard(0, bears)
    stamp = game.graveyard_target_at(0, 1)
    assert stamp.card is game.players[0].graveyard[1]
    game.players[0].graveyard.pop(1)
    assert game.graveyard_index_of(stamp) is None
    other = game.graveyard_target_at(0, 0)
    assert game.graveyard_index_of(other) == 0


def test_the_put_there_record_follows_the_copy_that_died():
    """No Rest for the Wicked's record, on the board the identity was for: an
    old Bears in the pile, a second one put there from the battlefield."""
    game = _game()
    bears = _cards()["Grizzly Bears"]
    old = game.put_card_into_graveyard(0, bears)
    died = game.put_card_into_graveyard(0, bears, from_zone="battlefield")
    record = game.players[0].cards_put_into_your_graveyard_from_battlefield_this_turn
    assert len(record) == 1 and record[0] is died and record[0] is not old


def test_keep_graveyards_apart_splits_a_pile_written_whole():
    """The Debug Menu's paste writes a pile from names, so two copies named
    are the catalog's one object; held apart, they are an arrival's two."""
    game = _game()
    bears = _cards()["Grizzly Bears"]
    game.players[0].graveyard = [bears, bears]
    game.players[1].graveyard = [bears]
    keep_graveyards_apart(game.players)
    held = _all_held(game)
    assert held[0] is bears
    assert len({id(card) for card in held}) == 3
    assert all(card == bears for card in held)


# ---------------------------------------------------------------------------
# The scan's blind spots
# ---------------------------------------------------------------------------

#: Every add to a list reached through a **computed** attribute name under
#: ``engine/`` and ``web/`` — ``getattr(x, name).append(...)`` or a local bound
#: from such a ``getattr`` — with what the name can be. The literal-name ban
#: (``test_graveyard_seam.py``) cannot read a variable, and two of these put
#: cards into a graveyard around the seam until this file: Gravegouger's,
#: Knowledge Vault's, Gustha's Scepter's and Duplicity's return of their
#: exiled cards (``leave_linked_exile``) and Petra Sphinx's and Vexing
#: Arcanix's miss (``_resolve_name_then_reveal_top``). An entry whose name can
#: be "graveyard" says why that is not an arrival.
_COMPUTED_NAME_ADDS: dict[str, str] = {
    "engine/commander.py::commander_declines_zone_change": (
        "CR 903.9's declined choice: the commander goes back to the graveyard "
        "or exile the state-based action took it out of — the commander "
        "object itself (CR 903.3), returned, not a copy arriving."
    ),
    "engine/exiled_records.py::record_exiled_card": (
        "the exile register's own list attribute on Game, not a zone."
    ),
    "engine/handlers/combat_declarations.py::_arm_declaration_toll": (
        "a combat-toll list attribute on Game, not a zone."
    ),
    "engine/mixins/stack/choices/pile_picks.py::_move_picked_pile_card": (
        "the refusal branch puts the card it just popped back into the pile it "
        "came from (a library, or Phyrexian Grimoire's graveyard) — the same "
        "object at the position it left, not an arrival."
    ),
    "engine/mixins/zone_funnels.py::leave_linked_exile": (
        "a linked-exile destination other than the four with seams (hand, "
        "library, graveyard, battlefield), which no lowering writes."
    ),
}


def _computed_getattr(node) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and not isinstance(node.args[1], ast.Constant)
    )


def _computed_name_adds(path: pathlib.Path) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []
    for function in ast.walk(source_tree(path)):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        aliases = {
            target.id
            for node in ast.walk(function)
            if isinstance(node, ast.Assign) and _computed_getattr(node.value)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _ADDERS
                and (
                    _computed_getattr(node.func.value)
                    or (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id in aliases
                    )
                )
            ):
                hits.append((function.name, node.lineno))
    return hits


def _scanned():
    for top in ("engine", "web"):
        yield from sorted((ROOT / top).rglob("*.py"))


def test_every_add_through_a_computed_attribute_name_is_accounted_for():
    found: dict[str, int] = {}
    examined = 0
    for path in _scanned():
        examined += 1
        module = path.relative_to(ROOT).as_posix()
        for function, line in _computed_name_adds(path):
            found.setdefault(f"{module}::{function}", line)
    assert examined > 100
    unlisted = sorted(set(found) - set(_COMPUTED_NAME_ADDS))
    assert not unlisted, (
        "an add through a computed attribute name — if the name can be "
        "'graveyard' it must go through game.put_card_into_graveyard (CR "
        "400.7: no graveyard holds one object twice); either way, list it in "
        "_COMPUTED_NAME_ADDS saying what the name can be:\n  "
        + "\n  ".join(f"{key} (line {found[key]})" for key in unlisted)
    )
    stale = sorted(set(_COMPUTED_NAME_ADDS) - set(found))
    assert not stale, (
        "listed as adding through a computed name but no longer does — a stale "
        "exemption is an unguarded write that looks guarded:\n  "
        + "\n  ".join(stale)
    )


#: The one place a graveyard is assigned whole with anything but an empty
#: list, and what holds it to the invariant afterwards.
_WHOLE_PILE_WRITERS = {
    "web/debug_actions.py": "keep_graveyards_apart",
}


def test_a_graveyard_is_assigned_whole_only_where_it_is_then_held_apart():
    writers: set[str] = set()
    for path in _scanned():
        module = path.relative_to(ROOT).as_posix()
        for node in ast.walk(source_tree(path)):
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Attribute) and target.attr == "graveyard"
                for target in node.targets
            ):
                continue
            if isinstance(node.value, ast.List) and not node.value.elts:
                continue
            writers.add(module)
    assert writers == set(_WHOLE_PILE_WRITERS), (
        "a graveyard assigned whole outside the listed writers — a pile built "
        "from names holds one object at every copy's position:\n  "
        + "\n  ".join(sorted(writers - set(_WHOLE_PILE_WRITERS)))
    )
    for module, holder in _WHOLE_PILE_WRITERS.items():
        assert holder in (ROOT / module).read_text(encoding="utf-8"), (
            f"{module} assigns a graveyard whole and no longer calls {holder}"
        )

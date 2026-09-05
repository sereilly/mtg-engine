"""Guard: leaving exile is one transition, and it is ``take_card_from_exile``.

``engine/exiled_records.py`` keeps one record per exiled *object* — its
counters, its face-down flag, who may look at it — because a ``CardDefinition``
in an exile list has nowhere to keep those and no identity to key them on. It
derives liveness from the zone rather than maintaining it, which makes a record
whose card has left **inert**.

Inert is not gone, and CR 400.7 is the rule that catches the difference: a card
that changes zones becomes a new object "with no memory of, or relation to, its
previous existence", and CR 406.7 says the same of a card in exile that becomes
exiled again. A record left behind is that memory — it comes back to life the
moment the *same* ``CardDefinition`` is exiled by something else, still saying
"face down", still carrying somebody else's counters.

So the departure needs a seam, and the two sides of this zone are nowhere near
the same size: **52** sites under ``engine/`` and ``web/`` append to
``player.exile`` and none of them has to know the register exists, while only
**thirteen** take a card back out. Thirteen places to forget something is the
shape ``remove_from_battlefield`` had at 41 and ``take_card_from_hand`` had at
five, and this file is the same guard those two have.

Three checks, of three different strengths:

  * ``player.exile`` shortened or replaced outside the seam is **banned**,
    with a small table of writes that are legitimately not departures.
  * ``.exile.remove(x)`` / ``.index(x)`` is banned by the same scan, and that
    half is not stylistic: ``list.remove`` compares by **value**, and four of
    the sites replaced here spelled it that way. Two printings of one card are
    equal-looking frozen dataclasses, and the *same* definition object can sit
    in two seats' exiles at once, so the value spelling reaches a look-alike.
  * a write through a **computed** attribute name (``getattr(player, zone).pop``
    / ``setattr(player, zone_name, …)``) is invisible to the first scan — the
    zone is a string in a variable. Four of the thirteen departures were
    spelled that way and the static scan could not see one of them, so every
    such write is enumerated below with what its computed name can be. That
    table is the first scan's completeness assertion: a new one fails here
    until somebody decides whether exile can reach it.
"""

from __future__ import annotations

import ast
import functools
import pathlib

import pytest

from engine.exiled_records import (ExiledRecord, live_records,
                                   record_exiled_card)
from engine.game import Game
from engine.models import PlayerState
from tests.source_index import source_text, source_tree

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCANNED = ("engine", "web")

# The one module allowed to shorten an exile pile: it *is* the transition.
SEAM = "engine/mixins/helpers.py"


# ---------------------------------------------------------------------------
# The seam's own behaviour
# ---------------------------------------------------------------------------


def _game(exile=(), seats: int = 2):
    players = [PlayerState(name=f"P{i + 1}") for i in range(seats)]
    players[0].exile = list(exile)
    return Game(players=players), players[0]


def test_it_removes_one_copy_of_a_shared_object(catalog_by_name):
    """A deck repeats one immutable definition per copy, so two exiled copies
    of a card are the same Python object. Removing "every one that is this
    card" is the bug ``take_card_from_hand`` exists for, one zone over."""
    forest = catalog_by_name["Forest"]
    game, player = _game([forest, forest, forest])

    assert game.take_card_from_exile(player, forest) is True
    assert len(player.exile) == 2


def test_it_matches_by_identity_not_by_value(catalog_by_name):
    """``list.remove``/``list.index`` compare with ``==``. Four of the sites
    this seam replaced used ``.remove(card)``, which finds the first *equal*
    card — a different printing, or an equal-looking copy in another pile."""
    forest = catalog_by_name["Forest"]
    bears = catalog_by_name["Grizzly Bears"]
    game, player = _game([bears, forest])

    assert game.take_card_from_exile(player, forest) is True
    assert [c.name for c in player.exile] == ["Grizzly Bears"]


def test_it_reports_a_card_that_is_not_there(catalog_by_name):
    """False rather than an exception: CR 608.2's "do as much as possible" is
    the caller's decision, and every caller already logs its own version."""
    game, player = _game([catalog_by_name["Forest"]])
    assert game.take_card_from_exile(player, catalog_by_name["Black Lotus"]) is False
    assert len(player.exile) == 1


def test_it_accepts_a_seat_index_as_well_as_a_player(catalog_by_name):
    """Both spellings, for ``take_card_from_hand``'s reason: the call sites hold
    one or the other, and converting at the boundary is cheaper than converting
    at each of them."""
    forest = catalog_by_name["Forest"]
    game, player = _game([forest])
    assert game.take_card_from_exile(0, forest) is True
    assert player.exile == []


def test_a_player_is_converted_to_a_seat_by_identity(catalog_by_name):
    """``Game._owner_seat`` is the boundary the zone seams convert at —
    ``put_card_into_hand``, ``put_card_into_library`` and this one — and it used
    to be ``self.players.index(owner)``.

    ``PlayerState`` is a plain ``@dataclass``, so ``list.index`` compares it
    field by field and hands back the **first** seat that matches. Two seats
    that match is not exotic; it is any board they have not diverged on yet.
    The seam would then take the card out of the wrong player's pile, which is
    the look-alike bug ``test_control_reads.py`` documents for ``Permanent``,
    arriving one level up through the seat.
    """
    lotus = catalog_by_name["Black Lotus"]
    first = PlayerState(name="P", exile=[lotus])
    second = PlayerState(name="P", exile=[lotus])
    game = Game(players=[first, second])
    assert first == second, "the premise: value equality cannot tell them apart"

    assert game.take_card_from_exile(second, lotus) is True

    assert [c.name for c in first.exile] == ["Black Lotus"]
    assert second.exile == []


def test_it_retires_the_record_the_departing_card_carried(catalog_by_name):
    """The whole reason the seam exists. The register never speaks for a card
    that is not in exile — but "does not speak" is derived, so the record is
    still sitting there waiting for the card to come back."""
    lotus = catalog_by_name["Black Lotus"]
    game, player = _game([lotus])
    record_exiled_card(game, lotus, 0, counters={"scream": 2}, face_down=True)

    assert game.take_card_from_exile(player, lotus) is True
    assert game.exiled_records == []


def test_a_record_does_not_come_back_to_life_when_the_card_is_exiled_again(
    catalog_by_name,
):
    """CR 400.7 / CR 406.7 in one assertion: the card that comes back is a new
    object with no memory of its previous existence.

    Without the seam the first exiling's record is merely inert while the card
    is elsewhere, and the *second* exiling — by an unrelated effect, which need
    not be face down and puts no counters anywhere — makes it live again. The
    card would be hidden from the table (CR 406.3) by an effect that never said
    so, carrying two scream counters nobody granted.
    """
    lotus = catalog_by_name["Black Lotus"]
    game, player = _game([lotus])
    record_exiled_card(game, lotus, 0, counters={"scream": 2}, face_down=True)

    game.take_card_from_exile(player, lotus)
    player.hand.append(lotus)

    # Something else exiles the same card, face up and with nothing on it.
    player.hand.remove(lotus)
    player.exile.append(lotus)

    assert [record.face_down for record in live_records(game)] == []


def test_one_departure_retires_exactly_one_of_two_records(catalog_by_name):
    """Two copies exiled by two different effects are two records, and they are
    not interchangeable — one may be face down and the other not. One copy
    leaving must retire one of them, or the pile reports two hidden cards where
    one card is left (CR 406.5's separate piles, arrived at from the other end).
    """
    lotus = catalog_by_name["Black Lotus"]
    game, player = _game([lotus, lotus])
    record_exiled_card(game, lotus, 0, face_down=True)
    record_exiled_card(game, lotus, 0, face_down=True)

    assert game.take_card_from_exile(player, lotus) is True
    assert len(player.exile) == 1
    assert len(list(live_records(game))) == 1


def test_a_named_record_is_the_one_retired(catalog_by_name):
    """A caller that already holds the record knows which of two it is finishing
    with, and that beats any derivation: All Hallow's Eve's upkeep trigger fires
    *for* a record, and binning the card must retire that one — retiring the
    other would strand this copy's counters on a card that has gone."""
    lotus = catalog_by_name["Black Lotus"]
    game, player = _game([lotus, lotus])
    first = record_exiled_card(game, lotus, 0, counters={"scream": 1})
    second = record_exiled_card(game, lotus, 0, counters={"scream": 2})

    assert game.take_card_from_exile(player, lotus, record=first) is True
    assert game.exiled_records == [second]


def test_a_record_for_another_seat_is_left_alone(catalog_by_name):
    """The same ``CardDefinition`` can sit in two players' exiles at once — the
    catalog is shared between seats — so a game-wide identity match would retire
    the wrong player's record."""
    lotus = catalog_by_name["Black Lotus"]
    game, player = _game([lotus])
    game.players[1].exile.append(lotus)
    theirs = record_exiled_card(game, lotus, 1, face_down=True)

    assert game.take_card_from_exile(player, lotus) is True
    assert game.exiled_records == [theirs]


# ---------------------------------------------------------------------------
# Leaving exile goes through that one transition
# ---------------------------------------------------------------------------

# Writes to an exile pile that are legitimately not departures, keyed by
# ``path::function`` so they survive line edits, each with the reason it cannot
# go through the choke point. Checked for staleness below, because an exemption
# naming a function that no longer writes an exile pile is a comment nobody
# re-reads and silently widens to whatever else that name comes to mean.
_EXILE_WRITE_EXEMPTIONS: dict[str, str] = {
    "engine/mixins/helpers.py::take_card_from_exile": "this is the transition",
    # The same exemption the battlefield guard carries for the same function:
    # the Debug Menu replaces a whole board from a supplied payload. Nothing
    # "leaves" — the game state is being rebuilt, register and all.
    "web/debug_actions.py::_apply_raw_state": "wholesale board replacement",
}

_MUTATORS = {"pop", "remove", "clear"}
_VALUE_LOOKUPS = {"remove", "index"}


def _scanned_files() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for base in SCANNED:
        found.extend(sorted((ROOT / base).rglob("*.py")))
    return found


def _module_name(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _enclosing_functions(tree: ast.Module):
    spans = [
        (node.lineno, node.end_lineno, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def enclosing(lineno: int) -> str:
        name = ""
        for start, end, candidate in spans:
            if start <= lineno <= end:
                name = candidate
        return name

    return enclosing


def _is_exile(node) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "exile"


@functools.lru_cache(maxsize=None)
def _exile_writes(path: pathlib.Path) -> tuple[tuple[str, int, str], ...]:
    """``(function, line, source)`` for every statement that shortens, replaces
    or value-searches an exile pile.

    Walked with ``ast`` rather than matched on raw lines, for the reason the
    battlefield guard gives: the first version of *that* scan flagged a
    docstring explaining why the spelling is banned, and a guard that reports
    its own documentation is one people learn to skim.
    """
    source = source_text(path)
    tree = source_tree(path)
    lines = source.splitlines()
    enclosing = _enclosing_functions(tree)
    hits: list[tuple[str, int, str]] = []

    def note(node) -> None:
        hits.append(
            (enclosing(node.lineno), node.lineno, lines[node.lineno - 1].strip())
        )

    for node in ast.walk(tree):
        # ``x.exile = ...`` — a wholesale replacement.
        if isinstance(node, ast.Assign) and any(_is_exile(t) for t in node.targets):
            note(node)
        # ``del x.exile[i]`` / ``x.exile[i:j] = ...``
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and _is_exile(target.value):
                    note(node)
        # ``x.exile.pop(i)`` / ``.remove(c)`` / ``.clear()`` / ``.index(c)``
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in (_MUTATORS | _VALUE_LOOKUPS)
            and _is_exile(node.func.value)
        ):
            note(node)
    return tuple(sorted(set(hits), key=lambda entry: entry[1]))


def test_leaving_exile_goes_through_one_transition():
    """Thirteen sites took a card out of exile, in four spellings — ``pop`` by
    index, ``remove`` by value, a ``getattr``'d zone name, and a whole-list
    rebuild. Three of them knew about the exile register and ten did not.

    That is ``remove_from_battlefield``'s shape at 41 sites and
    ``take_card_from_hand``'s at five: anything that must happen when a card
    leaves has thirteen places to be wired into and thirteen to be forgotten.
    ``Game.take_card_from_exile`` is that place. A new open-coded departure is
    not a style problem; it is a site the next thing hung off the transition
    will silently miss.
    """
    offenders = []
    for path in _scanned_files():
        module = _module_name(path)
        for function, line, text in _exile_writes(path):
            if _EXILE_WRITE_EXEMPTIONS.get(f"{module}::{function}"):
                continue
            offenders.append(f"  {module}:{line} in {function}(): {text}")
    assert not offenders, (
        "an exile pile shortened, replaced or searched by value outside the "
        "seam — call game.take_card_from_exile(owner, card) so the exile "
        "register has one place to retire (CR 400.7):\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("key", sorted(_EXILE_WRITE_EXEMPTIONS))
def test_no_exile_write_exemption_has_gone_stale(key):
    """An exemption for a function that no longer writes an exile pile is a
    standing allowance nobody re-reads."""
    module, function = key.split("::")
    path = ROOT / module
    assert path.exists(), f"{module} no longer exists"
    writes = [entry for entry in _exile_writes(path) if entry[0] == function]
    assert writes, (
        f"{key} is exempted from the exile-write rule but no longer writes an "
        "exile pile — delete the exemption"
    )


# ---------------------------------------------------------------------------
# The scan's blind spot, enumerated
# ---------------------------------------------------------------------------

# Every write under ``engine/`` and ``web/`` that reaches an attribute through a
# name the scan above cannot read — ``getattr(x, name).pop(...)``,
# ``setattr(x, name, ...)``, or a local bound from such a ``getattr``. The
# attribute might be ``exile``, and the static scan would never know: four of
# the thirteen departures were spelled this way, and one of them
# (``check_state_based_actions``) shortened three zones in a single line.
#
# The value is what the computed name can be, which is the fact a reviewer
# needs. Entries whose name can be "exile" have to say how they reach the seam.
_COMPUTED_ATTRIBUTE_WRITES: dict[str, str] = {
    "engine/commander.py::_commander_zone_state_based_actions": (
        "CR 903.9a's two dead zones — 'graveyard' or 'exile'. The exile branch "
        "calls take_card_from_exile; this is the graveyard one."
    ),
    "engine/handlers/zones.py::_take_located_card": (
        "_OWNERSHIP_ZONES — graveyard/hand/exile/library/ante. The exile branch "
        "calls take_card_from_exile; this is every other zone."
    ),
    "engine/mixins/game_ending.py::check_state_based_actions": (
        "CR 704.5d's token sweep over graveyard/hand/exile. The exile pass "
        "calls take_card_from_exile per token; this rebuilds the other two."
    ),
    "engine/mixins/stack/choices.py::_resolve_name_and_random_reveal": (
        "the zone Nebuchadnezzar's paragraph names, and the production accepts "
        "only 'hand' or 'library' (paragraphs._RANDOM_REVEAL_ZONES) — exile "
        "cannot reach it."
    ),
    "engine/exiled_records.py::forget_record": (
        "the register's own list attribute on Game (RECORDS_ATTR), not a zone."
    ),
    "engine/continuous.py::_set_action": (
        "the set-valued characteristic fields of a layer probe, not a zone."
    ),
    "engine/damage_redirects.py::redirects_on": (
        "the redirect collection's attribute on a recipient, not a zone."
    ),
    "engine/land_mana_swaps.py::swaps_on": (
        "the mana-swap collection's attribute on a player, not a zone."
    ),
    "engine/shields.py::shields_on": (
        "the shield collection's attribute on a recipient, not a zone."
    ),
}


@functools.lru_cache(maxsize=None)
def _computed_attribute_writes(path: pathlib.Path) -> tuple[tuple[str, int, str], ...]:
    """``(function, line, source)`` for every mutation through a computed
    attribute name.

    "Computed" means the name is not a string literal: ``getattr(p, zone)`` and
    ``setattr(p, zone_name, …)`` qualify, ``getattr(p, "metadata")`` does not.
    A literal name is something the scan above can already reason about; a
    variable is not.
    """
    source = source_text(path)
    tree = source_tree(path)
    lines = source.splitlines()
    hits: list[tuple[str, int, str]] = []

    def computed_getattr(node) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and not isinstance(node.args[1], ast.Constant)
        )

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        aliases: set[str] = set()
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and computed_getattr(node.value):
                aliases.update(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            reaches = False
            if isinstance(node.func, ast.Name) and node.func.id == "setattr":
                reaches = len(node.args) >= 2 and not isinstance(
                    node.args[1], ast.Constant
                )
            elif isinstance(node.func, ast.Attribute) and node.func.attr in _MUTATORS:
                receiver = node.func.value
                reaches = computed_getattr(receiver) or (
                    isinstance(receiver, ast.Name) and receiver.id in aliases
                )
            if reaches:
                hits.append(
                    (
                        function.name,
                        node.lineno,
                        lines[node.lineno - 1].strip(),
                    )
                )
    return tuple(sorted(set(hits), key=lambda entry: entry[1]))


def test_every_write_through_a_computed_attribute_name_is_accounted_for():
    """The completeness assertion the ban above needs.

    A ban that scans for the token ``exile`` cannot see ``getattr(player,
    zone).pop(at)``, and that is not hypothetical: four of the thirteen
    departures were spelled that way, including one line that swept three zones
    at once. So the set of writes whose attribute name is a *variable* is
    enumerated, with what that variable can hold. A new one is a hole in the
    ban until somebody writes down whether exile can reach it.
    """
    unlisted = []
    for path in _scanned_files():
        module = _module_name(path)
        for function, line, text in _computed_attribute_writes(path):
            if f"{module}::{function}" in _COMPUTED_ATTRIBUTE_WRITES:
                continue
            unlisted.append(f"  {module}:{line} in {function}(): {text}")
    assert not unlisted, (
        "a write through a computed attribute name, which the exile-write ban "
        "cannot see. If the name can be 'exile', route it through "
        "game.take_card_from_exile; either way add it to "
        "_COMPUTED_ATTRIBUTE_WRITES saying what the name can be:\n"
        + "\n".join(unlisted)
    )


@pytest.mark.parametrize("key", sorted(_COMPUTED_ATTRIBUTE_WRITES))
def test_no_computed_write_entry_has_gone_stale(key):
    """Same reason as every other table here: an entry whose function no longer
    writes through a computed name is a note nobody will re-check, and it goes
    on covering whatever that name comes to mean."""
    module, function = key.split("::")
    path = ROOT / module
    assert path.exists(), f"{module} no longer exists"
    writes = [
        entry for entry in _computed_attribute_writes(path) if entry[0] == function
    ]
    assert writes, (
        f"{key} is listed as a computed-name write but no longer is one — "
        "delete the entry"
    )


def test_the_seam_is_the_only_place_that_retires_a_record():
    """``forget_record`` is the register's private drop. One caller — the seam —
    because a second one is a second answer to "when does a record stop
    speaking", and the whole point of this round is that there is one.

    ``exiled_records.py`` itself is where it is defined.
    """
    callers = []
    for path in _scanned_files():
        module = _module_name(path)
        if module == "engine/exiled_records.py":
            continue
        for node in ast.walk(source_tree(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "forget_record"
            ):
                callers.append(f"{module}:{node.lineno}")
    assert callers, "forget_record has no callers at all — the register never drains"
    assert all(caller.startswith(SEAM) for caller in callers), (
        "forget_record is called outside the departure seam — a record retires "
        "when its card leaves exile, and that is one place:\n  "
        + "\n  ".join(callers)
    )


def test_the_register_is_typed_as_the_seam_expects():
    """A cheap shape check so the tests above cannot pass against a register
    that has quietly become something else."""
    game, _ = _game()
    assert game.exiled_records == []
    assert ExiledRecord.__dataclass_fields__.keys() >= {
        "card", "owner_index", "controller_index", "face_down", "looker_index",
        "metadata",
    }


# ---------------------------------------------------------------------------
# Every route out of exile, driven
# ---------------------------------------------------------------------------
#
# The scans above are structural: they say no *new* departure escapes. These
# say the ten that were open actually drain the register now, by driving each
# one on a real ``Game`` with a record planted on the card it moves. Three of
# the thirteen (the cast-from-exile path, ``put_exiled_cards_into_zone`` and
# ``put_self_into_zone``) already retired their records and are covered where
# their cards are — ``tests/sets/test_vis_instants.py`` for the Three Wishes
# cycle and ``tests/sets/test_legends_sorceries.py`` for All Hallow's Eve.


def _planted(game, seat, card):
    """A face-down record for *card* in seat *seat*'s exile."""
    return record_exiled_card(game, card, seat, face_down=True)


def test_a_creature_exiled_until_end_of_turn_takes_its_record_back(catalog_by_name):
    """CR 610.3's one-shot return, at the cleanup step. It used to be
    ``owner.exile.remove(card_def)`` — value comparison — and it retired
    nothing."""
    from engine.models import CardDefinition, Permanent

    banish = CardDefinition(
        name="Banish", mana_cost="{1}", cmc=1.0, type_line="Instant",
        oracle_text="Exile target creature until end of turn.", colors=(),
        color_identity=(), keywords=(), produced_mana=(), raw={"name": "Banish"},
    )
    bear = catalog_by_name["Grizzly Bears"]
    game = Game(players=[
        PlayerState(name="P1", hand=[banish], library=[catalog_by_name["Island"]] * 5),
        PlayerState(name="P2", battlefield=[Permanent(card=bear)],
                    library=[catalog_by_name["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Banish", target_player_index=1, target_permanent_index=0)
    game.resolve_stack()
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    _planted(game, 1, bear)

    game.resolve_cleanup_step(0)

    assert game.players[1].exile == []
    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]
    assert game.exiled_records == []


def test_a_token_that_ceases_to_exist_in_exile_takes_its_record(catalog_by_name):
    """CR 704.5d. The sweep rebuilt three zone lists in one line, which is the
    spelling the static scan cannot see at all — the zone name is a loop
    variable."""
    from engine.tokens import make_token_card

    game, player = _game()
    token = make_token_card("Wasp", 1, 1, "Artifact Creature - Insect")
    player.exile.append(token)
    _planted(game, 0, token)

    game.check_state_based_actions()

    assert player.exile == []
    assert game.exiled_records == []


def test_an_ownership_move_out_of_exile_takes_the_record(catalog_by_name):
    """Timmerian Fiends' "put this card **from anywhere** into that player's
    graveyard" (CR 701.12a). The locator returns a zone *name*, so the write
    went through ``getattr(player, zone).pop(at)`` — invisible to the scan."""
    from engine.handlers.zones import _give_card_to_graveyard

    lotus = catalog_by_name["Black Lotus"]
    game, player = _game([lotus])
    _planted(game, 0, lotus)

    assert _give_card_to_graveyard(game, lotus, 1, 0) is True

    assert player.exile == []
    assert [c.name for c in game.players[1].graveyard] == ["Black Lotus"]
    assert game.exiled_records == []


def test_a_commander_pulled_out_of_exile_takes_its_record(catalog_by_name):
    """CR 903.9a moves a commander out of a graveyard *or exile*, and the two
    branches shared one ``held.pop(index)`` over a computed zone name."""
    bear = catalog_by_name["Grizzly Bears"]
    game, player = _game([bear])
    game.commander_variant = "commander"
    player.commanders = [bear]
    game.interactive_seats = set()
    _planted(game, 0, bear)

    game.check_state_based_actions()
    game.auto_resolve_pending_choices()

    assert player.exile == []
    assert [c.name for c in player.command_zone] == ["Grizzly Bears"]
    assert game.exiled_records == []


def test_a_linked_pile_returning_a_card_takes_its_record(set_pool, catalog_by_name):
    """Tawnos's Coffin's "return that exiled card to the battlefield" — the
    linked-exile record's own return path (``Game.leave_linked_exile``), which
    is a different register and still leaves *this* one behind if it does not
    go through the seam."""
    from engine.models import Permanent

    coffin = Permanent(card=set_pool("ATQ")["Tawnos's Coffin"])
    bear = catalog_by_name["Grizzly Bears"]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[coffin],
                    library=[catalog_by_name["Island"]] * 5),
        PlayerState(name="P2", battlefield=[Permanent(card=bear)],
                    library=[catalog_by_name["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    coffin.metadata["summoning_sickness_turn"] = -99
    game.activate_permanent_ability(
        0, "Tawnos's Coffin", target_player_index=1, target_permanent_index=0
    )
    game._settle()
    game.auto_resolve_pending_choices()
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    _planted(game, 1, bear)

    game.become_untapped(coffin)
    game._settle()

    assert game.players[1].exile == []
    assert [p.card.name for p in game.players[1].battlefield] == ["Grizzly Bears"]
    assert game.exiled_records == []


def test_the_exiled_pile_top_going_to_a_hand_takes_its_record(
    set_pool, catalog_by_name
):
    """Mangara's Tome: "put the top card of the exiled pile into its owner's
    hand". A ``pop`` by index with no retirement behind it."""
    import random

    from engine.linked_exile import face_down_exiled_cards, linked_entries

    random.seed(11)
    names = ("Black Lotus", "Grizzly Bears", "Hurloon Minotaur", "Mox Pearl",
             "Healing Salve", "Island", "Island", "Island", "Island")
    game = Game(players=[
        PlayerState(name="P1", library=[catalog_by_name[n] for n in names],
                    hand=[set_pool("MIR")["Mangara's Tome"]]),
        PlayerState(name="P2", library=[catalog_by_name["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    assert game.cast_from_hand(0, "Mangara's Tome").supported
    game._settle()
    game.auto_resolve_pending_choices()
    tome = next(iter(game.controlled_by(game.players[0])))
    tome.metadata["summoning_sickness_turn"] = -99
    assert len(game.players[0].exile) == 5
    assert len(face_down_exiled_cards(game, 0)) == 5

    game.activate_permanent_ability(0, "Mangara's Tome")
    game._settle()
    game.auto_resolve_pending_choices()
    # The pile's order is its own — it was shuffled as it was made — so the
    # card about to move is the record's top, not the exile list's first entry.
    _planted(game, 0, linked_entries(tome)[0]["card"])
    game._draw_with_replacements(game.players[0], 1)

    assert len(game.players[0].exile) == 4
    assert len(face_down_exiled_cards(game, 0)) == 4
    assert game.exiled_records == []

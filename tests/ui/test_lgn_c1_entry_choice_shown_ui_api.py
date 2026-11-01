"""An "as it enters" choice is not shown before it is made (CR 614.12a) — on
the wire.

Found in Legions' Phase 5: a person cast Ward Sliver ("As this creature
enters, choose a color. All Slivers have protection from the chosen color.")
and, while the colour prompt was still open, both seats' payloads already
showed "Protection from red" — the engine's provisional default — on every
Sliver. Canopy Crawler sat on the battlefield as a 2/2 while its amplify reveal
was open and its spell was still on the stack.

The engine places the permanent and stamps a default before it arms the
prompt. Measured over every entry chooser in the pool cast from a person's
hand: of 40 that open a prompt, all 40 are on the battlefield with their spell
still on the stack, 37 have a provisional record written, 37 send a default
the client can pre-select, and the 11 creatures among them fire "whenever
another creature enters" (Soul Warden) before the choice. Moving the permanent
off the battlefield until the answer is the engine-side fix and is a parts list
in the Legions C1 report; what this holds is the measured wire partial
(``web.serialization.entry_choice_view``): while a permanent is entering, the
battlefield is sent as it reads with no entering permanent's choice recorded,
and the entering permanent is marked ``entering``.
"""
from __future__ import annotations

import re

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from web.serialization import _serialize_player, entry_choice_view

_CATALOG = {card.name: card for card in load_catalog()}
_ENTRY_CHOICE_LINE = re.compile(r"^as .*\benters\b.*\bchoose\b", re.I)


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_CATALOG[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _cast_and_open_the_prompt(name: str, *, beside=(), hand_extra=()):
    """*name* cast from the human's hand at a human-vs-AI table, resolved on
    the priority path until its entry prompt opens. None when it opens none."""
    lands = [_permanent(land) for land in ("Plains", "Island", "Swamp", "Mountain", "Forest") * 2]
    game = Game(players=[
        PlayerState(
            name="Human", hand=[_CATALOG[name], *(_CATALOG[n] for n in hand_extra)],
            library=[_CATALOG["Forest"]] * 10,
            battlefield=[*lands, *(_permanent(n) for n in beside)],
        ),
        PlayerState(
            name="AI", library=[_CATALOG["Forest"]] * 10,
            battlefield=[_permanent("Grizzly Bears"), _permanent("Llanowar Elves")],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._sync_control()
    before = {seat: _board(game, seat) for seat in (0, 1)}
    result = game.queue_from_hand(0, name)
    if not result.supported:
        return None
    for _ in range(5):
        if not game.stack or game.waiting_prompt() is not None:
            break
        game.resolve_top_of_stack(pause_for_choices=True)
    entering = [perm for perm in game.controlled_by(0) if game.permanent_is_entering(perm)]
    if game.waiting_prompt() is None or not entering:
        return None
    return game, entering[0], before


def _board(game: Game, seat: int, *, viewer: int = 0) -> list[dict]:
    payload = _serialize_player(
        game.players[seat], viewer, seat, game,
        battlefield_view=entry_choice_view(game),
    )
    return payload["battlefield"]


def _by_name(board: list[dict], name: str) -> dict:
    return next(entry for entry in board if entry["name"] == name)


def _protections(entry: dict) -> list[str]:
    return [k for k in entry.get("keywords", []) if "protection" in str(k).lower()]


def test_ward_slivers_colour_is_not_shown_on_any_sliver_before_it_is_chosen():
    opened = _cast_and_open_the_prompt("Ward Sliver", beside=("Plated Sliver",))
    assert opened is not None
    game, ward, _before = opened
    # The engine's provisional default is there…
    assert ward.metadata.get("chosen_color")
    for viewer in (0, 1):
        board = _board(game, 0, viewer=viewer)
        # …and no seat is told about it.
        assert _protections(_by_name(board, "Plated Sliver")) == []
        assert _protections(_by_name(board, "Ward Sliver")) == []
        assert _by_name(board, "Ward Sliver")["entering"] is True
        assert "entering" not in _by_name(board, "Plated Sliver")

    assert game.resolve_pending_choice("enter_choice", 0, color="U")
    board = _board(game, 0, viewer=1)
    assert "entering" not in _by_name(board, "Ward Sliver")
    assert _protections(_by_name(board, "Plated Sliver")), _by_name(board, "Plated Sliver")


def test_an_amplify_creature_is_sent_as_entering_while_its_reveal_is_open():
    opened = _cast_and_open_the_prompt("Canopy Crawler", hand_extra=("Krosan Tusker",))
    assert opened is not None
    game, crawler, _before = opened
    assert game.waiting_prompt().kind == "entry_reveal"
    entry = _by_name(_board(game, 0, viewer=1), "Canopy Crawler")
    assert entry["entering"] is True


def _entry_choosers() -> list[str]:
    """Every permanent whose text chooses or reveals as it enters, read face by
    face (a multi-face card's text is its faces'), named by the card that is
    cast."""
    return sorted({
        whole_card(unit).name for unit in compilation_units(_CATALOG.values())
        if unit.primary_type not in ("instant", "sorcery")
        and compile_card_oracle(unit).supported
        and (
            "Amplify" in (unit.oracle_text or "")
            or any(_ENTRY_CHOICE_LINE.search(line) for line in (unit.oracle_text or "").splitlines())
        )
    })


_VOLATILE = {"id", "target_spec", "ability_target_specs", "ability_denials", "ability_mana"}


def _steady(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if key not in _VOLATILE}


def test_while_any_permanent_is_entering_the_rest_of_the_board_reads_as_before():
    """Every entry chooser in the pool (and every amplify card), cast from the
    human's hand: while its prompt is open, every *other* permanent is sent
    exactly as it was before the spell was cast, to both seats, and the
    entering one is marked."""
    examined = 0
    changed: list[str] = []
    for name in _entry_choosers():
        opened = _cast_and_open_the_prompt(
            name, hand_extra=("Krosan Tusker",) if "Amplify" in (_CATALOG[name].oracle_text or "") else (),
        )
        if opened is None:
            continue
        game, entering, before = opened
        examined += 1
        for seat in (0, 1):
            now = _board(game, seat)
            assert any(entry.get("entering") for entry in now) == (seat == 0), name
            others_now = [_steady(e) for e in now if not e.get("entering")]
            others_before = [_steady(e) for e in before[seat]]
            if others_now != others_before:
                changed.append(f"{name}: seat {seat}'s board changed before the choice")
    assert not changed, "\n".join(changed)
    # Measured: 40 permanents open an entry prompt from a person's hand.
    assert examined >= 35, examined

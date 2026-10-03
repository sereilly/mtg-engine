"""CR 603.6c / 603.10a — a leaves-the-battlefield trigger watching the board —
and CR 707.5, a token that enters as a copy.

Dual Nature's second line ("Whenever a nontoken creature leaves the
battlefield, …") is the first board-wide leaves-the-battlefield trigger the pool
prints: every earlier one watched the ability's own source, its host or a token
it made. The condition is built as a mechanism rather than as one card — a
subject-led kind (``matching_permanent_leaves_battlefield``) announced from the
one transition off the battlefield — so every card here is **invented**, for the
reason the neighbouring rules files give: a test naming Dual Nature would pass
against a table keyed on Dual Nature. The real card is in
``tests/sets/test_pcy_enchantments.py``. The release line prints about thirty
more of these ("Whenever another creature you control leaves the battlefield,
you gain 1 life" is Lunarch Veteran's), and the first test is that sentence.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _mk_creature_card, resolve_stack


def _w2g2_rules_table() -> Game:
    game = Game(players=[PlayerState(name="P0"), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    return game  # the PCY W2G2 rules table


def _w2g2_rules_enter(game: Game, seat: int, card) -> Permanent:
    entered = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, entered, None)
    resolve_stack(game)
    return entered  # entered and drained, PCY W2G2 rules


def _w2g2_watcher(text: str, name: str = "Vigil Ward"):
    return _mk_card(name, "{1}{W}", "Enchantment", text)


@pytest.mark.cr("603.6c")
def test_603_6c_another_creature_you_control_leaving_is_watched_board_wide():
    """"Whenever another creature you control leaves the battlefield, you gain
    1 life." Every move off the battlefield counts — a death and a bounce
    alike — and the printed narrowing is enforced: an opponent's creature
    leaving and the watcher's own departure gain nothing."""
    game = _w2g2_rules_table()
    watcher = _w2g2_rules_enter(game, 0, _mk_creature_card(
        "Vigil Keeper", 1, 1,
        "Whenever another creature you control leaves the battlefield, "
        "you gain 1 life.",
    ))
    (trig,) = compile_card_oracle(watcher.card).triggered_abilities
    assert trig.condition.kind == "matching_permanent_leaves_battlefield"

    wolf = _w2g2_rules_enter(game, 0, _mk_creature_card("Wolf", 2, 2))
    elk = _w2g2_rules_enter(game, 0, _mk_creature_card("Elk", 3, 3))
    theirs = _w2g2_rules_enter(game, 1, _mk_creature_card("Bear", 2, 2))

    game.sacrifice_permanent(wolf)
    resolve_stack(game)
    assert game.players[0].life == 21
    game._bounce_target_creature(elk)
    resolve_stack(game)
    assert game.players[0].life == 22
    assert [c.name for c in game.players[0].hand] == ["Elk"]

    game.sacrifice_permanent(theirs)
    resolve_stack(game)
    assert game.players[0].life == 22
    game.sacrifice_permanent(watcher)
    resolve_stack(game)
    assert game.players[0].life == 22


@pytest.mark.cr("603.10a")
def test_603_10a_a_watcher_leaving_in_the_same_sweep_still_sees_the_rest_go():
    """Leaves-the-battlefield abilities look back in time. One removal takes
    the watcher and two creatures together: the watcher is gone by the time
    anything resolves, and it still triggers for both creatures — and the
    "nontoken" in its phrase is asked of each one as it last existed, so the
    token leaving beside them is not counted."""
    from engine.tokens import make_token_card

    game = _w2g2_rules_table()
    watcher = _w2g2_rules_enter(game, 0, _w2g2_watcher(
        "Whenever a nontoken creature leaves the battlefield, you gain 1 life."
    ))
    wolf = _w2g2_rules_enter(game, 0, _mk_creature_card("Wolf", 2, 2))
    bear = _w2g2_rules_enter(game, 1, _mk_creature_card("Bear", 2, 2))
    token = Permanent(
        card=make_token_card("Elf Token", 1, 1, "Creature — Elf"),
        metadata={"is_token": True},
    )
    game._put_permanent_onto_battlefield(1, token, None)

    removed = game.remove_all_from_battlefield([watcher, wolf, bear, token])
    assert len(removed) == 4
    resolve_stack(game)
    assert game.players[0].life == 22
    assert not list(game.all_permanents())


@pytest.mark.cr("603.6c")
def test_603_6c_when_a_creature_leaves_is_not_the_sources_own_departure():
    """Printed with "when", a quantified subject is still the board-wide event:
    "When a creature leaves the battlefield" must not be read as the source's
    own leave trigger. The enchantment leaving gains nothing; a creature
    leaving gains 1."""
    card = _w2g2_watcher(
        "When a creature leaves the battlefield, you gain 1 life.", "Brief Ward",
    )
    (trig,) = compile_card_oracle(card).triggered_abilities
    assert trig.condition.kind == "matching_permanent_leaves_battlefield"

    game = _w2g2_rules_table()
    ward = _w2g2_rules_enter(game, 0, card)
    wolf = _w2g2_rules_enter(game, 1, _mk_creature_card("Wolf", 2, 2))
    game.sacrifice_permanent(wolf)
    resolve_stack(game)
    assert game.players[0].life == 21
    game.sacrifice_permanent(ward)
    resolve_stack(game)
    assert game.players[0].life == 21


@pytest.mark.cr("707.5")
def test_707_5_a_token_copy_enters_as_the_copy(monkeypatch):
    """"An object that enters the battlefield … 'that's a copy' of another
    object becomes a copy as it enters the battlefield. It doesn't enter the
    battlefield, and then become a copy." So a "whenever a creature enters"
    watcher sees a creature arrive, and the entry announcement froze the copied
    creature's name and power — the token used to be announced as a typeless
    "Token" and only then become what it copies."""
    game = _w2g2_rules_table()
    _w2g2_rules_enter(game, 0, _w2g2_watcher(
        "Whenever a creature enters, you gain 1 life.", "Chorus Ward",
    ))
    bear = _w2g2_rules_enter(game, 1, _mk_creature_card("Bear", 2, 2))
    assert game.players[0].life == 21

    seen: list[dict] = []
    from engine import events as w2g2_events

    original = w2g2_events.collect

    def _spy(game_, event):
        if event.kind == "matching_permanent_enters":
            seen.append(dict(event.payload))
        return original(game_, event)

    monkeypatch.setattr(w2g2_events, "collect", _spy)
    token = game.create_token_copy(1, bear)
    monkeypatch.undo()
    resolve_stack(game)

    assert token.metadata.get("is_token") and token.is_creature
    assert game.players[0].life == 22
    assert [(p["event_subject_name"], p["entering_power"]) for p in seen] == [
        ("Bear", 2)
    ]

"""Every "as it enters" chooser in the pool, cast from a person's hand: the
choice is made before the permanent enters (CR 614.12a).

Legions' closer C1 measured 40 permanents that open an entry prompt from a
person's hand (every "As … enters, … choose" line and every amplify card). All
40 were on the battlefield with their spell still on the stack while the
prompt was open, 37 carried a provisional ``chosen_*`` record, and the 11
creatures among them set off Soul Warden ("whenever another creature enters")
before the choice.

Each is cast here at a human-vs-AI table with Soul Warden on the AI's side and
resolved on the priority path. While its prompt is open the permanent must be
on its way (``engine/entry_awaiting.py``): on no battlefield, its spell held on
the stack, no record of the person's choice written, Soul Warden silent. Once
every prompt is answered (by the default the prompt carries) it is on the
battlefield, Soul Warden has seen a creature enter, and no entry is left
waiting. Backwards, on the tree before ``entry``: all 40 fail the first check.

Whole in both passes: the 55 casts take well under a second.
"""
from __future__ import annotations

import re

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.entry_choices import ENTRY_CHOICES
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_C = {card.name: card for card in load_catalog()}
_ENTRY_CHOICE_LINE = re.compile(r"^as .*\benters\b.*\bchoose\b", re.I)
_RECORDS = {row.key for row in ENTRY_CHOICES}
#: Null Chamber's second name is the AI opponent's, chosen as its prompt was
#: armed: a choice made, not a default standing in for the person's.
_ANSWERED_BY_ANOTHER_SEAT = {"chosen_card_names"}


def _choosers() -> list[str]:
    return sorted({
        whole_card(unit).name for unit in compilation_units(_C.values())
        if unit.primary_type not in ("instant", "sorcery")
        and compile_card_oracle(unit).supported
        and (
            "Amplify" in (unit.oracle_text or "")
            or any(_ENTRY_CHOICE_LINE.search(line) for line in (unit.oracle_text or "").splitlines())
        )
    })


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_C[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(name: str) -> Game:
    amplify = "Amplify" in (_C[name].oracle_text or "")
    game = Game(players=[
        PlayerState(
            name="Human", hand=[_C[name]] + ([_C["Krosan Tusker"]] if amplify else []),
            library=[_C["Forest"]] * 10,
            battlefield=[_permanent(n) for n in ("Plains", "Island", "Swamp", "Mountain", "Forest") * 2],
        ),
        PlayerState(
            name="AI", library=[_C["Forest"]] * 10,
            battlefield=[_permanent("Soul Warden"), _permanent("Grizzly Bears"),
                         _permanent("Llanowar Elves")],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._sync_control()
    return game


def _warden(game: Game) -> bool:
    return any(item.card.name == "Soul Warden" for item in game.stack) or game.players[1].life > 20


def test_every_chooser_is_on_its_way_while_a_person_chooses():
    examined = 0
    wrong: list[str] = []
    for name in _choosers():
        game = _table(name)
        if not game.queue_from_hand(0, name).supported:
            continue
        for _ in range(5):
            if not game.stack or game.waiting_prompt() is not None:
                break
            game.resolve_top_of_stack(pause_for_choices=True)
        waiting = [r.permanent for r in game.entries_in_progress if game.entry_is_awaited(r.permanent)]
        if game.waiting_prompt() is None:
            # No question to ask from this board (one opponent, nothing to
            # reveal): it entered at once, and that is the whole of it.
            assert not waiting, name
            continue
        examined += 1
        if not waiting:
            wrong.append(f"{name}: a prompt is open and nothing is on its way")
            continue
        permanent = waiting[0]
        creature = permanent.is_creature or "Creature" in (_C[name].type_line or "")
        recorded = sorted(set(permanent.metadata) & _RECORDS - _ANSWERED_BY_ANOTHER_SEAT)
        if game.is_on_battlefield(permanent):
            wrong.append(f"{name}: on the battlefield while its choice is owed")
        if not any(item.card is _C[name] for item in game.stack):
            wrong.append(f"{name}: its spell left the stack before the choice")
        if recorded:
            wrong.append(f"{name}: {recorded} recorded before the person chose")
        if _warden(game):
            wrong.append(f"{name}: Soul Warden saw it enter before the choice")
        for _ in range(6):
            owed = game.waiting_prompt()
            if owed is None:
                break
            game.take_choice_default(owed)
        if not game.is_on_battlefield(permanent):
            wrong.append(f"{name}: not on the battlefield after the answer")
        if game.entries_in_progress:
            wrong.append(f"{name}: an entry is still waiting after every answer")
        if creature and not _warden(game):
            wrong.append(f"{name}: Soul Warden never saw it enter")
    assert not wrong, "\n".join(wrong)
    # Measured at kg3: 40 open a prompt from a person's hand.
    assert examined >= 35, examined


def test_a_seat_nobody_asks_enters_every_chooser_at_once():
    """The same casts by a seat nobody asks: the default is the answer, taken
    as the prompt is armed, and the permanent is on the battlefield when the
    resolution ends — the engine's behaviour before ``entry``, unchanged."""
    examined = 0
    wrong: list[str] = []
    for name in _choosers():
        game = _table(name)
        game.interactive_seats = set()
        if not game.queue_from_hand(0, name).supported:
            continue
        game.resolve_top_of_stack()
        examined += 1
        if not any(p.card is _C[name] for p in game.controlled_by(0)):
            wrong.append(f"{name}: not on the battlefield after resolving")
        if game.entries_in_progress:
            wrong.append(f"{name}: an entry waits at a table nobody is asked at")
    assert not wrong, "\n".join(wrong)
    assert examined >= 45, examined

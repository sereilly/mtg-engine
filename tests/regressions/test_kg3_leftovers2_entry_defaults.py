"""An entry's choice is never left owing after the permanent has entered
(CR 614.12a: "that choice is made before the permanent enters the
battlefield").

kg3's ``entry`` group made an entry that asks wait on its way at a table that
holds for answers (a person, or the simulator's driver), and left one road
open: **a bare headless table** (nobody interactive, no driver) holds nothing,
so a permanent whose entry prompt is of a kind that is not ``default_at_arm``
entered at once with its provisional default stamped and the prompt still
queued about a permanent already on the battlefield — Shapeshifter's number,
the life Phyrexian Processor, Minion of the Wastes and Nameless Race pay
(``number_choice``, a kind Tetravus's counters share). Answering that prompt
then *changed* the permanent after it had entered — a choice made after the
permanent entered; and ``web.serialization.entry_choice_view``
existed only to hide the stamped default in that window.

Every other entry prompt kind is ``default_at_arm`` (``enter_choice``,
``body_choice``, ``entry_exile``, ``entry_reveal``): a seat nobody asks
answers as the prompt is armed, which is what the stamped default stood in
for. So at a table that holds nothing, an entry prompt of any kind is answered
by its default as it is armed (``Game._an_entry_nobody_waits_for``, asked by
``arm_pending_choice``) — the kind stays queued everywhere else it is armed.

Census: every supported permanent card printing an "as … enters" line or
amplify, cast at a bare table and at a table with a person. After the cast no
permanent on any battlefield owes an entry prompt (``permanent_is_entering``),
which is also the only state ``entry_choice_view`` ever found something in.
Backwards on 90bef6d1: Shapeshifter, Phyrexian Processor and Minion of the
Wastes entered owing their prompts at the bare table.
"""
from __future__ import annotations

import re

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_C = {card.name: card for card in load_catalog()}
_ENTRY_LINE = re.compile(r"^as .*\benters\b", re.I)


def _entry_cards() -> list[str]:
    return sorted({
        whole_card(unit).name for unit in compilation_units(_C.values())
        if unit.primary_type not in ("instant", "sorcery")
        and compile_card_oracle(unit).supported
        and (
            "Amplify" in (unit.oracle_text or "")
            or any(_ENTRY_LINE.search(line) for line in (unit.oracle_text or "").splitlines())
        )
    })


def _permanent(name: str) -> Permanent:
    permanent = Permanent(card=_C[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(name: str, *, interactive: bool) -> Game:
    amplify = "Amplify" in (_C[name].oracle_text or "")
    game = Game(players=[
        PlayerState(
            name="P0", hand=[_C[name]] + ([_C["Krosan Tusker"]] if amplify else []),
            library=[_C["Forest"]] * 10,
            battlefield=[_permanent(n) for n in ("Plains", "Island", "Swamp", "Mountain", "Forest") * 2],
        ),
        PlayerState(
            name="P1", library=[_C["Forest"]] * 10,
            battlefield=[_permanent("Grizzly Bears"), _permanent("Llanowar Elves")],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game._sync_control()
    return game


def _owing(game: Game) -> list[str]:
    return [
        perm.card.name for perm in game.all_permanents()
        if game.permanent_is_entering(perm)
    ]


def test_a_permanent_at_a_bare_table_never_enters_owing_its_choice():
    examined = 0
    wrong: list[str] = []
    for name in _entry_cards():
        game = _table(name, interactive=False)
        if not game.cast_from_hand(0, name).supported:
            continue
        resolve_stack(game)
        examined += 1
        owing = _owing(game)
        if owing:
            wrong.append(f"{name}: entered owing a choice ({owing})")
    assert not wrong, "\n".join(wrong)
    # Measured at kg3/leftovers2: 67 supported "as … enters" / amplify cards
    # cast from a hand.
    assert examined >= 60, examined


def test_a_person_s_permanent_waits_on_its_way_and_owes_nothing_once_on_the_battlefield():
    """The person's road, unchanged: while the prompt is open nothing on the
    battlefield owes it (the permanent is on its way), and once answered
    nothing does either."""
    examined = 0
    wrong: list[str] = []
    for name in _entry_cards():
        game = _table(name, interactive=True)
        if not game.queue_from_hand(0, name).supported:
            continue
        for _ in range(5):
            if not game.stack or game.waiting_prompt() is not None:
                break
            game.resolve_top_of_stack(pause_for_choices=True)
        if _owing(game):
            wrong.append(f"{name}: on a battlefield owing its choice while it is asked")
        for _ in range(6):
            owed = game.waiting_prompt()
            if owed is None:
                break
            game.take_choice_default(owed)
        examined += 1
        if _owing(game):
            wrong.append(f"{name}: owing its choice after the answer")
    assert not wrong, "\n".join(wrong)
    assert examined >= 60, examined


def _shapeshifter(*, interactive: bool) -> Game:
    game = Game(players=[PlayerState(name="P0", hand=[_C["Shapeshifter"]]), PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    return game


def test_shapeshifter_at_a_bare_table_enters_with_its_default_and_owes_nothing():
    game = _shapeshifter(interactive=False)

    game.cast_from_hand(0, "Shapeshifter")
    resolve_stack(game)

    perm = game.players[0].battlefield[0]
    assert perm.metadata["chosen_number"] == 3, "the middle of the printed range"
    assert (perm.effective_power, perm.effective_toughness) == (3, 4)
    assert game.pending_choices_of("number_choice") == []
    assert not game.confirm_number_choice(0, 7), "nothing is left to answer after it entered"
    assert (perm.effective_power, perm.effective_toughness) == (3, 4)


def test_a_person_s_shapeshifter_enters_with_the_number_they_chose():
    game = _shapeshifter(interactive=True)

    game.cast_from_hand(0, "Shapeshifter")
    assert [choice.kind for choice in game.pending_choices] == ["number_choice"]
    assert not game.players[0].battlefield, "on its way while the number is owed"
    assert game.confirm_number_choice(0, 5)
    resolve_stack(game)

    perm = game.players[0].battlefield[0]
    assert (perm.effective_power, perm.effective_toughness) == (5, 2)

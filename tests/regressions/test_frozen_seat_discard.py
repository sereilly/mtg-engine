"""A triggered "**that player** discards a card" takes it from the seat the
event froze — not from whoever a targetless resolution happens to be carrying.

Found by PLS W1G7 driving Warped Devotion ("Whenever a permanent is returned to
a player's hand, that player discards a card"). The chosen-discard lowering
admitted ``that_player`` with **no event gate at all** — ``lowering/board.py``
said so in as many words, beside the sacrifice lowering that *does* gate it —
and let ``discard_target_cards`` read ``context.target``. Under a trigger nobody
targeted that is the ability controller's opponent, so:

* **Oppression** ("Whenever a player casts a spell, that player discards a
  card") made the *opponent* discard every time its own controller cast a spell;
* **Putrefaction** did the same for a green or white spell;
* **Anvil of Bogardan** drew its controller two cards on their own draw step
  and took the discard out of the opponent's hand.

All three compiled supported, resolved, and discarded exactly one card, which is
why no instrument saw it: the wrong seat is not a missing line, a hollow part or
a moved program. The seven ``damage_dealt`` cards beside them (Abyssal Specter's
family) were right in a duel by coincidence — the damaged player *is* the
default seat there — and wrong at a table of three.

The random half of the same sentence (``discard_x_target_cards``, Bottomless
Pit) had carried the gate since Mirage. This is the chosen half catching up.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compiled_units
from tests.helpers import resolve_stack


@pytest.fixture(scope="module")
def pool():
    found: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            found.setdefault(card.name, card)
    return found


def _table(pool, mine=(), theirs=(), *, hands=((), ())):
    filler = pool["Grizzly Bears"]
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[Permanent(card=pool[n]) for n in mine],
            hand=[pool[n] for n in hands[0]], library=[filler] * 8,
        ),
        PlayerState(
            name="P2", battlefield=[Permanent(card=pool[n]) for n in theirs],
            hand=[pool[n] for n in hands[1]], library=[filler] * 8,
        ),
    ])
    game.enforce_mana_costs = False
    return game


def _settle(game) -> None:
    for _ in range(8):
        resolve_stack(game)
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()
    raise AssertionError("the table did not settle")


def _zone(cards) -> list[str]:
    return sorted(card.name for card in cards)


def test_oppression_takes_the_card_from_whoever_cast_the_spell(pool):
    """Its own controller casting is the case that was wrong: the default seat
    is the *other* player."""
    game = _table(
        pool, mine=["Oppression"],
        hands=(("Lightning Bolt", "Forest"), ("Swamp",)),
    )

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _settle(game)

    assert _zone(game.players[0].graveyard) == ["Forest", "Lightning Bolt"]
    assert _zone(game.players[1].hand) == ["Swamp"]
    assert game.players[1].graveyard == []


def test_oppression_still_takes_it_from_an_opponent_who_casts(pool):
    """The control: the direction that happened to be right stays right."""
    game = _table(
        pool, mine=["Oppression"],
        hands=(("Forest",), ("Lightning Bolt", "Swamp")),
    )

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _settle(game)

    assert _zone(game.players[1].graveyard) == ["Lightning Bolt", "Swamp"]
    assert _zone(game.players[0].hand) == ["Forest"]


def test_putrefaction_takes_the_card_from_its_own_controller_too(pool):
    game = _table(
        pool, mine=["Putrefaction", "Grizzly Bears"],
        hands=(("Giant Growth", "Forest"), ("Swamp",)),
    )
    bears = next(p for p in game.players[0].battlefield if p.card.name == "Grizzly Bears")

    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    _settle(game)

    assert _zone(game.players[0].graveyard) == ["Forest", "Giant Growth"]
    assert _zone(game.players[1].hand) == ["Swamp"]


@pytest.mark.parametrize("active", [0, 1])
def test_anvil_of_bogardan_discards_from_the_player_whose_draw_step_it_is(pool, active):
    """"That player draws an additional card, then discards a card" — both
    halves are one seat's. On its controller's own draw step the draw went to
    them and the discard to the opponent."""
    game = _table(
        pool, mine=["Anvil of Bogardan"], hands=(("Forest",), ("Swamp",)),
    )
    game.turn = 2

    game.begin_turn_bookkeeping(active)
    game.resolve_untap_step(active)
    game.resolve_upkeep(active)
    game.resolve_draw_step(active)
    _settle(game)

    drawer, other = game.players[active], game.players[1 - active]
    # One card for the turn, one for the Anvil, one discarded: net +1.
    assert len(drawer.hand) == 2
    assert len(drawer.graveyard) == 1
    assert len(other.hand) == 1 and other.graveyard == []


# ---------------------------------------------------------------------------
# The census: no triggered chosen discard may leave its seat to the default
# ---------------------------------------------------------------------------


def _walk(instruction):
    yield instruction
    for value in instruction.payload.values():
        for step in value if isinstance(value, (tuple, list)) else (value,):
            if hasattr(step, "kind") and hasattr(step, "payload"):
                yield from _walk(step)


def _seatless_triggered_discards(cards) -> list[tuple[str, str, str]]:
    """``(card, condition kind, printed line)`` for every triggered ability
    whose effect holds a discard naming **no seat**: no ``who`` and no described
    ``targets``, so the handler falls to ``context.target``."""
    found = []
    for card, program in compiled_units(cards):
        if not program.supported:
            continue
        for trig in program.triggered_abilities:
            if trig.instruction is None:
                continue
            for step in _walk(trig.instruction):
                if step.kind not in ("discard_target_cards", "discard_x_target_cards"):
                    continue
                if "who" in step.payload or "targets" in step.payload:
                    continue
                found.append((card.name, trig.condition.kind, trig.source_line))
    return found


def test_no_triggered_that_player_discard_is_left_to_the_default_seat(pool):
    seatless = [
        row for row in _seatless_triggered_discards(pool.values())
        if "that player" in row[2].lower()
    ]
    assert seatless == [], (
        "a triggered 'that player discards' with no frozen seat discards from "
        f"whichever player the resolution is carrying: {seatless}"
    )


def test_the_census_examined_the_cards_it_is_about(pool):
    """A floor on what the sweep above looked at, and the cards it used to
    name: with the gate removed it reported exactly these ten, so a census that
    examines none of them and passes has stopped looking."""
    watched = {
        "Oppression", "Putrefaction", "Anvil of Bogardan", "Abyssal Specter",
        "Odylic Wraith", "Entropic Specter", "Order of Yawgmoth", "Larceny",
        "Chilling Apparition", "Blazing Specter", "Warped Devotion",
    }
    seated: set[str] = set()
    for card, program in compiled_units(pool.values()):
        if card.name not in watched or not program.supported:
            continue
        for trig in program.triggered_abilities:
            for step in _walk(trig.instruction):
                if step.kind == "discard_target_cards" and step.payload.get("who") in (
                    "event_subject_player", "damaged_player",
                    "event_subject_controller",
                ):
                    seated.add(card.name)
    assert seated == watched, sorted(watched - seated)

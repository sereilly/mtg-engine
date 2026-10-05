"""Pool-wide: what an AI seat chooses for a permanent's own entry trigger.

This engine names an entry trigger's target as the permanent is cast (the
standing approximation ``targeting._cast_target_spec`` documents), so for a
creature spell the cast's announcement *is* the trigger's choice — and the
spell-side choosers were written for spells. Three families, each found by
driving a Planeshift card and each already wrong on a shipped one:

* **A seat the trigger denies.** "When this creature enters, target player
  discards two cards" (Abyssal Horror; Thunderscape Battlemage's {1}{B}
  kicker). The spell scorer hands a creature spell's seat to its caster, so
  the AI discarded its own two cards; Gulf Squid tapped its own lands.
* **A several-target return.** "Return up to two target nonblack creatures to
  their owners' hands" (Nightscape Battlemage); "Return two target creatures
  to their owners' hands" (Undo). The several-target chooser had no side for a
  bounce and took two of the caster's own.
* **A gate.** "When this creature enters, return a <noun> you control to its
  owner's hand" (Planeshift's ten gating creatures; Shrieking Drake). The
  entering permanent is itself a legal answer, so cast onto a board with no
  other, it comes straight back — and the seat casts it again next turn.

Every census is derived from the compiled program, carries a floor on what it
examined, and names the shipped card that was failing, so a derivation that
drifts to an empty or different population is a failure rather than a pass.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _cast_candidate, given_back_first
from engine.ai_valuation import (entry_self_return_gate,
                                 entry_trigger_seat_side,
                                 several_target_slot_sides)
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.tokens import make_token_card
from tests.helpers import resolve_stack

_SEAT_DENIAL_FLOOR = 8
_GATE_FLOOR = 10


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


def _table(pool, hand, *, free_mana: bool = True) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("AI", library=[forest] * 30, hand=list(hand)),
        PlayerState("Other", library=[forest] * 30, hand=[forest, forest, forest]),
    ])
    game.enforce_mana_costs = not free_mana
    return game


def _put(game, pool, seat, name) -> Permanent:
    permanent = Permanent(card=pool[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _supported_permanents(pool):
    for card in pool.values():
        if card.primary_type in ("instant", "sorcery", "land"):
            continue
        if compile_card_oracle(card).supported:
            yield card


def test_an_entry_trigger_that_denies_a_player_is_aimed_at_an_opponent(pool):
    """For every permanent whose cast names a player its entry trigger denies
    (``entry_trigger_seat_side``): the candidate the AI builds names a seat
    that is not its own — on a symmetric board, with every optional cost the
    policy would take."""
    examined = []
    for card in _supported_permanents(pool):
        if entry_trigger_seat_side(card) != "opponent":
            continue
        game = _table(pool, [card])
        for seat in (0, 1):
            for name in ("Grizzly Bears", "Forest", "Sol Ring", "Castle"):
                _put(game, pool, seat, name)
        action = _cast_candidate(game, 0, card, 0)
        assert action is not None, card.name
        assert action.target_player_index == 1, card.name
        examined.append(card.name)
    assert len(examined) >= _SEAT_DENIAL_FLOOR, examined
    # The two shipped cards that discarded and tapped their own controller.
    assert {"Abyssal Horror", "Gulf Squid"} <= set(examined)


def test_abyssal_horror_makes_the_opponent_discard(pool):
    """The defect, played out: an AI seat casts Abyssal Horror and it is the
    *other* seat that loses two cards."""
    game = _table(pool, [pool["Abyssal Horror"]])
    action = _cast_candidate(game, 0, pool["Abyssal Horror"], 0)
    result = game.queue_from_hand(
        0, action.card_name, target_player_index=action.target_player_index
    )
    assert result.supported, result
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 2
    assert game.players[0].graveyard == []


def test_a_several_target_return_names_the_opponents_creatures(pool):
    """Undo ("Return two target creatures to their owners' hands") on a board
    where each seat controls two: both slots want an opponent's creature, and
    the AI names the opponent's two rather than its own."""
    assert several_target_slot_sides(compile_card_oracle(pool["Undo"])) == (
        "opponent", "opponent",
    )
    game = _table(pool, [pool["Undo"]])
    mine = [_put(game, pool, 0, name) for name in ("Grizzly Bears", "Hill Giant")]
    theirs = [_put(game, pool, 1, name) for name in ("Serra Angel", "Craw Wurm")]
    action = _cast_candidate(game, 0, pool["Undo"], 0)
    assert action is not None and action.target_player_index == 1
    named = sorted(
        game.permanent_at(game.players[1], slot).card.name
        for slot in action.target_permanent_index
    )
    assert named == ["Craw Wurm", "Serra Angel"]

    assert all(game.is_on_battlefield(p) for p in mine + theirs)

    # …and with a single opposing creature beside its own pair, it is still
    # the opponent's side the spell is pointed at, never the pair.
    lonely = _table(pool, [pool["Undo"]])
    for name in ("Grizzly Bears", "Hill Giant"):
        _put(lonely, pool, 0, name)
    _put(lonely, pool, 1, "Serra Angel")
    aimed = _cast_candidate(lonely, 0, pool["Undo"], 0)
    assert aimed is None or aimed.target_player_index == 1


@pytest.fixture(scope="module")
def gates(pool) -> list:
    found = [
        card for card in _supported_permanents(pool)
        if entry_self_return_gate(card) is not None
    ]
    assert len(found) >= _GATE_FLOOR, [card.name for card in found]
    # The shipped original of Planeshift's mechanic.
    assert "Shrieking Drake" in {card.name for card in found}
    return found


def test_a_gate_is_not_cast_to_return_itself(pool, gates):
    """Onto an empty board every gate's only legal answer is the permanent
    that asked, so the cast ends with the card back in hand: not proposed."""
    for card in gates:
        game = _table(pool, [card])
        assert _cast_candidate(game, 0, card, 0) is None, card.name


def test_a_gate_is_cast_when_something_cheaper_can_go_back(pool, gates):
    """…and proposed once the board holds a cheaper permanent its noun admits:
    for every *creature* gate, a one-drop of a colour it names."""
    one_drops = {
        "W": "Savannah Lions", "U": "Merfolk of the Pearl Trident",
        "B": "Will-o'-the-Wisp", "R": "Goblin Balloon Brigade",
        "G": "Llanowar Elves",
    }
    examined = 0
    for card in gates:
        described = entry_self_return_gate(card).get("filter") or {}
        if described.get("type_filter") != "creature":
            continue
        colours = described.get("any_colors") or list(one_drops)
        game = _table(pool, [card])
        _put(game, pool, 0, one_drops[colours[0]])
        action = _cast_candidate(game, 0, card, 0)
        assert action is not None and action.card_name == card.name, card.name
        examined += 1
    assert examined >= _GATE_FLOOR


def test_a_seat_nobody_asks_gives_back_the_smallest_loss(pool):
    """``given_back_first``, the valuation behind a headless gate: the asking
    permanent last, then the cheapest card, and a token — which does not come
    back (CR 111.7) — priced as the body it is rather than as free."""
    game = _table(pool, [])
    wurm = _put(game, pool, 0, "Craw Wurm")
    elves = _put(game, pool, 0, "Llanowar Elves")
    bears = _put(game, pool, 0, "Grizzly Bears")
    asking = _put(game, pool, 0, "Serra Angel")
    order = given_back_first([wurm, asking, bears, elves], asking)
    assert [p.card.name for p in order] == [
        "Llanowar Elves", "Grizzly Bears", "Craw Wurm", "Serra Angel",
    ]

    token = Permanent(card=make_token_card("Bear", 2, 2, "Token Creature — Bear"))
    token.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(0, token, None)
    # A 2/2 token is a bigger loss than a one-drop and a smaller one than a
    # six-drop: it is given up between them, never first for costing nothing.
    assert [p is token for p in given_back_first([wurm, token, elves], asking)] == [
        False, True, False,
    ]


def test_shrieking_drake_gives_back_the_cheaper_creature(pool):
    """The shipped card the gate valuation reaches: Shrieking Drake entering
    beside a Craw Wurm and a Llanowar Elves returns the Elves — it used to
    return the Wurm, which had been on the battlefield longest."""
    game = _table(pool, [pool["Shrieking Drake"]])
    _put(game, pool, 0, "Craw Wurm")
    _put(game, pool, 0, "Llanowar Elves")
    assert game.queue_from_hand(0, "Shrieking Drake").supported
    resolve_stack(game)
    assert [c.name for c in game.players[0].hand] == ["Llanowar Elves"]
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Craw Wurm", "Shrieking Drake",
    ]

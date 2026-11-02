"""The rest of the engine's multi-recipient damage, driven board by board (kg3
`dealings`): each is one simultaneous dealing (``engine/simultaneous_damage``),
so a trigger naming one end of the event fires once, for that end's total.

* The Fallen's upkeep point to each opponent it has damaged — Spirit Link sees
  it once;
* Cuombajj Witches' two halves, the second chosen by an opponent — once, with
  the default opponent and with an interactive one whose answer comes later
  (the dealing waits for it: ``opponent_damage`` suspends);
* Kaervek's Hex, "1 damage to each nonblack creature and an additional 1
  damage to each green creature" — a green Fungusaur is dealt 2 at once and
  grows one counter (its ruling, 2004-10-04: "If more than one creature
  damages it at one time, it only gets one counter"; the Hex's own,
  2013-04-15, has a black-and-green creature dealt 1, not 1 and 0);
* the excused loop: Mana Clash's flips stay one event per point ("Each point
  of damage is dealt separately", 2004-10-04), so Justice still answers each;
* a damage event re-run on an answer keeps its spell's controller (CR 109.5):
  the resumed half of a divided Fireball is recorded as P0's.

Validated backwards on 7d311d9f: The Fallen, the Witches and the Hex fail
there (two Spirit Link gains, two Fungusaur counters), and the resumed chunk
was recorded with no seat. The Mana Clash board passes on both, as an
exemption should.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.damage_events import DAMAGED_THIS_GAME
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.shields import add_shield, make_counting_pool, make_numeric_pool
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _table(seats: int = 2, *, interactive=()) -> Game:
    island = _POOL["Island"]
    game = Game(players=[
        PlayerState(f"P{seat}", library=[island] * 10) for seat in range(seats)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _lines(game: Game, text: str) -> list[str]:
    return [line for line in game.log if text in line]


def test_the_fallen_deals_its_upkeep_points_as_one_dealing():
    """Three seats, The Fallen having damaged both opponents: one point each
    at once, so Spirit Link on it gains 2 once."""
    game = _table(3)
    fallen = _put(game, 0, _POOL["The Fallen"])
    fallen.metadata[DAMAGED_THIS_GAME] = {"seats": [1, 2], "permanents": []}
    attach_aura(_put(game, 0, _POOL["Spirit Link"]), fallen)
    game._sync_control()

    game.resolve_upkeep(0)
    resolve_stack(game)

    assert (game.players[1].life, game.players[2].life) == (19, 19)
    assert _lines(game, "from Spirit Link") == ["P0 gained 2 life from Spirit Link (20 -> 22)"]


@pytest.mark.parametrize("interactive", [(), (1,)], ids=["default", "interactive"])
def test_cuombajj_witches_two_halves_are_one_dealing(interactive):
    """"{T}: This creature deals 1 damage to any target and 1 damage to any
    target of an opponent's choice." One sentence, one source: Spirit Link
    gains 2 once — and with an interactive opponent, only once the opponent
    has answered, the dealing staying open across the prompt."""
    game = _table(interactive=interactive)
    witches = _put(game, 0, _POOL["Cuombajj Witches"])
    attach_aura(_put(game, 0, _POOL["Spirit Link"]), witches)
    game._sync_control()

    result = game.activate_permanent_ability(0, "Cuombajj Witches", target_player_index=1)
    assert result.supported, result.details
    if interactive:
        assert game.pending_choices_of("opponent_damage", 1)
        assert game.simultaneous_damage is not None
        assert not _lines(game, "from Spirit Link")
        assert game.confirm_opponent_damage_choice(1, target_seat=0)
    resolve_stack(game)

    assert game.players[1].life == 19
    assert _lines(game, "from Spirit Link") == ["P0 gained 2 life from Spirit Link (19 -> 21)"]
    assert game.simultaneous_damage is None


def test_kaervek_s_hex_is_dealt_to_a_green_creature_once():
    """A green Fungusaur (2/2 with two +1/+1 counters) is dealt 1 for being
    nonblack and 1 more for being green, at once: one "whenever this creature
    is dealt damage" trigger, one counter. On the base, two."""
    game = _table()
    fungusaur = _put(game, 1, _POOL["Fungusaur"])
    game.place_plus1_counters(fungusaur, 2)
    game.players[0].hand.append(_POOL["Kaervek's Hex"])
    game._sync_control()

    result = game.cast_from_hand(0, "Kaervek's Hex")
    assert result.supported, result.details
    resolve_stack(game)

    assert fungusaur.damage_marked == 2
    assert counters_on(fungusaur, "+1/+1") == 3


def test_mana_clash_stays_one_event_per_point(monkeypatch):
    """The exemption: Mana Clash's ruling makes each point its own damage
    event, so both players' tails in one round are two events — Justice deals
    its damage twice — and the next round (both heads) ends it."""
    import engine.handlers.damage as damage_handlers

    flips = iter([False, False, True, True])
    monkeypatch.setattr(damage_handlers, "flip_coin", lambda *a, **k: next(flips))
    game = _table()
    _put(game, 1, _POOL["Justice"])
    game.players[0].hand.append(_POOL["Mana Clash"])
    game._sync_control()

    result = game.cast_from_hand(0, "Mana Clash", target_player_index=1)
    assert result.supported, result.details
    resolve_stack(game)

    assert _lines(game, "Justice dealt") == [
        "Justice dealt 1 damage to P0", "Justice dealt 1 damage to P0",
    ]


def test_a_resumed_spell_s_damage_keeps_its_controller():
    """Fireball divided between P1 (two prevention shields: asked, CR 616.1e)
    and P2. Both chunks are dealt from the answer, after the resolution that
    asked had returned — and both are still P0's damage (CR 109.5): the turn's
    ledger records the seat, which on the base was None."""
    game = _table(3, interactive=(1,))
    add_shield(game.players[1], make_numeric_pool(1, source_name="Test Pool A"))
    add_shield(game.players[1], make_counting_pool(1, "+1/+1", source_name="Test Pool B"))
    game.players[0].hand.append(_POOL["Fireball"])

    result = game.cast_from_hand(
        0, "Fireball", x_value=6, divided_targets=[(1, None), (2, None)],
    )
    assert result.supported, result.details
    assert game.resolve_pending_choice("effect_order", 1, option_index=0)
    resolve_stack(game)

    fireball = [e for e in game.damage_ledger.entries if e.source_name == "Fireball"]
    assert [(e.recipient_seat, e.amount, e.source_seat) for e in fireball] == [
        (1, 1, 0), (2, 3, 0),
    ]

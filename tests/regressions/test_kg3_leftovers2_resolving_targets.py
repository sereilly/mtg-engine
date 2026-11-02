"""What a resolving spell targets is known while an answer re-runs its event.

``Game.resolving_targets`` is the seam ``_execute_oracle_instruction`` pushes
around every instruction (CR 115.1: what the object chose), because a spell
reaches the damage paths as its printed card, which records nothing about its
targets. "Prevent all damage that would be dealt to this creature by spells
that target it" (Bronze Horse) reads it.

kg3/dealings restored the resolving *seat* while a prompt's answer re-runs the
event that asked and the loop behind it (``_answer_inside_its_window``, from
the prompt's ``_cause_seat``), and left the targets: by then the instruction
had returned and the seam was empty. Measured on 90bef6d1:

* a Lightning Bolt at a Bronze Horse that also carries a prevention pool:
  the two effects contend (CR 616.1e), the Horse's controller (a person)
  applies the Horse's first — and in the re-run event the Horse's static no
  longer saw a spell that targets it, so the pool prevented 1 and the Horse
  was dealt 2. A seat nobody asks took all 3 off with the Horse's static;
* beside it: a divided Fireball split between the Horse and its controller
  dealt the Horse its share with nothing asked at all — a divided spell's
  targets ride ``choices["divided_targets"]``, which the seam never read;
* and the CR 614 replacement queue stamped neither the seat nor the targets
  (``offer_replacement_choice``), so damage dealt after a replacement
  choice's answer had no source seat.

The seam now reads the divided targets too, and both queues stamp what was
resolving when a prompt was armed (``replacement_choices.stamp_resolving``),
which the answer pushes back for its length.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.shields import add_shield, make_numeric_pool
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _table(*, interactive=()) -> Game:
    island = _POOL["Island"]
    game = Game(players=[
        PlayerState(f"P{seat}", library=[island] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _horse(game: Game) -> Permanent:
    horse = _put(game, 1, "Bronze Horse")
    _put(game, 1, "Grizzly Bears")  # "as long as you control another creature"
    game._sync_control()
    return horse


def _bolt_the_shielded_horse(game: Game) -> Permanent:
    horse = _horse(game)
    add_shield(horse, make_numeric_pool(1, source_name="Test Pool"))
    game.players[0].hand.append(_POOL["Lightning Bolt"])
    result = game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[horse.permanent_id])
    assert result.supported, result.details
    return horse


def test_a_person_who_applies_the_horse_first_takes_no_damage():
    game = _table(interactive=(1,))
    horse = _bolt_the_shielded_horse(game)
    choice = game.pending_choice_of("effect_order", 1)
    assert choice is not None, game.log
    assert horse.damage_marked == 0, "nothing is dealt until the answer"

    # The Horse's own static, "…by spells that target it", first.
    assert game.resolve_pending_choice("effect_order", 1, option_index=0)
    resolve_stack(game)

    assert horse.damage_marked == 0, game.log[-6:]
    assert any("Bronze Horse prevented" in line for line in game.log), game.log[-6:]


def test_a_seat_nobody_asks_takes_none_either():
    """The control: the default answer is the Horse's static, applied on the
    first run of the event."""
    game = _table()
    horse = _bolt_the_shielded_horse(game)
    resolve_stack(game)

    assert horse.damage_marked == 0, game.log[-6:]


def test_a_divided_spell_targets_each_creature_it_divides_damage_to():
    """Fireball's 4 split between the Horse and its controller: the Horse's
    share is dealt by a spell that targets it, and is prevented."""
    game = _table()
    horse = _horse(game)
    game.players[0].hand.append(_POOL["Fireball"])
    slot = game.battlefield_index_of(horse)

    result = game.cast_from_hand(0, "Fireball", x_value=4, divided_targets=[(1, slot), (1, None)])
    assert result.supported, result.details
    resolve_stack(game)

    assert horse.damage_marked == 0, game.log[-6:]
    assert game.players[1].life == 18, "the face's share is dealt"


def test_damage_dealt_after_a_replacement_choice_keeps_its_spell_s_controller():
    """Blood of the Martyr ("you may have that damage dealt to you instead")
    offers its choice for each creature a divided Fireball hits; the share
    dealt from the answer is still P0's damage (CR 109.5, CR 120.7), as the
    turn's ledger records. Backwards on 90bef6d1 its seat was None."""
    game = _table(interactive=(1,))
    first, second = _put(game, 0, "Grizzly Bears"), _put(game, 0, "Hill Giant")
    game._sync_control()
    game.players[1].hand.append(_POOL["Blood of the Martyr"])
    game.active_player_index = 1
    assert game.cast_from_hand(1, "Blood of the Martyr").supported
    resolve_stack(game)
    game.players[0].hand.append(_POOL["Fireball"])
    game.active_player_index = 0

    result = game.cast_from_hand(
        0, "Fireball", x_value=4,
        divided_targets=[(0, game.battlefield_index_of(first)), (0, game.battlefield_index_of(second))],
    )
    assert result.supported, result.details
    for _ in range(4):
        if not game.pending_replacement_choices:
            break
        assert game.resolve_replacement_choice(1, 0)
    resolve_stack(game)

    fireball = [e for e in game.damage_ledger.entries if e.source_name == "Fireball"]
    assert fireball, game.log[-8:]
    assert {e.source_seat for e in fireball} == {0}, [(e.recipient_seat, e.amount, e.source_seat) for e in fireball]

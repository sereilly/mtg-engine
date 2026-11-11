"""Darksteel W1G9: two back-references, each read off its producer's record or
refused.

* "**Sacrifice those creatures** …" read as the sacrifice prompt was "sacrifice
  a creature of your choice" — the plural back-reference dropped and the card
  compiling supported, the failure the singular "that creature" was already
  refused for (``lowering/board._lower_sacrifice``). Tears of Rage's producer,
  the global buff's record (``oracle_types.BUFFED_THIS_WAY_PERMANENTS``), is
  what admits it now; with no producer it refuses.
* "**Put that card** onto the battlefield" names the card Scrounge's pick
  recorded (``oracle_types.CHOSEN_GRAVEYARD_CARD``); with no pick in front of
  it and no event that froze one, it refuses as before.

Invented card texts, because the point is the refusal a printed card does not
show: no shipped card prints either sentence without its producer.
"""

from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card


def _program(text: str, type_line: str = "Instant"):
    return compile_card_oracle(_mk_card("W1G9 Probe", type_line, text))


def _kinds(instruction) -> list[str]:
    found = [instruction.kind]
    for value in instruction.payload.values():
        items = value if isinstance(value, (list, tuple)) else (value,)
        for item in items:
            if hasattr(item, "kind") and hasattr(item, "payload"):
                found.extend(_kinds(item))
    return found


def test_sacrifice_those_creatures_with_no_producer_refuses():
    assert not _program(
        "Sacrifice those creatures at the beginning of the next end step."
    ).supported
    assert not _program("Sacrifice those creatures.").supported


def test_sacrifice_those_creatures_reads_the_global_buffs_record():
    program = _program(
        "Creatures you control get +1/+0 until end of turn. Sacrifice those "
        "creatures at the beginning of the next end step."
    )
    assert program.supported
    kinds = [kind for each in program.instructions for kind in _kinds(each)]
    assert "sacrifice_recorded_permanents" in kinds
    assert "sacrifice_matching_permanent" not in kinds


def test_put_that_card_with_no_pick_in_front_refuses():
    assert not _program(
        "Put that card onto the battlefield under your control.", "Sorcery"
    ).supported


def test_a_graveyard_pick_from_another_pile_refuses():
    # "Your graveyard" is Forgotten Lore's paragraph's, and the pick's AI
    # default (the chooser's own pile, least valuable first) answers only the
    # chooser's own pile.
    assert not _program(
        "Target opponent chooses an artifact card in your graveyard. Put that "
        "card onto the battlefield under your control.", "Sorcery",
    ).supported

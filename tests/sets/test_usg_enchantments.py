"""Urza's Saga enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The seven Runes of Protection plus Sicken and Power Taint. The Runes are the
#: shape worth naming: each prints a real activated ability *and* cycling, so
#: after the rewrite the compiled order is [{W} prevention, cycling] and the
#: battlefield list must be the first alone. All seven reported supported
#: before the rewrite with the keyword unclaimed; Sicken and Power Taint were
#: refused, because an Aura is gated on every effect line being claimed and
#: "cycling {2}" was not one the Aura reader knew.
_G1_RUNES = (
    "Rune of Protection: Artifacts",
    "Rune of Protection: Black",
    "Rune of Protection: Blue",
    "Rune of Protection: Green",
    "Rune of Protection: Lands",
    "Rune of Protection: Red",
    "Rune of Protection: White",
)


def _g1_ench_game(card, *, library=4):
    """Seat 0 holds *card*; the library is copies of it. Distinct to this block."""
    holder = PlayerState(name="G1-E", hand=[card], library=[card] * library)
    duel = Game(players=[holder, PlayerState(name="G1-F")])
    duel.enforce_mana_costs = False
    return duel, holder


@pytest.mark.parametrize("name", _G1_RUNES)
def test_w1g1_a_rune_of_protection_keeps_its_own_ability_and_gains_cycling(
    set_pool, name
):
    """Two abilities, two zones, and the index has to be right in both.

    ``usable_activated_abilities`` is what the web layer and the AI number an
    ability by. If cycling were left in a Rune's battlefield list the prevention
    ability would still be index 0 — but the second entry would be an ability
    the engine refuses, and the {2} the client collected for it would be spent
    on nothing.
    """
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason

    battlefield = usable_activated_abilities(program)
    assert len(battlefield) == 1
    assert battlefield[0].source_line.startswith("{W}: The next time")
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    duel, holder = _g1_ench_game(card)
    assert duel.activate_from_hand(0, name).supported
    resolve_stack(duel)
    assert [c.name for c in holder.graveyard] == [name]
    assert len(holder.library) == 3


@pytest.mark.parametrize("name", ("Sicken", "Power Taint"))
def test_w1g1_a_cycling_aura_is_supported_and_cycles(set_pool, name):
    """An Aura is unsupported unless every effect line is claimed
    (``engine/auras.py``), and "cycling {2}" was refused there — so these two
    were unsupported for a keyword rather than for their Aura text. The rewrite
    turns the line into an activated ability before the Aura gate reads it."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    duel, holder = _g1_ench_game(card)
    assert duel.activate_from_hand(0, name).supported
    resolve_stack(duel)
    assert [c.name for c in holder.graveyard] == [name]
    assert len(holder.library) == 3


def test_w1g1_veiled_serpent_cycles_but_its_trigger_is_still_unread(set_pool):
    """Half a card, said out loud.

    Veiled Serpent's cycling line is W1G1's and its "becomes a 4/4 Serpent
    creature with …" trigger is W1G3's. The rewrite makes the card report
    *supported* — a card is supported when any of its lines is — while the
    trigger it is famous for is still unimplemented. That is a real cost of
    this change and it is asserted here rather than left to be discovered:
    ``parse_coverage.py --set USG`` is the instrument that still sees it, and
    this test fails the day the other half lands, which is when the claim below
    stops being true.
    """
    program = compile_card_oracle(set_pool("USG")["Veiled Serpent"])
    assert program.supported
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]
    assert program.triggered_abilities
    assert all(not trig.supported for trig in program.triggered_abilities)

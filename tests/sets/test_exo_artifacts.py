"""Exodus artifacts.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: an anthem counted per buffed creature ----------------------------

from engine import Game as _G4aGame, PlayerState as _G4aPlayer
from engine.grammar.derived import derived_instruction_for_line as _g4a_derived
from engine.models import Permanent as _G4aPerm


def _g4a_perm(card):
    """A permanent already on the battlefield, past its summoning sickness."""
    permanent = _G4aPerm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _g4a_board(mine=(), theirs=()):
    """Two seats with the layers computed, and nothing else going on."""
    p0 = _G4aPlayer(name="G4a-P0", battlefield=list(mine), life=20)
    p1 = _G4aPlayer(name="G4a-P1", battlefield=list(theirs), life=20)
    game = _G4aGame(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    game._refresh_dynamic_creatures()
    # This block's own closing pair (W1G4, artifacts).
    game.check_state_based_actions()
    return game, p0, p1


def test_w1g4_coat_of_arms_counts_shared_types_per_creature(set_pool):
    """"Each creature gets +1/+1 for each other creature on the battlefield
    that shares at least one creature type with it."

    The one scale in the lord-buff family counted **per buffed creature**: the
    set it counts is defined by a relation to the creature being buffed, so two
    creatures under the same Coat of Arms take different numbers and the
    multiply cannot be lifted out of the loop the way ``per_counter``'s is.

    Every battlefield, because the printed phrase names none, and a creature
    sharing nothing gets nothing.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    coat = _g4a_perm(exo["Coat of Arms"])
    goblin_one = _g4a_perm(lea["Goblin Balloon Brigade"])
    goblin_two = _g4a_perm(lea["Goblin Balloon Brigade"])
    bear = _g4a_perm(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4a_board(
        mine=[coat, goblin_one, bear], theirs=[goblin_two]
    )

    # Each Goblin sees exactly one other Goblin — across the two battlefields.
    assert (goblin_one.effective_power, goblin_one.effective_toughness) == (2, 2)
    assert (goblin_two.effective_power, goblin_two.effective_toughness) == (2, 2)
    # The Bear shares a type with nobody, so it takes nothing.
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_w1g4_coat_of_arms_scales_with_the_third_of_a_type(set_pool):
    """Three of a type is +2/+2 each, which is the reminder text's own worked
    example — and the thing a scale lifted out of the per-creature loop could
    not produce."""
    exo, lea = set_pool("EXO"), set_pool("LEA")
    goblins = [_g4a_perm(lea["Goblin Balloon Brigade"]) for _ in range(3)]
    game, _p0, _p1 = _g4a_board(mine=[_g4a_perm(exo["Coat of Arms"]), *goblins])

    for goblin in goblins:
        assert (goblin.effective_power, goblin.effective_toughness) == (3, 3)


def test_w1g4_a_derived_line_is_read_past_its_reminder_text(set_pool):
    """The derivation tables strip reminder text, and used to say somebody else
    did.

    ``derived.py``'s normalizer read "reminder text is already gone by the time
    the parser is reached" — true of the productions, which read the lexer's
    tokens, and false here: ``parse_line`` hands the table the line it was
    given. Every matcher is anchored at both ends, so the result was a silent
    non-match, invisible until a card printed a derived line with a reminder on
    it. Coat of Arms is the first.
    """
    printed = set_pool("EXO")["Coat of Arms"].oracle_text

    assert "(For example" in printed, "the reminder is what this test is about"
    derived = _g4a_derived(printed)

    assert derived is not None
    table, instruction = derived
    assert table == "lord_buffs"
    assert instruction.payload["per_shared_creature_type"] is True

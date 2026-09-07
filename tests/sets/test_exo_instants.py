"""Exodus instants.

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


# --- W1G4: counted quantities with a multiplier -----------------------------

import pytest

from engine import Game as _G4iGame, PlayerState as _G4iPlayer
from engine.grammar import parse_line as _g4i_parse
from engine.grammar.errors import LoweringError as _G4iLoweringError
from engine.grammar.lower import lower_ability as _g4i_lower
from engine.models import Permanent as _G4iPerm

from tests.helpers import resolve_stack as _g4i_resolve


def _g4i_land(card):
    """A land already on the battlefield."""
    permanent = _G4iPerm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _g4i_duel(mine=(), theirs=(), hand=()):
    """Two seats, P0 to act, mana costs off."""
    p0 = _G4iPlayer(name="G4i-P0", battlefield=list(mine), life=20, hand=list(hand))
    p1 = _G4iPlayer(name="G4i-P1", battlefield=list(theirs), life=20)
    game = _G4iGame(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.priority_player_index = 0
    game._sync_control()
    # A closing pair that is this block's alone (W1G4, instants).
    game._refresh_dynamic_creatures()
    return game, p0, p1


def test_w1g4_price_of_progress_doubles_each_seats_nonbasic_count(set_pool):
    """"...deals damage to each player equal to **twice** the number of
    nonbasic lands that player controls."

    A printed multiplier over a counted quantity. The factor is unwrapped in
    the damage lowering and handed to ``count_spec``, which already carries a
    ``multiplier`` (CR 107.3) applied once by ``_scaled`` -- so no handler
    learns a key and the per-recipient loop scales without knowing it can.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    mine = [_g4i_land(lea["Mountain"]), _g4i_land(lea["Badlands"])]
    theirs = [_g4i_land(lea["Badlands"]), _g4i_land(lea["Tundra"]),
              _g4i_land(lea["Forest"])]
    game, p0, p1 = _g4i_duel(mine=mine, theirs=theirs,
                             hand=[exo["Price of Progress"]])

    assert game.cast_from_hand(0, "Price of Progress").supported
    _g4i_resolve(game)

    # One nonbasic for the caster, two for the opponent, doubled either way.
    assert p0.life == 18
    assert p1.life == 16


def test_w1g4_a_multiplier_over_something_that_is_not_a_count_refuses():
    """The factor is admitted only in front of a definition that can carry one.

    ``count_spec`` is where a multiplier lives, so a ``Times`` over a
    back-reference has nowhere to put it -- and dropping the word would be half
    the damage the card prints. It refuses in the lowering instead, which is
    the loud direction: the sentence is read in full and then declined by name.
    """
    node = _g4i_parse(
        "This creature deals damage to any target equal to twice the damage "
        "dealt."
    )

    with pytest.raises(_G4iLoweringError, match="Times"):
        _g4i_lower(node)


def test_w1g4_the_unmultiplied_printing_is_byte_identical():
    """Reading a multiplier in front of every "equal to ..." definition must
    leave the definitions themselves untouched.

    Karma's fused kind is the case that would show a change first: it carries
    no number of its own, so it is guarded on ``multiplier == 1`` and a plain
    printing has to keep reaching it.
    """
    node = _g4i_parse(
        "At the beginning of each player's upkeep, this enchantment deals "
        "damage to that player equal to the number of Swamps they control."
    )
    instructions = _g4i_lower(node)

    assert [i.kind for i in instructions] == ["deal_damage_equal_to_swamps"]
    assert instructions[0].payload == {}


# --- W1G4 (cont.): a quoted ability granted to a described set --------------

from engine.models import Permanent as _G4rPerm
from engine.oracle import compile_card_oracle as _g4r_compile
from engine.targeting import derive_cast_spec as _g4r_cast_spec


def _g4r_creature(card):
    """A creature already on the battlefield."""
    permanent = _G4rPerm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g4_resuscitate_grants_only_the_casters_creatures(set_pool):
    """"Until end of turn, creatures you control gain "{1}: Regenerate this
    creature.""

    A *described* set rather than a chosen one: nothing is targeted, and the
    board is walked as the effect resolves (CR 611.2c fixes the members then).
    The same layer-6 addition ``grant_team_keyword_until_eot`` already makes
    with a keyword, so it is the same kind with a filter on the payload — one
    reader of what the noun phrase means, one place a quoted ability is
    recorded.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    mine, theirs = _g4r_creature(lea["Grizzly Bears"]), _g4r_creature(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4i_duel(mine=[mine], theirs=[theirs],
                               hand=[exo["Resuscitate"]])

    assert game.cast_from_hand(0, "Resuscitate").supported
    _g4i_resolve(game)

    granted = [
        a.source_line for a in _g4r_compile(mine.effective_card).activated_abilities
    ]
    assert granted == ["{1}: Regenerate this creature"]
    assert not (theirs.effective_card.oracle_text or "").strip(), (
        '"you control" is a narrowing, and a dropped one would reach the table'
    )

    result = game.activate_permanent_ability(0, "Grizzly Bears", ability_index=0)
    assert result.supported, result.details
    _g4i_resolve(game)
    assert any("regeneration shield" in line for line in game.log), game.log


def test_w1g4_resuscitate_announces_no_target(set_pool):
    """The Cleanse class, in the direction the picker sweep watches.

    ``grant_target_ability_text`` serves four printings and only one of them
    chooses; answering "creature" for a described set puts a picker in front of
    a spell that targets nothing, and the prompt then aborts the cast on a
    board with no creature at all.
    """
    resuscitate = set_pool("EXO")["Resuscitate"]

    assert _g4r_cast_spec(resuscitate, _g4r_compile(resuscitate)) is None

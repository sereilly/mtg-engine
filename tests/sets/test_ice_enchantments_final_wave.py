"""Ice Age (ICE) enchantment cards — the final wave.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it.

The third file of the printed type, and the split is the one
``test_ice_creatures_final_wave.py`` already made: tests/sets/README.md's axis
after the printed type is a round boundary, and for this set that is a *wave*
boundary. The serial rounds and the first parallel wave are in
``test_ice_enchantments_early_rounds.py``, the second and third waves in
``test_ice_enchantments.py`` — which reached 2,353 lines — and the final wave
here. Sections are named for the wave and group that bought them
(``W<wave>G<group>``) rather than for a round, because the work ran in parallel
worktrees from that point on.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- W4G1: a reanimation that names what it created, and cannot let it go ---
#
# Dreams of the Dead. "{1}{U}: Return target white or black creature card from
# your graveyard to the battlefield. That creature gains "Cumulative upkeep
# {2}." If the creature would leave the battlefield, exile it instead of
# putting it anywhere else."
#
# Three sentences, and the last two are about a permanent that did not exist
# when the ability was activated — the ability's *target* is a card in a
# graveyard. So the reanimation records what it created and the sentences
# behind it read that record.
#
# The third sentence is a CR 614 replacement with no single fire site: a
# permanent's card leaves the battlefield for a graveyard, a hand or a library,
# and each is its own seam. The completeness of that set is
# ``tests/engine/test_leave_battlefield_seam.py``'s job; what is checked here
# is that each destination actually exiles.


def _dreams_board(set_pool, *graveyard_names):
    """Dreams of the Dead on the battlefield with a named graveyard behind it."""
    pool = set_pool("ICE")
    dreams = Permanent(card=pool["Dreams of the Dead"])
    p1 = PlayerState(
        name="P1", battlefield=[dreams], life=20,
        graveyard=[pool[name] for name in graveyard_names],
    )
    p2 = PlayerState(name="P2", battlefield=[], life=20)
    game = Game(players=[p1, p2])
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    return game, p1, p2


def _reanimate(game, graveyard_index=0):
    game.players[0].mana_pool = {"W": 0, "U": 1, "B": 0, "R": 0, "G": 0, "C": 1}
    game.activate_permanent_ability(
        0, "Dreams of the Dead", target_permanent_index=graveyard_index
    )
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return next(
        (
            perm for perm in game.players[0].battlefield
            if perm.card.name != "Dreams of the Dead"
        ),
        None,
    )


def test_w4g1_dreams_of_the_dead_compiles_all_three_sentences(set_pool):
    """The colour narrowing is payload, the grant reads the reanimation's own
    record, and the replacement folds onto the move that creates its subject."""
    program = compile_card_oracle(set_pool("ICE")["Dreams of the Dead"])

    assert program.supported
    (ability,) = program.activated_abilities
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "reanimate_creature", "grant_target_ability_text",
    ]
    assert steps[0].payload == {"colors": ("W", "B"), "exile_on_leave": True}
    assert steps[1].payload["abilities"] == ("Cumulative upkeep {2}",)
    # Not a target: the ability's target is a card in a graveyard, and the
    # grant is about the permanent the first step created.
    assert "targets" not in steps[1].payload
    assert steps[1].payload["permanents_from"] == "reanimated_permanents"


def test_w4g1_the_picker_offers_only_white_and_black_creature_cards(set_pool):
    """The printed adjective, in the place a dropped one would be free: the
    list the player is offered."""
    from engine.targeting import derive_activation_spec

    program = compile_card_oracle(set_pool("ICE")["Dreams of the Dead"])
    spec = derive_activation_spec(program.activated_abilities[0])
    assert spec == {
        "kind": "graveyard_creature",
        "own_graveyard_only": True,
        "graveyard_colors": ["W", "B"],
    }

    game, _p1, _p2 = _dreams_board(
        set_pool, "Balduvian Bears", "Kjeldoran Skycaptain",
    )
    offered = game._enumerate_targets(
        0, set_pool("ICE")["Dreams of the Dead"], spec, for_cast=False,
    )
    assert [entry["name"] for entry in offered] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_green_creature_card_is_not_reanimated(set_pool):
    """The other end of the same narrowing: the resolution re-checks it, so a
    stale or invented index cannot slip a card past the picker."""
    game, p1, _p2 = _dreams_board(set_pool, "Balduvian Bears")

    assert _reanimate(game) is None
    assert [card.name for card in p1.graveyard] == ["Balduvian Bears"]


def test_w4g1_the_reanimated_creature_gains_cumulative_upkeep(set_pool):
    """The second sentence, and the whole reason the first records what it
    made: read as "the ability's target" the grant would land on a card in a
    graveyard and do nothing."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")

    revived = _reanimate(game)
    assert revived is not None and revived.card.name == "Kjeldoran Skycaptain"
    assert "Cumulative upkeep {2}" in revived.effective_card.oracle_text

    granted = compile_card_oracle(revived.effective_card)
    assert [
        (trigger.condition.kind, trigger.instruction.kind)
        for trigger in granted.triggered_abilities
    ] == [("upkeep_self", "cumulative_upkeep")]


def test_w4g1_an_unpaid_upkeep_exiles_it_rather_than_burying_it(set_pool):
    """Both new sentences at once, which is how the card actually plays: the
    granted upkeep sacrifices the creature and the replacement takes it out of
    the graveyard the sacrifice was heading for (CR 614.6). Without the second,
    the card is a two-mana loop."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    game.turn += 1
    game.resolve_upkeep(0)
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == ["Dreams of the Dead"]
    assert [card.name for card in p1.graveyard] == []
    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_bounce_exiles_it_too(set_pool):
    """The destination a "would die" reading would miss entirely. "Leave the
    battlefield" is four exits, and this clause is a drawback — the smaller
    reading is the one that hands the player a better card than the printed
    one."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    game._bounce_target_creature(p1, p1.battlefield.index(revived))
    game._settle()

    assert [card.name for card in p1.hand] == []
    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_tuck_exiles_it_too(set_pool):
    """The third destination, through the library seam."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    game.remove_from_battlefield(revived)
    game.put_card_into_library(p1, revived.card, "top", from_battlefield=revived)

    assert p1.library == []
    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_a_creature_already_being_exiled_is_exiled_once(set_pool):
    """Exile is deliberately not one of the fire sites: a permanent already on
    its way there is going where "exile it instead" would send it, and an event
    fired at that destination would put the card in exile twice."""
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    game.remove_from_battlefield(revived)
    p1.exile.append(revived.card)

    assert [card.name for card in p1.exile] == ["Kjeldoran Skycaptain"]


def test_w4g1_an_ordinary_creature_beside_it_is_untouched(set_pool):
    """The marker is on the *permanent*, not on the card — a `CardDefinition`
    is shared between every copy of a card in a deck, so a record keyed to the
    card would divert a second copy's bounce as well."""
    pool = set_pool("ICE")
    game, p1, _p2 = _dreams_board(set_pool, "Kjeldoran Skycaptain")
    revived = _reanimate(game)
    assert revived is not None

    # A second, ordinary copy of the very same card object.
    twin = _nosick(Permanent(card=pool["Kjeldoran Skycaptain"]))
    p1.battlefield.append(twin)
    game._initialize_permanent_state(twin, 0, 0)

    game._bounce_target_creature(p1, p1.battlefield.index(twin))
    game._settle()

    assert [card.name for card in p1.hand] == ["Kjeldoran Skycaptain"]
    assert [card.name for card in p1.exile] == []


def test_w4g1_the_leave_rider_refuses_a_move_that_cannot_arm_it(set_pool):
    """The rider is armed by one handler. On any other move the word would be
    consumed and dropped — and a *dropped drawback* is a card better than the
    one printed, so the line refuses instead.

    An invented sentence, because a guard aimed at a printed line stops
    guarding the day somebody implements it.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError, LoweringError
    from engine.grammar.lower import lower_ability

    line = (
        "Return target creature card from your graveyard to your hand. "
        "If the creature would leave the battlefield, exile it instead of "
        "putting it anywhere else."
    )
    with pytest.raises((GrammarError, LoweringError)):
        lower_ability(parse_line(line))
# --- end W4G1 ---

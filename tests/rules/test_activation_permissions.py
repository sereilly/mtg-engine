"""CR 602.1a/602.1b — which players can activate an activated ability.

The twin of `tests/rules/test_activation_restrictions.py`, one question over:
that file is about *when* an ability may be activated, this one about *who* may.
CR 602.1b names them together as activation instructions, and Armageddon Clock
prints both in one sentence, which is why the two tables have to agree on where
the "but" falls.

Checked by behaviour rather than by reading the rows back, for the reason
`engine/activation_permissions.py` gives: the permission used to be a substring
test in four places and it only ever *widened*, so a card whose permission
excludes its own controller would have had the ability work for the one player
the card forbids. Nothing crashes when a permission is dropped — the ability
simply works more often than the card allows.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.activation_permissions import (
    activation_permission_denial,
    card_widens_activation,
    permission_shaped_line,
    unreadable_activation_permissions,
)
from engine.card_loader import load_catalog, load_cards, manifest_set_path
from engine.models import CardDefinition, Permanent, PlayerState

_CATALOG = {c.name: c for c in load_catalog()}
_LEG = {
    c.name: c
    for c in load_cards(manifest_set_path("LEG", include_measured=True))
}


def _r29_board(card, controller_seat: int = 0):
    players = [PlayerState(name="P1"), PlayerState(name="P2")]
    game = Game(players=players)
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(controller_seat, permanent, None)
    game._settle()
    return game, permanent


def _r29_ability_line(card, needle: str) -> str:
    return next(
        line for line in card.oracle_text.splitlines() if needle in line.lower()
    )


@pytest.mark.cr("602.1a")
def test_with_no_printed_permission_only_the_controller_may_activate():
    """The default the exceptions are exceptions to."""
    game, jayemdae = _r29_board(_CATALOG["Jayemdae Tome"])
    line = _r29_ability_line(jayemdae.card, "draw a card")

    assert activation_permission_denial(game, 0, jayemdae, line) is None
    assert activation_permission_denial(game, 1, jayemdae, line) is not None


@pytest.mark.cr("602.1b")
def test_any_player_may_activate_admits_every_seat():
    game, efreet = _r29_board(_CATALOG["Ifh-Bíff Efreet"])
    line = _r29_ability_line(efreet.card, "any player may activate")

    assert card_widens_activation(efreet.card)
    assert activation_permission_denial(game, 0, efreet, line) is None
    assert activation_permission_denial(game, 1, efreet, line) is None


@pytest.mark.cr("602.1b")
def test_only_your_opponents_may_activate_denies_the_controller():
    """The direction a permission that only widens cannot express."""
    game, clergy = _r29_board(_LEG["Clergy of the Holy Nimbus"])
    line = _r29_ability_line(clergy.card, "only your opponents")

    assert card_widens_activation(clergy.card)
    assert activation_permission_denial(game, 1, clergy, line) is None
    denial = activation_permission_denial(game, 0, clergy, line)
    assert denial is not None and "opponents" in denial


@pytest.mark.cr("602.1b", "108.3")
def test_owner_only_follows_ownership_not_control():
    """"Only this creature's owner may activate this ability." (Personal
    Incarnation.) The sentence exists for the case where the two differ."""
    game, incarnation = _r29_board(_CATALOG["Personal Incarnation"])
    line = _r29_ability_line(incarnation.card, "owner may activate")

    assert activation_permission_denial(game, 0, incarnation, line) is None
    assert activation_permission_denial(game, 1, incarnation, line) is not None

    from engine.control import change_control

    change_control(incarnation, 1, source="test")
    game._settle()

    assert game.controller_index_of(incarnation) == 1
    assert activation_permission_denial(game, 0, incarnation, line) is None
    assert activation_permission_denial(game, 1, incarnation, line) is not None


@pytest.mark.cr("602.1b")
def test_a_permission_shaped_sentence_no_row_implements_is_reported_unreadable():
    """The gate half: a sentence that reads as a permission and matches no row
    must make its card unsupported, never be consumed and dropped."""
    invented = "{T}: Draw a card. Only Wizards may activate this ability."

    assert permission_shaped_line("Only Wizards may activate this ability.")
    assert unreadable_activation_permissions(invented) == [
        "only wizards may activate this ability"
    ]
    assert unreadable_activation_permissions(
        "{T}: Draw a card. Only your opponents may activate this ability."
    ) == []


@pytest.mark.cr("602.1b", "602.5")
def test_a_permission_joined_to_a_timing_restriction_is_read_by_both_tables():
    """Armageddon Clock prints "Any player may activate this ability but only
    during any upkeep step" as one sentence; the head is a permission and the
    tail is a CR 602.5 restriction."""
    from engine.activation_permissions import permission_clause_readable
    from engine.activation_restrictions import unreadable_activation_clauses

    clock = _CATALOG["Armageddon Clock"]
    sentence = "Any player may activate this ability but only during any upkeep step."

    assert permission_clause_readable(sentence)
    assert card_widens_activation(clock)
    assert unreadable_activation_clauses(clock.oracle_text) == []
    assert unreadable_activation_permissions(clock.oracle_text) == []


@pytest.mark.cr("602.1b")
def test_a_card_with_an_unimplementable_permission_is_unsupported():
    """The gate is the grammar's full-consumption invariant: the production that
    consumes the sentence asks this module first, so a permission with no row
    leaves the line refused and the card visibly unsupported rather than
    admitted with an ability reachable by a player the card forbids."""
    from engine.oracle import compile_card_oracle

    def _invented(text: str):
        return CardDefinition(
            name="Invented Cleric", mana_cost="{W}", cmc=1.0,
            type_line="Creature - Human Cleric", oracle_text=text,
            colors=("W",), color_identity=("W",), keywords=(), produced_mana=(),
            raw={"name": "Invented Cleric", "type_line": "Creature - Human Cleric",
                 "power": "1", "toughness": "1"},
        )

    readable = _invented(
        "{1}: This creature can't be regenerated this turn. "
        "Only your opponents may activate this ability."
    )
    unreadable = _invented(
        "{1}: This creature can't be regenerated this turn. "
        "Only Wizards may activate this ability."
    )

    assert compile_card_oracle(readable).supported
    assert not compile_card_oracle(unreadable).supported


# ---------------------------------------------------------------------------
# CR 602.3 — an ability that hands one of its controller's opponents a choice
# the controller would normally make.
#
# One question over from the rest of this file again: those tests are about who
# may *activate*, this one about who answers a question inside an activation
# somebody else made. "In these cases, the opponent does so when the ability's
# controller normally would do so" — which for a target is the announcement
# (CR 601.2c), and that is the half of the rule this engine still owes.
# ---------------------------------------------------------------------------


def _cr602_3_board(pool, *, opposing_creatures: int, own_creatures: int = 0):
    from tests.helpers import _mk_creature_card, _nosick

    chamber = _nosick(Permanent(card=pool["Echo Chamber"]))
    mine = [
        Permanent(card=_mk_creature_card(f"Mine {i}", 2, 2))
        for i in range(own_creatures)
    ]
    theirs = [
        Permanent(card=_mk_creature_card(f"Theirs {i}", 2, 2))
        for i in range(opposing_creatures)
    ]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[chamber, *mine]),
        PlayerState(name="P2", battlefield=theirs),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game._settle()
    return game, chamber, theirs


@pytest.mark.cr("602.3", "601.2c")
def test_602_3_an_opponents_announced_target_still_has_to_exist(set_pool):
    """Echo Chamber is the pool's activated printing of this rule: "An opponent
    chooses **target** creature they control."

    The word "target" is printed, so CR 601.2c applies and CR 602.3 only moves
    who answers it — which means an ability whose announced target has no legal
    object cannot be activated. It could be: the pick is modelled as a value
    chosen during the resolution, so the announcement gate had no spec to read
    and the {4} and the {T} were paid into a choice with no candidates.
    """
    game, chamber, _ = _cr602_3_board(set_pool("TMP"), opposing_creatures=0)

    refused = game.activate_permanent_ability(0, "Echo Chamber", ability_index=0)

    assert not refused.supported
    assert "no valid target" in refused.details
    assert not chamber.tapped, "the cost was paid for a refused activation"


@pytest.mark.cr("602.3")
def test_602_3_the_choice_is_the_opponents_and_so_is_the_board_it_is_made_from(
    set_pool,
):
    """"…**they** control": the seat that chooses and the battlefield chosen
    from are one answer, and it is not the activator's.

    Both halves are asserted because either alone would pass a wrong engine —
    offering the activator's creatures to the opponent, or asking the activator
    about the opponent's.
    """
    game, chamber, theirs = _cr602_3_board(
        set_pool("TMP"), opposing_creatures=2, own_creatures=1
    )

    assert game.activate_permanent_ability(
        0, "Echo Chamber", ability_index=0
    ).supported
    game.resolve_top_of_stack()

    prompt = next(iter(game.pending_choices_of("permanent_choice")))
    assert prompt.player_index == 1, "the activator was asked"
    offered = {perm.card.name for perm in game.live_permanent_choices(prompt)}
    assert offered == {"Theirs 0", "Theirs 1"}


@pytest.mark.cr("602.3")
def test_602_3_the_activators_own_creature_does_not_make_it_activatable(set_pool):
    """The gate has to read the same battlefield the resolution will, or a
    refusal is worse than the bug it fixes: a creature the *activator* controls
    is not something the opponent may choose, so it cannot be what makes the
    ability legal to activate."""
    game, chamber, _ = _cr602_3_board(
        set_pool("TMP"), opposing_creatures=0, own_creatures=2
    )

    refused = game.activate_permanent_ability(0, "Echo Chamber", ability_index=0)

    assert not refused.supported
    assert not chamber.tapped

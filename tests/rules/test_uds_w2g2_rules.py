"""CR 502 — a type the untapping player names as their untap step begins.

Storage Matrix prints "As long as this artifact is untapped, each player chooses
artifact, creature, or land during their untap step. That player can untap only
permanents of the chosen type this step." — two sentences that are one rule, and
the third family in ``engine/untap_restrictions.py``: not a count limit and not a
block, but a set that **is not readable off the card at all** until somebody
answers.

Every card here is invented, for the reason the file next door gives: a test
naming Storage Matrix would pass against a table keyed on "Storage Matrix", and
the whole point of the text-keyed model is that a card printed with a different
list of types needs no code. The real card is in ``tests/sets/test_uds_artifacts.py``.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.phases.untap_step import UNTAP_TYPE_CHOICE_STAMP
from engine.untap_restrictions import (
    TYPE_CHOICE_SCOPE,
    untap_restriction_for,
    untap_type_choice_sentence,
)
from tests.helpers import _mk_card

_SENTENCES = (
    "each player chooses {options} during their untap step. That player can "
    "untap only permanents of the chosen type this step."
)


def _w2g2_matrix_text(options: str = "artifact, creature, or land", *, gated: bool = True) -> str:
    body = _SENTENCES.format(options=options)
    if gated:
        return "As long as this artifact is untapped, " + body
    return body[0].upper() + body[1:]


def _w2g2_prison(name: str, options: str = "artifact, creature, or land"):
    return _mk_card(name, "{3}", "Artifact", _w2g2_matrix_text(options))


def _w2g2_board(*, options: str = "artifact, creature, or land", seats: int = 2):
    """One prison plus a tapped land, creature and artifact for seat 0."""
    prison = Permanent(card=_w2g2_prison("Hoard Lattice", options))
    land = Permanent(card=_mk_card("Ridge", "", "Land", ""), tapped=True)
    creature = Permanent(card=_mk_card("Watcher", "", "Creature - Test", ""), tapped=True)
    artifact = Permanent(card=_mk_card("Cog", "", "Artifact", ""), tapped=True)
    players = [
        PlayerState(name="W2G2-A", battlefield=[prison, land, creature, artifact], life=20)
    ]
    players += [PlayerState(name=f"W2G2-{i}", life=20) for i in range(1, seats)]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, prison, {"land": land, "creature": creature, "artifact": artifact}


@pytest.mark.cr("502.3")
def test_502_3_a_named_type_is_its_own_family_of_untap_restriction():
    """The pair of sentences derives one restriction, and the printed list is
    payload.

    Not a count limit (no number is printed) and not a block (no noun phrase
    names what stays tapped) — the set that untaps is decided by an answer, so
    it is its own scope. The options being payload is what makes a card printed
    with a different list need no code at all, which is the whole claim of this
    file's model.
    """
    three = untap_restriction_for(_w2g2_matrix_text())
    assert three is not None
    assert three.scope == TYPE_CHOICE_SCOPE
    assert three.chosen_type_options == ("artifact", "creature", "land")
    assert three.limit is None and three.blocked is None

    two = untap_restriction_for(_w2g2_matrix_text("enchantment or land"))
    assert two is not None
    assert two.chosen_type_options == ("enchantment", "land")


@pytest.mark.cr("502.3")
def test_502_3_the_as_long_as_untapped_qualifier_survives_the_new_family():
    """"As long as this artifact is untapped, …" is stripped before the row is
    matched and re-applied after — the same qualifier Winter Orb carries.

    Without the re-application the restriction would apply from a tapped source,
    which is the direction that costs a player their whole untap step for a card
    that says nothing that turn.
    """
    gated = untap_restriction_for(_w2g2_matrix_text())
    ungated = untap_restriction_for(_w2g2_matrix_text(gated=False))

    assert gated is not None and gated.only_while_source_untapped
    assert ungated is not None and not ungated.only_while_source_untapped
    assert gated.chosen_type_options == ungated.chosen_type_options


@pytest.mark.cr("502.3")
def test_502_3_an_unreadable_option_list_refuses_the_whole_line():
    """A list this engine cannot turn into a filter is not admitted.

    The refusal direction matters more here than anywhere else in the file: the
    sentence says a player can untap **only** permanents of the chosen type, so
    a word nothing could test would either untap the whole board (the narrowing
    dropped) or none of it (the narrowing kept and matching nothing). Refusing
    the line leaves the card unsupported and visible instead.
    """
    assert untap_restriction_for(_w2g2_matrix_text("artifact, banana, or land")) is None
    assert not untap_type_choice_sentence(
        "Each player chooses artifact, banana, or land during their untap step."
    )


@pytest.mark.cr("502.3")
def test_502_3_both_printed_sentences_are_claimed_and_neither_alone_is_the_rule():
    """The census splits a line into sentences; the support gate reads the line.

    Both halves are claimed by the reader that carries the pair out, because the
    second has no separate implementation — but only the *pair* derives a
    restriction, so the half that says what the answer does can never be read as
    a rule of its own.
    """
    assert untap_type_choice_sentence(
        "As long as this artifact is untapped, each player chooses artifact, "
        "creature, or land during their untap step."
    )
    assert untap_type_choice_sentence(
        "That player can untap only permanents of the chosen type this step."
    )
    assert untap_restriction_for(
        "That player can untap only permanents of the chosen type this step."
    ) is None


@pytest.mark.cr("502.3")
def test_502_3_only_permanents_of_the_named_type_untap():
    """"That player can untap only permanents of the chosen type this step."

    The answer is written where the arming would have written it, so this test
    is about what the *step* does with a word rather than about how the word was
    chosen (the two tests below own that). One tapped permanent of each type, so
    naming one of the three has to leave exactly the other two down — a
    narrowing that was dropped would untap all three.
    """
    game, prison, board = _w2g2_board()
    prison.metadata["chosen_card_type"] = "creature"
    prison.metadata[UNTAP_TYPE_CHOICE_STAMP] = (game.turn, 0)
    game.resolve_untap_step(0)

    assert not board["creature"].tapped
    assert board["land"].tapped
    assert board["artifact"].tapped


@pytest.mark.cr("502.3")
def test_502_3_the_default_is_the_type_that_would_untap_the_most():
    """A headless or AI seat is never blocked, and what it gets is a real answer.

    The type under which the most of the chooser's tapped permanents would untap
    — the choice a player facing this every untap step would actually make —
    with the printed order breaking a tie, so a seed still reproduces a run.
    """
    game, prison, board = _w2g2_board()
    even = game.arm_untap_type_choices(0)
    assert even is False, "a non-interactive seat never queues the prompt"
    assert prison.metadata["chosen_card_type"] == "artifact", "one each: printed order"

    game, prison, board = _w2g2_board()
    game.players[0].battlefield.append(
        Permanent(card=_mk_card("Sentinel", "", "Creature - Test", ""), tapped=True)
    )
    game.arm_untap_type_choices(0)
    assert prison.metadata["chosen_card_type"] == "creature", "two beats one each"


@pytest.mark.cr("502.3")
def test_502_3_two_prisons_answered_differently_leave_the_intersection():
    """"Only" said twice is "only" twice, so nothing untaps unless every live
    source named its type.

    Each source records its own answer, which is what makes this fall out rather
    than needing a rule: the step asks each narrowing separately and a permanent
    has to survive them all.
    """
    game, first, board = _w2g2_board()
    second = Permanent(card=_w2g2_prison("Second Lattice"))
    game.players[0].battlefield.append(second)

    first.metadata["chosen_card_type"] = "creature"
    second.metadata["chosen_card_type"] = "land"
    first.metadata[UNTAP_TYPE_CHOICE_STAMP] = (game.turn, 0)
    second.metadata[UNTAP_TYPE_CHOICE_STAMP] = (game.turn, 0)
    game.resolve_untap_step(0)

    assert board["creature"].tapped, "the land prison keeps the creature down"
    assert board["land"].tapped, "the creature prison keeps the land down"
    assert board["artifact"].tapped


@pytest.mark.cr("502.3")
def test_502_3_a_tapped_source_asks_nothing_and_restricts_nothing():
    """"**As long as this artifact is untapped**, each player chooses…"

    A turn where the source is tapped owes no choice at all, so the whole board
    untaps — including the source, which untaps like any other permanent.
    """
    game, prison, board = _w2g2_board()
    prison.tapped = True

    assert game.arm_untap_type_choices(0) is False
    assert "chosen_card_type" not in prison.metadata
    game.resolve_untap_step(0)

    assert not any(perm.tapped for perm in board.values())
    assert not prison.tapped


@pytest.mark.cr("502.3")
def test_502_3_the_type_is_named_again_each_untap_step():
    """The answer is a fact about one step, not about the permanent.

    Stamped with ``(turn, seat)``, so the arming is idempotent within a step —
    which is what lets both the web layer and the step itself call it — and
    re-asks on the next one. Without the re-ask, turn one's answer would be
    frozen into the rest of the game.
    """
    game, prison, board = _w2g2_board()
    game.arm_untap_type_choices(0)
    stamped = prison.metadata[UNTAP_TYPE_CHOICE_STAMP]

    assert game.arm_untap_type_choices(0) is False, "asked twice in one step"
    assert prison.metadata[UNTAP_TYPE_CHOICE_STAMP] == stamped

    game.turn += 1
    for perm in board.values():
        perm.tapped = True
    game.arm_untap_type_choices(0)
    assert prison.metadata[UNTAP_TYPE_CHOICE_STAMP] == (game.turn, 0)


@pytest.mark.cr("502.3")
def test_502_3_each_player_names_their_own_type_on_their_own_step():
    """"**each player** chooses … during **their** untap step."

    One source, two seats, two different answers — and each is spent on the step
    that named it. The record is per source rather than per seat, so what stops
    seat 0's answer reaching seat 1's step is that the step re-asks.
    """
    game, prison, board = _w2g2_board()
    other_land = Permanent(card=_mk_card("Bluff", "", "Land", ""), tapped=True)
    other_creature = Permanent(
        card=_mk_card("Sentry", "", "Creature - Test", ""), tapped=True
    )
    game.players[1].battlefield = [other_land, other_creature]

    prison.metadata["chosen_card_type"] = "creature"
    prison.metadata[UNTAP_TYPE_CHOICE_STAMP] = (game.turn, 0)
    game.resolve_untap_step(0)
    assert not board["creature"].tapped and board["land"].tapped

    game.turn += 1
    prison.metadata["chosen_card_type"] = "land"
    prison.metadata[UNTAP_TYPE_CHOICE_STAMP] = (game.turn, 1)
    game.resolve_untap_step(1)
    assert not other_land.tapped
    assert other_creature.tapped, "seat 1 named land, so their creature stays down"


@pytest.mark.cr("502.4", "117.3b")
def test_502_4_no_step_advances_while_the_type_is_still_owed():
    """No player receives priority during the untap step, so the choice inside
    it has to be answered before anything else happens.

    An interactive seat's prompt is a registered ``PendingChoice`` and therefore
    holds priority off ``blocked_detail`` — this is the first prompt in the
    engine armed by a **turn-based action** rather than by a resolution, and the
    registry carries it with no widening: nothing is resolving, so it holds no
    stack object and simply makes the game wait.
    """
    game, prison, board = _w2g2_board()
    game.interactive_seats = {0}

    assert game.arm_untap_type_choices(0) is True
    owed = game.waiting_prompt()
    assert owed is not None and owed.kind == "card_type_choice"
    assert owed.data["options"] == ["artifact", "creature", "land"]
    assert owed.data.get("_stack_item") is None, "nothing was resolving"
    assert game.untap_type_choice_owed(0)

    assert game.confirm_card_type_choice(0, "artifact")
    assert game.waiting_prompt() is None
    assert not game.untap_type_choice_owed(0)

    game.resolve_untap_step(0)
    assert not board["artifact"].tapped
    assert board["land"].tapped and board["creature"].tapped


@pytest.mark.cr("502.3")
def test_502_3_an_answer_outside_the_printed_list_is_refused():
    """The options are the *card's*, not a catalog's.

    A seat that could answer "enchantment" against a card offering artifact,
    creature or land would name a type the sentence never offered — and the
    answer would then be spent by the untap step as if it had.
    """
    game, prison, _board = _w2g2_board()
    game.interactive_seats = {0}
    game.arm_untap_type_choices(0)

    assert not game.confirm_card_type_choice(0, "enchantment")
    assert game.untap_type_choice_owed(0), "a refused answer leaves the prompt owed"
    assert game.confirm_card_type_choice(0, "land")

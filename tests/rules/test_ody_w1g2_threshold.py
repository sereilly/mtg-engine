"""Threshold, where the rules put it (Odyssey, W1G2).

"Threshold" is an ability word (CR 207.2c) and means nothing; what the cards
print behind it is a count of cards in a graveyard, asked in two places:

* **CR 602.5** — "Activate only if there are seven or more cards in your
  graveyard." A restriction on *beginning* to activate, read by
  ``engine/activation_restrictions.py`` through the grammar's own condition
  reader, so the number, the pile and any narrowing on the cards are payload.
* **CR 608.2c / 608.2h / 608.2n** — "… instead if there are seven or more
  cards in your graveyard." A condition asked as the spell resolves, when the
  spell itself is still on the stack, that *replaces* the sentence above it.

Driven from invented cards, because the rows and the rider are templates: a
test built on Barbarian Ring would demonstrate Barbarian Ring. The per-card
tests are in ``tests/sets/test_ody_*.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.activation_restrictions import (
    activation_denial, unreadable_activation_clauses,
)
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_W1G2_CATALOG = {card.name: card for card in load_catalog()}


def _w1g2_card(name: str, type_line: str, text: str, mana_cost: str = "{1}") -> CardDefinition:
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw.update(power="2", toughness="2")
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=1.0, type_line=type_line,
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


def _w1g2_game(*, graveyard=(), hand=()) -> Game:
    forest = _W1G2_CATALOG["Forest"]
    game = Game(players=[
        PlayerState("P1", library=[forest] * 10, hand=list(hand)),
        PlayerState("P2", library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].graveyard.extend(graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _w1g2_put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g2_bears(count: int) -> list:
    return [_W1G2_CATALOG["Grizzly Bears"]] * count


# ---------------------------------------------------------------------------
# CR 602.5 — the activation restriction
# ---------------------------------------------------------------------------

@pytest.mark.cr("602.5", "601.2h")
def test_602_5_a_graveyard_count_refuses_before_anything_is_paid():
    """"A player can't begin to activate an ability that's prohibited from
    being activated." With six cards the {2} stays in the pool and the
    artifact stays untapped; with seven it is spent."""
    engine = _w1g2_card(
        "Pile Engine", "Artifact",
        "{2}, {T}: You gain 1 life. Activate only if there are seven or more "
        "cards in your graveyard.",
    )
    assert compile_card_oracle(engine).supported

    game = _w1g2_game(graveyard=_w1g2_bears(6))
    source = _w1g2_put(game, 0, engine)
    game.players[0].mana_pool["C"] = 2

    refused = game.activate_permanent_ability(0, "Pile Engine")

    assert not refused.supported
    assert refused.details == (
        "Pile Engine: only if there are seven or more cards in your graveyard"
    )
    assert game.players[0].mana_pool["C"] == 2 and not source.tapped
    assert game.players[0].life == 20

    game.players[0].graveyard.append(_W1G2_CATALOG["Forest"])
    allowed = game.activate_permanent_ability(0, "Pile Engine")

    assert allowed.supported, allowed.details
    assert game.players[0].mana_pool["C"] == 0 and source.tapped
    assert game.players[0].life == 21


@pytest.mark.cr("602.5")
@pytest.mark.parametrize(
    "clause, graveyard, legal",
    [
        ("there are three or more cards in your graveyard", ["Forest"] * 2, False),
        ("there are three or more cards in your graveyard", ["Forest"] * 3, True),
        # A narrowing on the cards: lands do not count toward creature cards.
        ("there are two or more creature cards in your graveyard",
         ["Forest", "Forest", "Grizzly Bears"], False),
        ("there are two or more creature cards in your graveyard",
         ["Forest", "Grizzly Bears", "Craw Wurm"], True),
        # The other bound and the article: the same reader, the same row.
        ("there are no cards in your graveyard", [], True),
        ("there are no cards in your graveyard", ["Forest"], False),
        ("there is a creature card in your graveyard", ["Forest"], False),
        ("there is a creature card in your graveyard", ["Grizzly Bears"], True),
    ],
)
def test_602_5_the_number_the_cards_and_the_bound_are_payload(clause, graveyard, legal):
    """Threshold's seven is not special-cased anywhere: the clause is read by
    the grammar's condition reader and answered by the evaluator every printed
    "if" goes through, so another number, a narrowing on the cards or another
    comparison is this row and needs no code."""
    engine = _w1g2_card(
        "Pile Engine", "Artifact", f"{{T}}: You gain 1 life. Activate only if {clause}.",
    )
    assert compile_card_oracle(engine).supported, clause
    game = _w1g2_game(graveyard=[_W1G2_CATALOG[name] for name in graveyard])
    source = _w1g2_put(game, 0, engine)

    denial = activation_denial(game, 0, source, engine.oracle_text)

    assert (denial is None) is legal, (clause, graveyard, denial)


@pytest.mark.cr("602.5")
def test_602_5_your_graveyard_is_the_activators_not_the_bigger_one():
    """"Your" is the ability's controller (CR 109.5). Seven cards in the
    opponent's graveyard are not threshold."""
    engine = _w1g2_card(
        "Pile Engine", "Artifact",
        "{T}: You gain 1 life. Activate only if there are seven or more cards "
        "in your graveyard.",
    )
    game = _w1g2_game()
    game.players[1].graveyard.extend(_w1g2_bears(9))
    _w1g2_put(game, 0, engine)

    assert not game.activate_permanent_ability(0, "Pile Engine").supported
    assert game.players[0].life == 20


@pytest.mark.cr("602.5")
@pytest.mark.parametrize(
    "clause",
    [
        # A pile the activation has no way to name: nothing has been targeted
        # when a restriction is asked.
        "there are seven or more cards in target player's graveyard",
        "there are seven or more cards in each graveyard",
        "there are seven or more cards in an opponent's graveyard",
        # Not a count of cards at all.
        "there are seven or more ghosts in your graveyard",
    ],
)
def test_602_5_a_pile_clause_nothing_can_count_makes_the_card_unsupported(clause):
    """The gate half. A clause the row cannot turn into a pile count must
    leave the card unsupported naming the sentence — admitted, it would be an
    ability with its restriction dropped, which works more often than the
    card allows."""
    text = f"{{T}}: You gain 1 life. Activate only if {clause}."
    engine = _w1g2_card("Pile Engine", "Artifact", text)

    assert unreadable_activation_clauses(text, "Pile Engine") == [
        f"activate only if {clause}"
    ]
    assert not compile_card_oracle(engine).supported


@pytest.mark.cr("602.5", "602.5d")
def test_602_5_and_only_if_joins_two_restrictions_and_both_bind():
    """"Activate only as a sorcery **and only if** there are seven or more
    cards in your graveyard." Each half refuses on its own, and the denial
    names the half that failed."""
    engine = _w1g2_card(
        "Pile Engine", "Artifact",
        "{T}: You gain 1 life. Activate only as a sorcery and only if there "
        "are seven or more cards in your graveyard.",
    )
    assert compile_card_oracle(engine).supported

    game = _w1g2_game(graveyard=_w1g2_bears(6))
    source = _w1g2_put(game, 0, engine)
    assert "seven or more cards" in activation_denial(game, 0, source, engine.oracle_text)

    game.players[0].graveyard.append(_W1G2_CATALOG["Forest"])
    assert activation_denial(game, 0, source, engine.oracle_text) is None

    game.active_player_index = 1
    assert "sorcery" in activation_denial(game, 0, source, engine.oracle_text)


@pytest.mark.cr("602.5")
def test_602_5_a_land_sacrificed_as_the_cost_is_not_its_own_seventh_card():
    """The clause is asked when activation *begins*; the sacrifice is a cost,
    paid at the end of the process. Six cards plus the land about to be
    sacrificed is six."""
    land = _w1g2_card(
        "Pile Quarry", "Land",
        "{T}: Add {C}.\n"
        "{T}, Sacrifice this land: You gain 4 life. Activate only if there "
        "are seven or more cards in your graveyard.",
        mana_cost="",
    )
    assert compile_card_oracle(land).supported
    game = _w1g2_game(graveyard=_w1g2_bears(6))
    source = _w1g2_put(game, 0, land)

    refused = game.activate_permanent_ability(0, "Pile Quarry", ability_index=1)

    assert not refused.supported
    assert game.is_on_battlefield(source) and game.players[0].life == 20


# ---------------------------------------------------------------------------
# CR 601.2c through CR 602.2b — a printed count is a count
# ---------------------------------------------------------------------------

@pytest.mark.cr("601.2c", "602.2b")
def test_601_2c_an_ability_printing_two_targets_is_not_activated_naming_one():
    """"Tap **two** target creatures." The player announces a choice "for
    each target the spell requires" and CR 602.2b sends an activation through
    the same step. One creature named is refused with the cost unpaid; "up to
    two" may name one."""
    exact = _w1g2_card("Twin Tapper", "Artifact", "{T}: Tap two target creatures.")
    lenient = _w1g2_card("Loose Tapper", "Artifact", "{T}: Tap up to two target creatures.")
    assert compile_card_oracle(exact).supported and compile_card_oracle(lenient).supported

    game = _w1g2_game()
    source = _w1g2_put(game, 0, exact)
    first, second = (_w1g2_put(game, 1, _W1G2_CATALOG["Grizzly Bears"]) for _ in range(2))

    short = game.activate_permanent_ability(
        0, "Twin Tapper", target_permanent_ids=[first.permanent_id],
    )
    assert not short.supported and "needs 2 targets, not 1" in short.details
    assert not source.tapped and not first.tapped

    assert game.activate_permanent_ability(
        0, "Twin Tapper",
        target_permanent_ids=[first.permanent_id, second.permanent_id],
    ).supported
    assert first.tapped and second.tapped

    game = _w1g2_game()
    _w1g2_put(game, 0, lenient)
    lone = _w1g2_put(game, 1, _W1G2_CATALOG["Grizzly Bears"])
    assert game.activate_permanent_ability(
        0, "Loose Tapper", target_permanent_ids=[lone.permanent_id],
    ).supported
    assert lone.tapped


# ---------------------------------------------------------------------------
# CR 608.2 — the spell's condition, and the sentence it replaces
# ---------------------------------------------------------------------------

_W1G2_BLAST = (
    "Pile Blast deals 2 damage to any target.\n"
    "Threshold — Pile Blast deals 6 damage instead if there are three or more "
    "cards in your graveyard."
)


@pytest.mark.cr("608.2c")
@pytest.mark.parametrize("graveyard, lost", [(2, 2), (3, 6)])
def test_608_2c_an_instead_paragraph_replaces_the_paragraph_above(graveyard, lost):
    """Later text modifying earlier text: exactly one of the two amounts is
    dealt. Read as two effects the spell would deal 8 at threshold, and read
    as one line at a time the second paragraph names no recipient at all."""
    blast = _w1g2_card("Pile Blast", "Instant", _W1G2_BLAST, mana_cost="{0}")
    program = compile_card_oracle(blast)
    assert program.supported and [i.kind for i in program.instructions] == ["if_then"]

    game = _w1g2_game(graveyard=_w1g2_bears(graveyard), hand=[blast])
    assert game.cast_from_hand(0, "Pile Blast", target_player_index=1).supported

    assert game.players[1].life == 20 - lost


@pytest.mark.cr("608.2n", "608.2h")
def test_608_2n_a_resolving_spell_is_not_in_its_owners_graveyard_yet():
    """"As the final part of an instant or sorcery spell's resolution, the
    spell is put into its owner's graveyard." So a spell with two cards in the
    graveyard does not count itself as the third — and a card that arrives
    while it is on the stack does count, because the answer "is determined
    only once, when the effect is applied"."""
    blast = _w1g2_card("Pile Blast", "Instant", _W1G2_BLAST, mana_cost="{0}")

    game = _w1g2_game(graveyard=_w1g2_bears(2), hand=[blast])
    assert game.queue_from_hand(0, "Pile Blast", target_player_index=1).supported
    assert len(game.players[0].graveyard) == 2
    resolve_stack(game)
    assert game.players[1].life == 18
    assert len(game.players[0].graveyard) == 3

    game = _w1g2_game(graveyard=_w1g2_bears(2), hand=[blast])
    assert game.queue_from_hand(0, "Pile Blast", target_player_index=1).supported
    game.players[0].graveyard.append(_W1G2_CATALOG["Forest"])
    resolve_stack(game)
    assert game.players[1].life == 14


@pytest.mark.cr("608.2c", "601.2c")
def test_608_2c_the_replacing_sentence_may_name_somebody_else():
    """"Target player sacrifices a land of their choice. / Threshold — Each
    player sacrifices all lands they control instead if …" The second sentence
    points back at nobody, so it is kept as written — and the spell still
    announces its target player, because targets are chosen as it is cast."""
    quake = _w1g2_card(
        "Pile Quake", "Sorcery",
        "Target player sacrifices a land of their choice.\n"
        "Threshold — Each player sacrifices all lands they control instead if "
        "there are three or more cards in your graveyard.",
        mana_cost="{0}",
    )
    assert compile_card_oracle(quake).supported
    forest, island = _W1G2_CATALOG["Forest"], _W1G2_CATALOG["Island"]

    for graveyard, mine_left, theirs_left in ((2, 2, 1), (3, 0, 0)):
        game = _w1g2_game(graveyard=_w1g2_bears(graveyard), hand=[quake])
        for _ in range(2):
            _w1g2_put(game, 0, forest)
            _w1g2_put(game, 1, island)
        assert game.cast_target_spec(0, quake)["requires_target"]
        assert game.queue_from_hand(0, "Pile Quake", target_player_index=1).supported
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        game._settle()
        assert len(list(game.controlled_by(0))) == mine_left, graveyard
        assert len(list(game.controlled_by(1))) == theirs_left, graveyard

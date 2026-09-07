"""Stronghold instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G4: library, graveyard and unusual costs ---

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.cast_costs import (buyback_cost, buyback_paid, expand_buyback_line,
                               unread_cost_sentence)
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g4_duel(hand: list) -> tuple[Game, PlayerState, PlayerState]:
    """A two-seat game with mana enforcement off, so a test about a *cost
    sentence* is not also a test about the pool."""
    caster, victim = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, caster, victim


@pytest.mark.cr("702.27a", "601.2b")
def test_g4_constant_mists_buyback_is_a_non_mana_offer(set_pool):
    """"Buyback—Sacrifice a land."

    CR 702.27's cost is *any* cost, and the rewrite could read only a run of
    mana symbols — so this line was refused by the support gate, which is the
    gate working (a spell cast for its printed {1}{G} with the price nobody was
    offered and no hand-return is worse than an unsupported card). It rewrites
    into CR 601.2b's optional sentence with the printed clause after "you may",
    and the announcement key is that clause.
    """
    card = set_pool("STH")["Constant Mists"]
    printed = card.oracle_text.split("\n")[0]

    assert expand_buyback_line(printed) == (
        "As an additional cost to cast this spell, you may sacrifice a land."
    )
    assert buyback_cost(card.oracle_text) == "sacrifice a land"
    assert unread_cost_sentence(printed) is None
    assert compile_card_oracle(card).supported


@pytest.mark.cr("702.27a", "601.2b")
def test_g4_constant_mists_declined_keeps_the_land_and_bins_the_spell(set_pool):
    """An offer nobody took costs nothing, and CR 702.27a's hand-return is
    conditional on the payment — so the declined cast is an ordinary instant."""
    game, caster, _ = _g4_duel([set_pool("STH")["Constant Mists"]])
    caster.battlefield.append(Permanent(card=_G4_LEA["Forest"]))

    result = game.cast_from_hand(0, "Constant Mists")
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Forest"]
    assert [c.name for c in caster.graveyard] == ["Constant Mists"]
    assert caster.hand == []


@pytest.mark.cr("702.27a", "601.2b")
def test_g4_constant_mists_bought_back_eats_a_land_and_returns(set_pool):
    """The two halves of CR 702.27a in one cast: the land is gone before the
    spell is on the stack, and the spell goes to the hand rather than the
    graveyard as it resolves."""
    game, caster, _ = _g4_duel([set_pool("STH")["Constant Mists"]])
    caster.battlefield.append(Permanent(card=_G4_LEA["Forest"]))

    result = game.cast_from_hand(
        0, "Constant Mists", optional_cost_payments={"sacrifice a land": 1},
    )
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert caster.battlefield == [], "the buyback ate the land"
    assert [c.name for c in caster.graveyard] == ["Forest"]
    assert [c.name for c in caster.hand] == ["Constant Mists"]
    assert buyback_paid(
        set_pool("STH")["Constant Mists"],
        {"additional_costs_paid": {"sacrifice a land": 1}},
    )


@pytest.mark.cr("601.2h", "702.27a")
def test_g4_a_buyback_announced_off_an_empty_board_refuses_the_cast(set_pool):
    """CR 601.2h: an announced price that cannot be paid is a cast that does
    not happen, never one that happens for less. Nothing is spent, and the same
    caster who *declines* casts the spell off the same empty board — which is
    the half a gate reading the cost as mandatory would have got wrong.
    """
    card = set_pool("STH")["Constant Mists"]

    game, caster, _ = _g4_duel([card])
    refused = game.cast_from_hand(
        0, "Constant Mists", optional_cost_payments={"sacrifice a land": 1},
    )
    assert not refused.supported
    assert "CR 601.2h" in refused.details
    assert [c.name for c in caster.hand] == ["Constant Mists"]

    game, caster, _ = _g4_duel([card])
    assert game.cast_from_hand(0, "Constant Mists").supported


@pytest.mark.cr("601.2b")
def test_g4_the_buyback_offer_reaches_the_picker_only_when_it_is_taken(set_pool):
    """The offer is what the client is shown, and the *picker* follows the
    answer: a caster who declines is asked to name no land, and one who takes it
    gets the sacrifice picker on the same re-asked spec."""
    card = set_pool("STH")["Constant Mists"]
    game, caster, _ = _g4_duel([card])
    caster.battlefield.append(Permanent(card=_G4_LEA["Forest"]))

    offers = game.cast_cost_offers(0, card)
    assert offers == [{
        "kind": "optional_cost", "symbols": "sacrifice a land",
        "label": "buyback", "repeatable": False, "max_times": 1, "times": 0,
    }]

    declined = game.cast_target_spec(0, card)
    assert declined["kind"] == "none"
    assert not declined.get("sacrifice_cost")

    taken = game.cast_target_spec(
        0, card, optional_cost_payments={"sacrifice a land": 1},
    )
    assert taken["kind"] == "land" and taken["sacrifice_cost"] is True
    assert [t["name"] for t in taken["valid_targets"]] == ["Forest"]

"""Stronghold enchantments.

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
from engine.alternative_costs import (granted_alternative_cost,
                                      granted_alternative_cost_claims_line)
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g4_halls(hand: list, halls) -> tuple[Game, PlayerState, PlayerState]:
    """A board with Dream Halls out and **mana enforcement on**: the whole
    point of the card is casting a spell for no mana at all, so a game that
    charged nothing would prove nothing."""
    caster, victim = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[caster, victim])
    game.active_player_index = 0
    game.enforce_mana_costs = True
    caster.battlefield.append(Permanent(card=halls))
    return game, caster, victim


@pytest.mark.cr("118.9", "118.9a")
def test_g4_dream_halls_grants_an_alternative_cost_to_every_spell(set_pool):
    """"Rather than pay the mana cost for a spell, its controller may discard a
    card that shares a color with that spell."

    CR 118.9's alternative cost from a **board** rather than printed on the
    spell — which is what nothing read: ``alternative_costs`` was card-scoped,
    so the sentence was claimed by nobody and the enchantment reported
    unsupported. The relationship is ``cost_modifiers``' to ``cast_costs``, one
    rule over.
    """
    halls = set_pool("STH")["Dream Halls"]
    assert compile_card_oracle(halls).supported
    assert granted_alternative_cost_claims_line(halls.oracle_text)

    cost = granted_alternative_cost(halls.oracle_text)
    assert cost is not None
    assert cost.discard_from_hand == (), "any card, narrowed by the relation"
    assert cost.shares_color_with_spell is True
    assert cost.exile_from_hand is None, "a discard is not an exile"


@pytest.mark.cr("118.9", "701.9a")
def test_g4_dream_halls_casts_a_blue_spell_for_a_blue_card(set_pool):
    """The mana payment is replaced, not reduced: the pool is empty and the
    spell resolves. The card paying goes through the discard seam, so it lands
    in the graveyard as a discard rather than as a bare move."""
    game, caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Counterspell"],
         _G4_LEA["Lightning Bolt"]],
        set_pool("STH")["Dream Halls"],
    )

    offers = game.cast_cost_offers(
        0, _G4_LEA["Ancestral Recall"], spell_hand_index=0,
    )
    assert len(offers) == 1 and offers[0]["kind"] == "alternative"
    assert offers[0]["payable"] is True
    assert [c["name"] for c in offers[0]["hand_choices"]] == ["Counterspell"], (
        "only the colour-sharing card is offered"
    )

    result = game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0,
        alternative_cost=True, alternative_cost_hand_index=1,
    )

    assert result.supported, result.details
    assert sum(caster.mana_pool.values()) == 0, "nothing was spent"
    assert [c.name for c in caster.hand] == ["Lightning Bolt"]
    assert "Counterspell" in [c.name for c in caster.graveyard]


@pytest.mark.cr("118.9", "105.2")
def test_g4_dream_halls_needs_a_shared_color(set_pool):
    """The relation is between the card paying and the spell being cast, so a
    red card cannot buy a blue spell — and a **colourless** spell shares a
    colour with nothing, which is why the offer is an intersection rather than
    a default of "no restriction"."""
    halls = set_pool("STH")["Dream Halls"]

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Lightning Bolt"]], halls,
    )
    named = game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0,
        alternative_cost=True, alternative_cost_hand_index=1,
    )
    assert not named.supported, "a red card is not a blue card"

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Ancestral Recall"], _G4_LEA["Lightning Bolt"]], halls,
    )
    unpayable = game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0, alternative_cost=True,
    )
    assert not unpayable.supported
    assert "CR 601.2h" in unpayable.details

    game, _caster, _ = _g4_halls(
        [_G4_LEA["Black Lotus"], _G4_LEA["Lightning Bolt"]], halls,
    )
    assert not game.cast_from_hand(
        0, "Black Lotus", alternative_cost=True,
    ).supported, "a colourless spell shares a colour with nothing"


@pytest.mark.cr("118.9b")
def test_g4_without_dream_halls_no_spell_carries_the_offer(set_pool):
    """The grant is a board read, so it is gone the moment the enchantment is.
    Asserted because the cost is now gathered from two places, and a source
    that leaked into every cast would be the loudest possible mis-play."""
    caster, victim = (
        PlayerState(name="A", hand=[_G4_LEA["Ancestral Recall"],
                                    _G4_LEA["Counterspell"]]),
        PlayerState(name="B"),
    )
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = True

    assert game.cast_cost_offers(
        0, _G4_LEA["Ancestral Recall"], spell_hand_index=0,
    ) == []
    assert not game.cast_from_hand(
        0, "Ancestral Recall", target_player_index=0, alternative_cost=True,
    ).supported

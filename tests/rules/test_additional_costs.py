"""CR 118.8 / 601.2b — additional costs a spell prints in its own rules text.

"An additional cost is a cost listed in a spell's rules text … that its
controller must pay at the same time they pay the spell's mana cost"
(CR 118.8). Three consequences, and the engine used to satisfy none of them for
a spell whose effect did not happen to mention what the cost ate:

* it is **paid** (CR 601.2h), rather than claimed by a whitelist substring and
  quietly skipped — which is how Village Rites drew two cards for {B} and
  Thrill of Possibility discarded nothing;
* an **unpayable** one means the spell can't be cast at all (CR 601.2h), not
  that it is cast for free;
* it is paid **while casting**, so what it ate is gone before the spell
  resolves — and the spell itself is on the stack, so it can't be discarded to
  pay for itself.

The two Alpha cards whose effect *does* mention it (Sacrifice, Metamorphosis)
were the reason the general form was never built: a card hook folded cost and
effect into one resolution, which was one sacrifice in the right place for the
wrong reason and two sacrifices as soon as the cost became real.
"""

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import load_catalog, manifest_set_path
from engine.models import Permanent

_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_CATALOG = {c.name: c for c in load_catalog()}
# M21 is measured, not shipped, so its cards are placed into the game directly —
# the same thing the cast-from-zone and revealed-hand suites do.
_M21 = {
    c.name: c
    for c in load_cards(manifest_set_path("M21", include_measured=True))
}


def _duel(hand: list) -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


# ---------------------------------------------------------------------------
# The cost is paid
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.8", "601.2b", "601.2h")
def test_a_sacrifice_cost_is_paid_by_a_spell_that_never_mentions_it_again():
    """Village Rites: "As an additional cost to cast this spell, sacrifice a
    creature." / "Draw two cards."

    Nothing in the effect refers back to the creature, which is exactly why the
    cost went unpaid: the sentence was claimed by a spell-pattern substring, the
    marker it produced had no handler, and the card reported ``supported``.
    """
    game, p1, _p2 = _duel([_M21["Village Rites"]])
    p1.battlefield.append(Permanent(card=_M21["Alpine Watchdog"]))
    p1.library = [_M21["Swamp"]] * 4

    game.cast_from_hand(0, "Village Rites")

    assert [p.card.name for p in p1.battlefield] == [], "the cost ate the creature"
    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog", "Village Rites"]
    assert len(p1.hand) == 2, "and the spell still drew its two cards"


@pytest.mark.cr("118.8", "601.2b")
def test_a_discard_cost_is_paid_and_cannot_be_paid_with_the_spell_itself():
    """Thrill of Possibility discards a card as its cost, then draws two. The
    spell is on the stack by the time costs are paid (CR 601.2a), so the card
    that leaves the hand is never the spell — with one other card in hand,
    there is exactly one legal payment.
    """
    game, p1, _p2 = _duel([_M21["Thrill of Possibility"], _M21["Mountain"]])
    p1.library = [_M21["Swamp"]] * 4

    game.cast_from_hand(0, "Thrill of Possibility")

    assert [c.name for c in p1.graveyard] == ["Mountain", "Thrill of Possibility"]
    assert len(p1.hand) == 2, "the two it drew"


# ---------------------------------------------------------------------------
# An unpayable cost means the spell is not cast
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2h", "118.8")
def test_a_spell_whose_sacrifice_cost_cannot_be_paid_is_not_cast():
    """"Unpayable costs can't be paid" (CR 601.2h), and casting is a single
    process that rewinds: the spell stays in hand rather than resolving for
    free. With no creature on the battlefield there is no legal payment."""
    game, p1, _p2 = _duel([_M21["Village Rites"]])
    p1.library = [_M21["Swamp"]] * 4

    result = game.cast_from_hand(0, "Village Rites")

    assert not result.supported
    assert "601.2h" in result.details
    assert [c.name for c in p1.hand] == ["Village Rites"], "still in hand"
    assert p1.library == [_M21["Swamp"]] * 4, "and nothing was drawn"


@pytest.mark.cr("601.2h", "118.8")
def test_a_spell_whose_discard_cost_cannot_be_paid_is_not_cast():
    """The same rule for the other shape. The spell is its own hand's only
    card, and it cannot be discarded to pay for itself."""
    game, p1, _p2 = _duel([_M21["Thrill of Possibility"]])
    p1.library = [_M21["Swamp"]] * 4

    result = game.cast_from_hand(0, "Thrill of Possibility")

    assert not result.supported
    assert [c.name for c in p1.hand] == ["Thrill of Possibility"]


# ---------------------------------------------------------------------------
# The payer chooses, and the effect reads what was paid
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2b", "608.2h")
def test_the_payer_chooses_which_creature_the_cost_eats():
    """CR 601.2b: the caster announces how they will pay. The choice arrives on
    the action that pays it (``cost_permanent_index``) rather than through the
    pending-choice queue, because a queued prompt would put the spell on the
    stack before its cost was collected.

    Sacrifice reads the choice back at resolution — the creature is in a
    graveyard by then, so its mana value is last-known information (CR 608.2h).
    """
    game, p1, _p2 = _duel([_CATALOG["Sacrifice"]])
    p1.battlefield.append(Permanent(card=_LEA["Grizzly Bears"]))  # mana value 2
    p1.battlefield.append(Permanent(card=_LEA["Hill Giant"]))     # mana value 4

    game.cast_from_hand(0, "Sacrifice", cost_permanent_index=1)

    assert [p.card.name for p in p1.battlefield] == ["Grizzly Bears"]
    assert p1.mana_pool["B"] == 4, "the mana value of the creature the payer chose"


@pytest.mark.cr("601.2b", "701.21a")
def test_the_cost_eats_exactly_one_creature():
    """The regression the split had to avoid. Sacrifice's hook used to perform
    the sacrifice at *resolution*; once the printed cost was also being paid,
    the same spell ate two creatures. The hook was re-keyed onto the effect
    line it alone prints, and now only reads what the cost took."""
    game, p1, _p2 = _duel([_CATALOG["Sacrifice"]])
    p1.battlefield.append(Permanent(card=_LEA["Grizzly Bears"]))
    p1.battlefield.append(Permanent(card=_LEA["Hill Giant"]))

    game.cast_from_hand(0, "Sacrifice")

    assert len(p1.battlefield) == 1, "one creature, not two"


@pytest.mark.cr("601.2b", "601.2h")
def test_a_creature_spells_additional_cost_is_paid_before_it_enters():
    """Goremand is a *creature* with the same printed cost, so the payment
    happens while it is being cast and the Demon is not on the battlefield to
    pay for itself. Nothing about the cost depends on the card type; the shape
    that made it look like one was the whitelist, which only ever ran for
    instants and sorceries."""
    game, p1, p2 = _duel([_M21["Goremand"]])
    p1.battlefield.append(Permanent(card=_M21["Alpine Watchdog"]))
    p2.battlefield.append(Permanent(card=_M21["Concordia Pegasus"]))

    game.cast_from_hand(0, "Goremand")
    game._settle()

    assert [p.card.name for p in p1.battlefield] == ["Goremand"]
    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog"]
    assert [p.card.name for p in p2.battlefield] == [], (
        "and its entry trigger made the opponent sacrifice too"
    )

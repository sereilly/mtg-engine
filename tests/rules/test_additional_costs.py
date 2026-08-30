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


# ---------------------------------------------------------------------------
# The payer chooses which card the discard eats, and the index means the hand
# they were looking at
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2b", "601.2a")
def test_the_payer_chooses_which_card_the_discard_cost_eats():
    """The other half of "the payer chooses". The sacrifice cost has taken a
    named permanent since round 44; the discard cost accepted an index and then
    read it *after* the spell had left the hand, so a caster naming the last
    card in hand fell past the shortened end and discarded the **first** one —
    the card a player is least likely to have meant."""
    game, p1, _p2 = _duel(
        [_M21["Shock"], _M21["Thrill of Possibility"], _M21["Alpine Watchdog"], _M21["Mountain"]]
    )
    p1.library = [_M21["Swamp"]] * 4

    game.cast_from_hand(0, "Thrill of Possibility", cost_hand_index=3)

    assert [c.name for c in p1.graveyard] == ["Mountain", "Thrill of Possibility"]
    assert "Shock" in [c.name for c in p1.hand]


@pytest.mark.cr("601.2b", "601.2a")
def test_a_named_discard_is_not_the_card_that_slides_into_its_slot():
    """The sharper half of the same bug, and the reason resolving the index
    early is the fix rather than clamping it. With the pick still in range after
    the spell left the hand, nothing looked wrong: the engine simply discarded
    the card that had slid up into the named slot."""
    game, p1, _p2 = _duel(
        [_M21["Shock"], _M21["Thrill of Possibility"], _M21["Alpine Watchdog"], _M21["Mountain"]]
    )
    p1.library = [_M21["Swamp"]] * 4

    game.cast_from_hand(0, "Thrill of Possibility", cost_hand_index=2)

    assert [c.name for c in p1.graveyard] == ["Alpine Watchdog", "Thrill of Possibility"]


@pytest.mark.cr("601.2a", "601.2b")
def test_naming_the_spell_itself_refuses_the_cast():
    """CR 601.2a puts the spell on the stack before its costs are paid, so it is
    not in the hand to be discarded. Refused before any mana is spent, and the
    whole announcement rewinds — the earlier test proves the *engine* never
    picks the spell; this one proves a client that asks for it is told no rather
    than quietly given something else."""
    game, p1, _p2 = _duel([_M21["Shock"], _M21["Thrill of Possibility"], _M21["Mountain"]])
    p1.library = [_M21["Swamp"]] * 4

    result = game.cast_from_hand(0, "Thrill of Possibility", cost_hand_index=1)

    assert not result.supported and "cannot be discarded to pay for itself" in result.details
    assert len(p1.hand) == 3 and not p1.graveyard and not game.stack


@pytest.mark.cr("601.2b")
def test_a_pick_that_names_no_card_refuses_rather_than_repointing():
    """The fallback that made the first bug invisible: an unusable index became
    a bare ``0``. Naming nothing at all is still the deterministic default —
    that is what keeps AI and headless play unblocked — but naming a card that
    is not there is an error, not a request for a different one."""
    game, p1, _p2 = _duel([_M21["Shock"], _M21["Thrill of Possibility"], _M21["Mountain"]])
    p1.library = [_M21["Swamp"]] * 4

    result = game.cast_from_hand(0, "Thrill of Possibility", cost_hand_index=9)

    assert not result.supported and "hand position 9" in result.details
    assert len(p1.hand) == 3 and not game.stack


@pytest.mark.cr("601.2b")
def test_naming_nothing_still_takes_the_deterministic_default():
    """The control for the two refusals above: a seat that names nothing — every
    AI and headless cast — keeps discarding the lowest-index card, which is the
    convention the pending-discard queue already uses."""
    game, p1, _p2 = _duel([_M21["Shock"], _M21["Thrill of Possibility"], _M21["Mountain"]])
    p1.library = [_M21["Swamp"]] * 4

    game.cast_from_hand(0, "Thrill of Possibility")

    assert [c.name for c in p1.graveyard] == ["Shock", "Thrill of Possibility"]


# ---------------------------------------------------------------------------
# A cost payment is not a target
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2b", "601.2c", "702.16b")
def test_a_creature_with_protection_can_still_pay_a_sacrifice_cost():
    """CR 601.2b's payment is not CR 601.2c's target, and protection only stops
    a permanent being *targeted* (CR 702.16b). Sacrifice is a black spell and a
    White Knight has protection from black: the payment path has always taken
    one happily, while the picker the UI runs refused to offer it. One question,
    two answers, and which you got depended on whether you were a person or a
    script — the round-48 disagreement arriving through the cost field."""
    game, p1, _p2 = _duel([_CATALOG["Sacrifice"]])
    p1.battlefield.append(Permanent(card=_LEA["White Knight"]))
    p1.battlefield.append(Permanent(card=_LEA["Grizzly Bears"]))

    offered = [t["name"] for t in game.cast_target_spec(0, _CATALOG["Sacrifice"])["valid_targets"]]
    assert offered == ["White Knight", "Grizzly Bears"]

    game.cast_from_hand(0, "Sacrifice", cost_permanent_index=0)

    assert [p.card.name for p in p1.battlefield] == ["Grizzly Bears"]
    assert p1.mana_pool["B"] == 2, "the White Knight's mana value"


# ---------------------------------------------------------------------------
# The preamble is not the cost — one vocabulary for both sentences that list one
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2b")
def test_601_2b_a_life_cost_is_read_beside_the_two_that_were_written_out():
    """The table used to be whole *phrases*, each writing "as an additional
    cost to cast this spell," out again — so the only part that varied was the
    clause after the comma, and a clause nobody had listed made the line unread.

    Fumarole's "pay 3 life" was one, and the way it surfaced is the point: the
    card had no other blocker, so the moment its second line parsed it would
    have compiled supported and cast for free.
    """
    from engine.cast_costs import additional_cost_for_line

    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, pay 3 life."
    )

    assert cost is not None
    assert cost.pay_life == 3
    assert cost.from_zone is None, "an unmarked cost applies from every zone"


@pytest.mark.cr("601.2b")
def test_601_2b_both_sentences_that_list_costs_read_one_vocabulary():
    """"as an additional cost …, **pay 3 life**" and "…by **paying 3 life** in
    addition to paying its other costs" list the same cost in two grammatical
    forms. Two clause tables would be two answers to what this engine can
    charge, and the one that grew slower would decide which cards were free."""
    from engine.cast_costs import additional_cost_for_line

    printed = additional_cost_for_line(
        "As an additional cost to cast this spell, pay 3 life."
    )
    permission = additional_cost_for_line(
        "You may cast this card from your graveyard by paying 3 life and "
        "discarding a card in addition to paying its other costs."
    )

    assert printed.pay_life == permission.pay_life == 3
    assert permission.discard_cards == 1
    assert permission.from_zone == "graveyard"


@pytest.mark.cr("601.2b")
def test_601_2b_a_clause_the_engine_cannot_charge_leaves_the_line_unread():
    """Every clause must be read or the whole sentence is refused. "Pay X life"
    (Fire Covenant) is the live one: X is announced as the spell is cast and
    this engine resolves it *after* the additional costs are charged, so a
    clause for it would charge zero — which is a spell cast for free wearing a
    cost's clothes."""
    from engine.cast_costs import additional_cost_for_line

    assert additional_cost_for_line(
        "As an additional cost to cast this spell, pay X life."
    ) is None
    assert additional_cost_for_line(
        "As an additional cost to cast this spell, exile a creature."
    ) is None

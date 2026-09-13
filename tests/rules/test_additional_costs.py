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

import re

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
    """Every clause must be read or the whole sentence is refused — a clause
    dropped is a spell cast for less than it prints.

    "Pay X life" (Fire Covenant) used to be the example here, on the grounds
    that X was announced after the costs were charged. That was true of the
    engine and not of the card: the announcement is CR 601.2b and the charge is
    CR 601.2h, in that order, and the gate ran in the wrong one. "Exile a
    creature" was the example after it and is read now too (Soul Exchange), so
    the boundary has moved again — and again at Urza's Saga, which prints two
    *activation* costs whose noun phrase is exactly "a permanent" (Barrin,
    Master Wizard; Claws of Gix). "Narrows nothing" turned out to be the wrong
    reading of those: the widest printed noun is still a printed noun, and a
    land is exactly what those cards say may pay. What the refusal was really
    guarding is a narrowing the reduction **lost**, and the reduction refuses
    rather than dropping.

    So what is left is a clause naming a **zone the payment path cannot
    reach**: the table charges what ``engine/mixins/stack/casting.py`` can
    collect, which is the caster's own battlefield, and a phrase it cannot
    enumerate must leave the line unread rather than be charged as the part of
    it that was."""
    from engine.cast_costs import additional_cost_for_line

    assert additional_cost_for_line(
        "As an additional cost to cast this spell, exile a creature card from "
        "your graveyard."
    ) is None
    # The widest printed noun *is* read, and its filter is empty — which the
    # payment path reads as "any permanent you control", the card's own words.
    unnarrowed = additional_cost_for_line(
        "As an additional cost to cast this spell, sacrifice a permanent."
    )
    assert unnarrowed is not None and unnarrowed.sacrifice_filter == {}


@pytest.mark.cr("601.2h")
def test_601_2h_an_x_life_cost_is_charged_the_announced_x():
    """"As an additional cost to cast this spell, pay X life." (Fire Covenant.)

    The amount is not printed on the card at all — it is the X the caster
    announces — so the gate and the charge have to read the same number, which
    is what ``AdditionalCost.life_charged`` is for."""
    from engine.cast_costs import additional_cost_for_line

    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, pay X life."
    )

    assert cost is not None and cost.pay_life_x
    assert cost.life_charged(4) == 4
    assert cost.life_charged(None) == 0, (
        "an X CR 107.3a left with the caster and the caster never announced "
        "is read as zero"
    )
    assert cost.describe() == "pay X life"


# --- W2G1 (Visions): a cost the tables cannot charge, and the two new clauses ---

from engine.alternative_costs import (
    unread_alternative_cost_sentence as _w2g1_unread_alt,
)
from engine.card_loader import manifest_set_paths as _w2g1_paths
from engine.cast_costs import (
    additional_cost_for_line,
    unread_cost_sentence as _w2g1_unread_add,
)
from engine.oracle import (
    chargeable_sacrifice_payload as _w2g1_chargeable,
    compile_card_oracle as _w2g1_compile,
)

_W2G1_VIS = {
    c.name: c
    for c in load_cards(manifest_set_path("VIS", include_measured=True))
}


def _w2g1_measured() -> dict:
    """Every card in the `measured` half of the manifest, by name.

    Built lazily rather than at import: the shipped assertion beside it is the
    one that must not depend on a set being present.
    """
    pool: dict = {}
    shipped = set(_w2g1_paths())
    for path in _w2g1_paths(include_measured=True):
        if path in shipped:
            continue
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


@pytest.mark.cr("601.2b", "118.9")
def test_601_2b_a_printed_cost_nothing_charges_makes_the_card_unsupported():
    """The standing invariant, as a gate.

    A card is supported when **any** of its lines is, so a spell whose effect
    line compiles reports supported however many of its other lines were
    dropped — and a dropped *cost* is not a missing feature, it is a card that
    resolves for a price it does not print. Three Visions cards were exactly
    that, green in every instrument except ``scripts/parse_coverage.py``,
    because a card that is not refused is invisible to a refusal census.

    Each table answers for its own sentence, so a clause taught to either one
    closes the gate for the card in the same edit; there is no whitelist here
    to fall behind.
    """
    assert _w2g1_unread_add(
        "As an additional cost to cast this spell, hum a tune."
    ) == "as an additional cost to cast this spell, hum a tune"
    assert _w2g1_unread_alt(
        "You may hum a tune rather than pay this spell's mana cost."
    ) is not None
    # A sentence the table *does* read is not "unread", which is the whole
    # distinction the boolean claim seam collapses.
    assert _w2g1_unread_add(
        "As an additional cost to cast this spell, sacrifice a creature."
    ) is None
    assert _w2g1_unread_add("Destroy target creature.") is None

    # …and a card whose cost the table *does* read stays supported, which is
    # the direction this gate must never move.
    assert _w2g1_compile(_M21["Village Rites"]).supported


@pytest.mark.cr("601.2b")
def test_601_2b_no_shipped_card_carries_a_cost_sentence_nothing_charges():
    """The measurement that made the gate above safe to add, kept as a test.

    A gate that refuses a printed cost is only safe while nothing shipped
    prints one the tables cannot read — and "safe today" is not a property a
    brief can carry forward, so it is asserted over the pool instead.

    **The two roles get two assertions, which is what Exodus's ingest showed
    was missing.** This read both halves and demanded both be empty, so it went
    red the day a `measured` set arrived printing buyback with a non-mana cost
    — an ingest is red on arrival for cards nobody can deck, which is the
    shape ``scripts/parse_coverage.py``'s docstring says not to build. The
    shipped half is the safety claim and stays an emptiness assertion. The
    measured half gets the invariant that is actually true there and is the
    whole point of the gate: a card printing a cost nothing charges is
    **unsupported**. That is a property rather than a list, it holds at every
    ingest, and Phase 4 cannot promote the set until the shipped assertion
    covers it.
    """
    shipped, measured = [], []
    for path in _w2g1_paths(include_measured=True):
        is_shipped = path in _w2g1_paths()
        for card in load_cards(path):
            for line in (card.oracle_text or "").split("\n"):
                if _w2g1_unread_add(line) or _w2g1_unread_alt(line):
                    (shipped if is_shipped else measured).append(
                        (card.name, line.strip())
                    )
    assert shipped == [], f"shipped cards printing a cost nothing charges: {shipped}"

    admitted = sorted(
        {name for name, _ in measured if _w2g1_compile(_w2g1_measured()[name]).supported}
    )
    assert admitted == [], (
        "measured cards printing a cost nothing charges that the support gate "
        f"admitted anyway — each would resolve for a price it does not print: {admitted}"
    )


@pytest.mark.cr("601.2b", "701.21a")
def test_701_21a_a_sacrifice_cost_names_only_the_payer_s_own_permanents():
    """"A player can't sacrifice … a permanent they don't control."

    The charger drops the ``controller`` narrowing on the premise that every
    path enumerates the payer's own battlefield first. That holds for "you
    control" and inverts for anyone else — so "sacrifice all lands your
    opponents control" was read as *your own* lands. Refusing the phrase is
    what leaves such a card unsupported instead of charging a price nobody
    printed.
    """
    assert _w2g1_chargeable({"type_filter": "land", "controller": "you"}) == {
        "type_filter": "land",
    }
    assert _w2g1_chargeable({"type_filter": "land", "controller": "opponent"}) is None
    assert additional_cost_for_line(
        "As an additional cost to cast this spell, sacrifice a creature an "
        "opponent controls."
    ) is None


@pytest.mark.cr("601.2b", "601.2h")
def test_601_2b_sacrifice_all_and_discard_your_hand_are_one_sentence():
    """Kaervek's Spite: a quantifier rather than a count, and the one sacrifice
    cost admitted with no card type named.

    Every other must name one — an unnamed cost lets the payment eat the
    cheapest thing on the board — and "all" is exactly the phrase for which
    that reasoning inverts: there is no cheapest thing, and the un-narrowed
    reading is the most expensive rather than the least. It is outside the
    CR 601.2h gate for the same reason: a board of nothing pays it in full.
    """
    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, sacrifice all permanents "
        "you control and discard your hand."
    )
    assert cost is not None
    assert cost.sacrifice_all_filter == {}
    assert cost.discard_whole_hand
    assert cost.sacrifice_count == 1  # untouched: "all" is not a count

    game, caster, victim = _duel([_W2G1_VIS["Kaervek's Spite"], _LEA["Black Lotus"]])
    caster.battlefield.append(Permanent(card=_LEA["Mons's Goblin Raiders"]))
    victim.battlefield.append(Permanent(card=_LEA["Forest"]))

    result = game.cast_from_hand(0, "Kaervek's Spite", target_player_index=1)

    assert result.supported, result.details
    assert caster.battlefield == []
    assert caster.hand == []
    assert [p.card.name for p in victim.battlefield] == ["Forest"]


@pytest.mark.cr("107.3a", "601.2b", "601.2h")
def test_107_3a_an_x_in_an_additional_cost_is_announced_as_the_spell_is_cast():
    """"If a spell … has a mana cost, alternative cost, **additional cost** …
    with an X in it, and the value of X isn't defined by the text of that
    spell, the controller … announces the value of X as part of casting."

    Infernal Harvest is the case that makes the rule visible: its printed mana
    cost is {1}{B} with no {X} at all, so this clause is the only place its X
    lives, and a reader that understood only digits would have charged one
    Swamp for however much damage the caster announced.
    """
    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, return X Swamps you "
        "control to their owner's hand."
    )
    assert cost is not None
    assert cost.return_count_x
    assert cost.return_filter == {"subtype_filter": "swamp"}
    # One reader for the gate and the payment, so the two cannot disagree.
    assert cost.returned_count(3) == 3
    assert cost.returned_count(None) == 0

    game, caster, victim = _duel([_W2G1_VIS["Infernal Harvest"]])
    for _ in range(3):
        caster.battlefield.append(Permanent(card=_LEA["Swamp"]))
    victim.battlefield.append(Permanent(card=_LEA["Hurloon Minotaur"]))

    # Targets first (CR 601.2c/d), costs after (CR 601.2h) — the rule order the
    # cast path walks, and why a divided spell is asked for a target before it
    # is asked whether it can pay.
    refused = game.cast_from_hand(
        0, "Infernal Harvest", x_value=4, divided_targets=[(1, 0)],
    )
    assert not refused.supported
    assert "CR 601.2h" in refused.details
    assert len(caster.battlefield) == 3

    paid = game.cast_from_hand(
        0, "Infernal Harvest", x_value=2, divided_targets=[(1, 0)],
    )
    assert paid.supported, paid.details
    assert len(caster.battlefield) == 1
    assert [c.name for c in caster.hand] == ["Swamp", "Swamp"]


# --- W4G2 (Visions): CR 107.3a's X does not live only in the mana cost --------

from engine.card_loader import manifest_set_paths as _w4g2_paths
from engine.cast_costs import costs_charged_from as _w4g2_all_costs

#: Both manifest roles, because the census this section pins is about the pool
#: rather than about what a player may deck today — and one of the two cards it
#: names is shipped while the other is not.
_W4G2_POOL = {
    card.name: card
    for path in _w4g2_paths(include_measured=True)
    for card in load_cards(path)
}


def _w4g2_costs(card):
    return _w4g2_all_costs(card, "hand")



@pytest.mark.cr("107.3a")
def test_107_3a_an_x_is_announced_for_a_cost_outside_the_mana_cost():
    """CR 107.3a: the caster announces X for "a mana cost, alternative cost,
    additional cost, and/or activation cost with an {X} … in it".

    Four places, and every reader of the question outside the engine asked the
    first one alone — as a substring probe of the printed mana-cost string.
    Fire Covenant's is ``{1}{B}{R}`` and Infernal Harvest's is ``{1}{B}``: both
    spell their X only in an additional cost, so both were offered no X and cast
    at the 0 an unmade CR 107.3a announcement reads as, which is legal and
    does nothing at all.
    """
    from engine.cast_costs import cast_announces_x

    for name in ("Fire Covenant", "Infernal Harvest"):
        card = _W4G2_POOL[name]
        assert "{X}" not in card.mana_cost.upper(), (
            f"{name}'s X is not in its mana cost — that is the whole point"
        )
        assert cast_announces_x(card), name

    # The mana-cost half of the same rule still answers yes, and a spell with no
    # X anywhere still answers no.
    assert cast_announces_x(_CATALOG["Fireball"])
    assert not cast_announces_x(_LEA["Lightning Bolt"])


@pytest.mark.cr("107.3a")
def test_107_3a_every_card_in_the_pool_whose_x_is_in_a_cost_is_named():
    """The census behind the fix, as a test rather than as a claim.

    Three cards in both manifest roles announce an X that is nowhere in their
    mana cost, and one of them (Fire Covenant, Ice Age) is in the **shipped**
    pool — so this was a live defect in a set players can already deck, not a
    Visions pre-ship item. A fourth card arriving here without a picker that
    asks for its X is the regression this pins.

    Haunting Misery (Weatherlight) is the third, and it arrived exactly the way
    the list is written to catch: its {1}{B}{B} prints no {X} at all, and the X
    lives only in "exile X creature cards from your graveyard".

    **Firestorm is the fourth, and it arrived the same way one wave later.** Its
    printed mana cost is {R}; the X is announced in "discard X cards" and then
    spent twice over by the damage line, which deals X to each of X targets. It
    is the first card in the pool whose *target count* is the announcement this
    census is about, so a picker that did not ask for the X would not merely
    resolve for nothing -- it would refuse the cast outright (CR 601.2c).

    **Hatred and Necrologia (Exodus) are the fifth and sixth, and their arrival
    is what showed this guard was inverted.** It asserted a *list of the cards
    the reader already detects*, so a seventh card that ``cast_announces_x``
    **missed** would leave the list unchanged and the test green — the guard was
    silent on exactly the regression its own docstring says it pins, and loud
    only when the engine got a new card right. What it asserts now is the
    property: an independent text probe over every printed cost sentence,
    compared against the reader in both directions. The list of names is gone,
    for the reason ``tests/ui/test_cast_target_kinds.py`` records one set
    earlier — a list of the cards that satisfy a property expires when a set
    prints the next one; the property does not.
    """
    from engine.cast_costs import cast_announces_x

    #: The other reading of "this card announces an X in a cost", owing nothing
    #: to ``cast_costs``: the printed line *is* a cost sentence (CR 601.2b's
    #: additional cost, buyback's, or CR 118.9's alternative) and it spells an X
    #: outside the reminder text.
    cost_line = re.compile(
        r"^(as an additional cost to cast this spell,|buyback"
        r"|.*rather than pay this spell's mana cost)",
        re.I,
    )
    probe = {
        card.name
        for card in _W4G2_POOL.values()
        for line in (card.oracle_text or "").splitlines()
        if cost_line.match(line.strip())
        and re.search(r"\bX\b", line.split("(")[0])
    }
    detected = {
        card.name for card in _W4G2_POOL.values() if cast_announces_x(card)
    }
    assert not (probe - detected), (
        "cards printing an X inside a cost sentence that cast_announces_x does "
        f"not read — the browser offers them no X box: {sorted(probe - detected)}"
    )

    # The half the old list was really watching, kept as a *derived* census: an
    # X the mana cost does not carry is the one CR 107.3a case the client cannot
    # find on its own, so every such card must be one the probe agrees about.
    outside = {
        name for name in detected
        if "{X}" not in (_W4G2_POOL[name].mana_cost or "").upper()
    }
    assert outside <= probe, sorted(outside - probe)
    assert outside, "no card announces an X outside its mana cost — vacuous"


@pytest.mark.cr("107.3a", "119.4", "601.2h")
def test_107_3a_the_announced_x_is_bounded_by_what_the_cost_can_pay():
    """CR 601.2h refuses a cast whose announcement prices a cost the caster
    cannot pay, so the announcement has a ceiling — and it is not the mana pool.

    Fire Covenant's X is paid in life (CR 119.4 caps a life payment at the life
    total) and Infernal Harvest's in Swamps. The picker reads the same numbers
    ``_unpayable_additional_cost`` refuses by, so it can neither offer an X the
    cast would reject nor hide one it would accept.
    """
    game, caster, _ = _duel([_W4G2_POOL["Fire Covenant"]])
    caster.life = 7
    assert game.cast_target_spec(0, _W4G2_POOL["Fire Covenant"])["max_x"] == 7
    caster.life = 2
    assert game.cast_target_spec(0, _W4G2_POOL["Fire Covenant"])["max_x"] == 2

    harvest = _W4G2_POOL["Infernal Harvest"]
    game, caster, _ = _duel([harvest])
    assert game.cast_target_spec(0, harvest)["max_x"] == 0, (
        "no Swamp to return is an X of zero, not an unbounded offer"
    )
    caster.battlefield = [Permanent(card=_LEA["Swamp"]) for _ in range(3)]
    game._settle()
    assert game.cast_target_spec(0, harvest)["max_x"] == 3


@pytest.mark.cr("107.3a", "601.2h")
def test_107_3a_the_ceiling_is_exactly_what_the_cast_gate_accepts():
    """The picker and the gate, compared directly over the same board: every X
    up to the ceiling is castable and the one above it is refused.

    Written as a comparison rather than as two numbers, because a picker and a
    gate with separate arithmetic between them is this engine's recurring
    defect — and on a cost the failure is an announcement the player makes and
    the game then throws away.
    """
    harvest = _W4G2_POOL["Infernal Harvest"]
    for swamps in (0, 2):
        game, caster, _ = _duel([harvest])
        game.enforce_mana_costs = True
        caster.mana_pool["B"] = 1
        caster.mana_pool["C"] = 1
        caster.battlefield = [Permanent(card=_LEA["Swamp"]) for _ in range(swamps)]
        game._settle()
        ceiling = game.cast_target_spec(0, harvest)["max_x"]
        assert ceiling == swamps

        refusal = game._unpayable_additional_cost(
            0, harvest, tuple(_w4g2_costs(harvest)),
            spell_hand_index=0, from_zone="hand", x_value=ceiling,
        )
        assert refusal is None, f"the picker offered {ceiling} and the gate refused it"
        over = game._unpayable_additional_cost(
            0, harvest, tuple(_w4g2_costs(harvest)),
            spell_hand_index=0, from_zone="hand", x_value=ceiling + 1,
        )
        assert over is not None, (
            f"the gate accepted {ceiling + 1} with {swamps} Swamps, so the "
            f"ceiling is hiding a legal announcement"
        )


# ---------------------------------------------------------------------------
# W2G1 (Weatherlight): a cost narrowed on an axis that is not a card type
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2b", "601.2h")
def test_601_2b_an_additional_cost_may_name_its_payment_by_colour():
    """Abjure: "As an additional cost to cast this spell, sacrifice a blue
    permanent." / "Counter target spell."

    The cost table refused the phrase for pinning no card *type*, which was the
    right refusal written as the wrong question. What the refusal is for is an
    **unnamed** cost — one whose noun phrase narrows nothing the charger can
    test, so the payment eats the cheapest thing the caster owns. "A blue
    permanent" names what may pay it exactly as precisely as "a creature" does;
    what it names is a colour.

    Refusing loudly was the right direction while it stood: the alternative is
    a counterspell cast for {U} with the cost claimed and skipped, which is
    what this whole module exists to prevent.
    """
    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, sacrifice a blue permanent."
    )
    assert cost is not None
    assert cost.sacrifice_filter == {"color_filter": "U"}
    # A phrase that narrows nothing used to refuse here too, on the same
    # "unnamed cost" ground — and Urza's Saga printed two costs that say
    # exactly that (Barrin, Master Wizard; Claws of Gix), where the land the
    # refusal was protecting is what the card allows. It is read now, with the
    # empty filter the payment path takes as "any permanent you control".
    unnarrowed = additional_cost_for_line(
        "As an additional cost to cast this spell, sacrifice a permanent."
    )
    assert unnarrowed is not None and unnarrowed.sacrifice_filter == {}


@pytest.mark.cr("202.4", "202.3")
def test_202_4_an_additional_cost_is_not_part_of_the_mana_cost():
    """"Any additional cost listed in an object’s rules text ... isn’t part of
    the mana cost."

    Goblin Grenade costs {R} and sacrifices a Goblin. The sacrifice is a cost
    the caster pays (CR 601.2h) and is **not** in the mana cost, so the card’s
    mana value stays 1 — which matters wherever mana value is read rather than
    paid: a "converted mana cost 2 or less" filter, an X count, a cost
    reduction.

    Asserted against every "as an additional cost" card in the pool rather than
    one example, because the failure this guards is a parser folding the extra
    cost into the cost it computed, and that would show up on whichever card
    happened to be parsed that way.
    """
    from engine.card_loader import load_catalog
    from engine.oracle import compile_card_oracle

    checked = 0
    for card in load_catalog():
        text = (card.oracle_text or "").lower()
        if "as an additional cost" not in text:
            continue
        if not compile_card_oracle(card).supported:
            continue
        checked += 1
        # The mana value is the printed symbols’ total and nothing else
        # (CR 202.3), so it agrees with the mana cost the card was printed with.
        assert card.cmc == _symbol_total(card.mana_cost), card.name

    assert checked >= 5, f"expected several such cards in the pool, saw {checked}"

    # And directly, on the card the rule is easiest to see on: the engine reads
    # the sacrifice as its own AdditionalCost and leaves {R} as the mana cost.
    # A reader that folded the two would either raise the mana value or drop the
    # sacrifice, and both stay visible here.
    from engine.cast_costs import additional_costs

    grenade = next(c for c in load_catalog() if c.name == "Goblin Grenade")
    assert grenade.mana_cost == "{R}"
    assert grenade.cmc == 1.0
    assert additional_costs(grenade), "the sacrifice is recorded, separately"


def _symbol_total(mana_cost: str) -> float:
    """The mana value of *mana_cost* (CR 202.3): generic + one per coloured pip."""
    import re

    total = 0
    for symbol in re.findall(r"\{([^}]+)\}", mana_cost or ""):
        if symbol.isdigit():
            total += int(symbol)
        elif symbol == "X":
            continue
        else:
            total += 1
    return float(total)


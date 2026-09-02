"""CR 118.9 — alternative costs, paid *rather than* a spell's mana cost.

"An alternative cost is a cost listed in a spell's text … that its controller
may pay rather than paying the spell's mana cost" (CR 118.9). The mechanic did
not exist in this engine at all before Alliances, and the shape of its absence
is worth recording because it is not the shape a coverage census reports:

* Force of Will and Pyrokinesis compiled **supported** the whole time, on their
  *other* line — the one that counters a spell or deals the damage. The
  defining line was claimed by nothing, produced nothing and cost nothing;
* so no refusal census could see them. ``scripts/parse_coverage.py`` could, and
  did: both sat in its unclaimed list, which is the instrument that reads the
  population "a card that works, doing less than it says".

What is asserted here is the rule rather than the card: an alternative cost is
announced at CR 601.2b, is optional (CR 118.9b), replaces the mana cost without
changing it (CR 118.9c), leaves additional costs in force (CR 118.9d), is
limited to one per spell (CR 118.9a), and is subject to CR 601.2h — an
unpayable cost makes the spell uncastable, never free.
"""

import pytest

from engine import Game, PlayerState, load_cards
from engine.alternative_costs import alternative_cost_for_line, alternative_costs
from engine.card_loader import manifest_set_path
from engine.models import Permanent

_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
# Alliances is measured, not shipped, so its cards are placed into the game
# directly — the same thing the additional-cost suite beside this does for M21.
_ALL = {
    c.name: c
    for c in load_cards(manifest_set_path("ALL", include_measured=True))
}


def _duel(hand: list, *, life: int = 20) -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[p1, p2])
    # Costs *on*: the whole point of an alternative cost is which price is paid,
    # and a game that enforces neither cannot tell the two apart.
    game.enforce_mana_costs = True
    p1.life = life
    return game, p1, p2


def _something_to_counter(game: Game) -> None:
    """Put an opposing Lightning Bolt on the stack, cost enforcement aside.

    Force of Will needs a spell to point at (CR 601.2c), and how the opponent
    paid for theirs is not what any test here is about.
    """
    game.players[1].hand.append(_LEA["Lightning Bolt"])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.enforce_mana_costs = True


@pytest.mark.cr("118.9", "118.9a", "601.2b")
def test_118_9_the_printed_sentence_is_read_as_a_cost_not_an_effect():
    """The line is a *price*, so it compiles to no instruction and is read by
    a table — the arrangement CR 601.2b's additional costs already use."""
    cost = alternative_cost_for_line(
        "You may pay 1 life and exile a blue card from your hand rather than "
        "pay this spell's mana cost."
    )
    assert cost is not None
    assert cost.pay_life == 1
    assert cost.exile_from_hand == ({"color_filter": "U"},)

    # Every clause must be read or the whole sentence refuses: a clause dropped
    # from an *alternative* cost is a spell cast for nothing at all.
    assert alternative_cost_for_line(
        "You may sing a song rather than pay this spell's mana cost."
    ) is None
    # …and the zone is part of the clause. The payment reaches one hand; a
    # sentence naming another zone must refuse rather than be charged here.
    assert alternative_cost_for_line(
        "You may exile a blue card from your graveyard rather than pay this "
        "spell's mana cost."
    ) is None


@pytest.mark.cr("118.9", "601.2h")
def test_118_9_the_alternative_cost_replaces_the_mana_cost():
    """Force of Will for {3}{U}{U} — cast with no mana at all, for 1 life and a
    blue card out of hand."""
    game, caster, _ = _duel([_ALL["Force of Will"], _LEA["Counterspell"]])
    _something_to_counter(game)

    result = game.cast_from_hand(0, "Force of Will", alternative_cost=True)

    assert result.supported, result.details
    assert caster.life == 19
    assert [c.name for c in caster.exile] == ["Counterspell"]
    assert caster.hand == []
    assert not game.stack, "the Bolt was countered"


@pytest.mark.cr("118.9b")
def test_118_9b_the_alternative_cost_is_optional_and_never_taken_by_default():
    """A caster who does not announce it pays the mana cost — and, with no mana,
    is refused. The engine spending a life total nobody offered would be the
    same bug as a cost nobody charges, pointing the other way."""
    game, caster, _ = _duel([_ALL["Force of Will"], _LEA["Counterspell"]])
    _something_to_counter(game)

    result = game.cast_from_hand(0, "Force of Will")

    assert not result.supported
    assert "insufficient mana" in result.details
    assert caster.life == 20
    assert caster.exile == []


@pytest.mark.cr("118.9c")
def test_118_9c_the_alternative_cost_does_not_change_the_spells_mana_cost():
    """CR 118.9c: "Spells and abilities that ask for that spell's mana cost still
    see the original value." Nothing in this seam rewrites the card."""
    force = _ALL["Force of Will"]
    assert force.mana_cost == "{3}{U}{U}"

    game, _, _ = _duel([force, _LEA["Counterspell"]])
    _something_to_counter(game)
    game.cast_from_hand(0, "Force of Will", alternative_cost=True)

    assert force.mana_cost == "{3}{U}{U}"


@pytest.mark.cr("601.2h", "119.4")
def test_601_2h_an_unpayable_alternative_cost_makes_the_spell_uncastable():
    """Both halves, and neither is a discount: no blue card refuses the cast, and
    so does too little life. CR 601.2e returns the game to the moment before the
    proposal, so nothing is spent either way."""
    game, caster, _ = _duel([_ALL["Force of Will"], _LEA["Mountain"]])
    _something_to_counter(game)
    result = game.cast_from_hand(0, "Force of Will", alternative_cost=True)
    assert not result.supported
    assert "no card in hand answers its alternative cost" in result.details
    assert caster.life == 20
    assert len(caster.hand) == 2, "the spell is still in hand"

    game, caster, _ = _duel([_ALL["Force of Will"], _LEA["Counterspell"]], life=0)
    _something_to_counter(game)
    result = game.cast_from_hand(0, "Force of Will", alternative_cost=True)
    assert not result.supported
    assert "cannot pay 1 life" in result.details
    assert caster.exile == []


@pytest.mark.cr("119.4")
def test_119_4_a_life_cost_may_be_paid_down_to_exactly_zero():
    """CR 119.4 permits a payment down to 0, not merely above it — so a caster on
    1 life may pay the last one. The state-based action that ends the game is a
    separate rule and runs afterwards (CR 704.5a)."""
    game, caster, _ = _duel([_ALL["Force of Will"], _LEA["Counterspell"]], life=1)
    _something_to_counter(game)

    result = game.cast_from_hand(0, "Force of Will", alternative_cost=True)

    assert result.supported, result.details
    assert caster.life == 0


@pytest.mark.cr("601.2a", "118.9")
def test_601_2a_a_second_copy_may_pay_but_the_spell_itself_may_not():
    """The spell is on the stack before its costs are paid, so it is not in the
    hand to be exiled — but a *second copy* is a different card in the game and
    legitimately pays. The two are the same Python object (a deck repeats one
    immutable definition per copy), which is why the withholding is by hand
    position and the removal is ``Game.take_card_from_hand``."""
    force = _ALL["Force of Will"]
    game, caster, _ = _duel([force, force, _LEA["Grizzly Bears"]])
    _something_to_counter(game)

    result = game.cast_from_hand(0, "Force of Will", alternative_cost=True)

    assert result.supported, result.details
    assert [c.name for c in caster.exile] == ["Force of Will"]
    # Exactly one copy left the hand to exile and exactly one to the stack: the
    # identity filter this seam bans would have removed both at once.
    assert [c.name for c in caster.hand] == ["Grizzly Bears"]


@pytest.mark.cr("118.9", "601.2b")
def test_118_9_a_named_card_that_does_not_answer_the_phrase_is_refused():
    """Not slid onto a legal one: a stale click must not exile the card the
    player meant to keep. The same answer the additional discard cost gives."""
    game, caster, _ = _duel(
        [_ALL["Force of Will"], _LEA["Grizzly Bears"], _LEA["Counterspell"]]
    )
    _something_to_counter(game)

    result = game.cast_from_hand(
        0, "Force of Will", alternative_cost=True, alternative_cost_hand_index=1,
    )

    assert not result.supported
    assert "does not answer its alternative cost" in result.details
    assert caster.exile == []
    assert caster.life == 20

    # …and the index that *does* answer it pays, rather than the deterministic
    # first pick — the choice is the caster's (CR 601.2b).
    game, caster, _ = _duel(
        [_ALL["Force of Will"], _LEA["Ancestral Recall"], _LEA["Counterspell"]]
    )
    _something_to_counter(game)
    result = game.cast_from_hand(
        0, "Force of Will", alternative_cost=True, alternative_cost_hand_index=2,
    )
    assert result.supported, result.details
    assert [c.name for c in caster.exile] == ["Counterspell"]


@pytest.mark.cr("118.9a")
def test_118_9a_a_cost_waiver_and_a_printed_alternative_cost_cannot_both_apply():
    """"A player can't apply two alternative methods of casting or two
    alternative costs to a single spell." A ``CastPermission`` with ``free`` set
    is CR 118.9's other spelling, so a caster who announced the printed cost is
    not also handed the waiver — which would make the life and the card a pure
    loss on a spell that was already free."""
    from engine.cast_permissions import grant_permission

    force = _ALL["Force of Will"]
    game, caster, _ = _duel([force, _LEA["Counterspell"]])
    # A *named* one-use waiver, so the difference is visible: a blanket grant is
    # unlimited and being wrongly applied to this cast would leave no trace.
    grant_permission(
        game, player_index=0, zone="hand", cards=[force], free=True,
        source_name="a waiver", duration=None,
    )
    _something_to_counter(game)

    result = game.cast_from_hand(0, "Force of Will", alternative_cost=True)

    assert result.supported, result.details
    # The announced price was paid, not skipped.
    assert caster.life == 19
    assert [c.name for c in caster.exile] == ["Counterspell"]
    # …and the waiver is untouched: applying it here would have spent a one-use
    # grant on a spell that was already being paid for another way.
    assert [p.source_name for p in game.cast_permissions] == ["a waiver"]
    assert not any(
        "without paying its mana cost" in line for line in game.log
    ), game.log


@pytest.mark.cr("118.9")
def test_118_9_announcing_an_alternative_cost_a_card_does_not_print_is_refused():
    """Silence is not consent in either direction: a caller that asks for a
    price the card never named gets a refusal, not an ordinary cast that quietly
    ignored the request."""
    game, _, _ = _duel([_LEA["Lightning Bolt"]])

    result = game.cast_from_hand(
        0, "Lightning Bolt", alternative_cost=True, target_player_index=1,
    )

    assert not result.supported
    assert "prints no alternative cost" in result.details


@pytest.mark.cr("118.9d", "601.2b")
def test_118_9d_additional_costs_stay_in_force_beside_an_alternative_one():
    """CR 118.9d: "any additional costs … that affect that spell are applied to
    that alternative cost". The two live in separate tables and are paid in
    separate steps, so this asserts the *arrangement* — no card in the pool
    prints both, and the day one does, nothing has to be rewired."""
    force = _ALL["Force of Will"]
    from engine.cast_costs import additional_costs

    assert alternative_costs(force) and not additional_costs(force)

    surge = _ALL["Surge of Strength"]
    assert additional_costs(surge) and not alternative_costs(surge)


@pytest.mark.cr("601.2b", "601.2h")
def test_601_2b_a_narrowed_discard_cost_is_read_and_charged():
    """"As an additional cost to cast this spell, discard a **red or green**
    card" (Surge of Strength). The narrowing is a shared-head disjunction —
    one noun phrase with two colour adjectives — which the cost table read as
    nothing at all, so the card compiled ``supported`` on its other line and was
    cast discarding nothing."""
    from engine.cast_costs import additional_costs

    (cost,) = additional_costs(_ALL["Surge of Strength"])
    assert cost.discard_cards == 1
    assert cost.discard_filters == ({"any_colors": ["R", "G"]},)

    game, caster, _ = _duel(
        [_ALL["Surge of Strength"], _LEA["Island"], _LEA["Grizzly Bears"]]
    )
    game.enforce_mana_costs = False
    caster.battlefield.append(Permanent(card=_LEA["Grizzly Bears"]))

    result = game.cast_from_hand(0, "Surge of Strength", target_permanent_index=0)

    assert result.supported, result.details
    # The green card paid, not the first card in hand.
    assert [c.name for c in caster.hand] == ["Island"]
    assert "Grizzly Bears" in [c.name for c in caster.graveyard]


@pytest.mark.cr("601.2h")
def test_601_2h_a_narrowed_discard_with_no_answering_card_refuses_the_cast():
    """The gate counts the cards the phrase *names*, not the hand. Counting the
    hand would admit a cast the payment could not collect, and the payment would
    then fall back to discarding whatever was first."""
    game, caster, _ = _duel([_ALL["Surge of Strength"], _LEA["Island"]])
    game.enforce_mana_costs = False
    caster.battlefield.append(Permanent(card=_LEA["Grizzly Bears"]))

    result = game.cast_from_hand(0, "Surge of Strength", target_permanent_index=0)

    assert not result.supported
    assert "no card in hand answers this cost" in result.details
    assert [c.name for c in caster.hand] == ["Surge of Strength", "Island"]

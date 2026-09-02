"""Exiling cards off a library as a *cost* — CR 118, CR 602.2b, CR 702.24a.

Alliances prints the pattern six times ("{2}, Exile the top card of your
library: …"), and it is a cost like any other: CR 118.1 makes paying it the
carrying out of the printed action, and CR 118.3 makes a library holding fewer
cards than the printed count unable to pay it at all.

Written against **invented** cards, which is the check ``engine/card_hooks.py``
describes: give a card nobody printed the same printed text and see whether it
works. If any of these needed a card name, the machinery behind them would be
one card's rather than the template's.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, parse_activated_ability_cost


def _card(
    name: str, type_line: str, oracle_text: str = "", *, cmc: float = 0.0,
    power: str = "1", toughness: str = "1", keywords: tuple[str, ...] = (),
) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = power
        raw["toughness"] = toughness
    return CardDefinition(
        name=name, mana_cost="", cmc=cmc, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(),
        keywords=keywords, produced_mana=(), raw=raw,
    )


def _filler(count: int, cmc: float = 0.0) -> list[CardDefinition]:
    return [_card("Filler", "Artifact", cmc=cmc) for _ in range(count)]


def _board(card: CardDefinition, library: list[CardDefinition]):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=list(library)),
        PlayerState(name="P2", library=_filler(5)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, perm


@pytest.mark.cr("118.1", "118.3")
def test_a_library_exile_cost_is_read_by_the_cost_parser():
    """CR 118.1: the cost is the printed action, so the compiler records how
    many cards it takes rather than treating the clause as effect text."""
    one = parse_activated_ability_cost(
        "{2}, Exile the top card of your library: You gain 1 life."
    )
    assert one.exile_top_of_library == 1
    assert one.mana["generic"] == 2

    four = parse_activated_ability_cost(
        "{3}, Exile the top four cards of your library: You gain 1 life."
    )
    assert four.exile_top_of_library == 4

    plain = parse_activated_ability_cost("{2}: You gain 1 life.")
    assert plain.exile_top_of_library == 0, "0 is the honest 'no such cost'"


@pytest.mark.cr("118.1", "601.2h")
def test_the_cost_is_paid_when_the_ability_is_activated():
    """CR 601.2h (through CR 602.2b): the cost is paid on the way to the stack,
    so the cards are gone before the ability resolves."""
    card = _card(
        "Test Herbalist", "Creature - Human",
        "{2}, Exile the top card of your library: You gain 1 life.",
    )
    game, _perm = _board(card, _filler(3))
    me = game.players[0]
    assert game.activate_permanent_ability(0, card.name).supported
    assert len(me.library) == 2 and len(me.exile) == 1, (
        "paid on activation, not on resolution"
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert me.life == 21


@pytest.mark.cr("118.3", "601.2h")
def test_a_short_library_cannot_pay_a_library_exile_cost():
    """CR 118.3: a player can't pay a cost without the resources to pay it
    **fully**, and CR 601.2h forbids partial payments — so three cards do not
    pay a four-card cost and nothing at all is spent.

    The failure this guards is not a crash: it is an ability that works more
    often than the card allows, exiling what is there and resolving anyway.
    """
    card = _card(
        "Test Tactician", "Creature - Human",
        "{3}, Exile the top four cards of your library: You gain 1 life.",
    )
    game, _perm = _board(card, _filler(3))
    me = game.players[0]
    assert not game.activate_permanent_ability(0, card.name).supported
    assert len(me.library) == 3 and not me.exile
    assert not game.stack
    assert me.life == 20


@pytest.mark.cr("118.3")
def test_an_empty_library_cannot_pay_a_one_card_cost():
    """The degenerate case of the rule above, and the one a clamp would hide:
    exiling zero cards is not paying a one-card cost."""
    card = _card(
        "Test Herbalist", "Creature - Human",
        "{2}, Exile the top card of your library: You gain 1 life.",
    )
    game, _perm = _board(card, [])
    assert not game.activate_permanent_ability(0, card.name).supported
    assert game.players[0].life == 20


@pytest.mark.cr("608.2h")
def test_the_effect_reads_the_card_the_cost_exiled():
    """CR 608.2h: by resolution the card is in exile, so what the sentence
    behind the colon asks about is the payment path's record of it — here its
    mana value, counted into X."""
    card = _card(
        "Test Devourer", "Artifact Creature - Construct",
        "Exile the top card of your library: Put X +1/+1 counters on this "
        "creature, where X is the exiled card's mana value.",
    )
    game, perm = _board(card, _filler(3, cmc=3.0))
    assert game.activate_permanent_ability(0, card.name).supported
    game.resolve_top_of_stack()
    assert (perm.effective_power, perm.effective_toughness) == (4, 4)


@pytest.mark.cr("603.8")
def test_a_power_threshold_state_trigger_fires_as_soon_as_the_state_matches():
    """CR 603.8: a state trigger fires whenever the game state matches its
    condition, not on an event — so it is swept for rather than announced from
    any one call site, and a power that arrives from *anywhere* trips it."""
    card = _card(
        "Test Threshold", "Creature - Construct",
        "When this creature's power is 4 or greater, sacrifice it.",
        power="1", toughness="1",
    )
    game, perm = _board(card, _filler(1))
    game.check_state_based_actions()
    assert game.is_on_battlefield(perm), "1 power is under the threshold"

    game.place_plus1_counters(perm, 3)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(perm)
    assert [c.name for c in game.players[0].graveyard] == [card.name]


@pytest.mark.cr("702.24a", "118.3")
def test_cumulative_upkeep_charges_a_non_mana_cost_and_escalates_it():
    """CR 702.24a admits *any* cost after the keyword, and "for each age
    counter on it" scales the whole of it — so a library-exile upkeep takes one
    card, then two, then three."""
    card = _card(
        "Test Lash", "Enchantment",
        "Cumulative upkeep—Exile the top card of your library.",
    )
    perm = Permanent(card=card)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=_filler(12)),
        PlayerState(name="P2", library=_filler(12)),
    ])
    game.enforce_mana_costs = False
    for expected in (1, 3, 6):
        game.start_turn(0)
        while game.stack:
            game.resolve_top_of_stack()
        assert len(game.players[0].exile) == expected
        assert game.is_on_battlefield(perm)
        game.start_turn(1)
        while game.stack:
            game.resolve_top_of_stack()


@pytest.mark.cr("702.24a", "118.3")
def test_a_library_too_short_for_the_cumulative_upkeep_sacrifices_the_permanent():
    """The same rule from the other side: a cost that cannot be paid in full is
    not paid at all, and CR 702.24a's "if you don't" then applies."""
    card = _card(
        "Test Lash", "Enchantment",
        "Cumulative upkeep—Exile the top card of your library.",
    )
    perm = Permanent(card=card)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=[]),
        PlayerState(name="P2", library=_filler(5)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    while game.stack:
        game.resolve_top_of_stack()
    assert not game.is_on_battlefield(perm)


@pytest.mark.cr("404.1")
def test_the_top_of_a_graveyard_is_the_card_put_there_last():
    """CR 404.1 makes a graveyard an ordered pile with new objects on **top**,
    so "the top card of your graveyard" is the most recent one — reading it as
    the first card the pile ever held names a different card every time."""
    card = _card(
        "Test Digger", "Artifact",
        "{2}: Put the top card of your graveyard on the bottom of your library.",
    )
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[perm], library=[_card("Deck Card", "Artifact")],
            graveyard=[_card("Oldest", "Artifact"), _card("Newest", "Artifact")],
        ),
        PlayerState(name="P2", library=_filler(5)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    assert game.activate_permanent_ability(0, card.name).supported
    game.resolve_top_of_stack()
    me = game.players[0]
    assert [c.name for c in me.graveyard] == ["Oldest"]
    assert [c.name for c in me.library] == ["Deck Card", "Newest"]


@pytest.mark.cr("118.3", "602.2b")
def test_an_unpayable_library_cost_spends_no_mana_and_taps_nothing():
    """CR 602.2b: the ability is never activated, so no other half of its cost
    is spent either — the failure mode that would leave a permanent tapped for
    an ability that never happened."""
    card = _card(
        "Test Tapper", "Artifact",
        "{T}, Exile the top two cards of your library: You gain 1 life.",
    )
    game, perm = _board(card, _filler(1))
    assert compile_card_oracle(card).supported
    assert not game.activate_permanent_ability(0, card.name).supported
    assert not perm.tapped
    assert len(game.players[0].library) == 1


# ---------------------------------------------------------------------------
# The picker/gate half of the same round: a narrowing only the *game* can test
# ---------------------------------------------------------------------------
#
# Found by giving Storm Elemental's "Tap target creature with flying" a game.
# ``legality._ability_target_legal``'s tap arm asked the **pure** matcher, which
# by design cannot answer three of the keys these payloads carry — a keyword is
# layer 6, a controller is a seat, "attacking you" is a combat record — and
# ignores them rather than refusing. Four cards in the pool print one, three of
# them shipped.


def _tap_rig(pool_card, keywords=()):
    """*pool_card* on seat 0, with a flier and a ground creature on seat 1 and
    one of the activator's own creatures beside the source."""
    source = Permanent(card=pool_card)
    source.metadata["summoning_sickness_turn"] = -99
    flier = Permanent(card=_card(
        "Sky Thing", "Creature - Bird", "Flying",
        power="2", toughness="2", keywords=("flying",),
    ))
    ground = Permanent(card=_card("Ground Thing", "Creature - Bear", power="2", toughness="2"))
    mine = Permanent(card=_card("My Own Guy", "Creature - Bear", power="2", toughness="2"))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[source, mine], library=_filler(5)),
        PlayerState(name="P2", battlefield=[flier, ground], library=_filler(5)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, source, flier, ground, mine


@pytest.mark.cr("601.2c", "602.2b")
def test_a_keyword_narrowed_tap_target_refuses_the_wrong_creature(set_pool):
    """"{U}{U}: Tap target creature **without flying**." (Flood, The Dark.)

    CR 601.2c: the announced target must be legal, and CR 602.2b applies that
    to an activation — so naming a flier refuses the whole activation with
    nothing paid. It used to be *activatable*: the ability resolved, the
    handler re-read the filter and tapped nothing, and the printed word was
    enforced by nobody.
    """
    game, _flood, flier, ground, _mine = _tap_rig(set_pool("DRK")["Flood"])
    assert not game.activate_permanent_ability(
        0, "Flood", target_player_index=1, target_permanent_index=0
    ).supported
    assert not game.stack
    assert game.activate_permanent_ability(
        0, "Flood", target_player_index=1, target_permanent_index=1
    ).supported
    while game.stack:
        game.resolve_top_of_stack()
    assert ground.tapped and not flier.tapped


@pytest.mark.cr("601.2c", "602.2b")
def test_a_seat_narrowed_tap_target_refuses_your_own_creature(set_pool):
    """"Tap two untapped Spirits you control: Tap target creature **you don't
    control**." (Shacklegeist, M21.) The same gate with the narrowing on a
    seat rather than a keyword."""
    game, _geist, _flier, _ground, mine = _tap_rig(set_pool("M21")["Shacklegeist"])
    own_index = game.battlefield_index_of(mine)
    assert not game.activate_permanent_ability(
        0, "Shacklegeist", target_player_index=0, target_permanent_index=own_index
    ).supported
    assert not mine.tapped

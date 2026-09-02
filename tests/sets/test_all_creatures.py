"""Per-card tests for Alliances' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G2: library-top costs ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g2_card(name: str, type_line: str, mana_cost: str = "") -> CardDefinition:
    """A vanilla card to stack a library with, invented so the only thing that
    varies between the halves of each pair below is the characteristic under
    test."""
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(len(mana_cost) // 3),
        type_line=type_line, oracle_text="", colors=(), color_identity=(),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    )


def _w1g2_board(set_pool, name: str, library: list[CardDefinition]):
    """*name* on the battlefield with *library* under it, ready to activate."""
    perm = Permanent(card=set_pool("ALL")[name])
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=list(library)),
        PlayerState(name="P2", library=[_w1g2_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, perm


def test_royal_herbalist_exiles_the_top_card_to_gain_a_life(set_pool):
    """"{2}, Exile the top card of your library: You gain 1 life."

    CR 118.1: paying the cost is carrying out the printed action, so the card
    is in exile before the ability is on the stack — and the life arrives
    whatever that card was.
    """
    game, _perm = _w1g2_board(
        set_pool, "Royal Herbalist", [_w1g2_card("Top Card", "Artifact")] * 3
    )
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Royal Herbalist")
    assert result.supported, result.details
    assert len(me.library) == 2, "the cost came off the library on activation"
    assert [card.name for card in me.exile] == ["Top Card"]
    game.resolve_top_of_stack()
    assert me.life == 21


def test_royal_herbalist_cannot_be_activated_with_an_empty_library(set_pool):
    """CR 118.3: a player can't pay a cost without the resources to pay it
    *fully*, so an empty library makes this ability unactivatable — never a
    free one, and never one that exiles nothing and gains the life anyway."""
    game, _perm = _w1g2_board(set_pool, "Royal Herbalist", [])
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Royal Herbalist")
    assert not result.supported
    assert me.life == 20, "nothing was gained"
    assert not game.stack, "the ability never reached the stack"


def test_seasoned_tactician_needs_four_cards_for_its_four_card_cost(set_pool):
    """"{3}, Exile the top four cards of your library: …"

    The counted cost, and CR 118.3's "fully" is the whole of it: three cards
    do not pay a four-card cost, and the three are still there afterwards.
    """
    game, _perm = _w1g2_board(
        set_pool, "Seasoned Tactician", [_w1g2_card("Card", "Artifact")] * 3
    )
    me = game.players[0]
    assert not game.activate_permanent_ability(0, "Seasoned Tactician").supported
    assert len(me.library) == 3 and not me.exile

    me.library.append(_w1g2_card("Card", "Artifact"))
    assert game.activate_permanent_ability(0, "Seasoned Tactician").supported
    assert not me.library and len(me.exile) == 4


def test_storm_elemental_reads_back_the_card_its_cost_exiled(set_pool):
    """"{U}, Exile the top card of your library: If the exiled card is a snow
    land, this creature gets +1/+1 until end of turn."

    The sentence asks about the card the *cost* ate, which by resolution is in
    exile (CR 608.2h) — so the answer is the record the payment kept, and the
    snow supertype is what it is asked for.
    """
    snow = _w1g2_card("Snowy", "Basic Snow Land - Mountain")
    plain = _w1g2_card("Plain Land", "Basic Land - Mountain")

    game, elemental = _w1g2_board(set_pool, "Storm Elemental", [snow, snow])
    assert game.activate_permanent_ability(0, "Storm Elemental", ability_index=1).supported
    game.resolve_top_of_stack()
    assert (elemental.effective_power, elemental.effective_toughness) == (4, 5)

    game, elemental = _w1g2_board(set_pool, "Storm Elemental", [plain, plain])
    assert game.activate_permanent_ability(0, "Storm Elemental", ability_index=1).supported
    game.resolve_top_of_stack()
    assert (elemental.effective_power, elemental.effective_toughness) == (3, 4), (
        "an ordinary land is not a snow land"
    )


def test_chaos_harlequin_branches_on_the_card_its_effect_exiled(set_pool):
    """"{R}: Exile the top card of your library. If that card is a land card,
    this creature gets -4/-0 until end of turn. Otherwise, this creature gets
    +2/+0 until end of turn."

    The exile here is the *effect*, not the cost, and "that card" is the
    pronoun for what the step in front of it moved — the same back-reference
    "it was" spells with a bare pronoun.
    """
    game, harlequin = _w1g2_board(
        set_pool, "Chaos Harlequin", [_w1g2_card("Plain Land", "Basic Land - Mountain")]
    )
    assert game.activate_permanent_ability(0, "Chaos Harlequin").supported
    game.resolve_top_of_stack()
    assert (harlequin.effective_power, harlequin.effective_toughness) == (-2, 4)

    game, harlequin = _w1g2_board(
        set_pool, "Chaos Harlequin", [_w1g2_card("Some Spell", "Artifact")]
    )
    assert game.activate_permanent_ability(0, "Chaos Harlequin").supported
    game.resolve_top_of_stack()
    assert (harlequin.effective_power, harlequin.effective_toughness) == (4, 4)


# --- W1G5: delayed triggers ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path


def _w1g5_lea(name: str):
    """One Limited Edition Alpha card, for the graveyards these tests build."""
    for card in load_cards(manifest_set_path("LEA", include_measured=True)):
        if card.name == name:
            return card
    raise AssertionError(f"{name} is not in LEA")


def _w1g5_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def test_w1g5_krovikan_horror_returns_itself_at_the_end_step(set_pool):
    """CR 113.6b: "if this card is in your graveyard …" is where the card states
    which zone the ability functions in, and CR 404.3's order is what "directly
    above it" reads."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])

    game.resolve_end_step(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]


def test_w1g5_krovikan_horror_answers_to_an_opponents_end_step(set_pool):
    """"At the beginning of **the** end step" — not "your". CR 513.1 gives every
    turn one end step and this ability names whichever comes next, so the scan
    is unseated where Death Spark's upkeep one is not."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])
    game.active_player_index = 1

    game.resolve_end_step(1)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]


def test_w1g5_krovikan_horror_stays_put_with_nothing_above_it(set_pool):
    """CR 603.4: the intervening-if is checked when the trigger would fire. On
    top of the pile there is nothing above it, so nothing fires."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([_w1g5_lea("Grizzly Bears"), horror])

    game.resolve_end_step(0)
    game._settle()

    assert p1.hand == []
    assert p1.graveyard[-1] is horror


def test_w1g5_nether_shadows_deeper_condition_still_reads(set_pool):
    """The three-cards-above spelling is the same clause with a different number,
    and it must keep answering the way it did — Nether Shadow's line is claimed
    by a card hook, and a condition production that changed what "above" means
    would have moved it silently."""
    from engine.graveyard_order import satisfies_above

    bear = _w1g5_lea("Grizzly Bears")
    forest = _w1g5_lea("Forest")
    pile = [set_pool("ALL")["Krovikan Horror"], bear, bear, bear]
    spec = {"card_type": "creature", "count": 3, "op": "ge", "directly": False}
    assert satisfies_above(pile, 0, spec)
    assert not satisfies_above([pile[0], bear, forest], 0, spec)

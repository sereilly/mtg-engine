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

"""Per-card tests for Alliances' enchantments.

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


def _w1g2_card(name: str = "Deck Card") -> CardDefinition:
    """A vanilla card to stack a library with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Artifact", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def _w1g2_board(set_pool, name: str, library_size: int):
    perm = Permanent(card=set_pool("ALL")[name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=[_w1g2_card()] * library_size),
        PlayerState(name="P2", library=[_w1g2_card()] * 10),
    ])
    game.enforce_mana_costs = False
    return game, perm


def _w1g2_settle(game):
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()


def test_thought_lash_cumulative_upkeep_exiles_more_each_turn(set_pool):
    """"Cumulative upkeep—Exile the top card of your library."

    CR 702.24a's cost is *any* cost, and "for each age counter on it" scales
    the whole of it — so the second upkeep exiles two cards and the third
    three. A cost read as mana-only would have made this permanent free
    forever.
    """
    game, lash = _w1g2_board(set_pool, "Thought Lash", 12)
    me = game.players[0]
    for expected in (1, 3, 6):
        game.start_turn(0)
        _w1g2_settle(game)
        assert len(me.exile) == expected
        assert game.is_on_battlefield(lash)
        game.start_turn(1)
        _w1g2_settle(game)


def test_thought_lash_unpaid_upkeep_exiles_the_whole_library(set_pool):
    """"When a player doesn't pay this enchantment's cumulative upkeep, that
    player exiles all cards from their library."

    The trigger's one fire site is the upkeep handler's non-payment branch —
    nothing on a board records who declined — and "that player" is the seat
    that event froze. The enchantment is sacrificed either way (CR 702.24a).
    """
    game, lash = _w1g2_board(set_pool, "Thought Lash", 8)
    me = game.players[0]
    game.start_turn(0)
    game.resolve_upkeep(0, human_choices={"Thought Lash": False})
    _w1g2_settle(game)
    assert not me.library, "the whole library went to exile"
    assert len(me.exile) == 8
    assert not game.is_on_battlefield(lash)


def test_thought_lash_with_an_empty_library_cannot_pay_its_upkeep(set_pool):
    """CR 118.3 in the upkeep's half of the engine: a library holding fewer
    cards than the cost names cannot pay it *fully*, so none of it is paid and
    CR 702.24a sacrifices the permanent."""
    game, lash = _w1g2_board(set_pool, "Thought Lash", 0)
    game.start_turn(0)
    _w1g2_settle(game)
    assert not game.is_on_battlefield(lash)


def test_thought_lash_prevention_ability_charges_its_library_cost(set_pool):
    """"Exile the top card of your library: Prevent the next 1 damage that
    would be dealt to you this turn."

    The third line, and the one with no mana in its cost at all.
    """
    game, _lash = _w1g2_board(set_pool, "Thought Lash", 4)
    me = game.players[0]
    assert game.activate_permanent_ability(0, "Thought Lash").supported
    assert len(me.library) == 3 and len(me.exile) == 1
    game.resolve_top_of_stack()
    assert me.damage_prevention_pool == 1

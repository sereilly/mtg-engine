"""Per-card tests for Homelands' sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

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


# --- W1G3: prevention, redirection and filtered damage ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g3_cast(set_pool, spell, *battlefield, poison=0):
    """Cast *spell* from HML at seat 1, with *battlefield* on the opponent's
    board, and resolve it.

    ``(set_code, name)`` pairs for the creatures, because these two spells are
    both about which permanents a printed noun phrase names and the pool has to
    contain ones it does *not*.
    """
    perms = [Permanent(card=set_pool(code)[name]) for code, name in battlefield]
    p0 = PlayerState(name="P0", hand=[set_pool("HML")[spell]])
    p1 = PlayerState(name="P1", battlefield=perms)
    p1.poison_counters = poison
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._settle()
    result = game.cast_from_hand(0, spell, target_player_index=1)
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return game, result, p1, perms


def test_evaporate_burns_every_white_or_blue_creature_and_nothing_else(set_pool):
    """"Evaporate deals 1 damage to each white and/or blue creature."

    The printed conjunction is a **union** (CR 105.2 gives an object one or more
    colours), so a white creature and a blue one are both in the set and a green
    one is not. Read as an intersection the spell would hit nothing at all; read
    with the conjunction dropped it would hit the whole board.
    """
    game, result, _p1, (white, blue, green) = _g3_cast(
        set_pool, "Evaporate",
        ("LEA", "White Knight"),
        ("LEA", "Merfolk of the Pearl Trident"),
        ("LEA", "Grizzly Bears"),
    )

    assert result.supported, result.details
    assert white.damage_marked == 1
    assert not game.is_on_battlefield(blue), "a 1/1 took lethal damage"
    assert green.damage_marked == 0, "green is neither white nor blue"


def test_leeches_deals_the_number_of_counters_it_actually_removed(set_pool):
    """"Target player loses all poison counters. Leeches deals that much damage
    to that player."

    "That much" is the count the *first* sentence took off, read out of the
    resolution's scratchpad — by the time the damage runs the store holds zero,
    so a reading that asked the player again would deal nothing.
    """
    _game, result, victim, _perms = _g3_cast(set_pool, "Leeches", poison=3)

    assert result.supported, result.details
    assert victim.poison_counters == 0
    assert victim.life == 17


def test_leeches_deals_nothing_to_an_unpoisoned_player(set_pool):
    """The same back-reference from the other end: nothing was removed, so
    nothing is dealt. A "that much" that fell back to a printed number would
    make this spell a burn spell."""
    _game, result, victim, _perms = _g3_cast(set_pool, "Leeches", poison=0)

    assert result.supported, result.details
    assert victim.life == 20


# --- W1G2: counted amounts ---

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent


def _w1g2_game(mine, hand, theirs=()):
    p1 = PlayerState(name="P1", battlefield=list(mine), hand=list(hand))
    p2 = PlayerState(name="P2", battlefield=list(theirs))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, p1, p2


def _w1g2_creature(name, colors=("G",), toughness="4"):
    return Permanent(card=CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Human",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Human",
             "power": "1", "toughness": toughness},
    ))


def _w1g2_aura(name):
    return Permanent(card=CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Enchantment — Aura",
        oracle_text="Enchant creature", colors=("U",), color_identity=("U",),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment — Aura"},
    ))


def test_an_havva_inn_gains_one_more_than_the_green_creatures_everywhere(set_pool):
    """"You gain **X plus 1** life, where X is the number of green creatures
    **on the battlefield**."

    Both halves of the arithmetic are printed and both have somewhere to go
    wrong: the count spans every seat (CR 403.1's shared zone), and the
    constant is added to it rather than being the whole amount."""
    pool = set_pool("HML")
    game, p1, p2 = _w1g2_game(
        [_w1g2_creature("Mine"), _w1g2_creature("Red", colors=("R",))],
        [pool["An-Havva Inn"]],
        theirs=[_w1g2_creature("Theirs")],
    )

    result = game.cast_from_hand(0, "An-Havva Inn")
    game._settle()

    assert result.supported, result.details
    # Two green creatures on the battlefield, plus 1.
    assert p1.life == 23


def test_an_havva_inn_gains_one_with_no_green_creature_at_all(set_pool):
    """The printed constant is paid whatever the count says. A reading that
    made the "plus 1" part of the *count* rather than part of the amount would
    be the same number here and a different one nowhere — which is exactly why
    it is worth pinning the floor."""
    pool = set_pool("HML")
    game, p1, p2 = _w1g2_game([], [pool["An-Havva Inn"]])

    game.cast_from_hand(0, "An-Havva Inn")
    game._settle()

    assert p1.life == 21


def test_bakis_curse_damages_each_creature_by_its_own_aura_count(set_pool):
    """"Baki's Curse deals 2 damage to each creature **for each Aura attached
    to that creature**."

    The multiplier is re-counted per recipient: "that creature" is whichever
    creature is being damaged, not one object the spell chose. Folded into the
    single X every other computed amount rides on, the count taken off the
    first creature would have been dealt to all of them."""
    pool = set_pool("HML")
    bare = _w1g2_creature("Bare", toughness="4")
    one = _w1g2_creature("One Aura", toughness="4")
    two = _w1g2_creature("Two Auras", toughness="9")
    auras = [_w1g2_aura("Aura A"), _w1g2_aura("Aura B"), _w1g2_aura("Aura C")]
    game, p1, p2 = _w1g2_game(
        [bare, one, two, *auras], [pool["Baki's Curse"]],
    )
    attach_aura(auras[0], one)
    attach_aura(auras[1], two)
    attach_aura(auras[2], two)

    result = game.cast_from_hand(0, "Baki's Curse")
    game._settle()

    assert result.supported, result.details
    assert (bare.damage_marked, one.damage_marked, two.damage_marked) == (0, 2, 4)


def test_bakis_curse_deals_nothing_to_an_unenchanted_creature(set_pool):
    """CR 120.8: a source that *would* deal 0 damage does not deal damage at
    all. A creature with no Aura on it is not dealt 0 by Baki's Curse, it is
    not dealt to — so nothing that triggers on damage triggers, and no shield
    is spent."""
    pool = set_pool("HML")
    bare = _w1g2_creature("Bare", toughness="4")
    game, p1, p2 = _w1g2_game([bare], [pool["Baki's Curse"]])

    game.cast_from_hand(0, "Baki's Curse")
    game._settle()

    assert bare.damage_marked == 0
    assert not bare.metadata.get("was_dealt_damage_this_turn")


def test_bakis_curse_counts_an_opponents_aura_on_your_creature(set_pool):
    """What is attached to a permanent is a record kept on that permanent, so
    the count is not a battlefield scan and inherits no controller scope — an
    opponent's Aura on your creature is attached to your creature."""
    pool = set_pool("HML")
    mine = _w1g2_creature("Mine", toughness="4")
    theirs = _w1g2_aura("Their Aura")
    game, p1, p2 = _w1g2_game([mine], [pool["Baki's Curse"]], theirs=[theirs])
    attach_aura(theirs, mine)

    game.cast_from_hand(0, "Baki's Curse")
    game._settle()

    assert mine.damage_marked == 2


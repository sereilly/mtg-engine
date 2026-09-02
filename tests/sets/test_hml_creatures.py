"""Per-card tests for Homelands' creatures.

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

# --- W1G2: counted amounts ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g2_game(*battlefields):
    """A game whose seats hold the given battlefields, in seat order."""
    players = [
        PlayerState(name=f"P{i + 1}", battlefield=list(perms))
        for i, perms in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, players


def _w1g2_creature(name, colors=("G",), subtypes="Human"):
    """A vanilla 1/1 with the given colours and printed creature types."""
    type_line = f"Creature — {subtypes}"
    return Permanent(card=CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    ))


def test_an_havva_constable_counts_green_creatures_on_both_battlefields(set_pool):
    """"An-Havva Constable's **toughness** is equal to 1 plus the number of
    green creatures **on the battlefield**."

    Two halves, and the card is wrong without either. The printed power stands
    (it is a 2/1+*), so only the toughness is defined; and CR 403.1's
    battlefield is one shared zone, so the count spans every seat. An unscoped
    count is taken on the caster's own board by default, which would have made
    the Constable read the opponent's green creatures as nothing at all."""
    pool = set_pool("HML")
    constable = Permanent(card=pool["An-Havva Constable"])
    mine = _w1g2_creature("Mine", colors=("G",))
    theirs = _w1g2_creature("Theirs", colors=("G",))
    red = _w1g2_creature("Red One", colors=("R",))
    game, _ = _w1g2_game([constable, mine, red], [theirs])

    # 1 + (the Constable itself, Mine, Theirs) = 4. The red creature is out.
    assert constable.effective_power == 2
    assert constable.effective_toughness == 4


def test_an_havva_constable_recounts_when_a_green_creature_leaves(set_pool):
    """CR 604.3: a characteristic-defining ability is recomputed continuously,
    so the toughness follows the board rather than being stamped once as the
    creature entered."""
    pool = set_pool("HML")
    constable = Permanent(card=pool["An-Havva Constable"])
    friend = _w1g2_creature("Friend", colors=("G",))
    game, players = _w1g2_game([constable, friend], [])
    assert constable.effective_toughness == 3

    game.remove_from_battlefield(friend)
    game._settle()

    assert constable.effective_toughness == 2


def test_aysen_crusader_counts_two_creature_types_as_a_union(set_pool):
    """"Aysen Crusader's power and toughness are each equal to 2 plus the
    number of **Soldiers and Warriors you control**."

    "And" between two creature types is the *union* — a Soldier is in the set
    and a Warrior is in the set — exactly as "artifact and enchantment" has
    been a union of card types since the noun parser was written. Read as a
    conjunction the set would be creatures that are both, which on this card's
    own board is almost always empty."""
    pool = set_pool("HML")
    crusader = Permanent(card=pool["Aysen Crusader"])
    soldier = _w1g2_creature("A Soldier", colors=("W",), subtypes="Human Soldier")
    warrior = _w1g2_creature("A Warrior", colors=("W",), subtypes="Human Warrior")
    both = _w1g2_creature("A Both", colors=("W",), subtypes="Soldier Warrior")
    plain = _w1g2_creature("A Human", colors=("W",), subtypes="Human")
    game, _ = _w1g2_game([crusader, soldier, warrior, both, plain], [])

    # 2 + (Soldier, Warrior, Both) = 5. The bare Human is out, and the one
    # creature carrying both types is counted once.
    assert crusader.effective_power == 5
    assert crusader.effective_toughness == 5


def test_aysen_crusader_does_not_count_an_opponents_soldiers(set_pool):
    """"…you control" is the half An-Havva Constable does not print, and the
    two cards share one count — so the scope has to come out of the noun phrase
    rather than out of a default, or one of them is wrong."""
    pool = set_pool("HML")
    crusader = Permanent(card=pool["Aysen Crusader"])
    theirs = _w1g2_creature("Their Soldier", colors=("W",), subtypes="Soldier")
    game, _ = _w1g2_game([crusader], [theirs])

    assert crusader.effective_power == 2
    assert crusader.effective_toughness == 2


def test_both_an_havva_cards_compile_the_same_count(set_pool):
    """An-Havva Constable's toughness and An-Havva Inn's life gain print the
    same printed count. They reach it through different machinery — a
    characteristic-defining P/T against a where-clause's X — so the guard worth
    having is that the *spec* they produce is identical: two counters would be
    one sentence meaning two numbers, which is the drift ``count_spec`` exists
    to prevent."""
    pool = set_pool("HML")
    creature = compile_card_oracle(pool["An-Havva Constable"])
    sorcery = compile_card_oracle(pool["An-Havva Inn"])

    cda = next(i for i in creature.instructions if i.kind == "dynamic_pt_count")
    gain = next(i for i in sorcery.instructions if i.kind == "target_gains_life")

    counted = dict(cda.payload["count_spec"])
    # The Constable's spec carries the printed "1 plus" as the count's offset;
    # the Inn prints its "plus 1" on the life gain instead, which is where the
    # sentence puts it.
    assert counted.pop("offset") == 1
    assert counted == gain.payload["x_from_count"]
    assert gain.payload["amount"] == {"plus_x": 1}

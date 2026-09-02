"""Per-card tests for Homelands' enchantments.

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


# --- W1G4: filtered statics and block triggers ---

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.keywords import grant_keyword, remove_keyword
from engine.models import CardDefinition, Permanent


def _w1g4_creature(name: str, keywords: tuple[str, ...] = ()) -> CardDefinition:
    """A 2/2 whose whole text is the keywords it is printed with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="\n".join(keywords), colors=(), color_identity=(),
        keywords=tuple(keywords), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "2", "toughness": "2"},
    )


def _w1g4_board(*permanents: Permanent) -> Game:
    """Every permanent on seat 0's battlefield, settled once."""
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(permanents)),
        PlayerState(name="P2"),
    ])
    game._settle()
    return game


def test_serra_aviary_buffs_a_flier_and_leaves_the_ground_alone(set_pool):
    """"Creatures with flying get +1/+1." — CR 613.4c's anthem narrowed by a
    layer-6 question. Both halves in one test, because a filter that was simply
    dropped would pass the positive one on its own."""
    aviary = Permanent(card=set_pool("HML")["Serra Aviary"])
    bird = Permanent(card=_w1g4_creature("Test Bird", ("flying",)))
    bear = Permanent(card=_w1g4_creature("Test Bear"))
    _w1g4_board(aviary, bird, bear)

    assert (bird.effective_power, bird.effective_toughness) == (3, 3)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_serra_aviary_follows_a_creature_into_and_out_of_flying(set_pool):
    """CR 613.5: the set is re-derived on every recompute, so a creature that
    *gains* flying joins the anthem and one it is removed from leaves it — the
    same thing that rule's own worked example says one layer over about a
    creature an effect turned white. Reading ``card.keywords`` instead would
    freeze both answers to the printed face."""
    aviary = Permanent(card=set_pool("HML")["Serra Aviary"])
    bird = Permanent(card=_w1g4_creature("Test Bird", ("flying",)))
    bear = Permanent(card=_w1g4_creature("Test Bear"))
    game = _w1g4_board(aviary, bird, bear)

    grant_keyword(bear, "flying")
    remove_keyword(bird, "flying")
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    assert (bird.effective_power, bird.effective_toughness) == (2, 2)


def test_mammoth_harness_takes_flying_away_and_gives_it_back_on_detach(set_pool):
    """"Enchanted creature loses flying." — CR 613 layer 6, derived from the
    Aura's own text on every recompute. Removal is the contribution ceasing to
    be made, so nothing has to find and undo a stored grant."""
    harness = Permanent(card=set_pool("HML")["Mammoth Harness"])
    host = Permanent(card=_w1g4_creature("Test Bird", ("flying",)))
    game = _w1g4_board(harness, host)

    attach_aura(harness, host)
    game._settle()
    assert not host.has_keyword("flying")

    detach_aura(harness, host)
    game._settle()
    assert host.has_keyword("flying")


def test_mammoth_harness_drops_serra_aviarys_anthem_off_its_host(set_pool):
    """The two cards of this group meeting, which is the layer order asserted
    end to end: the Harness's removal is layer 6 and the Aviary's anthem is
    layer 7c, so the creature stops being a creature with flying *before* the
    anthem asks."""
    aviary = Permanent(card=set_pool("HML")["Serra Aviary"])
    harness = Permanent(card=set_pool("HML")["Mammoth Harness"])
    bird = Permanent(card=_w1g4_creature("Test Bird", ("flying",)))
    game = _w1g4_board(aviary, harness, bird)

    assert (bird.effective_power, bird.effective_toughness) == (3, 3)

    attach_aura(harness, bird)
    game._settle()

    assert (bird.effective_power, bird.effective_toughness) == (2, 2)


def _w1g4_harnessed_block(set_pool, on_the_blocker: bool):
    """A block with Mammoth Harness on one side of it.

    Seat 0 attacks with one creature, seat 1 blocks with one, and the Harness
    is attached to whichever the caller names — so both halves of "blocks **or
    becomes blocked by**" are exercised by one body.
    """
    harness = Permanent(card=set_pool("HML")["Mammoth Harness"])
    attacker = Permanent(card=_w1g4_creature("Test Ogre"))
    blocker = Permanent(card=_w1g4_creature("Test Wall"))
    host = blocker if on_the_blocker else attacker
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[blocker, harness]),
    ])
    attach_aura(harness, host)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning_of_combat
    game.advance_combat_phase()   # declare_attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare_blockers
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    game._settle()
    return attacker, blocker, host


def test_mammoth_harness_gives_first_strike_to_the_creature_its_host_blocked(set_pool):
    """"…the **other** creature gains first strike until end of turn."

    The blocks half. "The other creature" is the far side of the pair the
    trigger bound, which is the same referent "that creature" names on the
    cards that print it that way — never the Harness's own host.
    """
    attacker, blocker, host = _w1g4_harnessed_block(set_pool, on_the_blocker=True)

    assert attacker.has_keyword("first strike")
    assert not blocker.has_keyword("first strike")
    assert host is blocker


def test_mammoth_harness_gives_first_strike_to_the_creature_that_blocked_its_host(set_pool):
    """The becomes-blocked half of the same printed sentence, which is a
    different fire site with the pair's two ends swapped."""
    attacker, blocker, host = _w1g4_harnessed_block(set_pool, on_the_blocker=False)

    assert blocker.has_keyword("first strike")
    assert not attacker.has_keyword("first strike")
    assert host is attacker

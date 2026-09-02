"""Per-card tests for Homelands' instants.

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


# --- W2G2: library search, reveal and tuck ---

from engine import Game as _G2Game, PlayerState as _G2PlayerState
from engine.models import Permanent as _G2Permanent
from engine.oracle import compile_card_oracle as _g2_compile
from engine.targeting import derive_cast_spec as _g2_cast_spec


def _g2_duel(*, interactive=(0,)):
    """A two-seat game with costs off. Seat 0 is interactive by default, so a
    prompt this group arms is *queued* rather than answered by its own default —
    ROADMAP idiom 39: a headless probe cannot tell "nobody was asked" from
    "nobody was there to ask"."""
    p0, p1 = _G2PlayerState(name="A"), _G2PlayerState(name="B")
    game = _G2Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p0, p1


def test_memory_lapse_puts_the_countered_spell_on_top_of_its_library(
    set_pool, catalog_by_name
):
    """"Counter target spell. If that spell is countered this way, put it on
    top of its owner's library **instead of** into that player's graveyard."

    Both halves are asserted, because the failure this replaces is silent: a
    counter whose destination clause was dropped bins the card, which is
    exactly what an ordinary Counterspell does and reads as nothing going wrong.
    """
    game, p0, p1 = _g2_duel()
    p0.hand = [set_pool("HML")["Memory Lapse"]]
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    p1.library = [catalog_by_name["Forest"]]

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert game.cast_from_hand(0, "Memory Lapse", target_stack_index=0).supported
    game.resolve_stack()

    assert [card.name for card in p1.library] == ["Lightning Bolt", "Forest"]
    assert [card.name for card in p1.graveyard] == []


def test_memory_lapse_stops_the_spell_resolving(set_pool, catalog_by_name):
    """CR 701.5a is still a counter — the redirect changes where the card goes
    and not whether the spell did anything. Asserted on a life total, because a
    Bolt that resolved *and* got tucked would pass the destination test above."""
    game, p0, p1 = _g2_duel()
    p0.hand = [set_pool("HML")["Memory Lapse"]]
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    before = p0.life

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert game.cast_from_hand(0, "Memory Lapse", target_stack_index=0).supported
    game.resolve_stack()

    assert p0.life == before


def test_jinx_asks_for_the_land_type_before_changing_anything(
    set_pool, catalog_by_name
):
    """"Target land becomes **the basic land type of your choice** until end of
    turn." CR 609.3 puts the choice inside the resolution, so nothing is
    recorded until the seat answers — the same contract Phantasmal Terrain's
    prompt already had, reached from a spell that has no permanent."""
    game, p0, p1 = _g2_duel()
    forest = _G2Permanent(card=catalog_by_name["Forest"])
    p1.battlefield.append(forest)
    p0.hand = [set_pool("HML")["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert forest.changed_land_types == ()
    assert game.pending_land_type_choice is not None
    assert game.pending_land_type_choice["player_index"] == 0

    assert game.confirm_land_type(0, "island") is True
    assert forest.changed_land_types == ("island",)
    assert forest.basic_land_types == ("island",)


def test_jinx_replaces_the_lands_types_rather_than_adding_one(
    set_pool, catalog_by_name
):
    """CR 305.7: a land that becomes a basic land type **loses** its old ones,
    which is what makes this a type change and not a grant. A Forest that was
    still a Forest would tap for two colours."""
    game, p0, p1 = _g2_duel()
    forest = _G2Permanent(card=catalog_by_name["Forest"])
    p1.battlefield.append(forest)
    p0.hand = [set_pool("HML")["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()
    game.confirm_land_type(0, "swamp")

    assert forest.basic_land_types == ("swamp",)


def test_jinx_wears_off_in_the_cleanup_step(set_pool, catalog_by_name):
    """"…**until end of turn**." The lowering admits that duration only because
    this sweep exists; without it the land would be a Swamp for the rest of the
    game, which is the direction a dropped duration always fails in.

    The record is keyed by a label rather than by a permanent, because Jinx is
    an instant and has none — so what the cleanup step drops is the label's
    prefix, and the reversion is that contribution leaving (CR 611.3b).
    """
    game, p0, p1 = _g2_duel()
    forest = _G2Permanent(card=catalog_by_name["Forest"])
    p1.battlefield.append(forest)
    p0.hand = [set_pool("HML")["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()
    game.confirm_land_type(0, "swamp")
    assert forest.basic_land_types == ("swamp",)

    game.resolve_cleanup_step(0)

    assert forest.changed_land_types == ()
    assert forest.basic_land_types == ("forest",)


def test_two_jinxes_do_not_overwrite_each_other(set_pool, catalog_by_name):
    """The reason the contribution is keyed by a per-resolution label. Both
    copies are one instant with no permanent behind it, so keying on the source
    would give them the same key — and the second would replace the first's
    contribution on a *different* land, reverting it."""
    game, p0, p1 = _g2_duel()
    pool = set_pool("HML")
    one = _G2Permanent(card=catalog_by_name["Forest"])
    two = _G2Permanent(card=catalog_by_name["Mountain"])
    p1.battlefield.extend([one, two])
    p0.hand = [pool["Jinx"], pool["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()
    game.confirm_land_type(0, "swamp")
    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=1)
    game._settle()
    game.confirm_land_type(0, "island")

    assert one.basic_land_types == ("swamp",)
    assert two.basic_land_types == ("island",)


def test_jinx_offers_a_land_to_target(set_pool):
    """The picker's half. ``derive_cast_spec`` answered None while the first
    line did not parse, and None is what the client tests to decide whether to
    ask for a target — so the app could not aim a card it reported supported."""
    card = set_pool("HML")["Jinx"]

    assert _g2_cast_spec(card, _g2_compile(card)) == {"kind": "land"}

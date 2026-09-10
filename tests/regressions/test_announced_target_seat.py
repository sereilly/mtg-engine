"""Regression: an announcement made by ``permanent_id`` keeps its battlefield.

A target named by id is a complete announcement. CR 400.7 makes the id one
object for one stay on the battlefield, and that object knows whose battlefield
it is on — so a caller naming ids has no seat left to supply, and every headless
caller (a test, the AI, ``scripts/run_duel.py``) supplied none.

Downstream, "no seat named" was read as "the opponent". ``StackItem``'s seat was
defaulted to ``1 - caster`` before the object went on the stack, and
``handlers/_common.pick_target_permanent`` scopes its id lookup to exactly that
player — deliberately, so that widening a target's battlefield is never
something a resolver does by itself. Each half is defensible; together they
threw the announcement away and fell through to the scan underneath, which took
whichever permanent it met first.

Nothing crashed and nothing reported unsupported. War Barge, aimed by id at a
creature its own controller had, gave islandwalk to an opposing one and logged
success; Giant Growth cast the same way pumped the wrong creature. **209 shipped
cards did that shape of thing on the activation side** (163 acting on the wrong
permanent, 47 silently doing nothing) and 151 more on the cast side, and no
compiled program moved — so ``oracle_diff`` and every coverage instrument were
blind to all of it. Only running a card could see it.

The seam is ``Game.announced_target_seat``: the seat the ids already name,
asked wherever an announcement's seat is settled. The sweep at the bottom is the
ratchet — it asks the question of the **whole shipped pool** rather than of the
one card that surfaced it, because a defect measured on one anecdote comes back
on a card nobody tested.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.legality import _activation_spec
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _mk_card, _nosick


def _bait() -> list:
    """One permanent of each printed type, so most noun phrases find something.

    Deliberately plain: the sweep is about *which battlefield* an announced id
    resolves against, and a bait card with abilities of its own would put its
    own triggers between the announcement and the answer.
    """
    return [
        _mk_card(name="Bait Creature", type_line="Creature - Human Soldier", power=2, toughness=2),
        _mk_card(name="Bait Artifact", type_line="Artifact"),
        _mk_card(name="Bait Enchantment", type_line="Enchantment"),
        _mk_card(name="Bait Land", type_line="Land"),
        _mk_card(name="Bait Artifact Creature", type_line="Artifact Creature - Golem", power=3, toughness=3),
    ]


def _board(source_card, *, hand=()) -> tuple[Game, Permanent]:
    """A two-seat board with the same bait on both sides.

    The mirror is the whole point: with one seat empty, a scan that ignored the
    announcement would still land on the right permanent for want of anywhere
    else to go, and the test would pass on the broken engine.
    """
    source = _nosick(Permanent(card=source_card))
    p1 = PlayerState(
        name="P1",
        hand=list(hand),
        battlefield=[source] + [_nosick(Permanent(card=c)) for c in _bait()],
        life=20,
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[_nosick(Permanent(card=c)) for c in _bait()],
        life=20,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, source


# ---------------------------------------------------------------------------
# The two anecdotes: one shipped card per side of the stack.
# ---------------------------------------------------------------------------


def test_war_barge_aimed_by_id_at_its_own_side_hits_that_creature(set_pool):
    """"{3}: Target creature gains islandwalk until end of turn."

    The card wave 1 reproduced it on, and the assertion is in two halves on
    purpose. That the named creature gained islandwalk is the fix; that the
    *other* creature did not is the defect — the old engine granted it there
    and reported the ability resolved.
    """
    game, _barge = _board(set_pool("DRK")["War Barge"])
    mine = _nosick(Permanent(card=_mk_creature("Mine")))
    theirs = _nosick(Permanent(card=_mk_creature("Theirs")))
    game._put_permanent_onto_battlefield(0, mine, 0)
    game._put_permanent_onto_battlefield(1, theirs, 1)

    result = game.activate_permanent_ability(
        0, "War Barge", target_permanent_ids=[mine.permanent_id]
    )
    game._settle()

    assert result.supported, result.details
    assert game._has_keyword(mine, "islandwalk"), game.log
    assert not game._has_keyword(theirs, "islandwalk"), game.log


def test_giant_growth_cast_by_id_at_its_own_side_pumps_that_creature(catalog_by_name):
    """The cast half of the same announcement (CR 601.2c).

    The activation path defaulted the seat before the object was built and the
    cast path let it through as None; the two arrived at the same wrong answer
    from opposite directions, which is why the fix is at the stamping rather
    than at either caller.
    """
    mine = _nosick(Permanent(card=_mk_creature("Mine")))
    theirs = _nosick(Permanent(card=_mk_creature("Theirs")))
    p1 = PlayerState(name="P1", hand=[catalog_by_name["Giant Growth"]], battlefield=[mine])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[mine.permanent_id]
    )
    game._settle()

    assert result.supported, result.details
    assert (mine.effective_power, mine.effective_toughness) == (4, 4), game.log
    assert (theirs.effective_power, theirs.effective_toughness) == (1, 1), game.log


def _mk_creature(name: str):
    return _mk_card(name=name, type_line="Creature - Human", power=1, toughness=1)


# ---------------------------------------------------------------------------
# The ratchet: the whole shipped pool, one announcement each.
# ---------------------------------------------------------------------------


def _target_kinds(instruction) -> set:
    """Every instruction kind in *instruction*'s tree.

    Walked rather than read off the top: a targeting step is routinely wrapped
    in ``sequence`` / ``if_then`` / ``may``, and asking the wrapper what it
    targets would drop most of the pool out of the sweep.
    """
    if instruction is None:
        return set()
    found = {instruction.kind}
    for key in ("steps", "then", "else", "effect", "effects", "instructions", "body"):
        value = instruction.payload.get(key)
        if isinstance(value, (list, tuple)):
            for step in value:
                found |= _target_kinds(step)
        elif value is not None and hasattr(value, "kind"):
            found |= _target_kinds(value)
    return found


def _announcements_on_the_activators_own_side():
    """Every shipped activated ability that can legally be aimed at a permanent
    its own activator controls, with the id it would be aimed by.

    The candidate list comes from ``_enumerate_targets`` — the same list the web
    picker is handed and ``activation_target_refusal`` enforces against — so the
    sweep cannot drift from what the engine calls a legal target. That mattered
    here: the announcement gate passed every one of these announcements and the
    *resolver* discarded them, which is why nothing in the suite went red.
    """
    for card in load_catalog():
        try:
            program = compile_card_oracle(card)
        except Exception:  # pragma: no cover - a compile failure is another test's
            continue
        for ability_index, ability in enumerate(usable_activated_abilities(program)):
            instruction = getattr(ability, "instruction", None)
            if instruction is None:
                continue
            game, source = _board(card)
            # Let the turn's own upkeep finish before anything is announced, and
            # then ask whether seat 0 still has the source. Two shapes do not
            # survive an empty board: Gaea's Liege is */* off a Forest count, so
            # with none it is 0/0 and CR 704.5f has binned it, and Infernal
            # Denizen's upkeep hands *itself* to an opponent, which leaves it on
            # a battlefield but not on the activator's. Left to be discovered
            # during the activation, each raises "Permanent not found" from
            # inside the very call this sweep is measuring.
            game._settle()
            if game.controller_index_of(source) != 0:
                continue
            spec, _ = _activation_spec([ability])
            if spec.get("kind") in (None, "none", "modal", "hand_card"):
                continue
            # The same four flags ``legality.activation_target_refusal`` returns
            # None for. A cost payment (Diamond Valley's sacrificed creature), a
            # discarded card and a chosen *source* (Jade Monolith) are CR 601.2b
            # choices, not CR 601.2c targets — the enumeration offers them all
            # the same way, and a sweep that read them as targets would announce
            # a permanent the cost then eats and call the missing seat a defect.
            # Twenty-one shipped cards said exactly that until this line existed,
            # which is the census-with-fewer-arguments shape in miniature.
            if any(
                spec.get(flag) for flag in
                ("sacrifice_cost", "discard_cost", "also_stack", "requires_source")
            ):
                continue
            try:
                valid = game._enumerate_targets(
                    0, card, spec, for_cast=False,
                    ability_instruction=instruction,
                    source_permanent=source, ability_source=source,
                )
            except Exception:  # pragma: no cover - enumeration is another test's
                continue
            own = [
                entry for entry in valid
                if entry.get("kind") == "permanent" and entry.get("seat") == 0
                and game.permanent_at(0, entry["index"]) is not source
            ]
            if not own:
                continue
            chosen = game.permanent_at(0, own[0]["index"])
            yield card, ability_index, game, chosen


def test_every_shipped_activation_keeps_the_battlefield_its_id_named():
    """Announced by id and by nothing else, on the activator's own side.

    Asserted on the **announcement** rather than on each card's effect: what
    every one of these resolutions reads is ``StackItem.target_player_index``,
    and a card-by-card check of 396 different effects would be 396 chances to
    write the assertion the way the code already behaves.
    """
    wrong, measured = [], 0
    for card, ability_index, game, chosen in _announcements_on_the_activators_own_side():
        # ``queue_permanent_ability``, not ``activate_permanent_ability``: the
        # latter settles the stack before it returns, so the object this sweep
        # is about is gone by the time it could be looked at. Asked of the wrong
        # one, the sweep found nothing to examine and passed on the *broken*
        # engine — the honesty floor below is here because it did.
        result = game.queue_permanent_ability(
            0, card.name, ability_index=ability_index,
            target_permanent_ids=[chosen.permanent_id],
        )
        if not result.supported or result.details != "queued":
            # Refused for a reason that is not this one — an unpayable cost, a
            # timing gate — or resolved without ever being an object on the
            # stack. Either way there is no announcement here to be wrong about.
            continue
        announced = next(
            (
                item for item in reversed(game.stack)
                if item.target_permanent_id
                and chosen.permanent_id in (
                    item.target_permanent_id
                    if isinstance(item.target_permanent_id, (list, tuple))
                    else [item.target_permanent_id]
                )
            ),
            None,
        )
        if announced is None:
            continue
        measured += 1
        if announced.target_player_index != 0:
            wrong.append(f"{card.name} (ability {ability_index})")
    assert not wrong, (
        f"{len(wrong)} of {measured} shipped activations announced a target on "
        f"their own battlefield and put the opposing seat on the stack: "
        f"{sorted(wrong)[:12]}"
    )
    # "No wrong announcements" over a sweep that examined none is a true
    # statement about nothing — the same honesty check the AI simulator's report
    # carries, for the same reason. The pool has ~340 of these; the floor is set
    # well under that so an ordinary ingest does not move it, and well over zero
    # so a sweep that stops reaching the stack cannot read green.
    assert measured > 250, f"the sweep only examined {measured} announcements"


def test_an_announced_id_that_has_left_still_fizzles():
    """The fix must not turn CR 608.2b into a scan.

    ``pick_target_permanent`` answers None for an id that was recorded and now
    resolves to nothing, and that answer is load-bearing — it is the only shape
    where the fallback scan can be *shown* to be wrong rather than merely
    unsupported. Settling the seat from the ids must leave it exactly as it was,
    which is a thing to assert rather than to believe: with the seat now
    correct, a resolver that had grown a scan here would find the bait creature
    standing beside the departed one and pump that instead.
    """
    game, _source = _board(_mk_card(name="Unused", type_line="Artifact"))
    mine = _nosick(Permanent(card=_mk_creature("Mine")))
    game._put_permanent_onto_battlefield(0, mine, 0)
    game.players[0].hand.append(load_catalog_card("Giant Growth"))

    result = game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[mine.permanent_id]
    )
    assert result.supported, result.details
    game.remove_from_battlefield(mine)
    game._settle()

    survivors = [
        (p.effective_power, p.effective_toughness)
        for p in game.controlled_by(0)
        if p.is_creature
    ]
    assert all(pt != (4, 4) for pt in survivors), game.log


_CATALOG_BY_NAME: dict = {}


def load_catalog_card(name: str):
    """One catalog card by name, loaded once for this module.

    Not the ``catalog_by_name`` fixture: this helper is reached from a test that
    already takes no fixture, and threading one through only to look up a single
    card would put the pool in the signature of every test below it.
    """
    if not _CATALOG_BY_NAME:
        _CATALOG_BY_NAME.update({c.name: c for c in load_catalog()})
    return _CATALOG_BY_NAME[name]

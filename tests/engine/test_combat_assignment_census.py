"""Pool census: no blocked attacker's combat damage goes nowhere, and every
assignment the engine itself would make stays legal.

The defect was not on any card. A creature with three power, blocked by two,
could be announced as assigning one and none (CR 510.1c says "its combat
damage … divided as its controller chooses among them" — the shares, not the
total), and the engine dealt one. No compiled program moved when that was
fixed, so ``oracle_diff`` and every coverage instrument read the fix as
nothing; and the fix is a *refusal*, which is the kind of change that breaks
the paths beside it — a trampler's remainder, a deathtouch creature's one
point, a creature that assigns none, the defending player's division under
banding, the default every seat that is not asked is given.

So the population is every way the pool can make a blocked attacker assign
**differently**: each creature card is classed by the things that change the
arithmetic (trample, deathtouch, first strike, double strike, banding, "as
though it weren't blocked", and whether its power is zero), a few of each
class attack for real through the engine's own combat steps into each of the
blocking arrangements below, and three things are held:

* **conservation** — under the engine's default assignment, the damage that
  arrives (marked on blockers, lost by the defending player) is exactly what
  the attacker assigns. Nothing vanishes and nothing is invented;
* **the default is legal** — the engine never refuses its own assignment;
* **the refusal** — the same attacker announcing one point less than it
  assigns is refused with nothing dealt, unless trample makes the remainder
  somebody's (CR 702.19b), in which case it is dealt to them.

Each test carries a floor on what it examined, because a sweep that reaches
nothing passes.

Measured backwards on the tree before the fix (exported and run there, this
file unchanged): of 139 announcements one point short, 37 were tramplers'
and of the 102 that were not, **58 were accepted** — one point of combat
damage gone, a Benalish Hero assigning none of its one — and 44 refused, which
were exactly the two paths that already asked for the whole: the defending
player's division under a banding blocker, and a declined "as though it
weren't blocked". Here: 0 accepted, 102 refused. The default was already
conserved, which is why nothing else had noticed.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.combat_assignment import (combat_damage_assigned_by,
                                      may_assign_as_unblocked)
from engine.models import Permanent

from tests.helpers import _mk_creature_card

#: The keywords that change how an attacker's combat damage is assigned or
#: when. Read through the game (CR 613 layer 6), never off the printed line.
KEYWORDS = ("trample", "deathtouch", "first strike", "double strike", "banding")

#: How many cards of each class attack. The classes are what is being covered;
#: three of each is enough to tell a class from one card's quirk.
PER_CLASS = 3

#: Blocking arrangements: name -> the blockers, as (power, toughness, text).
#: Low toughness so a trampler has something to trample over; a wall it cannot
#: kill; a creature with banding, which moves the assignment to the defender
#: (CR 702.22j); a first striker, which makes two combat damage steps.
ARRANGEMENTS = {
    "one small": [(0, 1, "")],
    "one wall": [(0, 40, "")],
    "two small": [(0, 1, ""), (0, 1, "")],
    "small and wall": [(0, 1, ""), (0, 40, "")],
    "bander and small": [(0, 2, "Banding"), (0, 1, "")],
    "one bander": [(0, 2, "Banding")],
    "first striker and small": [(0, 3, "First strike"), (0, 1, "")],
}


@pytest.fixture(scope="module")
def creatures():
    """Every creature card in the shipped pool, one per name.

    A question about a **card** — one permanent put onto a battlefield and
    attacked with — so the pool is walked card by card and nothing here
    compiles one (``tests/engine/test_face_blind_guards.py``). The shipped pool
    is held at fully supported by its own guards, so there is no unsupported
    creature to filter out; one that cannot simply be put onto a battlefield
    is skipped where the sample is drawn."""
    by_name = {}
    for path in manifest_set_paths():
        for card in load_cards(path):
            if "creature" not in (card.type_line or "").lower():
                continue
            by_name.setdefault(card.name, card)
    return by_name


def _attacker_class(game_free_card) -> tuple:
    """What changes this card's assignment arithmetic, as a hashable class."""
    probe = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    perm = Permanent(card=game_free_card)
    probe._put_permanent_onto_battlefield(0, perm, None)
    words = tuple(word for word in KEYWORDS if probe._has_keyword(perm, word))
    return (
        words,
        may_assign_as_unblocked(perm),
        "zero" if perm.effective_power <= 0 else "some",
    )


@pytest.fixture(scope="module")
def sample(creatures):
    """``{class: [cards]}`` — up to :data:`PER_CLASS` of each, by name order so
    the sample is the same on every run."""
    classes: dict[tuple, list] = {}
    for name in sorted(creatures):
        card = creatures[name]
        try:
            key = _attacker_class(card)
        except Exception:  # a card that cannot simply be put onto a battlefield
            continue
        bucket = classes.setdefault(key, [])
        if len(bucket) < PER_CLASS:
            bucket.append(card)
    return classes


def _combat(attacker_card, arrangement):
    """*attacker_card* attacks for seat 0 into the arrangement's blockers, all
    of which block it, through the engine's own steps. Returns
    ``(game, attacker, blockers, life)`` with combat damage **entered and not
    resolved** — ``life`` being the defending player's as the step begins, so
    what an attack trigger took (Hooded Blightfang) is not counted as combat
    damage — or None when this card cannot be put in that position (it cannot
    attack, cannot be blocked this way, or something it does on attacking or
    being blocked changed the board)."""
    me = PlayerState(name="Me")
    opp = PlayerState(name="Opp")
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    me.life = opp.life = 1000
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    attacker.metadata["summoning_sickness_turn"] = -99
    blockers = []
    for number, (power, toughness, text) in enumerate(arrangement):
        blocker = Permanent(card=_mk_creature_card(f"Census Blocker {number}", power, toughness, text))
        game._put_permanent_onto_battlefield(1, blocker, None)
        blockers.append(blocker)
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    if game.current_step != "declare_attackers":
        return None
    slot = game.battlefield_index_of(attacker)
    if slot is None or not game.declare_attackers(0, [slot], defending_player_index=1)[0]:
        return None
    game.advance_combat_phase()
    if game.current_step != "declare_blockers":
        return None
    pairs = {game.battlefield_index_of(blocker): slot for blocker in blockers}
    if None in pairs or not game.declare_blockers(1, pairs)[0]:
        return None
    # Hold the step open so the assignment under test is the one that is dealt:
    # a single ordinary block would otherwise resolve as the step is entered.
    game.interactive_seats = {0, 1}
    game._enter_combat_step("combat_damage")
    game.combat_damage_resolved = False
    game.combat_first_strike_done = False
    game._prune_combat_state()
    if game.stack or game.pending_choices:
        return None
    if not all(game.is_on_battlefield(perm) for perm in (attacker, *blockers)):
        return None
    slot = game.battlefield_index_of(attacker)
    if slot not in game.combat_attackers:
        return None
    if sorted(game._attacker_all_blockers(slot)) != sorted(
        game.battlefield_index_of(blocker) for blocker in blockers
    ):
        return None
    if any(perm.damage_marked for perm in (attacker, *blockers)):
        return None
    return game, attacker, blockers, opp.life


def _arrived(game, blockers, life_before: int) -> int:
    """Combat damage that reached somebody from the attacking side."""
    return sum(blocker.damage_marked for blocker in blockers) + (
        life_before - game.players[1].life
    )


def _cases(sample):
    for key in sorted(sample, key=repr):
        for card in sample[key]:
            for arrangement_name, arrangement in ARRANGEMENTS.items():
                yield key, card, arrangement_name, arrangement


def test_the_sample_reaches_every_way_of_assigning(sample):
    """The floor on the population itself. If a keyword stops being found the
    sweeps below would pass over a pool with nothing in it."""
    classes = set(sample)
    seen_words = {word for words, _offer, _power in classes for word in words}

    assert len(classes) >= 12, sorted(classes, key=repr)
    assert {"trample", "deathtouch", "first strike", "banding"} <= seen_words
    assert any(offer for _words, offer, _power in classes), "no creature with the offer"
    assert any(power == "zero" for _words, _offer, power in classes)
    assert sum(len(cards) for cards in sample.values()) >= 30


def test_the_default_assignment_is_legal_and_loses_nothing(sample):
    """Conservation, over every class and arrangement, for the assignment a
    seat that is not asked is given. Collected in full before it is asserted,
    so a failure names every case rather than the first."""
    examined = 0
    refused, lost = [], []
    for key, card, arrangement_name, arrangement in _cases(sample):
        built = _combat(card, arrangement)
        if built is None:
            continue
        game, attacker, blockers, life_before = built
        steps = 0
        expected = 0
        while not game.combat_damage_resolved and steps < 2:
            steps += 1
            first_step = game._first_strike_pass_pending() and not game.combat_first_strike_done
            strikes = game._strikes_in_pass(
                attacker, first_step, game._first_strike_pass_pending()
            )
            slot = game.battlefield_index_of(attacker)
            if strikes and slot is not None and slot in game.combat_attackers:
                # CR 510.1c: a blocked creature with nothing blocking it any
                # more assigns no combat damage, unless trample or the offer
                # sends it on (CR 702.19d; the default takes the offer).
                still_blocked_by = game._attacker_all_blockers(slot)
                goes_on = (
                    game._has_keyword(attacker, "trample")
                    or game.unblocked_assignment_chooser(slot) == 0
                )
                if still_blocked_by or goes_on:
                    expected += combat_damage_assigned_by(attacker)
            ok, why = game.resolve_combat_damage(0)
            if not ok:
                refused.append((card.name, arrangement_name, why))
                break
            if game.resume_stack or game.pending_choices:
                break  # a damage event stopped to ask (CR 616.1e); not this census
        else:
            examined += 1
            arrived = _arrived(game, blockers, life_before)
            if arrived != expected:
                lost.append((card.name, arrangement_name, expected, arrived))
            continue
        if game.combat_damage_resolved:
            examined += 1

    assert examined >= 150, f"only {examined} combats were examined"
    assert not refused, f"the engine refused its own default: {refused[:10]} ({len(refused)})"
    assert not lost, (
        "combat damage assigned and not dealt, or dealt and not assigned "
        f"(card, arrangement, assigned, arrived): {lost[:10]} ({len(lost)})"
    )


def test_one_point_short_is_refused_unless_trample_owns_the_remainder(sample):
    """The refusal, over the same population. The attacker announces a
    division among its blockers that is **one point less** than it assigns
    (all on the first blocker). For every attacker without trample that is
    two things at once — some of its damage nowhere — and is refused with
    nothing dealt. A trampler's remainder is the player's (CR 702.19b) when
    the blocker it shorted had lethal damage, and is refused when it had not.

    Where the defending player assigns (a creature with banding blocking,
    CR 702.22j) the same division is announced by *them* and held to the same
    check."""
    refused = accepted_short = examined = trampled = 0
    wrongly_accepted, wrongly_dealt = [], []
    for key, card, arrangement_name, arrangement in _cases(sample):
        words, offered, power_class = key
        if power_class == "zero":
            continue
        built = _combat(card, arrangement)
        if built is None:
            continue
        game, attacker, blockers, life_before = built
        if game._first_strike_pass_pending() and not game._participates_in_first_strike(attacker):
            # It does not assign in the step being resolved (CR 510.4), so
            # nothing it announces there is examined.
            continue
        slot = game.battlefield_index_of(attacker)
        assigns = combat_damage_assigned_by(attacker)
        if assigns <= 0:
            continue
        first = game.battlefield_index_of(blockers[0])
        short = {game.battlefield_index_of(blocker): 0 for blocker in blockers}
        short[first] = assigns - 1
        # (A name the tree before this round also had, so the census can be
        # run there unchanged.)
        defender_assigns = game._defender_assigns_attacker_damage(slot)
        if defender_assigns:
            ok, why = game.assign_banding_combat_damage(1, {slot: short})
            if ok:
                ok, why = game.resolve_combat_damage(0)
        else:
            ok, why = game.resolve_combat_damage(0, attacker_damage={slot: short})
        examined += 1
        has_trample = "trample" in words
        if has_trample:
            trampled += 1
            lethal = max(0, blockers[0].effective_toughness)
            if "deathtouch" in words and lethal > 0:
                lethal = 1
            others_lethal = all(b.effective_toughness <= 0 for b in blockers[1:])
            legal = assigns - 1 >= lethal and others_lethal
            if ok != legal:
                wrongly_accepted.append((card.name, arrangement_name, "trample", ok, why))
            continue
        if ok:
            accepted_short += 1
            wrongly_accepted.append((card.name, arrangement_name, assigns, why))
            continue
        refused += 1
        if _arrived(game, blockers, life_before) != 0 or attacker.damage_marked != 0:
            wrongly_dealt.append((card.name, arrangement_name))

    assert examined >= 100, f"only {examined} under-assignments were announced"
    assert trampled >= 5, "no trampler was examined"
    assert refused >= 80, f"only {refused} refusals were examined"
    assert not wrongly_accepted, (
        f"{accepted_short} of {examined} under-assignments were accepted: "
        f"{wrongly_accepted[:10]}"
    )
    assert not wrongly_dealt, f"a refused assignment dealt damage: {wrongly_dealt[:10]}"

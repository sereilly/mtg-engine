"""CR 508.1d's maximisation for attacks, judged against a brute force.

"If the number of requirements that are being obeyed is fewer than the maximum
possible number of requirements that could be obeyed without disobeying any
restrictions, the declaration of attackers is illegal. If a creature can't
attack unless a player pays a cost, that player is not required to pay that
cost." (CR 508.1d.)

Every shipped permanent whose text prints an attack requirement, an attack
restriction, a cap on attackers or a cost to attack is put on a small board
beside two plain creatures — one of them under a requirement of its own when
the card prints none — with and without Dueling Grounds' cap, on each side of
the table it could be printed for, and with a planeswalker to attack beside the
defending player. **Every** declaration that board allows (each creature home,
at the player, or at the planeswalker) is then made through
``Game.declare_attackers`` and the engine's verdict compared with one computed
here by enumeration:

* a declaration is *restriction-legal* when each attacker passes the
  per-creature predicate (``can_attack``) for what it attacks and the set
  passes ``attack_declaration_refusal`` — the engine's own predicates, because
  the subject here is the maximisation over them, not them;
* it is *cost-free* when no attacker owes a cost to attack what it attacks;
* the most a declaration can obey is the maximum, over every declaration that
  is both, of the requirements it obeys — an unconditional one when its
  creature attacks, a conditional one ("if a creature you control attacks,
  this creature also attacks if able", CR 508.1d's "attacks if some condition
  is met") when its creature attacks or its condition does not hold;
* a declaration is legal when it is restriction-legal, its costs can be paid,
  and it obeys at least that many.

A requirement is counted only on a creature able to obey it — untapped and
able to attack something without paying (CR 508.1a, and the cost sentence
above): a requirement on a creature that is not able imposes nothing, which is
what Juggernaut's ruling (2022-12-08) says of both.

The requirement half of the judge reads the per-creature predicates the engine
has always had (``_must_attack_if_able``, ``_must_attack_beside``), so it runs
on the tree before the maximisation existed — where it fails: under Dueling
Grounds a plain creature attacking alone beside an "attacks each combat if
able" creature was accepted (CR 508.1d's own example), and Juggernaut under
Propaganda was compelled to attack and pay.
"""

from __future__ import annotations

import itertools

import pytest

from engine import Game, PlayerState
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.combat_restrictions import declaration_tap_costs
from engine.faces import compilation_units
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.turn_state import MUST_ATTACK_ON_SEAT_TURN_KEY

from tests.helpers import _mk_creature_card, _nosick


_EAGER_TEXT = "This creature attacks each combat if able."

#: The printed fragments that make a permanent's text an attack requirement, a
#: restriction, a cap or a cost. Broad on purpose: a card selected here that
#: turns out to say something else is judged like any other and costs only
#: time, while a card missed is a hole nobody sees.
_FRAGMENTS = ("if able", "can't attack", "no more than", "attack unless",
              "attack you unless", "attack or block unless")


def _census_cards():
    found = {}
    for card in compilation_units(load_catalog()):
        text = (card.oracle_text or "").lower()
        if "attack" not in text:
            continue
        if not any(fragment in text for fragment in _FRAGMENTS):
            continue
        type_line = (card.type_line or "").lower()
        if "instant" in type_line or "sorcery" in type_line:
            continue
        found.setdefault(card.name, card)
    return [found[name] for name in sorted(found)]


_CATALOG = {card.name: card for card in load_catalog()}
_CARDS = _census_cards()


def _placements(card):
    """Where *card* goes: (seat, attached_to) pairs. A creature attacks; an
    Aura goes on one of the attacker's plain creatures; anything else sits on
    each side in turn, because "can't attack **you**" and "creatures you
    control" are about whose permanent it is."""
    type_line = (card.type_line or "").lower()
    if "creature" in type_line:
        return [(0, None)]
    if "aura" in type_line:
        return [(0, "V"), (1, "V")]
    return [(0, None), (1, None)]


def _prints_a_requirement(card) -> bool:
    return "if able" in (card.oracle_text or "").lower()


def _board(card, seat, attached, *, capped, walker, mark=None):
    """The census board, in the declare attackers step on seat 0's turn.

    *card* None is a **channel** board: no permanent prints the requirement,
    and *mark* puts it on the plain creature the way a resolved spell or
    ability does — "eot" is the one-turn mark (Boiling Blood, Siren's Call,
    Norritt, Bullwhip, Kookus), "seat_turn" the stamp for a later turn
    (Oracle en-Vec). "eot_twice" and "seat_turn_twice" put two effects' marks
    on the plain creature and one on the other: CR 508.1d counts three
    requirements, so under a cap the creature carrying two is the one that
    attacks (:data:`_MARK_WEIGHTS`)."""
    p0 = PlayerState(name="P0")
    p1 = PlayerState(name="P1")
    first = (
        _mk_creature_card("Plain W", 2, 2)
        if card is None or _prints_a_requirement(card)
        else _mk_creature_card("Eager E", 2, 2, _EAGER_TEXT)
    )
    p0.battlefield.append(_nosick(Permanent(card=first)))
    vanilla = _nosick(Permanent(card=_mk_creature_card("Plain V", 3, 3)))
    p0.battlefield.append(vanilla)
    for land in ("Island", "Island", "Forest", "Mountain"):
        p0.battlefield.append(Permanent(card=_CATALOG[land]))
    for land in ("Island", "Plains", "Swamp"):
        p1.battlefield.append(Permanent(card=_CATALOG[land]))
    p1.battlefield.append(
        _nosick(Permanent(card=_mk_creature_card("Opposing Bear", 2, 2)))
    )
    if capped:
        p0.battlefield.append(Permanent(card=_CATALOG["Dueling Grounds"]))
    if walker:
        p1.battlefield.append(Permanent(card=_CATALOG["Basri Ket"]))
    subject = None
    if card is not None:
        subject = _nosick(Permanent(card=card))
        owner = p0 if seat == 0 else p1
        owner.battlefield.append(subject)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    if attached == "V":
        attach_aura(subject, vanilla)
    if card is not None and "magnet counter" in (card.oracle_text or "").lower():
        # Magnetic Web's requirement reads magnet counters; give both plain
        # creatures one, so its condition can be met.
        add_counters(p0.battlefield[0], "magnet", 1)
        add_counters(vanilla, "magnet", 1)
    game._sync_control()
    game.start_turn(0)
    for perm in p0.battlefield:
        _nosick(perm)
    if mark == "eot":
        vanilla.metadata["must_attack_until_eot"] = True
    elif mark == "seat_turn":
        vanilla.metadata[MUST_ATTACK_ON_SEAT_TURN_KEY] = {
            "seat": 0, "seat_turn": game.seat_turn_counts.get(0, 0),
        }
    elif mark == "eot_twice":
        vanilla.metadata["must_attack_until_eot"] = 2
        p0.battlefield[0].metadata["must_attack_until_eot"] = 1
    elif mark == "seat_turn_twice":
        stamp = {"seat": 0, "seat_turn": game.seat_turn_counts.get(0, 0)}
        vanilla.metadata[MUST_ATTACK_ON_SEAT_TURN_KEY] = [dict(stamp), dict(stamp)]
        p0.battlefield[0].metadata[MUST_ATTACK_ON_SEAT_TURN_KEY] = [dict(stamp)]
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    if game.current_step != "declare_attackers":
        return None
    return game


def _owes(game, attacker, target) -> bool:
    seat, walker_id = target
    return bool(
        game._attack_mana_costs_of(attacker, None if walker_id is not None else seat)
        or game._attack_costs_of(attacker)
        or declaration_tap_costs(attacker, "attack")
    )


def _payable(game, attackers, seats) -> bool:
    total, plan = game._declaration_mana_plan(0, attackers, seats)
    if total and plan is None:
        return False
    sacrifices = game._declaration_sacrifice_plan(0, attackers)
    if sacrifices is None:
        return False
    return game.declaration_tap_plan(
        0, attackers, "attack",
        unavailable=[*sacrifices, *(plan.tapped if plan else ())],
    ) is not None


#: The requirements the two-mark boards write on each plain creature, by name —
#: the census's own count, never the engine's.
_MARK_WEIGHTS = {"Plain V": 2, "Plain W": 1}


def _judge(game, weights=None):
    """Every declaration on *game*, with the verdict CR 508.1c–d gives it.

    *weights* is how many unconditional requirements a creature carries, by
    name, where the board wrote more than one; any other is one.

    Returns ``(declarations, best, requirement_count)`` where each declaration
    is ``(assignment, legal, restriction_legal_and_payable)`` and an
    assignment maps a battlefield slot to ``(seat, walker_id or None)``.
    """
    mine = list(game.controlled_by(0))
    slots = [s for s, p in enumerate(mine) if p.is_creature and not p.tapped]
    targets = [(1, None)] + [
        (1, w.permanent_id) for w in game.controlled_by(1)
        if w.has_type("planeswalker")
    ]

    def allowed(perm, target):
        return game.can_attack(
            perm, target[0], attacking_planeswalker=target[1] is not None
        )

    able = {
        s for s in slots
        if any(allowed(mine[s], t) and not _owes(game, mine[s], t) for t in targets)
    }
    unconditional = {s for s in able if game._must_attack_if_able(mine[s])}
    conditional = {
        s for s in able
        if game._must_attack_beside(mine[s], [mine[o] for o in slots if o != s])
    }

    def weight(slot: int) -> int:
        return (weights or {}).get(mine[slot].card.name, 1)

    def obeyed(attacking: set[int]) -> int:
        declared = [mine[s] for s in sorted(attacking)]
        return (
            sum(weight(s) for s in unconditional if s in attacking)
            + sum(
                1 for s in conditional
                if s in attacking or not game._must_attack_beside(mine[s], declared)
            )
        )

    rows = []
    for choice in itertools.product([None, *targets], repeat=len(slots)):
        assignment = {slots[i]: t for i, t in enumerate(choice) if t is not None}
        perms = [mine[s] for s in sorted(assignment)]
        defenders = {
            mine[s].permanent_id: (None if t[1] is not None else t[0])
            for s, t in assignment.items()
        }
        restriction_legal = all(
            allowed(mine[s], t) for s, t in assignment.items()
        ) and game.attack_declaration_refusal(perms, defenders=defenders) is None
        cost_free = not any(_owes(game, mine[s], t) for s, t in assignment.items())
        payable = restriction_legal and _payable(
            game, perms,
            [None if assignment[s][1] is not None else assignment[s][0]
             for s in sorted(assignment)],
        )
        rows.append((assignment, restriction_legal, cost_free, payable,
                     obeyed(set(assignment))))
    best = max(ob for _a, legal, free, _p, ob in rows if legal and free)
    return (
        [(a, payable and ob >= best, payable) for a, _r, _f, payable, ob in rows],
        best,
        sum(weight(s) for s in unconditional) + len(conditional),
    )


def _walker_id(game):
    """The defending player's planeswalker on *game* — looked up per game,
    because a board rebuilt after an accepted declaration has new ids."""
    return next(
        (w.permanent_id for w in game.controlled_by(1) if w.has_type("planeswalker")),
        None,
    )


def _declare(game, assignment):
    slots = sorted(assignment)
    walker = _walker_id(game)
    return game.declare_attackers(
        0, slots, defending_player_index=1,
        attacker_planeswalker_ids={
            s: walker for s, t in assignment.items() if t[1] is not None
        } or None,
    )


def _boards():
    for card in _CARDS:
        for seat, attached in _placements(card):
            for capped in (False, True):
                for walker in (False, True):
                    yield card, seat, attached, capped, walker, None
    for mark in ("eot", "seat_turn", "eot_twice", "seat_turn_twice"):
        for capped in (False, True):
            for walker in (False, True):
                yield None, 0, None, capped, walker, mark


def _census():
    """Run the whole census; return (mismatches, tallies)."""
    mismatches = []
    tallies = {"boards": 0, "declarations": 0, "requirement_bit": 0,
               "cost_excused": 0, "conditional": 0, "short_of_total": 0,
               "marks": 0, "counted_marks": 0}
    for card, seat, attached, capped, walker, mark in _boards():
        build = lambda: _board(  # noqa: E731
            card, seat, attached, capped=capped, walker=walker, mark=mark,
        )
        game = build()
        if game is None:
            continue
        rows, best, total = _judge(
            game, _MARK_WEIGHTS if mark and mark.endswith("_twice") else None,
        )
        tallies["boards"] += 1
        if mark is not None:
            tallies["marks"] += 1
        if mark and mark.endswith("_twice") and capped:
            tallies["counted_marks"] += 1
        if any(payable and not legal for _a, legal, payable in rows):
            tallies["requirement_bit"] += 1
        if total and best < total:
            tallies["short_of_total"] += 1
        if any(
            game._must_attack_beside(p, [o for o in game.controlled_by(0) if o is not p])
            for p in game.controlled_by(0) if p.is_creature
        ):
            tallies["conditional"] += 1
        if any(
            game._must_attack_if_able(p) and any(
                _owes(game, p, (1, None)) for _ in (0,)
            )
            for p in game.controlled_by(0) if p.is_creature
        ):
            tallies["cost_excused"] += 1
        for assignment, legal, _payable_ in rows:
            tallies["declarations"] += 1
            ok, why = _declare(game, assignment)
            if ok != legal:
                mismatches.append(
                    f"{card.name if card else 'mark ' + mark} (seat {seat}{', capped' if capped else ''}"
                    f"{', walker' if walker else ''}): "
                    f"{ {s: ('walker' if t[1] else 'player') for s, t in assignment.items()} } "
                    f"engine={'accepted' if ok else 'refused: ' + why} judge="
                    f"{'legal' if legal else 'illegal'}"
                )
            if ok:
                game = build()
    return mismatches, tallies


@pytest.mark.full
@pytest.mark.cr("508.1c", "508.1d")
def test_every_attack_declaration_obeys_the_most_requirements_it_can():
    """The engine accepts exactly the declarations CR 508.1c–d allows, on
    every census board — and the census examined enough to mean it."""
    mismatches, tallies = _census()
    assert not mismatches, (
        f"{len(mismatches)} declaration(s) judged differently:\n"
        + "\n".join(mismatches[:40])
    )
    # Floors: a census that measured nothing reads like one that found nothing.
    # Measured on 2026-11-01: 948 boards, 12,718 declarations, 806 boards on
    # which a requirement refused a declaration the restrictions allowed, 16
    # with a conditional requirement, 16 with a requirement a cost excused, 4
    # where the requirements could not all be obeyed together, 8 mark boards.
    # Round kg3 (leftovers) added 8 two-mark boards, 4 of them capped.
    assert tallies["boards"] >= 900, tallies
    assert tallies["declarations"] >= 12000, tallies
    assert tallies["requirement_bit"] >= 700, tallies
    assert tallies["conditional"] >= 12, tallies
    assert tallies["cost_excused"] >= 12, tallies
    assert tallies["short_of_total"] >= 3, tallies
    assert tallies["marks"] >= 16, tallies
    assert tallies["counted_marks"] >= 4, tallies

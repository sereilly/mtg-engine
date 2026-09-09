"""How much combat damage a creature assigns (CR 510.1).

Ordinarily the answer is its power, and every site in the combat damage step
read ``permanent.effective_power`` to get it. "This creature assigns no combat
damage this turn" (Floral Spuzzem) is the first printed sentence that makes the
answer something else, and it is *not* any of the three mechanisms it resembles:

* not a prevention shield (CR 615) — nothing is prevented, because nothing is
  ever assigned, so no shield counter is spent and no "if damage would be
  dealt" replacement ever sees an event;
* not a P/T change (CR 613 layer 7) — the creature keeps its power for what a
  lord counts, for what "power 3 or greater" matches, and for the noncombat
  damage its own abilities deal;
* not a combat restriction (CR 506) — the creature still attacks, is still
  blocked, and still *receives* combat damage.

So the rule is one function with four callers rather than a flag tested at each
of the four sites the step assigns from — an attacker to its blockers, an
attacker to the player it is attacking, a blocker to the creature it blocks, and
a blocker to one member of a band. A flag read at three of four is the shape
this repo keeps finding: the card works everywhere anyone tested and quietly
does nothing at the fourth.

The mark is per-turn, held on the permanent's metadata and swept with the rest
of the turn's marks by the cleanup step (``engine/mixins/_constants.py``). It
travels with the permanent and dies with it, which CR 400.7 gives for free.
"""

from __future__ import annotations

#: "This creature assigns no combat damage this turn." (Floral Spuzzem.)
ASSIGNS_NO_COMBAT_DAMAGE = "assigns_no_combat_damage_until_eot"

#: "X target blocked creatures assign their combat damage this turn **as
#: though they weren't blocked**." (Outmaneuver.) CR 510.1a's assignment to
#: the blocking creatures replaced, for a turn, by CR 510.1b's assignment to
#: the player being attacked.
#:
#: Named here beside the mark above because both are answers to "how does this
#: creature assign?" and the combat damage step reads them at the same moment —
#: but they are not the same answer and this one is not read by
#: :func:`combat_damage_assigned_by`, because the *amount* is unchanged. What
#: changes is where it goes, which only the step knows.
#:
#: **Its own key beside the "may" one** Garruk, Savage Herald grants
#: (``assign_combat_damage_as_unblocked_until_eot``). The two look identical at
#: the damage step and are not: that one is an offer, and the step answers it
#: yes only where no explicit per-blocker assignment was given — which is how
#: a player declines it. This is a *restriction*, so declining is exactly what
#: must not be possible, and one key for both would make Outmaneuver optional
#: for whoever bothered to assign.
#:
#: Swept with the turn by ``engine/mixins/_constants.py``.
MUST_ASSIGN_AS_UNBLOCKED = "must_assign_combat_damage_as_unblocked_until_eot"

#: The **offer** beside the restriction above: "You may have this creature
#: assign its combat damage as though it weren't blocked", granted for the turn
#: by Garruk, Savage Herald's −7 and printed permanently on Lone Wolf.
#:
#: Named here for this module's stated reason, and it was overdue: the string
#: was spelled out in the handler that writes it, in the step that reads it and
#: in the cleanup sweep that clears it — three copies of a channel, which is the
#: arrangement whose failure mode is a write nothing reads.
#:
#: Swept with the turn by ``engine/mixins/_constants.py``. The printed half is
#: not swept and is not a mark at all: see :func:`may_assign_as_unblocked`.
MAY_ASSIGN_AS_UNBLOCKED = "assign_combat_damage_as_unblocked_until_eot"

#: "Target unblocked attacking creature **becomes blocked**." (Dazzling Beauty;
#: CR 509.1h.) Named here rather than beside the combat maps because the maps
#: record *who blocks whom*, and this is precisely the state CR 509.1h says a
#: creature can be in with no blockers at all — the one an attacker is left in
#: when its blockers leave combat.
#:
#: A mark on the permanent, not an entry in a combat map. The maps are keyed by
#: battlefield slot and have to be renumbered whenever anything leaves; this
#: travels with the permanent and dies with it, which CR 400.7 gives for free.
#:
#: Swept by the **end of combat** step, not by cleanup: a turn may hold a second
#: combat phase (Relentless Assault), and a creature this blocked in the first
#: one is a fresh attacker in the second.
BLOCKED_WITHOUT_BLOCKERS = "blocked_without_blockers_this_combat"


#: "**Rather than the attacking player, you assign the combat damage of each
#: creature attacking you.** You can divide that creature's combat damage as
#: you choose among any of the creatures blocking it." (Defensive Formation.)
#:
#: CR 510.1a names the attacking player as the one who divides a blocked
#: creature's damage among its blockers; this substitutes the defending player,
#: which is the same substitution CR 702.22j makes for a creature blocked by a
#: band. So it is answered at the *same* seam and by the same reader — a second
#: one would be the two-readers failure this module exists to prevent, with the
#: prompt offering a division the damage step then ignored.
#:
#: The second printed sentence needs no code and is not a shortcut: CR 510.1c
#: already lets whoever assigns divide the damage among the blockers however
#: they choose. It says what the substitution *means*, for a player reading the
#: card, and the substitution is the whole of what changes.
#:
#: Text-keyed rather than name-keyed because the sentence is a template: a card
#: printing it about artifacts, or on an artifact instead of an enchantment,
#: is this rule with nothing added.
#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the rule below. Its own, for ``cast_restrictions.OWN_CAST_BAN_CLAIM``'s
#: reason: every other claim in this engine says what a *card* may do, and this
#: one says who makes a decision the rules otherwise give to somebody else.
DEFENDER_ASSIGNS_CLAIM = "defender_assigns"

_DEFENDER_ASSIGNS = (
    "rather than the attacking player, you assign the combat damage of each "
    "creature attacking you"
)


def defender_assigns_line(line: str) -> bool:
    """Whether *line* substitutes CR 510.1a's assigner for the defending player.

    One reader, three callers, the arrangement ``cast_restrictions``' board bans
    have: ``engine/grammar/registries.py`` asks it so the printed line is
    *claimed*, ``engine/oracle.py``'s support gate asks it so the card is
    admitted on the strength of a rule that exists, and
    ``phases/combat_damage_step`` asks it so the line is *enforced*. A
    substitution claimed and not enforced is an enchantment that reports
    supported while the attacking player goes on assigning.

    The line is matched whole, the sentence after it included where the card
    prints one: the second sentence restates CR 510.1c and adds nothing, so it
    is stripped by the caller rather than read here.
    """
    return line.strip().lower().rstrip(".") == _DEFENDER_ASSIGNS


def defender_assigns_all_damage(game, defender_index: int) -> bool:
    """Whether *defender_index* assigns the damage of every creature attacking
    them (Defensive Formation).

    Their **own** battlefield only, which is the whole of what "you" means here
    (CR 109.5): an opponent's copy of the card moves nobody else's assignment.

    ``effective_card`` rather than the printed face, for the reason every other
    text-keyed board scan in this engine reads it: what a permanent says is what
    layer 1 and layer 3 have made of it (CR 707.2, CR 612.1).
    """
    if not (0 <= defender_index < len(game.players)):
        return False
    for seat, permanent in game.permanents_with_controller():
        if seat != defender_index:
            continue
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            for sentence in raw_line.split(". "):
                if defender_assigns_line(sentence):
                    return True
    return False


def may_assign_as_unblocked(permanent) -> bool:
    """Whether *permanent*'s controller may send its combat damage past its
    blockers (CR 510.1b instead of CR 510.1a).

    **Two channels, one question.** Garruk, Savage Herald's −7 grants the
    ability for a turn and writes :data:`MAY_ASSIGN_AS_UNBLOCKED`; Lone Wolf
    prints it, and a printed static is not a mark — nothing writes it and
    nothing sweeps it, it is simply true while the creature is on the
    battlefield. The damage step asks *this*, so a card printing the sentence
    and a creature granted it cannot be answered differently.

    Read off ``effective_card``, like every other text-derived combat read: a
    Clone of Lone Wolf has the offer too (CR 707.2).

    This is only the **offer**. Whether it is taken is the damage step's own
    reading — an explicit per-blocker assignment is how a player declines — and
    that decision is deliberately not made here: the restriction
    (:data:`MUST_ASSIGN_AS_UNBLOCKED`, Outmaneuver) gives its controller nothing
    to decline, and one function answering both would make it optional for
    whoever bothered to assign.
    """
    from .oracle import compile_card_oracle

    if permanent.metadata.get(MAY_ASSIGN_AS_UNBLOCKED):
        return True
    return any(
        instruction.kind == "may_assign_as_unblocked"
        for instruction in compile_card_oracle(
            permanent.effective_card
        ).instructions
    )


def combat_damage_assigned_by(permanent) -> int:
    """How much combat damage *permanent* assigns this step (CR 510.1a).

    Its power, or zero while it is marked as assigning none. Never negative:
    CR 510.1a assigns damage equal to power and a creature with negative power
    assigns none, which every caller already relied on by testing ``<= 0``.
    """
    if permanent.metadata.get(ASSIGNS_NO_COMBAT_DAMAGE):
        return 0
    return max(0, permanent.effective_power)


__all__ = [
    "ASSIGNS_NO_COMBAT_DAMAGE",
    "MAY_ASSIGN_AS_UNBLOCKED",
    "combat_damage_assigned_by",
    "may_assign_as_unblocked",
]

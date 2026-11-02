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
#: though they weren't blocked**." (Outmaneuver.) CR 510.1c's assignment to
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

#: The offer **taken by the defending player**, for one combat damage step.
#:
#: Where the defending player assigns an attacker's combat damage (CR 702.22j:
#: a creature with banding is blocking it; or a permanent that says "rather
#: than the attacking player, you assign…") the offer above is theirs to take
#: — "If blocked by a creature with banding, the defending player decides
#: whether or not the damage is assigned 'as though it weren't blocked'."
#: (Thorn Elemental / Lone Wolf / Rhox / Pride of Lions, 2018-04-27.) And for
#: the printed substitution: "Damage assignment choices from Trample and other
#: things which allow alternative damage assignments for attacking creatures
#: are all made by you." (Defensive Formation, 2004-10-04.)
#:
#: The defending player announces before the active player's assignment is
#: resolved (``Game.assign_banding_combat_damage``), so their answer has to be
#: *held* until the step deals its damage — the one place in this module where
#: an answer is stored rather than announced with the assignment it belongs to.
#: It is held the way their division is (``Game.combat_banding_damage``): for
#: the combat, as what that player last said about this creature.
#:
#: A mark on the attacker rather than an entry in a combat map, for
#: :data:`BLOCKED_WITHOUT_BLOCKERS`'s reason: the maps are keyed by battlefield
#: slot and have to be renumbered whenever anything leaves, and this travels
#: with the permanent. Swept with that mark by the end of combat step.
DEFENDER_ASSIGNS_AS_UNBLOCKED = "defender_assigns_as_unblocked_this_combat"

#: Whether the defending player has **announced** how this attacker assigns
#: its combat damage in the combat damage step in progress — either answer,
#: the division or the mark above.
#:
#: Separate from the answer because the two have different lifetimes. CR 510.4
#: gives a combat with first or double strike two combat damage steps, and
#: CR 510.1 is an announcement made in each: a double striker blocked by a
#: Benalish Hero is divided by the defending player twice, over a board the
#: first strike changed. So the *asking* is per step — the step that deals an
#: attacker's damage clears this, and a person is asked again — while the
#: *answer* stays where it was, as the default for a seat nobody is asking (a
#: headless combat replays the division it was given, where it is still one).
#:
#: An attacker that has not struck yet keeps the mark across the first step:
#: its announcement has not been used, and asking for it twice would be asking
#: about one assignment two times.
DEFENDER_ANNOUNCED_THIS_STEP = "defender_announced_assignment_this_step"

#: The tail of the log line the damage step writes for each blocked attacker
#: whose combat damage went past its blockers — the offer taken, or Outmaneuver's
#: restriction — as "<name> assigns its combat damage as though it weren't
#: blocked". Named because it has a second reader: the client's combat damage
#: animation rebuilds the strikes from the previous state and the new log
#: lines, the way it already reads "Resolved combat damage", and matches this
#: tail to know the blow landed on the player. A log line is the only thing
#: both seats' clients and an AI's attack all pass through.
AS_THOUGH_UNBLOCKED_LOG = "as though it weren't blocked"

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
#: CR 510.1c names the attacking player as the one who divides a blocked
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
#: the rule below. Its own, for ``cast_bans.OWN_CAST_BAN_CLAIM``'s
#: reason: every other claim in this engine says what a *card* may do, and this
#: one says who makes a decision the rules otherwise give to somebody else.
DEFENDER_ASSIGNS_CLAIM = "defender_assigns"

_DEFENDER_ASSIGNS = (
    "rather than the attacking player, you assign the combat damage of each "
    "creature attacking you"
)


def defender_assigns_line(line: str) -> bool:
    """Whether *line* substitutes CR 510.1c's assigner for the defending player.

    One reader, three callers, the arrangement ``cast_bans``' board bans
    have: ``engine/grammar/registries.py`` asks it so the printed line is
    *claimed*, ``engine/derived_static_claims.py``'s support gate asks it so the card is
    admitted on the strength of a rule that exists, and
    ``phases/combat_damage_assignment`` asks it so the line is *enforced*. A
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
    blockers (CR 510.1b instead of CR 510.1c).

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

    Nor is it *whose* offer. That needs the combat maps — a creature has to be
    blocked for the sentence to say anything, and where the defending player
    assigns its damage (CR 702.22j) the choice is theirs — so it is
    ``Game.unblocked_assignment_chooser``, on the damage step, which asks this
    and then says which seat answers. Taking the offer is announced to the
    step by the creature's id (``resolve_combat_damage(as_though_unblocked=)``),
    so a seat that is asked can say yes as plainly as it can say no.
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


#: "You may assign this creature's combat damage divided as you choose among
#: defending player and/or any number of creatures they control." (Butcher
#: Orgg.) The static record the line compiles to, read here and nowhere else.
DIVIDES_AMONG_DEFENDERS = "may_divide_combat_damage_among_defenders"

#: The key a division names **the defending player's** share under; every
#: other key is the ``permanent_id`` of a creature that player controls. One
#: string rather than a seat number, because the seat is not the announcer's to
#: choose: it is CR 506.2's defending player for this attacker, read off the
#: combat maps.
DEFENDING_PLAYER_SHARE = "player"

#: The tail of the log line the damage step writes for a creature whose
#: combat damage was divided this way, for :data:`AS_THOUGH_UNBLOCKED_LOG`'s
#: two readers: a table owed the reason creatures nobody declared as blockers
#: are taking combat damage, and the client's damage animation.
DIVIDED_AMONG_DEFENDERS_LOG = (
    "divides its combat damage among defending player and the creatures "
    "they control"
)


def may_divide_among_defenders(permanent) -> bool:
    """Whether *permanent* prints Butcher Orgg's offer (read off its effective
    card, so a Clone of the Orgg has it too, CR 707.2)."""
    from .oracle import compile_card_oracle

    return any(
        instruction.kind == DIVIDES_AMONG_DEFENDERS
        for instruction in compile_card_oracle(permanent.effective_card).instructions
    )


def division_shares(division) -> list[tuple[object, int]]:
    """*division* as ``(recipient key, amount)`` pairs: the defending player's
    share under :data:`DEFENDING_PLAYER_SHARE`, every other key a permanent id
    as an int (a wire announcement arrives with string keys). An unreadable key
    is kept as it came, for the gate to refuse."""
    shares: list[tuple[object, int]] = []
    for key, amount in (division or {}).items():
        if key == DEFENDING_PLAYER_SHARE:
            shares.append((DEFENDING_PLAYER_SHARE, int(amount)))
            continue
        try:
            shares.append((int(key), int(amount)))
        except (TypeError, ValueError):
            shares.append((key, int(amount)))
    return shares


def divided_among_defenders_refusal(game, attacker_idx: int, attacker, division) -> str | None:
    """CR 510.1e's check of a Butcher Orgg announcement, or None when legal.

    The rulings (2004-10-04) are the rule's whole shape: "You can use the
    ability to divide damage even if it is not blocked"; "If it is blocked but
    then all of its blockers are removed before combat damage is assigned, then
    it won't be able to deal combat damage and you won't be able to use its
    ability"; "you must choose at least one creature or the defending player,
    and can't choose more total creatures and players than the amount of damage
    being assigned (minimum 1 point per player or creature)". So: the offer is
    the creature's and the active player's to take (CR 510.1's assigner), the
    shares are each at least 1 and add up to all of its combat damage, and each
    creature named is one the defending player controls.
    """
    name = attacker.card.name
    if not may_divide_among_defenders(attacker):
        return (
            f"{name} can't divide its combat damage among defending player and "
            "the creatures they control"
        )
    if game.combat_damage_assigner(attacker_idx) != game.active_player_index:
        return f"the defending player assigns {name}'s combat damage"
    if attacker.blocked and not game._attacker_all_blockers(attacker_idx):
        return (
            f"{name} is blocked with nothing left blocking it, so it assigns no "
            "combat damage to divide"
        )
    defending_index = game.combat_attackers.get(attacker_idx)
    shares = division_shares(division)
    if not shares:
        return f"{name}'s division names no recipient"
    if len({key for key, _amount in shares}) != len(shares):
        return f"{name}'s division names one recipient twice"
    if any(amount < 1 for _key, amount in shares):
        return f"each recipient of {name}'s division takes at least 1 damage"
    assignable = combat_damage_assigned_by(attacker)
    if sum(amount for _key, amount in shares) != assignable:
        return f"{name} divides all {assignable} of its combat damage"
    for key, _amount in shares:
        if key == DEFENDING_PLAYER_SHARE:
            continue
        creature = game.permanent_by_id(key) if isinstance(key, int) else None
        if (
            creature is None
            or not creature.is_creature
            or game.controller_index_of(creature) != defending_index
        ):
            return (
                f"{name} divides its damage among defending player and the "
                "creatures they control"
            )
    return None


def divided_announcement_refusal(
    game, attacker_damage: dict, unblocked_ids, divided_among: dict | None,
) -> str | None:
    """The announcement-level half of the gate: every id the active player's
    divisions name is one of this combat's attackers, and none of them is also
    assigned among its blockers or sent "as though it weren't blocked" — one
    creature's combat damage is assigned one way (CR 510.1)."""
    active = game.active_player_index
    for permanent_id in sorted(int(pid) for pid in (divided_among or {})):
        attacker = game.permanent_by_id(permanent_id)
        attacker_idx = (
            game.battlefield_index_of(attacker)
            if attacker is not None and game.controls(active, attacker)
            else None
        )
        if attacker_idx is None or attacker_idx not in game.combat_attackers:
            return "that creature is not attacking"
        if permanent_id in unblocked_ids or any(
            int(v) > 0 for v in (attacker_damage.get(attacker_idx) or {}).values()
        ):
            return (
                f"{attacker.card.name}'s combat damage is divided one way: "
                "among defending player and their creatures, or as it would "
                "otherwise be assigned"
            )
    return None


def still_legal_divisions(game, divided: dict) -> dict:
    """*divided* on the board a first-strike step left (CR 510.4: the second
    step is assigned afresh): each division still legal carried over, and one
    the first strike made illegal — a creature it named is gone — dropped, so
    the offer is declined for this step rather than the whole step refused."""
    active = game.active_player_index
    kept: dict = {}
    for permanent_id, split in divided.items():
        attacker = game.permanent_by_id(permanent_id)
        attacker_idx = (
            game.battlefield_index_of(attacker)
            if attacker is not None and game.controls(active, attacker)
            else None
        )
        if attacker_idx is None or attacker_idx not in game.combat_attackers:
            continue
        if divided_among_defenders_refusal(game, attacker_idx, attacker, split) is None:
            kept[permanent_id] = split
    return kept


def divided_among_defenders_events(game, attacker_idx: int, attacker, division):
    """The two halves of a legal division as the damage step records them —
    ``(to_creatures, to_player)`` in the shapes of its ``to_blockers`` and
    ``to_players`` events. The creatures need not be blocking (they are
    addressed by their slot on the defending player's battlefield, as a
    blocker is), and the player's share goes to the defending **player** even
    when the creature attacks a planeswalker: the card names the player."""
    defending_index = game.combat_attackers[attacker_idx]
    to_creatures: list[tuple[int, int, int, int]] = []
    to_player: list[tuple[int, int, object, None]] = []
    for key, amount in division_shares(division):
        if key == DEFENDING_PLAYER_SHARE:
            to_player.append((defending_index, amount, attacker, None))
            continue
        slot = game.battlefield_index_of(game.permanent_by_id(key))
        to_creatures.append((defending_index, slot, amount, attacker_idx))
    return to_creatures, to_player


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
    "AS_THOUGH_UNBLOCKED_LOG",
    "ASSIGNS_NO_COMBAT_DAMAGE",
    "DEFENDER_ANNOUNCED_THIS_STEP",
    "DEFENDER_ASSIGNS_AS_UNBLOCKED",
    "DEFENDING_PLAYER_SHARE",
    "DIVIDED_AMONG_DEFENDERS_LOG",
    "DIVIDES_AMONG_DEFENDERS",
    "MAY_ASSIGN_AS_UNBLOCKED",
    "combat_damage_assigned_by",
    "divided_among_defenders_events",
    "divided_among_defenders_refusal",
    "divided_announcement_refusal",
    "division_shares",
    "may_assign_as_unblocked",
    "may_divide_among_defenders",
    "still_legal_divisions",
]

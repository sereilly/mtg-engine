"""Combat marks recorded on a permanent, and read by the combat steps.

An "as though" effect applies only to the stated effect, so a permission is a
flag the combat step reads rather than a characteristic the layers change: a
Wall told it may attack still **has** defender for everything else — for what
"creatures with defender" counts, for what a defender-narrowed filter matches,
for what layer 6 reports to the web payload.

The key lives here, and not as a string spelled once in the handler that writes
it and again in the step that reads it, for the reason ``engine/pt.py`` gives
about channel vocabulary: two spellings of one channel is how an effect ends up
writing somewhere nothing reads. The cleanup sweep names it too
(``engine/mixins/_constants.py``), which is the whole of "this turn".
"""

from __future__ import annotations

# A leaf too (it imports nothing), so naming the duration vocabulary here keeps
# this module importable from the cleanup sweep without closing a cycle.
from .shields import END_OF_COMBAT

#: "…can attack this turn as though it didn't have defender." (Wall of Wonder.)
ATTACK_AS_THOUGH_NO_DEFENDER = "attack_as_though_no_defender_until_eot"

#: "This creature can attack as though it didn't have defender." with **no**
#: duration (the ability Prison Barricade has when it was kicked). The static
#: twin of the flag above: an instruction kind on the creature's own compiled
#: program, never a stamp, because a static ability applies for exactly as long
#: as the permanent says the sentence (CR 604.1) and nothing has to sweep it.
#: One name here for the lowering that produces it and the declare-attackers
#: read that honours it.
ATTACKS_AS_THOUGH_NO_DEFENDER = "attacks_as_though_no_defender"

#: "Target creature can't block this turn." (Panic.) A *restriction* rather than
#: a permission, and here anyway: it is the same kind of channel — one mark on
#: one permanent, written by a handler, read by a combat step, swept with the
#: turn — and the argument above about spelling a channel twice does not care
#: which direction the mark points. This module is a leaf that imports nothing
#: but another leaf (``engine/shields.py``'s duration words), which is what
#: lets the cleanup sweep name the key without closing a cycle;
#: ``engine/combat_restrictions.py``, where the *derivation* of the printed
#: clause lives, cannot be imported that early.
CANT_BLOCK_UNTIL_EOT = "cant_block_until_eot"

#: "Target creature can't attack this turn." (Change of Heart.) The attacking
#: twin of the mark above, in the same channel shape and here for the same
#: reason. Its own key rather than a second reading of that one: the two are
#: answered at two different steps, and one flag for both would ground a
#: creature Panic only meant to stop blocking.
CANT_ATTACK_UNTIL_EOT = "cant_attack_until_eot_mark"

#: "That creature can block up to two additional creatures this turn." (Yare.)
#: How many attackers *beyond the printed one* this permanent may block for the
#: rest of the turn, read by ``_max_blocks_for`` and swept with the turn. A
#: count rather than a flag, because CR 509.1b's ceilings add: two copies of the
#: spell are four extra attackers, and a creature whose own printed line already
#: blocks an additional one keeps that too.
ADDITIONAL_BLOCKS_UNTIL_EOT = "additional_blocks_until_eot"

#: Blaze of Glory's pair. Both are named here rather than spelled at their two
#: call sites for this module's stated reason -- and because naming them is what
#: got them into the cleanup sweep: "this turn" was written on the card and
#: nothing ever cleared either flag, so one Blaze of Glory made a creature able
#: to block every attacker, and obliged to, for the rest of the game.
CAN_BLOCK_ANY_NUMBER_UNTIL_EOT = "can_block_any_number_until_eot"
MUST_BLOCK_ALL_UNTIL_EOT = "must_block_all_until_eot"

#: "Target creature blocks this creature this turn if able." (Trumpeting
#: Armodon.) CR 509.1c's requirement for one turn, aimed at **one named
#: attacker**: a list of that attacker's ``permanent_id``s on the compelled
#: creature, read by the declare-blockers step and swept with the turn.
#:
#: A list of ids rather than a flag, for the reason ``ADDITIONAL_BLOCKS`` is a
#: count: two activations name two attackers and the creature owes both blocks
#: as far as the rules allow, so a flag would make the second activation do
#: nothing. By **id** rather than by index, because an index is renumbered by
#: anything leaving the battlefield and a returning permanent is a new object
#: (CR 400.7) that must not inherit a requirement aimed at its earlier self.
MUST_BLOCK_ATTACKERS_UNTIL_EOT = "must_block_attackers_until_eot"

#: "…block this creature **this combat** if able." (Provoke, CR 702.39a.) The
#: same pair as ``MUST_BLOCK_ATTACKERS_UNTIL_EOT`` over the shorter window, so
#: its own key rather than a second reading of that one: a turn may hold a
#: second combat phase (CR 505.1a's additional phases), and a requirement swept
#: only at cleanup would compel the creature to block the same attacker again
#: there. Swept by the end of combat step, where every other "this combat"
#: mark ends, and by cleanup as well, for a combat that never reaches its end
#: step (a turn ended early, CR 723).
#:
#: **One entry per requirement**, where the until-end-of-turn list keeps one per
#: attacker: two instances of provoke (two Hunter Slivers, CR 702.39b) aimed at
#: one creature are two requirements CR 509.1c counts, and a creature also owed
#: a block elsewhere must obey the side that carries more of them.
MUST_BLOCK_ATTACKERS_THIS_COMBAT = "must_block_attackers_this_combat"

#: Which mark a requirement aimed at one attacker is written to, by the
#: ``duration`` its payload carries: absent (Trumpeting Armodon's "this turn")
#: or ``shields.END_OF_COMBAT`` (provoke's "this combat") — the duration
#: vocabulary the end of combat step already sweeps shields and redirects by.
OWED_BLOCK_KEYS: dict[str | None, str] = {
    None: MUST_BLOCK_ATTACKERS_UNTIL_EOT,
    END_OF_COMBAT: MUST_BLOCK_ATTACKERS_THIS_COMBAT,
}

#: The duration provoke's requirement carries (CR 702.39a: "this combat").
PROVOKE_DURATION = END_OF_COMBAT

#: "Target creature can't block this creature this turn." (Duct Crawler.) The
#: exact denial mirror of the requirement above, and the same shape for the
#: same reasons: a list of the forbidden attackers' ``permanent_id``s on the
#: restricted creature, read by the declare-blockers step and swept with the
#: turn. A list because two activations name two attackers and both denials
#: hold; by id because an index is renumbered by anything leaving the
#: battlefield and a returning permanent is a new object (CR 400.7).
CANT_BLOCK_ATTACKERS_UNTIL_EOT = "cant_block_attackers_until_eot"

#: "That creature blocks this turn if able." (Provoke.) CR 509.1c's **weakest**
#: requirement for one turn: block *something* — any one attacker this creature
#: can legally block — where ``MUST_BLOCK_ATTACKERS_UNTIL_EOT`` names which
#: attacker and Blaze of Glory's mark names all of them.
#:
#: A count rather than a list: the requirement is about the creature and not
#: about a pair, so there is no id to keep — but a second copy of the spell is a
#: second requirement CR 509.1c counts (:func:`add_turn_requirement`). It is the
#: one-turn twin of Watchdog's printed static, read at the same place in the
#: declare-blockers step so the two cannot come to mean different things.
MUST_BLOCK_UNTIL_EOT = "must_block_until_eot"

#: "Target creature attacks this turn if able." (Boiling Blood, Siren's Call,
#: Norritt, Bullwhip, Kookus's upkeep.) CR 508.1d's requirement for one turn,
#: on the creature, swept at cleanup — a count of the effects imposing it
#: (:func:`add_turn_requirement`).
MUST_ATTACK_UNTIL_EOT = "must_attack_until_eot"


def add_turn_requirement(permanent, key: str) -> int:
    """Put **one more** requirement for this turn on *permanent* under *key*
    (:data:`MUST_ATTACK_UNTIL_EOT`, :data:`MUST_BLOCK_UNTIL_EOT`,
    :data:`MUST_BLOCK_ALL_UNTIL_EOT`) and return how many it now carries.

    A count, because CR 508.1d and 509.1c count requirements: two Boiling
    Bloods on one creature are two, which matters wherever they cannot all be
    obeyed — under Dueling Grounds that creature is the one that must attack
    beside a creature carrying one. The marks were ``True``, so the second
    effect did nothing at all.
    """
    count = turn_requirements(permanent, key) + 1
    permanent.metadata[key] = count
    return count


def turn_requirements(permanent, key: str) -> int:
    """How many requirements for this turn *permanent* carries under *key* —
    the one reader of :func:`add_turn_requirement`'s count. ``True``, the
    shape the marks had, is one."""
    value = permanent.metadata.get(key)
    if value is True:
        return 1
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


#: The printed static permissions that lift CR 509.1a's default of **one**
#: attacker per blocker, and how many extra attackers each one grants.
#:
#: A table beside the marks above rather than a substring scan inside the
#: declare-blockers step, for this module's stated reason: the sentence is read
#: twice — once by ``_max_blocks_for`` to raise the ceiling and once by the
#: support gate in ``engine/oracle.py`` to claim the line — and two readings of
#: one printed sentence is how a card comes to be admitted with its only ability
#: dropped. Two-Headed Giant of Foriys was already in that state in the small
#: way (a substring count here, a prefix string there); Wall of Glare is the
#: card that would have made it the large way, because "any number" is not a
#: count and a scan for the other spelling answers zero.
#:
#: Whole printed lines rather than prefixes, which is the anchoring
#: ``combat_restriction_for`` already has and the reason
#: ``static_line_support.py``'s own comment gives for preferring a table: a
#: prefix claim admits any sentence beginning with the words and drops
#: whatever follows.
#:
#: "…**this turn**" is deliberately absent. That spelling is a one-shot grant
#: (Yare, Mounted Archers, Blaze of Glory) written onto the permanent as
#: ``ADDITIONAL_BLOCKS_UNTIL_EOT`` / ``CAN_BLOCK_ANY_NUMBER_UNTIL_EOT`` by the
#: handler that resolves it and swept with the turn; read here it would be a
#: permanent grant every combat, for free and whether or not anybody activated
#: anything.
_PRINTED_BLOCK_PERMISSIONS: dict[str, int] = {
    # Two-Headed Giant of Foriys, Foriysian Brigade.
    "this creature can block an additional creature each combat": 1,
    # "This creature can block any number of creatures." (Wall of Glare.) No
    # ceiling at all, spelled as a number the additive arithmetic in
    # ``_max_blocks_for`` can carry — a sentinel keeps the sum one expression,
    # where an "unlimited" flag would fork every caller that adds to it.
    "this creature can block any number of creatures": 1_000_000,
}


def printed_block_ceiling(static_lines) -> int:
    """How many attackers **beyond the printed one** *static_lines* allow.

    0 for a creature printing none, which is every creature. Summed rather than
    maximised, because CR 509.1b's permissions are cumulative the way the
    granted ceilings beside them are: a creature printing the sentence twice
    blocks two extra.

    Read off the compiled program's **static** lines and not the whole oracle
    text, which is the distinction ``_max_blocks_for`` has always drawn and the
    one that matters: the same sentence is printed as an *activated* ability
    ("{W}: This creature can block an additional creature this turn.", Mounted
    Archers), and a text scan cannot tell the two apart.
    """
    return sum(
        _PRINTED_BLOCK_PERMISSIONS.get(_normalized_permission(line), 0)
        for line in static_lines or ()
    )


def block_permission_claims_line(line: str) -> bool:
    """Whether *line* is, in full, one of the block permissions above.

    The support gate's half of :func:`printed_block_ceiling`, so what raises the
    ceiling and what admits the card are the same table. A creature whose only
    line is one of these is supported by this and by nothing else.
    """
    return _normalized_permission(line) in _PRINTED_BLOCK_PERMISSIONS


def _normalized_permission(line: str) -> str:
    """*line* as the table spells it — lowercased, with the full stop off.

    One normalizer for both readers, because the gate is handed a line the
    compiler already normalized and the ceiling is handed a compiled static
    line, and the two differ by exactly a trailing period.
    """
    return str(line or "").strip().lower().rstrip(".")

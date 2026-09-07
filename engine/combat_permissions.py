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

#: "…can attack this turn as though it didn't have defender." (Wall of Wonder.)
ATTACK_AS_THOUGH_NO_DEFENDER = "attack_as_though_no_defender_until_eot"

#: "Target creature can't block this turn." (Panic.) A *restriction* rather than
#: a permission, and here anyway: it is the same kind of channel — one mark on
#: one permanent, written by a handler, read by a combat step, swept with the
#: turn — and the argument above about spelling a channel twice does not care
#: which direction the mark points. This module is a leaf that imports nothing,
#: which is what lets the cleanup sweep name the key without closing a cycle;
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
#: attacker and Blaze of Glory's flag names all of them.
#:
#: A flag rather than a list, and that is the difference itself: the
#: requirement is about the creature and not about a pair, so there is no id to
#: keep and a second copy of the spell asks for nothing more. It is the
#: one-turn twin of Watchdog's printed static, read at the same place in the
#: declare-blockers step so the two cannot come to mean different things.
MUST_BLOCK_UNTIL_EOT = "must_block_until_eot"

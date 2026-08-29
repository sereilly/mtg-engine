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

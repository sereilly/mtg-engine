"""CR 609.4 combat *permissions* recorded on a permanent.

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

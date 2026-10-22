"""Size-guard headroom for the tree you are in, without running the checks.

    headroom.py

`check_all.py --caps` prints the same report after running every check; this
is the report alone, for a merge being staged and for a brief's "module
headroom" section. It prints every module inside the band (`CAP_MARGIN` of a
cap) — those are the modules Phase 0 pre-splits before a set, not a wave
during one. The caps are `check_all.SIZE_GUARDS`, which a test holds equal to
the guards that enforce them.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "scripts"))

import check_all  # noqa: E402

check_all.report_caps()

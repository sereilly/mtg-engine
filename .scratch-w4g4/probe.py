import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
from engine.grammar import parse_line
from engine.grammar.lower import lower_ability

LINES = [
    "Tap X target creatures.",
    "Choose X target attacking creatures.",
    "X can't be greater than the number of snow lands you control.",
    "For each of those creatures, its controller may pay {1} or {2}.",
    "Destroy that creature at end of combat.",
    "Prevent all combat damage that would be dealt to and dealt by that creature this combat.",
    "Cast this spell only during combat before blockers are declared.",
]
for line in LINES:
    print("=" * 70)
    print(line)
    try:
        node = parse_line(line)
        print("  PARSED:", node)
    except Exception as exc:
        print("  PARSE FAIL:", type(exc).__name__, exc)
        continue
    try:
        print("  LOWERED:", lower_ability(node))
    except Exception as exc:
        print("  LOWER FAIL:", type(exc).__name__, exc)

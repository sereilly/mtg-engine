import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.grammar import parse_line
from engine.grammar.lower import lower_ability

LINES = [
    "Prevent all combat damage that would be dealt to and dealt by that creature this combat.",
    "Prevent all combat damage that would be dealt to and dealt by that creature this turn.",
    "Prevent all combat damage that would be dealt by that creature this turn.",
    "Prevent all combat damage that would be dealt to and dealt by target creature this turn.",
    "Prevent all combat damage that would be dealt to and dealt by enchanted creature.",
    "Prevent all damage that would be dealt to and dealt by that creature this turn.",
    "Its controller may pay {1}.",
    "Its controller may pay {1} or {2}.",
    "That creature's controller may pay {1}.",
    "If that player doesn't, destroy that creature at end of combat.",
    "If that player pays only {1}, prevent all combat damage that would be dealt to and dealt by that creature this combat.",
    "Choose two target blocked attacking creatures.",
    "Choose target creature.",
    "Choose X target attacking creatures.",
    "Tap X target attacking creatures.",
]
for line in LINES:
    print("=" * 70)
    print(line)
    try:
        node = parse_line(line)
    except Exception as exc:
        print("  PARSE FAIL:", type(exc).__name__, exc)
        continue
    print("  PARSED ok")
    try:
        for ins in lower_ability(node):
            print("  ->", ins.kind, ins.payload)
    except Exception as exc:
        print("  LOWER FAIL:", type(exc).__name__, exc)

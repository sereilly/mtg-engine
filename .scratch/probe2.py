import sys
sys.path.insert(0, ".")
from engine.grammar import parse_line
LINES = [
 "When an opponent casts a creature spell, it becomes white.",
 "When an opponent casts a creature spell, this permanent becomes white.",
 "Whenever you play a land, this permanent becomes white.",
 "{0}: This permanent becomes white.",
 "Target creature loses all abilities until end of turn.",
 "Target creature becomes an enchantment in addition to its other types.",
 "{X}: This artifact becomes an X/X Construct artifact creature in addition to its other types until end of turn.",
 "{2}: This artifact becomes a 3/3 Construct artifact creature until end of turn.",
 "When an opponent casts a spell, it becomes a 1/1 Bird creature with flying in addition to its other types.",
]
for line in LINES:
    try:
        r = parse_line(line)
        print("OK  ", line[:78])
        print("     ", repr(r)[:700])
    except Exception as e:
        print("FAIL", line[:78]); print("     ", type(e).__name__, e)

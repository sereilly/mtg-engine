import sys
sys.path.insert(0, ".")
from engine.grammar import parse_line
LINES = [
 "When an opponent casts a creature spell, if this permanent is an enchantment, it becomes a 2/2 Gargoyle creature with flying.",
 "When an opponent casts a creature spell, this permanent becomes a 2/2 Gargoyle creature with flying.",
 "When an opponent casts a creature spell, it becomes a 2/2 Gargoyle creature.",
 "When an opponent casts a spell, it becomes a 1/1 Bird creature with flying.",
 "When an opponent casts an enchantment spell, it becomes a 5/5 Treefolk creature.",
 "When an opponent casts an artifact spell, it becomes a 5/3 Soldier creature with trample.",
 "When an opponent casts a creature spell with flying, it becomes a 3/5 Spider creature with reach.",
 "When an opponent plays a nonbasic land, it becomes a 3/3 Beast creature.",
 "Whenever an opponent plays a land, it becomes a 3/2 Elk Beast creature.",
 "Whenever you play a land, it becomes an enchantment.",
 "When an opponent controls a creature with power 4 or greater, it becomes a 4/4 Beast creature.",
 "When a player has no cards in hand, it becomes a 4/4 Crocodile creature.",
 "{0}: This permanent becomes an enchantment.",
 "{X}: This artifact becomes an X/X Construct artifact creature until end of turn.",
 "{1}{W}, {T}: Target creature becomes an enchantment and loses all abilities until a player casts a creature spell.",
 "At the beginning of your upkeep, sacrifice this creature unless you pay {1}{U}.",
 "This creature can't attack unless defending player controls an Island.",
 "Pay half your life, rounded up: This enchantment becomes a 4/4 Phyrexian Horror creature with flying.",
 "When an opponent casts a spell, it becomes an Illusion creature with power and toughness each equal to that spell's mana value.",
 "When an opponent casts a creature spell, it becomes a 4/4 Giant creature with protection from each of that spell's colors.",
 "{1}: Target noncreature artifact becomes an artifact creature with power and toughness each equal to its mana value until end of turn.",
]
for line in LINES:
    try:
        r = parse_line(line)
        print("OK  ", line[:70])
        print("     ", repr(r)[:400])
    except Exception as e:
        print("FAIL", line[:70])
        print("     ", type(e).__name__, e)

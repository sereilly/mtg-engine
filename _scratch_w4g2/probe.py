import sys
sys.path.insert(0, '.')
from engine.grammar import parse_line, GrammarError
from engine.grammar.lower import lower_ability
lines = [
    "Untap it and remove it from combat.",
    "untap it and remove it from combat",
    "Untap target attacking creature and remove it from combat.",
    "You choose which creatures block this combat and how those creatures block.",
    "Whenever a creature attacks and isn't blocked this combat, untap it and remove it from combat.",
    "Choose two target blocked attacking creatures.",
    "Choose target blocked attacking creature.",
    "Choose two target attacking creatures.",
    "Choose X target attacking creatures.",
]
for ln in lines:
    try:
        node = parse_line(ln)
        print("PARSE OK  :", repr(ln))
        print("   node:", node)
        try:
            instr = lower_ability(node)
            print("   LOWERED:", instr)
        except Exception as e:
            print("   LOWER FAIL:", type(e).__name__, e)
    except GrammarError as e:
        print("PARSE FAIL:", repr(ln), "->", e)
    except Exception as e:
        print("PARSE ERR :", repr(ln), "->", type(e).__name__, e)
    print()

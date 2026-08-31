import sys, traceback
sys.path.insert(0, ".")
from engine.grammar import parse_line, GrammarError, lower_ability, LoweringError
import pprint

for text in sys.argv[1:]:
    print("="*70)
    print(repr(text))
    try:
        node = parse_line(text)
        print("PARSE OK:", node)
    except GrammarError as e:
        print("PARSE REFUSED:", e)
        continue
    except Exception as e:
        print("PARSE EXC:", type(e).__name__, e); traceback.print_exc(); continue
    try:
        instrs = lower_ability(node)
        print("LOWER OK:")
        pprint.pprint(instrs)
    except LoweringError as e:
        print("LOWER REFUSED:", e)
    except Exception as e:
        print("LOWER EXC:", type(e).__name__, e); traceback.print_exc()

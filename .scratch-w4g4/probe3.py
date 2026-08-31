import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.grammar.nouns import parse_object_filter
from engine.grammar.stream import TokenStream
from engine.grammar.lexer import tokenize

for phrase in ["snow lands you control", "snow land", "attacking creatures", "snow permanents you control", "creatures"]:
    lex = tokenize(phrase)
    st = TokenStream(lex.tokens, phrase)
    try:
        f = parse_object_filter(st)
        print(phrase, "->", "supertypes=", f.supertypes, "types=", f.card_types, "ctrl=", f.controller, "attacking=", f.attacking, "| exhausted:", st.exhausted)
    except Exception as e:
        print(phrase, "-> FAIL", e)

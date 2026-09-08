import sys
sys.path.insert(0, ".")
from engine.grammar import parse_line
for line in [
 "When an opponent casts a creature spell, it becomes white.",
 "When an opponent casts a spell, it becomes white.",
 "When an opponent casts a creature spell, this permanent becomes white.",
]:
    r = parse_line(line)
    st = r.statement
    print(line)
    print("   subject quantifier:", st.subject.quantifier, "| filter card_types:", st.subject.filter.card_types, "| is_source:", st.subject.filter.is_source)

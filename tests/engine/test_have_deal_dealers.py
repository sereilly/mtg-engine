"""Every "have <dealer> deal" printing's damage comes from the object its
words name (CR 120.7).

"Whenever a Beast you control enters, you may **have it** deal 4 damage to
target opponent or planeswalker." (Aether Charge.) A reader consumes the
causative "have" in front of the damage sentence — ``statements``' "you may
have", ``player_verbs``' "<seat> may have", ``effects.damage``'s "have
<source> deal" — and what was left read exactly like Mogg Bombers' "it deals",
whose pronoun is the ability's own source. So the red Charge dealt the damage
the green Beast deals. ``ast.DealDamage.causative`` keeps the "have" on the
node and ``lowering.damage._with_foreign_dealer`` makes a rebound pronoun
under it the event's object (``biter: "event_subject"``).

The census is the twenty-three printings in both manifest roles, the dealer
read off the **text** — the trigger clause's subject is the antecedent of a
bare "it", "this <noun>" is the source, "enchanted creature" the host — and
compared with the dealer the compiled line carries. It is independent of the
grammar's own rebinding, which is what made the misreading invisible.
Validated backwards: on the tree before the fix it names Aether Charge alone.
"""

from __future__ import annotations

import re

from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar import compile_line
from engine.oracle import compile_card_oracle, expand_ability_lines
from engine.oracle_types import strip_ability_word

_HAVE_DEAL = re.compile(
    r"\bhave (it|this \w+|that creature|enchanted creature) deal\b", re.I,
)
_SELF_WORDS = (
    "this creature", "this card", "this enchantment", "this permanent",
    "this artifact",
)
#: Printings when this was written (23); a census that examined nothing passes.
_FLOOR = 20


def _named_dealer(line: str, card_name: str, dealer: str) -> str:
    """Which object the printed words make the dealer: "own" (the ability's
    source), "attached" (the host) or "event_subject" (the object the
    trigger's condition was about)."""
    if dealer.lower().startswith("this "):
        return "own"
    if dealer.lower() == "enchanted creature":
        return "attached"
    lowered = line.lower()
    if lowered.startswith("until end of turn, "):
        lowered = lowered[len("until end of turn, "):]
    if not re.match(r"^(when|whenever|at)\b", lowered):
        return "own"
    head = lowered.split(",")[0]
    if "enchanted creature" in head:
        return "attached"
    if any(word in head for word in _SELF_WORDS) or card_name.lower() in head:
        return "own"
    return "event_subject"


def _dealers(instructions) -> set:
    found = set()
    for instruction in instructions or ():
        if "biter" in instruction.payload:
            found.add(instruction.payload["biter"])
        for value in instruction.payload.values():
            if isinstance(value, tuple) and value and hasattr(value[0], "kind"):
                found |= _dealers(value)
    return found


def _census():
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    examined = 0
    wrong = []
    for name, card in sorted(cards.items()):
        text = expand_ability_lines(
            card.oracle_text or "", card_name=card.name, legendary=card.is_legendary,
        )
        for raw in text.split("\n"):
            line = strip_ability_word(raw).strip()
            match = _HAVE_DEAL.search(line)
            if match is None:
                continue
            examined += 1
            want = _named_dealer(line, card.name, match.group(1))
            if line.lower().startswith("until end of turn, whenever"):
                # A spell's delayed trigger (Gaze of Pain): CR 603.7d's
                # fallback hands the event's object over as the ability's
                # source at the fire site (``delayed_triggers``), so the
                # pronoun is the dealer with no ``biter`` at all.
                program = compile_card_oracle(card)
                if not (
                    program.supported
                    and any(i.kind == "create_delayed_trigger" for i in program.instructions)
                ):
                    wrong.append((name, want, "no delayed trigger"))
                continue
            compiled = compile_line(line, card_name=card.name)
            got = _dealers(compiled.instructions)
            if not compiled.instructions:
                wrong.append((name, want, "refused"))
            elif (want == "own" and got) or (want != "own" and want not in got):
                wrong.append((name, want, sorted(got)))
    return examined, wrong


def test_every_have_deal_printing_deals_from_the_object_it_names():
    examined, wrong = _census()
    assert examined >= _FLOOR, examined
    assert wrong == [], (
        "these lines deal their damage from an object other than the one "
        f"their words name (name, named dealer, compiled dealer): {wrong}"
    )


def test_have_it_deal_reads_the_event_object_and_it_deals_does_not():
    """The two spellings side by side on invented lines: under "have" the
    rebound pronoun is the Beast that entered; without it, Mogg Bombers'
    reading keeps the ability's own source. And a causative pronoun no fire
    site records refuses rather than dealing as the source."""
    had = compile_line(
        "Whenever a Beast you control enters, you may have it deal 2 damage "
        "to target creature.",
        card_name="Probe Charge",
    )
    assert _dealers(had.instructions) == {"event_subject"}

    bare = compile_line(
        "When another creature enters, sacrifice this creature and it deals "
        "3 damage to target player or planeswalker.",
        card_name="Probe Bombers",
    )
    assert bare.instructions
    assert _dealers(bare.instructions) == set()

    # An attack's fire site freezes no object for the dealer to be read from
    # (``_events.EVENT_SUBJECT_LAST_KNOWN_EVENTS``), so the line refuses rather
    # than compiling as the ability's source dealing the damage.
    unrecorded = compile_line(
        "Whenever a creature you control attacks, you may have it deal 1 "
        "damage to any target.",
        card_name="Probe Banner",
    )
    assert not unrecorded.instructions

    # "have" is read, not skipped: without it the offer is not a sentence,
    # which the deletion probe used to report as a word nothing read.
    for sentence in (
        "Whenever a Beast you control enters, you may it deal 4 damage to "
        "target opponent or planeswalker.",
        "When this creature enters, any opponent may it deal 5 damage to them.",
    ):
        assert not compile_line(sentence, card_name="Probe Charge").instructions, sentence

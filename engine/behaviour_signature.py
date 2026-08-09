"""Behavioural equivalence between cards.

Two cards are *behaviourally equivalent* when the engine, resolving them, runs
the same code with the same shape of data — differing only in values it handles
generically (how much damage, which colour, what power and toughness). Grizzly
Bears and Hill Giant are equivalent: both are vanilla creatures and the numbers
flow through the same combat code. Aladdin's Ring and Rod of Ruin are
equivalent: the same activated damage ability with different constants.

This exists so verification can scale. Testing 26,000 cards one at a time is not
possible, but a card whose behaviour class already contains a verified card
exercises no engine path that card didn't.

**What it does not claim.** Equivalence is strictly weaker than checking a card:
it says "this runs no new engine path", not "this is correct". It cannot catch a
card whose *data* breaks a generic path, and it inherits any error in its peer —
if the peer was marked passing wrongly, so is everything derived from it. That
is why the web layer reports it as its own status rather than as a pass.

**The failure mode to respect.** The signature is only as good as its coverage of
what the engine branches on. A first version of this dropped ``produced_mana``,
activated-ability payloads, and the oracle text that text-keyed channels read —
and cheerfully declared Flight equivalent to Control Magic (grant flying vs.
steal the creature), Forest equivalent to Badlands, and Sol Ring equivalent to
Mox Emerald. Nothing in the output looked wrong; it just reported twice the
coverage. Whenever a new text-keyed behaviour is added to the engine, check that
the signature still distinguishes the cards it applies to.
``tests/engine/test_behaviour_classes.py`` pins the classes against a snapshot
so a regression here fails loudly instead of quietly inflating coverage.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Iterable

from .oracle import compile_card_oracle

_COLOUR_WORD = re.compile(r"\b(white|blue|black|red|green)\b")
_COLOUR_SYMBOL = re.compile(r"\{[WUBRG]\}")
_NUMBER = re.compile(r"\d+")

# Card types the engine dispatches on. Subtypes are deliberately excluded — a
# Goblin and a Zombie run the same code — except where a subtype appears in
# oracle text, which the masked text below preserves.
_DISPATCH_TYPES = ("artifact", "creature", "enchantment", "instant", "land", "sorcery")


def _mask(text: str) -> str:
    """Blank the values the engine handles generically.

    Numeric literals and which colour are data, not control flow: "deals 3
    damage" and "deals 4 damage" run one handler, and a colour-scoped effect
    runs one path for every colour. Everything else is kept, because everything
    else can select a different path.
    """
    masked = _COLOUR_WORD.sub("@c", text.lower())
    masked = _COLOUR_SYMBOL.sub("{@c}", masked)
    return _NUMBER.sub("#", masked)


# Payload keys whose value is a colour, held as a bare mana symbol ("B", "R")
# that the text mask cannot recognise. Masked by key rather than by looking for
# single letters, so an unrelated payload that happens to hold "b" is untouched.
_COLOUR_KEYS = ("color", "colour")


def _mask_value(value: Any, key: str = "") -> Any:
    if isinstance(value, str):
        if any(marker in key.lower() for marker in _COLOUR_KEYS):
            return "@c"
        return _mask(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return "#"
    if isinstance(value, dict):
        return {inner_key: _mask_value(inner, inner_key) for inner_key, inner in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        return sorted((_mask_value(item, key) for item in value), key=repr)
    return str(value)


def behaviour_signature(card) -> str:
    """A stable key for *card*'s behaviour. Equal keys mean equal engine paths.

    Includes every input the engine branches on: card types, keywords, how much
    mana it produces, the compiled instructions/triggers/activated abilities
    with their payloads, static lines, and the normalized oracle text (which is
    what the text-keyed channels — auras, untap and draw-step tables, the
    replacement and prevention registries — actually read).
    """
    program = compile_card_oracle(card)
    type_line = card.type_line.lower()
    return json.dumps(
        {
            "types": [t for t in _DISPATCH_TYPES if t in type_line],
            "keywords": sorted(k.lower() for k in (card.keywords or ())),
            # Colour is masked, but how *many* mana are produced is not:
            # Sol Ring's {C}{C} is not Mox Emerald's {G}.
            "mana_produced": len(card.produced_mana or ()),
            "text": _mask(program.normalized_text or ""),
            "instructions": sorted(
                [instr.kind, _mask(instr.value), _mask_value(instr.payload)]
                for instr in program.instructions
            ),
            "triggered": sorted(
                [
                    trig.condition.kind,
                    trig.instruction.kind if trig.instruction else None,
                    _mask_value(trig.instruction.payload if trig.instruction else {}),
                ]
                for trig in program.triggered_abilities
            ),
            "activated": sorted(
                [
                    ability.instruction.kind if ability.instruction else None,
                    _mask_value(ability.instruction.payload if ability.instruction else {}),
                ]
                for ability in program.activated_abilities
            ),
            "statics": sorted(_mask(line) for line in program.static_lines),
        },
        sort_keys=True,
        default=str,
    )


def behaviour_classes(cards: Iterable) -> dict[str, list[str]]:
    """Card names grouped by behaviour signature, each group name-sorted."""
    groups: dict[str, list[str]] = defaultdict(list)
    for card in cards:
        groups[behaviour_signature(card)].append(card.name)
    return {sig: sorted(names) for sig, names in groups.items()}


def peers_by_card(cards: Iterable) -> dict[str, list[str]]:
    """For each card name, the other cards sharing its behaviour (may be empty)."""
    peers: dict[str, list[str]] = {}
    for names in behaviour_classes(cards).values():
        for name in names:
            peers[name] = [other for other in names if other != name]
    return peers


def equivalent_peer(name: str, peers: dict[str, list[str]], verified: set[str]) -> str | None:
    """The verified card *name* derives its equivalence from, or None.

    Deterministic (name-sorted) so a card's stated peer doesn't drift between
    runs, which would make the tracker's history unreadable.
    """
    return next((peer for peer in peers.get(name, ()) if peer in verified), None)

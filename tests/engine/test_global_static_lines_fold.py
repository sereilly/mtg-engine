"""Every board-wide static line a card prints is honoured by the static its
text compiles to.

The support gate claims a board-wide static **per line**
(``static_line_support``, ``parse_coverage_claims``): a line
``global_statics.global_static_for`` reads on its own is a supported line.
But the layers, the refresh and the colour readers ask ``global_static_for``
of a permanent's **whole** text, and that answered with the first matching
line alone — so a card printing two would compile supported with its second
line doing nothing. Mycosynth Lattice prints two ("All permanents are
artifacts in addition to their other types." / "All cards that aren't on the
battlefield, spells, and permanents are colorless."), and the whole-text read
folds lines over one scope into one static (``global_statics._fold``).

This census holds the two readings together over both manifest roles: every
field a line's own static sets is set the same way in the whole text's. It
fails the first card whose lines do not fold (another scope, a field both
set) — the shape that would be a hollow line.
"""

from dataclasses import fields

from engine.card_loader import load_cards, manifest_set_paths
from engine.global_statics import GlobalStatic, global_static_for


def _set_fields(static: GlobalStatic) -> dict:
    return {
        spec.name: getattr(static, spec.name)
        for spec in fields(GlobalStatic)
        if spec.name != "name" and getattr(static, spec.name) != spec.default
    }


def test_every_global_static_line_reaches_the_whole_texts_static():
    seen: set[str] = set()
    examined = 0
    several = []
    unhonoured = []
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            if card.name in seen:
                continue
            seen.add(card.name)
            text = card.oracle_text or ""
            statics = [
                found for line in text.splitlines()
                if (found := global_static_for(line)) is not None
            ]
            if not statics:
                continue
            examined += 1
            if len(statics) > 1:
                several.append(card.name)
            whole = _set_fields(global_static_for(text))
            for line_static in statics:
                for name, value in _set_fields(line_static).items():
                    if whole.get(name) != value:
                        unhonoured.append((card.name, line_static.name, name))
    assert not unhonoured, unhonoured
    # Floors: the census read the board-wide statics at all, and at least one
    # card prints two of them (the shape the fold exists for).
    assert examined >= 15, examined
    assert several, "no card prints two board-wide static lines"

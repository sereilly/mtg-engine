"""The keyword badges the client shows are held to the keywords the engine has.

`web/serialization._DISPLAY_KEYWORDS` is a hand-ordered tuple, because the badge
row reads better in a fixed order than in alphabetical one. That is the only
reason it is written out, and it is exactly the shape this repo keeps finding
stale: a list somebody has to remember to extend.

It went stale three times before anything asked. **Shadow** shipped with
Tempest's 25 creatures and the badge row never mentioned it — the keyword that
decides whether the creature can block or be blocked at all (CR 702.28b), read
by the engine correctly and invisible to the player. **Phasing** had been
missing since Mirage and **desertwalk** since Arabian Nights.

So the tuple stays hand-ordered and this test makes the omission loud: every
keyword in `vocabulary.IMPLEMENTED_KEYWORDS` is either badged or named in
`_NOT_BADGED` with its reason. Neither half may drift — a keyword excused here
that the engine does not implement is the same second copy going stale from the
other end.
"""

import pytest

from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS
from web.serialization import _DISPLAY_KEYWORDS, _NOT_BADGED


def _badged() -> set[str]:
    return {keyword.lower() for keyword in _DISPLAY_KEYWORDS}


def test_every_implemented_keyword_is_badged_or_excused():
    """The assertion the tuple could not make about itself."""
    implemented = {keyword.lower() for keyword in IMPLEMENTED_KEYWORDS}
    unaccounted = sorted(implemented - _badged() - _NOT_BADGED)
    assert not unaccounted, (
        "these keywords are implemented and the client shows no badge for "
        f"them: {unaccounted}. Add each to _DISPLAY_KEYWORDS, or to _NOT_BADGED "
        "with the reason a badge would say less than the card does."
    )


def test_nothing_is_excused_that_the_engine_does_not_implement():
    """The other direction, so the excuse list cannot outlive its keyword."""
    implemented = {keyword.lower() for keyword in IMPLEMENTED_KEYWORDS}
    stale = sorted(_NOT_BADGED - implemented)
    assert not stale, (
        f"_NOT_BADGED excuses keywords the engine does not implement: {stale}"
    )


def test_no_keyword_is_both_badged_and_excused():
    both = sorted(_badged() & _NOT_BADGED)
    assert not both, f"badged and excused at once: {both}"


@pytest.mark.parametrize(
    "name,keyword",
    [
        ("Soltari Priest", "Shadow"),
        ("Teferi's Isle", "Phasing"),
    ],
)
def test_a_shipped_card_carrying_the_keyword_gets_its_badge(catalog_by_name, name, keyword):
    """The badge on a real card, not on the tuple.

    Soltari Priest is the case that found this: the engine enforced its shadow
    from the day the keyword landed, and the player was never told the creature
    had it.
    """
    from engine import Game, PlayerState
    from engine.models import Permanent
    from web.serialization import _effective_keywords

    card = catalog_by_name[name]
    game = Game([PlayerState(name="A"), PlayerState(name="B")])
    permanent = Permanent(card=card)
    game.players[0].battlefield.append(permanent)

    assert keyword in _effective_keywords(permanent, game), (
        f"{name} carries {keyword} and the client is not told"
    )

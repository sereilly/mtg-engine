"""Changing what a permanent produces when it is tapped for mana (CR 611.2).

Three printed sentences and one standing swap. Nothing is added when any of
them resolves: what they record is that a land will make a different symbol
from now on, which the mana ability reads back every time it is tapped
(CR 305.7).

    _parse_produces_instead             "If target Plains is tapped for mana, it
                                        produces {B} instead of {W}." — one
                                        named land (Quarum Trench Gnomes)
    _parse_tapper_produces_instead      "…if you tap a land you control for
                                        mana, it produces {U} instead of any
                                        other type." — a *class* of lands, in
                                        the active voice (Deep Water, Chaos
                                        Moon)
    _parse_tapped_lands_produce_chosen  "Lands tapped for mana produce mana of
                                        the chosen color instead of any other
                                        color." — the same swap in the passive
                                        voice (Hall of Gemstone)

Split out of ``effects/mana.py`` at Urza's Destiny's Phase 0, when that module
sat **twelve** lines under the thousand-line guard with a parallel wave about to
land productions in it — the pre-split SET_PLAYBOOK.md asks for rather than a
brief. The seam is the one that module's own first sentence had already drawn
and named: "Mana: producing it, **and changing what a permanent produces**."

The line is the CR's own, and it is the one ``control_changes`` and
``text_changes`` draw beside this file: CR 605 is a mana ability a permanent
performs *now*, resolving into a pool, where CR 611.2 is a continuous effect
that changes what it will do *later* — recorded on the land or on a seat, and
never adding a single point of mana itself. Everything left in ``mana`` counts
pips, multipliers and amounts, none of which appears below.

The two halves share no name in either direction, checked at the split:
``_parse_produced_mana_word`` and its word table are read by these three
productions alone, and ``references.parse_target_spec`` — one layer down, not a
sibling — by no production left behind. There is no import between the two
modules in either direction.

A **parse-only family**, like ``search``, ``reveal``, ``text_changes`` and
``damage_locks`` before it, and for their reason read the other way round: the
words are where the work is. All three sentences lower within fifty lines of
each other in ``lowering/mana.py`` — a swap lowers to one instruction however
many ways its sentence spells the tapper — so a near-empty
``lowering/production_changes.py`` would buy back the symmetry and cost the
thing symmetry is for.
"""

from ...oracle_types import MANA_COLOR_OF_CHOICE
from .. import ast
from ..errors import GrammarError
from ..lexer import MANA
from ..references import parse_target_spec
from ..stream import TokenStream


# The colour words a "produces X instead of Y" clause may name, mapped to the
# symbol produced. "Colorless" is here rather than beside the five colours in
# `oracle_types` because {C} is not a colour (CR 105.1) — it is the *absence*
# of one, and only a clause about produced mana treats the two as alternatives
# in the same slot.
_PRODUCED_MANA_WORDS = {
    "white": "W",
    "blue": "U",
    "black": "B",
    "red": "R",
    "green": "G",
    "colorless": "C",
}


def _parse_produced_mana_word(stream: TokenStream) -> str | None:
    """``<colour|colorless> mana`` — the symbol named, or None."""
    mark = stream.mark()
    word = stream.peek_word()
    symbol = _PRODUCED_MANA_WORDS.get(word or "")
    if symbol is None:
        return None
    stream.advance()
    if not stream.accept_word("mana"):
        stream.reset(mark)
        return None
    return symbol


def _parse_produces_instead(stream: TokenStream) -> "ast.ProducesManaInstead | None":
    """``If <object> is tapped for mana, it produces <X> mana instead of <Y> mana.``

    Quarum Trench Gnomes. Refuses without consuming, because "if" opens every
    intervening-if and every conditional sentence in the pool and this is one
    printed shape among them.

    Both symbols are read, in both slots. A production that consumed "instead
    of white mana" without recording the colour would read a card that swapped
    a land's *green* mana as though it swapped its white — and, worse, would
    fire on a land that never made white at all.
    """
    mark = stream.mark()
    if not stream.accept_word("if"):
        return None
    try:
        target = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if target is None or not stream.accept_phrase("is", "tapped", "for", "mana"):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    # "**it** produces" — the same object the condition named. Read rather than
    # skipped: a different subject here would be a different card.
    if not stream.accept_phrase("it", "produces"):
        stream.reset(mark)
        return None
    produced = _parse_produced_mana_word(stream)
    if produced is None or not stream.accept_phrase("instead", "of"):
        stream.reset(mark)
        return None
    replaced = _parse_produced_mana_word(stream)
    if replaced is None:
        stream.reset(mark)
        return None
    return ast.ProducesManaInstead(target, replaced=replaced, produced=produced)


def _accept_swapped_land_back_reference(
    stream: TokenStream, subject: "ast.TargetSpec"
) -> bool:
    """``it`` / ``that Mountain`` — the land the clause's condition just named.

    Read rather than skipped: a different subject here would be a different
    card, and the noun in the long spelling has to be the one the condition
    described. Chaos Moon prints "if a player taps **a Mountain** for mana,
    **that Mountain** produces …" and a reader that took any noun would accept
    a sentence swapping the mana of something the clause never mentioned.
    """
    if stream.accept_word("it"):
        return True
    mark = stream.mark()
    if not stream.accept_word("that"):
        return False
    noun = stream.peek_word()
    if noun is None:
        stream.reset(mark)
        return False
    subtypes = subject.filter.subtypes
    # "that land" answers a clause that named no land type; "that Mountain"
    # answers one that named exactly that type. Anything else is a noun the
    # condition did not describe.
    if noun == "land" and not subtypes:
        stream.advance()
        return True
    if noun in subtypes:
        stream.advance()
        return True
    stream.reset(mark)
    return False


def _parse_tapper_produces_instead(
    stream: TokenStream,
) -> "ast.ProducesManaInstead | None":
    """``If you tap <objects> for mana, it produces {X} instead of any other
    type.`` (Deep Water.) ``If a player taps <objects> for mana, that <noun>
    produces <colour> mana instead of any other type.`` (Chaos Moon.) Both with
    "Until end of turn," in front of them — the leading duration the statement
    layer distributes.

    The same CR 611.2 / CR 305.7 swap :func:`_parse_produces_instead` reads, in
    the active voice and about a *class* of lands rather than one named object.
    Read as its own production rather than as a branch of that one because the
    two sentences share no word after "if": one names the land and puts it in
    the subject slot, the other names the tapper and puts the land in the
    object slot.

    **The tapper is the whole difference between the two spellings here**, and
    it is read rather than inferred. "You" arms the swap on the ability's own
    controller; "a player" arms it on every seat, because the sentence names
    none. Inferring that from the noun phrase's "you control" instead would tie
    two independent printed words together, and each of them can appear without
    the other.

    Refuses without consuming, for :func:`_parse_produces_instead`'s reason:
    "if" opens every conditional in the pool.

    Both ends are read. "instead of any other **type**" is not a colour — it is
    everything the land would have produced — and a production that stopped at
    "instead of" would compile Deep Water onto a swap of one unnamed symbol.
    """
    mark = stream.mark()
    if stream.accept_phrase("if", "you", "tap"):
        each_player = False
    elif stream.accept_phrase("if", "a", "player", "taps"):
        each_player = True
    else:
        return None
    try:
        subject = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if subject is None or not stream.accept_phrase("for", "mana"):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    if not _accept_swapped_land_back_reference(stream, subject):
        stream.reset(mark)
        return None
    if not stream.accept_word("produces"):
        stream.reset(mark)
        return None
    # Two printed spellings of one symbol, because the pool prints both: the
    # symbol itself ({U}, Deep Water) and the colour written out ("colorless
    # mana", Chaos Moon). The word form is read first and non-consuming, so a
    # line printing neither still falls out on the mana check below.
    produced = _parse_produced_mana_word(stream)
    # "…it produces **one mana of a color of your choice** instead of any other
    # type and amount." (Harvest Mage.) No symbol at all: the tapper names a
    # colour each time a land is tapped, so the node carries the sentinel the
    # tap seam resolves. Every word is required — "one" is the amount the
    # "and amount" tail below replaces *to*, and "your" is the tapper's own
    # choice, which is why the any-player spelling ("a player taps", where
    # "your" would be somebody else's) refuses it.
    if produced is None and not each_player and stream.accept_phrase(
        "one", "mana", "of", "a", "color", "of", "your", "choice"
    ):
        produced = MANA_COLOR_OF_CHOICE
    if produced is None:
        token = stream.peek()
        produced = (
            token.text.strip("{}") if token is not None and token.kind == MANA else ""
        )
        # One coloured symbol, spelled as the card prints it. A hybrid, a
        # phyrexian or a generic pip is a symbol the record has no way to
        # produce, and admitting one would arm a swap onto a symbol no mana pool
        # has.
        if len(produced) != 1 or not produced.isalpha():
            stream.reset(mark)
            return None
        stream.advance()
    if not stream.accept_phrase("instead", "of", "any", "other", "type"):
        stream.reset(mark)
        return None
    # "…instead of any other type **and amount**." (Harvest Mage.) Read, not
    # skipped, for the static twin's reason (Contamination): without the words
    # a land that makes two mana makes two of the new colour, a strictly
    # better card than the printed one.
    replaces_amount = bool(stream.accept_phrase("and", "amount"))
    if produced == MANA_COLOR_OF_CHOICE and not replaces_amount:
        # "one mana of a color of your choice" with no "and amount" behind it
        # would say one mana and then keep the land's amount — a sentence no
        # card prints, and the two halves would contradict each other.
        stream.reset(mark)
        return None
    return ast.ProducesManaInstead(
        subject,
        replaced=ast.ANY_OTHER_TYPE,
        produced=produced,
        by_controller=True,
        each_player=each_player,
        replaces_amount=replaces_amount,
    )


def _parse_tapped_lands_produce_chosen(
    stream: TokenStream,
) -> "ast.ProducesManaInstead | None":
    """``<lands> tapped for mana produce mana of the chosen color instead of
    any other color.`` (Hall of Gemstone, behind its leading "Until end of
    turn,".)

    The **passive** voice of the swap the two productions above read, and its
    own production for their own reason: the three sentences share no word
    after their first, because each puts a different thing in the subject slot.
    Here it is the lands themselves, and nobody is named as the tapper at all —
    which is what makes the swap cover every seat.

    The colour is not printed. It is the one an earlier sentence of the same
    ability had a player choose, so the node carries the *reference* and the
    handler reads the record — the same channel "add one mana of the chosen
    color" already travels.

    Refuses without consuming, like both productions above it: a noun phrase in
    the subject slot is what every ordinary sentence in the pool opens with.
    """
    mark = stream.mark()
    try:
        subject = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if subject is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("tapped", "for", "mana"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("produce", "mana", "of", "the", "chosen", "color"):
        stream.reset(mark)
        return None
    # "instead of any other **color**" where the active-voice spellings print
    # "type". Both ends are read for that production's reason: a reader that
    # stopped at "instead of" would compile a swap of one unnamed symbol. And
    # the word is *kept*: "color" replaces only the coloured mana a land makes
    # (CR 106.1a/106.1b — five colors, six types), where "type" replaces all.
    if not stream.accept_phrase("instead", "of", "any", "other", "color"):
        stream.reset(mark)
        return None
    return ast.ProducesManaInstead(
        subject,
        replaced=ast.ANY_OTHER_COLOR,
        produced="",
        from_chosen_color=True,
        by_controller=True,
        each_player=True,
    )

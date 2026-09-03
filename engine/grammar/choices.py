"""``Choose <something>.`` and the sentence that binds what it chose.

Three productions and one rule between them: a "choose" sentence performs
nothing on its own, so it parses **only** when the sentence that reads the
choice follows. A card whose one instruction chose a target and then did
nothing would report itself supported and do nothing at all, which is the
failure this grammar refuses loudly everywhere else.

Split out of `delayed` at the thousand-line guard, along the boundary that
module's own docstring already drew: it explained at length why "Choose target
<noun>." *lived* there — "for the same reason" a delayed trigger does — and a
shared reason is not a shared subject. What is left in `delayed` reads a
sentence that arranges for something later; what is here reads a sentence whose
own content is a **choice**, and the probe for the sentence that reads it back
is the whole of the work in all three.

The recursion arrives as a parameter for `delayed`'s reason: a binder probe
parses a whole statement, and `parse_statement` is the roof one layer up.

Below `delayed`, from which it takes the delayed-trigger production its own
probe asks — and which never imports it back.
"""

from __future__ import annotations

import dataclasses

from . import ast
from .delayed import _parse_create_delayed_trigger
from .effects.characteristics import _parse_keywords
from .effects.prevention import _parse_bound_targeting_prevention
from .errors import GrammarError
from .phrases import BASIC_LAND_WORDS, _parse_duration
from .references import parse_recipient, parse_target_spec
from .stream import TokenStream
from .vocabulary import LAND_TYPES, TYPE_LINE_SUPERTYPES


def _accept_targeted_player(stream: TokenStream) -> "ast.PlayerRef | None":
    """``target opponent`` / ``target player`` at the cursor, or None.

    Through ``parse_recipient``, so the printed references this admits are the
    ones every other player-targeting sentence admits — and the ``target``
    quantifier is what CR 115.1b requires: an untargeted "choose a player" is a
    *resolution* choice and reading one as the other would raise a picker for a
    decision the card makes later.
    """
    mark = stream.mark()
    try:
        chosen = parse_recipient(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if isinstance(chosen, ast.PlayerRef) and chosen.kind in (
        "target_player", "target_opponent"
    ):
        return chosen
    stream.reset(mark)
    return None


def _names_that_player(stream: TokenStream) -> bool:
    """Whether the rest of the line says "that player" anywhere.

    A token scan rather than a parse, and that is the honest shape of the
    question: the binder for a chosen *player* may be several sentences away
    (Soldevi Sentry regenerates in between), and it is a pronoun rather than a
    production — nothing about the sentence that names it is fixed. Without the
    check the production would claim any "choose target player" and leave a
    picker attached to an effect that never reads the answer.
    """
    words = [str(token.text).lower() for token in stream.tokens[stream.pos:]]
    return any(
        first == "that" and second == "player"
        for first, second in zip(words, words[1:])
    )


def _parse_choose_target(stream: TokenStream, parse_statement) -> "ast.ChooseTarget | None":
    """``Choose target creature.`` — a sentence whose whole content is
    CR 601.2c's choosing of targets (Reincarnation, Glyph of Life).

    **It is only a sentence when the next one binds what it chose.** A spell
    whose only instruction chose a target and then did nothing would report
    itself supported while doing nothing at all, which is the failure this
    engine refuses loudly everywhere else. So the following sentence is parsed
    as a probe and the tokens handed straight back: if it is not a delayed
    triggered ability about "that <noun>", this production declines and the
    line fails on whatever it really says.
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        stream.reset(mark)
        return None
    # "Choose **target opponent**." (Soldevi Sentry.) The player form, read
    # first because `parse_target_spec` is about objects and would refuse the
    # noun. Its binder test is different too, and deliberately weaker: the
    # sentence that names the chosen seat is not the next one — the Sentry
    # regenerates in between — so what is asked is whether *anything later on
    # this line* says "that player". That is still the question the object form
    # asks (does a later sentence bind this choice?), just answered over the
    # rest of the line rather than over one sentence, because a player cannot
    # be bound by a delayed ability's opener the way an object can.
    player = _accept_targeted_player(stream)
    if player is not None:
        after_player = stream.mark()
        if not stream.accept_punct("."):
            stream.reset(mark)
            return None
        binds = _names_that_player(stream)
        # The sentence boundary goes back, exactly as the object form's
        # `reset(after_filter)` does: the loop in `parser.py` is what consumes
        # it, and a production that ate it leaves the cursor mid-sentence where
        # that loop's own "unconsumed text" guard fires.
        stream.reset(after_player)
        if not binds:
            stream.reset(mark)
            return None
        return ast.ChooseTarget(player)
    # Through `parse_target_spec` rather than "target" plus a noun phrase, so
    # the counted spelling — "Choose **X target** attacking creatures"
    # (Winter's Chill) — is the same production with the same quantifier
    # machinery every other counted target phrase in the grammar uses. The word
    # "target" is still required (the `targeted` check below): CR 115.1b makes
    # an untargeted "choose" a *resolution* choice, and reading one as the other
    # would raise a cast-time picker for a decision the card makes later.
    try:
        chosen = parse_target_spec(stream)
    except GrammarError:
        # "Choose **one or more** —" (Sublime Epiphany) opens with the same
        # word and a quantifier this reader half-recognizes; the modal head is
        # a different production, so the refusal is handed straight back rather
        # than becoming this one's.
        stream.reset(mark)
        return None
    if chosen is None or not chosen.targeted:
        stream.reset(mark)
        return None
    after_filter = stream.mark()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    delayed = _parse_create_delayed_trigger(stream, parse_statement)
    binds = delayed is not None and delayed.binds_target
    if not binds:
        # …or a shield the following sentence hangs on what was chosen
        # (Silhouette). The probe asks the same question either way — does the
        # next sentence bind this choice — and a second binder is a second
        # answer to it, not a second production of this one.
        binds = _parse_bound_targeting_prevention(stream) is not None
    if not binds:
        # …or a loop over the set this sentence just named — "**For each of
        # those creatures,** its controller may pay …" (Winter's Chill). The
        # third answer to the one question, and the only one a *several*-target
        # choice can give: a set of creatures is bound by a sentence that
        # repeats over it, not by one that says "that creature".
        binds = bool(stream.accept_phrase("for", "each", "of", "those"))
    if not binds:
        # …or one of two more answers, both read off the *parsed* next
        # sentence rather than off its opening words. Dwarven Sea Clan prints
        # the delay **after** the effect ("This creature deals 2 damage to that
        # creature **at end of combat**"), which ``statements.parse_statement``
        # reads through its own trailing-delay clause (Hazezon Tamar's) and the
        # openers above do not. Retribution names **one member** of the set this
        # sentence just chose ("That player chooses and sacrifices **one of
        # those creatures**"). A loop announces itself in four tokens and
        # neither of these does, so the probe has to be the statement itself.
        #
        # Parsed **once** and asked both questions. Two probes over one sentence
        # would parse it twice and, worse, the second would start from wherever
        # the first left the cursor — which is how two independently correct
        # binder probes become one that reads the wrong sentence.
        probe = stream.mark()
        try:
            following = parse_statement(stream, top_level=True)
        except GrammarError:
            following = None
        stream.reset(probe)
        binds = bool(
            (
                isinstance(following, ast.CreateDelayedTrigger)
                and following.binds_target
            )
            or (following is not None and _names_a_chosen_member(following))
        )
    stream.reset(after_filter)
    if not binds:
        stream.reset(mark)
        return None
    return ast.ChooseTarget(chosen)


def _parse_choose_then_gain(stream: TokenStream) -> "ast.GainKeyword | None":
    """``Choose <A>, <B>, or <C>. <subject> gains that ability <duration>.``
    (Gabriel Angelfire)
    ``Choose a basic land type. <subject> gains landwalk of the chosen type
    <duration>.`` (Giant Slug)

    Two sentences, one effect, and it is the *second* one that says what the
    choice was for — which is why this is a fusion rather than two productions.
    A "choose" sentence alone performs nothing and would report a card
    supported while doing nothing at all; that is the same reason
    :func:`_parse_choose_target` lives in this module rather than beside the
    effects it precedes.

    Both spellings lower to the ``choose_one`` the *one*-sentence form already
    produces ("gains your choice of flying, first strike, trample, or rampage 3
    until end of turn"), so nothing downstream learns a second shape. The two
    differ only in what the options are made of: printed keywords, or the five
    basic land types turned into landwalks by the binding sentence. That is why
    the domain and the binding phrase are read as a pair — "choose a basic land
    type" followed by anything but "landwalk of the chosen type" is a card this
    does not read, and declining leaves whatever refusal the line already had.
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        stream.reset(mark)
        return None
    # "a **basic** land type" (Giant Slug) and "a land type" (Illusionary
    # Presence) are the same sentence over two domains, and the difference is
    # exactly CR 205.3i's: five types the rules fix, against every land subtype
    # printed. So the domain is read off the words rather than assumed — reading
    # the wider phrase as the narrower one would offer five options where the
    # card offers eighteen, and the vocabulary catalog is where the wider answer
    # already lives.
    land_choice = bool(stream.accept_phrase("a", "basic", "land", "type"))
    any_land_choice = not land_choice and bool(
        stream.accept_phrase("a", "land", "type")
    )
    if land_choice or any_land_choice:
        options: tuple[str, ...] = (
            BASIC_LAND_WORDS if land_choice else tuple(sorted(LAND_TYPES))
        )
    else:
        try:
            options = _parse_keywords(stream)
        except GrammarError:
            stream.reset(mark)
            return None
        # A single option is not a choice. "Choose flying." with a binding
        # sentence behind it is a wording no card prints, and admitting it
        # would put a one-option prompt in front of the player.
        if len(options) < 2:
            stream.reset(mark)
            return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    # ``parse_recipient`` rather than ``parse_target_spec``: both cards name
    # the source, and one of them does it by printing its own name — which the
    # lexer has collapsed into a SELF token that only this reader knows.
    subject = parse_recipient(stream)
    if not isinstance(subject, ast.TargetSpec) or not stream.accept_word("gains", "gain"):
        stream.reset(mark)
        return None
    if land_choice or any_land_choice:
        # "**snow** landwalk of the chosen type" (Barbarian Guides). CR 702.14a
        # lets a landwalk's type be "the card type land plus any combination of
        # land types, card types, and/or supertypes", and `engine/landwalk.py`
        # already reads a supertype sitting in front of the family word — so the
        # printed qualifier is payload here rather than a second production.
        qualifier = ""
        prefix_mark = stream.mark()
        word = stream.peek_word()
        if word is not None and word in TYPE_LINE_SUPERTYPES:
            stream.advance()
            qualifier = f"{word} "
        if not stream.accept_phrase("landwalk", "of", "the", "chosen", "type"):
            stream.reset(prefix_mark)
            stream.reset(mark)
            return None
        # CR 702.14a spells the family as "[type]walk", so the chosen type and
        # the granted ability are the same word carrying a suffix — payload,
        # never five productions.
        keywords = tuple(f"{qualifier}{option}walk" for option in options)
    else:
        if not stream.accept_phrase("that", "ability"):
            stream.reset(mark)
            return None
        keywords = options
    return ast.GainKeyword(
        subject, keywords, _parse_duration(stream), choose_one=True
    )


def _names_a_chosen_member(node) -> bool:
    """Whether *node* names one member of a set an earlier sentence chose.

    A walk over the dataclass rather than a check on the top-level statement,
    for :func:`_names_a_bound_object`'s reason: the reference can be nested
    inside an offer, a sequence or a toll, and a statement class added later is
    covered by default instead of silently answering False.
    """
    if isinstance(node, ast.TargetSpec) and node.quantifier == "one_of_those":
        return True
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        return any(
            _names_a_chosen_member(getattr(node, field.name))
            for field in dataclasses.fields(node)
        )
    if isinstance(node, (tuple, list)):
        return any(_names_a_chosen_member(item) for item in node)
    return False

"""``Choose <something>.`` and the sentence that binds what it chose.

Four productions and one rule between them: a "choose" sentence performs
nothing on its own, so it parses **only** when the sentence that reads the
choice follows. A card whose one instruction chose a target and then did
nothing would report itself supported and do nothing at all, which is the
failure this grammar refuses loudly everywhere else.

The fourth (Goblin Welder's) is the strongest reading of that rule rather than
an exception to it: its two chosen objects sit in **different zones**, so
neither sentence alone says what the card does to which, and the pair is one
production or nothing.

Split out of `delayed` at the thousand-line guard, along the boundary that
module's own docstring already drew: it explained at length why "Choose target
<noun>." *lived* there — "for the same reason" a delayed trigger does — and a
shared reason is not a shared subject. What is left in `delayed` reads a
sentence that arranges for something later; what is here reads a sentence whose
own content is a **choice**, and the probe for the sentence that reads it back
is the whole of the work in all four.

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
from .durations import _parse_duration
from .phrases import BASIC_LAND_WORDS
from .nouns import parse_object_filter
from .references import _parse_further_subjects, parse_recipient, parse_target_spec
from .seat_comparisons import accept_player_comparison
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


def _names_the_chosen_cards(stream: TokenStream) -> bool:
    """Whether the rest of the line says "the chosen card(s)" anywhere.

    :func:`_names_that_player`'s twin one zone over, and it is a token scan for
    that function's reason: Victimize's binder is not the next sentence but the
    one after it ("Sacrifice a creature. **If you do**, return the chosen cards
    …"), and what binds is a definite noun phrase rather than a production. A
    probe over one sentence would answer no and the whole line would refuse.

    A *card* rather than a permanent, deliberately: what "the chosen cards"
    names is the announcement over a graveyard, and a sentence saying "the
    chosen creature" is about something on a battlefield that this production
    never picked.
    """
    words = [str(token.text).lower() for token in stream.tokens[stream.pos:]]
    return any(
        first == "the" and second == "chosen" and third in ("card", "cards")
        for first, second, third in zip(words, words[1:], words[2:])
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
    #
    # **And a narrowed choice needs no binder at all.** The rule this whole
    # module states is that a "choose" sentence must not be the only thing a
    # card does, because a target chosen and never read is an instruction that
    # performs nothing. A *comparison* clause is the counter-example and the
    # reason the test is a question rather than a rule: "Choose target opponent
    # who controls more creatures than you do" performs the whole of what those
    # three Keepers print, by refusing the activation when no seat answers
    # (CR 601.2c) and by countering it when the seat stops answering
    # (CR 608.2b). Keeper of the Beasts never says "that player" again and is
    # not a card that does nothing.
    player = _accept_targeted_player(stream)
    if player is not None:
        # "Choose target opponent **who has more life than you do**" (the
        # Exodus Keepers). A printed restriction on which seats may be chosen,
        # read here beside the noun it hangs on and carried to the picker,
        # which is the only reader that can enforce it (CR 601.2c/602.2b).
        comparison = accept_player_comparison(stream, parse_object_filter)
        if comparison is not None:
            player = dataclasses.replace(player, compared=comparison)
        # "…**as you activate this ability**." (the Keepers again.) CR 602.2b
        # already says an activated ability's targets are chosen as it is
        # activated, so these words restate the rule rather than adding one —
        # and the engine enforces exactly that, through
        # `legality.activation_target_refusal` before any cost is paid. Read
        # rather than left, because a production must consume every token of
        # its line; consumed only *after* a comparison, so a sentence that
        # printed the words alone is still nobody's.
        if comparison is not None:
            stream.accept_phrase("as", "you", "activate", "this", "ability")
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
        if not binds and comparison is None:
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
        # …or a later sentence naming what was chosen by its noun phrase —
        # "Sacrifice a creature. If you do, return **the chosen cards** to the
        # battlefield tapped." (Victimize.) The binder is two sentences away and
        # is not a production at all, so the question is asked over the rest of
        # the line exactly as the player arm asks its own.
        binds = _names_the_chosen_cards(stream)
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



#: The printed rider that makes CR 608.2b **all-or-nothing** for one ability.
#:
#: The default rule removes an ability from the stack only when *every* one of
#: its targets has become illegal; an ability printing this sentence does
#: nothing unless *both* are still legal. So it is strictly stronger than the
#: rule, and a production that read it and dropped it would leave the engine
#: resolving the half the card forbids — an artifact sacrificed for a card that
#: never comes back, which is silent and in the player's favour.
_BOTH_TARGETS_STILL_LEGAL = (
    "if", "both", "targets", "are", "still", "legal",
    "as", "this", "ability", "resolves",
)


def _accept_the_named_object(stream: TokenStream, spec: "ast.TargetSpec") -> bool:
    """``the <printed noun of *spec*>`` at the cursor.

    The back-reference half of a two-sentence announcement: the second sentence
    names each chosen object by the noun the first sentence chose it with, and
    this is what holds the two together. Compared by the *parsed* noun phrase
    rather than by the raw words, so "the artifact card" and "the artifact" are
    told apart by the same reader that told "target artifact card" from "target
    artifact" one sentence earlier — a word-level match would let a card whose
    second sentence names the wrong one of its two targets compile as though it
    named the right one.

    Only the type half is compared. A slot's *other* narrowings ("a player
    controls", "in that player's graveyard") describe how it was chosen and are
    not reprinted on the back-reference.
    """
    mark = stream.mark()
    if not stream.accept_word("the"):
        stream.reset(mark)
        return False
    try:
        named = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    wanted = spec.filter
    if (
        named.card_types == wanted.card_types
        and named.subtypes == wanted.subtypes
        and named.is_card == wanted.is_card
    ):
        return True
    stream.reset(mark)
    return False


def _parse_choose_then_swap(
    stream: TokenStream,
) -> "ast.SacrificeAndReturnTargets | None":
    """``Choose target <A> and target <B>. [If both targets are still legal as
    this ability resolves,] that player simultaneously sacrifices the <A> and
    returns the <B> to the battlefield.`` (Goblin Welder.)

    A fusion for `_parse_choose_then_gain`'s reason and one more. The first
    sentence performs nothing on its own — it is CR 601.2c's choosing — and the
    second names both objects back by their printed nouns, so neither sentence
    can be read alone. The extra reason is the pair of *zones*: one target is a
    permanent and the other a card in a graveyard, and which is which is said
    by the first sentence and acted on by the second.

    The two slots are held to the shape the sentence behind them can mean: the
    first is a battlefield permanent narrowed by the indefinite seat ("a player
    controls"), the second a **card** in the graveyard of that same seat. That
    is the binding "that player" points back at, and it is checked here rather
    than assumed, because a production that accepted any two targets would read
    "…in **your** graveyard" as though it said "theirs".
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        stream.reset(mark)
        return None
    try:
        first = parse_target_spec(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if first is None or not first.targeted or first.count != 1:
        stream.reset(mark)
        return None
    # "…**and** target artifact card in that player's graveyard" — the same
    # union reader every other several-target sentence uses, so the second slot
    # is parsed by the machinery that already knows what "target" means rather
    # than by a second reading of the word.
    further = _parse_further_subjects(stream, first, several_targets=True)
    if len(further) != 1:
        stream.reset(mark)
        return None
    second = further[0]
    if (
        not isinstance(second, ast.TargetSpec)
        or not second.targeted
        or second.count != 1
    ):
        stream.reset(mark)
        return None
    if first.filter.controller != "any_player" or first.filter.is_card:
        stream.reset(mark)
        return None
    owner = second.filter.zone_owner
    if (
        not second.filter.is_card
        or second.filter.zone != "graveyard"
        # "that player's graveyard", which `accept_zone_possessive` spells
        # ``owner`` — its own comment says the two are one node. The seat is the
        # one the first slot's "a player controls" bound, which is the whole
        # dependency between the two slots.
        or owner is None
        or owner.kind != "owner"
    ):
        stream.reset(mark)
        return None
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    must_all_be_legal = bool(stream.accept_phrase(*_BOTH_TARGETS_STILL_LEGAL))
    if must_all_be_legal:
        stream.accept_punct(",")
    actor = parse_recipient(stream)
    if not isinstance(actor, ast.PlayerRef) or actor.kind != "that_player":
        stream.reset(mark)
        return None
    # CR 608.2's steps happen in the order written unless a card says
    # otherwise, and this one says otherwise: the sacrifice and the return are
    # **one** event, so the artifact going to the graveyard is not a card the
    # return could have been aimed at and nothing sees the board in between.
    # Required, not optional: without the word the sentence is two ordinary
    # steps and a different card.
    if not stream.accept_word("simultaneously"):
        stream.reset(mark)
        return None
    if not stream.accept_word("sacrifices"):
        stream.reset(mark)
        return None
    if not _accept_the_named_object(stream, first):
        stream.reset(mark)
        return None
    if not stream.accept_word("and") or not stream.accept_word("returns"):
        stream.reset(mark)
        return None
    if not _accept_the_named_object(stream, second):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("to", "the", "battlefield"):
        stream.reset(mark)
        return None
    return ast.SacrificeAndReturnTargets(
        sacrificed=first,
        returned=second,
        actor=actor,
        must_all_be_legal=must_all_be_legal,
    )


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

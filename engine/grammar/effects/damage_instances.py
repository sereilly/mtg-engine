"""CR 615.8: the next **instance** of damage from a source the sentence names.

"The next time a black or red source of your choice would deal damage to you
this turn, prevent that damage." (Greater Realm of Preservation, and every
Circle of Protection.) "…, that damage is dealt to target creature of an
opponent's choice instead." (Nova Pentacle.) "The next time this creature would
deal combat damage to an opponent this turn, it deals that damage to another
creature instead." (Soltari Guerrillas.) And Desperate Gambit's pair — "Choose
a source you control", then "The next time that source would deal damage this
turn, it deals double that damage instead."

Split out of ``effects/prevention.py`` at Exodus' Phase 0, when that module sat
ten lines under the 1,000-line guard with two of wave 1's groups about to land
productions in it. **The CR draws the line and the engine already turns on
it**: a CR 615.7 shield is a pool spent by *points* and "count[s] only the
amount of damage; the number of events or sources dealing it doesn't matter",
where everything here modifies "the next instance of damage from that source,
regardless of how much damage that is". ``lowering/_blankets.py`` had already
written that sentence down — "a pool (CR 615.7) is spent by points and a
CR 615.8 shield by instances" — because ``engine/prevention.py``'s order bands
depend on it. What stays behind names the **recipient**; everything here names
the **source**, and its recipient is optional (Penance prints none at all).

``_parse_source_of_choice_effect`` returning *either* node is what kept this
half out of ``effects/redirection.py``, and that is unchanged rather than
overruled: the whole production moved, so no module holds half of it, and this
one carries both endings for the same reason it always did — CR 615.8's opening
words are a way of *naming* the damage, and the clause after the comma decides
whether it is prevented or moved. There is no import between this module and
``prevention``, ``redirection`` or ``damage_locks`` in either direction.

**Parse-only, and the mirror says why.** All six productions lower in
``lowering/prevention.py`` and ``lowering/redirection.py``, a few lines from the
shields', because CR 615.8's elaboration is in the *words*: a Circle of
Protection and Reverse Damage lower to one shield instruction apiece however
many ways the sentence spells its source. A near-empty
``lowering/damage_instances.py`` would buy back the symmetry and cost the thing
symmetry is for — ``search``, ``reveal``, ``text_changes`` and ``damage_locks``
beside it record the same shape.
"""

from .. import ast
from ..references import parse_recipient
from ..errors import GrammarError
from ..readers import _parse_keyword_list
from ..prevented_riders import _parse_prevented_this_way_rider
from ..stream import TokenStream
from ..vocabulary import CARD_TYPES, COLOR_WORDS
from ..durations import _parse_duration
from ..phrases import _parse_opponents_choice


def _accept_redirect_tail(
    stream: TokenStream,
) -> "tuple[ast.Recipient, ast.PlayerRef | None] | None":
    """``, that damage is dealt to <recipient> instead`` — or the same clause in
    the active voice, ``, it deals that damage to <recipient> instead``.

    Nova Pentacle prints the passive and Soltari Guerrillas the active, and they
    are one clause: "it" is the source the sentence in front of the comma
    already named, so the two spellings differ in nothing a reader downstream
    could act on. One production for that reason — two would be two readings of
    one printed idea, and the round that added a rider to one of them would
    leave the other card without it.

    Once either opening phrase is consumed the production is **committed**: what
    follows is a redirection or the line is unreadable, so the rest raises
    rather than rewinding. A rewind here would hand the words to whatever reads
    "prevent…" next, which is the shield this sentence is not.
    """
    if not (
        stream.accept_phrase("that", "damage", "is", "dealt", "to")
        or stream.accept_phrase("it", "deals", "that", "damage", "to")
    ):
        return None
    new_recipient = parse_recipient(stream)
    if new_recipient is None:
        raise stream.error("expected who takes the redirected damage")
    chooser, new_recipient = _parse_opponents_choice(stream, new_recipient)
    if not stream.accept_word("instead"):
        raise stream.error("expected 'instead' to end a redirection effect")
    return new_recipient, chooser


def _finish_named_source_effect(
    stream: TokenStream, source: "ast.TargetSpec", mark, combat_only: bool
) -> "ast.PreventDamage | ast.RedirectDamage | None":
    """The tail of "The next time <named source> would deal [combat] damage to
    <recipient> <duration>, …" — either "prevent that damage" (Mercenaries) or
    "it deals that damage to <recipient> instead" (Soltari Guerrillas).

    Split out because the sibling branch reads seven more words before reaching
    the same clause; keeping the tail in one function is what stops the two from
    drifting into two readings of one sentence.

    Both endings, for the reason the chosen-source branch reads both: CR 615.8's
    "the next time <source> would deal damage" is a way of *naming* the damage,
    and the clause after the comma is what happens to it. The halving is still
    absent — no card prints it of a named source — and refusing it names that
    rather than lowering it onto a shield that answers to the wrong object.
    """
    recipient = parse_recipient(stream)
    if recipient is None:
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    stream.accept_punct(",")
    if _accept_reflexive_redirect_tail(stream, source):
        # "…, that creature deals that damage **to itself** instead." (Shield
        # Dancer.) The damage goes back onto the object that would have dealt
        # it — a recipient no node names, so it is a flag on the redirect.
        return ast.RedirectDamage(
            to=recipient,
            dealt_by=source,
            duration=duration,
            one_shot=True,
            combat_only=combat_only,
            to_damage_source=True,
        )
    tail = _accept_redirect_tail(stream)
    if tail is not None:
        new_recipient, chooser = tail
        # The source is carried whole rather than as its filter: a redirect
        # records *which object's* damage moves, and the quantifier is how the
        # lowering tells "this creature" from a source the sentence chose.
        return ast.RedirectDamage(
            to=recipient,
            new_recipient=new_recipient,
            dealt_by=source,
            duration=duration,
            one_shot=True,
            chooser=chooser,
            combat_only=combat_only,
        )
    # The shield ending is the ability's own source only: ``PreventDamage``
    # carries the source as a *filter*, and a targeted source reduced to its
    # filter would be a shield against every creature the noun phrase
    # describes rather than the one announced.
    if not source.filter.is_source or not stream.accept_phrase(
        "prevent", "that", "damage"
    ):
        stream.reset(mark)
        return None
    return ast.PreventDamage(
        ast.Fixed(1), to=recipient, from_filter=source.filter, duration=duration,
        combat_only=combat_only,
    )


def _accept_reflexive_redirect_tail(
    stream: TokenStream, source: "ast.TargetSpec"
) -> bool:
    """``that <noun> deals that damage to itself instead`` — or ``it deals …``.

    The active-voice tail ``_accept_redirect_tail`` reads, with the damage's
    own source as the new recipient. Read here rather than through
    ``parse_recipient``, which reads a bare "itself" as the *ability's* source
    (Psionic Entity's "…and 3 damage to itself") — right there, and wrong
    when the sentence's subject is a creature the ability targeted: "that
    creature … itself" is the attacker, not the Shield Dancer.

    "That <noun>" must name the source's own card type, or the back-reference
    is to something this sentence did not name. Refuses without consuming.
    """
    mark = stream.mark()
    if stream.accept_word("that"):
        noun = stream.peek_word()
        if noun is None or noun not in source.filter.card_types:
            stream.reset(mark)
            return False
        stream.advance()
    elif not stream.accept_word("it"):
        return False
    if stream.accept_phrase(
        "deals", "that", "damage", "to", "itself", "instead"
    ):
        return True
    stream.reset(mark)
    return False


def _parse_source_of_choice_effect(
    stream: TokenStream,
) -> "ast.PreventDamage | ast.RedirectDamage | None":
    """"The next time a <colour> source of your choice would deal damage to you
    this turn, **prevent that damage**." — the Circles of Protection, and
    Reverse Damage with no colour word.

    …or "…, **that damage is dealt to target creature of an opponent's choice
    instead**" (Nova Pentacle). One production, because everything up to the
    comma is the same printed sentence: CR 615.8's "a source of your choice" is
    a way of *naming* the damage, and what the card then does with it — prevent
    it, or move it — is the clause after. Splitting them would be two
    productions racing on the same seven words, and the second would only ever
    be reached by the first rewinding.

    A whole-instance shield, not a numeric one; the amount is fixed at 1 because
    the handler counts shields, not damage.
    """
    mark = stream.mark()
    # "a red source" / "an artifact source" — the article follows the noun's
    # first letter, so both are accepted here rather than assuming "a".
    if not stream.accept_phrase("the", "next", "time"):
        stream.reset(mark)
        return None
    colours: list[str] = []
    card_type = None
    if not (stream.accept_word("a") or stream.accept_word("an")):
        # "The next time **this creature** would deal damage to you this turn,
        # prevent that damage." (Mercenaries.) The same CR 615.8 sentence with
        # the source *named* instead of chosen — a branch of this production
        # rather than one of its own, because everything from "would deal
        # damage to" onward is the identical clause and two productions racing
        # on "the next time" would differ only in how the second rewinds.
        named = parse_recipient(stream)
        # "The next time **target attacking creature** would deal combat
        # damage to this creature this turn, …" (Shield Dancer.) The source
        # named by announcement rather than by self-reference: one target, the
        # same clause after it. ``_finish_named_source_effect`` refuses the
        # shield ending for it, which carries a source as a filter only.
        announced = (
            isinstance(named, ast.TargetSpec)
            and named.quantifier == "target"
            and named.targeted
            and named.count == 1
        )
        if (
            not isinstance(named, ast.TargetSpec)
            or not (named.filter.is_source or announced)
            or not stream.accept_phrase("would", "deal")
        ):
            stream.reset(mark)
            return None
        # "…would deal **combat** damage to an opponent this turn" (Soltari
        # Guerrillas). CR 510.2's narrowing, read here rather than skipped for
        # the reason every blanket shield in this file reads its own: the word
        # is the whole difference between a record that catches an unblocked
        # attacker's ping ability and one that does not, and a dropped
        # narrowing is a record wider than the card prints. It is carried, not
        # honoured — the shield lowering refuses it, and one redirect lowering
        # implements it.
        combat_only = bool(stream.accept_word("combat"))
        if not stream.accept_phrase("damage", "to"):
            stream.reset(mark)
            return None
        return _finish_named_source_effect(stream, named, mark, combat_only)
    token = stream.peek()
    word = str(token.text).lower() if token is not None else ""
    if word in COLOR_WORDS:
        # "a **black or red** source of your choice" (Greater Realm of
        # Preservation). A list rather than one word, because the printed
        # sentence records one property with several admissible values — one
        # shield the next matching source spends, not one shield per colour.
        # Read as a loop rather than as a two-colour special case: a card
        # printing three needs no code.
        colours.append(COLOR_WORDS[word])
        stream.advance()
        while stream.accept_word("or"):
            token = stream.peek()
            word = str(token.text).lower() if token is not None else ""
            if word not in COLOR_WORDS:
                stream.reset(mark)
                return None
            colours.append(COLOR_WORDS[word])
            stream.advance()
    elif word in CARD_TYPES:
        # "an **artifact** source of your choice" (Circle of Protection:
        # Artifacts). The same Circle keyed on a card type instead of a colour
        # — CR 615.9 rechecks whichever property the shield recorded, so the
        # two are one production with two narrowings rather than two effects.
        card_type = word
        stream.advance()
    # "an artifact **source** of your choice" (Circle of Protection: Artifacts)
    # and "a **creature** of your choice with shadow" (Circle of Protection:
    # Shadow) are the same clause with the head noun spelled two ways. CR 615.8
    # says "a source of your choice", and a card naming a card type is naming a
    # source of that type — so the word is optional exactly where the type
    # supplies it, and required where nothing else does (a bare "a of your
    # choice" is not a sentence).
    if not stream.accept_word("source") and card_type is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("of", "your", "choice"):
        stream.reset(mark)
        return None
    # "a creature of your choice **with shadow**" (Circle of Protection:
    # Shadow). A postmodifier on the head noun, printed *after* "of your
    # choice" rather than before the noun the way a colour or a card type is —
    # which is why it is read here and not in the adjective run above. It is a
    # third narrowing axis beside those two, and CR 615.9 rechecks it at damage
    # time exactly as it rechecks them (a creature that has since lost shadow no
    # longer matches).
    #
    # Read by ``_parse_keyword_list`` — the one reader every other "with
    # <keyword>" postmodifier in the grammar goes through — rather than a
    # keyword word of this production's own, so "with shadow and flying" is
    # the same phrase here as it is anywhere else and no second keyword
    # vocabulary can drift from it.
    keywords: tuple[str, ...] = ()
    keyword_mark = stream.mark()
    if stream.accept_word("with"):
        try:
            keywords = _parse_keyword_list(stream)
        except GrammarError:
            stream.reset(keyword_mark)
        else:
            if card_type is None:
                # "a source of your choice with shadow" names no object the
                # keyword could be tested on — a spell reaches the damage paths
                # as its printed CardDefinition, which has no layers — so the
                # phrase refuses rather than arming a shield that answers to
                # nothing.
                raise stream.error("a keyword-narrowed shield needs the object type")
    # "a source of your choice **of the chosen color**" (Prismatic Circle). The
    # same Circle narrowing read one branch above, with the colour deferred to
    # what the permanent recorded as it entered (CR 614.1c) instead of printed
    # in the sentence — so it is read here, after "of your choice", because
    # that is where this card prints it and the branch above reads a colour
    # *word*, which "the chosen color" is not.
    #
    # Refused alongside a printed colour rather than folded in: "a red source
    # of your choice of the chosen color" names two properties, and a shield
    # records one (CR 615.9 rechecks *the* recorded property).
    chosen_color = bool(stream.accept_phrase("of", "the", "chosen", "color"))
    if chosen_color and (colours or card_type):
        raise stream.error("a shield records one source property, not two")
    if not stream.accept_phrase("would", "deal", "damage"):
        stream.reset(mark)
        return None
    # "The next time a source of your choice would deal damage **this turn**,
    # that damage is dealt to that source's controller instead." (Reflect
    # Damage.) The one printing of this sentence that names no recipient at
    # all: it moves whatever the chosen source deals, to whoever it would have
    # damaged. So the "to <recipient>" clause is optional here — and its
    # absence is a *fact about the card*, carried through as ``to=None``, which
    # is the same value Reverberation's sentence already produces one
    # production over.
    recipient = None
    if stream.accept_word("to"):
        recipient = parse_recipient(stream)
        if recipient is None:
            stream.reset(mark)
            return None
    # "…would deal damage to **you and/or creatures you control** this turn"
    # (Shadowbane). One shield over several recipients, joined by the printed
    # "and/or" — CR 615.1's shield goes around whatever the effect is affecting,
    # and here that is a player *and* a described set. The loop backtracks, so
    # an "and" that introduces something else is left for whatever follows.
    others: list[ast.Recipient] = []
    while True:
        conjunct = stream.mark()
        if not (stream.accept_phrase("and", "or") or stream.accept_word("and")):
            break
        further = parse_recipient(stream)
        if further is None:
            stream.reset(conjunct)
            break
        others.append(further)
    duration = _parse_duration(stream)
    stream.accept_punct(",")
    tail = _accept_redirect_tail(stream)
    if tail is not None:
        # Nova Pentacle. The damage is *moved*, so this leaves with a
        # RedirectDamage: nothing about it is a shield, and the one thing the
        # two share is how the source was named.
        new_recipient, chooser = tail
        return ast.RedirectDamage(
            to=recipient,
            new_recipient=new_recipient,
            from_chosen_source=True,
            duration=duration,
            one_shot=True,
            chooser=chooser,
        )
    if recipient is None and not (colours or card_type or chosen_color):
        # A shield naming **neither** a recipient nor a property of the source
        # would answer to the next damage anything deals to anybody, which is a
        # card nobody has printed and the widest reading of every sentence this
        # production reads. Rewound rather than raised, so the line keeps
        # whatever refusal it had.
        #
        # A recipient on its own is no longer required, and CR 615.8 is why: the
        # rule defines this shield by "the next time a specific **source** would
        # deal damage", with no recipient in it at all. "The next time a black
        # or red source of your choice would deal damage this turn, prevent that
        # damage." (Penance) is that sentence printed without one, and it
        # prevents that source's next damage to whoever it was headed for.
        # Every Circle of Protection prints "to you", which is what made the
        # recipient look like part of the shape.
        stream.reset(mark)
        return None
    # "…, prevent **half** that damage, rounded down." (Dark Sphere.) The same
    # sentence, absorbing a share of the event instead of all of it — so it is
    # a branch of this production rather than a second one racing it over the
    # same seven opening words. The rounding is read rather than assumed:
    # `amounts.parse_amount` defaults a bare `Half` to "down", so an unread
    # "rounded up" would prevent one point less than the card says.
    half_mark = stream.mark()
    if stream.accept_phrase("prevent", "half", "that", "damage"):
        rounding = "down"
        stream.accept_punct(",")
        if stream.accept_word("rounded"):
            if stream.accept_word("up"):
                rounding = "up"
            elif not stream.accept_word("down"):
                raise stream.error("expected 'up' or 'down' after 'rounded'")
        if colours or card_type or chosen_color or keywords:
            # A shield that records a property *and* halves is a card nobody has
            # printed; refusing names the gap rather than dropping one half.
            raise stream.error("no shield both narrows its source and halves")
        return ast.PreventDamage(
            ast.Half(ast.ThatMuch(None), rounding),
            to=recipient,
            from_filter=ast.ObjectFilter(),
        )
    stream.reset(half_mark)
    if not stream.accept_phrase("prevent", "that", "damage"):
        stream.reset(mark)
        return None
    # "…prevent that damage. **You gain life equal to the damage prevented this
    # way.**" (Reverse Damage.) CR 615.5's additional effect, read as part of
    # this sentence — see :func:`_parse_prevented_this_way_rider`.
    rider = _parse_prevented_this_way_rider(stream)
    if colours:
        filt = ast.ObjectFilter(colors=tuple(colours))
    elif card_type:
        filt = ast.ObjectFilter(card_types=(card_type,), with_keywords=keywords)
    elif chosen_color:
        # Not a member of ``colors``: the colour is not in the sentence at all,
        # and folding it in would need a sentinel every ``colors`` reader would
        # then have to know about — the argument ``ObjectFilter.chosen_color``
        # already carries for the noun-phrase side.
        filt = ast.ObjectFilter(chosen_color=True)
    else:
        filt = ast.ObjectFilter()
    return ast.PreventDamage(
        ast.Fixed(1), to=recipient, from_filter=filt, prevented_rider=rider,
        to_others=tuple(others),
    )


def _names_a_next_time_clause(stream: TokenStream) -> bool:
    """Whether the rest of the line still has a "the next time …" sentence in it.

    The binder probe :func:`_parse_choose_damage_source` needs, and a token scan
    rather than a parse for the reason ``choices._names_that_player`` gives about
    its own: what reads the choice back may be several sentences away — Desperate
    Gambit flips a coin in between — and only the *presence* of the reader is
    being asked about.
    """
    words = [str(token.text).lower() for token in stream.tokens[stream.pos:]]
    return any(
        first == "next" and second == "time"
        for first, second in zip(words, words[1:])
    )


def _parse_choose_damage_source(stream: TokenStream) -> "ast.ChooseDamageSource | None":
    """``Choose a source you control`` (Desperate Gambit) — CR 609.7's source of
    damage, picked as the spell resolves.

    **Only when a later sentence reads it back.** A sentence whose whole content
    is a choice performs nothing, and a card that chose something and then did
    nothing would report itself supported while doing nothing at all — the rule
    ``grammar/choices.py`` exists to enforce, applied here because the binder is
    a damage clause rather than a delayed trigger. So the rest of the line has to
    contain the "the next time …" sentence that names the choice, and without one
    this declines and the line keeps whatever refusal it had.

    The noun phrase goes through ``parse_recipient``, so "you control" narrows
    exactly as it narrows anywhere else — but the head word is checked first,
    because a filter cannot say afterwards which noun it was built from and
    "choose a creature you control" is a different sentence with no reader here.

    Untargeted on purpose (CR 601.2c announced nothing), which is why this is not
    ``ChooseTarget``: the pick is made on resolution and belongs to
    ``choose_permanent``'s prompt, not to a cast-time picker.
    """
    mark = stream.mark()
    if not stream.accept_word("choose"):
        return None
    if stream.peek_word() not in ("a", "an") or stream.peek_word(1) != "source":
        stream.reset(mark)
        return None
    try:
        chosen = parse_recipient(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not isinstance(chosen, ast.TargetSpec) or chosen.targeted:
        stream.reset(mark)
        return None
    if not _names_a_next_time_clause(stream):
        stream.reset(mark)
        return None
    return ast.ChooseDamageSource(chosen.filter)


def _parse_chosen_source_next_damage(
    stream: TokenStream,
) -> "ast.ChosenSourceNextDamage | None":
    """``The next time that source would deal damage this turn, it deals double
    that damage instead.`` / ``…, prevent that damage.`` (Desperate Gambit.)

    :func:`_parse_source_of_choice_effect`'s sentence with the source named by a
    back-reference instead of chosen inside it, and with **no recipient at all** —
    the two together are why it is a production of its own rather than a branch
    of that one. That production requires an article ("a <colour> source of your
    choice") or a printed source, so it refuses this line without consuming and
    hands it here unchanged.

    Both pronouns are read, and they mean the same object: the card says "that
    source" in the first branch and "it" in the second because the antecedent has
    already been established. Nothing here decides *which* object that is — the
    lowering refuses unless a step in front of it really recorded one, which is
    the same producer gate every other back-reference in this grammar passes.

    Every word of the tail is required. "Double" is the whole of the winning
    branch and "prevent" the whole of the losing one, so a reader that stopped at
    "that damage" would leave one of the two doing the other's job.
    """
    mark = stream.mark()
    if not stream.accept_phrase("the", "next", "time"):
        return None
    if not (stream.accept_phrase("that", "source") or stream.accept_word("it")):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("would", "deal", "damage"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    stream.accept_punct(",")
    for printed, modification in (
        (("it", "deals", "double", "that", "damage", "instead"), "double"),
        (("prevent", "that", "damage"), "prevent"),
    ):
        if stream.accept_phrase(*printed):
            return ast.ChosenSourceNextDamage(modification, duration)
    stream.reset(mark)
    return None

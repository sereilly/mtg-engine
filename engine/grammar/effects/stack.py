"""The stack: countering spells, copying them, choosing modes, and what
declining a cost costs.

Counterspell's production, the two copy-a-spell templates (CR 707.10), the modal
head ("Choose one —") every modal spell and ability is announced with, the closed
list of penalties a card imposes on a player who declines an "unless they pay"
cost, and the activation restrictions ("activate only during your upkeep") that
gate an ability.

The copy productions arrived here from ``subject_verb`` when that module crossed
the thousand-line guard, and the move is the family rule rather than the nearest
free space: neither of them reads a subject and a verb — they read a whole
printed sentence about **an object on the stack**, which is this module's
subject and nobody else's.
"""

from .. import ast
from ..lexer import DASH, WORD
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream
from ..phrases import (_accept_mana_alternatives, _parse_counted_sacrifice,
                       _parse_mana_payment, _parse_zone)
from ..vocabulary import NUMBER_WORDS


def _parse_unless_pays(stream: TokenStream) -> "ast.ManaCost | None":
    """``unless <the object's controller> pays <cost>``, or None if absent.

    One reader for a spell's clause and an ability's, because it is the same
    clause: the cost is offered to the *countered object's* controller while
    that object waits on the stack (CR 118.3c). Only that player has a payment
    flow, so a third party named here refuses the line rather than being
    silently read as the controller.
    """
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None:
        raise stream.error("expected who pays after 'unless'")
    if payer.kind not in ("controller", "that_player"):
        # "that player" is admitted beside "its controller" because in a
        # trigger they name the same person by construction: the condition is
        # "whenever **a player** casts a spell", so the player it bound is the
        # spell's controller. What is refused is a *third* party.
        raise stream.error(
            "only the countered object's controller can pay to avoid a counter"
        )
    stream.expect_word("pays", "pay")
    return _parse_mana_payment(stream, allow_variable=True)


def _parse_counter(stream: TokenStream) -> ast.Statement:
    """``counter <spell> [unless <player> pays <cost>]``.

    The "unless" clause is part of the counter, not a wrapper around it: the
    cost is offered to the *targeted spell's* controller while that spell waits
    on the stack (CR 118.3c). Reading it as a `Conditional` would put the
    decision on the wrong player and the counter in the wrong place.
    """
    stream.expect_word("counter")
    subject = parse_target_spec(stream)
    if subject is not None and subject.filter.ability_kinds:
        # "counter target activated or triggered ability" (Sublime Epiphany).
        # Its own node: CR 701.5a removes the object from the stack either way,
        # but a spell's card goes to a graveyard and an ability has no card to
        # send anywhere, so one handler cannot do both without asking which it
        # has — and asking is the branch this avoids.
        #
        # The "unless" clause is read here rather than shared with the spell
        # branch below because the spell branch's own trailers ("instead",
        # "that spell") are about a *spell* that an earlier sentence named, and
        # none of them can follow an ability.
        return ast.CounterAbility(subject, unless_pays=_parse_unless_pays(stream))
    if subject is None:
        # "**Counter that ability.**" (Imprison.) The ability the trigger's own
        # condition was about, not one this sentence chose — so it is the bound
        # quantifier, exactly as "that spell" below is, and it reaches
        # `CounterAbility` rather than the spell node because an ability has no
        # card to send to a graveyard (CR 113.7a).
        #
        # Read here rather than through `parse_target_spec`, which would have to
        # admit "ability" as a noun phrase a matcher could test; it is not one,
        # and `references.parse_player_ref` already keeps the word out of
        # `_GENERIC_NOUNS` for that reason.
        bound_ability = stream.mark()
        if stream.accept_phrase("that", "ability"):
            return ast.CounterAbility(
                ast.TargetSpec("that", ast.ObjectFilter()),
                unless_pays=_parse_unless_pays(stream),
            )
        stream.reset(bound_ability)
        # "counter **that spell**" (Lofty Denial's second sentence, Invoke
        # Prejudice's trigger) — a spell something already named, not a second
        # choice. Its own quantifier for the reason round 75's "those creatures"
        # has one: a bound reference and a chosen one reach different machinery,
        # and every lowering refuses "that" unless it says otherwise, so a
        # sentence that reaches one fails by name rather than failing to parse.
        #
        # **What named it is not this phrase's business.** The words used to set
        # `replaces_prior_amount` here, which read "that spell" as "the spell an
        # earlier *sentence* targeted" and made Lofty Denial's construction the
        # only one the two words could belong to. Invoke Prejudice prints them
        # about the spell its own trigger condition bound, with no earlier
        # sentence at all — so the replacement is now read off the word that
        # actually says it, "instead", and "that spell" means what "it" beside
        # it means.
        if stream.accept_phrase("that", "spell"):
            subject = ast.TargetSpec("that", ast.ObjectFilter())
        elif stream.accept_word("it"):
            # "Whenever a player casts a spell, **counter it**." (Nether Void,
            # Presence of the Master, In the Eye of Chaos.) The pronoun is
            # bound by the trigger's own condition, not chosen — so it is its
            # own quantifier, for the reason "that spell" beside it has one.
            #
            # A stand-alone spell line reading "Counter it." would be a card
            # with nothing to refer to, and there is none; the handler answers
            # by reading the trigger's event, and an absent event resolves
            # having countered nothing rather than reaching for the stack top.
            subject = ast.TargetSpec("it", ast.ObjectFilter())
        else:
            raise stream.error("expected a spell to counter")

    # "…**if it would destroy a land you control**" (Equinox). Read before the
    # "unless … pays" clause because a card can print only one of them and this
    # one starts with a word that clause never does; the sentence is handed to
    # `engine/counter_conditions.py`, which is the code that answers it, so a
    # condition nothing implements leaves the line refused rather than consumed
    # and dropped — a dropped condition here is a counter that fires on every
    # spell.
    condition_mark = stream.mark()
    if stream.accept_word("if"):
        from ...counter_conditions import counter_condition_readable

        words: list[str] = []
        while not stream.exhausted and not stream.at_punct("."):
            words.append(str(stream.next().text))
        sentence = " ".join(words).replace(" '", "'")
        if counter_condition_readable(sentence):
            return ast.CounterSpell(subject, only_if=sentence)
    stream.reset(condition_mark)

    # "…**unless you sacrifice a land**" (Mana Vortex). The counter's twin of
    # the destroy and sacrifice tails in the `board` family, decomposed to the
    # same `May(action=…, otherwise=…)` for the same reason: an "unless" is an
    # offer with a penalty, and saying it that way means the offer, the penalty
    # and the "you have no land to give" case all come from machinery that
    # already works — where `_parse_unless_pays` below is the *countered*
    # object's controller paying mana, which is the counter flow's own job.
    #
    # Read before that clause because both open with "unless", and it raises on
    # a payer it does not admit rather than refusing quietly — so "you" would
    # fail the whole line naming the wrong reason.
    sacrifice_mark = stream.mark()
    if stream.accept_phrase("unless", "you", "sacrifice"):
        payer = ast.PlayerRef("you")
        return ast.May(
            actor=payer,
            action=_parse_counted_sacrifice(stream, payer),
            otherwise=ast.CounterSpell(subject),
        )
    stream.reset(sacrifice_mark)

    payment = _parse_unless_pays(stream)
    if payment is not None:
        # "…pays {4} **instead**" (Lofty Denial). The word is the whole
        # difference between a second counter and a replacement amount for the
        # first, so it is what sets the flag. Refused on the chosen form:
        # "counter target spell unless its controller pays {4} instead"
        # replaces an amount no sentence before it named.
        replaces_prior = stream.accept_word("instead")
        if replaces_prior and subject.quantifier not in ("that", "it"):
            raise stream.error(
                "'instead' replaces an amount an earlier sentence named"
            )

        return ast.CounterSpell(
            subject, unless_pays=payment,
            # "…pays {B} **or {3}**" (Thrull Wizard). Read here rather than
            # before "instead" above because the two clauses are about
            # different things: "instead" replaces an amount an earlier
            # sentence named, and this offers a second way to cover *this* one.
            unless_pays_alternatives=_accept_mana_alternatives(stream),
            replaces_prior_amount=replaces_prior,
        )

    # "**If that spell is countered this way, put it on top of its owner's
    # library instead of into that player's graveyard.**" (Memory Lapse.) Read
    # here, after every other clause has refused, because a card printing this
    # tail *and* an "unless … pays" would be a shape no flow performs — the
    # counter that never happens has no card to redirect — and refusing the
    # whole line is this grammar's answer to a shape it cannot honour.
    zone, position = _parse_countered_destination(stream)
    if zone is not None:
        return ast.CounterSpell(
            subject, countered_to=zone, countered_to_position=position
        )
    return ast.CounterSpell(subject)


def _parse_countered_destination(
    stream: TokenStream,
) -> "tuple[ast.Zone | None, str]":
    """``If that spell is countered this way, put it <zone> instead of into
    that player's graveyard.`` (Memory Lapse; Remand's zone is the hand.)

    CR 614.1's replacement of CR 701.5a's destination, and a *tail of the
    counter* rather than the next statement: "that spell" is the one the
    sentence before it countered, so parsed apart this sentence names an object
    no earlier step handed it. The interior full stop is consumed here for the
    same reason the search's conditional-shuffle sentence consumes its own —
    left to the sequence parser it would be a statement no production
    implements and the whole line would refuse.

    Non-consuming when the tail is not there, and **loud** once its opening
    seven words have matched: a line that says "countered this way" and then
    something this cannot read is a card whose destination would otherwise be
    silently the graveyard, which is the counter it already was.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None, ""
    if not stream.accept_phrase(
        "if", "that", "spell", "is", "countered", "this", "way"
    ):
        stream.reset(mark)
        return None, ""
    stream.accept_punct(",")
    # "…**exile it** instead of putting it into its owner's graveyard."
    # (Dissipate.) The same CR 614.1 replacement of CR 701.5a's destination
    # written with the destination as a *verb* rather than as a zone — which is
    # how Magic prints exile and only exile, because "put it into exile" is not
    # a sentence the game uses. One branch rather than a second production: the
    # tail it shares with Memory Lapse is the whole rest of the clause, and a
    # second production would be a second place the "instead of" half could be
    # forgotten.
    if stream.accept_phrase("exile", "it"):
        _expect_replaced_graveyard(stream)
        return ast.Zone("exile"), ""
    stream.expect_word("put")
    stream.expect_word("it")
    position = ""
    if stream.accept_word("on"):
        # "on top of" / "on the bottom of" — one zone, two places in it, which
        # is the pair the library seam takes rather than two destinations.
        stream.accept_word("the")
        if stream.accept_word("top"):
            position = "top"
        elif stream.accept_word("bottom"):
            position = "bottom"
        else:
            raise stream.error("expected 'top' or 'bottom' of the library")
        stream.expect_word("of")
    elif not stream.accept_word("into"):
        raise stream.error("expected where a countered spell goes instead")
    zone = _parse_zone(stream)
    _expect_replaced_graveyard(stream)
    return zone, position


def _expect_replaced_graveyard(stream: TokenStream) -> None:
    """Consume the "instead of … graveyard" half, in either printed spelling.

    **Required, not skipped.** Without it the sentence would be an
    unconditional move of a card that is already somewhere else, and the word
    "instead" is the whole of what makes this a replacement (CR 614.1) rather
    than a second effect.

    Two spellings, because the two verbs take different grammar: Memory Lapse's
    "put it on top of its owner's library **instead of into that player's
    graveyard**" and Dissipate's "exile it **instead of putting it into its
    owner's graveyard**". They name one destination — CR 404.3's owner's
    graveyard, which "that player" refers back to — so they are one clause read
    two ways rather than two clauses.
    """
    stream.expect_word("instead")
    stream.expect_word("of")
    if stream.accept_phrase("putting", "it"):
        stream.expect_word("into")
        for word in ("its", "owner", "'s", "graveyard"):
            stream.expect_word(word)
        return
    for word in ("into", "that", "player", "'s", "graveyard"):
        stream.expect_word(word)


def _parse_change_target(stream: TokenStream) -> "ast.ChangeTarget | None":
    """``Change the target of target spell with a single target [if that target
    is <player>].`` (Reflecting Mirror; Deflection and Divert print the first
    sentence without the "if".)

    CR 115.7a. Returns None **without consuming** when the sentence is one of
    the other two "Change the …" templates — "change the text of" (Magical
    Hack) and "change the base power and toughness of" (Halfdane) open on the
    same two words — so those keep the refusals they have today.

    Two things are required past the verb, and both are the full-consumption
    invariant rather than fussiness:

    * the printed head noun must be **spell**. A bare "spell" is a generic noun
      that leaves no mark on the filter at all (only a *typed* phrase — "target
      instant or sorcery spell" — records ``zone="stack"``), so without this
      guard the word could be deleted with no change to the parse and "target
      permanent with a single target" would reach the same lowering. That is
      the dropped-rider shape, arriving through a word that describes the
      *zone* rather than a rider.
    * "if that target is <player>" is read here rather than left to the
      sentence loop's trailing-``if`` fold, because it is not a condition about
      the board: it asks what the *other* object announced, which no
      ``Condition`` in this grammar can describe, and the picker has to be able
      to ask it before the ability is activated at all.
    """
    mark = stream.mark()
    if not stream.accept_phrase("change", "the", "target", "of"):
        stream.reset(mark)
        return None
    if not (stream.at_word("target") and stream.peek_word(1) == "spell"):
        stream.reset(mark)
        return None
    subject = parse_target_spec(stream)
    if subject is None:
        raise stream.error("expected the spell whose target to change")
    current = None
    if stream.accept_phrase("if", "that", "target", "is"):
        current = parse_player_ref(stream)
        if current is None:
            raise stream.error("expected who that target has to be")
    return ast.ChangeTarget(subject, current_target=current)


# The words that can count modes. `NUMBER_WORDS` minus the articles: "Choose a
# card name other than a basic land card name." (Necromentia) opens with the
# same two tokens as a modal head, and reading "a" as the count would put the
# head production in front of every "choose a <noun>" line in the pool.
_MODE_COUNT_WORDS = frozenset(NUMBER_WORDS) - {"a", "an"}


def _parse_modal_head(stream: TokenStream) -> ast.ModalNode | None:
    """``Choose one —`` / ``Choose two —`` / ``Choose one or more —``.

    The head of a modal spell or ability (CR 700.2). Returns the node, or None
    when the clause is not a modal head at all — which is the whole reason this
    reads as a *quiet* refusal rather than an error. Every other "choose …"
    sentence in the pool ("Choose a card name…", "you choose a noncreature card
    from it") is a different effect, and raising here would replace their real
    backlog reasons with this one.

    Two things are checked past the count, and both are the full-consumption
    invariant rather than fussiness:

    * **The clause ends here.** A modal head is the whole clause — the modes are
      the bulleted lines below it, which are separate lines to this parser. So
      anything after the dash means this is not the sentence it looks like, and
      the head is refused rather than claimed with a tail dropped.
    * **The dash is optional but the end is not.** The lexer only emits `DASH`
      for an em or en dash; a printing with a plain hyphen loses it entirely
      (the token table has no rule for a bare "-"), so requiring the dash would
      make an invisible character decide whether a card is modal.

    The count is carried, not assumed. ``choose_count`` and ``at_least`` are
    what the lowering refuses on — the substring test this replaces matched
    "choose one" inside "Choose one or more" and built a one-mode spell from a
    card that chooses several.
    """
    mark = stream.mark()
    # "**An opponent** chooses one —" (Fatal Lore, Library of Lat-Nam,
    # Misfortune). CR 700.2e's head: a player other than the controller picks
    # the mode, and does it when the controller normally would (CR 601.2b, as
    # the spell is cast). Read here rather than as a subject-verb sentence
    # because it is the *same* head with its chooser printed — the bullets
    # below it are the modes either way, and a second production would be a
    # second answer to "how many of the lines below does somebody take?".
    chooser: "ast.PlayerRef | None" = None
    if not stream.at_word("choose"):
        chooser = parse_player_ref(stream)
        if chooser is None or not stream.accept_word("chooses"):
            stream.reset(mark)
            return None
    elif not stream.accept_word("choose"):
        return None
    token = stream.peek()
    if token is None or token.kind != WORD or token.text not in _MODE_COUNT_WORDS:
        stream.reset(mark)
        return None
    stream.advance()
    count = NUMBER_WORDS[token.text]

    at_least = bool(stream.accept_phrase("or", "more"))
    stream.accept_kind(DASH)
    stream.accept_punct(".")
    # "…: Choose one. **Activate only if there are two or more hatchling
    # counters on this artifact.**" (Triassic Egg.) The trailing sentence
    # belongs to the *ability*, not to the head, and it is read through the same
    # reader every other activated line reads it through — so a restriction
    # nothing implements still refuses the line.
    #
    # Without this the head failed the end-of-clause check below and the card's
    # whole modal ability was unread: Triassic Egg reported supported on its
    # counter-adding line while the ability players actually want did nothing.
    _parse_activation_restriction(stream)
    if not stream.exhausted:
        stream.reset(mark)
        return None
    return ast.ModalNode(count, at_least, chooser=chooser)


# What a card does to the player who declines an "unless … pays" cost, matched
# as one literal shape per penalty. Deliberately not parsed compositionally:
# the sentence is not a step of the spell — the counter flow performs it while
# countering — so the grammar's only job is to say *which* penalty was written
# and account for the tokens. A penalty not listed here fails to match, the
# line fails full-token consumption, and the card falls back rather than
# compiling with a rider nothing performs.
_UNPAID_PENALTIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "tap_lands_and_empty_pool",
        (
            "they", "tap", "all", "lands", "with", "mana", "abilities", "they",
            "control", "and", "lose", "all", "unspent", "mana",
        ),
    ),
)


def _parse_unpaid_penalty_sentence(stream: TokenStream) -> str | None:
    """"If that player doesn't, <penalty>." — the declined branch of an
    "unless … pays" cost, as a penalty name."""
    mark = stream.mark()
    if not (
        stream.accept_phrase("if", "that", "player", "doesn't")
        or stream.accept_phrase("if", "that", "player", "does", "not")
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    for name, phrase in _UNPAID_PENALTIES:
        if stream.accept_phrase(*phrase):
            return name
    stream.reset(mark)
    return None


def _parse_cost_x_definition(stream: TokenStream) -> ast.ActivationRestriction | None:
    """A trailing "X is the number of pin counters on this artifact." sentence
    (Voodoo Doll) — what the ability's **cost** X is, when the card says.

    The same arrangement as :func:`_parse_activation_restriction` below, for the
    same reason: the sentence belongs to the ability rather than to the effect,
    and what enforces it is the activation path, which reads the raw text. The
    grammar's job is to account for the tokens — and, through
    ``engine/cost_x_definitions.py``, to refuse a definition nothing computes.

    Refusing is the whole point of asking that module rather than matching "x
    is" here: an unimplemented definition consumed silently would leave the
    activator announcing X freely on a cost the card fixes, which on a {X}{X}
    ability is free.
    """
    from ...cost_x_definitions import cost_x_definition_readable

    mark = stream.mark()
    stream.accept_punct(".", ";")
    if not stream.at_word("x") or stream.peek_word(1) != "is":
        stream.reset(mark)
        return None
    words: list[str] = []
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    sentence = " ".join(words).replace(" '", "'")
    if not cost_x_definition_readable(sentence):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    return ast.ActivationRestriction(sentence)


def _parse_activation_restriction(stream: TokenStream) -> ast.ActivationRestriction | None:
    """A trailing "Activate only …" / "Any player may activate this ability."
    sentence on an activated ability.

    Recorded on the AST and lowered to nothing. The restriction is *enforced*
    from the raw ability text in ``mixins/stack/activation.py``, which reads
    ``ability.source_line`` -- so consuming the sentence here drops no behaviour,
    it only lets the line satisfy the grammar's full-consumption invariant.

    "Drops no behaviour" is true **only of a clause something enforces**, which
    is why both branches below ask the module that enforces theirs. The
    permission branch already did; the "Activate ..." branch consumed the rest
    of the sentence verbatim and asked nothing, so Vampire Bats' "Activate no
    more than twice each turn" satisfied the invariant against a table with no
    row for it -- the card compiled supported with an uncapped {B} pump. A
    clause `engine/activation_restrictions.py` cannot read now leaves the line
    refused, and the card reports unsupported naming the sentence.
    """
    from ...activation_permissions import permission_clause_readable
    from ...activation_restrictions import (activation_restriction_line,
                                            x_zero_restriction_line)

    mark = stream.mark()
    stream.accept_punct(".", ";")
    words: list[str] = []
    # "X can't be 0." (Aladdin's Lamp, Helm of Obedience.) A constraint on the
    # value chosen for X (CR 601.2b) rather than on when the ability may be
    # activated, so it opens on a different word and is enforced by a different
    # gate — but it is the same *kind* of sentence, a rider on the ability line
    # whose enforcement lives outside the compiled program, and it is admitted
    # here on the same terms: the module that enforces it says whether it can
    # read the sentence, and a wording that module cannot read leaves the line
    # refused.
    if stream.at_word("x"):
        x_mark = stream.mark()
        probe: list[str] = []
        while not stream.exhausted and not stream.at_punct("."):
            probe.append(str(stream.next().text))
        sentence = " ".join(probe).replace(" '", "'")
        if x_zero_restriction_line(sentence):
            stream.accept_punct(".")
            return ast.ActivationRestriction(sentence)
        stream.reset(x_mark)
        stream.reset(mark)
        return None
    if stream.accept_word("activate"):
        words.append("activate")
    elif stream.at_word("any", "only"):
        # A "who may activate" permission (CR 602.1a). The spellings used to be
        # listed here as literal token sequences -- a fourth copy of a table
        # `engine/activation_permissions.py` now holds -- so a permission the
        # engine could not enforce still consumed its line and the card was
        # admitted with the clause dropped. The sentence is read verbatim and
        # handed to that module, which is the code that enforces it: a shape it
        # does not implement leaves the line refused.
        probe_words: list[str] = []
        while not stream.exhausted and not stream.at_punct("."):
            probe_words.append(str(stream.next().text))
        sentence = " ".join(probe_words).replace(" '", "'")
        if not permission_clause_readable(sentence):
            stream.reset(mark)
            return None
        stream.accept_punct(".")
        return ast.ActivationRestriction(sentence)
    else:
        stream.reset(mark)
        return None
    # Consume the remainder of the sentence verbatim; the enforcing code reads
    # the original text, so the grammar only has to account for the tokens --
    # but only once that code has said it can read the sentence at all.
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    sentence = " ".join(words).replace(" '", "'")
    if not activation_restriction_line(sentence):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    return ast.ActivationRestriction(sentence)


def _parse_copy_that_spell(stream: TokenStream) -> ast.Statement:
    """``Copy that spell. You may choose new targets for the copy.``

    Both sentences, every word. The second is CR 707.10's choice and part of
    what the card does; consuming it is also what stops this production
    claiming a bare "copy that spell" no card prints.
    """
    for word in ("copy", "that", "spell"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the new-targets sentence after the copy")
    for word in (
        "you", "may", "choose", "new", "targets", "for", "the", "copy",
    ):
        stream.expect_word(word)
    return ast.CopyThatSpell()


def _parse_copy_this_spell(stream: TokenStream) -> ast.Statement | None:
    """``Copy this spell[.| and] [you] may choose [a] new target[s] for
    [that|the] copy.`` (Chain Lightning.)

    "This spell" is the one resolving, so the copy is made from
    ``Game.resolving_items[-1]`` rather than from the stack — see
    :class:`ast.CopySpell`. The re-aiming clause is consumed here in either
    printed spelling, and *recorded*: a copy that could not be re-aimed is a
    smaller card, and the deletion probe is right to call a dropped rider a bug.

    Refuses without consuming, so a "Copy that spell" line still reaches the
    production behind this one.
    """
    mark = stream.mark()
    if not stream.accept_phrase("copy", "this", "spell"):
        stream.reset(mark)
        return None
    # "…and may choose a new target for that copy" (Chain Lightning) and
    # "… . You may choose new targets for the copy" (the modern template) are
    # the same offer printed two ways. Both are read; neither is optional,
    # because a bare "copy this spell" is not a line any card prints and
    # claiming it would let a card with an unread rider report itself supported.
    retarget = False
    if stream.accept_word("and"):
        stream.accept_word("you")
        retarget = stream.accept_word("may") and stream.accept_word("choose")
    elif stream.accept_punct(".") and stream.accept_phrase("you", "may"):
        retarget = stream.accept_word("choose")
    if not retarget:
        stream.reset(mark)
        return None
    stream.accept_word("a")
    if not (stream.accept_word("new") and stream.accept_word("target")
            or stream.accept_word("targets")):
        stream.reset(mark)
        return None
    stream.accept_word("targets")
    if not stream.accept_word("for"):
        stream.reset(mark)
        return None
    if not (stream.accept_word("that") or stream.accept_word("the")):
        stream.reset(mark)
        return None
    if not stream.accept_word("copy"):
        stream.reset(mark)
        return None
    return ast.CopySpell(ast.PlayerRef("you"), may_choose_new_target=True)


def _parse_can_be_targeted_as_though(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.WaiveShroud | None":
    """``can be the target of spells and abilities controlled by <player> as
    though it didn't have shroud`` — the permission clause, without its subject.

    Autumn Willow. CR 609.4's "as though" cutting a hole in CR 702.18 for one
    seat, and the twin of ``phrases._parse_can_attack_as_though`` one rule
    over: both are permissions that lift a restriction and change nothing else.

    Every word after "can" is required literally, and that is the production
    rather than a shortcoming of it. The three that could vary do not vary
    across any card, and each names a different mechanism if it did: "spells
    and abilities" is both kinds because CR 115.1a and CR 115.1c/d make them
    separately targeted and a card naming one of them is a narrower effect;
    and "shroud" is the one keyword whose restriction
    ``permanent_state._can_be_targeted`` lifts through this record — hexproof
    is already seat-relative and protection asks about the source's qualities,
    so neither would be this rule with a word changed. What *does* vary is the
    player, which is why that is the field.

    Non-consuming on refusal, so every other "can …" sentence keeps the reading
    it has today.
    """
    mark = stream.mark()
    if not stream.accept_phrase("can", "be", "the", "target", "of"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("spells", "and", "abilities", "controlled", "by"):
        stream.reset(mark)
        return None
    player = parse_player_ref(stream)
    if player is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "as", "though", "it", "didn't", "have", "shroud"
    ):
        stream.reset(mark)
        return None
    return ast.WaiveShroud(player)

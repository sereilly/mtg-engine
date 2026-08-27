"""The stack: countering spells, choosing modes, and what declining a cost costs.

Counterspell's production, the modal head ("Choose one —") every modal spell and
ability is announced with, the closed list of penalties a card imposes on a
player who declines an "unless they pay" cost, and the activation restrictions
("activate only during your upkeep") that gate an ability.
"""

from .. import ast
from ..lexer import DASH, WORD
from ..references import parse_player_ref, parse_target_spec
from ..stream import TokenStream
from ..phrases import _parse_mana_payment
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
            subject, unless_pays=payment, replaces_prior_amount=replaces_prior
        )

    return ast.CounterSpell(subject)


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
    if not stream.accept_word("choose"):
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
    return ast.ModalNode(count, at_least)


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
    ``ability.source_line`` — so consuming the sentence here drops no behaviour,
    it only lets the line satisfy the grammar's full-consumption invariant
    instead of failing and sending the whole ability back to the legacy rules.
    """
    from ...activation_permissions import permission_clause_readable

    mark = stream.mark()
    stream.accept_punct(".", ";")
    words: list[str] = []
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
    # the original text, so the grammar only has to account for the tokens.
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    stream.accept_punct(".")
    return ast.ActivationRestriction(" ".join(words))

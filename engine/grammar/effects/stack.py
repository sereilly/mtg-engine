"""The stack: countering spells, choosing modes, and what declining a cost costs.

Counterspell's production, the modal head ("Choose one —") every modal spell and
ability is announced with, the closed list of penalties a card imposes on a
player who declines an "unless they pay" cost, and the activation restrictions
("activate only during your upkeep") that gate an ability.
"""

from .. import ast
from ..lexer import DASH, WORD
from ..nouns import (parse_player_ref, parse_target_spec)
from ..stream import TokenStream
from ..phrases import _parse_mana_payment
from ..vocabulary import NUMBER_WORDS


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
        return ast.CounterAbility(subject)
    replaces_prior = False
    if subject is None:
        # "counter **that spell**" (Lofty Denial's second sentence) — the spell
        # the sentence before it already targeted, not a second choice. Its own
        # quantifier for the reason round 75's "those creatures" has one: a
        # bound reference and a chosen one reach different machinery, and every
        # lowering refuses "that" unless it says otherwise, so a sentence that
        # reaches one fails by name rather than failing to parse.
        if stream.accept_phrase("that", "spell"):
            subject = ast.TargetSpec("that", ast.ObjectFilter())
            replaces_prior = True
        else:
            raise stream.error("expected a spell to counter")

    if stream.accept_word("unless"):
        payer = parse_player_ref(stream)
        if payer is None:
            raise stream.error("expected who pays after 'unless'")
        if payer.kind != "controller":
            # Only the countered spell's own controller has a payment flow.
            # Anyone else paying is a different effect, so refuse instead of
            # dropping the distinction.
            raise stream.error("only the spell's controller can pay to avoid a counter")
        stream.expect_word("pays", "pay")
        payment = _parse_mana_payment(stream, allow_variable=True)
        # "…pays {4} **instead**". Required on the bound form and refused on the
        # chosen one: "counter target spell unless its controller pays {4}
        # instead" replaces an amount no sentence before it named.
        if stream.accept_word("instead"):
            if not replaces_prior:
                raise stream.error(
                    "'instead' replaces an amount an earlier sentence named"
                )
        elif replaces_prior:
            raise stream.error(
                "a counter of the spell already targeted must say what it replaces"
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


def _parse_activation_restriction(stream: TokenStream) -> ast.ActivationRestriction | None:
    """A trailing "Activate only …" / "Any player may activate this ability."
    sentence on an activated ability.

    Recorded on the AST and lowered to nothing. The restriction is *enforced*
    from the raw ability text in ``mixins/stack/activation.py``, which reads
    ``ability.source_line`` — so consuming the sentence here drops no behaviour,
    it only lets the line satisfy the grammar's full-consumption invariant
    instead of failing and sending the whole ability back to the legacy rules.
    """
    mark = stream.mark()
    stream.accept_punct(".", ";")
    words: list[str] = []
    if stream.accept_word("activate"):
        words.append("activate")
    elif stream.accept_phrase("any", "player", "may", "activate"):
        words.extend(["any", "player", "may", "activate"])
    elif stream.accept_phrase("only", "this", "creature", "'s", "owner", "may", "activate"):
        words.extend(["only", "this", "creature", "'s", "owner", "may", "activate"])
    else:
        stream.reset(mark)
        return None
    # Consume the remainder of the sentence verbatim; the enforcing code reads
    # the original text, so the grammar only has to account for the tokens.
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    stream.accept_punct(".")
    return ast.ActivationRestriction(" ".join(words))

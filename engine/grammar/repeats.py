"""``Repeat this process …`` — the sentence that says the sentences before it
happen again.

Three cards print one and **no two of them are the same mechanism**, which is
why they are one module rather than one production:

* "Repeat this process **until no one** puts a card onto the battlefield."
  (Eureka.) A round of offers made to every seat in turn, repeated while
  anybody took it. What ends it is a whole round nobody took, which only the
  thing running the round can see — so the clause folds into the offer and
  lowers to one instruction (``repeat_offer_round``).
* "You may repeat this process **any number of times**." (Forbidden Ritual.)
  One seat's decision, taken again after every round, over a process of
  *several* printed sentences. Nothing about a round decides it and there is no
  bound but the answer, so the clause wraps everything before it and the loop
  ends when its controller says so.
* "Repeat this process **for artifacts and creatures**." (Equipoise.) Not a
  loop at all: a printed *list of parameters*, known when the line is parsed,
  so the round happens exactly three times with one word changed each time.

Fusing them would mean a mechanism that is a round-of-offers, a decision and a
parameter list at once, and each card would reach it through a payload flag
saying which of the three it really is. Building three where they genuinely
share would be the opposite mistake, so what they *do* share sits here: the
attach-to-the-steps-before-it shape (``(stream, steps) -> bool``, the same
contract ``control_flow``'s branch readers use), and the two readers that turn
the rest of a printed sentence back into a statement.

Split out of ``parser`` at the thousand-line guard, along the boundary the
sentence loop already draws: every one of these is a clause *about* the
sentences the loop has already read, not a step beside them. Below ``parser``
and above ``statements``, whose parser two of them re-enter to read a
restatement.
"""

from __future__ import annotations

from . import ast
from .errors import GrammarError
from .lexer import PUNCT, tokenize
from .vocabulary import CARD_TYPES, singular
from .statements import parse_statement
from .stream import TokenStream


def _rest_of_sentence(stream: TokenStream) -> str | None:
    """Consume the tokens up to the next full stop and return their source text.

    The same slice ``_parse_registry_claimed_sentence`` takes, and for a related
    reason: what the words mean is decided by handing them back to a reader,
    not by matching them here.
    """
    start_token = stream.peek()
    if start_token is None:
        return None
    end = start_token.end
    while not stream.exhausted:
        token = stream.peek()
        if token is None or (token.kind == PUNCT and token.text == "."):
            break
        end = token.end
        stream.advance()
    stream.accept_punct(".")
    return stream.line[start_token.start:end]


def _as_imperative(phrase: str) -> str:
    """A restated act in the third person, read back as the act itself.

    "no one **puts** a card onto the battlefield" is the same act as "**put** a
    card onto the battlefield"; the verb tables hold the uninflected spelling,
    so the inflection is undone before they are asked. One rule about English —
    a third-person singular present verb ends in *s* — rather than a table of
    verbs, which would go stale the moment a production learned a new one.
    """
    head, _, tail = phrase.partition(" ")
    if head.endswith("s") and not head.endswith("ss"):
        head = head[:-1]
    return f"{head} {tail}" if tail else head


def _attach_repeat_this_process(stream: TokenStream, steps: list) -> bool:
    """Fold "Repeat this process until no one puts a card onto the battlefield."
    into the offer before it (Eureka).

    "This process" is the sentence before this one — an offer made to every seat
    in turn — so the clause wraps that statement instead of standing beside it
    as a step. Parsed as its own step it would name no process at all.

    The tail is a *restatement* of the offered act, and it is checked rather
    than skipped: it is re-read as a statement of its own and must describe the
    same kind of act as the offer. A card printing a repeat clause about
    something else is a card this reading would repeat the wrong thing for, so
    it rewinds and the line refuses.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.May) or last.action is None:
        return False
    mark = stream.mark()
    if not stream.accept_phrase("repeat", "this", "process", "until"):
        stream.reset(mark)
        return False
    if not (stream.accept_phrase("no", "one") or stream.accept_phrase("no", "player")):
        stream.reset(mark)
        return False
    phrase = _rest_of_sentence(stream)
    if not phrase:
        stream.reset(mark)
        return False
    try:
        imperative = _as_imperative(phrase)
        restated = tokenize(imperative)
        restated_stream = TokenStream(restated.tokens, restated.source)
        restated = parse_statement(restated_stream)
        if not restated_stream.exhausted:
            raise GrammarError("unconsumed text", line=imperative)
    except GrammarError:
        stream.reset(mark)
        return False
    if type(restated) is not type(last.action):
        stream.reset(mark)
        return False
    steps[-1] = ast.RepeatProcess(round=last, restatement=restated)
    return True


def _attach_repeat_for_types(stream: TokenStream, steps: list) -> bool:
    """Fold "Repeat this process for artifacts and creatures." into the
    sentence before it (Equipoise).

    The third printed "repeat" and the only one that decides nothing: the card
    names the remaining parameters, so the process happens a *printed* number of
    further times and each one differs by one word. That is why it wraps the
    step before it rather than every step the line has read — Equipoise's
    process is one sentence, and the two before it on Forbidden Ritual are that
    card's shape rather than the clause's.

    Only card types, and only real ones: the substitution the lowering makes is
    on a printed noun's card type, and a word this cannot resolve would be a
    round repeated for nothing. The vocabulary is
    ``engine/grammar/vocabulary.CARD_TYPES``, the same table the noun parser
    reads, so a type added to the game needs no code here.
    """
    if not steps:
        return False
    mark = stream.mark()
    if not stream.accept_phrase("repeat", "this", "process", "for"):
        stream.reset(mark)
        return False
    types: list[str] = []
    while True:
        word = stream.peek_word()
        if word is None or singular(word) not in CARD_TYPES:
            break
        stream.advance()
        types.append(singular(word))
        if not (stream.accept_word("and") or stream.accept_punct(",")):
            break
    # The clause must **end** its sentence: a word behind it is a card this
    # reading has not read, and repeating a process for a list that carries on
    # into something else is a rewrite of a sentence nobody printed. An
    # exhausted stream ends it as surely as a full stop does — `parse_coverage`
    # asks the same clause with its trailing period already stripped, and a
    # production that needed the punctuation reported the sentence as
    # implemented by nothing.
    if not types or not (stream.accept_punct(".") or stream.exhausted):
        stream.reset(mark)
        return False
    steps[-1] = ast.RepeatForEachType(round=steps[-1], types=tuple(types))
    return True


def _attach_repeat_optional_process(stream: TokenStream, steps: list) -> bool:
    """Fold "You may repeat this process any number of times." into everything
    before it (Forbidden Ritual).

    "This process" is every sentence of the line so far — Forbidden Ritual's is
    two, a sacrifice and the toll it pays for — so this wraps the whole step
    list rather than the last step, which is the one thing that separates it
    from :func:`_attach_repeat_this_process` next door. Eureka's clause names a
    *round of offers* and folds into that one offer; this one names a process
    nobody offered, performed by the spell's own controller, and the repetition
    is the only decision in it.

    "**Any number of times**" is the other difference, and it is why the two
    cannot share a node. Eureka's loop ends on a fact about the round — nobody
    took the offer — which the handler running the round can see for itself.
    This one ends when its controller says so and has no other bound at all, so
    the decision has to be asked between rounds and there is nothing to check it
    against.

    Refuses without consuming when the sentence is not exactly these words, and
    when there is nothing in front of it: a process with no sentences before it
    names nothing, and wrapping an empty list would compile a loop that repeats
    silence.
    """
    if not steps:
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "you", "may", "repeat", "this", "process", "any", "number", "of", "times"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(".")
    round_ = steps[0] if len(steps) == 1 else ast.Sequence(tuple(steps))
    steps[:] = [ast.RepeatOptionalProcess(round=round_)]
    return True

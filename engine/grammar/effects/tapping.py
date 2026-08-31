"""Tapping: the keyword action (CR 701.20) and the untap-step restrictions.

Split from ``board`` at the thousand-line guard, under the name
``lowering/tapping.py`` has carried since the lowering side crossed the same cap
— so one template keeps one home per side and a production moving between
families stays invisible to callers (``effects/__init__`` re-exports flat).

The two productions belong together for a reason beyond size: "tap it" and "it
doesn't untap during its controller's next untap step" are the two halves of
every card that means to keep a permanent down, and Frost Breath, Telekinesis
and Mind Whip all print them in one sentence.
"""

from .. import ast
from ..errors import GrammarError
from ..lexer import PT
from ..phrases import (
    _expect_counter_kind, _parse_mana_payment, parse_bound_subject,
    parse_subject_filter_at,
)
from ..references import parse_player_ref, parse_recipient
from ..stream import TokenStream
from ..vocabulary import NUMBER_WORDS


def _parse_doesnt_untap_next_step(
    stream: TokenStream, subject: ast.Recipient
) -> ast.Statement:
    """``<subject> don't untap during their controller's next untap step.``

    The verb is already at the cursor; the subject was read by the sentence's
    subject position and is passed in.

    Every word of the duration is consumed literally, and two of them are the
    production's whole safety:

    * **"next"** is required. Drop it and the sentence is "…don't untap during
      their controller's untap step", which is the *permanent* restriction
      ``engine/auras.py`` derives for Paralyze and Capture Sphere — a strictly
      larger effect. Refusing the wording without "next" is what makes the
      deletion probe's rider check pass honestly rather than by accident.
    * **"their/its controller's"** is required, and "your" is refused. They are
      different effects: this one is per-creature, and "your next untap step"
      (exert's wording, CR 701.43a) is the *controller of the effect's* step,
      which the marker this lowers to carries no seat to express.
    """
    stream.expect_word("don't", "doesn't")
    stream.expect_word("untap")
    stream.expect_word("during")
    stream.expect_word("their", "its")
    stream.expect_word("controller")
    stream.expect_word("'s")
    # "…untap step **for as long as this creature remains tapped**" (Phyrexian
    # Gremlins). No "next": the restriction is continuous and ends when the
    # source untaps, which is a different effect from Frost Breath's one-shot
    # and gets a different node. Tried before requiring "next" so the two
    # spellings do not have to be told apart by their prefixes.
    linked = stream.mark()
    # "…untap step **for as long as it has a paralyzation counter on it**"
    # (Dread Wight). Also no "next", and also continuous — but what ends it is
    # a fact about the restricted permanent rather than about the source, which
    # is a third node. Tried before the source-tapped spelling only because
    # both begin "for as long as" and one of them has to go first; each names
    # its own pronoun on the next word, so neither can swallow the other.
    if stream.accept_phrase(
        "untap", "step", "for", "as", "long", "as", "it", "has"
    ):
        stream.expect_word("a", "an")
        token = _expect_counter_kind(stream)
        if token.kind == PT:
            # A CR 122.1a P/T pair is not a marker a card removes one of to
            # release a creature, and nothing in this family reads one. Refused
            # rather than accepted, so the sentence fails by name.
            raise stream.error(
                "an untap restriction is conditioned on a named counter"
            )
        stream.expect_word("counter")
        stream.expect_word("on")
        stream.expect_word("it")
        return ast.DoesntUntapWhileCounter(subject, token.text)
    stream.reset(linked)
    if stream.accept_phrase("untap", "step", "for", "as", "long", "as", "this"):
        # The noun is required. Accepted-but-optional, it could be deleted with
        # no change to what was lowered — which is what the parse-coverage
        # deletion probe reports, and the shape three productions in
        # `paragraphs.py` were tightened out of at the same time.
        if stream.accept_word(
            "creature", "artifact", "enchantment", "land", "permanent"
        ) and stream.accept_phrase("remains", "tapped"):
            return ast.DoesntUntapWhileSourceTapped(subject)
    stream.reset(linked)
    stream.expect_word("next")
    # "…next **two** untap steps" (Telekinesis). The number is read rather than
    # skipped: a restriction that survived one untap step where the card says
    # two is the creature back a turn early, and one that skipped the word would
    # report supported while doing it.
    count = 1
    counted = stream.mark()
    word = stream.peek_word()
    if word in NUMBER_WORDS:
        count = NUMBER_WORDS[word]
        stream.advance()
        if not (stream.at_word("untap") and stream.peek_word(1) == "steps"):
            # A number with the singular noun after it is not this sentence.
            stream.reset(counted)
            count = 1
    stream.expect_word("untap")
    stream.expect_word("step", "steps")
    return ast.DoesntUntapNextStep(subject, count=count)


def _parse_tap_untap(stream: TokenStream) -> ast.Statement:
    """``tap <objects>`` / ``untap <objects>`` / ``tap or untap <objects>``.

    The disjunction (Twiddle) is read here rather than as two statements joined
    by "or": both directions act on the *same* chosen target and only one of
    them happens, so a ``Conjunction`` would tap the permanent and then untap
    it. Only "tap or untap" is a disjunction — "untap or tap" is not printed on
    any card, and inventing it would accept text no card carries.
    """
    # The inflected spelling is the same verb with a printed subject in front
    # of it ("…and **you tap** that creature", Mind Whip) — normalized here so
    # every branch below reads one word.
    verb = stream.expect_word("tap", "untap", "taps", "untaps").text.rstrip("s")
    either_way = False
    if verb == "tap":
        mark = stream.mark()
        if stream.accept_word("or") and stream.accept_word("untap"):
            either_way = True
        else:
            stream.reset(mark)
    # "…and you tap **that creature**." (Mind Whip.) The object the sentence's
    # own trigger condition named, read by the bound reader after the ordinary
    # one so "the creature" keeps its existing reading as the source. Every
    # lowering refuses a bound quantifier unless it says otherwise, so reading
    # it here fails the line **by name** where it used to fail at the noun.
    subject = parse_recipient(stream) or parse_bound_subject(stream)
    if subject is None:
        raise stream.error(f"expected something to {verb}")
    if either_way:
        return ast.TapOrUntap(subject)
    return ast.Tap(subject) if verb == "tap" else ast.Untap(subject)


def _parse_untap_chosen_by_paying(stream: TokenStream) -> "ast.Statement | None":
    """``<player> may choose any number of <objects> and pay <cost> for each
    <noun> chosen this way. If the player does, untap those <nouns>.``
    (Mudslide.)

    A toll the payer chooses how many times to pay: the cost is per chosen
    object, so the count is the payer's own decision and the effect lands on
    exactly what they paid for. That is why it is one production rather than a
    ``May`` wrapping a choice — a ``May``'s cost is fixed when the offer is
    made, and here it is not known until the picking is done.

    Both sentences are read, interior full stop included, and the second one is
    required: a line that chooses and charges but never says what the payment
    bought is a card that takes mana and does nothing, and dropping the
    sentence would make the two indistinguishable.

    Returns None with the cursor untouched on anything else, so an ordinary
    "may" keeps its own reading.
    """
    mark = stream.mark()
    payer = parse_player_ref(stream)
    if payer is None or not stream.accept_phrase(
        "may", "choose", "any", "number", "of"
    ):
        stream.reset(mark)
        return None
    # The counted position: a bare plural names a *kind* here, so the noun
    # phrase is read as one rather than as a quantified single object.
    subject = parse_subject_filter_at(stream, plural=True)
    if subject is None:
        stream.reset(mark)
        return None
    if not stream.accept_phrase("and", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if cost is None or not stream.accept_phrase("for", "each"):
        stream.reset(mark)
        return None
    # The repeated noun is compared against the set the choice named rather
    # than skipped: "pay {2} for each **land** chosen this way" after choosing
    # creatures is a card charging for something else, and a production that
    # accepted any word there would read it as this one.
    noun = stream.peek_word()
    if noun is None or noun not in subject.card_types:
        stream.reset(mark)
        return None
    stream.advance()
    if not stream.accept_phrase("chosen", "this", "way"):
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    # "If the player does, untap those creatures." The payment's consequence,
    # required in full — including the plural noun, for the reason the singular
    # one above is read.
    if not stream.accept_word("if"):
        stream.reset(mark)
        return None
    doer = parse_player_ref(stream)
    if doer is None or doer.kind != payer.kind:
        stream.reset(mark)
        return None
    if not stream.accept_word("does"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("untap", "those"):
        stream.reset(mark)
        return None
    if stream.peek_word() != noun + "s":
        stream.reset(mark)
        return None
    stream.advance()
    return ast.UntapChosenByPaying(payer, subject, cost)

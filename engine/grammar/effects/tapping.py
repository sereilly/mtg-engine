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
from ..phrases import parse_bound_subject
from ..references import parse_recipient
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

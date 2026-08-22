"""The battlefield: destruction, bouncing, tapping, control.

Return-to-zone, destroy, tap/untap, gain control, and `_parse_that_object` —
the back-reference a delayed effect uses to name the permanent its trigger
bound ("destroy *that creature* at end of combat").

These productions read a zone through `phrases._parse_zone`; they do not define
one, because "search your library" needs the same fragment and neither family
should own the other's vocabulary.
"""

import dataclasses

from .. import ast
from ..references import parse_recipient
from ..stream import TokenStream
from ..vocabulary import (CARD_TYPES, CREATURE_TYPES, SUBTYPE_INDEX, match_longest)
from ..phrases import _parse_mana_payment, _parse_zone


def _parse_gain_control(stream: TokenStream) -> ast.GainControl | None:
    """``Gain control of <subject> for as long as you control this <permanent>.``

    Returns None — cursor untouched — unless the line really opens "gain
    control": "gains flying", "you gain 3 life" and "gains control of this
    creature" (Ghazbán Ogre, whose subject comes first) all begin with the same
    verb and are read elsewhere.

    The duration clause is *required*, and only the one shape a handler
    implements is admitted. An untimed "gain control of target creature" is a
    permanent control change; a differently-timed one (Old Man of the Sea's two
    conditions) reverts on things nothing here watches. Both would be this
    production's sentence with the ending changed, so both have to fail rather
    than borrow the linked duration.
    """
    mark = stream.mark()
    stream.expect_word("gain")
    if not stream.accept_word("control"):
        stream.reset(mark)
        return None
    if not stream.accept_word("of"):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to gain control of")
    # "…until end of turn" (Traitorous Greed). A lifetime of its own rather than
    # one tied to a permanent that is still there: the spell that granted it is
    # in a graveyard by the time the turn ends, so nothing can be watched for —
    # CR 611.2c ends it at cleanup instead.
    if stream.accept_phrase("until", "end", "of", "turn"):
        return ast.GainControl(subject, "until_end_of_turn")
    if not stream.accept_phrase("for", "as", "long", "as", "you", "control", "this"):
        raise stream.error(
            "no handler for a control change without a duration the engine ends"
        )
    # The noun after "this" names the source's own type and adds nothing the
    # payload carries, but it still has to be consumed for the line to be
    # accounted for in full.
    if stream.peek_word() is None:
        raise stream.error("expected the permanent the control change is linked to")
    stream.advance()
    return ast.GainControl(subject, "while_you_control_source")


def _parse_return(stream: TokenStream) -> ast.Statement:
    """``Return <objects> [from <zone>] to <zone>`` (CR 400.7).

    One production for Raise Dead, Regrowth, Resurrection and Unsummon, which
    the legacy registry needed three separately-ordered substring rules for —
    and which it told apart by probing for ``"creature card" not in text``. The
    source zone rides on the noun phrase (``engine/grammar/nouns.py``), because
    "target creature card from your graveyard" is one noun phrase; the
    destination is parsed here.
    """
    stream.expect_word("return")
    # "Return target spell or creature to its owner's hand." (Unsubstantiate.)
    # A union across two zones — the stack and the battlefield — which no
    # object filter expresses, so the template is read whole and the node
    # carries the stack half as a flag.
    union_mark = stream.mark()
    if stream.accept_phrase("target", "spell", "or", "creature"):
        if stream.accept_word("to"):
            destination = _parse_zone(stream)
            if (
                destination.name == "hand"
                and destination.owner is not None
                and destination.owner.kind == "owner"
            ):
                return ast.ReturnToZone(
                    ast.TargetSpec(
                        "target", ast.ObjectFilter(card_types=("creature",)),
                        targeted=True,
                    ),
                    destination, None, also_stack=True,
                )
        stream.reset(union_mark)
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to return")
    if not stream.accept_word("to"):
        raise stream.error("expected a destination zone after 'return'")
    destination = _parse_zone(stream)

    # "...to the battlefield **tapped**." (Silversmote Ghoul.) CR 110.5b: a
    # permanent enters untapped unless a spell or ability says otherwise, and
    # this is the ability saying so. Consumed here rather than left to
    # engine/enter_effects.py, which answers for a permanent's *own printed*
    # entry line (a static ability, CR 603.6d) — this rider is printed on the
    # ability that does the moving, and the permanent it makes has no such line.
    # Accepted only for the battlefield, because "to your hand tapped" is not a
    # sentence and silently dropping the word is the bug class this grammar
    # refuses by construction.
    entering_tapped = False
    if destination.name == "battlefield" and stream.accept_word("tapped"):
        entering_tapped = True

    from_zone: ast.Zone | None = None
    if isinstance(subject, ast.TargetSpec) and subject.filter.zone != "battlefield":
        from_zone = ast.Zone(subject.filter.zone, subject.filter.zone_owner)
    return ast.ReturnToZone(
        subject, destination, from_zone, entering_tapped=entering_tapped
    )


def _parse_destroy(stream: TokenStream) -> ast.Statement:
    """``destroy <objects> [. It can't be regenerated.]``

    One production covers "destroy target creature", "destroy all lands",
    "destroy target tapped creature", and "destroy all Plains" — the
    distinction lives in the noun phrase's quantifier and filter. The legacy
    registry needed five separate rules with hand-ordered precedence numbers to
    keep "destroy all creatures" from being eaten by "destroy target".
    """
    stream.expect_word("destroy")
    subject = _parse_that_object(stream) or parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to destroy")

    # "…at end of combat" (CR 603.7). Only this one delay: a destruction
    # deferred to the next end step is a different handler, so leaving those
    # tokens unconsumed is what keeps Stone Giant and Nettling Imp failing
    # loudly instead of being destroyed a step early.
    delay = "end_of_combat" if stream.accept_phrase("at", "end", "of", "combat") else ""

    no_regen = False
    mark = stream.mark()
    stream.accept_punct(".", ",")
    if stream.accept_phrase("it", "can't", "be", "regenerated") or stream.accept_phrase(
        "they", "can't", "be", "regenerated"
    ):
        no_regen = True
    else:
        stream.reset(mark)
    return ast.Destroy(subject, no_regen=no_regen, delay=delay)


def _parse_that_object(stream: TokenStream) -> ast.TargetSpec | None:
    """``that <card type>`` — the object a trigger already named.

    Not a target: the trigger bound it when it fired, so nothing is chosen on
    resolution. It gets its own quantifier rather than being read as an ordinary
    noun phrase, so a lowering written for "target creature" can never receive
    it — the two reach completely different handlers, and the ones that take a
    bound object read it out of the trigger's context instead of the payload.

    Deliberately local to the destroy production. The phrase turns up all over
    the pool ("tap that creature", "that player discards"), and teaching the
    shared noun parser to claim it would let every one of those lines lower
    through a filter naming a card type nobody bound.
    """
    mark = stream.mark()
    if not stream.accept_word("that"):
        return None
    noun = stream.peek_word()
    if noun is not None and noun in CARD_TYPES:
        stream.advance()
        return ast.TargetSpec("that", ast.ObjectFilter(card_types=(noun,)))
    # "destroy that **Wall**" (Battering Ram). A subtype names the bound object
    # just as a card type does — the trigger that fired required it, so the word
    # is describing what was bound rather than narrowing a fresh choice. Read
    # through the vocabulary, so a made-up noun still refuses.
    matched = match_longest(stream.words_from(), 0, SUBTYPE_INDEX)
    if matched is not None and matched[0] in CREATURE_TYPES:
        stream.advance(matched[1])
        return ast.TargetSpec(
            "that",
            ast.ObjectFilter(card_types=("creature",), subtypes=(matched[0],)),
        )
    stream.reset(mark)
    return None


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
    stream.expect_word("untap")
    stream.expect_word("step")
    return ast.DoesntUntapNextStep(subject)


def _parse_attach(stream: TokenStream) -> ast.Statement:
    """``Attach <subject> to <host>`` (CR 701.3).

    The sentence CR 702.6a expands equip into — "Attach this permanent to
    target creature you control" — and its one generalisation, a chosen
    Equipment ("Attach target Equipment you control to target creature you
    control"). Both halves go through `parse_recipient`, so a narrowed host
    ("target legendary creature you control", CR 702.6c's "Equip [quality]")
    is read by the noun phrase every other production already uses rather than
    by anything here. The whole line must be consumed: a trailing clause this
    does not read is a refusal, never a silent partial attach.
    """
    stream.expect_word("attach")
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected what to attach")
    if not stream.accept_word("to"):
        raise stream.error("expected 'to' after what is attached")
    host = parse_recipient(stream)
    if host is None:
        raise stream.error("expected what to attach to")
    return ast.Attach(subject, host)


def _parse_tap_untap(stream: TokenStream) -> ast.Statement:
    """``tap <objects>`` / ``untap <objects>`` / ``tap or untap <objects>``.

    The disjunction (Twiddle) is read here rather than as two statements joined
    by "or": both directions act on the *same* chosen target and only one of
    them happens, so a ``Conjunction`` would tap the permanent and then untap
    it. Only "tap or untap" is a disjunction — "untap or tap" is not printed on
    any card, and inventing it would accept text no card carries.
    """
    verb = stream.expect_word("tap", "untap").text
    either_way = False
    if verb == "tap":
        mark = stream.mark()
        if stream.accept_word("or") and stream.accept_word("untap"):
            either_way = True
        else:
            stream.reset(mark)
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error(f"expected something to {verb}")
    if either_way:
        return ast.TapOrUntap(subject)
    return ast.Tap(subject) if verb == "tap" else ast.Untap(subject)


def _parse_sacrifice(stream: TokenStream, player: ast.PlayerRef) -> ast.Statement:
    """"<player> sacrifices <noun>", with the verb already consumed.

    Two spellings reach it: the bare imperative, whose player is you, and a
    printed subject ("each opponent sacrifices a creature", Goremand). One
    production for both, because who sacrifices is the node's field and the
    sentence is otherwise word-for-word the same — the alternative was a second
    copy that would have had to grow the "another" reading and the unless-pay
    tail again.
    """
    # "Sacrifice **another** creature" (Dire Fleet Warmonger) — the same
    # reading the cost parser gives the word: a restriction on what may be
    # sacrificed, carried on the filter's existing field.
    another = bool(stream.accept_word("another"))
    subject = parse_recipient(stream)
    if subject is None:
        raise stream.error("expected something to sacrifice")
    if another and isinstance(subject, ast.TargetSpec):
        subject = dataclasses.replace(
            subject, filter=dataclasses.replace(subject.filter, other_than_source=True)
        )
    # "… unless you pay {W}{W}" — a pay-or-else prompt, kept fused because
    # that is the shape the upkeep dispatcher's handlers implement.
    mark = stream.mark()
    if stream.accept_phrase("unless", "you", "pay"):
        return ast.SacrificeUnlessPay(subject, _parse_mana_payment(stream))
    stream.reset(mark)
    return ast.Sacrifice(player, subject)


def _parse_sacrifice_expansion_permanents(stream: TokenStream) -> ast.Statement | None:
    """``Each nontoken permanent with a name originally printed in the <Set>
    expansion is sacrificed by its controller.`` (Golgothian Sylex.)

    The set *name* is printed and the engine wants its code, so the mapping is
    asked of the manifest — the registry that already holds both — rather than
    written out here. A name the manifest does not know leaves the line
    unconsumed and its card unsupported, which is the right answer: the effect
    would otherwise sacrifice the permanents of whichever set the caller
    guessed, or of none, and neither is what the card says.
    """
    from ...card_loader import set_code_for_expansion_name

    mark = stream.mark()
    if not stream.accept_phrase(
        "each", "nontoken", "permanent", "with", "a", "name",
        "originally", "printed", "in", "the",
    ):
        stream.reset(mark)
        return None
    words: list[str] = []
    while not stream.exhausted and not stream.at_word("expansion"):
        word = stream.peek_word()
        if word is None:
            stream.reset(mark)
            return None
        words.append(word)
        stream.advance()
    if not words or not stream.accept_word("expansion"):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("is", "sacrificed", "by", "its", "controller"):
        stream.reset(mark)
        return None
    set_code = set_code_for_expansion_name(" ".join(words))
    if set_code is None:
        stream.reset(mark)
        return None
    return ast.SacrificeExpansionPermanents(set_code)


def _parse_shuffle_graveyard_into_library(stream: TokenStream) -> ast.Statement | None:
    """``Shuffle your graveyard into your library.`` (Feldon's Cane.)

    Both possessives are read rather than assumed. A card moving *another*
    player's graveyard is a different effect, and consuming "your" without
    checking it would compile that card onto this one.
    """
    mark = stream.mark()
    # "your graveyard" is a possessive, not a player reference — `parse_player_ref`
    # reads "you" / "target player" / "each opponent" and rightly refuses it —
    # so the word is matched directly, and both occurrences are checked. A card
    # moving *another* player's graveyard is a different effect, and consuming
    # the possessive without reading it would compile that card onto this one.
    if not stream.accept_phrase(
        "shuffle", "your", "graveyard", "into", "your", "library"
    ):
        stream.reset(mark)
        return None
    return ast.ShuffleGraveyardIntoLibrary(ast.PlayerRef("you"))


def _parse_delayed_self_action(stream: TokenStream) -> ast.Statement | None:
    """``Destroy this artifact at the beginning of the next end step.`` /
    ``Return this artifact to its owner's hand at the beginning of the next end
    step.``

    The whole sentence, delay included, because the action on its own is
    performed *now* — an artifact that destroys itself the moment its ability
    resolves is a different card from one that survives until the end step.
    Every word of the timing is required for the same reason the "next" in
    ``_parse_doesnt_untap_next_step`` is.
    """
    mark = stream.mark()
    if stream.accept_word("destroy"):
        action = "destroy"
    elif stream.accept_word("return"):
        action = "bounce"
    else:
        stream.reset(mark)
        return None
    if not stream.accept_word("this"):
        stream.reset(mark)
        return None
    if not stream.accept_word(
        "artifact", "creature", "enchantment", "land", "permanent"
    ):
        stream.reset(mark)
        return None
    if action == "bounce" and not stream.accept_phrase(
        "to", "its", "owner", "'s", "hand"
    ):
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "at", "the", "beginning", "of", "the", "next", "end", "step"
    ):
        stream.reset(mark)
        return None
    return ast.DelayedSelfAction(action)

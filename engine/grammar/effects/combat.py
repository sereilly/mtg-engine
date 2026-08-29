"""Combat restrictions (CR 506, 509).

The two printed shapes the engine enforces: "can't attack unless defending
player controls a <land type>" and "can't be blocked by …". The land type and
the power threshold are *captured*, not baked into the production — which is
what lets a second card with the same template arrive needing no parser change
at all.
"""

from .. import ast
from ..nouns import parse_object_filter
from ..references import parse_recipient
from ..stream import TokenStream
from ..phrases import _accept_number, _parse_duration, parse_counted_subject


# The printed combat restrictions the engine enforces (CR 506, 509). Several are
# also derived from raw text by engine/combat_restrictions.py for the legacy
# path; these productions let the *grammar* claim them, lowering to the same
# instruction kinds with the same payloads so the differential can hold the two
# to agreement.
#
# Everything printed is captured rather than baked into a production: the noun
# phrase the defending player controls, the power threshold, the count of other
# attackers. A card naming a Mountain, a threshold of 4 or three companions is
# the same restriction, and spelling any of them into a kind would make each
# printed word a new kind and a new enforcement branch.
#
# The five basic land words used to be re-bound here, because the defender-board
# clause could name only those. It reads a whole noun phrase now, so the list is
# gone with the restriction it was.


def _parse_cant_attack_or_block(
    stream: TokenStream, subject: ast.Recipient
) -> ast.Statement:
    """``<subject> can't attack unless defending player controls a <land>`` /
    ``<subject> can't block creatures with power N or greater``."""
    # "can't" is peeked, not consumed, so the fallback to _parse_cant_be (which
    # expects to read it itself) sees an untouched stream.
    mark = stream.mark()
    stream.expect_word("can't", "cannot")

    if stream.accept_word("attack"):
        # "That creature can't attack during its controller's next turn."
        # (Wall of Dust's block trigger.) A one-shot restriction with a stated
        # window rather than a static ability — the window is the whole of the
        # payload-free kind, and lowering holds the subject to the
        # back-reference the trigger already bound.
        if stream.accept_phrase("during", "its", "controller", "'s", "next", "turn"):
            return ast.CombatRestriction(
                subject, "cant_attack_during_controllers_next_turn", ()
            )
        # "Creatures can't attack this turn." (Festival.) The attack twin of
        # the blanket can't-block below: no "unless", just a duration — the
        # restriction is a blanket over the *subject* for the rest of the turn
        # rather than a property of any permanent. Only the durationed form is
        # claimed; a bare "<subject> can't attack" is a static ability and
        # falls through to the refusal below, which is where the pool's
        # printed statics ("This creature can't attack") already go.
        if not stream.at_word("unless"):
            duration_mark = stream.mark()
            duration = _parse_duration(stream)
            if duration.kind is not None:
                return ast.CombatRestriction(
                    subject, "cant_attack_until_eot", (("duration", duration.kind),)
                )
            stream.reset(duration_mark)
        # "This creature can't attack **unless you sacrifice two Islands**."
        # (Leviathan.) CR 508.1g: an additional *cost* to attack, paid as
        # attackers are declared — not a target and not a board condition, so
        # the declaration charges it and an unpayable cost makes the attack
        # illegal. The noun phrase is `phrases.parse_counted_subject`, the same
        # reading the "unless you sacrifice" tails elsewhere use, so the gate
        # and the charge cannot disagree about what is owed.
        # "This creature can't attack **unless at least two other creatures
        # attack**." (Orcish Conscripts.) CR 508.1c reads a restriction against
        # the *whole* declaration — "if any restrictions are being disobeyed,
        # the declaration is illegal" — so this is not a fact about the creature
        # and no per-creature predicate can answer it. Its own kind for that
        # reason, checked where Errantry's "can only attack alone" already is.
        #
        # The threshold is payload: "at least three" is the same restriction,
        # and spelling the number into the kind would make each printed count a
        # new kind and a new check.
        others_mark = stream.mark()
        if stream.accept_phrase("unless", "at", "least"):
            count = _accept_number(stream)
            if count is not None and stream.accept_phrase(
                "other", "creatures", "attack"
            ):
                return ast.CombatRestriction(
                    subject, "cant_attack_unless_others_attack", (("count", count),)
                )
            stream.reset(others_mark)
        # "Green creatures can't attack unless **their controller** sacrifices a
        # land of their choice **for each green creature they control that's
        # attacking**." (Flooded Woodlands, Reclamation — one sentence with the
        # colour word changed.) CR 508.1g again, and three things differ from
        # Leviathan's cost one branch down: the sentence is printed on a
        # permanent that names a *class* of creatures rather than itself, the
        # payer is that class's controller rather than "you", and the cost is
        # charged once per attacking member.
        #
        # The "for each" tail is **read and kept**, not skipped: it says what the
        # cost scales with, and lowering holds it to the subject the sentence
        # opened with. A tail consumed and dropped would be a card that charges
        # once for a whole team.
        per_mark = stream.mark()
        if stream.accept_phrase("unless", "their", "controller", "sacrifices"):
            counted = parse_counted_subject(stream)
            if counted is not None:
                count, described = counted
                if not stream.accept_phrase("for", "each"):
                    raise stream.error("expected 'for each' after the attack cost")
                per = parse_object_filter(stream)
                return ast.CombatRestriction(
                    subject,
                    "creatures_cant_attack_unless_sacrifice",
                    (
                        ("sacrifice_filter", described),
                        ("sacrifice_count", count),
                        ("per", per),
                    ),
                )
            stream.reset(per_mark)
        unless_mark = stream.mark()
        if stream.accept_phrase("unless", "you", "sacrifice"):
            counted = parse_counted_subject(stream)
            if counted is not None:
                count, described = counted
                return ast.CombatRestriction(
                    subject,
                    "cant_attack_unless_sacrifice",
                    (("sacrifice_filter", described), ("sacrifice_count", count)),
                )
            stream.reset(unless_mark)
        # "…**unless** defending player controls an Island" (Sea Serpent) and
        # "…**if** defending player controls an untapped creature with power 3
        # or greater" (Goblin Mutant) are one restriction under two printed
        # polarities: both ask whether the defender's board holds something
        # answering a description, and differ in which answer forbids the
        # attack. The word travels as payload for the reason the noun does — a
        # card printing the other one is the same question.
        required = True
        if not stream.accept_phrase("unless", "defending", "player", "controls"):
            if not stream.accept_phrase("if", "defending", "player", "controls"):
                raise stream.error("expected 'unless defending player controls'")
            required = False
        # The whole noun phrase, through the reader every counted subject uses.
        # It was five basic land *words* welded into the payload, because the
        # enforcing check scanned lands by name; the check tests the printed
        # phrase with `subject_matches` now, so "a Forest" and "an untapped
        # creature with power 3 or greater" are the same production.
        counted = parse_counted_subject(stream)
        if counted is None:
            raise stream.error("expected what the defending player controls")
        _count, described = counted
        return ast.CombatRestriction(
            subject,
            "cant_attack_unless_defender_controls",
            (("subject", described), ("required", required)),
        )

    if stream.accept_word("block"):
        # "…**unless at least two other creatures block**." (Orcish Conscripts.)
        # The blocking twin of the attack clause above, CR 509.1b's side of the
        # same rule, and read here before the two shapes below because it opens
        # on a word neither of them takes.
        block_others = stream.mark()
        if stream.accept_phrase("unless", "at", "least"):
            count = _accept_number(stream)
            if count is not None and stream.accept_phrase(
                "other", "creatures", "block"
            ):
                return ast.CombatRestriction(
                    subject, "cant_block_unless_others_block", (("count", count),)
                )
            stream.reset(block_others)
        # "Creatures without flying can't block this turn." (Destructive
        # Tampering's second mode): no object after "block" — the restriction
        # is a blanket over the *subject*, scoped by the printed duration.
        # Only the durationed form is claimed; a bare "<subject> can't block"
        # would be a static ability and refuses below by falling through.
        if not stream.at_word("creatures"):
            duration = _parse_duration(stream)
            if duration.kind is None:
                raise stream.error("expected 'creatures' or a duration after \"can't block\"")
            return ast.CombatRestriction(
                subject, "cant_block_until_eot", (("duration", duration.kind),)
            )
        stream.expect_word("creatures")
        if not stream.accept_phrase("with", "power"):
            raise stream.error("expected 'with power'")
        token = stream.peek()
        if token is None or not token.text.isdigit():
            raise stream.error("expected a power threshold")
        power = token.text
        stream.advance()
        if not stream.accept_phrase("or", "greater"):
            raise stream.error("expected 'or greater'")
        return ast.CombatRestriction(
            subject, "cant_block_power_n_or_greater", (("power", int(power)),)
        )

    stream.reset(mark)
    return _parse_cant_be(stream, subject)


# Participles this production recognizes after "can't be". A closed list, so a
# restriction the grammar has never seen fails in the parser by name instead of
# being read as one of these.
_CANT_BE_ACTIONS = ("regenerated", "blocked")


def _parse_cant_be(stream: TokenStream, subject: ast.Recipient) -> ast.Statement:
    """``<subject> can't be <participle> [by <blockers>] [duration]``.

    "…can't be blocked **by Walls** this turn" (Tower of Coireall) is a
    *granted* restriction with a duration, so the class of blocker is read and
    carried — a narrowing dropped here would make the creature unblockable
    outright, which is a strictly larger effect than the card prints.

    Note what is still deliberately *not* consumed. An "except by" clause is a
    whitelist rather than a class, and says the opposite thing about everything
    unnamed, so it keeps its tokens and its loud failure. And a "by" clause with
    **no duration** is a static ability (Juggernaut, Argothian Pixies) that
    ``engine/combat_restrictions.py`` derives; the words are put back so the
    line falls through to that table exactly as it did before, rather than
    parsing here and refusing at lowering — which would take those cards'
    support away.
    """
    stream.expect_word("can't", "cannot")
    stream.expect_word("be")
    word = stream.peek_word()
    if word not in _CANT_BE_ACTIONS:
        raise stream.error("unrecognized \"can't be\" restriction")
    stream.advance()
    by = None
    by_mark = stream.mark()
    if word == "blocked" and stream.accept_word("by"):
        by = parse_recipient(stream)
        if by is None:
            stream.reset(by_mark)
    duration = _parse_duration(stream)
    if by is not None and duration.kind is None:
        # The static printing. Put the phrase back and let the line fail
        # full-consumption, which is what routes it to the derived table.
        stream.reset(by_mark)
        return ast.CantBe(subject, word, duration)
    return ast.CantBe(subject, word, duration, by=by)


def _parse_remove_from_combat(stream: TokenStream) -> ast.RemoveFromCombat | None:
    """``remove <subject> from combat`` (Disharmony; CR 506.4c).

    Returns None — cursor untouched — when the words after "remove" are not
    this sentence, so the counter-removal production keeps every other
    "remove …" line. The subject is an ordinary recipient here; *lowering*
    holds it to the back-reference shape the pool prints, so a freestanding
    "remove target creature … from combat" (False Orders) refuses there by
    name rather than being half-read.
    """
    mark = stream.mark()
    stream.expect_word("remove")
    subject = parse_recipient(stream)
    if subject is None or not stream.accept_phrase("from", "combat"):
        stream.reset(mark)
        return None
    _accept_freed_blockers_restatement(stream)
    return ast.RemoveFromCombat(subject)


def _accept_freed_blockers_restatement(stream: TokenStream) -> None:
    """Consume ", and creatures it was blocking that had become blocked by only
    that creature this combat become unblocked" (Imprison).

    CR 506.4c already says this: a creature removed from combat stops being a
    blocker, and an attacker it was the only blocker of stops being blocked.
    The engine says it in one place — ``_remove_blocker_from_combat``, which
    every removal goes through — so the printed clause restates the sentence in
    front of it rather than adding to it, and there is nothing for a payload to
    carry that is not already true of every removal.

    Consumed rather than carried for that reason, the way "each of" is in
    ``references.parse_target_spec``. Consumed rather than *ignored* because a
    production must claim every token of its line: left over, these words would
    fail the line at "unconsumed text" and Imprison would stay unsupported with
    both of its halves working.

    All-or-nothing — a partial match rewinds, so a card printing some *other*
    consequence after the removal keeps its tokens and fails loudly.
    """
    mark = stream.mark()
    stream.accept_punct(",")
    stream.accept_word("and")
    for word in (
        "creatures", "it", "was", "blocking", "that", "had", "become",
        "blocked", "by", "only",
    ):
        if not stream.accept_word(word):
            stream.reset(mark)
            return
    # "that creature" (False Orders, Imprison) and "this creature" (Ydwen
    # Efreet) are the same referent printed two ways — the creature the
    # sentence just removed.
    if not stream.accept_word("that", "this"):
        stream.reset(mark)
        return
    for word in ("creature", "this", "combat", "become", "unblocked"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return


def _parse_attacking_doesnt_tap(
    stream: TokenStream, parse_condition
) -> "ast.AttackingDoesntTap | None":
    """``Attacking doesn't cause <subject> to tap this combat[ if <condition>].``
    (Johan.)

    CR 508.1f's tap, switched off for the creatures the sentence names.
    Returns None — cursor untouched — for anything else opening with
    "attacking", so no other reading of the word is taken away.

    *parse_condition* arrives as a parameter rather than as an import: the
    condition parser sits in this module's own layer, and a family that reached
    up for it would be the coupling `test_grammar_layering.py` exists to
    refuse. The same shape `lowering/where_x.py` and `delayed.py` already use
    for their recursion.

    The duration is read here rather than through the shared duration table.
    "This combat" is a duration exactly one printed sentence in the pool takes,
    and putting it in that table would offer it to every production that reads
    a duration — including the several that would then accept a word no sweep
    of theirs ends.
    """
    mark = stream.mark()
    if not stream.accept_word("attacking"):
        return None
    if not (stream.accept_word("doesn't") and stream.accept_word("cause")):
        stream.reset(mark)
        return None
    subject = parse_recipient(stream)
    if subject is None or not stream.accept_phrase("to", "tap", "this", "combat"):
        stream.reset(mark)
        return None
    if not stream.accept_word("if"):
        return ast.AttackingDoesntTap(subject)
    condition = parse_condition(stream)
    # Reduced to the state word here rather than stored whole. The gate is a
    # *standing* test — "for as long as Johan is untapped" — and the only shape
    # the declare-attackers step can keep asking is a state of the effect's own
    # source, which is the same question an adjective in a noun phrase asks. A
    # condition about anything else is refused rather than consumed and dropped.
    if not isinstance(condition, ast.IsState) or not _is_self_reference(condition.subject):
        raise stream.error(
            "an attack-tap exemption's gate asks about a state of its own source"
        )
    return ast.AttackingDoesntTap(subject, condition.state, condition.negated)


def _is_self_reference(recipient: ast.Recipient) -> bool:
    """Whether *recipient* is the printed "this creature" / the card's own name."""
    return (
        isinstance(recipient, ast.TargetSpec)
        and recipient.filter.is_source
        and not recipient.targeted
    )


def _parse_assigns_no_combat_damage(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.AssignsNoCombatDamage | None":
    """``<subject> assigns no combat damage <duration>.`` (Floral Spuzzem.)

    CR 510.1 says a creature assigns its combat damage as the step begins; this
    is that assignment switched off. Read as its own sentence rather than as a
    prevention shield, because it is not one: no damage is prevented, none is
    ever assigned, so nothing a shield counts is spent and a replacement that
    watches for damage never fires.

    Returns None — cursor untouched — for any other reading of "assigns", so a
    future "assigns its combat damage as though …" keeps its own refusal
    instead of failing on words this production expected.
    """
    mark = stream.mark()
    if not stream.accept_word("assigns", "assign"):
        return None
    if not stream.accept_phrase("no", "combat", "damage"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    return ast.AssignsNoCombatDamage(subject, duration)

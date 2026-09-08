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
from ..phrases import (_accept_number, _parse_duration, parse_subject_filter_at)
from ..sacrifices import parse_counted_subject


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
        # "This creature can't attack **or block alone**." (Mogg Flunkies.)
        # CR 506.5 defines "attacking alone" as being the only creature
        # declared as an attacker, so the word is a *count*: this is the
        # printed-word spelling of "unless at least one other creature attacks"
        # two branches down, and it lowers to that very kind rather than to a
        # restriction of its own. One sentence, two prohibitions, one subject —
        # the shape ``CombatRestriction.also_kinds`` names on the text-table
        # side, and the lowering returns the pair.
        #
        # Read here, in front of the duration probe, because "alone" is a word
        # neither that probe nor the "unless" clauses take: without it the
        # sentence fell all the way through to "expected 'unless defending
        # player controls'", a refusal naming a phrase the card does not print.
        #
        # Each half is accepted on its own as well as in the conjunction. The
        # word means the same thing in all three spellings, and a production
        # that read the compound but refused "can't block alone" would hand the
        # half-sentence the same misleading refusal this branch exists to
        # remove.
        if stream.accept_word("alone"):
            return ast.CombatRestriction(
                subject, "cant_attack_alone", (("count", 1),)
            )
        if stream.accept_phrase("or", "block", "alone"):
            return ast.CombatRestriction(
                subject, "cant_attack_or_block_alone", (("count", 1),)
            )
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
        # rather than a property of any permanent.
        if not stream.at_word("unless"):
            duration_mark = stream.mark()
            duration = _parse_duration(stream)
            if duration.kind is not None:
                return ast.CombatRestriction(
                    subject, "cant_attack_until_eot", (("duration", duration.kind),)
                )
            stream.reset(duration_mark)
            # "Creatures without flying can't attack." (Moat.) The same
            # sentence with **no** duration, which makes it a static ability
            # over a described set — and one the engine has always
            # implemented, through `engine/combat_restrictions.py`'s three
            # rows. It is claimed here now because the durationed reading has
            # to be reachable from a duration printed in *front* of the verb
            # ("This turn and next turn, creatures can't attack, and …", Peace
            # Talks), and a production that refuses the durationless sentence
            # has nothing for `_distribute_duration` to attach the prefix to.
            #
            # The lowering produces the table's own instruction, byte for byte,
            # which is what `test_grammar_derived_lines` compares over the
            # whole pool — the sanctioned second state for a line a derivation
            # table also reads.
            #
            # A **plural** subject only, and the sentence must end here. "This
            # creature can't attack" (Pacifism's half) is a restriction on one
            # permanent with its own kind and no grammar production, so it must
            # keep failing the parser; and "can't attack **or block**"
            # (Katabatic Winds) is a longer sentence the table reads whole, so
            # stopping at "attack" would take three prohibitions down to one.
            if (
                isinstance(subject, ast.TargetSpec)
                and subject.quantifier in ("all", "each")
                and (stream.exhausted or stream.at_punct(".", ","))
            ):
                return ast.CombatRestriction(
                    subject, "cant_attack_until_eot", ()
                )
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
        # "This creature can't attack **unless a creature with greater power
        # also attacks**." (Okk.) CR 508.1c again, and the same shape as the
        # count below it: a restriction the *declaration* answers rather than
        # the creature, because no per-creature predicate can see who else was
        # declared.
        #
        # What differs is the question. The count below asks how many joined;
        # this asks whether one of them is bigger, which is a comparison
        # against this creature's own power and so cannot ride that kind's
        # ``count`` payload. Its own kind for the reason ``cant_attack`` and
        # ``cant_block`` are two: one kind answered by two different questions
        # is a kind one of the answers gets wrong.
        #
        # Every word required, and "also" is the one that matters: it is what
        # makes the other creature a *second* attacker rather than any creature
        # on the board, and the whole card is the difference.
        greater_mark = stream.mark()
        if stream.accept_phrase(
            "unless", "a", "creature", "with", "greater", "power", "also", "attacks"
        ):
            return ast.CombatRestriction(
                subject, "cant_attack_unless_greater_power_attacks", ()
            )
        stream.reset(greater_mark)
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
        # "…can't block **alone**." The blocking half of Mogg Flunkies' word,
        # read here for the reason the attack half is read above its own
        # duration probe: "alone" opens none of the readings below it.
        if stream.accept_word("alone"):
            return ast.CombatRestriction(
                subject, "cant_block_alone", (("count", 1),)
            )
        # "…**unless at least two other creatures block**." (Orcish Conscripts.)
        # The blocking twin of the attack clause above, CR 509.1b's side of the
        # same rule, and read here before the two shapes below because it opens
        # on a word neither of them takes.
        # "This creature can't block **unless a creature with greater power
        # also blocks**." (Okk's second line.) CR 509.1b's side of the rule the
        # attack branch above reads, and the same declaration-wide question:
        # the creatures compared are the ones declared as blockers, which the
        # blocker gate cannot see one pair at a time.
        greater_block = stream.mark()
        if stream.accept_phrase(
            "unless", "a", "creature", "with", "greater", "power", "also", "blocks"
        ):
            return ast.CombatRestriction(
                subject, "cant_block_unless_greater_power_blocks", ()
            )
        stream.reset(greater_block)
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
        # "Target creature can't block **this creature** this turn." (Duct
        # Crawler.) CR 509.1b narrowed to one *named attacker* — the ability's
        # own source — where the `cant_block_subject` branch below narrows to a
        # class of them. The pair (blocker, attacker) is what a block is
        # (CR 509.1a), so this is the denial twin of Trumpeting Armodon's
        # requirement rather than a wording of the blanket.
        #
        # Read in front of the duration probe because the probe is gated on the
        # word "this" and cannot tell "this turn" from "this creature": with
        # the noun unread the sentence refused at "expected a duration after
        # can't block", a refusal naming a word the card does print, two words
        # later than the one it could not read.
        named_mark = stream.mark()
        if stream.at_word("this") and stream.peek_word(1) != "turn":
            blocked = parse_recipient(stream)
            if blocked is not None:
                duration = _parse_duration(stream)
                if duration.kind is None:
                    # A named attacker with no window is a permanent
                    # restriction the card did not print, and the widening
                    # direction on a *denial* is the one that silently gives
                    # the ability more reach than the sentence.
                    raise stream.error(
                        "expected a duration after the attacker this creature "
                        "can't block"
                    )
                return ast.CombatRestriction(
                    subject,
                    "cant_block_named_attacker_until_eot",
                    (("attacker", blocked), ("duration", duration.kind)),
                )
            stream.reset(named_mark)
        # "Creatures without flying can't block this turn." (Destructive
        # Tampering's second mode): no object after "block" — the restriction
        # is a blanket over the *subject*, scoped by the printed duration.
        # Only the durationed form is claimed; a bare "<subject> can't block"
        # would be a static ability and refuses below by falling through.
        #
        # Gated on the words a duration can start with, so the noun read below
        # never has to decline "this turn" — the two readings are told apart by
        # the printed word rather than by one of them failing.
        if stream.at_word("this", "until"):
            duration = _parse_duration(stream)
            if duration.kind is None:
                raise stream.error("expected a duration after \"can't block\"")
            return ast.CombatRestriction(
                subject, "cant_block_until_eot", (("duration", duration.kind),)
            )
        # "…can't block **creatures with power 2 or greater**" (Ironclaw Orcs),
        # "…**white creatures with power 2 or greater**" (Orcish Veteran). The
        # whole noun phrase, through the reader every other narrowed subject in
        # this file uses. It used to be three literal steps — "creatures", "with
        # power", a digit, "or greater" — so a colour in front of the noun was a
        # parse error, and the threshold rode in the instruction *kind*'s name
        # while every other narrowing had nowhere to go.
        described = parse_subject_filter_at(stream, plural=True)
        if described is None:
            raise stream.error(
                "expected what this creature can't block, or a duration"
            )
        return ast.CombatRestriction(
            subject, "cant_block_subject", (("blockees", described),)
        )

    stream.reset(mark)
    return _parse_cant_be(stream, subject)


def parse_block_count_grant(
    stream: TokenStream, subject: "ast.Recipient"
) -> "ast.BlockCountGrant | None":
    """``can block [up to <n>] additional creature(s) <duration>``, or None.

    "That creature can block **up to two additional creatures** this turn."
    (Yare.) CR 509.1b's block-count restriction lifted for a turn, which is the
    one direction the combat productions in this file did not read: everything
    beside it says what a creature may *not* do.

    The count is payload, so "an additional creature" -- the far commoner
    printing, and the one the pool's static form already carries -- is this
    production with a 1 rather than a second one. "Up to" and the bare article
    are the same permission: a ceiling is a ceiling however many of it the
    defender chooses to use, and CR 509.1b never obliges anyone to block at all.

    The duration is **required**. Without one the sentence is a static ability
    ("This creature can block an additional creature each combat"), which
    ``_max_blocks_for`` already derives off the printed text -- so claiming the
    durationless form here would take that reading away and replace it with a
    one-shot that never fires.

    Non-consuming on refusal, like every other "can …" reader, so a sentence
    this cannot finish keeps the refusal it has today.
    """
    mark = stream.mark()
    if not stream.accept_phrase("can", "block"):
        stream.reset(mark)
        return None
    count = 1
    if stream.accept_phrase("up", "to"):
        parsed = _accept_number(stream)
        if parsed is None:
            stream.reset(mark)
            return None
        count = parsed
    elif stream.accept_word("an", "a"):
        pass
    else:
        stream.reset(mark)
        return None
    if not stream.accept_word("additional"):
        stream.reset(mark)
        return None
    if not stream.accept_word("creature", "creatures"):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if duration.kind is None:
        stream.reset(mark)
        return None
    return ast.BlockCountGrant(subject, count, duration)


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
    # "Target creature can't be blocked this turn **except by Walls**."
    # (Joven's Tools.) The whitelist, printed *after* the duration where the
    # blacklist is printed before it — so it is read here rather than beside
    # the "by" clause above, and only once a duration has been consumed. That
    # gate is the whole reason the static printing (Elven Riders, "can't be
    # blocked except by Walls and/or creatures with flying") keeps its tokens
    # and falls through to `engine/combat_restrictions.py` exactly as it did.
    if word == "blocked" and by is None and duration.kind is not None:
        except_mark = stream.mark()
        if stream.accept_phrase("except", "by"):
            allowed = parse_recipient(stream)
            if allowed is None:
                stream.reset(except_mark)
            else:
                return ast.CantBe(subject, word, duration, except_by=allowed)
    if by is not None and duration.kind is None:
        # The static printing. Put the phrase back and let the line fail
        # full-consumption, which is what routes it to the derived table.
        stream.reset(by_mark)
        return ast.CantBe(subject, word, duration)
    return ast.CantBe(subject, word, duration, by=by)


def _parse_becomes_blocked(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.BecomeBlocked | None":
    """``<subject> becomes blocked`` (Dazzling Beauty; CR 509.1h).

    Returns None with the cursor untouched when the word after "becomes" is
    anything else, so every colour and creature-body reading of the same verb
    keeps its own production and its own refusal. It is read here rather than
    as a branch of that one because *blocked* is not a characteristic — the
    type/colour production is about CR 613 layers and this is about a combat.
    """
    mark = stream.mark()
    if not stream.accept_word("becomes", "become"):
        stream.reset(mark)
        return None
    if not stream.accept_word("blocked"):
        stream.reset(mark)
        return None
    return ast.BecomeBlocked(subject)


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
    frees = _accept_freed_blockers_restatement(stream)
    return ast.RemoveFromCombat(subject, frees_blocked_attackers=frees)


def _accept_freed_blockers_restatement(stream: TokenStream) -> bool:
    """Consume ", and creatures it was blocking that had become blocked by only
    that creature this combat become unblocked" (Imprison), reporting whether it
    was there.

    It is **not** a restatement, which is what this comment used to say. CR
    506.4 takes the creature out of combat and CR 509.1h then keeps the attacker
    blocked — "a creature remains blocked even if all the creatures blocking it
    are removed from combat" — so unblocking it is something Imprison, Ydwen
    Efreet and False Orders each *add*, and every one of them prints the
    sentence for that reason. Carried as payload, therefore, rather than
    consumed and forgotten: the removal itself must not do it, or a card printed
    without the clause would inherit three cards' extra sentence.

    Consumed rather than *ignored* because a production must claim every token
    of its line: left over, these words would fail the line at "unconsumed text"
    and Imprison would stay unsupported with both of its halves working.

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
            return False
    # "that creature" (False Orders, Imprison) and "this creature" (Ydwen
    # Efreet) are the same referent printed two ways — the creature the
    # sentence just removed.
    if not stream.accept_word("that", "this"):
        stream.reset(mark)
        return False
    for word in ("creature", "this", "combat", "become", "unblocked"):
        if not stream.accept_word(word):
            stream.reset(mark)
            return False
    return True


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


def _parse_assigns_combat_damage_as_unblocked(
    stream: TokenStream, subject: ast.Recipient
) -> "ast.AssignsCombatDamageAsUnblocked | None":
    """``<subject> assign their combat damage <duration> as though they weren't
    blocked.`` (Outmaneuver.)

    The mirror of :func:`_parse_assigns_no_combat_damage` beside it — the
    refusal that function's docstring promised to leave room for, arriving with
    the card that prints it — and read *before* it for no reason but that both
    open on the same verb; the two diverge on the next word and neither can
    swallow the other.

    Both printed numbers of the pronoun, because the sentence prints one per
    subject: "their … they weren't" for a plural subject and "its … it weren't"
    for a singular one are the same rewrite, and a production that read only one
    would refuse the other on a word that means nothing to the rule.

    The duration is printed **between** the object and the "as though" clause
    ("assign their combat damage **this turn** as though …"), which is where
    this card puts it and why the duration is read there rather than at the end.
    Returns None with the cursor untouched for any other reading of "assign".
    """
    mark = stream.mark()
    if not stream.accept_word("assigns", "assign"):
        return None
    if not (
        stream.accept_phrase("their", "combat", "damage")
        or stream.accept_phrase("its", "combat", "damage")
    ):
        stream.reset(mark)
        return None
    duration = _parse_duration(stream)
    if not (
        stream.accept_phrase("as", "though", "they", "weren't", "blocked")
        or stream.accept_phrase("as", "though", "it", "weren't", "blocked")
    ):
        stream.reset(mark)
        return None
    return ast.AssignsCombatDamageAsUnblocked(subject, duration)


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


def _parse_choose_blocks_for_defenders(
    stream: TokenStream,
) -> "ast.ChooseBlocksForDefenders | None":
    """``You choose which creatures block <duration> and how those creatures
    block.`` (Melee.) CR 509.1a with the chooser substituted.

    Returns None without consuming when the sentence is not this one, so every
    other line opening "You …" keeps its own reading — the courtesy the
    paragraph productions are given, and for the same reason: this is tried in
    front of the subject-verb reader, which reads "You" and then wants a verb it
    has ("chooses", not "choose which").

    **Both halves are required.** "Which creatures block" and "how those
    creatures block" are CR 509.1a's two sentences — which of the defender's
    creatures block at all, and which attacker each one is assigned to — and a
    production that shrugged at the second would compile a card that hands over
    half a declaration and leaves the rest with a player the effect never named.

    **Both printed windows parse and only one lowers.** "This combat" is the
    window `_DURATIONS` already knows as `until_end_of_combat` — CR 511.1's end
    of combat step is where a "this combat" effect ends — and "this turn"
    (Master Warcraft) is read here and refused in the *lowering*, because a
    turn-scoped substitution would have to survive the combat reset that clears
    the state holding it. Parsed-and-refused reports the card unsupported naming
    its clause; refusing the words here would hand the line to the derivation
    tables underneath instead.

    The two spellings are matched here rather than through the shared duration
    reader because "this combat" is not in its table, and putting it there would
    newly admit a trailing "this combat" on every other production that reads a
    duration — a window several of them have no lowering for.
    """
    mark = stream.mark()
    if not stream.accept_phrase("you", "choose", "which", "creatures", "block"):
        stream.reset(mark)
        return None
    if stream.accept_phrase("this", "combat"):
        duration = ast.Duration("until_end_of_combat")
    elif stream.accept_phrase("this", "turn"):
        duration = ast.Duration("this_turn")
    else:
        stream.reset(mark)
        return None
    if not stream.accept_phrase(
        "and", "how", "those", "creatures", "block"
    ):
        stream.reset(mark)
        return None
    return ast.ChooseBlocksForDefenders(duration)

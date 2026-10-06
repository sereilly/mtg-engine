"""``<subject> <verb> …`` — the common imperative-with-subject shape.

Split out of `statements` at the thousand-line guard, along the boundary that
module's own docstring had already drawn: it named three productions, and this
is the one that reads a sentence's *opening* — a subject, then the verb it
dispatches into `effects` on. `parse_statement` stays the entry point for a
whole sentence above, and `_parse_statement_body` keeps the shapes that open
with something other than a subject.

One call goes upward. "Each player **may** ante the top card of their library"
takes a whole statement as its action, and reading one is `statements`' job, so
the caller hands `parse_optional_action` in rather than being imported back.
That is the same inversion `delayed`, `postmodifiers` and `lowering/where_x`
make, for the same reason: what differs between callers is only which parser
they already hold.

And one call goes downward. The other half of "a sentence's opening" — the
shapes that print **no** subject — left for `imperatives` at the same guard,
and is asked first: a bare imperative has a subject by CR 608.2c and simply does
not spell it out, so the two readers answer one question in one order rather
than being two parsers.

A second call goes downward, at the same guard one pool later. What is left
here is the verbs whose subject is an *object* — a permanent deals, gets,
fights, blocks — because the whole contiguous run whose branches were gated on
``isinstance(source_spec, ast.PlayerRef)`` left for `player_verbs`. That is
the seam the dispatch had already drawn for itself rather than one chosen for
it: the branches from "adds" through "may" tested the same thing, and nothing
between them did. It is asked in one call at the point its first branch sat and
falls through at the point its last one did, because those branches are arms of
one fall-through chain and their order is the production.
"""

import dataclasses
from . import ast
from .lexer import SELF, WORD
from .conjuncts import (_with_attack_conjunct, _with_damage_conjunct,
                        _with_gained_type_conjunct,
                        _with_keyword_loss_conjunct, _with_predicate_list,
                        _with_untap_conjunct)
from .imperatives import parse_imperative
from .nouns import parse_object_filter
from .player_verbs import parse_player_subject_verb
from .records import accept_player_deed
from .references import _parse_further_subjects, parse_recipient
from .stream import TokenStream
from .durations import _parse_duration
from .phrases import (
    _parse_can_attack_as_though,
    parse_bound_subject,
)
from .effects import (
    _parse_attacks_this_turn_if_able,
    _parse_blocks_this_turn_if_able,
    parse_block_count_grant,
    parse_cant_activate_nonmana_abilities,
    parse_cant_cast_spell_types,
    parse_cant_play_lands,
    _parse_gain_control,
    _parse_assigns_combat_damage_as_unblocked,
    _parse_assigns_no_combat_damage,
    _parse_becomes_blocked,
    _parse_becomes,
    _parse_becomes_base_pt,
    _parse_cant_attack_or_block,
    _parse_no_longer_supertype,
    _parse_can_be_targeted_as_though,
    _parse_damage,
    _parse_doesnt_untap_next_step,
    _parse_fight,
    _parse_gains,
    _parse_gets,
    _parse_has,
    _parse_becomes_aura_enchantment,
    _parse_loses,
    _parse_loses_unspent_mana,
    _parse_wins,
)




#: The seats a sentence describes by what an earlier sentence of the same
#: effect *recorded* about each player, rather than by a board or a choice.
#: ``seats.parse_player_ref`` reads the phrase; this names the kinds for the
#: one reader here that asks.
RECORD_DESCRIBED_SEATS = frozenset({"revealed_fewest"})


def parse_subject_verb(
    stream: TokenStream,
    carried_subject: ast.Recipient | None = None,
    *,
    parse_optional_action,
) -> ast.Statement:
    """``<subject> <verb> …`` — the common imperative-with-subject shape.

    *carried_subject* supplies the subject instead of reading one, for the tail
    of a conjunction that shares the subject printed in front of it: "Target
    player draws a card **and loses 1 life**" names the player once. The subject
    the sentence actually used is left on ``stream.last_subject`` so the sentence
    loop can hand it back on the next join.
    """
    # A sentence with no printed subject — the bare imperative and the whole
    # paragraphs that open on a noun phrase. Split into `imperatives` at the
    # size guard; asked first, and asked even when a subject was *carried*,
    # because that is the order this function has always run them in: the tail
    # of "…and destroy target creature" is claimed by the imperative reader,
    # not by the carried subject's verb table.
    opened = parse_imperative(stream, parse_optional_action=parse_optional_action)
    if opened is not None:
        return opened

    mark = stream.mark()

    # The self-reference token the lexer emits for the card's own name, plus
    # the "it" of a trigger's remainder clause, both denote the source.
    source_spec: ast.Recipient | None = carried_subject
    if carried_subject is not None:
        pass
    elif stream.at_kind(SELF):
        stream.advance()
        source_spec = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
    elif stream.at_word("it"):
        stream.advance()
        # Quantifier ``"it"``, not ``"this"``, and the difference is the whole
        # of ``rebinding.rebind_pronoun_to_event_subject``: a bare pronoun means
        # the source only where the trigger's condition named nothing else, and
        # that rebinder finds one by its quantifier. Spelled ``"this"`` here,
        # the pronoun in a *subject* position was never rebindable — "whenever
        # enchanted creature attacks and isn't blocked, you may have **it**
        # assign no combat damage" pointed at the Aura, which assigns no combat
        # damage in any case. ``parse_recipient`` has always answered "it" with
        # this quantifier; the two positions now read one word one way, and the
        # SELF branch above keeps ``"this"`` because a card naming itself is not
        # a pronoun (see that rebinder's docstring).
        source_spec = ast.TargetSpec("it", ast.ObjectFilter(is_source=True))
    else:
        # "**That creature** deals damage equal to its power to …" (Hunter's
        # Edge): a back-reference to the object the *previous sentence* chose.
        # Read only in the subject position, and deliberately not taught to the
        # shared noun parser — `effects/board.py` explains why, and the reason
        # holds: the phrase turns up all over the pool and a filter naming a
        # card type nobody bound would lower through every one of them.
        #
        # Here it is safe because the quantifier is refused by default: no
        # lowering accepts "that" (`_is_target` answers False), so a sentence
        # that reaches one fails *by name* instead of failing to parse at all.
        # A parse error would blame the subject for a missing production.
        #
        # `parse_recipient` runs first, and that order is load-bearing: "that
        # creature**'s controller**" is a *player* reference it already reads,
        # and a bound-subject reader that got there first would eat the noun and
        # strand the possessive — which is exactly what it did to Gloom Sower.
        source_spec = parse_recipient(stream) or parse_bound_subject(stream)
        # "…**each player who tapped a land for mana this turn** sacrifices a
        # land of their choice." (Desolation.) A relative clause narrowing
        # *which seats* the sentence is about, sitting between the subject and
        # its verb — so it is read here, where the subject was, rather than by
        # the production the verb dispatches into, which never sees these words.
        #
        # Gated on the verb that follows, for the reason `effects/damage.py`
        # gives for reading "who attacked this turn" beside the one lowering
        # that honours it: a seat narrowing nothing enforces is a sentence that
        # acts on **every** player, silently and in the caster's favour. The
        # sacrifice lowering is the reader; under any other verb the clause is
        # put back and the line fails on it as unconsumed text, which is the
        # loud direction.
        if isinstance(source_spec, ast.PlayerRef):
            deed_at = stream.mark()
            deed = accept_player_deed(stream, parse_object_filter)
            if deed is not None and stream.at_word("sacrifices", "sacrifice"):
                source_spec = dataclasses.replace(source_spec, did=deed)
            else:
                stream.reset(deed_at)
        # "**Each attacking creature and each blocking creature** doesn't untap
        # during its controller's next untap step." (Spore Cloud.) One verb over
        # a union of *subject* noun phrases — the mirror of the union
        # `_parse_further_subjects` already reads in the object position, and
        # the same answer to it: no single ``ObjectFilter`` says "attacking or
        # blocking" without also saying "and", so the union lives in the shape.
        #
        # The clause is re-read once per phrase through ``carried_subject``,
        # which is the mechanism a shared subject already uses in the other
        # direction ("target player draws a card **and loses 1 life**"). Reading
        # it once and rewriting the statement's subject field would work only
        # for the statements that happen to have one.
        #
        # Safe to probe here because at this point the next token is the
        # sentence's verb on every line the pool prints: an "and" this early
        # cannot be joining two clauses, since the first has no verb yet.
        # ``_parse_further_subjects`` rewinds whole unless a separator really is
        # followed by an object-quantified noun phrase.
        if source_spec is not None and stream.at_word("and"):
            shared = _parse_further_subjects(
                stream, source_spec, before_verb=True
            )
            if shared:
                verb_at = stream.mark()
                parts = []
                for subject in (source_spec, *shared):
                    stream.reset(verb_at)
                    parts.append(
                        parse_subject_verb(
                            stream, subject,
                            parse_optional_action=parse_optional_action,
                        )
                    )
                return ast.Conjunction(tuple(parts))

    if source_spec is None:
        stream.reset(mark)
        raise stream.error("expected a subject")
    # "Two target creatures **each** get +2/+2 until end of turn." (Symbiosis.)
    # The distributive word between a counted plural subject and its verb, which
    # says nothing the count did not already say: CR 601.2c gives the sentence
    # two chosen objects either way, and every one of them is pumped. Consumed
    # here, at the subject, rather than in each verb's production — it can
    # precede any of them, and a per-verb probe would be the same word read in
    # a dozen places, with the eleven that forgot refusing at "unrecognized
    # effect verb" while the twelfth worked.
    #
    # Gated on a subject that really is **several** objects, which is what keeps
    # this from eating a word other sentences use as a quantifier of their own:
    # "each player draws a card" opens on "each" as the subject, and by this
    # point that word is already inside `source_spec`. A singular subject
    # followed by "each" is a sentence nobody prints, and it keeps its refusal.
    if (
        isinstance(source_spec, ast.TargetSpec)
        and source_spec.quantifier in ("exactly", "up_to", "one_or_more",
                                       "any_number")
        and (source_spec.count_from_x or source_spec.count > 1
             or source_spec.quantifier in ("one_or_more", "any_number"))
        and stream.at_word("each")
    ):
        stream.advance()
    # "The player who revealed the fewest items **then** loses half their
    # life, rounded up." (Goblin Game.) The sequencing word printed after the
    # subject instead of in front of the sentence, where the sentence loop
    # already reads it ("Then each player …") and for that reader's reason: the
    # steps of a line run in printed order, so the word says nothing the order
    # did not.
    #
    # Only behind a seat a *record* describes. That is where the word earns its
    # place — the seat does not exist until the sentence in front has been
    # carried out — and it keeps "then" out of every other subject's sentence,
    # where it opens the next clause ("…, then that player discards a card").
    if (
        isinstance(source_spec, ast.PlayerRef)
        and source_spec.kind in RECORD_DESCRIBED_SEATS
    ):
        stream.accept_word("then")
    stream.last_subject = source_spec
    after_subject = stream.mark()

    token = stream.peek()
    if token is None:
        stream.reset(mark)
        raise stream.error("expected a verb")

    if token.kind == WORD:
        source_target = source_spec if isinstance(source_spec, ast.TargetSpec) else None
        if token.text in ("deals", "deal"):
            # "{T}: This creature deals 2 damage to any target **and doesn't
            # untap during your next untap step**." (Reveka, Wizard Savant.)
            # The same tail the two pump verbs below already carry, on the
            # third verb that prints it: one noun phrase printed once, two
            # things said about it. Left unread the clause is unconsumed text
            # and takes the whole line down, which is what it did.
            # "…this creature deals 3 damage to you **and attacks this turn if
            # able**." (Kookus.) The third tail this verb carries, read outside
            # the untap one rather than nested inside it: a sentence prints one
            # of them, and nesting would make the order they are tried a fact
            # about which card was written first.
            return _with_attack_conjunct(
                stream,
                _with_untap_conjunct(
                    stream, _parse_damage(stream, source_target), source_target
                ),
                source_target,
            )
        if token.text in ("fights", "fight"):
            return _parse_fight(stream, source_spec)
        if token.text in ("gets", "get"):
            # "…gets +1/+0 **and becomes an artifact in addition to its other
            # types**." (Thran Forge.) The fourth tail this verb carries, read
            # outside the other two rather than nested inside them for the
            # reason the "deals" branch above gives: a sentence prints one of
            # them, and nesting would make the order they are tried a fact
            # about which card was written first.
            return _with_predicate_list(stream, _with_gained_type_conjunct(
                stream,
                _with_untap_conjunct(stream, _with_damage_conjunct(
                    stream, _parse_gets(stream, source_spec), source_target
                ), source_target),
                source_target,
            ), source_target)
        if token.text in ("gains", "gain"):
            # "**You** gain control of that land until end of turn."
            # (Wellspring.) CR 608.2c gives an effect with no printed subject
            # to the object's controller, so the pronoun says nothing the
            # bare imperative did not — but the verb table reaches
            # `_parse_gains`, which expects a keyword and refuses with
            # "expected a keyword ability". Tried first and non-consuming on
            # refusal (`_parse_gain_control` returns None unless the line
            # really opens "gain control"), so "gains flying" and "you gain 3
            # life" keep the readings they have.
            if isinstance(source_spec, ast.PlayerRef) and source_spec.kind == "you":
                control = _parse_gain_control(stream)
                if control is not None:
                    return control
            # "Target creature gains flying **and becomes blue until end of
            # turn**." (Disciple of Kangee.) The tail the pump verb above
            # already carries, on the second verb that prints it: one target
            # (CR 601.2c), a keyword and a colour, one window.
            return _with_predicate_list(stream, _with_gained_type_conjunct(
                stream,
                _with_untap_conjunct(stream, _with_damage_conjunct(
                    stream, _parse_gains(stream, source_spec), source_target
                ), source_target),
                source_target,
            ), source_target)
        if token.text in ("loses", "lose"):
            # "…**that player loses all unspent mana**" (Drain Power, Mana
            # Short), "…**lose all unspent mana**" (Pygmy Hippo, under the
            # causative above). Read in front of `_parse_loses`, which is about
            # life and keywords and refused the clause with "expected a keyword
            # ability" — a message about the wrong half of the verb table.
            # Non-consuming on refusal, so every other "loses …" keeps its own
            # reading.
            if isinstance(source_spec, ast.PlayerRef):
                drained = _parse_loses_unspent_mana(stream, source_spec)
                if drained is not None:
                    return drained
            # "This creature **loses this ability and becomes an Aura
            # enchantment with enchant creature**." (Tempest's five Licids.)
            # The same verb about an *ability* rather than about life or a
            # keyword, and the same shape the two readings above have: tried
            # first, non-consuming on refusal, so every other "loses …" keeps
            # the reading it has. Left to `_parse_loses` the clause died on
            # "expected a keyword ability" — a message about the wrong half of
            # the verb table again.
            licid = _parse_becomes_aura_enchantment(stream, source_spec)
            if licid is not None:
                return licid
            return _parse_loses(stream, source_spec)
        if token.text in ("wins", "win"):
            return _parse_wins(stream, source_spec)
        if token.text in ("has", "have"):
            return _parse_has(stream, source_spec)
        # The player-subject run — every branch from "adds" through "may" was
        # gated on ``isinstance(source_spec, ast.PlayerRef)``, so it left whole
        # for `player_verbs` at the size guard. Asked here, where its first
        # branch sat, and falling through here, where its last one did: the
        # branches are arms of one fall-through chain and their order is the
        # production.
        seat_verb = parse_player_subject_verb(
            stream, token, source_spec,
            parse_optional_action=parse_optional_action,
            parse_subject_verb=parse_subject_verb,
        )
        if seat_verb is not None:
            return seat_verb
        # "This creature **assigns no combat damage** this turn." (Floral
        # Spuzzem.) Non-consuming on refusal, so any other sentence opening
        # with the word keeps its own refusal rather than failing on words this
        # production expected.
        if token.text in ("assigns", "assign"):
            # "X target blocked creatures **assign their combat damage this
            # turn as though they weren't blocked**." (Outmaneuver.) Tried in
            # front of the "assigns no combat damage" reader beside it because
            # both open on the verb and diverge on the next word; each is
            # non-consuming on refusal, so neither can take the other's
            # sentence or replace its refusal.
            as_unblocked = _parse_assigns_combat_damage_as_unblocked(
                stream, source_spec
            )
            if as_unblocked is not None:
                return as_unblocked
            no_damage = _parse_assigns_no_combat_damage(stream, source_spec)
            if no_damage is not None:
                return no_damage
        # "**Target creature** attacks this turn if able." (Boiling Blood.) The
        # production already existed for Kookus' trailing conjunct; nothing had
        # ever asked it at the head of a sentence, so a card printing the clause
        # on its own refused at "unrecognized effect verb" and compiled to its
        # second line alone.
        #
        # Non-consuming on refusal, and that is load-bearing rather than
        # habitual: "attacks **each combat** if able" is a printed static
        # `engine/combat_restrictions.py` reads as a table, and a production
        # that consumed the verb would take the table's line away
        # (CLAUDE.md: parsed-but-unlowered is still parsed).
        if token.text in ("attacks", "attack"):
            requirement = _parse_attacks_this_turn_if_able(stream, source_spec)
            if requirement is not None:
                return requirement
        # "**Target creature** blocks this creature this turn if able."
        # (Trumpeting Armodon.) The blocking twin of the requirement above,
        # beside it rather than inside it because the two share the duration and
        # the escape and nothing else: a block names *two* creatures and an
        # attack names one.
        #
        # Non-consuming on refusal for the same load-bearing reason: "blocks
        # **each combat** if able" is a printed static
        # `engine/combat_restrictions.py` reads as a table (Watchdog), and a
        # production that consumed the verb would take the table's line away.
        if token.text in ("blocks", "block"):
            requirement = _parse_blocks_this_turn_if_able(stream, source_spec)
            if requirement is not None:
                return requirement
        if token.text in ("becomes", "become"):
            # "Target unblocked attacking creature **becomes blocked**."
            # (Dazzling Beauty; CR 509.1h.) Tried before the type/colour
            # production and non-consuming on refusal, because *blocked* is not
            # a characteristic: that production is about CR 613 layers and this
            # is about a combat, and folding the word into it would put a
            # combat fact in the layer system's vocabulary.
            blocked = _parse_becomes_blocked(stream, source_spec)
            if blocked is not None:
                return blocked
            # "…becomes a 3/2 Construct artifact creature **and loses
            # flying**." (Chimeric Sphere.) The tail the two pump verbs already
            # carry, on the verb that prints it here — one noun phrase, two
            # things said about it, and left unread it is unconsumed text that
            # refuses the whole line.
            # "…becomes black**, gets +1/-1, and gains** "{B}: Regenerate this
            # creature."" (Defiling Tears.) The listed spelling of the same
            # join, read outside it: a sentence prints one or the other.
            return _with_predicate_list(stream, _with_keyword_loss_conjunct(
                stream,
                _parse_becomes(stream, source_spec),
                source_target,
            ), source_target)
        # "This creature**'s power becomes** the toughness of target creature
        # …" (Sworn Defender). CR 613.4b's rewrite in the possessive voice,
        # where the verb belongs to a *characteristic* of the subject rather
        # than to the subject itself — so the dispatcher's own token is the
        # possessive marker and not a verb at all. Non-consuming on refusal:
        # "'s" opens sentences this has no business claiming, and one it cannot
        # finish keeps the "unrecognized effect verb" it already had.
        if token.text == "'s":
            rewritten = _parse_becomes_base_pt(stream, source_spec)
            if rewritten is not None:
                return rewritten
        # "Target snow land **is no longer snow**." (Arcum's Weathervane.)
        # Non-consuming on refusal: "is" opens sentences this has no business
        # claiming, so anything it cannot finish keeps its own refusal.
        if token.text in ("is", "are"):
            thawed = _parse_no_longer_supertype(stream, source_spec)
            if thawed is not None:
                return thawed
        if token.text in ("phases", "phase"):
            # "Target creature you don't control phases out." (Teferi, Master
            # of Time) / "Each creature target opponent controls phases out.
            # Until the end of your next turn, they can't phase in." (Teferi,
            # Timeless Voyager). The rider is read here so its words cannot be
            # shed — a phase-out that could be answered by phasing straight
            # back in is a strictly smaller effect.
            stream.advance()
            stream.expect_word("out")
            blocked = False
            mark2 = stream.mark()
            if stream.accept_punct("."):
                if (
                    stream.accept_phrase("until", "the", "end", "of", "your", "next", "turn")
                    and (stream.accept_punct(",") or True)
                    and stream.accept_phrase("they", "can't", "phase", "in")
                ):
                    blocked = True
                else:
                    stream.reset(mark2)
            return ast.PhaseOut(source_spec, cant_phase_in_until_your_next_turn=blocked)
        # "<subject> can attack [this turn] as though it didn't have defender"
        # (CR 609.4). Tried before nothing else claims the word — "can" opens no
        # other production — and non-consuming on refusal, so a sentence this
        # cannot finish keeps the refusal it has today.
        if token.text == "can":
            permission = _parse_can_attack_as_though(stream, source_spec)
            if permission is not None:
                return permission
            # "<self> can be the target of spells and abilities controlled by
            # target player as though it didn't have shroud" (Autumn Willow) —
            # the same "as though" permission (CR 609.4) about a different
            # restriction, so it is tried beside its twin rather than inside
            # it: the two share the auxiliary and nothing else, and both refuse
            # without consuming.
            waived = _parse_can_be_targeted_as_though(stream, source_spec)
            if waived is not None:
                return waived
            # "<subject> can block up to two additional creatures this turn"
            # (Yare) — CR 509.1b's block-count ceiling raised rather than an
            # "as though" waiver, so it is a third reader beside the two above
            # rather than a branch inside either: all three share the auxiliary
            # and nothing else, and all three refuse without consuming.
            blocks = parse_block_count_grant(stream, source_spec)
            if blocks is not None:
                return blocks
        if token.text in ("can't", "cannot"):
            # "…**can't phase out**" (Spatial Binding, CR 702.26). Read ahead of
            # the combat dispatcher below, which is the `can't` production for
            # attacking and blocking and refuses everything else with "expected
            # 'be'" — a refusal naming a word this sentence never prints.
            #
            # Beside the `phases out` branch above rather than inside it, for
            # the reason `auras.py` keeps a keyword removal separate from a
            # keyword grant: an action and the restriction forbidding it are
            # opposite contributions, and one production reading both is one
            # place for the negation to be dropped. Non-consuming on refusal, so
            # every other `can't` sentence keeps the refusal it has today.
            phase_mark = stream.mark()
            stream.advance()
            if stream.accept_phrase("phase", "out"):
                # The trailing spelling. The *fronted* one — Spatial Binding's
                # "Until your next upkeep, target permanent can't phase out" —
                # arrives through `sentence_clauses._distribute_duration`, which
                # fills the node's `duration` field after the fact; that is why
                # the field is a `Duration` node with an empty default rather
                # than the string the lock itself is keyed by.
                return ast.CantPhaseOut(source_spec, _parse_duration(stream))
            # "Target player **can't play lands** this turn." (Solfatara,
            # CR 305.1.) Beside the phase-out reader above and for its reason:
            # the combat production below is the `can't` reader for attacking
            # and blocking and refuses everything else with "expected 'be'" — a
            # word this sentence never prints, and the refusal that hid this
            # card's first line while its second line kept it "supported".
            lands = parse_cant_play_lands(stream, source_spec)
            if lands is not None:
                return lands
            # "Until end of turn, target player **can't cast instant or sorcery
            # spells**, and that player **can't activate abilities that aren't
            # mana abilities**." (Abeyance.) Two more readers beside the two
            # above and for their reason: the combat production below is the
            # `can't` reader for attacking and blocking and refuses everything
            # else with "expected 'be'" — a word neither of these sentences
            # prints, and the refusal that hid Abeyance's whole first line while
            # its second line ("Draw a card.") kept the card "supported".
            forbidden = parse_cant_cast_spell_types(stream, source_spec)
            if forbidden is not None:
                return forbidden
            activations = parse_cant_activate_nonmana_abilities(
                stream, source_spec
            )
            if activations is not None:
                return activations
            stream.reset(phase_mark)
            return _parse_cant_attack_or_block(stream, source_spec)
        # "Those creatures **don't untap** during their controller's next untap
        # step." (Frost Breath.) The verb is checked before dispatching, not
        # inside the production: "You don't lose the game for having 0 or less
        # life" (Lich) is the same auxiliary, and a dispatch on the auxiliary
        # alone replaced its "unrecognized effect verb" with a refusal naming a
        # word Lich never prints. A line this branch cannot finish keeps the
        # refusal it already had.
        if token.text in ("don't", "doesn't") and stream.peek_word(1) == "untap":
            return _parse_doesnt_untap_next_step(
                stream, _untap_subject(source_spec)
            )

    # "**You** exile the top ten cards of your library." (Diminishing Returns.)
    # "**You** search your library for a card…" (Library of Lat-Nam.) CR 608.2c
    # gives an effect with no printed subject to the object's controller, so
    # spelling the pronoun out says nothing the bare imperative did not — the
    # word is the same sentence's subject written down. Handed back to this
    # function with the cursor past it, exactly as the "puts" branch above
    # already does for one verb, rather than to a second copy of the imperative
    # chain: that chain's *ordering* is the whole of what it is.
    #
    # Last, after every verb branch above has declined, so no reading this
    # function already had is shadowed — the pronoun still means the seat
    # wherever "you draw", "you gain" or "you may" has its own production. And
    # the inner refusal is the one that propagates, because a sentence whose
    # verb is read and whose object is not should say so: "unrecognized effect
    # verb" over `_parse_put_counter`'s real complaint names the wrong problem.
    if (
        carried_subject is None
        and isinstance(source_spec, ast.PlayerRef)
        and source_spec.kind == "you"
    ):
        stream.reset(after_subject)
        return parse_subject_verb(
            stream, parse_optional_action=parse_optional_action
        )

    stream.reset(mark)
    raise stream.error("unrecognized effect verb")


def _untap_subject(subject: "ast.Recipient | None") -> "ast.Recipient | None":
    """*subject* as the untap restriction reads it — the plural pronoun made a
    bound set.

    "Tap all creatures that blocked this creature this turn. **They** don't
    untap during their controller's next untap step." (Joven's Ferrets.) The
    subject reader has no verb in hand when it meets "they", and reads it as a
    *seat* (``that_player``) — which is what the word means in front of every
    other verb it opens ("they lose 1 life", "they sacrifice a creature"). CR
    502.1 untaps permanents and never players, so in front of this one verb the
    same word is the plural of "those creatures": the objects the sentence
    before it acted on.

    Rewritten here rather than in the subject reader, and rewritten to the
    quantifier the bound plural already carries rather than to a second
    spelling of it — so the lowering keeps one branch, and its producer gate
    (a set really was recorded) applies to both printings.
    """
    if isinstance(subject, ast.PlayerRef) and subject.kind == "that_player":
        return ast.TargetSpec(quantifier="those", filter=ast.ObjectFilter())
    return subject

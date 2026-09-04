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
and is asked first: a bare imperative has a subject by CR 101.1 and simply does
not spell it out, so the two readers answer one question in one order rather
than being two parsers.
"""

import dataclasses
from . import ast
from .errors import GrammarError
from .lexer import SELF, WORD
from .paragraphs import _parse_name_then_reveal_top
from .conjuncts import _with_damage_conjunct, _with_untap_conjunct
from .imperatives import parse_imperative
from .references import parse_recipient
from .stream import TokenStream
from .phrases import (
    _accept_mana_alternatives,
    _accept_life_alternative,
    _parse_can_attack_as_though,
    _parse_duration,
    _parse_mana_payment,
    parse_bound_subject,
)
from .effects import (
    parse_block_count_grant,
    _parse_ante,
    _parse_gain_control,
    _parse_assigns_no_combat_damage,
    _parse_becomes,
    _parse_becomes_base_pt,
    _parse_cant_attack_or_block,
    _parse_no_longer_supertype,
    _parse_play_with_hand_revealed,
    _parse_can_be_targeted_as_though,
    _parse_damage,
    _parse_discard,
    _parse_discard_revealed_unless_pay_life,
    _parse_reveal_hand,
    _parse_doesnt_untap_next_step,
    _parse_draw,
    _parse_further_subjects,
    _parse_exile_entire_library,
    _parse_fight,
    _parse_gains,
    _parse_gets,
    _parse_has,
    _parse_loses,
    _parse_mill,
    _parse_skip_step,
    parse_player_looks_at_own_library_top,
    parse_player_separates_your_library_top,
    _parse_player_adds_mana,
    _parse_player_puts_hand_cards_on_library,
    _parse_player_puts_whole_hand_on_library,
    _parse_repeated_graveyard_pick,
    _parse_return,
    _parse_sacrifice,
    parse_player_chooses_permanent,
    _parse_tap_untap,
    _parse_wins,
)




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
            shared = _parse_further_subjects(stream, source_spec)
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
            return _with_untap_conjunct(
                stream, _parse_damage(stream, source_target), source_target
            )
        if token.text in ("fights", "fight"):
            return _parse_fight(stream, source_spec)
        if token.text in ("gets", "get"):
            return _with_untap_conjunct(stream, _with_damage_conjunct(
                stream, _parse_gets(stream, source_spec), source_target
            ), source_target)
        if token.text in ("gains", "gain"):
            # "**You** gain control of that land until end of turn."
            # (Wellspring.) CR 101.1 gives an effect with no printed subject
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
            return _with_untap_conjunct(stream, _with_damage_conjunct(
                stream, _parse_gains(stream, source_spec), source_target
            ), source_target)
        if token.text in ("loses", "lose"):
            return _parse_loses(stream, source_spec)
        if token.text in ("wins", "win"):
            return _parse_wins(stream, source_spec)
        if token.text in ("has", "have"):
            return _parse_has(stream, source_spec)
        if token.text in ("adds", "add") and isinstance(source_spec, ast.PlayerRef):
            return _parse_player_adds_mana(stream, source_spec)
        if token.text in ("draws", "draw") and isinstance(source_spec, ast.PlayerRef):
            return _parse_draw(stream, source_spec)
        if token.text in ("discards", "discard") and isinstance(source_spec, ast.PlayerRef):
            # "…**discards it unless they pay 1 life**." (Wand of Ith.) "It" is
            # the card the sentence in front of this one revealed, so nothing is
            # chosen and there is no count — read first, and declining without
            # consuming leaves every ordinary discard its own reading.
            bought_off = _parse_discard_revealed_unless_pay_life(stream, source_spec)
            if bought_off is not None:
                return bought_off
            return _parse_discard(stream, source_spec)
        # "…have **defending player play with their hand revealed** for as long
        # as this creature remains on the battlefield." (Stromgald Spy.) The
        # causative "you may have <player> <verb>" above has already taken its
        # subject and left the uninflected verb, which is why both spellings
        # are read. Non-consuming on refusal: "play" opens sentences this has no
        # business claiming — a land, a subgame, an additional turn — and one it
        # cannot finish keeps its own refusal.
        if token.text in ("plays", "play") and isinstance(source_spec, ast.PlayerRef):
            revealed = _parse_play_with_hand_revealed(stream, source_spec)
            if revealed is not None:
                return revealed
        if token.text in ("mills", "mill") and isinstance(source_spec, ast.PlayerRef):
            return _parse_mill(stream, source_spec)
        # "**Target player** looks at the top three cards of their library…"
        # (Ashnod's Cylix.) The look-and-pick template with its looker printed:
        # every other card in that family looks at its own controller's library,
        # so "your library" was a literal and the seat was never a field.
        # Dispatched on the verb like every other player action, and the
        # production declines without consuming — "Look at target player's
        # hand" and Visions' look at somebody else's library top keep their own
        # readings, which are reached from the bare imperative and not from
        # here.
        if token.text in ("looks", "look") and isinstance(source_spec, ast.PlayerRef):
            looked = parse_player_looks_at_own_library_top(stream, source_spec)
            if looked is not None:
                return looked
            # "Target opponent looks at the top ten cards of **your** library
            # and separates them into two face-down piles." (Phyrexian
            # Portal.) The same four opening words as the production above and
            # a different card from the possessive on: somebody else is
            # looking through the ability controller's deck. Tried second and
            # declining without consuming, exactly as that one does.
            separated = parse_player_separates_your_library_top(
                stream, source_spec
            )
            if separated is not None:
                return separated
        if token.text in ("skips", "skip") and isinstance(source_spec, ast.PlayerRef):
            return _parse_skip_step(stream, source_spec)
        # "**That player** exiles all cards from their library." (Thought
        # Lash.) The only player-subject sentence in the exile family;
        # declines without consuming, so every other printed exile keeps the
        # bare-imperative reading below.
        if token.text in ("exiles", "exile") and isinstance(source_spec, ast.PlayerRef):
            emptied = _parse_exile_entire_library(stream, source_spec)
            if emptied is not None:
                return emptied
        # "…and **you tap** that creature." (Mind Whip.) Tapping has no actor in
        # the rules — CR 701.20a turns a permanent sideways and says nothing
        # about who does it — so the printed subject is read and then dropped
        # rather than carried: the same instruction results whoever the sentence
        # names. Read here because only the bare imperative had a production, so
        # a printed subject came back as an unrecognized verb.
        if token.text in ("taps", "tap", "untaps", "untap") and isinstance(
            source_spec, ast.PlayerRef
        ):
            return _parse_tap_untap(stream)
        # "**Target player** reveals their hand." (Inquisition.) "Target player
        # **reveals their hand** and discards all nonland cards." (Amnesia.)
        # Dispatched on the verb like every other player action; the Duress
        # paragraph that opens with the same three words is read whole, before
        # the sentence parser ever reaches here. Declines *without consuming*
        # when the reveal names something other than a hand, so "reveals the top
        # card of their library" keeps its own reading and its own error — the
        # production returns ``Statement | None``, so returning it unconditionally
        # would hand None back as if it were a parse.
        if token.text in ("reveals", "reveal") and isinstance(source_spec, ast.PlayerRef):
            revealed = _parse_reveal_hand(stream, source_spec)
            if revealed is not None:
                return revealed
        # "**Each player** returns all creature cards from their graveyard to
        # the battlefield." (All Hallow's Eve.) The return production with a
        # printed subject: only the bare imperative ("Return target creature
        # card…", which means you) had a reading, so a named returner was an
        # unrecognized verb. The subject is handed to the production, which
        # records it — who returns the cards is who they come back under the
        # control of (CR 110.2), and dropping it would give one player the
        # table's graveyards.
        if token.text in ("returns", "return") and isinstance(source_spec, ast.PlayerRef):
            return _parse_return(stream, source_spec)
        # "Target player **chooses a card name**, then reveals the top card of
        # their library…" (Petra Sphinx) — a paragraph, because the two
        # sentences after it test the name and the card this one produced.
        # Dispatched on the verb like every other player action; the production
        # reads its own words to the end.
        if token.text in ("chooses", "choose") and isinstance(source_spec, ast.PlayerRef):
            # "That creature's controller **chooses a creature that this card
            # could enchant**." (Takklemaggot.) Read first because it declines
            # without consuming, where the paragraph below expects "a card
            # name" from its second word and fails the line on anything else.
            chosen = parse_player_chooses_permanent(stream, source_spec)
            if chosen is not None:
                return chosen
            # "That player **chooses and sacrifices** one of those creatures."
            # (Retribution.) CR 701.21a already makes the sacrificing player the
            # one who picks, so the two printed verbs are one action — the same
            # reading `_parse_sacrifice` gives the "of their choice" it consumes
            # and drops. Read here for the reason every sibling above is: it
            # declines without consuming, and the paragraph at the bottom of
            # this branch expects "a card name" from its second word and would
            # fail the line on "and".
            mark_and_sacrifices = stream.mark()
            stream.advance()
            if stream.accept_word("and") and stream.accept_word(
                "sacrifices", "sacrifice"
            ):
                return _parse_sacrifice(stream, source_spec)
            stream.reset(mark_and_sacrifices)
            # "…**chooses three cards from their hand and puts them on top of
            # their library**" (Stunted Growth). Same reason it is read here:
            # it declines without consuming, and the paragraph below would fail
            # the line on "three".
            to_library = _parse_player_puts_hand_cards_on_library(stream, source_spec)
            if to_library is not None:
                return to_library
            # "Target opponent **chooses a card in your graveyard**…"
            # (Forgotten Lore.) Same reason as the two above: it declines
            # without consuming, where the paragraph below expects "a card
            # name" from its second word and would fail the line on "in".
            repeated = _parse_repeated_graveyard_pick(stream, source_spec)
            if repeated is not None:
                return repeated
            return _parse_name_then_reveal_top(stream, source_spec)
        # "Each opponent sacrifices a creature" (Goremand). The AST node has
        # carried its player since it was written; only the *bare* imperative
        # ("Sacrifice a creature", which means you) had a production, so a
        # printed subject was an unrecognized verb.
        # "Target opponent **puts the cards from their hand on top of their
        # library**." (Jester's Mask.) Dispatched on the verb like every other
        # player action; the production declines without consuming, so the
        # subject-verb table below still sees every other "puts" sentence.
        if token.text in ("puts", "put") and isinstance(source_spec, ast.PlayerRef):
            whole_hand = _parse_player_puts_whole_hand_on_library(stream, source_spec)
            if whole_hand is not None:
                return whole_hand
            # "…and **you put** a cube counter on this artifact" (Delif's Cube).
            # The imperative with its subject spelled out, which CR 101.1 makes
            # the same sentence — so it is handed back to this function with the
            # cursor on the verb rather than to a second copy of the "put" chain
            # above, whose ordering is the whole of what that chain is.
            if source_spec.kind == "you":
                return parse_subject_verb(
                    stream, parse_optional_action=parse_optional_action
                )
        if token.text in ("sacrifices", "sacrifice") and isinstance(source_spec, ast.PlayerRef):
            stream.advance()
            return _parse_sacrifice(stream, source_spec)
        # "Each player antes the top card of their library." (Demonic
        # Attorney.) The subject is who antes (CR 407.4: a card is anted by
        # its owner), so it is handed to the production rather than read back
        # off the possessive.
        if token.text in ("antes", "ante") and isinstance(source_spec, ast.PlayerRef):
            ante = _parse_ante(stream, source_spec)
            if ante is not None:
                return ante
        # "**Each player may** ante the top card of their library." (Rebirth.)
        # The offer with a printed subject other than "you", which the bare
        # "you may" branch in `_parse_statement_body` cannot reach. One offer
        # node either way; who is offered is the actor field it already has,
        # and `handlers/control_flow.may` arms one prompt per named seat.
        if token.text == "may" and isinstance(source_spec, ast.PlayerRef):
            mark_may = stream.mark()
            stream.advance()
            # "**That player** … may pay {R}{R}." (Chain Lightning.) The offer
            # of a *cost* with a printed subject other than "you", which the
            # bare "you may pay" branch in `statements.py` cannot reach. One
            # `May` node either way; who is offered is the actor field it
            # already carries, and `handlers/control_flow.may` arms the prompt
            # for exactly that seat — which is what makes the payment come off
            # the payer's lands rather than the caster's.
            if stream.at_word("pay"):
                mark_pay = stream.mark()
                stream.advance()
                try:
                    cost = _parse_mana_payment(stream, allow_variable=True)
                    # "…may pay {1} **or {2}**" (Winter's Chill): CR 118.8's
                    # alternative in the offered-cost position, through the
                    # fragment the "unless they pay {B} or {3}" penalty uses.
                    # It must be consumed here — `_parse_optional_action`'s own
                    # "or" is next and would read "{2}" as a second *action*.
                    # What each way buys is read behind the sentence, by
                    # `sentence_clauses._accept_graded_toll_outcomes`.
                    # "…may pay {R}{R} **or 2 life**." (Emberwilde Djinn.)
                    # The other currency of CR 118.8's alternative, and it
                    # is read here beside the mana one for that reader's
                    # reason exactly: `_parse_optional_action`'s own "or"
                    # comes next and would take "2 life" for a second
                    # *action*. Two readers rather than one because a mana
                    # alternative is a whole symbol dict and a life one is a
                    # number — the same split `_accept_life_alternative`
                    # already documents one clause over.
                    alternatives = _accept_mana_alternatives(stream)
                    return ast.May(
                        source_spec, cost=cost,
                        cost_alternatives=alternatives,
                        life_alternative=(
                            None if alternatives
                            else _accept_life_alternative(stream)
                        ),
                    )
                except GrammarError:
                    stream.reset(mark_pay)
            # "Target opponent **may choose that** for each 1 damage that would
            # be dealt to you …" (Soul Echo.) An offer with no price at all:
            # what the seat is being asked is whether the sentence behind
            # "that" happens. The words are the offer, so they are consumed and
            # the clause behind them becomes the offered *action* — which is
            # what puts it on the ordinary optional-choice queue with the
            # ability's controller as the one it happens to.
            #
            # Distinct from the "you may **choose to** have it …" spelling one
            # module over, which is the same offer written about the *actor*;
            # here the chooser and the affected player are different seats, and
            # that is the whole reason the card prints a subject.
            if stream.at_word("choose") and stream.peek_word(1) == "that":
                mark_choose = stream.mark()
                stream.advance(2)
                try:
                    return ast.May(
                        source_spec,
                        action=parse_optional_action(stream),
                    )
                except GrammarError:
                    stream.reset(mark_choose)
            # "…its controller **may add** an additional {U}." (Snowfall.) The
            # offer of a *mana production* to a seat the enclosing trigger
            # bound. Routed to the same production the un-offered spelling one
            # branch below reaches, because `parse_optional_action` would read
            # the bare "add …" as :class:`ast.AddMana` — the ability's *own*
            # controller — and pay the wrong player. The word rides the node
            # (CR 605.4a: a triggered mana ability has no priority window in
            # which a prompt could be answered) rather than wrapping it in a
            # `May`, which would hide the production from the tap seam that
            # fires it.
            if stream.at_word("add", "adds"):
                mark_add = stream.mark()
                try:
                    return _parse_player_adds_mana(
                        stream, source_spec, optional=True
                    )
                except GrammarError:
                    stream.reset(mark_add)
            try:
                action = parse_optional_action(stream)
                # "…**they** may copy this spell…" — the copy's controller is
                # the sentence's own subject (CR 707.10a), which is not the
                # resolving spell's controller here. Bound at the one place
                # both facts are in hand rather than guessed in the handler.
                if isinstance(action, ast.CopySpell):
                    action = dataclasses.replace(action, controller=source_spec)
                # "**An opponent may** gain control of a creature you control
                # **of their choice** for as long as this creature remains on
                # the battlefield." (Infernal Denizen.) The same binding the
                # copy above makes — the sentence's subject onto the action —
                # and then the offer *folds into* that action instead of
                # wrapping it, because "may" and "of their choice" are one
                # decision made by one seat: choose one of those creatures, or
                # none. Two nodes would be two prompts to the same player, and
                # two non-interactive defaults that have to agree.
                #
                # Only when the pick is the subject's own ("of their choice").
                # "An opponent may gain control of target creature" is an
                # ordinary offer of an action whose object somebody else
                # already named, and stays a ``May``.
                if isinstance(action, ast.GainControl) and getattr(
                    getattr(action.subject, "filter", None), "their_choice", False
                ):
                    return dataclasses.replace(
                        action, gained_by=source_spec, offered=True
                    )
                # "**That player** may draw a card." (Soldevi Sentry.) The
                # action's subject is elided and it is the *offer's* subject,
                # not the ability's controller — the same binding the mana
                # branch above makes for "…may add {R}", and the same one the
                # copy and the control change make below it.
                #
                # Only the elided form is rebound, and only under "that
                # player". CR 109.5 keeps "you" meaning the ability's
                # controller wherever the card actually prints the word ("an
                # opponent may sacrifice a creature **you control**"), and a
                # bare imperative prints no word at all — which is exactly the
                # difference `parse_optional_action` cannot see from inside the
                # action.
                #
                # The other seat words are left alone because their offers are
                # *collapsed* one layer down: "its controller may draw up to two
                # cards" (Arcane Denial) and "each player may draw…" (Truce)
                # lower to a per-seat draw prompt rather than to an offer with a
                # draw inside it, and rebinding here takes the shape those
                # collapses match on away from them.
                if isinstance(action, ast.Draw) and (
                    isinstance(action.player, ast.PlayerRef)
                    and action.player.kind == "you"
                    and isinstance(source_spec, ast.PlayerRef)
                    and source_spec.kind == "that_player"
                ):
                    action = dataclasses.replace(action, player=source_spec)
                return ast.May(source_spec, action=action)
            except GrammarError:
                stream.reset(mark_may)
        # "This creature **assigns no combat damage** this turn." (Floral
        # Spuzzem.) Non-consuming on refusal, so any other sentence opening
        # with the word keeps its own refusal rather than failing on words this
        # production expected.
        if token.text in ("assigns", "assign"):
            no_damage = _parse_assigns_no_combat_damage(stream, source_spec)
            if no_damage is not None:
                return no_damage
        if token.text in ("becomes", "become"):
            return _parse_becomes(stream, source_spec)
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
    # "**You** search your library for a card…" (Library of Lat-Nam.) CR 101.1
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

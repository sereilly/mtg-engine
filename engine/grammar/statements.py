"""Statement productions: one whole sentence, assembled from effects.

`parse_statement` is the entry point for one sentence, and
`_parse_statement_body` reads the shapes that open with something other than a
subject. The `<subject> <verb> …` opening moved to `subject_verb` at the
thousand-line guard, and `_parse_condition` to `conditions` before it; both are
handed back what they need from here rather than importing upward.

The narrow waist of the parser — below is a fragment, above is a *line*.
"""

import dataclasses

from . import ast
from .errors import GrammarError
from .paragraphs import (_parse_reassign_blockers_between_attackers,
                         _parse_cast_from_exiled_with)
from .choices import _parse_choose_target, _parse_choose_then_gain
from .delayed import (_parse_create_delayed_trigger, delay_binds_an_object,
                      fold_flip_stakes, parse_trailing_delay,
                      resolve_that_turn)
from .references import parse_player_ref
from .stream import TokenStream
from .conditions import _parse_condition
from .where_x import parse_where_x_definition
from .subject_verb import parse_subject_verb
from .rebinding import (rebind_alternative_pronoun_to_choice_target,
                        rebind_counter_pronoun_to_bound_target,
                        rebind_player_pronoun_to_condition_target,
                        rebind_pronoun_to_condition_target)
from .phrases import (_accept_conjoined_life_cost, _accept_life_only_offer,
                      _parse_duration, _parse_mana_payment)
from .effects import (_parse_damage_becomes_counter_removal,
                      _parse_untap_chosen_by_paying,
                      _parse_for_each_destroy_unless_paid,
                      _parse_have_source_deal_damage, _parse_cast_permission,
                      _parse_optional_damage_redirect, _parse_attacking_doesnt_tap,
                      _parse_bound_targeting_prevention, _parse_damage_dealt_riders,
                      _parse_reveal_hand_and_choose,
                      _parse_return_instead_of_untapping,
                      _parse_reveal_hand_and_choose,
                      _parse_count_objects, _parse_produces_instead,
                      _parse_tapped_lands_produce_chosen,
                      _parse_tapper_produces_instead, _parse_spend_mana_as_though,
                      _parse_choose_blocks_for_defenders, _parse_sacrifice,
                      _parse_sacrifice_expansion_permanents,
                      parse_create_token_with_stated_pt,
                      _parse_delayed_self_action, _parse_shuffle_graveyard_into_library,
                      _parse_shuffle_hand_into_library, _parse_shuffle_library,
                      parse_graveyard_top_to_library,
                      _parse_targeting_ban)
from .sacrifices import _parse_counted_sacrifice
from .effects.exile import _parse_bin_unplayed_exiled_card
from .effects.game import parse_extra_land_plays, parse_extra_phases
from .effects.stack import _parse_conditional_retarget
from .effects.cards import _parse_for_each_revealed_discard


from .sentence_clauses import (
    _accept_alternative_sweep,
    _accept_graded_toll_outcomes,
    _distribute_duration,
    _parse_unless_player_pays,
    accept_delayed_toll,
    _accept_trailing_toll,
    _parse_leading_controller_of_each,
    _parse_leading_count_scale,
    _parse_leading_for_each,
    _parse_leading_linked_duration,
    _round_every_half,
)


# ---------------------------------------------------------------------------
# Statement productions
# ---------------------------------------------------------------------------


def parse_statement(stream: TokenStream, *, top_level: bool = True) -> ast.Statement:
    """One sentence's worth of effect, plus the clause that defines its X.

    A thin wrapper, and the wrapper *is* the rule: "…, where X is the number of
    …" binds the whole sentence, so it is read once around the body rather than
    wherever the body happens to stop. The body returns early from several
    branches (`if`, `you may`, a cast permission), and asking each of them to
    remember the clause is how one of them forgets.

    ``top_level`` is False for the body's own recursive calls. A nested call
    taking the clause would define X for its half and leave the other half's X
    undefined — "each opponent loses X life and you gain X life, where X is …"
    gave the definition to the gain, and the loss silently lost nothing.
    """
    body_at = stream.pos
    statement = _parse_statement_body(stream)
    statement = _accept_alternative_sweep(_parse_statement_body, stream, statement, body_at)
    # "<statement> **unless <player> pays <cost>**." The toll, in its trailing
    # printed position. Read around the body rather than inside each verb,
    # because the clause is the same sentence whatever the verb was: Icy Prison
    # sacrifices, Mystic Remora draws, Lim-Dûl's Hex damages, and every one of
    # them is "this happens unless somebody pays". The verbs that fuse their own
    # "unless you pay" (Cosmic Horror's destroy, the upkeep sacrifice) have
    # already consumed the word by the time this runs, so this reader sees only
    # what nothing else claimed.
    #
    # Top level only, and that is the whole of what the recursion gets wrong: a
    # nested body reading the clause would attach it to the *inner* statement,
    # so "you may draw a card unless that player pays {4}" became an offer to
    # draw whose action was the opponent's toll — the two seats' decisions
    # nested the wrong way round.
    if not top_level:
        return statement
    statement = _accept_trailing_toll(_parse_statement_body, stream, statement) or statement
    # "…may pay {1} or {2}. **If that player doesn't**, … **If that player pays
    # only {1}**, …" (Winter's Chill.) The sentences that say what each way of
    # covering the offer buys. Read around the body for the toll's own reason —
    # they modify a sentence already read and name nothing on their own — and
    # top level only, because a nested body's offer is not the one the printed
    # sentences behind this one are about.
    statement = _accept_graded_toll_outcomes(
        _parse_statement_body, stream, statement
    ) or statement
    # "…**at the beginning of your next upkeep**, where X is …" (Hazezon
    # Tamar): the delay printed after its effect rather than in front of it.
    # Read before the where-clause and wrapped *around* it, because the delay
    # governs the whole sentence — the definition included.
    delay = parse_trailing_delay(stream)
    definition = _parse_where_x(stream)
    if definition is not None:
        statement = ast.WhereX(statement, definition)
        # "…, where X is the total power of the creatures sacrificed this way,
        # **then exile this artifact and those creature cards**." (Sword of the
        # Ages.) The comma list inside the body stops at "where" — correctly,
        # since the clause is a modifier and not a step — so a step printed
        # *after* the definition has to be picked up here, where the definition
        # has been consumed. Left to the body it was unconsumed text and refused
        # the whole ability.
        #
        # The definition stays scoped to the sentence it modifies: the tail is a
        # sibling in the sequence rather than another statement inside the
        # WhereX, so an X the tail does not read is an X it is not stamped with.
        tail_mark = stream.mark()
        joined = stream.accept_punct(",")
        if stream.accept_word("then"):
            statement = ast.Sequence(
                (statement, parse_statement(stream, top_level=False))
            )
        elif joined:
            stream.reset(tail_mark)
    if delay is None:
        return statement
    event, once, duration, binds, watches = delay
    if definition is not None:
        # "…, where X is the number of lands you control **at that time**."
        # The words decide which of two different cards this is. Inside the
        # delay the count is taken when the ability *resolves*, which is what
        # "at that time" says; a card meaning the count as it stood when the
        # ability was created would need the number frozen at arming time, and
        # this engine has nowhere to freeze it. So the phrase is required
        # rather than tolerated, and its absence refuses the line instead of
        # counting the wrong board.
        if not stream.accept_phrase("at", "that", "time"):
            raise stream.error(
                "a delayed sentence's X must say when it is counted"
            )
    statement = resolve_that_turn(statement) or statement
    # "…you gain 2 life, **and** you return this card from your graveyard to
    # your hand **at the beginning of the next end step**." (Mangara's
    # Blessing.) A trailing delay attaches to the clause it follows, not to
    # the whole sentence: Magic prints a whole-sentence delay as an *opener*
    # ("At the beginning of …, do X"), which is what `_DELAYED_OPENERS`
    # reads. So the steps in front of the last one stay where they are, and
    # the Blessing gains its 2 life as the trigger resolves rather than an
    # end step later — which on a card printed to be discarded is the
    # difference between surviving the turn and not.
    #
    # Only a sequence built **inside one sentence** is split here, which is
    # the only kind that reaches this point: sentences separated by a full
    # stop are joined one layer up, by `_statements_from_sentences`, after
    # each has already been through this function.
    #
    # Split **before** `fold_flip_stakes` below, and that order is the whole
    # of its safety: that fold *creates* a sequence by pulling the sentence
    # behind the delay into it (Goblin Kites), and a split run afterwards
    # would leave the coin flip happening now and delay only the sacrifice.
    leading: tuple = ()
    if isinstance(statement, ast.Sequence) and len(statement.steps) > 1:
        leading, statement = statement.steps[:-1], statement.steps[-1]
    # "Flip a coin at the beginning of the next end step. **If you lose the
    # flip, sacrifice that creature.**" (Goblin Kites.) The sentence behind the
    # delay reads a value only the delayed effect produces, so it belongs inside
    # the ability rather than beside it — folded before the node is built, which
    # is what lets `delay_binds_an_object` below see the "that creature" it now
    # contains.
    statement = fold_flip_stakes(stream, statement, parse_statement)

    # "…at the beginning of their next upkeep **unless they pay {2} before that
    # step**." (Sabertooth Cobra.) The toll printed behind the delay rather than
    # behind the body, so the reader around the body has already stopped by the
    # time the word arrives. Folded *inside* the delayed ability, because that
    # is when the offer is made — wrapped around the delay it would ask for the
    # payment now and delay only the penalty.
    tolled = accept_delayed_toll(_parse_statement_body, stream, statement)
    if tolled is not None:
        statement = tolled

    def _delay(effect: ast.Statement) -> ast.CreateDelayedTrigger:
        return ast.CreateDelayedTrigger(
            event=event, effect=effect,
            once=once, duration=duration,
            # A permission, not the answer — see ``delay_binds_an_object``.
            binds_target=delay_binds_an_object(binds, effect),
            subject=None, agent=None,
            watches=watches,
        )

    # "**For each** +1/+1 counter you put on a creature this way, remove a +1/+1
    # counter from that creature **at the beginning of the next cleanup step**."
    # (Bounty of the Hunt.) The delay is printed after the loop but modifies the
    # verb *inside* it, so the ability is created once per member (CR 603.7) and
    # each one is about that member — which is also the only reading that can
    # work here: left wrapped around the loop, the loop would run a turn later,
    # by which time the record it iterates is long out of scope and "that
    # creature" names nobody.
    if isinstance(statement, ast.ForEach):
        delayed = dataclasses.replace(statement, effect=_delay(statement.effect))
    else:
        delayed = _delay(statement)
    joined = _accept_conjunct_after_delay(stream, delayed)
    # The steps the delay does not govern, back in front of it and in the
    # order they were printed.
    return ast.Sequence((*leading, joined)) if leading else joined


def _accept_conjunct_after_delay(
    stream: TokenStream, delayed: ast.CreateDelayedTrigger
) -> ast.Statement:
    """``… <delay> and <effect>.`` — a second effect the delay does **not**
    govern.

    "When this creature dies, return it to the battlefield under its owner's
    control **at the beginning of the next end step** and you skip your next
    draw step." (Ivory Gargoyle.) The delay is a postfix on the first conjunct
    and the second belongs to the trigger itself: the skip happens as the death
    trigger resolves, not at the end step.

    Read here, after the node is built, because that is the only place the
    scope is unambiguous — the body parser has already stopped, so an "and" it
    could see would have been swallowed into the delayed half. Before this the
    word was simply unconsumed text and took the whole line down.

    Returns *delayed* unchanged when no conjunct follows, so every line that
    parsed before this existed parses identically.
    """
    mark = stream.mark()
    if not stream.accept_word("and"):
        stream.reset(mark)
        return delayed
    try:
        second = parse_statement(stream, top_level=False)
    except GrammarError:
        stream.reset(mark)
        return delayed
    return ast.Conjunction((delayed, second))


def _parse_statement_body(stream: TokenStream) -> ast.Statement:
    """One sentence's worth of effect, including ``if``/``may`` wrappers."""
    # "**Starting with you**, each player may …" (Eureka.) Which seat answers a
    # multi-seat offer first. Read here, in front of the sentence, because that
    # is where it is printed and because the sentence behind it is an ordinary
    # one — the phrase names the order, not the effect. Attached only to an
    # offer: on anything else the words would be describing a turn order nothing
    # takes, so the line refuses rather than dropping them.
    if stream.at_word("starting"):
        mark = stream.mark()
        stream.advance()
        if stream.accept_word("with"):
            first = parse_player_ref(stream)
            if first is not None and stream.accept_punct(","):
                inner = _parse_statement_body(stream)
                if not isinstance(inner, ast.May):
                    raise stream.error(
                        "'starting with …' orders an offer made to several "
                        "seats, and this sentence makes none"
                    )
                return dataclasses.replace(inner, starting_with=first)
        stream.reset(mark)
    # "Target opponent reveals their hand. You choose … from it. That player
    # discards that card." (Duress.) Read before anything else, because it
    # spans three printed sentences: the sentence loop above would hand the
    # first one to the subject-verb reader, which has no "reveals" and would
    # fail the line on a word that is only the opening of a longer template.
    # "**Unless an opponent pays {2},** gain control of target artifact …"
    # (Scarwood Bandits.) A leading clause that governs the whole sentence, so
    # it is read here rather than inside the effect behind it — the same rule
    # the leading duration and the leading "for each" below follow. The body is
    # an ordinary statement, which is what keeps this from being one production
    # per effect that can be bought off.
    unless_paid = _parse_unless_player_pays(stream, _parse_statement_body)
    if unless_paid is not None:
        return unless_paid
    # "That player may choose any number of tapped creatures without flying
    # they control **and pay {2} for each creature chosen this way**." A toll
    # whose number of payments the payer chooses, so it spans both printed
    # sentences (Mudslide). Read here rather than from the subject-verb reader
    # because the sentence opens with a player and the verb is "may" — the
    # opening the offer productions below already own — and it has to be tried
    # before them, whose "may" branch would take the offer and leave the
    # per-object cost stranded.
    per_object_toll = _parse_untap_chosen_by_paying(stream)
    if per_object_toll is not None:
        return per_object_toll
    # "**For as long as this creature remains tapped,** gain control of …"
    # (Preacher.) A linked duration (CR 611.2b) printed in front of the verb.
    # Read here for the reason the leading duration below is read here — it
    # governs the whole sentence — and handed to the control production rather
    # than distributed like an ordinary one, because a linked duration is a
    # *string* on that node naming which conditions the sweep re-checks, not a
    # `Duration` any effect can carry.
    leading_link = _parse_leading_linked_duration(stream, _parse_statement_body)
    if leading_link is not None:
        return leading_link
    # "**During your next untap step, as you untap your permanents,** return
    # this land to its owner's hand." (Undiscovered Paradise.) A sentence whose
    # first word opens no effect, so it is read here rather than by the
    # subject-verb reader, which would fail the line on a subject it never
    # finds.
    untap_return = _parse_return_instead_of_untapping(stream)
    if untap_return is not None:
        return untap_return
    revealed = _parse_reveal_hand_and_choose(stream)
    if revealed is not None:
        return revealed
    # "**After this main phase,** there is an additional combat phase followed
    # by an additional main phase." (Relentless Assault, CR 500.8.) Read here
    # with the other sentences whose first word opens no effect: there is no
    # subject and no verb the subject-verb reader could take, so left to it the
    # line dies on "expected a subject" - which is where this card sat.
    extra_phases = parse_extra_phases(stream)
    if extra_phases is not None:
        return extra_phases
    # "**The next time you would draw a card this turn, instead** <effect>."
    # (Mangara's Tome; Aladdin's Lamp and Ring of Ma'rûf print the same
    # opener with different effects behind it.) CR 614.1's one-shot
    # replacement, read here rather than in a family because the words wrap a
    # whole sentence — the same reason `unless <player> pays` and the leading
    # duration above are read here.
    #
    # Gated on the opening word so it costs every other line nothing, and once
    # the opener has matched the sentence behind "instead" is parsed as an
    # ordinary statement: a line that consumed the opener and then fell through
    # would be read as though the replacement were not printed at all. That is
    # also what leaves the two card hooks theirs — their inner sentences are
    # not ones this grammar reads, so the line fails here and the compiler goes
    # on to `card_hooks`.
    if stream.at_word("the"):
        next_time = stream.mark()
        stream.advance()
        if stream.accept_phrase(
            "next", "time", "you", "would", "draw", "a", "card", "this", "turn"
        ):
            stream.accept_punct(",")
            if stream.accept_word("instead"):
                return ast.NextDrawReplacement(_parse_statement_body(stream))
        stream.reset(next_time)
    # "Create a black Spirit creature token. **Its power is equal to that
    # creature's power** …" (Broken Visage.) Two sentences and one effect, so
    # it is read here rather than by the token production the sentence loop
    # would reach: parsed apart, the first is a creature token with no P/T —
    # no card at all (CR 208.2) — and the second is a sentence about a token
    # nothing names. Gated on the opening word and refusing without consuming,
    # so every ordinary token line keeps its own reading.
    token_with_stated_pt = parse_create_token_with_stated_pt(stream)
    if token_with_stated_pt is not None:
        return token_with_stated_pt
    # "Each nontoken permanent with a name originally printed in the <Set>
    # expansion is sacrificed by its controller." (Golgothian Sylex.) Read
    # early because the sentence opens with "each", which the subject-verb
    # reader below would take as a quantified noun phrase and then fail on the
    # passive verb — losing the line to a less specific error.
    expansion_sacrifice = _parse_sacrifice_expansion_permanents(stream)
    if expansion_sacrifice is not None:
        return expansion_sacrifice
    # "Shuffle your graveyard into your library." (Feldon's Cane.) Read here
    # rather than as a verb in the subject-verb reader: the sentence has no
    # object noun phrase at all — it names two zones — so there is nothing for
    # that reader to take as a subject.
    graveyard_shuffle = _parse_shuffle_graveyard_into_library(stream)
    if graveyard_shuffle is not None:
        return graveyard_shuffle
    # "**For each creature that died this way,** put a creature card …" (Glyph
    # of Reincarnation) — the iteration clause in its *leading* printed
    # position, where `phrases._parse_for_each` reads the trailing one. Read at
    # the statement level rather than inside the effect behind it, because it
    # governs a whole sentence: the same rule the leading duration a few
    # branches below follows, and for the same reason — an effect that read its
    # own "for each" would be one production per effect that can carry one.
    # "**For each land,** destroy that land unless any player pays 1 life."
    # (Cleansing.) Read before the "this way" windows below, because both open
    # with the same two words and only this one names a set on the battlefield
    # — the window reader would take the noun phrase and then fail the line on
    # the missing participle, losing it to a less specific error.
    # "**Have this enchantment deal 5 damage to that player**" (Worms of the
    # Earth) — a damage event printed as something a player chooses to do, so
    # it opens with a verb rather than with the subject `subject_verb` wants.
    have_deal = _parse_have_source_deal_damage(stream)
    if have_deal is not None:
        return have_deal
    each_bought_off = _parse_for_each_destroy_unless_paid(stream)
    if each_bought_off is not None:
        return each_bought_off
    # The *count* reading of the same leading words, tried first because it is
    # the narrower one: it requires the phrase to name a zone other than the
    # battlefield, which the loop's sentences never do.
    per_count = _parse_leading_count_scale(_parse_statement_body, stream)
    if per_count is not None:
        return per_count
    # "**For each blue instant card revealed this way,** that player discards
    # that card unless they pay 4 life." (Sirocco.) Read before the general
    # leading loop below, which would take the noun phrase and then fail the
    # line on a body it has no reading for — the discard names "that card",
    # which is one turn of a loop rather than a subject anything else parses.
    # Refuses without consuming, so every other "For each …" keeps its reading.
    revealed_discard = _parse_for_each_revealed_discard(stream)
    if revealed_discard is not None:
        return revealed_discard

    # "**The controller of each of those artifacts** gains life equal to its
    # mana value." (Seeds of Innocence.) The loop with its subject printed in
    # front of it. Read here, beside the "for each …" spelling it is a word
    # order of and before the subject-verb reader below, which would take "the
    # controller" as a bare back-reference and then loop over nothing.
    controller_of_each = _parse_leading_controller_of_each(stream)
    if controller_of_each is not None:
        return ast.ForEach(
            controller_of_each,
            parse_subject_verb(
                stream, ast.PlayerRef("controller"),
                parse_optional_action=_parse_optional_action,
            ),
        )
    per_death = _parse_leading_for_each(_parse_statement_body, stream)
    if per_death is not None:
        # The repeated act may be printed as a choice of two ("pay 4 life **or**
        # put the card on top of your library"), so it is read through the same
        # alternatives reader "you may …" uses. One reader, so a statement-level
        # "or" means one thing wherever the pool prints it — and neither
        # position can quietly take the first half and drop the rest.
        repeated = _parse_optional_action(stream)
        # "…sacrifice a permanent other than this enchantment **unless you
        # discard a card**" (Oath of Lim-Dûl). The toll belongs to the repeated
        # sentence, not to the loop around it: the offer is made once per
        # repetition, and read outside the loop it would be one offer buying
        # off every repetition at once.
        return ast.ForEach(per_death, _accept_trailing_toll(_parse_statement_body, stream, repeated) or repeated)
    # "Each player shuffles the cards from their hand into their library, then
    # draws that many cards." (Winds of Change.) Same position and the same
    # reason: the subject-verb reader below has no "shuffles", and the sentence
    # names zones rather than an object it could take as a subject.
    hand_shuffle = _parse_shuffle_hand_into_library(stream)
    if hand_shuffle is not None:
        return hand_shuffle
    # "Then that player shuffles." (Prophecy.) CR 701.16 with nothing moving
    # into the library, so it names no zone the subject-verb reader could take
    # as an object and no verb it knows. Read *after* the two shuffles above,
    # which open with the same subject and the same verb and are the only ones
    # that name the pile that moves.
    bare_shuffle = _parse_shuffle_library(stream)
    if bare_shuffle is not None:
        return bare_shuffle
    # "Choose two target blocked attacking creatures. If each of those
    # creatures could be blocked by …" (General Jarkeld.) A whole paragraph,
    # read before every other production that opens with "choose": the counted
    # noun phrase after it is not a target *this* sentence acts on, and the
    # single-target reader below would decline on the count and leave the line
    # to fail on a word that is only the paragraph's opening.
    reassigned_blocks = _parse_reassign_blockers_between_attackers(stream)
    if reassigned_blocks is not None:
        return reassigned_blocks
    # "Choose target creature." (Reincarnation, Glyph of Life) — the targeting
    # half of a two-sentence spell. Read before anything else that opens with
    # "choose", and it declines unless the sentence binding what it chose
    # follows.
    chosen = _parse_choose_target(stream, parse_statement)
    if chosen is not None:
        return chosen
    # "Choose flying, first strike, trample, or rampage 3. <source> gains that
    # ability …" (Gabriel Angelfire) / "Choose a basic land type. This creature
    # gains landwalk of the chosen type …" (Giant Slug). The same rule as the
    # production above: the "choose" sentence means nothing without the one
    # that binds it, so the pair is read together or not at all.
    choose_then_gain = _parse_choose_then_gain(stream)
    if choose_then_gain is not None:
        return choose_then_gain
    # "Count the number of permanents." (Chaos Moon.) A sentence whose whole
    # content is CR 107.1's number, named for the sentences behind it. Gated on
    # the word so every other opener is untouched, and the production itself
    # refuses without consuming.
    if stream.at_word("count"):
        counted = _parse_count_objects(stream)
        if counted is not None:
            return counted
    # "When that creature dies this turn, …" / "At the beginning of your next
    # main phase, …" — a delayed triggered ability (CR 603.7). Read before the
    # productions its inner effect uses, whose sentences this one's tail is:
    # matched first they would perform the effect now, which is the opposite of
    # what the card says.
    delayed_trigger = _parse_create_delayed_trigger(stream, parse_statement)
    if delayed_trigger is not None:
        return delayed_trigger
    # "Destroy this artifact at the beginning of the next end step." (Rocket
    # Launcher, Rakalite.) Read before the plain destroy/return productions,
    # whose sentences are this one's prefix — matched first they would perform
    # the action immediately, which is the opposite of what the card says.
    delayed_self = _parse_delayed_self_action(stream)
    if delayed_self is not None:
        return delayed_self
    # "[Until end of turn,] you may play/cast <cards> [this turn] […]" — a
    # cast-or-play permission (CR 601.3). Tried before the "you may" wrapper
    # below: the permission IS the sentence's whole effect, where the wrapper
    # reads "you may <action>" as an optional action performed now.
    # "Until end of turn, you may cast a creature spell **from among cards
    # exiled with this artifact** without paying its mana cost" (Idol of
    # Endurance). Read before the general permission, whose zone vocabulary is
    # hand/graveyard/library and which would either refuse the line or claim it
    # while dropping the pile it is actually about.
    mark_idol = stream.mark()
    idol = _parse_cast_from_exiled_with(stream)
    if idol is not None:
        return idol
    stream.reset(mark_idol)
    if stream.at_word("until", "you"):
        permission = _parse_cast_permission(stream)
        if permission is not None:
            return permission

    # "Players and permanents can't be the targets of spells or activated
    # abilities." (Peace Talks.) Read here rather than by the subject-verb
    # table below, whose one subject cannot be both a player and an object —
    # see the production. Gated on the opening word and refusing without
    # consuming, so every other sentence about players keeps its reading.
    if stream.at_word("players"):
        targeting_ban = _parse_targeting_ban(stream)
        if targeting_ban is not None:
            return targeting_ban

    # "Until end of turn, <sentence>" — a duration in the *leading* printed
    # position (Rookie Mistake). Read **after** the cast permission above, which
    # prints the same prefix and reads it itself: taking it first turns both
    # Chandras unsupported. On any failure the mark is restored and the ordinary
    # readings continue, so this production can only add a reading, never remove
    # one — a line it cannot finish keeps the refusal it has today rather than
    # gaining a new and more confident one.
    # "**This turn and next turn**, creatures can't attack, and …" (Peace
    # Talks) prints the same leading position with a different word, so the
    # gate names both openings. Every sentence beginning "This creature …"
    # reaches the probe and leaves it untouched: ``_parse_duration`` answers
    # ``kind=None`` for a phrase that is not a duration, and the mark is
    # restored.
    if stream.at_word("until", "this"):
        mark = stream.mark()
        try:
            duration = _parse_duration(stream)
            if duration.kind is not None and stream.accept_punct(","):
                return _distribute_duration(
                    parse_statement(stream, top_level=False), duration, stream
                )
        except GrammarError:
            pass
        stream.reset(mark)

    # "For one spell this turn, you may spend mana as though it were mana of
    # any type to pay that spell's mana cost." (North Star.) A CR 609.4
    # permission rather than an action: nothing happens when it resolves.
    # Refuses without consuming, so "for each …" and every other clause opening
    # with the word keeps its reading.
    if stream.at_word("for"):
        as_though = _parse_spend_mana_as_though(stream)
        if as_though is not None:
            return as_though
        # "For each 1 damage that would be dealt to you until your next upkeep,
        # you remove an echo counter from this enchantment instead." (Soul
        # Echo.) CR 614's replacement, opening with the same two words as the
        # ordinary per-object loop below — so it is read here and refuses
        # without consuming, leaving "for each" every reading it had.
        becomes_counters = _parse_damage_becomes_counter_removal(stream)
        if becomes_counters is not None:
            return becomes_counters

    # "Until end of turn, **lands tapped for mana produce mana of the chosen
    # color** instead of any other color." (Hall of Gemstone.) The passive
    # voice of the two swaps above, with the lands in the subject slot — so it
    # is read here, ahead of the subject-verb reader that would take "lands"
    # for an ordinary noun phrase and fail on "tapped". Declines without
    # consuming, leaving every other sentence opening with a noun untouched.
    chosen_swap = _parse_tapped_lands_produce_chosen(stream)
    if chosen_swap is not None:
        return chosen_swap

    # "Attacking doesn't cause creatures you control to tap this combat if
    # Johan is untapped." (Johan.) A sentence whose subject is a gerund, which
    # the subject-verb reader below has no noun for — so it is read here, and
    # it declines without consuming, leaving every other word the same reading
    # it had. `_parse_condition` is handed down rather than imported up: this
    # module is the condition parser's layer, `effects/` is below it.
    if stream.at_word("attacking"):
        no_tap = _parse_attacking_doesnt_tap(stream, _parse_condition)
        if no_tap is not None:
            return no_tap

    # "If target Plains is tapped for mana, it produces colorless mana instead
    # of white mana." (Quarum Trench Gnomes.) The printed shape opens like an
    # ordinary conditional, but its "condition" is not one: nothing is tested
    # when the ability resolves, and the arm is a standing change to what the
    # land will produce later. Read before the conditional below, which would
    # take the clause as an intervening-if over a sentence it has no production
    # for — and refuses without consuming, so every other "if" keeps its
    # reading.
    if stream.at_word("if"):
        # "If you haven't played it, put it into its owner's graveyard."
        # (Grinning Totem, inside its delay.) Read here rather than as an
        # ordinary conditional because the condition is what binds the pronoun
        # in its arm: "put it into its owner's graveyard" on its own is All
        # Hallow's Eve's sentence about the ability's own source, and nothing
        # else in the words tells the two referents apart. Refuses without
        # consuming, so every other "If …" keeps its reading.
        binned = _parse_bin_unplayed_exiled_card(stream)
        if binned is not None:
            return binned
        # "If target spell has only one target and that target is a creature,
        # change that spell's target to another creature." (Meddle.) Read here
        # for the reason the two below it are: what looks like a condition is
        # not one — nothing about the *board* is tested, and both halves are
        # questions about the announced target of another object, which the
        # picker has to ask before the spell is cast at all. Refuses without
        # consuming, so every other "If …" keeps its reading.
        retarget = _parse_conditional_retarget(stream)
        if retarget is not None:
            return retarget
        # "If the top card of target player's graveyard is a creature card, put
        # that card on top of that player's library." (Guiding Spirit.) Read
        # here for the two above's reason: the printed "if" is part of the
        # effect rather than a condition over it — both halves name the top card
        # of one graveyard, and split into a condition and an arm neither half
        # can say which card it means. Refuses without consuming, so every other
        # "If …" keeps its reading.
        graveyard_top = parse_graveyard_top_to_library(stream)
        if graveyard_top is not None:
            return graveyard_top
        produces = _parse_produces_instead(stream)
        if produces is not None:
            return produces
        # "…if **you tap** a land you control for mana, it produces {U} instead
        # of any other type." (Deep Water.) "…if **a player taps** a Mountain
        # for mana, that Mountain produces colorless mana instead of any other
        # type." (Chaos Moon.) The active-voice spellings of the same swap,
        # beside it and refusing the same way.
        produces = _parse_tapper_produces_instead(stream)
        if produces is not None:
            return produces

    # "If a spell or ability that targets that creature would cause a source to
    # deal damage to that creature this turn, prevent that damage."
    # (Silhouette.) A *replacement* condition — what would happen, not what is
    # true — so the generic conditional below cannot read it; tried first and
    # refusing without consuming, so every other "If …" is untouched.
    bound_shield = _parse_bound_targeting_prevention(stream)
    if bound_shield is not None:
        return bound_shield

    # "If the creature deals damage to a creature this turn, the creature dealt
    # damage can't be regenerated this turn." (Runesword.) The other side of
    # the same verb, and not a conditional either: the sentence grants a
    # standing property to the creature the ability targeted. Read here, beside
    # the shield above and before the generic conditional, and refusing without
    # consuming.
    dealt_riders = _parse_damage_dealt_riders(stream)
    if dealt_riders is not None:
        return dealt_riders

    # "If damage would be dealt to any creature, you may have that damage dealt
    # to you instead." (Blood of the Martyr.) A replacement condition too, and
    # here for the same reason as the shield above: the generic conditional
    # below tests what is *true* when the sentence resolves, and this one is
    # about what *would happen* later in the turn. Refuses without consuming.
    optional_redirect = _parse_optional_damage_redirect(stream)
    if optional_redirect is not None:
        return optional_redirect

    # "if <condition>, <statement>"
    if stream.at_word("if"):
        mark = stream.mark()
        stream.advance()
        try:
            condition = _parse_condition(stream)
            stream.accept_punct(",")
            then = parse_statement(stream, top_level=False)
            # "If **target creature** has toughness 5 or greater, **it** gets
            # +4/-4…" (Blood Lust). The condition announced the spell's target
            # (CR 601.2c), so the pronoun in the arm names that choice — without
            # this the arm reads "it" as the spell itself and lowers to a pump
            # of a card on the stack, which is a supported card that does
            # nothing.
            # "…is 5 or less, exchange life totals with **that player**"
            # (Psychic Transfer). The same substitution for the *player*
            # pronoun, run after the object one: a condition that announced a
            # targeted seat has chosen it, and "that player" names that choice.
            return ast.Conditional(
                condition,
                rebind_player_pronoun_to_condition_target(
                    condition, rebind_pronoun_to_condition_target(condition, then)
                ),
            )
        except GrammarError:
            stream.reset(mark)

    # "**Unless you sacrifice an Island**, sacrifice this creature and it deals
    # 6 damage to you." (Elder Spawn.) The same offer-with-a-penalty
    # `_parse_sacrifice` already reads in the trailing spelling ("Sacrifice this
    # creature **unless you sacrifice two Swamps**", Mold Demon), printed with
    # the alternative first — so it is one production reusing that clause
    # parser, and lowers to the same `May`, not a second fused node.
    #
    # The penalty is a whole statement rather than a bare sacrifice, which is
    # the reason the leading spelling needs its own reading at all: the trailing
    # one attaches to the verb it follows and can only ever punish with that
    # verb, while Elder Spawn's penalty is a sacrifice *and* a damage rider.
    if stream.at_word("unless"):
        mark = stream.mark()
        stream.advance()
        if stream.accept_phrase("you", "sacrifice"):
            try:
                alternative = _parse_counted_sacrifice(stream, ast.PlayerRef("you"))
                if not stream.accept_punct(","):
                    raise stream.error("expected the penalty after an 'unless' clause")
                penalty = parse_statement(stream, top_level=False)
                return ast.May(
                    actor=ast.PlayerRef("you"),
                    action=alternative,
                    otherwise=penalty,
                )
            except GrammarError:
                stream.reset(mark)
        else:
            stream.reset(mark)

    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) Read here, in front of the "you may" branch and the
    # subject-verb reader below: both take "You" as a subject and then want a
    # verb, and neither has this one — the sentence would fail on "choose"
    # rather than on anything it says.
    substituted_blocks = _parse_choose_blocks_for_defenders(stream)
    if substituted_blocks is not None:
        return substituted_blocks

    # "You may play up to three additional lands this turn." (Summer Bloom.)
    # Ahead of the "you may" branch below, which would read the "may" as
    # CR 601.2's offer and wrap a permission in a prompt nobody is asked. It
    # refuses without consuming, so every other "you may …" sentence keeps the
    # reading it has today — including the two the land-play derivation table
    # owns, which differ from this one only in their duration clause.
    land_plays = parse_extra_land_plays(stream)
    if land_plays is not None:
        return land_plays

    # "you may <pay a cost | take an action>"
    if stream.at_word("you"):
        mark = stream.mark()
        stream.advance()
        if stream.accept_word("may"):
            if stream.at_word("pay"):
                # "You may pay **2 life**." (Wand of Denial.) A price with no
                # mana in it at all, which the mana reader below refuses at
                # "expected a mana cost to pay" — so the sentence failed on a
                # payment the ``May`` node has carried a field for since
                # Purgatory printed it as the *second* half of a price. One
                # offer, one prompt, and the same ``life_cost`` payload: what
                # differs from Purgatory is only that the mana half is absent.
                #
                # Read before the mana half rather than as a fallback after it,
                # because that reader raises rather than rewinding, and a
                # production that has already raised has taken the line with it.
                life_only = _accept_life_only_offer(stream)
                if life_only is not None:
                    return life_only
                stream.advance()
                # "You may pay **{X}**, where X is the number of +1/+1 counters
                # on it." (Primordial Ooze.) Admitted here and refused at
                # lowering unless the sentence really defines an X — the offer
                # is made by the same handler either way, and an undefined X
                # would make it "pay {0}", which is not a choice.
                cost = _parse_mana_payment(stream, allow_variable=True)
                # "You may pay {4} **and 2 life**." (Purgatory.) One offer with
                # two prices — CR 118.8's "or" is the alternative and this is
                # the conjunction, so both are charged and a player short of
                # either cannot take the offer at all.
                return ast.May(
                    ast.PlayerRef("you"),
                    cost=cost,
                    life_cost=_accept_conjoined_life_cost(stream),
                )
            # The causative "you may have <subject> <verb> …" (Goblin
            # Arsonist's "you may have it deal 1 damage to any target") is the
            # optional form of the unwrapped sentence — the verb table already
            # accepts the uninflected spelling the causative leaves behind, so
            # consuming "have" is the whole difference.
            #
            # "you may **choose to** have it …" (Gaze of Pain) is the same
            # offer written out. CR 601.2 has no such step: the choosing *is*
            # the "may", so the two words say twice what one word already said,
            # and reading them as anything else would invent a decision the card
            # does not make. Consumed only in front of "have", so a sentence
            # where "choose" really is the verb ("you may choose a colour")
            # keeps its own reading.
            if stream.at_word("choose") and stream.peek_word(1) == "to":
                if stream.peek_word(2) == "have":
                    stream.advance(2)
            stream.accept_word("have")
            try:
                action = _parse_optional_action(stream)
                return ast.May(ast.PlayerRef("you"), action=action)
            except GrammarError:
                stream.reset(mark)
        else:
            stream.reset(mark)

    statement = parse_subject_verb(
        stream, parse_optional_action=_parse_optional_action
    )
    carried = stream.last_subject

    # "<statement>, then <statement>" / "<statement> and <statement>" /
    # "<statement>, <statement>, then <statement>" — a comma list is joined
    # only when what follows the comma parses as a statement of its own
    # ("You gain 7 life, draw seven cards, then put …", Ugin −10), so a
    # trailing modifier clause keeps its comma and fails the line loudly.
    while True:
        mark = stream.mark()
        joined = False
        if stream.accept_punct(","):
            # ", then" and the Oxford ", and" (Cocoon's "sacrifice it, put a
            # +1/+1 counter on enchanted creature, **and** that creature gains
            # flying") both continue the list; a bare comma already does.
            if stream.accept_word("then") or stream.accept_word("and"):
                joined = True
        elif stream.accept_word("and"):
            joined = True
        elif stream.accept_word("then"):
            joined = True

        if not joined and stream.mark() == mark:
            break
        try:
            follow = parse_statement(stream, top_level=False)
        except GrammarError:
            # "Target player draws a card **and loses 1 life**." A conjunction
            # whose tail has no subject of its own, because the sentence printed
            # one in front of both verbs. Retried rather than read this way
            # first: a tail that *does* name a subject ("… and another target
            # creature gets -2/-0") is a different sentence, and reading the
            # carried one over it would silently aim the second clause at the
            # first one's object.
            #
            # Bare imperatives already worked ("You gain 1 life and draw a
            # card") because their subject is implied by the verb; this is the
            # printed-subject half of the same shape.
            after_fail = stream.mark()
            # Only a printed **player** carries. The verbs a carried subject
            # would reach — "gains", "loses", "wins" — substitute "you" for a
            # non-player subject rather than refusing, so carrying a creature
            # into one reads a sentence nobody printed: "Target creature gets
            # +3/+3 until end of turn **and wins the game**" would parse, with
            # the creature's controller winning. That line is a guard in
            # tests/engine/test_grammar_parser.py and it is right.
            if isinstance(carried, ast.PlayerRef):
                try:
                    follow = parse_subject_verb(
                        stream,
                        carried_subject=carried,
                        parse_optional_action=_parse_optional_action,
                    )
                except GrammarError:
                    stream.reset(mark)
                    break
            else:
                stream.reset(after_fail)
                stream.reset(mark)
                break
        # "…**and put a -1/-0 counter on it**." (Jabari's Influence.) The
        # pronoun names what the clause in front of it targeted, which the
        # rider table already says at a *sentence* boundary — but a conjunction
        # never reaches that table, so the same printed clause one punctuation
        # mark over placed the counter on the ability's source.
        follow = rebind_counter_pronoun_to_bound_target(statement, follow)
        statement = ast.Sequence((statement, follow))
        # A third clause shares the subject of the one it follows, not of the
        # sentence's head, which is the same rule and matters the moment a
        # sentence names a second subject part-way through.
        carried = stream.last_subject or carried

    # "Round up each time." (Peer into the Abyss.) The second trailing modifier,
    # read here for the same reason the where-clause is: it is not another
    # statement, it changes how a value the sentence already computed is
    # rounded. **Each time** is the load-bearing half — the rounding is applied
    # per calculation, so it reaches every `Half` in the sentence rather than
    # the last one, and a card printing it over a sentence with no half at all
    # is a wording this does not read.
    rounding_mark = stream.mark()
    if stream.accept_punct("."):
        if stream.accept_phrase("round", "up", "each", "time"):
            stream.accept_punct(".")
            rounded = _round_every_half(statement, "up")
            if rounded is None:
                raise stream.error("'round up each time' with nothing to round")
            return rounded
        stream.reset(rounding_mark)

    # "…, where X is the number of <filter>." The one trailing modifier the
    # loop above deliberately refuses to join, read here instead: it is not
    # another statement, it *defines* a value the statement already used. Read
    # after the join so it binds the whole sentence — "each opponent loses X
    # life and you gain X life, where X is …" is two effects and one
    # definition, and consuming it inside the first would leave the second's X
    # undefined.
    return statement


def _parse_where_x(stream: TokenStream) -> ast.Amount | None:
    """``[,] where X is <definition>`` at the sentence level.

    The clause itself is `phrases.parse_where_x_definition`; this is the name
    the statement parser has always called it by.
    """
    return parse_where_x_definition(stream)


def _parse_optional_action(stream: TokenStream) -> ast.Statement:
    """The action behind "you may …", which may be printed as a choice of two.

    "You may sacrifice a creature **or** discard a creature card" (Crypt Lurker)
    is one action with two ways to take it, so it parses to a single
    :class:`ast.OneOf` the player picks from — not two steps, which would do
    both, and not the first half with the rest dropped, which is what the
    unconsumed-token invariant was refusing the whole line for.

    Read here rather than in ``parse_statement`` at large. A statement-level
    "or" is rare and this is the one position the pool prints it in; claiming it
    everywhere would put a production in front of every sentence in the game on
    the strength of one card.
    """
    first_at = stream.pos
    try:
        first = parse_statement(stream, top_level=False)
    except GrammarError:
        # "You may **gain 1 life**." (Thoughtleech.) The offer printed its
        # subject once, in front of "may", and the action behind it is a bare
        # verb — the same shared-subject shape a conjunction already handles
        # ("Target player draws a card **and loses 1 life**"), one clause
        # earlier. Retried rather than read this way first, for that rule's own
        # reason: an action that names a subject of its own is a different
        # sentence, and carrying "you" over it would aim it at the wrong player.
        stream.reset(first_at)
        first = parse_subject_verb(
            stream,
            carried_subject=ast.PlayerRef("you"),
            parse_optional_action=_parse_optional_action,
        )
        first_at = first_at
    if not stream.at_word("or"):
        return first
    options = [first]
    spans = [(first_at, stream.pos)]
    while stream.accept_word("or"):
        start = stream.pos
        options.append(parse_statement(stream, top_level=False))
        spans.append((start, stream.pos))
    return rebind_alternative_pronoun_to_choice_target(
        ast.OneOf(
            tuple(options), tuple(stream.text_between(a, b) for a, b in spans)
        )
    )

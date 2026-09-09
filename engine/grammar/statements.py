"""Statement productions: one whole sentence, assembled from effects.

`parse_statement` is the entry point for one sentence, and
`_parse_statement_body` reads the shapes that open with something other than a
subject. The `<subject> <verb> …` opening moved to `subject_verb` at the
thousand-line guard, and `_parse_condition` to `conditions` before it; both are
handed back what they need from here rather than importing upward.

Two more left at Urza's Legacy's Phase 0, and only one of them needed a new
file. **The sentences opening on "if"** — nine spellings that only wear the
word and the intervening-if that means it — are `if_openings`, cut where the
cascade had already drawn the line and taking the generic conditional with
them, so this module reads no "if" opener at all. **The trailing delay's node
assembly** went back to `delayed`, which was never a split so much as a
correction: that module defines `resolve_that_turn`, `fold_flip_stakes` and
`delay_binds_an_object`, called them out to nothing but this file, and called
its own `_parse_create_delayed_trigger` "the one place the rows become a node"
while a second place sat here. Ask where a block already belongs before asking
what to name a file for it.

The narrow waist of the parser — below is a fragment, above is a *line*.
"""

import dataclasses

from . import ast
from .errors import GrammarError
from .paragraphs import (_parse_reassign_blockers_between_attackers,
                         _parse_cast_from_exiled_with)
from .choices import (_parse_choose_target, _parse_choose_then_gain,
                      _parse_choose_then_swap)
from .delay_openers import parse_trailing_delay
from .delayed import _parse_create_delayed_trigger, wrap_in_trailing_delay
from .references import parse_player_ref
from .stream import TokenStream
from .conditions import _parse_condition
from .where_x import accept_cast_time_marker, parse_where_x_definition
from .subject_verb import parse_subject_verb
from .leading_iteration import parse_leading_iteration
from .if_openings import parse_if_opening
from .rebinding import (rebind_alternative_pronoun_to_choice_target,
                        rebind_counter_pronoun_to_bound_target)
from .phrases import (_accept_conjoined_life_cost, _accept_life_only_offer,
                      _parse_duration, _parse_mana_payment)
from .effects import (_parse_damage_becomes_counter_removal,
                      _parse_destroy_chosen_that_didnt_attack,
                      _parse_untap_chosen_by_paying,
                      _parse_cast_permission,
                      _parse_attacking_doesnt_tap,
                      _parse_reveal_hand_and_choose,
                      _parse_return_instead_of_untapping,
                      _parse_count_objects,
                      _parse_tapped_lands_produce_chosen,
                      _parse_spend_mana_as_though,
                      _parse_choose_blocks_for_defenders,
                      _parse_sacrifice_expansion_permanents,
                      parse_create_token_with_stated_pt,
                      _parse_delayed_self_action, _parse_shuffle_graveyard_into_library,
                      _parse_shuffle_hand_into_library, _parse_shuffle_library,
                      _parse_bound_permanent_activation_ban,
                      _parse_targeting_ban)
from .sacrifices import _parse_counted_sacrifice
from .effects.game import parse_extra_land_plays, parse_extra_phases


from .sentence_clauses import (
    accept_shuffle_sequence_tail,
    _accept_alternative_sweep,
    _accept_graded_toll_outcomes,
    _distribute_duration,
    _parse_unless_player_pays,
    accept_delayed_toll,
    _accept_trailing_toll,
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
        # "…, where X is the number of black permanents target opponent
        # controls **as you cast this spell**." (Reap.) CR 601.2b fixes the
        # quantity at the announcement, which is a different card from the
        # same sentence without the words — so the phrase is read here,
        # where the clause has just been consumed, and carried on the node
        # rather than left as unconsumed text that refuses the line.
        statement = ast.WhereX(
            statement, definition, as_cast=accept_cast_time_marker(stream)
        )
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
    # The delay was printed *behind* its effect. Both word orders build the same
    # node out of the same rows, so the construction lives beside the leading
    # spelling's in `delayed` — where the three walks over the wrapped sentence
    # were already defined and called from nowhere but here. It crossed out of
    # this module at Urza's Legacy's Phase 0 (see that file's docstring); the
    # callables it needs are handed down, because this is the layer above it.
    return wrap_in_trailing_delay(
        stream,
        statement,
        delay,
        definition,
        parse_statement=parse_statement,
        parse_body=_parse_statement_body,
        accept_delayed_toll=accept_delayed_toll,
    )


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
    # A loop or a count printed in front of the sentence — eight spellings, one
    # question — read in `leading_iteration`, which crossed out of this module
    # at Weatherlight's Phase 0 (see that file's docstring). It declines without
    # consuming, so everything below keeps its reading.
    leading = parse_leading_iteration(
        stream,
        parse_body=_parse_statement_body,
        parse_optional_action=_parse_optional_action,
        accept_trailing_toll=_accept_trailing_toll,
    )
    if leading is not None:
        return leading
    # "Each player shuffles the cards from their hand into their library, then
    # draws that many cards." (Winds of Change.) Same position and the same
    # reason: the subject-verb reader below has no "shuffles", and the sentence
    # names zones rather than an object it could take as a subject.
    hand_shuffle = _parse_shuffle_hand_into_library(stream)
    if hand_shuffle is not None:
        return hand_shuffle
    # "Then that player shuffles." (Prophecy.) CR 701.24 with nothing moving
    # into the library, so it names no zone the subject-verb reader could take
    # as an object and no verb it knows. Read *after* the two shuffles above,
    # which open with the same subject and the same verb and are the only ones
    # that name the pile that moves.
    bare_shuffle = _parse_shuffle_library(stream)
    if bare_shuffle is not None:
        return accept_shuffle_sequence_tail(bare_shuffle, stream, parse_statement)
    # "Choose two target blocked attacking creatures. If each of those
    # creatures could be blocked by …" (General Jarkeld.) A whole paragraph,
    # read before every other production that opens with "choose": the counted
    # noun phrase after it is not a target *this* sentence acts on, and the
    # single-target reader below would decline on the count and leave the line
    # to fail on a word that is only the paragraph's opening.
    reassigned_blocks = _parse_reassign_blockers_between_attackers(stream)
    if reassigned_blocks is not None:
        return reassigned_blocks
    # "Choose target artifact a player controls and target artifact card in
    # that player's graveyard. … that player simultaneously sacrifices the
    # artifact and returns the artifact card to the battlefield." (Goblin
    # Welder.) Two sentences and one announcement, read before the single-slot
    # "choose" reader below because that one's binder probe cannot see a
    # sentence naming *both* chosen objects.
    swapped = _parse_choose_then_swap(stream)
    if swapped is not None:
        return swapped
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
    # "At the beginning of **that turn's** end step, destroy each of the chosen
    # creatures that didn't attack this turn." (Oracle en-Vec.) Read before the
    # delayed-trigger opener below, whose table has a row for these exact words
    # meaning a different turn — Final Fortune's extra turn. Both are "that
    # turn"; which one is decided by the sentence in front, and only this
    # production asks. It refuses without consuming, so Final Fortune's line is
    # untouched.
    if stream.at_word("at"):
        destroy_chosen = _parse_destroy_chosen_that_didnt_attack(stream)
        if destroy_chosen is not None:
            return destroy_chosen
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
    # …plus the one printed subject other than "you": "**The player** may play
    # that card this turn" (Elkin Lair). The "may" lookahead keeps the gate as
    # tight as it was — "the"/"that"/"they" open a great many sentences and
    # almost none is a permission, and one tried on all of them would replace
    # their refusal sites with its own.
    if stream.at_word("until", "you") or (
        stream.at_word("the", "that", "they") and stream.peek_word(1) == "may"
        or stream.at_word("the", "that") and stream.peek_word(2) == "may"
    ):
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

    # "**That permanent's** activated abilities can't be activated this turn."
    # (Interdict.) Read here beside the ban above rather than by the
    # subject-verb table, whose subject reader would take "that permanent" as a
    # bound object and then hand the verb an object nothing bans. Gated on the
    # opening word and refusing without consuming, so every other sentence
    # opening on "that" keeps its reading.
    if stream.at_word("that"):
        activation_ban = _parse_bound_permanent_activation_ban(stream)
        if activation_ban is not None:
            return activation_ban

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
    # "**During that player's next turn**, the chosen creatures attack if able,
    # and other creatures can't attack." (Oracle en-Vec.) The third opening word
    # a leading duration can have, named here for the two above it: the probe is
    # only reached for a word this gate lists, and a duration nothing tries is a
    # duration nothing reads. Every other sentence beginning "During …" is
    # untouched — ``_parse_duration`` answers ``kind=None`` for a phrase that is
    # not in its table and the mark is restored, which is what already happens
    # for the hundreds of sentences beginning "This creature …".
    if stream.at_word("until", "this", "during"):
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
    # voice of the two swaps `if_openings` reads — Deep Water's and Chaos
    # Moon's, which print the same exchange with an "If" in front of it — with
    # the lands in the subject slot and no "if" for that module to gate on. So
    # it is read here, ahead of the subject-verb reader that would take "lands"
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

    # Every sentence whose printed first word is "if" — nine spellings that only
    # wear the word and the one intervening-if that means it — read in
    # `if_openings`, which crossed out of this module at Urza's Legacy's Phase 0
    # (see that file's docstring). The generic conditional went with them
    # because it is the fall-through the other nine exist to get in front of,
    # and an ordering split across two files is an ordering neither can state.
    # It declines without consuming, so everything below keeps its reading.
    if_opening = parse_if_opening(stream, parse_statement=parse_statement)
    if if_opening is not None:
        return if_opening

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

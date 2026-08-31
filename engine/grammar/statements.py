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
from .lexer import (SELF, WORD)
from .nouns import parse_object_filter
from .paragraphs import (
    _parse_random_reveal_ownership_exchange,
    _parse_exchange_greatest_mana_value,
    _parse_cast_from_exiled_with,
    _parse_ownership_exchange_unless_paid,
    _parse_exile_graveyard_until_leaves,
    _parse_exile_until_leaves_or_untaps,
    _parse_name_and_strip,
    _parse_name_then_random_reveal,
    _parse_name_then_reveal_top,
    _parse_transmute_by_sacrifice,
)
from .delayed import (_parse_choose_target, _parse_choose_then_gain,
                      _parse_create_delayed_trigger, delay_binds_an_object,
                      parse_trailing_delay,
                      resolve_that_turn)
from .references import parse_player_ref, parse_recipient
from .vocabulary import CARD_TYPES
from .stream import TokenStream
from .conditions import _parse_condition
from .where_x import parse_where_x_definition
from .subject_verb import parse_subject_verb
from .rebinding import rebind_pronoun_to_condition_target
from .phrases import (
    _accept_self_reference,
    parse_bound_subject,
    _parse_can_attack_as_though,
    _parse_duration,
    _parse_mana_payment,
)
from .effects import (
    _parse_for_each_destroy_unless_paid,
    _parse_have_source_deal_damage,
    _parse_add_mana,
    _parse_becomes,
    _parse_cant_attack_or_block,
    _parse_cast_permission,
    _parse_change_base_pt,
    _parse_change_text,
    _parse_source_of_choice_effect,
    _parse_damage_redirect,
    _parse_optional_damage_redirect,
    _parse_assigns_no_combat_damage,
    _parse_attacking_doesnt_tap,
    _parse_bound_targeting_prevention,
    _parse_damage_dealt_riders,
    _parse_counter,
    _parse_create_token,
    _parse_damage,
    _parse_destroy,
    _parse_discard,
    _parse_draw,
    _parse_exile_graveyard,
    _parse_reveal_hand_and_choose,
    _parse_exile_top_of_library,
    _parse_put_exiled_with_source,
    _parse_enchant,
    _parse_end_the_turn,
    _parse_extra_turn,
    _parse_ante,
    _parse_life_total_becomes,
    _parse_gain_control,
    _parse_gains,
    _parse_choose_number,
    _parse_flip_coin,
    _parse_game_is_a_draw,
    _parse_gets,
    _parse_has,
    _parse_look_at_hand,
    _parse_loses,
    _parse_mill,
    _parse_scry,
    _parse_modal_head,
    _parse_player_adds_mana,
    _parse_produces_instead,
    _parse_you_tap_produces_instead,
    _parse_spend_mana_as_though,
    _parse_prevent,
    _parse_double,
    _parse_switch_pt,
    _parse_fight,
    _parse_put_counter,
    _parse_remove_counter,
    _parse_remove_from_combat,
    _parse_return,
    _parse_reveal_top,
    _parse_sacrifice,
    _parse_counted_sacrifice,
    _parse_sacrifice_expansion_permanents,
    _parse_delayed_self_action,
    _parse_shuffle_graveyard_into_library,
    _parse_shuffle_hand_into_library,
    _parse_search_library,
    _parse_doesnt_untap_next_step,
    _parse_tap_untap,
    _parse_attach,
    _parse_exchange_control,
    _parse_wins,
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
    statement = _accept_alternative_sweep(stream, statement, body_at)
    if not top_level:
        return statement
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
    return ast.CreateDelayedTrigger(
        event=event, effect=statement,
        once=once, duration=duration,
        # A permission, not the answer — see ``delay_binds_an_object``.
        binds_target=delay_binds_an_object(binds, statement),
        subject=None, agent=None,
        watches=watches,
    )


def _parse_leading_for_each(
    stream: TokenStream,
) -> "ast.DiedThisWay | ast.ExiledThisWay | ast.ChosenThisWay | None":
    """``For each <objects> that died this way,`` — the set a later clause
    repeats over, in the leading printed position.

    Only the "this way" window, deliberately. "That died **this turn**" is a
    different set — a window of the turn's history anything may have
    contributed to — and it already has a reader in ``phrases``, in the
    trailing position where the pool prints it. Admitting both here would let
    one clause mean either, and the two differ by every creature the spell had
    nothing to do with.

    Returns None with the cursor where it found it, so a sentence this is not
    keeps the refusal it already had rather than gaining a more confident one.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "each"):
        return None
    # "For each of **those cards**, …" (Sylvan Library) — the set an earlier
    # sentence of this same effect chose. Read before the noun phrase, because
    # "those cards" is a back-reference and not a filter: read as one it would
    # name every card in every hand.
    if stream.accept_phrase("of", "those", "cards"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.ChosenThisWay()
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    # "For each creature **exiled this way**, …" (Martyr's Cry). The same
    # leading position and the same "this way" window, over the set an earlier
    # step *exiled* rather than the set it destroyed — two records, so two
    # nodes, because a sweep that exiles kills nothing and the destroy family's
    # record would be empty.
    #
    # No "that": the printed participle is bare ("creature exiled this way"),
    # where the death spelling prints a relative clause ("creature **that**
    # died this way").
    if stream.accept_phrase("exiled", "this", "way"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.ExiledThisWay(filt)
    # "For each land **destroyed this way**, …" (Stench of Evil.) The bare
    # participle spelling of the relative clause below, and the *same* set: what
    # a destroy sweep records is what actually died, because a regenerated or
    # indestructible permanent was not destroyed (CR 701.7c). One node, so the
    # two printings cannot come to mean two sets — the difference is Wizards'
    # templating and nothing else.
    if stream.accept_phrase("destroyed", "this", "way"):
        if not stream.accept_punct(","):
            stream.reset(mark)
            return None
        return ast.DiedThisWay(filt)
    if not stream.accept_phrase("that", "died", "this", "way"):
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    return ast.DiedThisWay(filt)


def _distribute_duration(
    statement: ast.Statement, duration: ast.Duration, stream: TokenStream
) -> ast.Statement:
    """Attach a *leading* duration to every effect of the sentence behind it.

    "Until end of turn, A gets +0/+2 and another target creature gets -2/-0"
    (Rookie Mistake) prints one duration in front of two effects, where the
    trailing spelling attaches to the clause it follows. So the leading one is
    distributed rather than stored on a wrapper node: every consumer already
    reads a duration off the effect it belongs to, and a node above them all
    would be a second place to ask.

    Refuses rather than dropping, in three shapes — a statement with no duration
    field at all (the prefix would silently vanish), a statement already printing
    a *different* duration, and, through the recursion, a sequence with any such
    step. A dropped "until end of turn" is a permanent effect the card never
    printed.
    """
    if isinstance(statement, ast.Sequence):
        return dataclasses.replace(
            statement,
            steps=tuple(
                _distribute_duration(step, duration, stream) for step in statement.steps
            ),
        )
    fields = {field.name for field in dataclasses.fields(statement)}
    if "duration" not in fields:
        raise stream.error(
            f"a leading duration has nothing to attach to in {type(statement).__name__}"
        )
    existing = getattr(statement, "duration")
    if existing.kind is not None and existing.kind != duration.kind:
        raise stream.error("this sentence prints two different durations")
    return dataclasses.replace(statement, duration=duration)


def _parse_leading_linked_duration(stream: TokenStream) -> "ast.GainControl | None":
    """``For as long as <self> remains tapped, gain control of <subject>.``
    (Preacher.)

    Returns None with the cursor untouched for anything else opening "for as
    long as", so the trailing spelling every other card prints keeps its reader
    and an unreadable condition still fails loudly on its own words.

    Only the control change takes it. A leading duration on any other sentence
    is the ordinary ``Duration`` the reader below distributes; this one names
    the conditions a *sweep* re-checks, which only the control contribution has.
    """
    mark = stream.mark()
    if not stream.accept_phrase("for", "as", "long", "as"):
        return None
    if not (
        _accept_self_reference(stream)
        and stream.accept_phrase("remains", "tapped")
        and stream.accept_punct(",")
    ):
        stream.reset(mark)
        return None
    control = _parse_gain_control(stream, leading_duration="while_source_tapped")
    if control is None:
        stream.reset(mark)
        return None
    return control


def _parse_unless_player_pays(stream: TokenStream) -> "ast.UnlessPlayerPays | None":
    """``Unless <player> pays <cost>, <statement>.`` (Scarwood Bandits.)

    Returns None with the cursor untouched for anything else opening with
    "unless", so the trailing "…unless <condition>" every other sentence can
    carry keeps its own reader.

    The payer must be a *player reference the engine can enumerate seats from*;
    the cost must be mana. Both are refused rather than skipped, because a payer
    nobody is asked and a cost nobody is charged are the same failure — the
    effect happening unconditionally, which is the card without its clause.
    """
    mark = stream.mark()
    if not stream.accept_word("unless"):
        return None
    payer = parse_player_ref(stream)
    if payer is None or not stream.accept_word("pays", "pay"):
        stream.reset(mark)
        return None
    try:
        cost = _parse_mana_payment(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if cost is None or not stream.accept_punct(","):
        stream.reset(mark)
        return None
    return ast.UnlessPlayerPays(payer, cost, _parse_statement_body(stream))


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
    unless_paid = _parse_unless_player_pays(stream)
    if unless_paid is not None:
        return unless_paid
    # "**For as long as this creature remains tapped,** gain control of …"
    # (Preacher.) A linked duration (CR 611.2b) printed in front of the verb.
    # Read here for the reason the leading duration below is read here — it
    # governs the whole sentence — and handed to the control production rather
    # than distributed like an ordinary one, because a linked duration is a
    # *string* on that node naming which conditions the sweep re-checks, not a
    # `Duration` any effect can carry.
    leading_link = _parse_leading_linked_duration(stream)
    if leading_link is not None:
        return leading_link
    revealed = _parse_reveal_hand_and_choose(stream)
    if revealed is not None:
        return revealed
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
    per_death = _parse_leading_for_each(stream)
    if per_death is not None:
        # The repeated act may be printed as a choice of two ("pay 4 life **or**
        # put the card on top of your library"), so it is read through the same
        # alternatives reader "you may …" uses. One reader, so a statement-level
        # "or" means one thing wherever the pool prints it — and neither
        # position can quietly take the first half and drop the rest.
        return ast.ForEach(per_death, _parse_optional_action(stream))
    # "Each player shuffles the cards from their hand into their library, then
    # draws that many cards." (Winds of Change.) Same position and the same
    # reason: the subject-verb reader below has no "shuffles", and the sentence
    # names zones rather than an object it could take as a subject.
    hand_shuffle = _parse_shuffle_hand_into_library(stream)
    if hand_shuffle is not None:
        return hand_shuffle
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

    # "Until end of turn, <sentence>" — a duration in the *leading* printed
    # position (Rookie Mistake). Read **after** the cast permission above, which
    # prints the same prefix and reads it itself: taking it first turns both
    # Chandras unsupported. On any failure the mark is restored and the ordinary
    # readings continue, so this production can only add a reading, never remove
    # one — a line it cannot finish keeps the refusal it has today rather than
    # gaining a new and more confident one.
    if stream.at_word("until"):
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
        produces = _parse_produces_instead(stream)
        if produces is not None:
            return produces
        # "…if **you tap** a land you control for mana, it produces {U} instead
        # of any other type." (Deep Water.) The active-voice spelling of the
        # same swap, beside it and refusing the same way.
        produces = _parse_you_tap_produces_instead(stream)
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
            return ast.Conditional(
                condition, rebind_pronoun_to_condition_target(condition, then)
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

    # "you may <pay a cost | take an action>"
    if stream.at_word("you"):
        mark = stream.mark()
        stream.advance()
        if stream.accept_word("may"):
            if stream.at_word("pay"):
                stream.advance()
                # "You may pay **{X}**, where X is the number of +1/+1 counters
                # on it." (Primordial Ooze.) Admitted here and refused at
                # lowering unless the sentence really defines an X — the offer
                # is made by the same handler either way, and an undefined X
                # would make it "pay {0}", which is not a choice.
                cost = _parse_mana_payment(stream, allow_variable=True)
                return ast.May(ast.PlayerRef("you"), cost=cost)
            # The causative "you may have <subject> <verb> …" (Goblin
            # Arsonist's "you may have it deal 1 damage to any target") is the
            # optional form of the unwrapped sentence — the verb table already
            # accepts the uninflected spelling the causative leaves behind, so
            # consuming "have" is the whole difference.
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


def _round_every_half(node, rounding: str):
    """*node* with every :class:`ast.Half` in it rounded *rounding*, or None
    when it contains none.

    Written against the dataclass fields rather than a per-node list, for the
    reason ``_targeted_specs`` gives: a statement class added later is covered
    by default instead of silently keeping the printed default. Returning None
    for "nothing to round" is what lets the caller refuse the wording rather
    than consume it and change nothing.
    """
    if isinstance(node, ast.Half):
        return dataclasses.replace(node, rounding=rounding)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changed = False
        updates = {}
        for field in dataclasses.fields(node):
            value = getattr(node, field.name)
            rebuilt = _round_every_half(value, rounding)
            if rebuilt is not None:
                updates[field.name] = rebuilt
                changed = True
        return dataclasses.replace(node, **updates) if changed else None
    if isinstance(node, tuple):
        rebuilt_items = [_round_every_half(item, rounding) for item in node]
        if not any(item is not None for item in rebuilt_items):
            return None
        return tuple(
            new if new is not None else old for new, old in zip(rebuilt_items, node)
        )
    return None


def _accept_alternative_sweep(
    stream: TokenStream, statement: ast.Statement, body_at: int
) -> ast.Statement:
    """``Destroy all enchantments **or all nonwhite enchantments**.`` (Essence
    Filter.) One verb, two object phrases, and the controller picks.

    CR 608.2d, not CR 700.2: there is no bulleted list and nothing is announced
    as the spell is cast, so this is a choice made *while applying the effect*.
    That is the same question ``_parse_optional_action``'s "or" asks, so it is
    the same :class:`ast.OneOf` and the same prompt — inventing a second
    mechanism would mean two defaults and two places for an option to go
    unoffered.

    Read here, after the body, rather than inside the destroy production: the
    shape is "the sentence again with a different object", which is a property
    of the sentence and not of the verb. Every guard below is what keeps that
    from over-claiming:

    * only a **sweep** may be repeated. A targeted alternative would be two
      target sets, one of them never chosen, and CR 601.2c picks targets as the
      spell is cast — the picker has no way to announce a set that depends on a
      choice made later. "Destroy target creature or target land" therefore
      stays refused rather than becoming a choice nobody can make.
    * the alternative must be a sweep too, and must **end the sentence**. A
      near-miss rewinds whole, so "or" introducing anything else falls through
      to the reading it already had.
    """
    subject = getattr(statement, "subject", None)
    if (
        not isinstance(statement, ast.Destroy)
        or not isinstance(subject, ast.TargetSpec)
        or subject.quantifier != "all"
    ):
        return statement
    mark = stream.mark()
    if not stream.accept_word("or"):
        return statement
    start = stream.pos
    try:
        alternative = parse_recipient(stream)
    except GrammarError:
        stream.reset(mark)
        return statement
    if (
        not isinstance(alternative, ast.TargetSpec)
        or alternative.quantifier != "all"
        or stream.peek() is not None and stream.peek().kind == WORD
    ):
        stream.reset(mark)
        return statement
    second = dataclasses.replace(statement, subject=alternative)
    return ast.OneOf(
        (statement, second),
        (stream.text_between(body_at, mark), stream.text_between(start, stream.pos)),
    )


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
    return ast.OneOf(tuple(options), tuple(stream.text_between(a, b) for a, b in spans))

"""Statement productions: one whole sentence, assembled from effects.

Three productions and the layer they name. `_parse_subject_verb` reads the
common `<subject> <verb> …` shape and dispatches into `effects`;
`parse_statement` is the entry point for one sentence; `_parse_condition` reads
the condition half of a trigger or an intervening-if.

The narrow waist of the parser — below is a fragment, above is a *line*.
"""

import dataclasses

from . import ast
from .errors import GrammarError
from .lexer import (SELF, WORD)
from .nouns import parse_object_filter
from .paragraphs import (
    _parse_cast_from_exiled_with,
    _parse_ownership_exchange_unless_paid,
    _parse_exile_graveyard_until_leaves,
    _parse_exile_until_leaves_or_untaps,
    _parse_name_and_strip,
    _parse_name_then_reveal_top,
    _parse_transmute_by_sacrifice,
)
from .references import parse_recipient
from .vocabulary import CARD_TYPES
from .stream import TokenStream
from .conditions import _parse_condition
from .rebinding import rebind_pronoun_to_condition_target
from .phrases import (
    parse_bound_subject,
    _parse_can_attack_as_though,
    _parse_duration,
    _parse_mana_payment,
    parse_where_x_definition,
)
from .effects import (
    _parse_add_mana,
    _parse_becomes,
    _parse_cant_attack_or_block,
    _parse_cast_permission,
    _parse_change_base_pt,
    _parse_change_text,
    _parse_colour_source_prevention,
    _parse_counter,
    _parse_create_token,
    _parse_damage,
    _parse_destroy,
    _parse_discard,
    _parse_draw,
    _parse_exile_graveyard,
    _parse_reveal_hand_and_choose,
    _parse_exile_top_of_library,
    _parse_enchant,
    _parse_end_the_turn,
    _parse_extra_turn,
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


def _parse_subject_verb(
    stream: TokenStream, carried_subject: ast.Recipient | None = None
) -> ast.Statement:
    """``<subject> <verb> …`` — the common imperative-with-subject shape.

    *carried_subject* supplies the subject instead of reading one, for the tail
    of a conjunction that shares the subject printed in front of it: "Target
    player draws a card **and loses 1 life**" names the player once. The subject
    the sentence actually used is left on ``stream.last_subject`` so the sentence
    loop can hand it back on the next join.
    """
    # "The next time a <colour> source of your choice would deal damage to you
    # this turn, prevent that damage." opens with a noun phrase rather than a
    # verb, so it is tried before the subject-verb shapes below.
    colour_shield = _parse_colour_source_prevention(stream)
    if colour_shield is not None:
        return colour_shield
    # "The game is a draw." — a subjectless sentence, tried before the noun
    # phrase for the same reason the colour shield is.
    game_draw = _parse_game_is_a_draw(stream)
    if game_draw is not None:
        return game_draw
    # "Choose one —" (CR 700.2). A *statement* rather than a line shape so the
    # three places a modal head is printed — bare on a spell, after an
    # activation cost, after a trigger condition — all read it through the line
    # layer that already handles those prefixes. It refuses quietly, so every
    # other "choose …" sentence keeps the backlog reason it had.
    if stream.at_word("choose"):
        modal = _parse_modal_head(stream)
        if modal is not None:
            return modal
    # "Flip a coin." (CR 705.1) — a bare imperative like the ones below, and
    # the only production that reads the word, so any other "flip …" sentence
    # (Chaos Orb's) falls through untouched.
    if stream.at_word("flip"):
        flip = _parse_flip_coin(stream)
        if flip is not None:
            return flip
    # A bare imperative verb has an implied "you"/the source as subject.
    if stream.at_word("destroy"):
        return _parse_destroy(stream)
    if stream.at_word("tap", "untap"):
        return _parse_tap_untap(stream)
    if stream.at_word("attach"):
        return _parse_attach(stream)
    if stream.at_word("exchange"):
        return _parse_exchange_control(stream)
    if stream.at_word("put"):
        return _parse_put_counter(stream)
    if stream.at_word("double"):
        return _parse_double(stream)
    if stream.at_word("switch"):
        return _parse_switch_pt(stream)
    if stream.at_word("remove"):
        removal = _parse_remove_counter(stream)
        if removal is not None:
            return removal
        # "…and remove it from combat" (Disharmony). Tried after the counter
        # removal, and non-consuming on refusal, so every other "remove …"
        # sentence keeps the refusal it has today.
        combat_removal = _parse_remove_from_combat(stream)
        if combat_removal is not None:
            return combat_removal
    if stream.at_word("change"):
        # The base-P/T rewrite is tried first and refuses without consuming
        # when the sentence is "change the text of …", so the two readings of
        # the verb cannot shadow each other.
        base_pt = _parse_change_base_pt(stream)
        if base_pt is not None:
            return base_pt
        return _parse_change_text(stream)
    if stream.at_word("gain"):
        control = _parse_gain_control(stream)
        if control is not None:
            return control
    if stream.at_word("create"):
        return _parse_create_token(stream)
    if stream.at_word("return"):
        return _parse_return(stream)
    if stream.at_word("prevent"):
        return _parse_prevent(stream)
    if stream.at_word("sacrifice"):
        # Transmute Artifact's whole paragraph opens with the same two words a
        # bare sacrifice does, and that match would leave six sentences
        # unconsumed — so it is tried first, and refuses without consuming.
        mark_transmute = stream.mark()
        transmute = _parse_transmute_by_sacrifice(stream)
        if transmute is not None:
            return transmute
        stream.reset(mark_transmute)
        stream.advance()
        return _parse_sacrifice(stream, ast.PlayerRef("you"))
    if stream.at_word("regenerate"):
        stream.advance()
        subject = parse_recipient(stream)
        if subject is None:
            raise stream.error("expected something to regenerate")
        return ast.Regenerate(subject)
    # "Exile all … from your graveyard **until this artifact leaves the
    # battlefield**" (Idol of Endurance). Read before the general exile, whose
    # sweep is over battlefield permanents and whose match would strand the
    # duration as unconsumed text.
    mark_idol = stream.mark()
    idol = _parse_exile_graveyard_until_leaves(stream)
    if idol is not None:
        return idol
    stream.reset(mark_idol)
    # Tawnos's Coffin's whole four-sentence effect, read before the general
    # exile for the same reason Idol's is: the sentences behind the first one
    # are not effects of their own, and a general match would leave them as
    # unconsumed text.
    mark_coffin = stream.mark()
    coffin = _parse_exile_until_leaves_or_untaps(stream)
    if coffin is not None:
        return coffin
    stream.reset(mark_coffin)
    if stream.at_word("exile"):
        # Bronze Tablet's whole paragraph opens "Exile this artifact and …", and
        # the ordinary exile would match its first clause and strand three
        # sentences. Refuses without consuming.
        mark_tablet = stream.mark()
        tablet = _parse_ownership_exchange_unless_paid(stream)
        if tablet is not None:
            return tablet
        stream.reset(mark_tablet)
        # "Exile the top three cards of your library" moves library cards, not
        # a permanent — tried first because the recipient parser below refuses
        # "the top" and would fail the sentence with a misleading reason.
        from_library = _parse_exile_top_of_library(stream)
        if from_library is not None:
            return from_library
        # "Exile target player's graveyard" is a whole zone, which the
        # recipient parser below would read as the player alone and then
        # choke on the possessive.
        whole_graveyard = _parse_exile_graveyard(stream)
        if whole_graveyard is not None:
            return whole_graveyard
        stream.advance()
        subject = parse_recipient(stream)
        if subject is None:
            raise stream.error("expected something to exile")
        return ast.Exile(subject, _parse_duration(stream))
    if stream.at_word("add"):
        return _parse_add_mana(stream)
    if stream.at_word("look"):
        return _parse_look_at_hand(stream)
    if stream.at_word("search"):
        return _parse_search_library(stream)
    # "Scry N" has no subject for the same reason "draw a card" has none: the
    # effect's controller is implied. It belongs with the other bare
    # imperatives rather than in the subject-verb table below, which is why
    # `Scry 1.` used to die on "expected a subject" — and why every scry line
    # in the pool produced no instruction at all while its card still reported
    # supported on the strength of its other line.
    if stream.at_word("scry"):
        return _parse_scry(stream)
    if stream.at_word("reveal"):
        return _parse_reveal_top(stream)
    if stream.at_word("take"):
        return _parse_extra_turn(stream)
    if stream.at_word("end"):
        return _parse_end_the_turn(stream)
    if stream.at_word("copy"):
        return _parse_copy_that_spell(stream)
    # "**Each opponent** creates a … token" (Pursued Whale). The token maker
    # with a different recipient, which is payload rather than a second
    # production — everything else about the sentence is identical.
    mark_recipient = stream.mark()
    if stream.accept_phrase("each", "opponent") and stream.at_word("creates"):
        token = _parse_create_token(stream)
        assert isinstance(token, ast.CreateToken)
        return dataclasses.replace(token, recipient_players="each_opponent")
    stream.reset(mark_recipient)
    if stream.at_word("choose"):
        # "Choose a number between 0 and 7." (Shapeshifter.) Tried first and
        # non-consuming on refusal, so every other "choose" sentence still
        # reaches the naming production behind it.
        chosen_number = _parse_choose_number(stream)
        if chosen_number is not None:
            return chosen_number
        return _parse_name_and_strip(stream)
    if stream.at_word("draw"):
        return _parse_draw(stream, ast.PlayerRef("you"))
    # A bare "discard N cards" is the effect's *controller* discarding, the same
    # implied subject a bare "draw" already carries. Without it "Draw two cards,
    # then discard three cards" strands its second clause and the whole line
    # fails; with it the line parses and lowering decides whether the pair has a
    # handler.
    if stream.at_word("discard"):
        return _parse_discard(stream, ast.PlayerRef("you"))
    # "Mill four cards." — the same implied controller a bare draw or discard
    # carries. Without this the line dies on "expected a subject", which is
    # what the subject-verb table below says about a sentence that has none.
    if stream.at_word("mill"):
        return _parse_mill(stream, ast.PlayerRef("you"))
    if stream.at_word("counter"):
        return _parse_counter(stream)
    if stream.at_word("enchant"):
        return _parse_enchant(stream)

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
        source_spec = ast.TargetSpec("this", ast.ObjectFilter(is_source=True))
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

    if source_spec is None:
        stream.reset(mark)
        raise stream.error("expected a subject")
    stream.last_subject = source_spec

    token = stream.peek()
    if token is None:
        stream.reset(mark)
        raise stream.error("expected a verb")

    if token.kind == WORD:
        source_target = source_spec if isinstance(source_spec, ast.TargetSpec) else None
        if token.text in ("deals", "deal"):
            return _parse_damage(stream, source_target)
        if token.text in ("fights", "fight"):
            return _parse_fight(stream, source_spec)
        if token.text in ("gets", "get"):
            return _parse_gets(stream, source_spec)
        if token.text in ("gains", "gain"):
            return _parse_gains(stream, source_spec)
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
            return _parse_discard(stream, source_spec)
        if token.text in ("mills", "mill") and isinstance(source_spec, ast.PlayerRef):
            return _parse_mill(stream, source_spec)
        # "Target player **chooses a card name**, then reveals the top card of
        # their library…" (Petra Sphinx) — a paragraph, because the two
        # sentences after it test the name and the card this one produced.
        # Dispatched on the verb like every other player action; the production
        # reads its own words to the end.
        if token.text in ("chooses", "choose") and isinstance(source_spec, ast.PlayerRef):
            return _parse_name_then_reveal_top(stream, source_spec)
        # "Each opponent sacrifices a creature" (Goremand). The AST node has
        # carried its player since it was written; only the *bare* imperative
        # ("Sacrifice a creature", which means you) had a production, so a
        # printed subject was an unrecognized verb.
        if token.text in ("sacrifices", "sacrifice") and isinstance(source_spec, ast.PlayerRef):
            stream.advance()
            return _parse_sacrifice(stream, source_spec)
        if token.text in ("becomes", "become"):
            return _parse_becomes(stream, source_spec)
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
        if token.text in ("can't", "cannot"):
            return _parse_cant_attack_or_block(stream, source_spec)
        # "Those creatures **don't untap** during their controller's next untap
        # step." (Frost Breath.) The verb is checked before dispatching, not
        # inside the production: "You don't lose the game for having 0 or less
        # life" (Lich) is the same auxiliary, and a dispatch on the auxiliary
        # alone replaced its "unrecognized effect verb" with a refusal naming a
        # word Lich never prints. A line this branch cannot finish keeps the
        # refusal it already had.
        if token.text in ("don't", "doesn't") and stream.peek_word(1) == "untap":
            return _parse_doesnt_untap_next_step(stream, source_spec)

    stream.reset(mark)
    raise stream.error("unrecognized effect verb")


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
    statement = _parse_statement_body(stream)
    if not top_level:
        return statement
    definition = _parse_where_x(stream)
    return ast.WhereX(statement, definition) if definition is not None else statement


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


def _parse_statement_body(stream: TokenStream) -> ast.Statement:
    """One sentence's worth of effect, including ``if``/``may`` wrappers."""
    # "Target opponent reveals their hand. You choose … from it. That player
    # discards that card." (Duress.) Read before anything else, because it
    # spans three printed sentences: the sentence loop above would hand the
    # first one to the subject-verb reader, which has no "reveals" and would
    # fail the line on a word that is only the opening of a longer template.
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
    chosen = _parse_choose_target(stream)
    if chosen is not None:
        return chosen
    # "When that creature dies this turn, …" / "At the beginning of your next
    # main phase, …" — a delayed triggered ability (CR 603.7). Read before the
    # productions its inner effect uses, whose sentences this one's tail is:
    # matched first they would perform the effect now, which is the opposite of
    # what the card says.
    delayed_trigger = _parse_create_delayed_trigger(stream)
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

    # "you may <pay a cost | take an action>"
    if stream.at_word("you"):
        mark = stream.mark()
        stream.advance()
        if stream.accept_word("may"):
            if stream.at_word("pay"):
                stream.advance()
                cost = _parse_mana_payment(stream)
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

    statement = _parse_subject_verb(stream)
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
                    follow = _parse_subject_verb(stream, carried_subject=carried)
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


def _parse_where_x(stream: TokenStream) -> ast.Amount | None:
    """``[,] where X is <definition>`` at the sentence level.

    The clause itself is `phrases.parse_where_x_definition`; this is the name
    the statement parser has always called it by.
    """
    return parse_where_x_definition(stream)


def _parse_copy_that_spell(stream: TokenStream) -> ast.Statement:
    """``Copy that spell. You may choose new targets for the copy.``

    Both sentences, every word. The second is CR 707.10's choice and part of
    what the card does; consuming it is also what stops this production
    claiming a bare "copy that spell" no card prints.
    """
    for word in ("copy", "that", "spell"):
        stream.expect_word(word)
    if not stream.accept_punct("."):
        raise stream.error("expected the new-targets sentence after the copy")
    for word in (
        "you", "may", "choose", "new", "targets", "for", "the", "copy",
    ):
        stream.expect_word(word)
    return ast.CopyThatSpell()


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
    first = parse_statement(stream, top_level=False)
    if not stream.at_word("or"):
        return first
    options = [first]
    spans = [(first_at, stream.pos)]
    while stream.accept_word("or"):
        start = stream.pos
        options.append(parse_statement(stream, top_level=False))
        spans.append((start, stream.pos))
    return ast.OneOf(tuple(options), tuple(stream.text_between(a, b) for a, b in spans))


# ---------------------------------------------------------------------------
# Delayed triggered abilities (CR 603.7)
# ---------------------------------------------------------------------------

# Which printed opener names which delayed-trigger event, and what the two
# words CR 603.7 turns into fields say:
#
#   ``once``        CR 603.7b — "when" triggers once, "whenever" keeps
#                   triggering for as long as the ability lasts.
#   ``duration``    how long an ability that never triggers survives. "This
#                   turn" expires with the turn; an ability naming a future
#                   step waits for that step however many turns away it is.
#   ``binds``       whether the opener is about "**that** <noun>" — the object
#                   the creating spell targeted (CR 603.7c).
#
# A table rather than a production each, because the difference between these
# rows is four values and no structure at all. The event names are keys of
# ``engine/delayed_triggers.DELAYED_EVENTS``; one that is not is refused when
# the sentence is lowered, so a new row cannot arm an ability nothing announces.
_DELAYED_OPENERS: tuple[tuple[tuple[str, ...], str, bool, str, bool], ...] = (
    # "At the beginning of your next main phase, …" (Mana Drain). Either main
    # phase of the controller's — whichever one comes next.
    (("at", "the", "beginning", "of", "your", "next", "main", "phase"),
     "controllers_next_main_phase", True, "until_it_triggers", False),
    # "At this turn's next end of combat, …" (Glyph of Doom).
    (("at", "this", "turn", "'s", "next", "end", "of", "combat"),
     "next_end_of_combat", True, "end_of_turn", True),
)


def _delayed_bound_subject(stream: TokenStream) -> "ast.ObjectFilter | None":
    """``that creature`` — the noun phrase naming the object an earlier
    sentence of the same spell chose, as a filter.

    :func:`phrases.parse_bound_subject` is the one reader of the phrase; this
    only asks for the singular half of it and hands back the filter. "Those
    creatures" is a *list* the delayed-trigger machinery has no shape for —
    one entry binds one permanent id — so it is refused rather than silently
    bound to whichever one the reader returned first.

    The phrase is read rather than skipped, and travels as the delayed
    ability's own subject filter, for the reason
    ``delayed_destroy_blocked_or_blocker`` states about "destroy that
    **Wall**": the id already names the object exactly, so the noun re-states
    rather than narrows — but a word consumed and never read is a word that
    could be deleted with no change to what the card does, and this engine
    does not leave one lying in a payload.
    """
    spec = parse_bound_subject(stream)
    if spec is None or spec.quantifier != "that":
        return None
    return spec.filter


def _parse_create_delayed_trigger(stream: TokenStream) -> "ast.CreateDelayedTrigger | None":
    """A sentence that **creates** a delayed triggered ability (CR 603.7).

    ``When that creature dies this turn, <effect>.`` (Reincarnation)
    ``Whenever that creature is dealt damage by <phrase> this turn, <effect>.``
      (Glyph of Life)
    ``At the beginning of your next main phase, <effect>.`` (Mana Drain)

    The whole sentence, delay included, for the reason
    ``_parse_delayed_self_action`` gives: the effect on its own is performed
    *now*, and a spell that gains the life immediately is a different card from
    one that gains it when a creature is next damaged.

    The inner effect is parsed by the ordinary sentence parser, so a delayed
    ability's effect is every effect this engine has, and one that fails to
    parse refuses the whole line rather than arming an ability that fires into
    nothing.
    """
    mark = stream.mark()
    event: str | None = None
    once = True
    duration = "end_of_turn"
    binds = False
    subject = None
    agent = None

    if stream.accept_word("when"):
        # "When that creature dies this turn, …"
        subject = _delayed_bound_subject(stream)
        if subject is not None and stream.accept_phrase("dies", "this", "turn"):
            event, binds = "bound_permanent_dies", True
    elif stream.accept_word("whenever"):
        # "Whenever that creature is dealt damage by an attacking creature this
        # turn, …" — "this turn" is CR 603.7b's stated duration, so this one
        # fires every time for as long as it lasts.
        subject = _delayed_bound_subject(stream)
        if subject is not None and stream.accept_phrase("is", "dealt", "damage", "by"):
            # The indefinite article is the noun parser's caller's business
            # everywhere in this grammar: `parse_object_filter` reads the
            # phrase from the noun onward.
            stream.accept_word("a", "an")
            try:
                agent = parse_object_filter(stream)
            except GrammarError:
                agent = None
            if agent is not None and stream.accept_phrase("this", "turn"):
                event, binds, once = "bound_permanent_dealt_damage", True, False
    else:
        for phrase, kind, kind_once, kind_duration, kind_binds in _DELAYED_OPENERS:
            if stream.accept_phrase(*phrase):
                event, once, duration, binds = kind, kind_once, kind_duration, kind_binds
                break

    if event is None:
        stream.reset(mark)
        return None
    if not stream.accept_punct(","):
        stream.reset(mark)
        return None
    try:
        effect = parse_statement(stream, top_level=False)
    except GrammarError:
        stream.reset(mark)
        return None
    # The delay governs its whole sentence, so the effect has to run to the end
    # of one. Without this the production would accept a *prefix* — "destroy
    # all creatures" out of "destroy all creatures that were blocked by that
    # creature this turn" — and the words left over would either fail the line
    # somewhere that says nothing about what happened or, worse, parse as a
    # sentence of their own and be performed **now** rather than when the
    # ability fires. Declining instead leaves the refusal the line already had.
    if not stream.exhausted and not stream.at_punct(".", ";"):
        stream.reset(mark)
        return None
    return ast.CreateDelayedTrigger(
        event=event, effect=effect, once=once, duration=duration,
        binds_target=binds, subject=subject, agent=agent,
    )


def _parse_choose_target(stream: TokenStream) -> "ast.ChooseTarget | None":
    """``Choose target creature.`` — a sentence whose whole content is
    CR 601.2c's choosing of targets (Reincarnation, Glyph of Life).

    **It is only a sentence when the next one binds what it chose.** A spell
    whose only instruction chose a target and then did nothing would report
    itself supported while doing nothing at all, which is the failure this
    engine refuses loudly everywhere else. So the following sentence is parsed
    as a probe and the tokens handed straight back: if it is not a delayed
    triggered ability about "that <noun>", this production declines and the
    line fails on whatever it really says.
    """
    mark = stream.mark()
    if not stream.accept_phrase("choose", "target"):
        stream.reset(mark)
        return None
    try:
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    after_filter = stream.mark()
    if not stream.accept_punct("."):
        stream.reset(mark)
        return None
    delayed = _parse_create_delayed_trigger(stream)
    stream.reset(after_filter)
    if delayed is None or not delayed.binds_target:
        stream.reset(mark)
        return None
    return ast.ChooseTarget(ast.TargetSpec("target", filt, targeted=True))

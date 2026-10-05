"""How a printed line's sentences join into one statement.

``_statements_from_sentences`` is the loop: it reads sentence after sentence off
whatever token stream it is handed, folds a rider into the step in front of it
rather than appending one, and returns the single statement — or the
``Sequence`` — the line came to. Around it sit the four readers only that loop
calls: the sentence a text-keyed registry runs end to end, the closing quote
that stands in for a sentence's full stop, the "who may activate this" that
folds into a granted ability's quoted text, and the statement-level "or".

Split out of ``parser`` at Urza's Legacy's Phase 0, ten lines under the size
guard with five groups about to open on the parser — the shared-module case
SET_PLAYBOOK.md says to pre-split rather than to brief. The seam is the one
``parser``'s own docstring draws when it lists what that file is: "what kind of
line is this …, what costs and trigger event does it carry, **how do its
sentences join**, and ``parse_line``". The call graph agrees with the prose
exactly — six functions that call each other and no line production, against
six that call this and each other — which is what makes it a family rather than
a cut. The line layer decides *which* tokens are a sentence sequence (the half
after an activation colon, the half after a trigger's comma, the body of a
quoted-token line, the whole line); this reads them.

``riders``' docstring records that "the loop that drives them stays behind in
``parser.py`` with the line-level productions it belongs to", which was true of
the seam that sentence describes and is not true of the file. The loop is not a
line production; it is what a line production is *handed*. Above ``riders``,
``repeats``, ``control_flow`` and ``pronouns`` — every attacher this loop drives
had already left ``parser`` for this same guard, and none of them reaches back.
(Five modules now: ``conditional_instead`` was cut out of ``control_flow`` at
Invasion's Phase 0, and its one rider is driven from here like the rest.)
Below ``parser``, whose import of ``_statements_from_sentences`` is also that
name's re-export, so its old address still answers. Only that one: the five
readers around it are pulled by nothing outside this module, and
``tests/engine/test_import_hygiene.py`` reads a re-export nobody pulls as the
stale binding a move leaves behind — a re-export is for a caller that exists.

The name is ``lowering/sequences.py``'s, and the two are one subject from
opposite ends: this builds the ``ast.Sequence`` out of the printed sentences and
that lowers it, threading each step's records forward into the next. Different
packages, neither importing the other, so the mirror re-forms rather than forks
— the arrangement ``zones`` and ``records`` already have with their own
lowering twins.
"""

import dataclasses

from . import ast
from .conditional_instead import _parse_conditional_instead_rider
from .control_flow import (_attach_if_that_card_was_returned, _attach_if_you_cant,
                          _attach_if_you_do, _attach_otherwise, _attach_when_you_do,
                          _attach_tied_life_draw, _parse_who_cant_rider)
from .effects import (
    _parse_activation_restriction,
    _parse_x_spend_restriction,
    _parse_cost_x_definition,
    _parse_damage_rider_sentence,
    _parse_unpaid_penalty_sentence,
)
from .errors import GrammarError
from .lexer import (PUNCT, QUOTE)
from .pronouns import (_RIDER_FOLDED, _attach_returned_text_change,
                       _attach_sacrifice_when_control_lost,
                       _parse_conditional_pronoun_grant_rider,
                       _parse_conditional_quoted_grant_rider,
                       _parse_exile_instead_of_leaving_rider,
                       _parse_its_controller_creates_rider,
                       _parse_pronoun_counter_rider,
                       _parse_plural_pronoun_pump_rider,
                       _parse_conditional_set_pump_rider,
                       _parse_pronoun_grant_rider, _parse_pronoun_verb_rider,
                       _parse_that_controller_reveals_rider)
from .sentence_rebinding import (
    rebind_alternative_pronoun_to_choice_target,
    rebind_delayed_pronoun_to_sentence_target,
    rebind_keyword_loss_pronoun_to_clause_target,
    rebind_pump_pronoun_to_sentence_target,
    rebind_token_maker_to_previous_player,
)
from .repeats import (_attach_repeat_for_types,
                      _attach_repeat_optional_process,
                      _attach_repeat_this_process,
                      _attach_repeat_until_pile_chosen,
                      _attach_repeat_while_condition)
from .riders import (_attach_destroyed_this_way, _attach_flip_stakes_to_loop,
    _attach_no_regeneration,
    _attach_unaffected_when_cost_paid, _attach_exchanged_this_way, _attach_tap_when_control_lost, _attach_riders, _attach_conditional_damage_riders, _attach_source_damage_lock, _attach_counter_cap, _attach_new_target_bound, _attach_spend_only, _attach_superlative_tie_break, _attach_unpaid_penalty, _parse_exile_instead_rider)
from .statements import (
    _parse_condition,
    parse_statement,
)
from .stream import TokenStream
# The two riders behind an offered change of targets (Psychic Battle). On a
# line of their own rather than in the list above: that list is one long line
# every round appends to, and a second import statement cannot collide with it.
from .riders import _attach_silent_target_change, _attach_tied_reveals_unchanged
# "This cost is reduced by {2} for each …" (Draco) — a rider on the toll in
# front of it, and it lives with the tolls because what it narrows is a price.
from .tolls import _attach_toll_cost_reduction


def _parse_registry_claimed_sentence(stream: TokenStream) -> bool:
    """Consume a trailing sentence a text-keyed registry implements end to end.

    "{5}{W}: Tap target creature. **This ability costs {1} less to activate for
    each Shrine you control.**" (Sanctum of Tranquil Light.) The reduction is a
    whole sentence inside an activated ability's printed line, and it is not an
    effect — `engine/cost_modifiers.py` applies it while the cost is being paid,
    so there is nothing here for a production to lower.

    "{R}, {T}: … **You may pay {R} to end this effect.**" (Tempest's Licids) is
    the same shape one registry over: CR 116.2c's special action, offered by
    `engine/special_actions.py` for as long as the effect the two sentences in
    front of it created is running.

    The claim **delegates to the implementing code** rather than restating its
    words, which is the rule `engine/grammar/registries.py` states for the
    whole-line case: a copy of the phrase here would be free to drift, and a
    drifted copy would consume a sentence nothing runs. The sentence's own source
    text is sliced back out of the line through the tokens' offsets and handed to
    the registry's matcher.
    """
    from ..cost_modifiers import cost_modifier_claims_line
    from ..resolution_overrides import resolution_override_sentence
    from ..special_actions import permanent_special_action_sentence

    mark = stream.mark()
    start_token = stream.peek()
    if start_token is None:
        return False
    end = start_token.end
    while not stream.exhausted:
        token = stream.peek()
        if token is None:
            break
        if token.kind == PUNCT and token.text == ".":
            break
        end = token.end
        stream.advance()
    text = stream.line[start_token.start:end]
    if cost_modifier_claims_line(text):
        stream.accept_punct(".")
        return True
    # "**You may pay {R} to end this effect.**" (Tempest's five Licids.) The
    # third sentence of an activated ability's line, and not an effect either:
    # CR 116.2c makes it a *special action*, taken later, with priority, without
    # the stack — so there is nothing here for a production to lower and the
    # sentence is consumed by the table that performs it
    # (`engine/special_actions.py`), exactly as the cost reduction above is.
    if permanent_special_action_sentence(text) is not None:
        stream.accept_punct(".")
        return True
    # "**This ability still resolves if its target becomes illegal.**" (Gilded
    # Drake.) The fourth sentence of a triggered ability's line, and not an
    # effect either: it says what the *rules* do with the object when it begins
    # to resolve (CR 608.2b), so there is nothing here for a production to lower
    # and the sentence is consumed by the table `engine/legality.py` reads —
    # exactly as the cost reduction and the special action above are.
    if resolution_override_sentence(text) is not None:
        stream.accept_punct(".")
        return True
    stream.reset(mark)
    return False


def _sentence_ended_on_a_quote(stream: TokenStream) -> bool:
    """Whether the sentence just read ended on a closing quotation mark.

    "…that creature gains "Remove a matrix counter from this creature:
    Regenerate this creature." **Activate only during your upkeep.**" (Life
    Matrix.) Magic prints the sentence's full stop *inside* the quoted ability,
    so the quoted ability's own terminator ends the outer sentence as well and
    there is no bare "." left for the loop below to see. Without this the words
    behind the quote read as unconsumed text and the whole line refuses — which
    is the loud failure this parser wants everywhere the boundary is genuinely
    missing, and exactly the wrong answer where the card printed one.
    """
    previous = stream.peek(-1)
    return previous is not None and previous.kind == QUOTE


def _attach_granted_ability_permission(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold a trailing "who may activate" sentence into the ability the step
    before it granted, and say whether one was found.

    "Until end of turn, target creature you control gains "{0}: …" **Only you
    may activate this ability.**" (Martyrdom.) The permission is about the
    granted ability, not about the spell: what reaches the battlefield is the
    quoted line, and `engine/keywords.py` records exactly that string for
    `Permanent.effective_card` to fold in and the compiler to read. A clause
    left outside it belongs to a spell that is in its owner's graveyard by the
    time anyone activates — read there it would restrict nothing.

    So the sentence is appended to the quoted text, which is the same rewrite
    `oracle.expand_equip_lines` makes one layer up and for the same reason:
    every reader of what the creature now says has to see the same sentence.
    `engine/activation_permissions.py` is asked first, so a permission that
    module does not implement leaves the line refused rather than consumed and
    dropped.

    Only a grant with **one** quoted ability is claimed. A sentence naming
    "this ability" after two of them names one of the two and the card would
    have to say which; nothing prints that, and guessing is what this refuses.
    """
    from ..activation_permissions import permission_clause_readable

    if not steps or not isinstance(steps[-1], ast.GainAbilityText):
        return False
    grant = steps[-1]
    if len(grant.abilities) != 1:
        return False
    mark = stream.mark()
    stream.accept_punct(".", ";")
    if not stream.at_word("any", "only"):
        stream.reset(mark)
        return False
    words: list[str] = []
    while not stream.exhausted and not stream.at_punct("."):
        words.append(str(stream.next().text))
    sentence = " ".join(words).replace(" '", "'")
    if not permission_clause_readable(sentence):
        stream.reset(mark)
        return False
    stream.accept_punct(".")
    steps[-1] = dataclasses.replace(
        grant, abilities=(f"{grant.abilities[0]}. {sentence.capitalize()}",)
    )
    return True


def _at_alternative(stream: TokenStream) -> bool:
    """Whether the cursor is on the "or" that opens a statement alternative.

    One reader for both spellings — a bare "or" and a comma in front of it —
    so the loop below and its own guard cannot disagree about where an
    alternative starts. Non-consuming in every branch: the probe past a comma
    rewinds, because a comma followed by anything else is still the caller's
    "unconsumed text".
    """
    if stream.at_word("or"):
        return True
    if not stream.at_punct(","):
        return False
    mark = stream.mark()
    stream.advance()
    found = stream.at_word("or")
    stream.reset(mark)
    return found


def _parse_statement_alternatives(
    stream: TokenStream, first: ast.Statement, first_at: int
) -> ast.Statement:
    """*first*, or an :class:`ast.OneOf` if the sentence goes on with "**or**".

    "Put a +1/+1 counter on target creature **or** that creature gains banding,
    first strike, or trample." (Nature's Blessing.) One action with two ways to
    take it, the controller choosing which as the effect is applied
    (CR 608.2d) — not a `Sequence`, which does both, and not a modal spell's
    bulleted "Choose one —", which is chosen as the spell is cast (CR 601.2b).

    ``statements._parse_optional_action`` already reads this shape behind "you
    may" (Crypt Lurker) and its docstring records why it was written there and
    not at large: a statement-level "or" is rare, and putting a production in
    front of every sentence in the game on the strength of one card is a bad
    trade. What makes this position safe is not the count of cards but *where
    it sits*: the statement has already been parsed and the cursor is on a word
    that is neither a full stop nor a semicolon, which is the state the line
    fails in three lines further down. So this can only claim text that is
    being refused today.

    An alternative that does not parse is left alone — the cursor rewinds and
    the "unconsumed text" refusal below stands, naming the same offset it names
    now.

    **A comma may stand in front of the "or"**, and that is the same sentence:
    "Tap all untapped permanents of the chosen type target player controls**,
    or** untap all tapped permanents of that type that player controls."
    (Turnabout.) The punctuation separates two long clauses and says nothing
    about how many actions are taken. Safe for the reason above and *only* that
    reason: a comma at this position is where the line fails today — the caller
    raises "unconsumed text" for anything that is neither a full stop nor a
    semicolon — so the widened probe can claim no reading anything else has.
    """
    if not _at_alternative(stream):
        return first
    options: list[ast.Statement] = [first]
    spans: list[tuple[int, int]] = [(first_at, stream.pos)]
    while _at_alternative(stream):
        mark = stream.mark()
        stream.accept_punct(",")
        stream.advance()
        start = stream.pos
        try:
            options.append(parse_statement(stream, top_level=False))
        except GrammarError:
            stream.reset(mark)
            break
        spans.append((start, stream.pos))
    if len(options) == 1:
        return first
    return rebind_alternative_pronoun_to_choice_target(
        ast.OneOf(
            tuple(options), tuple(stream.text_between(a, b) for a, b in spans)
        )
    )


def _statements_from_sentences(stream: TokenStream) -> ast.Statement:
    """Parse the remaining tokens as one or more sentences, joining them into a
    ``Sequence``. A rider sentence folds into the effect it modifies instead of
    becoming a step of its own."""
    steps: list[ast.Statement] = []
    while not stream.exhausted:
        if stream.accept_punct(".", ";", ","):
            continue
        # A sentence opening with "Then …" ("Create a 3/3 green Beast creature
        # token. Then if an opponent controls more creatures than you, …",
        # Garruk, Unleashed) — sequencing the sentence loop already provides.
        if steps and stream.accept_word("then"):
            continue

        if steps:
            # A sentence a text-keyed registry runs, rather than an effect. It
            # contributes no step, which is the point: the words are accounted
            # for and the table does the work.
            if _parse_registry_claimed_sentence(stream):
                continue
            riders_at = stream.mark()
            restated = stream.at_word("that")
            riders = _parse_damage_rider_sentence(stream)
            if riders is not None:
                # "**That creature** can't be regenerated this turn" behind a
                # step that deals no damage is another reader's sentence (the
                # ``CantBe`` production's, which names the creature rather
                # than riding a damage event), so that spelling rewinds and
                # the loop goes on. The pronoun spelling does **not**: "Tap
                # target creature. It can't be regenerated this turn." fails
                # here and must keep failing — let through, the bare "it"
                # lowers as the ability's own source and the line compiles
                # denying regeneration to the wrong permanent.
                try:
                    steps[-1] = _attach_riders(steps[-1], riders)
                except GrammarError:
                    if not restated:
                        raise
                    stream.reset(riders_at)
                else:
                    continue
            penalty = _parse_unpaid_penalty_sentence(stream)
            if penalty is not None:
                steps[-1] = _attach_unpaid_penalty(steps[-1], penalty)
                continue
            if _attach_if_you_do(stream, steps):
                continue
            if _attach_if_that_card_was_returned(stream, steps):
                continue
            if _attach_if_you_cant(stream, steps):
                continue
            if _attach_when_you_do(stream, steps):
                continue
            # "Repeat this process until no one puts a card onto the
            # battlefield." (Eureka.) A clause about the sentence before it,
            # folded into that sentence the way every other rider here is.
            if _attach_repeat_this_process(stream, steps):
                continue
            # "You may repeat this process any number of times." (Forbidden
            # Ritual.) The same word about *every* sentence read so far rather
            # than about the last one, and a different mechanism behind it —
            # see `engine/grammar/repeats.py`, which holds both and says why
            # they are not one production.
            if _attach_repeat_optional_process(stream, steps):
                continue
            # "Repeat this process for artifacts and creatures." (Equipoise.)
            # The same word again and a third mechanism behind it: a printed
            # list of parameters rather than a loop.
            if _attach_repeat_for_types(stream, steps):
                continue
            # "If two cards that share a color were milled this way, repeat
            # this process." (Grindstone.) The fourth mechanism behind the same
            # word — a loop that ends on a condition asked of what the round
            # just did. Read here, after the three above and before the
            # `Otherwise` rider, because it opens on "if" and none of them do.
            if _attach_repeat_while_condition(stream, steps):
                continue
            # "Repeat this process until all cards exiled this way have been
            # chosen." (Thieves' Auction.) The fifth mechanism behind the same
            # word — a loop bounded by a pile emptying. Beside the four above
            # and after them only because it declines without consuming, like
            # every one of them.
            if _attach_repeat_until_pile_chosen(stream, steps):
                continue
            # "For each blocking creature, flip a coin. **If you win the
            # flip, prevent all combat damage that would be dealt by that
            # creature this turn.**" (Fighting Chance.) The stakes of a flip
            # the loop makes once per member, so they belong inside the loop —
            # read before `_attach_otherwise` below only because both open on a
            # word the other does not, and this one is the narrower question.
            if _attach_flip_stakes_to_loop(stream, steps):
                stream.accept_punct(".")
                continue
            # "If two or more creatures are tied for least toughness, you
            # choose one of them." (Purging Scythe, Drop of Honey.) CR 608.2d's
            # choice on the superlative the sentence in front of it picked
            # by — no step of its own, because that sentence's own
            # ``choose_permanent`` already carries ``only_on_tie``. Read before
            # `Otherwise` and after the four "repeat" riders for the reason
            # every ordering here is documentation rather than precedence: it
            # opens on "if two or more", which none of them does, and it
            # refuses without consuming.
            if _attach_superlative_tie_break(stream, steps):
                continue
            # "If two or more players are tied for highest life total, the game
            # is a draw." (Celestial Convergence.) The other arm of the win in
            # front of it, beside the creature tie-break above for the order's
            # reason: both open on "if two or more" and each refuses without
            # consuming whatever the other one reads.
            if _attach_tied_life_draw(stream, steps):
                continue
            # "Otherwise, it gets +4/-X until end of turn." (Blood Lust.) The
            # second arm of the conditional sentence before it.
            if _attach_otherwise(stream, steps):
                stream.accept_punct(".")
                continue
            # "This ability can't cause the total number of +1/+0 counters on
            # this creature to be greater than N." (the Clockwork cycle.) A
            # bound on the sentence before it, not a step.
            # "If this creature is destroyed this way, it deals 7 damage to
            # you." (Cosmic Horror.) A consequence of what the sentence before
            # it did, not a step.
            if _attach_destroyed_this_way(stream, steps):
                stream.accept_punct(".")
                continue
            # "This cost is reduced by {2} for each basic land type among lands
            # you control." (Draco.) A size on the price the sentence before it
            # offered, not a step: alone, "this cost" names nothing. Opens on
            # words no other rider here reads and refuses without consuming.
            if _attach_toll_cost_reduction(stream, steps):
                stream.accept_punct(".")
                continue
            # "A creature destroyed this way can't be regenerated." (Soul Rend.)
            # CR 701.19c's rider on a destroy the sentence layer has already
            # wrapped in a conditional, which is why the destroy production's
            # own probe of the same words could not reach it.
            if _attach_no_regeneration(stream, steps):
                stream.accept_punct(".")
                continue
            # "If this spell's additional cost was paid, this effect doesn't
            # affect combat damage that would be dealt by red creatures."
            # (Undergrowth.) A width on the prevention the sentence before it
            # created, not a step: "this effect" names that one and nothing
            # else.
            if _attach_unaffected_when_cost_paid(stream, steps):
                stream.accept_punct(".")
                continue
            # "When you lose control of the creature, tap it." (Ray of
            # Command.) CR 603.7's delayed trigger on the control change the
            # sentence before it made — a clause about that sentence, not a
            # step: alone, "the creature" names nothing.
            # "Sacrifice the creature when you lose control of this creature."
            # (Seraph, Krovikan Vampire.) The same CR 603.7 delay one verb over,
            # and read beside its sibling so the two spellings of "when you lose
            # control" stay together — but folded onto a battlefield *entry*
            # rather than onto a control change, which is why it is its own
            # production and lives with the pronoun binders.
            if _attach_sacrifice_when_control_lost(stream, steps):
                continue
            if _attach_tap_when_control_lost(stream, steps):
                stream.accept_punct(".")
                continue
            # "If those permanents are exchanged this way, destroy all Auras
            # attached to them." (Gauntlets of Chaos.) Same shape, same reason.
            if _attach_exchanged_this_way(stream, steps):
                stream.accept_punct(".")
                continue
            if _attach_counter_cap(stream, steps):
                stream.accept_punct(".")
                continue
            # "The new target must be a player." (Reflecting Mirror.) A bound on
            # the choice the sentence before it will make at resolution, not a
            # step of its own.
            if _attach_new_target_bound(stream, steps):
                stream.accept_punct(".")
                continue
            # "If two or more cards are tied for greatest, the target or
            # targets remain unchanged." / "Changing targets this way doesn't
            # trigger abilities of permanents named ~." (Psychic Battle.) Two
            # sentences about the change the sentence before them offered —
            # the first restates that offer's own strictness and contributes
            # nothing, the second is a flag on it. Beside the retarget bound
            # above for the family's sake; each opens on words nothing else
            # here reads behind an offered change and refuses without consuming.
            if _attach_tied_reveals_unchanged(stream, steps):
                stream.accept_punct(".")
                continue
            if _attach_silent_target_change(stream, steps):
                stream.accept_punct(".")
                continue
            if _attach_spend_only(stream, steps):
                continue
            pronoun_verb = _parse_pronoun_verb_rider(stream, steps)
            if pronoun_verb is not None:
                steps.append(pronoun_verb)
                continue
            # "Untap two target creatures. **Each of them** gets +1/+1 until
            # end of turn." (Hope and Glory.) The plural of the pronoun the
            # riders around it bind, and read here beside them because its
            # antecedent is the same thing: the several targets the sentence
            # before it chose. Parsed fresh, "each of them" is not a subject
            # this grammar reads at all and the whole line refuses.
            plural_pump = _parse_plural_pronoun_pump_rider(stream, steps)
            if plural_pump is not None:
                steps.append(plural_pump)
                continue
            # "Creatures you control gain first strike until end of turn. **If
            # this spell was kicked, they get +1/+1 until end of turn.**"
            # (Savage Offensive.) The plural again, with a *set* for an
            # antecedent rather than several targets.
            set_pump = _parse_conditional_set_pump_rider(stream, steps)
            if set_pump is not None:
                steps.append(set_pump)
                continue
            # "…and put a -1/-0 counter on **it**." (Jabari's Influence.) The
            # counter's own pronoun, beside the imperative one above: parsed
            # fresh, "it" is the ability's source and the counter lands on the
            # wrong permanent — or, for a spell, on nothing at all.
            pronoun_counter = _parse_pronoun_counter_rider(stream, steps)
            if pronoun_counter is not None:
                steps.append(pronoun_counter)
                continue
            # "It loses "enchant creature" and gains "…"." (Takklemaggot.) The
            # quoted half, read before the keyword rider below, whose "It
            # loses …" reading is about a keyword and would refuse a quote.
            if _attach_returned_text_change(stream, steps):
                stream.accept_punct(".")
                continue
            pronoun_grant = _parse_pronoun_grant_rider(stream, steps)
            if pronoun_grant is not None:
                if pronoun_grant is not _RIDER_FOLDED:
                    steps.append(pronoun_grant)
                continue
            conditional_grant = _parse_conditional_pronoun_grant_rider(stream, steps)
            if conditional_grant is not None:
                steps.append(conditional_grant)
                continue
            # "If it doesn't have "<ability>," it gains that ability."
            # (Musician.) The quoted twin of the rider above, read after it
            # because that one's condition parser would refuse a quote and
            # rewind — leaving this sentence to fail the whole line.
            quoted_grant = _parse_conditional_quoted_grant_rider(stream, steps)
            if quoted_grant is not None:
                steps.append(quoted_grant)
                continue
            who_cant = _parse_who_cant_rider(stream, steps)
            if who_cant is not None:
                steps.append(who_cant)
                continue
            # "If the creature would leave the battlefield, exile it instead
            # of putting it anywhere else." (Dreams of the Dead.) Read before
            # the two "instead" riders below, whose own openings would consume
            # the "if" and rewind — leaving this sentence to fail the line.
            if _parse_exile_instead_of_leaving_rider(stream, steps) is not None:
                continue
            if _parse_exile_instead_rider(stream, steps):
                continue
            if _parse_conditional_instead_rider(stream, steps):
                continue
            # "If this spell was kicked, that creature can't be regenerated
            # this turn and if it would die this turn, exile it instead."
            # (Scorching Lava.) The damage riders the loop's first probe reads,
            # under a condition; beside the "instead" pair because it builds
            # the same two-armed step from one sentence.
            if _attach_conditional_damage_riders(stream, steps):
                continue
            # "If <the source> would deal damage to a creature, that damage
            # can't be prevented or dealt instead to another permanent or
            # player." (Lava Burst.) A statement about the damage the sentence
            # in front of it deals, so it folds into that sentence's riders.
            if _attach_source_damage_lock(stream, steps):
                stream.accept_punct(".")
                continue
            reveals = _parse_that_controller_reveals_rider(stream, steps)
            if reveals is not None:
                steps.append(reveals)
                continue
            controller_token = _parse_its_controller_creates_rider(stream, steps)
            if controller_token is not None:
                steps.append(controller_token)
                continue
            # "…gains "<ability>." **Only you may activate this ability.**"
            # (Martyrdom.) A sentence about the *granted* ability, printed
            # outside the quotes because the quotes hold what the creature
            # gains and this says who may use it — so it folds into the quoted
            # text rather than becoming a step. Read before the trailing
            # restriction below, which would consume the same sentence and
            # record it on a **spell**: the spell is in a graveyard by the time
            # anybody activates, so the clause would be enforced by nobody.
            if _attach_granted_ability_permission(stream, steps):
                continue
            # A trailing "Activate only during your upkeep." belongs to the
            # ability, not to the effect. Consuming it here keeps the line
            # fully accounted for; enforcement stays on the raw text.
            if _parse_activation_restriction(stream) is not None:
                continue
            # A trailing "X is the number of pin counters on this artifact."
            # belongs to the ability's *cost*, not to its effect — same
            # arrangement, same reason, and enforcement likewise stays on the
            # raw text (engine/cost_x_definitions.py).
            if _parse_cost_x_definition(stream) is not None:
                continue
            # A trailing "Spend only red mana on X." (Crimson Hellkite) belongs
            # to the cost too — the third of the same family, consumed here and
            # charged by the activation path off the raw text.
            if _parse_x_spend_restriction(stream) is not None:
                continue

        sentence_at = stream.pos
        statement = parse_statement(stream)
        # "Destroy this enchantment **if it has five or more hunger counters on
        # it**." (Fasting.) The trailing spelling of the "if <condition>,
        # <statement>" sentence `statements.py` already reads — one clause, one
        # meaning, printed at the other end. It is folded here rather than
        # inside `parse_statement` because the condition modifies the whole
        # sentence, and a production that consumed it would have to be written
        # once per verb.
        #
        # Refusing without consuming (the reset below) is what keeps every
        # other "if" reading intact: a clause `_parse_condition` cannot describe
        # falls through to the "unconsumed text" error it already raised, rather
        # than being silently dropped off a card that would then destroy itself
        # unconditionally.
        if not stream.exhausted and stream.at_word("if"):
            if_mark = stream.mark()
            stream.advance()
            try:
                condition = _parse_condition(stream)
            except GrammarError:
                stream.reset(if_mark)
            else:
                statement = ast.Conditional(condition, statement)
        # "…deals 2 damage to that player **unless one of their opponents was
        # dealt damage this turn**." (Antagonism.) The same trailing clause with
        # the printed word that puts the body on the *false* branch. Read here,
        # beside the "if" above, because it modifies the whole sentence for that
        # branch's reason exactly — and read **after** it, so nothing changes
        # for a sentence that printed neither word.
        #
        # ``tolls.accept_trailing_toll`` has already had its say on this
        # sentence by now and returns None for anything that is not a price, so
        # an "unless <player> pays …" never reaches here — the two readers name
        # the two things the word can introduce, and neither claims the other's.
        #
        # Refusing without consuming keeps a clause `_parse_condition` cannot
        # describe failing the line as unconsumed text, rather than being
        # dropped off a card that would then fire unconditionally.
        elif not stream.exhausted and stream.at_word("unless"):
            unless_mark = stream.mark()
            stream.advance()
            try:
                condition = _parse_condition(stream)
            except GrammarError:
                stream.reset(unless_mark)
            else:
                statement = ast.Conditional(condition, statement, negated=True)
        statement = _parse_statement_alternatives(stream, statement, sentence_at)
        steps.append(statement)
        if (
            not stream.exhausted
            and not stream.at_punct(".", ";")
            and not _sentence_ended_on_a_quote(stream)
        ):
            raise stream.error("unconsumed text")

    if not steps:
        raise GrammarError("empty line", line=stream.line)
    # One sentence has nothing in front of it to refer back to; a sequence
    # does, and this is the one place a whole printed line's sentences are in
    # hand. It runs here rather than in `parse_line`'s tail because an
    # activated ability's effect never reaches that tail -- and an activated
    # ability is exactly where Orcish Captain prints the pronoun.
    # The cross-*clause* pronoun, which a one-sentence line can also print:
    # "…and that creature loses flying until end of turn" (Burning Palm
    # Efreet). Run over every line rather than only over a multi-sentence one,
    # because the `Sequence` it reads is the one `statements.py` built from an
    # "and" join inside a single sentence.
    if len(steps) == 1:
        return rebind_keyword_loss_pronoun_to_clause_target(steps[0])
    sequence = rebind_keyword_loss_pronoun_to_clause_target(
        rebind_pump_pronoun_to_sentence_target(ast.Sequence(tuple(steps)))
    )
    # The other cross-sentence pronoun, and the same argument: "remove all
    # -1/-1 counters from **the creature**" (Giant Oyster) names the creature
    # the sentence in front of it chose, and read as the bare source pronoun it
    # empties the ability's own permanent instead. Composed rather than folded
    # into the walk above, because the two rewrite different nodes under
    # different conditions — see `rebinding.py` for why each is narrow.
    return rebind_token_maker_to_previous_player(
        rebind_delayed_pronoun_to_sentence_target(sequence)
    )

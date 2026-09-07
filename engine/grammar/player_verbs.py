"""``<player> <verb> …`` — the sentences whose subject is a *seat*.

Split out of `subject_verb` at the thousand-line guard, along the seam that
module's dispatch had already drawn for itself: one contiguous run of verb
branches, every one of them gated on ``isinstance(source_spec, ast.PlayerRef)``.
"Target player draws a card", "each player sacrifices a creature", "that player
may pay {R}{R}" — what these have in common is not the verb but that the actor
is a *player* rather than a permanent, and the two vocabularies barely overlap:
a permanent never draws and a seat never fights.

The run is moved **whole and in order**, and that is load-bearing rather than
tidy. These branches are arms of one fall-through chain: a branch that declines
without consuming falls through to the next, and several pairs are correct only
in the order they are written (tap/untap sits behind the simultaneous reader;
"puts" behind its three library shapes). So the caller asks this reader once,
at exactly the point the first branch used to sit, and carries on where the
last one used to fall through — the extraction changes which file a branch
lives in and nothing else. That is the whole reason it is one function rather
than a table: a table would have to invent an order.

Returns ``None`` where every branch declined, which is the fall-through the run
had inside its old home. A branch that *raises* still raises: a production that
consumed tokens and then found the sentence unreadable keeps its own refusal,
which is the difference between "this is not my sentence" and "this is my
sentence and it is broken".

Two calls go upward and neither is imported back. ``parse_optional_action``
reads a whole statement as an offer's action, and ``parse_subject_verb`` is
this reader's own caller — "…and **you put** a cube counter on this artifact"
is the imperative with its subject spelled out (CR 608.2c), so it goes back to
the top with the cursor on the verb rather than to a second copy of the "put"
chain. Both are handed in, the inversion `delayed`, `postmodifiers` and
`lowering/where_x` already make: what differs between callers is only which
parser they already hold.
"""

import dataclasses

from . import ast
from .errors import GrammarError
from .paragraphs import _parse_name_then_reveal_top
from .phrases import (
    _accept_life_alternative,
    _accept_mana_alternatives,
    _parse_mana_payment,
)
from .stream import TokenStream
from .effects import (
    _parse_activates_each_lands_mana_ability,
    _parse_ante,
    _parse_bid_life_for_control,
    _parse_discard,
    _parse_discard_revealed_unless_pay_life,
    _parse_draw,
    _parse_exile_entire_library,
    _parse_extra_turn,
    _parse_mill,
    _parse_play_with_hand_revealed,
    _parse_player_adds_mana,
    _parse_player_exiles_graveyard,
    _parse_player_exiles_target_spell,
    _parse_player_puts_hand_cards_on_library,
    _parse_player_puts_whole_hand_on_library,
    _parse_put_hand_cards_on_library,
    _parse_put_exiled_card_on_stack_as_copy,
    _parse_put_exiled_this_way,
    _parse_repeated_graveyard_pick,
    _parse_return,
    _parse_reveal_hand,
    _parse_sacrifice,
    _parse_simultaneous_untap_and_tap,
    _parse_skip_step,
    _parse_tap_untap,
    parse_choose_card_type,
    parse_exile_random_card_from_hand,
    parse_graveyard_top_opponent_chooses,
    parse_player_chooses_permanent,
    parse_player_looks_at_own_library_top,
    parse_player_separates_your_library_top,
)


def parse_player_subject_verb(
    stream: TokenStream,
    token,
    source_spec: "ast.Recipient",
    *,
    parse_optional_action,
    parse_subject_verb,
) -> "ast.Statement | None":
    """The player-subject verb branches, in their printed order, or None.

    *token* is the verb the caller peeked at and did **not** consume, so every
    branch dispatches on ``token.text`` exactly as it did in place; each one
    that claims the sentence advances the stream itself.
    """
    if token.text in ("adds", "add") and isinstance(source_spec, ast.PlayerRef):
        return _parse_player_adds_mana(stream, source_spec)
    # "**Target player activates a mana ability of each land they
    # control.**" (Drain Power.) A seat made to tap out into its own pool,
    # which is somebody else's board and somebody else's mana — so the
    # subject is the whole of what the clause is about, and the production
    # declines without consuming for `_parse_play_with_hand_revealed`'s
    # reason below: "activate" opens sentences this has no business
    # claiming.
    if (
        token.text in ("activates", "activate")
        and isinstance(source_spec, ast.PlayerRef)
    ):
        tapped_out = _parse_activates_each_lands_mana_ability(
            stream, source_spec
        )
        if tapped_out is not None:
            return tapped_out
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
    # Lash.) "**That player** exiles a card at random from their hand."
    # (Elkin Lair.) The player-subject sentences in the exile family; each
    # declines without consuming, so the other keeps its own reading and
    # every printed exile with no subject keeps the bare-imperative one
    # below. Neither can claim the other: they differ from the verb's object
    # on, which is the first word each of them reads.
    if token.text in ("exiles", "exile") and isinstance(source_spec, ast.PlayerRef):
        emptied = _parse_exile_entire_library(stream, source_spec)
        if emptied is not None:
            return emptied
        at_random = parse_exile_random_card_from_hand(stream, source_spec)
        if at_random is not None:
            return at_random
        # "**Each player** exiles all creature cards from their graveyard."
        # (Living Death.) The third of the family, and last of the three
        # because it is the one whose object is an ordinary noun phrase:
        # the two above it name a whole library and a card at random, and
        # each refuses on the words right after the verb. Declines without
        # consuming, so a printed exile this cannot read still fails as an
        # unrecognized verb rather than inside a production that never had
        # its sentence.
        from_graveyard = _parse_player_exiles_graveyard(stream, source_spec)
        if from_graveyard is not None:
            return from_graveyard
        # "**Target spell's controller** exiles it with X delay counters on
        # it." (Ertai's Meddling.) The fourth of the family and the only one
        # whose object was printed *in front of* the verb — the seat is read
        # off the spell the announcement chose, so "it" names that spell.
        # Gated on that referent inside the production, so every other
        # player-subject exile keeps its own reading; last, because it is
        # the narrowest.
        targeted_spell = _parse_player_exiles_target_spell(stream, source_spec)
        if targeted_spell is not None:
            return targeted_spell
    # "…and **you tap** that creature." (Mind Whip.) Tapping has no actor in
    # the rules — CR 701.26a turns a permanent sideways and says nothing
    # about who does it — so the printed subject is read and then dropped
    # rather than carried: the same instruction results whoever the sentence
    # names. Read here because only the bare imperative had a production, so
    # a printed subject came back as an unrecognized verb.
    # "…that player **simultaneously** untaps each tapped artifact,
    # creature, and land they control and taps each untapped one." (Sands
    # of Time.) The adverb is the verb here — the sentence's two sweeps are
    # one effect, and read as two the untap would run first and the tap
    # would then find everything untapped. Above the tap table below, which
    # its second word would otherwise be claimed by; declines without
    # consuming, so a plain "that player untaps …" keeps its reading.
    if token.text == "simultaneously" and isinstance(source_spec, ast.PlayerRef):
        both = _parse_simultaneous_untap_and_tap(stream, source_spec)
        if both is not None:
            return both
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
        # "At the beginning of each player's upkeep, **that player chooses
        # a color**." (Hall of Gemstone.) The imperative production reads
        # the same three words with no subject in front of them, where CR
        # 601.2b's default makes the ability's controller the chooser; here
        # the sentence names somebody else, and for this card that is a
        # different seat every turn.
        #
        # First among these arms, and matched in full: every one below
        # declines without consuming, and this is the only reading of the
        # verb whose object is a colour.
        mark_colour = stream.mark()
        stream.advance()
        if stream.accept_phrase("a", "color") and (
            stream.exhausted or stream.at_punct(".", ",")
        ):
            return ast.ChooseColor(chooser=source_spec)
        stream.reset(mark_colour)
        # "At the beginning of each player's upkeep, **that player chooses
        # artifact, creature, land, or non-Aura enchantment**." (Teferi's
        # Realm.) The colour branch's sibling one characteristic over, and
        # read beside it rather than inside it for the reason that one is
        # read first: each is the only reading of the verb whose object is
        # what it names. Non-consuming on refusal.
        types = parse_choose_card_type(stream, source_spec)
        if types is not None:
            return types
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
        # "Target opponent **chooses one of the top two cards of your
        # graveyard**. …" (Phyrexian Grimoire.) Same reason as every arm
        # above: it declines without consuming, where the paragraph below
        # expects "a card name" from its second word and would fail the
        # line on "one".
        top_of_pile = parse_graveyard_top_opponent_chooses(stream, source_spec)
        if top_of_pile is not None:
            return top_of_pile
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
        # "**Target player puts a card from their hand on top of their
        # library.**" (Volrath's Dungeon.) A *counted* move with no choosing
        # clause in front of it — Stunted Growth's "chooses three cards … and
        # puts them" one arm up, and Jester's Mask's whole hand the arm above,
        # are the two spellings this sat between.
        #
        # It is the production ``_parse_put_hand_cards_on_library`` already is:
        # handed a player, it reads the third-person possessives, which is how
        # Tainted Specter's toll ("…unless they put a card from their hand on
        # top of their library") has always been read. So the gap was never the
        # sentence, it was that no arm here dispatched to it — and the lowering
        # has honoured ``target_player`` since it was written. Declines without
        # consuming, like every arm around it.
        counted = _parse_put_hand_cards_on_library(stream, source_spec)
        if counted is not None:
            return counted
        # "…then **puts all cards they exiled this way** onto the
        # battlefield." (Living Death.) A back-reference to a step of the
        # same sentence, so it is read here rather than by the noun parser:
        # "exiled this way" names a record and not a characteristic, and a
        # filter carrying the words would lower through every line that
        # printed them. Declines without consuming.
        exiled_pile = _parse_put_exiled_this_way(stream, source_spec)
        if exiled_pile is not None:
            return exiled_pile
        # "…**the player puts it onto the stack as a copy of the original
        # spell**." (Ertai's Meddling.) The card an earlier step of the same
        # effect exiled, going back where it came from as CR 707.10's copy.
        # Declines without consuming, like every arm around it.
        as_copy = _parse_put_exiled_card_on_stack_as_copy(stream, source_spec)
        if as_copy is not None:
            return as_copy
        # "…and **you put** a cube counter on this artifact" (Delif's Cube).
        # The imperative with its subject spelled out, which CR 608.2c makes
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
    # "**Target player** takes an extra turn after this one." (Time Warp.)
    # The bare imperative ("Take an extra turn after this one", Time Walk)
    # is routed from `imperatives.py`; this is the same production with its
    # subject printed, which CR 608.2c makes the same sentence. Dispatched
    # on the verb like every other player action here, and handed the
    # subject rather than defaulting it — the whole of what Time Warp adds
    # to Time Walk is which seat gets the turn.
    if token.text in ("takes", "take") and isinstance(source_spec, ast.PlayerRef):
        return _parse_extra_turn(stream, source_spec)
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
        # "**Each player may bid** life for control of target creature."
        # (Illicit Auction.) The whole auction — the offer and the four
        # sentences of procedure behind it — is one production, so it is
        # reached here rather than through `parse_optional_action`: that
        # one reads a single sentence, and would leave four unaccounted
        # for. Non-consuming on refusal, like every other probe in this
        # chain.
        if stream.at_word("bid"):
            auction = _parse_bid_life_for_control(stream, source_spec)
            if auction is not None:
                return auction
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
    return None

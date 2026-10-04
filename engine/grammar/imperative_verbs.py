"""The bare imperative whose **verb** is its first word.

Split out of ``imperatives`` at Mercadian Masques' Phase 0, along the boundary
that module's own docstring draws in its second sentence: an opening is one of
two shapes, and ``imperatives`` said so while holding both. What stays there is
every **paragraph** opener — the printed sentences that begin with a noun
phrase no subject reader may eat, each tried before any verb because a subject
parser would consume half of one and strand the rest. What moved here is the
half after ``# A bare imperative verb has an implied "you"/the source as
subject``: a flat dispatch on the first word, and the half that **grows with
the pool**, since a new printed verb is a new row and a new paragraph is rare.

That is ``by_node.py``'s rule from Fallen Empires — "the table is a registry
either way" — with both halves dispatch and the growing one moving out, the
same cut :mod:`trigger_matched` took one family over in the same Phase 0.

The upward call is carried across unchanged: ``parse_optional_action`` is
handed in rather than imported, because reading a whole statement is
``statements``' job. ``parse_imperative`` calls this at its tail, so the
ordering the paragraph openers depend on is unchanged — every one of them is
still tried before the first verb.
"""

import dataclasses
from . import ast
from .ownership import _parse_ownership_exchange_unless_paid
from .naming import (
    _parse_name_and_strip,
    _parse_name_then_consult,
    _parse_name_then_random_reveal,
)
from .paragraphs import (
    _parse_exile_graveyard_until_leaves,
    _parse_exile_until_leaves_or_untaps,
    _parse_transmute_by_sacrifice,
)
from .back_references import _parse_that_object
from .conditions import _parse_condition
from .errors import GrammarError
from .nouns import parse_object_filter
from .references import parse_recipient
from .stream import TokenStream
from .durations import _parse_duration
from .phrases import (
    _parse_pay_life,
)
from .references import _parse_further_subjects
from .readers import _parse_entering_counters
from .effects import (
    parse_bin_revealed_card,
    _parse_force_chosen_creature_to_attack,
    _parse_add_mana,
    _parse_ante,
    _parse_attach,
    _parse_note_mana_spent,
    _parse_change_base_pt,
    _parse_change_target,
    _parse_change_text,
    _parse_choose_cards_in_hand,
    _parse_choose_color,
    _parse_choose_creature_type,
    _parse_choose_opponent,
    parse_choose_card_name,
    parse_choose_card_type,
    _parse_choose_number,
    _parse_choose_player_who_cast,
    _parse_copy_that_spell,
    _parse_copy_this_spell,
    _parse_counter,
    _parse_create_token,
    _parse_create_token_for_recipient,
    _parse_destroy,
    _parse_discard,
    _parse_double,
    _parse_draw,
    _parse_enchant,
    _parse_end_the_turn,
    _parse_exchange_control,
    _parse_exile_graveyard,
    _parse_exile_graveyard_position,
    _parse_exile_entire_library,
    _parse_exile_top_of_library,
    _parse_extra_turn,
    _parse_flip_coin,
    _parse_gain_control,
    _parse_exchange_life_totals,
    _parse_life_total_becomes,
    _parse_look_at_hand,
    _parse_exile_bound_card,
    _parse_bin_unplayed_exiled_cards,
    _parse_put_exiled_card_into_hand,
    _parse_put_exiled_pile_top_into_hand,
    _parse_exile_cost_sacrifices,
    _parse_mill,
    _parse_prevent,
    _parse_put_iterated_card_on_library,
    parse_put_library_top_into_hand,
    parse_put_exiled_pile_on_library,
    _parse_distribute_counters,
    _parse_put_counter,
    _parse_put_exiled_with_source,
    parse_put_milled_card_onto_battlefield,
    _parse_put_hand_cards_on_library,
    _parse_put_source_into_zone,
    _parse_move_counter,
    _parse_remove_counter,
    _parse_remove_from_combat,
    _parse_return,
    _parse_reveal_hand,
    _parse_reveal_top,
    parse_reveal_any_number_from_hand,
    _parse_sacrifice,
    _parse_scry,
    _parse_search_library,
    _parse_switch_pt,
    _parse_tap_untap,
)


def parse_imperative_verb(
    stream: TokenStream, *, parse_optional_action
) -> "ast.Statement | None":
    """The sentence at the cursor when its first word is a verb, or None.

    None means "not one of these" and the stream is where it was — the same
    contract :func:`~engine.grammar.imperatives.parse_imperative` has, and for
    the same reason: the subject reader above gets its turn on the same words.
    """
    # "Flip a coin." (CR 705.1) — a bare imperative like the ones below, and
    # the only production that reads the word, so any other "flip …" sentence
    # (Chaos Orb's) falls through untouched.
    # "**You** flip a coin" is the same sentence with its subject printed
    # (Amulet of Quoz), so the gate admits the pronoun too and the production
    # refuses quietly for every other "you …" line.
    if stream.at_word("flip", "you"):
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
        # One printed verb, two effect families: "exchange **control** of …"
        # acts on permanents (`board`) and "exchange **life totals** with …"
        # acts on a player's life (`game`). The word after the verb is the whole
        # difference, so it is the branch — a shared production would have to
        # own both, and a family a production belongs to is the family of what
        # it acts on.
        if stream.peek_word(1) == "life":
            return _parse_exchange_life_totals(stream)
        return _parse_exchange_control(stream)
    # "Distribute X +1/+1 counters among any number of target creatures."
    # (Spoils of War.) Its own bare imperative, beside "put" rather than inside
    # it: the verb differs and so does every noun after it — "among" names the
    # set the shares are split across where "on" names the one permanent.
    if stream.at_word("distribute"):
        distributed = _parse_distribute_counters(stream)
        if distributed is not None:
            return distributed
    if stream.at_word("put"):
        # "Put all cards exiled with this artifact into their owner's hand."
        # (Knowledge Vault.) Tried first and non-consuming on refusal: the
        # counter production reads the noun after "put" as a counter kind and
        # would fail this sentence with "expected 'counter or counters'",
        # which is a refusal site that names the wrong problem.
        linked = _parse_put_exiled_with_source(stream)
        if linked is not None:
            return linked
        # "Put the card on top of your library." (Sylvan Library.) The same
        # treatment and for the same reason: the counter production reads
        # "the" as a counter kind and refuses with a site naming counters.
        iterated = _parse_put_iterated_card_on_library(stream)
        if iterated is not None:
            return iterated
        # "Put two cards from your hand on top of your library in any order."
        # (Brainstorm.) Same treatment and the same reason as the two above:
        # the counter production reads "two" as a count and then refuses with a
        # site naming counters.
        from_hand = _parse_put_hand_cards_on_library(stream)
        if from_hand is not None:
            return from_hand
        # "Put that card into your hand." (Necropotence, inside its delay.)
        # Same treatment and same reason as the three above: the counter
        # production reads "that" as a counter kind and refuses with a site
        # naming counters.
        exiled_back = _parse_put_exiled_card_into_hand(stream)
        if exiled_back is not None:
            return exiled_back
        # "Put any of those cards you didn't play into your graveyard." (Three
        # Wishes, inside its delay.) Same treatment and same reason as the ones
        # above: the counter production reads "any" as a count and refuses with
        # a site naming counters.
        unplayed = _parse_bin_unplayed_exiled_cards(stream)
        if unplayed is not None:
            return unplayed
        # "Put the top card of the exiled pile into its owner's hand."
        # (Mangara's Tome.) CR 610.3's linked pile rather than a back-reference
        # inside one resolution, and read here for the same reason as the three
        # above: the counter production takes "the top card" as a count and
        # refuses with a site naming counters.
        pile_top = _parse_put_exiled_pile_top_into_hand(stream)
        if pile_top is not None:
            return pile_top
        # "Put it into your graveyard." (All Hallow's Eve.) The ability moving
        # its own source; same treatment and same reason as the two above.
        moved = _parse_put_source_into_zone(stream)
        if moved is not None:
            return moved
        # "**If you do,** put it into that player's graveyard." (Wand of
        # Denial.) The same three opening words as the source move above and a
        # different referent — the card the look turned up — so it is read
        # after it: "put it into **your** graveyard" is the source's sentence
        # and keeps its reading, and only a possessive naming somebody else
        # reaches here.
        binned = parse_bin_revealed_card(stream)
        if binned is not None:
            return binned
        # "Put one of them onto the battlefield under your control." (Helm of
        # Obedience.) The last of the back-references and the same treatment:
        # the counter production reads "one" as a count and then refuses with a
        # site naming counters.
        milled = parse_put_milled_card_onto_battlefield(stream)
        if milled is not None:
            return milled
        # "Put that many cards from the top of your library into your hand."
        # (Scroll Rack.) The last of them, and the same treatment for the same
        # reason as every one above: the counter production reads "that" as a
        # counter kind and refuses with a site naming counters.
        off_the_top = parse_put_library_top_into_hand(stream)
        if off_the_top is not None:
            return off_the_top
        return _parse_put_counter(stream)
    if stream.at_word("double"):
        return _parse_double(stream)
    if stream.at_word("switch"):
        return _parse_switch_pt(stream)
    if stream.at_word("move"):
        # "Move a +1/+1 counter from this enchantment onto target creature."
        # (Afiya Grove.) Non-consuming on refusal, so the counter-less "move"
        # sentences keep failing on their own missing production rather than on
        # a counter kind they never mentioned — `_parse_remove_counter`'s rule
        # one verb over.
        moved = _parse_move_counter(stream)
        if moved is not None:
            return moved
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
        # "Change the target of target spell …" (Reflecting Mirror, CR 115.7a).
        # Third of the three "Change the …" templates, and like the first it
        # refuses without consuming — so the text rewrite below keeps every
        # refusal it has today.
        retarget = _parse_change_target(stream)
        if retarget is not None:
            return retarget
        return _parse_change_text(stream)
    if stream.at_word("gain"):
        control = _parse_gain_control(stream)
        if control is not None:
            return control
    if stream.at_word("create"):
        return _parse_create_token(stream)
    if stream.at_word("return"):
        # "Return each card exiled with this land to the battlefield under its
        # owner's control." (Safe Haven.) The linked-pile production again,
        # printed with the other verb — tried first and non-consuming on
        # refusal, exactly as the "put" spelling is above, because the general
        # return production reads "each card" as a noun phrase and then fails
        # naming a missing destination zone rather than the pile.
        linked = _parse_put_exiled_with_source(stream)
        if linked is not None:
            return linked
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
        # "**Exile all cards from your library.**" (Paradigm Shift.) The
        # imperative spelling of the sentence Thought Lash prints in the third
        # person, so it is the same production read from the other entry point
        # rather than a second one — and read here for the reason the
        # top-of-library form above is: the recipient parser below takes
        # "all cards" as a battlefield sweep and refuses it on the zone, which
        # is a misleading refusal for a sentence that never named a permanent.
        whole_library = _parse_exile_entire_library(stream, ast.PlayerRef("you"))
        if whole_library is not None:
            return whole_library
        # "Exile the bottom card of target player's graveyard" (Phyrexian
        # Furnace) names cards by position in an *ordered* zone (CR 404.1,
        # CR 404.2), so
        # the recipient parser below refuses "the bottom" the same way it
        # refuses "the top" — tried here for that reason and beside the library
        # form it mirrors.
        from_graveyard = _parse_exile_graveyard_position(stream)
        if from_graveyard is not None:
            return from_graveyard
        # "Exile target player's graveyard" is a whole zone, which the
        # recipient parser below would read as the player alone and then
        # choke on the possessive.
        whole_graveyard = _parse_exile_graveyard(stream)
        if whole_graveyard is not None:
            return whole_graveyard
        # "Exile this artifact **and those creature cards**." (Sword of the
        # Ages.) The ordinary exile below reads the first three words and
        # strands the rest, which is a different sentence: what this names is
        # already in a graveyard, put there by the ability's own cost.
        cost_sacrifices = _parse_exile_cost_sacrifices(stream)
        if cost_sacrifices is not None:
            return cost_sacrifices
        # "Exile **that card** from your graveyard." (Necropotence.) The object
        # the firing event named, which the recipient parser below cannot read —
        # it reads permanents and chosen cards, and this is neither.
        bound_card = _parse_exile_bound_card(stream)
        if bound_card is not None:
            return bound_card
        stream.advance()
        # "…**exile that creature**." (Coffin Queen, inside the delay its
        # activated ability creates.) The object the delayed ability was armed
        # about (CR 603.7c), read locally exactly as the destroy production
        # reads the same two words and for the same stated reason: the phrase
        # turns up all over the pool, and teaching the shared noun parser to
        # claim it would lower every one of those lines through a filter naming
        # a card type nobody bound.
        #
        # Safe here because the quantifier is refused by default — no lowering
        # accepts "that" unless it says so — so a sentence that reaches one
        # without a binder fails **by name** rather than failing to parse.
        subject = _parse_that_object(stream) or parse_recipient(stream)
        if subject is None:
            # "Create three 2/2 white Knight creature tokens. **Exile them** at
            # the beginning of the next cleanup step." (Waylay.) The plural of
            # "that token": the objects an earlier step of this same effect
            # created, which no read of a permanent can identify — a token is a
            # new object with a fresh id (CR 400.7), so the maker records the
            # ids and this reads them back.
            #
            # Read **last**, only where every reader above has already refused,
            # and that ordering is the whole safety of it. "Exile them" is
            # printed by six other cards in the pool ("Search your library for
            # three cards, **exile them**, then shuffle") where the word names
            # a pile a search produced, and each of those sentences is claimed
            # whole by its own production long before this line is reached. A
            # reader placed in front of them would take the word and hand the
            # search's cards to a token exile.
            #
            # ``"those"`` rather than ``"that"``, because the quantifier is
            # what the lowering tells the two apart by: the singular addresses
            # one recorded id and the plural addresses the list.
            if stream.accept_word("them"):
                subject = ast.TargetSpec(
                    "those", ast.ObjectFilter(is_created_token=True)
                )
        if subject is None:
            raise stream.error("expected something to exile")
        # "Exile this creature **and target creature** without flying that's
        # attacking you." (Giant Trap Door Spider.) One verb over two noun
        # phrases, the same union `destroy` and `return` already read — and the
        # same reason it is a shape rather than a filter: an `ObjectFilter`
        # AND's its keys, so the source and a chosen creature folded into one
        # would name neither.
        further = _parse_further_subjects(stream, subject)
        # Read before the duration: the two never co-occur on a printed card,
        # and a duration parser that ran first would answer "no duration" and
        # leave the counter phrase to die as unconsumed text.
        counters = _parse_entering_counters(stream)
        duration = _parse_duration(stream)
        # "Exile a card from your hand **face down**." (Gustha's Scepter.)
        # CR 406.3's rider, read here for the reason `ExileTopOfLibrary` reads
        # it one production over: it is the difference between a card the whole
        # table can read in exile and one nobody can, and a production that
        # consumed the words without recording them would exile it face up.
        face_down = bool(stream.accept_phrase("face", "down"))
        # "Exile up to three target cards **from a single graveyard**." (Ebony
        # Charm.) The noun parser stops in front of it — "single" is not a zone
        # owner it knows — so the tail is read here, exactly as
        # ``costs._parse_costs`` reads the same four words for Night Soil. The
        # pile half goes on the filter and the sameness half on the node; the
        # two are separate because a filter is asked of one card at a time and
        # "all out of one pile" is a fact about the whole set.
        same_zone = False
        if stream.accept_phrase("from", "a", "single", "graveyard"):
            if not isinstance(subject, ast.TargetSpec):
                raise stream.error(
                    "expected a counted noun phrase before 'from a single "
                    "graveyard'"
                )
            subject = dataclasses.replace(
                subject,
                filter=dataclasses.replace(
                    subject.filter, zone="graveyard", zone_owner=None,
                    is_card=True,
                ),
            )
            same_zone = True
        if further:
            return ast.Conjunction(
                tuple(
                    ast.Exile(each, duration, counters=counters,
                              face_down=face_down, same_zone=same_zone)
                    for each in (subject, *further)
                )
            )
        return ast.Exile(
            subject, duration, counters=counters, face_down=face_down,
            same_zone=same_zone,
        )
    if stream.at_word("add"):
        return _parse_add_mana(stream)
    # "Note the type of mana spent to pay this activation cost." (Jeweled
    # Amulet.) A bare imperative like the draw and discard above it — the
    # ability's own controller notes it, and the record hangs off the ability's
    # own source. Non-consuming on refusal, so a sentence opening with "note"
    # that this cannot read falls through rather than losing its line.
    if stream.at_word("note"):
        noted = _parse_note_mana_spent(stream)
        if noted is not None:
            return noted
    if stream.at_word("look"):
        # "Look at **the exiled cards** and put them on top of your library in
        # any order." (Scroll Rack.) CR 610.3's linked pile rather than a
        # player's zone, and non-consuming on refusal so every ordinary look
        # keeps its own reading and its own refusal site.
        pile = parse_put_exiled_pile_on_library(stream)
        if pile is not None:
            return pile
        return _parse_look_at_hand(stream)
    if stream.at_word("search"):
        # "Search your library for a Plains card. If target opponent controls
        # more lands than you, you may search your library for an additional
        # Plains card. Reveal those cards, put them into your hand, then
        # shuffle." (Tithe.) Three printed sentences and one effect
        # (CR 701.23h), so it is read whole and before the ordinary search —
        # which refuses this line at "expected 'put'", the first sentence
        # having no destination clause of its own. Non-consuming on refusal.
        deferred = _parse_conditional_additional_search(stream)
        if deferred is not None:
            return deferred
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
        # "**Reveal your hand** and put all land cards from it onto the
        # battlefield." (Manabond.) The bare imperative spelling of a sentence
        # that already had a reader: `_parse_reveal_hand` has read
        # "<player> reveals their hand" since Amnesia, and with no printed
        # subject the line reached `_parse_reveal_top` and failed on the
        # literal "the" — four words short of a production that exists, which
        # is the same one-line gap that function's own comments record twice.
        #
        # The subject is "you", which is what a bare imperative means
        # (CR 608.2's effect is performed by the ability's controller), and the
        # reveal production declines *without consuming* when the reveal names
        # something other than a hand — so "reveal the top card of your
        # library" keeps its own reading and its own error.
        # "**Reveal any number of blue cards in your hand.**" (Brine Seer and
        # the eleven cards printed with it.) Read first, and non-consuming on
        # refusal: the hand reveal below opens on the same verb and reads the
        # possessive straight after it, so "any" would send it back with the
        # line half-claimed — and the top-of-library reveal under that would
        # then fail on "any" four words from a production that exists.
        chosen = parse_reveal_any_number_from_hand(stream)
        if chosen is not None:
            return chosen
        hand = _parse_reveal_hand(stream, ast.PlayerRef("you"))
        if hand is not None:
            return hand
        return _parse_reveal_top(stream)
    if stream.at_word("take"):
        return _parse_extra_turn(stream)
    if stream.at_word("end"):
        return _parse_end_the_turn(stream)
    if stream.at_word("copy"):
        # "Copy **this** spell …" first and non-consuming on refusal, so
        # "Copy that spell …" keeps its own production and its own refusal.
        this_spell = _parse_copy_this_spell(stream)
        if this_spell is not None:
            return this_spell
        return _parse_copy_that_spell(stream)
    # A token maker with a **recipient** printed in front of it — "Each
    # opponent creates …" (Pursued Whale), "Target opponent creates …"
    # (Phelddagrif). One reader, beside the token production itself, and
    # non-consuming on refusal.
    for_recipient = _parse_create_token_for_recipient(stream)
    if for_recipient is not None:
        return for_recipient
    if stream.at_word("choose"):
        # Nettling Imp / Norritt's three sentences, which are one effect. Tried
        # first because the sentence *after* the one this opens has nothing to
        # read on its own — "that creature" names what this one chose — so a
        # production that took only the first sentence would strand the other
        # two as unconsumed text.
        mark_forced = stream.mark()
        forced = _parse_force_chosen_creature_to_attack(stream)
        if forced is not None:
            return forced
        stream.reset(mark_forced)
        # "Choose a number between 0 and 7." (Shapeshifter.) Tried first and
        # non-consuming on refusal, so every other "choose" sentence still
        # reaches the naming production behind it.
        chosen_number = _parse_choose_number(stream)
        if chosen_number is not None:
            return chosen_number
        # "Choose a color." (Chromatic Armor.) Beside the number above and
        # non-consuming on refusal for the same reason — the word opens several
        # unrelated sentences, and "choose a color **and an opponent**" is one
        # of them.
        chosen_color = _parse_choose_color(stream)
        if chosen_color is not None:
            return chosen_color
        # "Choose a creature type." (Outbreak.) The colour's sibling one
        # characteristic over, for its reason and non-consuming the same way.
        chosen_creature_type = _parse_choose_creature_type(stream)
        if chosen_creature_type is not None:
            return chosen_creature_type
        # "Choose artifact, creature, or land." (Turnabout.) The colour's
        # sibling one characteristic over, and the *bare imperative* spelling of
        # the sentence `player_verbs` already reads with a subject in front of
        # it ("that player chooses artifact, creature, land, or non-Aura
        # enchantment", Teferi's Realm). One production, two positions: with no
        # subject the chooser is the effect's own controller, which is what
        # `chooser_payload` answers for a `None` chooser.
        #
        # Non-consuming on refusal and it declines anything that is not a list
        # of two or more card types, so every other "choose" sentence keeps the
        # reading it has — the naming productions below included.
        chosen_type = parse_choose_card_type(stream)
        if chosen_type is not None:
            return chosen_type
        # "Choose one of your opponents." (Goblin Festival.) A *seat* where the
        # three above name a value, and beside them for their reason: the word
        # opens several unrelated sentences and this declines without consuming,
        # so every reader below keeps the one it owns.
        chosen_opponent = _parse_choose_opponent(stream)
        if chosen_opponent is not None:
            return chosen_opponent
        # "Choose a player who cast one or more sorcery spells this turn."
        # (Backdraft.) Non-consuming on refusal for the reason every "choose"
        # production here is: the word opens several unrelated sentences, and a
        # production that ate part of one would take the whole line with it.
        chosen_player = _parse_choose_player_who_cast(stream)
        if chosen_player is not None:
            return chosen_player
        # "Choose two cards in your hand drawn this turn." (Sylvan Library.)
        # Also non-consuming on refusal — it declines anything that is not a
        # pick out of a hand, so the naming productions below keep their say.
        hand_pick = _parse_choose_cards_in_hand(stream)
        if hand_pick is not None:
            return hand_pick
        # Demonic Consultation's naming paragraph. Tried before the two below
        # it because all three open with the same four words and this one is
        # the only one whose fifth token is a full stop followed by "exile" —
        # it declines without consuming, so nothing else loses a reading.
        consulted = _parse_name_then_consult(stream)
        if consulted is not None:
            return consulted
        # Nebuchadnezzar's naming paragraph. Tried before Necromentia's, which
        # is the last resort here and raises rather than refusing — the two
        # differ from the fifth word on, and this one declines without
        # consuming so nothing else loses a reading.
        random_reveal = _parse_name_then_random_reveal(stream)
        if random_reveal is not None:
            return random_reveal
        # "Choose a card name, then target opponent mills a card. …"
        # (Foreshadow.) The bare naming *sentence*, and it is read **last of
        # the naming productions** — Demonic Consultation, Nebuchadnezzar and
        # Necromentia all open with these same four words and then read two or
        # three more printed sentences as one paragraph, so a single-sentence
        # reading tried first takes the first sentence and strands the rest.
        #
        # That is not hypothetical: probed above the colour choice it claimed
        # Nebuchadnezzar's opening and the card went from supported to
        # unsupported. The suite caught it through ``test_effect_labels``,
        # whose "every table entry is still reached" is the guard that sees a
        # kind quietly stop being produced — which is what widening a gate does
        # to whatever was keyed on the refused shape.
        chosen_name = parse_choose_card_name(stream)
        if chosen_name is not None:
            return chosen_name
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
    # "Ante the top card of your library." — a bare imperative like the draw
    # and discard above it, and the shape Rebirth prints inside its offer.
    if stream.at_word("ante"):
        ante = _parse_ante(stream)
        if ante is not None:
            return ante
    # "Pay 4 life." (Sylvan Library, inside its per-card choice.) A bare
    # imperative like the draw and discard above, and non-consuming on refusal
    # so "pay {R}{R}" and the unless-pay templates keep their readings.
    if stream.at_word("pay"):
        # "**pay any amount of mana**" (Liege of the Hollows, and Power Leak's
        # and Errant Minion's upkeep paragraphs, which read their own whole
        # text). A cost with no printed number: the payer names it, which is
        # why it is a statement rather than a `ManaCost` — nothing about the
        # sentence says how much, and the sentence behind it reads the answer.
        # Before the life reader, which would refuse "any" and take the line
        # with it.
        mark_any = stream.mark()
        if stream.accept_phrase("pay", "any", "amount", "of", "mana"):
            return ast.PayAnyAmountOfMana(ast.PlayerRef("you"))
        stream.reset(mark_any)
        paid = _parse_pay_life(stream)
        if paid is not None:
            return paid
    if stream.at_word("counter"):
        return _parse_counter(stream)
    if stream.at_word("enchant"):
        return _parse_enchant(stream)

    # "That player's life total becomes 20." (Rebirth.) The subject is a
    # possessive **of a player**, which the recipient parser below reads down
    # to the player and then chokes on the "'s". Refuses without consuming.
    life_total = _parse_life_total_becomes(stream)
    if life_total is not None:
        return life_total
    return None


def _parse_conditional_additional_search(
    stream: TokenStream,
) -> "ast.Statement | None":
    """``Search your library for <filter>. If <condition>, you may search your
    library for an additional <filter>. Reveal those cards, put them into your
    hand, then shuffle.`` (Tithe.)

    Three printed sentences, one effect. CR 701.23h says so outright: a player
    told to search a library more than once before being told to shuffle
    searches it **once**, for all those cards — which is why the destination
    clause is printed after both searches and belongs to neither of them alone.

    Read here rather than in ``effects/search.py`` for a layering reason and
    not a taste one: the middle sentence carries a *condition*, and the
    condition parser sits at ``effects``' own rank (``conditions``), so the
    search family may not call it. ``imperatives`` is the first layer above
    both, and it is already where a sentence opening with "search" is routed.

    Refuses without consuming, so an ordinary search keeps its reading and its
    own refusal — the singular production's "expected 'put'" is still what a
    line with a missing destination clause gets.

    The second phrase must be the **same** noun phrase as the first. A card
    naming different cards for its two finds is a different sentence: the one
    destination clause behind them describes both, and admitting a mismatch
    would send a find somewhere the card never said.
    """
    mark = stream.mark()
    if not stream.accept_phrase("search", "your", "library", "for"):
        stream.reset(mark)
        return None
    stream.accept_word("a", "an")
    try:
        wanted = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not wanted.is_card or not stream.accept_punct("."):
        stream.reset(mark)
        return None
    if not stream.accept_word("if"):
        stream.reset(mark)
        return None
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "you", "may", "search", "your", "library", "for", "an", "additional",
    ):
        stream.reset(mark)
        return None
    try:
        again = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if again != wanted or not stream.accept_punct("."):
        stream.reset(mark)
        return None
    # "Reveal those cards, put them into your hand, then shuffle." The clause
    # both searches share, and every word of it is required: a card sending its
    # finds anywhere else is a different effect, and reading the destination
    # loosely here is how a tutor to hand becomes a tutor to the battlefield.
    if not stream.accept_phrase("reveal", "those", "cards"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("put", "them", "into", "your", "hand"):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_phrase("then", "shuffle"):
        stream.reset(mark)
        return None

    def _one_search() -> ast.SearchLibrary:
        return ast.SearchLibrary(
            ast.PlayerRef("you"), wanted,
            ast.Zone("hand", ast.PlayerRef("you")),
            tapped=(False,), reveal=True,
        )

    # Two search steps rather than one for two finds, which is what the flow
    # can express: a counted search takes its whole answer at once, and the
    # second find here exists only if a condition holds and only if its
    # controller wants it. CR 701.23h makes the two one search in the rules;
    # what a player sees is two prompts, and every card that could be found is
    # findable in exactly one of them.
    return ast.Sequence((
        _one_search(),
        ast.Conditional(
            condition,
            ast.May(ast.PlayerRef("you"), action=_one_search()),
        ),
    ))


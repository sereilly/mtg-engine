"""The bare imperative — a sentence whose subject is not printed.

Split out of `subject_verb` at the thousand-line guard, along the boundary that
module's docstring already drew: it reads a sentence's *opening*, and an opening
is one of two shapes. Here are the ones that begin with the verb ("Destroy
target creature", "Draw two cards") plus the whole printed paragraphs that begin
with a noun phrase no subject reader may eat; `subject_verb` keeps the ones that
name a subject and dispatch on the verb behind it.

CR 101.1 is why they are one question asked in one order rather than two
parsers: an effect with no printed subject is performed by the object's
controller, so these sentences *have* a subject and simply do not spell it out.
Every production here therefore declines without consuming when it is not the
sentence it looks like, and the subject reader above gets its turn.

One call goes upward, the same inversion `subject_verb` itself makes:
`parse_optional_action` is handed in, because reading a whole statement is
`statements`' job.
"""

import dataclasses
from . import ast
from .paragraphs import (
    _parse_coin_flip_damage_loop,
    _parse_exchange_greatest_mana_value,
    _parse_exile_graveyard_until_leaves,
    _parse_exile_until_leaves_or_untaps,
    _parse_name_and_strip,
    _parse_name_then_consult,
    _parse_name_then_random_reveal,
    _parse_ante_offer_ownership_exchange,
    _parse_ownership_exchange_unless_paid,
    _parse_random_reveal_ownership_exchange,
    _parse_transmute_by_sacrifice,
)
from .references import parse_recipient
from .stream import TokenStream
from .upkeep import (_parse_pay_mana_to_prevent_upkeep_damage,
                     _parse_upkeep_damage_unless_cost)
from .phrases import _parse_duration, _parse_pay_life
from .vocabulary import NUMBER_WORDS
from .effects import (
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
    _parse_choose_number,
    _parse_choose_player_who_cast,
    _parse_copy_that_spell,
    _parse_copy_this_spell,
    _parse_counter,
    _parse_create_token,
    _parse_damage_redirect,
    _parse_destroy,
    _parse_discard,
    _parse_damage_cant_be_prevented,
    _parse_double,
    _parse_draw,
    _parse_enchant,
    _parse_end_the_turn,
    _parse_exchange_control,
    _parse_exile_graveyard,
    _parse_further_subjects,
    _parse_coin_flip_stakes_loop,
    _parse_exile_top_of_library,
    _parse_extra_turn,
    _parse_flip_coin,
    _parse_gain_control,
    _parse_game_is_a_draw,
    _parse_exchange_life_totals,
    _parse_life_total_becomes,
    _parse_look_at_hand,
    _parse_exile_bound_card,
    _parse_put_exiled_card_into_hand,
    _parse_exile_cost_sacrifices,
    _parse_mill,
    _parse_modal_head,
    _parse_prevent,
    _parse_put_iterated_card_on_library,
    _parse_distribute_counters,
    _parse_put_counter,
    _parse_put_exiled_with_source,
    _parse_put_hand_cards_on_library,
    _parse_put_source_into_zone,
    _parse_remove_counter,
    _parse_remove_from_combat,
    _parse_return,
    _parse_reveal_top,
    _parse_sacrifice,
    _parse_scry,
    _parse_search_library,
    _parse_source_of_choice_effect,
    _parse_switch_pt,
    _parse_tap_untap,
)


def _parse_entering_counters(stream: TokenStream) -> tuple[tuple[str, int], ...]:
    """``with two scream counters on it`` — counters an object carries into a zone.

    "Exile All Hallow's Eve **with two scream counters on it**." The counters
    are put on as part of the move (CR 121.2), so they are a property of the
    exiling rather than a second sentence, and reading them here is what stops
    the phrase being shed as unconsumed text — the whole card is those counters
    coming back off one per upkeep.

    The counter word and the number are both payload. Nothing about "scream"
    reaches this production: any word followed by "counter"/"counters" is a
    counter of that name (CR 122.1), which is the same open vocabulary
    ``engine/named_counters.py`` stores.

    Returns an empty tuple with the cursor untouched when the phrase is not
    there, so an exile that prints no counters is unaffected and a "with" this
    production cannot finish falls back to whatever else the line says.
    """
    mark = stream.mark()
    if not stream.accept_word("with"):
        return ()
    if stream.accept_word("a", "an"):
        count = 1
    else:
        word = stream.peek_word()
        count = NUMBER_WORDS.get(word) if word is not None else None
        if count is None:
            stream.reset(mark)
            return ()
        stream.advance()
    name = stream.peek_word()
    if name is None or name in ("counter", "counters"):
        stream.reset(mark)
        return ()
    stream.advance()
    if not (stream.accept_word("counters") or stream.accept_word("counter")):
        stream.reset(mark)
        return ()
    # "on it" is required, not optional: the phrase names *which* object the
    # counters go on, and an exile that dropped it would be reading a sentence
    # nobody printed.
    if not stream.accept_phrase("on", "it"):
        stream.reset(mark)
        return ()
    return ((name, count),)






def parse_imperative(
    stream: TokenStream, *, parse_optional_action
) -> "ast.Statement | None":
    """The sentence at the cursor when it prints no subject, or None.

    None means "not one of these" and the stream is where it was, which is what
    lets the subject reader above try its own shapes on the same words.
    """
    # "The next time a <colour> source of your choice would deal damage to you
    # this turn, prevent that damage." opens with a noun phrase rather than a
    # verb, so it is tried before the subject-verb shapes below.
    # "You and target player exchange control of …" (Juxtapose) — a whole
    # paragraph, and it opens with a noun phrase the subject parser would read
    # as a player and then choke on the conjunction. Refuses without consuming.
    juxtaposition = _parse_exchange_greatest_mana_value(stream)
    if juxtaposition is not None:
        return juxtaposition
    # Mana Clash's whole three-sentence paragraph, which opens with the same
    # "You and target opponent …" shape and would meet the same subject parser.
    # Refuses without consuming.
    flip_loop = _parse_coin_flip_damage_loop(stream)
    if flip_loop is not None:
        return flip_loop
    # "<source> deals N damage to you unless you <cost>. If it deals damage to
    # you this way, tap it." (Mishra's War Machine, Minion of Leshrac.) Two
    # sentences and one effect, so it is tried before the ordinary damage
    # production, which would read the first and strand the rider. Refuses
    # without consuming.
    upkeep_toll = _parse_upkeep_damage_unless_cost(stream)
    if upkeep_toll is not None:
        return upkeep_toll
    # "That player may pay any amount of mana. <source> deals N damage to that
    # player. Prevent X of that damage, where X is the amount of mana that
    # player paid this way." (Power Leak, Errant Minion.) Three sentences and
    # one effect, so it is tried before the offer below reads the first alone
    # and strands the other two. Refuses without consuming.
    paid_off = _parse_pay_mana_to_prevent_upkeep_damage(stream)
    if paid_off is not None:
        return paid_off
    # Tempest Efreet's whole ability, which opens "Target opponent may pay …"
    # — a subject the noun parser reads and then a "may" no production of its
    # own would finish. Refuses without consuming.
    efreet = _parse_random_reveal_ownership_exchange(stream)
    if efreet is not None:
        return efreet
    # Timmerian Fiends' whole ability, beside the Efreet's for the same reason:
    # it opens on a noun phrase ("The owner of target artifact") that the noun
    # parser reads and then a "may" no production of its own would finish.
    # Refuses without consuming.
    fiends = _parse_ante_offer_ownership_exchange(stream)
    if fiends is not None:
        return fiends
    colour_shield = _parse_source_of_choice_effect(stream)
    if colour_shield is not None:
        return colour_shield
    # "All damage that would be dealt to you this turn by target attacking
    # creature is dealt to this creature instead." (Shimian Night Stalker.) A
    # noun phrase in front of the verb, like the one above, and refusing without
    # consuming so every other sentence opening "All …" is untouched.
    redirect = _parse_damage_redirect(stream)
    if redirect is not None:
        return redirect
    # "Damage that would be dealt to that creature this turn can't be prevented
    # or dealt instead to another permanent or player." (Whippoorwill.) Another
    # noun phrase in front of the verb, and beside the redirect above for the
    # same reason: the sentence is *about* a damage event rather than dealing
    # one, so the subject-verb reader below would take "Damage" for a noun
    # phrase and fail on the modal.
    damage_lock = _parse_damage_cant_be_prevented(stream)
    if damage_lock is not None:
        return damage_lock
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
    # Ungated, unlike the productions around it: the head is printed bare
    # ("Choose one —") **and** with its chooser in front of it ("An opponent
    # chooses one —", CR 700.2e), so there is no one word to gate on. It refuses
    # quietly and without consuming, so every other sentence keeps the backlog
    # reason it had — which is the whole licence for asking it of every line.
    modal = _parse_modal_head(stream)
    if modal is not None:
        return modal
    # Game of Chaos's whole four-sentence paragraph, which *opens* with "Flip a
    # coin." and would otherwise be read as that sentence alone, stranding the
    # three behind it. Tried first for that reason and refuses without
    # consuming, so the bare imperative below keeps every other card.
    stakes = _parse_coin_flip_stakes_loop(stream)
    if stakes is not None:
        return stakes
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
        # "Put it into your graveyard." (All Hallow's Eve.) The ability moving
        # its own source; same treatment and same reason as the two above.
        moved = _parse_put_source_into_zone(stream)
        if moved is not None:
            return moved
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
        subject = parse_recipient(stream)
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
        if further:
            return ast.Conjunction(
                tuple(
                    ast.Exile(each, duration, counters=counters)
                    for each in (subject, *further)
                )
            )
        return ast.Exile(subject, duration, counters=counters)
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
        # "Copy **this** spell …" first and non-consuming on refusal, so
        # "Copy that spell …" keeps its own production and its own refusal.
        this_spell = _parse_copy_this_spell(stream)
        if this_spell is not None:
            return this_spell
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

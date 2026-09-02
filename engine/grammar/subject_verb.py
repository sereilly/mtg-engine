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
"""

import dataclasses
from . import ast
from .errors import GrammarError
from .lexer import SELF, WORD
from .paragraphs import (
    _parse_coin_flip_damage_loop,
    _parse_exchange_greatest_mana_value, _parse_exile_graveyard_until_leaves,
    _parse_exile_until_leaves_or_untaps, _parse_name_and_strip,
    _parse_name_then_consult,
    _parse_name_then_random_reveal, _parse_name_then_reveal_top,
    _parse_ante_offer_ownership_exchange,
    _parse_ownership_exchange_unless_paid, _parse_random_reveal_ownership_exchange,
    _parse_transmute_by_sacrifice,
)
from .conjuncts import _with_damage_conjunct, _with_untap_conjunct
from .references import parse_recipient
from .stream import TokenStream
from .upkeep import (_parse_pay_mana_to_prevent_upkeep_damage,
                     _parse_upkeep_damage_unless_cost)
from .phrases import (_accept_mana_alternatives, _parse_can_attack_as_though,
                      _parse_duration, _parse_mana_payment, _parse_pay_life,
                      parse_bound_subject)
from .vocabulary import NUMBER_WORDS
from .effects import (
    _parse_force_chosen_creature_to_attack,
    _parse_add_mana, _parse_ante, _parse_assigns_no_combat_damage, _parse_attach,
    _parse_note_mana_spent,
    _parse_becomes, _parse_cant_attack_or_block, _parse_change_base_pt,
    _parse_no_longer_supertype,
    _parse_can_be_targeted_as_though,
    _parse_change_target,
    _parse_change_text, _parse_choose_cards_in_hand, _parse_choose_color,
    _parse_choose_number,
    _parse_choose_player_who_cast,
    _parse_copy_that_spell, _parse_copy_this_spell,
    _parse_counter, _parse_create_token,
    _parse_damage, _parse_damage_redirect, _parse_destroy, _parse_discard,
    _parse_discard_revealed_unless_pay_life,
    _parse_reveal_hand,
    _parse_damage, _parse_damage_cant_be_prevented, _parse_damage_redirect,
    _parse_destroy, _parse_discard,
    _parse_doesnt_untap_next_step, _parse_double, _parse_draw, _parse_enchant,
    _parse_end_the_turn, _parse_exchange_control, _parse_exile_graveyard,
    _parse_further_subjects,
    _parse_coin_flip_stakes_loop,
    _parse_exile_top_of_library, _parse_extra_turn, _parse_fight, _parse_flip_coin,
    _parse_gain_control, _parse_gains, _parse_game_is_a_draw, _parse_gets,
    _parse_exchange_life_totals,
    _parse_has, _parse_life_total_becomes, _parse_look_at_hand, _parse_loses,
    _parse_exile_bound_card,
    _parse_put_exiled_card_into_hand,
    _parse_exile_cost_sacrifices,
    _parse_mill, _parse_modal_head, _parse_player_adds_mana,
    _parse_prevent, _parse_put_iterated_card_on_library,
    _parse_distribute_counters,
    _parse_put_counter, _parse_put_exiled_with_source,
    _parse_put_hand_cards_on_library,
    _parse_player_puts_hand_cards_on_library,
    _parse_player_puts_whole_hand_on_library,
    _parse_repeated_graveyard_pick,
    _parse_put_source_into_zone, _parse_remove_counter,
    _parse_remove_from_combat, _parse_return, _parse_reveal_hand, _parse_reveal_top,
    _parse_sacrifice,
    _parse_scry, _parse_search_library, _parse_source_of_choice_effect, parse_player_chooses_permanent,
    _parse_switch_pt, _parse_tap_untap, _parse_wins,
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
    if stream.at_word("choose"):
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
        if token.text in ("mills", "mill") and isinstance(source_spec, ast.PlayerRef):
            return _parse_mill(stream, source_spec)
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
                    return ast.May(source_spec, cost=cost,
                                   cost_alternatives=_accept_mana_alternatives(stream))
                except GrammarError:
                    stream.reset(mark_pay)
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
            return _parse_doesnt_untap_next_step(
                stream, _untap_subject(source_spec)
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

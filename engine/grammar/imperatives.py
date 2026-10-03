"""The bare imperative — a sentence whose subject is not printed.

Split out of `subject_verb` at the thousand-line guard, along the boundary that
module's docstring already drew: it reads a sentence's *opening*, and an opening
is one of two shapes. Here are the ones that begin with the verb ("Destroy
target creature", "Draw two cards") plus the whole printed paragraphs that begin
with a noun phrase no subject reader may eat; `subject_verb` keeps the ones that
name a subject and dispatch on the verb behind it.

CR 608.2c is why they are one question asked in one order rather than two
parsers: an effect with no printed subject is performed by the object's
controller, so these sentences *have* a subject and simply do not spell it out.
Every production here therefore declines without consuming when it is not the
sentence it looks like, and the subject reader above gets its turn.

One call goes upward, the same inversion `subject_verb` itself makes:
`parse_optional_action` is handed in, because reading a whole statement is
`statements`' job.

**And the two shapes named above are now two modules**, as of Mercadian
Masques' Phase 0. What is left here is the paragraph openers — every printed
sentence that begins with a noun phrase, each tried before any verb because a
subject parser would eat half of one and strand the rest — and the tail call
into :mod:`imperative_verbs`, which holds the flat dispatch on a first-word
verb. The ordering is unchanged: every opener here is still tried before the
first verb there.
"""

from .ownership import (
    _parse_ante_offer_ownership_exchange,
    _parse_random_reveal_ownership_exchange,
)
from .paragraphs import (
    _parse_coin_flip_damage_loop,
    _parse_exchange_greatest_mana_value,
    _parse_pay_or_sacrifice_greatest_mana_value,
    _parse_random_graveyard_card_fate,
    _parse_rebalance_lands,
)
from .stream import TokenStream
from .upkeep import parse_upkeep_paragraph
from .effects import (
    parse_simultaneous_phasing,
    parse_land_type_swap,
    _parse_damage_becomes_counter_removal,
    _parse_damage_redirect,
    _parse_double_combat_damage,
    _parse_damage_cant_be_prevented,
    _parse_coin_flip_stakes_loop,
    parse_mutual_control_of_sets,
    _parse_game_is_a_draw,
    _parse_modal_head,
    _parse_source_of_choice_effect,
    _parse_choose_damage_source,
    _parse_chosen_source_next_damage,
)
from .imperative_verbs import parse_imperative_verb


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
    # "Simultaneously, all phased-out creatures phase in and all creatures with
    # phasing phase out." (Time and Tide.) An adverb no other production claims,
    # and one sentence rather than two because the word is what makes the two
    # halves read their sets before either applies. Refuses without consuming.
    tide = parse_simultaneous_phasing(stream)
    if tide is not None:
        return tide
    # "Choose a land type and a basic land type. Each land of the first chosen
    # type becomes the second chosen type until end of turn." (Vision Charm.)
    # Two sentences the productions below would take one of and strand the
    # other — the card-name reader claims the first four words and fails on
    # "land", which is the refusal ("expected 'card'") this card carried.
    # Refuses without consuming.
    swap = parse_land_type_swap(stream)
    if swap is not None:
        return swap
    # "Choose a source you control and flip a coin." (Desperate Gambit.) Beside
    # Vision Charm above and refused by the same reader for the same reason: the
    # card-name production claims "Choose a card…" on its first three words and
    # fails on the noun, which is the "expected 'card'" this card carried too.
    # Refuses without consuming, and only where a later sentence reads the
    # choice back.
    chosen_source = _parse_choose_damage_source(stream)
    if chosen_source is not None:
        return chosen_source
    juxtaposition = _parse_exchange_greatest_mana_value(stream)
    if juxtaposition is not None:
        return juxtaposition
    # "You and that opponent each gain control of all creatures the other
    # controls until end of turn." (Reins of Power.) Juxtapose's opener one
    # verb over and the same reason for being read here: the compound subject
    # is a player and a conjunction, which the subject reader takes the first
    # half of and then fails on. Refuses without consuming.
    mutual_control = parse_mutual_control_of_sets(stream)
    if mutual_control is not None:
        return mutual_control
    # Mana Clash's whole three-sentence paragraph, which opens with the same
    # "You and target opponent …" shape and would meet the same subject parser.
    # Refuses without consuming.
    flip_loop = _parse_coin_flip_damage_loop(stream)
    if flip_loop is not None:
        return flip_loop
    # Every paragraph whose frame is an upkeep obligation — Mishra's War
    # Machine's damage-unless-cost, Power Leak's bounded payment, Phantasmal
    # Sphere's counter toll. Each is several printed sentences answering one
    # question, so all of them are tried before the ordinary damage and counter
    # productions, which would read the first sentence and strand the rest.
    # `grammar/upkeep.py` owns the order; each refuses without consuming.
    upkeep_paragraph = parse_upkeep_paragraph(stream)
    if upkeep_paragraph is not None:
        return upkeep_paragraph
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
    # Natural Balance's whole three-sentence paragraph, beside the two above
    # for their reason: it opens on a noun phrase ("Each player who controls six
    # or more lands") that the subject reader would take and then a verb no
    # production of its own would finish. Refuses without consuming.
    rebalanced = _parse_rebalance_lands(stream)
    if rebalanced is not None:
        return rebalanced
    # Tariff's two-sentence paragraph, beside Natural Balance's for its reason
    # and one word apart from it: both open "Each player …" on a verb whose
    # ordinary production would read the first sentence and strand the second.
    # Refuses without consuming.
    tariff = _parse_pay_or_sacrifice_greatest_mana_value(stream)
    if tariff is not None:
        return tariff
    # Search for Survivors' four sentences, which open on a verb ("Reorder")
    # no production reads alone. Refuses without consuming.
    survivors = _parse_random_graveyard_card_fate(stream)
    if survivors is not None:
        return survivors
    colour_shield = _parse_source_of_choice_effect(stream)
    if colour_shield is not None:
        return colour_shield
    # "The next time **that source** would deal damage this turn, it deals
    # double that damage instead." (Desperate Gambit.) The same eight opening
    # words with the source named by a back-reference and no recipient at all,
    # so the production above declines it without consuming and this reads it.
    # Behind that one because it is the narrower sentence: everything it accepts
    # after "the next time" is a pronoun, which that reader has already refused.
    bound_next_damage = _parse_chosen_source_next_damage(stream)
    if bound_next_damage is not None:
        return bound_next_damage
    # "All damage that would be dealt to you this turn by target attacking
    # creature is dealt to this creature instead." (Shimian Night Stalker.) A
    # noun phrase in front of the verb, like the one above, and refusing without
    # consuming so every other sentence opening "All …" is untouched.
    redirect = _parse_damage_redirect(stream)
    if redirect is not None:
        return redirect
    # "For each 1 damage that would be dealt to you until your next upkeep, you
    # remove an echo counter from this enchantment instead." (Soul Echo.) The
    # same kind of sentence as the redirect above — one *about* a damage event
    # — and refusing without consuming for the same reason: "For each …" opens
    # the ordinary per-object loop, which must keep its own reading.
    becomes_counters = _parse_damage_becomes_counter_removal(stream)
    if becomes_counters is not None:
        return becomes_counters
    # "If a creature would deal combat damage to a creature this turn, it deals
    # double that damage to that creature instead." (Blind Fury.) A CR 614
    # replacement whose sentence opens on "if" and never names a subject, so the
    # subject-verb reader below would take "a creature" for one and fail on the
    # modal — the same reason the redirect above and the lock below are read
    # here. Refuses without consuming.
    doubled = _parse_double_combat_damage(stream)
    if doubled is not None:
        return doubled
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
    # Every verb-led shape, in :mod:`imperative_verbs`. Last, because each of
    # the paragraph openers above would be half-eaten by one of them.
    return parse_imperative_verb(stream, parse_optional_action=parse_optional_action)

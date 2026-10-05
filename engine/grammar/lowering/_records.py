"""What each instruction kind records in the resolution scratchpad.

One table, ``_PRODUCES``, its two payload-conditional refinements, and the two
accessors that ask them. A *registry* rather than logic, exactly as
``categories`` beside it is: a handler writes a value and a later sentence of
the same effect reads it back ("that much", "if you do", "died this way"), and
the only thing that can say the two agree is a declaration both sides are held
to.

Beside `_common` rather than inside it, and beside `categories` rather than
inside it, for `_events`' own stated reason: what a step **records** is keyed by
*instruction kind*, where `_events`' tables are keyed by *trigger-condition
kind* and `categories`' by which migration family a kind belongs to. Three
tables, three keys, three questions — and `categories` had grown to a thousand
lines carrying two of them.

**A value may be a tuple**, because a handler may record more than one thing and
this table was under-describing when it could not say so:
``destroy_target_permanent`` has written both the victim's mana value and its
controller's seat for as long as both riders have existed, and the table named
one of them. The **first** entry is the *primary* record — the one "if you do"
tests, because that rider asks whether the step took place and the primary is
what a step of that kind always writes when it does.

**The first paragraph is true again as of the Phase 0 after Mercadian
Masques.** Two CR 615.5 predicates — ``names_the_shielded_object`` and
``counts_prevented_damage`` — had accumulated at the bottom of this file, and
neither read ``_PRODUCES`` at all: they were here because this is a floor, not
because this is *their* floor. They now sit in ``_prevented_riders``, whose
stated subject is the rider a shield carries and whose docstring already cited
the same two cards. Which is the pre-split this module needed as well as the one
it wanted — the cut that restores a module's subject is worth more headroom than
the cut that only buys lines.

**A new record gets a terse row**: the card that needed it and a pointer to
where its key is named — the ``grant_extra_turn`` and ``flip_coin`` rows are
the model. *Why* the value has to be recorded rather than read off the board
is a fact about the key, and it lives with the key in ``_record_keys`` or
``oracle_types``; written here as well, it is a second copy that drifts. Say
here only what the key's definition cannot: which record is primary, which
payloads write it, why a record is withheld. Prophecy's Phase 0 found 34 rows
restating their key's own argument and nine comment blocks separated from their
rows by later insertions, which is what this table looks like when it holds the
argument twice.
"""

from __future__ import annotations

# The key names from the modules that name them, not through `_events`'
# re-exports. This table says which instruction kind writes which record, so it
# and the namer of each string belong next to each other — until Tempest's
# Phase 0 the fourteen `_record_keys` names were read through `_events`, which
# is neither, and the hop was invisible only because that module re-exported
# them. Prophecy's Phase 0 did the same for the eight left behind (six
# `oracle_types` names and `_deaths`' two); `_events` is read only for the two
# keys it defines itself.
from ...oracle_types import (ATTACHED_PERMANENT_CONTROLLER,
                             CHOSEN_COLOR_THIS_WAY,
                             CHOSEN_CREATURE_TYPE_THIS_WAY,
                             CHOSEN_NUMBER_THIS_WAY,
                             CHOSEN_TARGET_GRAVEYARD_SLOTS,
                             CHOSEN_TARGET_PERMANENTS, CHOSEN_THIS_WAY_OBJECTS,
                             COUNTERED_ABILITY_SOURCE,
                             COUNTERED_SPELL_CONTROLLER, COUNTERED_SPELL_NAME,
                             COUNTERS_REMOVED, DISCARDED_BY_SEAT, DREW_BY_SEAT,
                             DREW_COUNT, EXILED_BY_SEAT, EXILED_THIS_WAY,
                             EXILED_THIS_WAY_OBJECTS, HAND_CARDS_TO_LIBRARY,
                             LAST_TARGET_CONTROLLER, LAST_TARGET_NAME,
                             LAST_TARGET_OWNER, LIFE_LOST_THIS_WAY,
                             MANA_LOST_COUNT, MANA_LOST_THIS_WAY,
                             MANA_PAID_BY_SEAT, MILLED_THIS_WAY,
                             DISCARDED_INTO_GRAVEYARD, DISCARDED_THIS_WAY,
                             PER_OBJECT_SEAT_RECORDS, REVEALED_HAND_CARDS,
                             REVEALED_THIS_WAY, REVEALED_TOP_CARDS_BY_SEAT,
                             SACRIFICED_CARDS_BY_SEAT, SACRIFICED_COUNT,
                             SEARCHED_PERMANENTS, TAPPED_THIS_WAY,
                             TAPPED_THIS_WAY_OBJECTS, X_FROM_COUNT,
                             X_FROM_COUNT_PER_RECIPIENT)
from ._deaths import (_EVENT_SUBJECT_POWER_RECORD,
                      _EVENT_SUBJECT_TOUGHNESS_RECORD)
from ._events import EXILED_SPELL_CONTROLLER, EXILED_SPELL_RECORD
from ._record_keys import (CHOSEN_CAST_DAMAGE, CHOSEN_DAMAGE_SOURCE,
                           CONTROL_EXCHANGED_PERMANENTS,
                           CHOSEN_PERMANENT, CHOSEN_PLAYER, COUNTED_NUMBER,
                           CREATED_TOKEN, CREATED_TOKENS,
                           DAMAGE_RECIPIENT, EXTRA_TURN_GRANTED,
                           OTHER_CHOSEN_PERMANENT, PUT_FROM_HAND_PERMANENTS,
                           REMOVED_FROM_COMBAT_PERMANENTS,
                           _BASE_PT_SET_PERMANENTS, _COUNTERS_PLACED_THIS_WAY,
                           _PERMANENTS_GIVEN_COUNTERS, _REANIMATED_PERMANENTS)


_PRODUCES: dict[str, str | tuple[str, ...]] = {
    # Two records: how much was dealt, the primary, and who or what took it
    # (Drain Life, Soul Burn) — see ``_record_keys.DAMAGE_RECIPIENT``.
    "deal_damage": ("damage_dealt", DAMAGE_RECIPIENT),
    # "…**That creature** deals damage equal to its power to this creature."
    # (Tracker.) The bite's one target, which the second sentence names without
    # choosing again — see ``_record_keys._DAMAGED_PERMANENTS``.
    "source_bites_target": "damaged_permanents",
    # "…**If the player does**, return this card … **attached to that
    # creature**." (Takklemaggot.) The chosen permanent's id, both what the
    # branch tests and what the step behind it acts on; the choice is not a
    # target, so nothing else records it — see
    # ``_record_keys.CHOSEN_PERMANENT``. …and the **other** member of the set
    # it was offered (Retribution) — see ``_record_keys.OTHER_CHOSEN_PERMANENT``.
    "choose_permanent": (CHOSEN_PERMANENT, OTHER_CHOSEN_PERMANENT),
    # "…**Those creatures** gain haste until end of turn." (Reins of Power.)
    # Every creature the swap moved, both directions — by then the two sets
    # have changed hands, so neither printed seat phrase names them. See
    # ``oracle_types.CONTROL_EXCHANGED_PERMANENTS``.
    "exchange_control_of_sets_until_eot": CONTROL_EXCHANGED_PERMANENTS,
    # "…exchange control of this creature and up to one target creature an
    # opponent controls. **If you don't or can't make an exchange**, sacrifice
    # this creature." (Gilded Drake.) The same record from the chosen-slot
    # exchange, and the same key deliberately: a reader asking "did an exchange
    # happen?" is asking one question, and two keys would be one fact under two
    # names — free to disagree the day either handler is rewritten.
    #
    # What reads it here is the *negation*: CR 701.12a makes the exchange
    # atomic, so the record is written on the one path that completed it and on
    # no other, and "you don't or can't" is exactly the absence of it. Every
    # way the card can fail — no target chosen (the printed "up to one"), a
    # target that has left, one that no longer answers "an opponent controls",
    # a Guardian Beast on either side, both permanents under one seat — leaves
    # nothing recorded, which is why the branch is one condition rather than
    # five.
    "exchange_control_of_targets": CONTROL_EXCHANGED_PERMANENTS,
    # "Count the number of permanents. **If the number** is odd, …" (Chaos
    # Moon.) See ``_record_keys.COUNTED_NUMBER``; asking the board again would
    # be a second count, a different question the moment anything between them
    # changes it.
    "count_objects": COUNTED_NUMBER,
    # "Choose a player who cast one or more sorcery spells this turn.
    # Backdraft deals damage to **that player** …" The seat is the whole of what
    # the first sentence does, and the only place the second can read it: a
    # chosen player is not a target and nothing on a board records the choice.
    "choose_player_who_cast": CHOSEN_PLAYER,
    # "**An opponent** gains control of this land …" (Rainbow Vale.) The same
    # record: an unnamed seat the effect picks is written where every chosen
    # player is written, so the hand-over behind it needs no key of its own.
    "choose_opponent": CHOSEN_PLAYER,
    # "Destroy all creatures **of the creature type of your choice**."
    # (Extinction.) See ``oracle_types.CHOSEN_CREATURE_TYPE_THIS_WAY``.
    "choose_creature_type": CHOSEN_CREATURE_TYPE_THIS_WAY,
    # "**Choose target opponent.** … When it regenerates this way, **that
    # player** may draw a card." (Soldevi Sentry.) The seat the *targeting*
    # sentence chose, under the same key the resolution-time choice above
    # writes: which step picked the player is not a difference any later
    # sentence can see, and two keys would be two readers of "that player".
    "choose_target_player": CHOSEN_PLAYER,
    # "…equal to half the damage dealt by **one of those** sorcery spells this
    # turn." The pick records what the chosen cast dealt, because by the time
    # this is asked the spell has resolved and left the stack — the ledger is
    # the record, and this is which row of it the player named.
    "choose_cast_this_turn": CHOSEN_CAST_DAMAGE,
    # "Counter target spell. … an amount of {C} equal to **that spell's** mana
    # value." (Mana Drain.) The countered spell's mana value — the one thing
    # about it that survives the counter, and only because the counter wrote it
    # down. …and **whose** spell it was (Arcane Denial) — see
    # ``oracle_types.COUNTERED_SPELL_CONTROLLER``. The mana value stays primary:
    # it is the one an "if you do" would test.
    "counter_top_stack_spell": (
        "countered_spell_mana_value", COUNTERED_SPELL_CONTROLLER,
        # …and what it was called (Quash) — see
        # ``oracle_types.COUNTERED_SPELL_NAME``. Beside the seat because the
        # strip reads both: the name says what to look for and the seat says
        # whose zones to look in.
        COUNTERED_SPELL_NAME,
    ),
    # "…**That permanent's** activated abilities can't be activated this
    # turn." (Interdict.) See ``oracle_types.COUNTERED_ABILITY_SOURCE``.
    "counter_stack_ability": COUNTERED_ABILITY_SOURCE,
    # "…destroy the other creature at end of combat. At the beginning of the
    # next end step, **if that creature was destroyed this way**, …" (Infinite
    # Authority.) The delayed destroy records which creature it marked and which
    # one the trigger was about, because the sentence after it names both and by
    # then neither is anything the board can be asked for — the victim is in a
    # graveyard and the pair the trigger bound is long past.
    "delayed_destroy_blocked_or_blocker": "end_of_combat_destruction",
    # "Destroy all nonblack creatures. … where X is the number of creatures
    # that **died this way**." (Hellfire.) A sweep records how many permanents
    # it actually destroyed, which is the only place a later clause can read
    # that set from — by then the board no longer holds it.
    # Each of these records the victims and their controllers beside the count,
    # so "for each <noun> destroyed this way, its controller …" reaches a set
    # rather than an empty list. Declared as two products because they are two
    # questions: how many died, and whose each of them was.
    "destroy_all_creatures": ("destroyed_this_way", PER_OBJECT_SEAT_RECORDS["controller"]),
    "destroy_all_artifacts": ("destroyed_this_way", PER_OBJECT_SEAT_RECORDS["controller"]),
    "destroy_all_enchantments": ("destroyed_this_way", PER_OBJECT_SEAT_RECORDS["controller"]),
    "destroy_all_lands": ("destroyed_this_way", PER_OBJECT_SEAT_RECORDS["controller"]),
    "destroy_all_artifacts_creatures_enchantments": (
        "destroyed_this_way", PER_OBJECT_SEAT_RECORDS["controller"],
    ),
    "destroy_all_matching": "destroyed_this_way",
    # "Destroy all Plains. **For each land destroyed this way**, this spell
    # deals 1 damage to **that land's controller** unless they pay {2}."
    # (Stench of Evil.) Two records rather than one: the sweep beside it needs
    # only the count, and this sentence asks a question about each victim
    # individually — whose it was — which CR 400.7 makes unanswerable from any
    # later read of the board.
    "destroy_all_lands_of_type": (
        "destroyed_this_way", PER_OBJECT_SEAT_RECORDS["controller"],
    ),
    # "Exile all white creatures. **For each creature exiled this way**, …"
    # (Martyr's Cry.) The exile sweep's twin of the four rows above, and its own
    # marker rather than theirs: a sweep that exiles kills nothing, so "died
    # this way" over it would name an empty set.
    # …and the **list** beside the count, which the handler has written
    # since it was first read for "For each creature exiled this way" and
    # this table did not say so. A record written and undeclared is a
    # back-reference gate that refuses a sentence the effect can answer:
    # "each player chooses one of the exiled cards" (Thieves' Auction)
    # reads exactly this list. Two records for the one step, for the
    # ``exile_graveyard_cards`` row's stated reason — how many, and which.
    "exile_all_matching": (EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS),
    # "…exile up to two target creature cards from defending player's
    # graveyard. If you do, you gain 1 life **for each card exiled this way**"
    # (Rysorian Badger). The same key the sweep above writes, because the
    # question the back-reference asks is the same one: how many did this step
    # exile? Written when the prompt is answered, which is why the offer's
    # ``then`` branch has to wait for it — the choice spec says ``suspends``.
    "exile_cards_from_graveyard": EXILED_THIS_WAY,
    # "Each player exiles all creature cards from their graveyard, then … then
    # puts all cards **they** exiled this way onto the battlefield." (Living
    # Death.) The per-seat record — see ``oracle_types.EXILED_BY_SEAT``. The
    # sweep writes one entry per seat, including the empty ones: a seat the map
    # never mentioned reads as somebody else's pile the moment a later step
    # iterates it.
    # …and the flat pair beside it, because the same step answers a second
    # question a card actually prints: "you gain 1 life **for each card exiled
    # this way**" (Honor the Fallen) asks how many, over the whole table, and
    # the per-seat map above cannot answer it without a reader that knows the
    # map's shape. Three records for one step rather than two spellings of one:
    # the map is *whose*, the count is *how many*, and the list is *which*.
    "exile_graveyard_cards": (
        EXILED_BY_SEAT, EXILED_THIS_WAY, EXILED_THIS_WAY_OBJECTS,
    ),
    # Which mana the emptied pool held (Drain Power) and how much (Pygmy Hippo)
    # — see ``oracle_types.MANA_LOST_THIS_WAY`` and ``MANA_LOST_COUNT``. The
    # dict is primary: it is what an "if you do" would test.
    "lose_all_unspent_mana": (MANA_LOST_THIS_WAY, MANA_LOST_COUNT),
    # "You gain life equal to **the life lost this way**." (Subversion.) See
    # ``oracle_types.LIFE_LOST_THIS_WAY``.
    "target_loses_life": LIFE_LOST_THIS_WAY,
    # CR 705.2: only the player who flipped wins or loses that flip, and both
    # "if you win" and "if you lose" read the one result — so the flip records
    # it and the conditionals after it read the record, rather than each
    # sentence flipping a coin of its own.
    "flip_coin": "coin_flip",
    # "…Search that player's library for **that many** cards." (Jester's Mask.)
    # See ``oracle_types.HAND_CARDS_TO_LIBRARY``; by then the hand is empty and
    # nothing else records how many went.
    "put_hand_cards_on_library": HAND_CARDS_TO_LIBRARY,
    # "Shuffle a card from your hand into your library. **If you do**, draw
    # two cards at the beginning of the next turn's upkeep." (Lat-Nam's
    # Legacy.) The same record its twin one destination over writes, and the
    # same reason: the number is settled before the prompt is armed, so the
    # rider behind it reads what the step really moved rather than what the
    # card asked for — an empty hand shuffles nothing and draws nothing.
    "shuffle_hand_cards_into_library": HAND_CARDS_TO_LIBRARY,
    # "Return that card to its owner's hand. **If that card is returned to
    # its owner's hand this way**, …" (Puppet Master.) The return records
    # whether it actually took place, which is what the rider after it asks —
    # the card may have been exiled in response, or diverted (CR 903.9b).
    "return_bound_card_to_owners_hand": "returned_bound_card",
    # "Discard X cards, **then** return a card from your graveyard to your hand
    # **for each card discarded this way**." (Recall.) The prompt records how
    # many were actually discarded when it is answered, which is the only place
    # the number exists — the hand the step was handed is not the hand the
    # player chose from.
    "discard_controller_cards": "discarded_count",
    # "Discard a card **at random**. If you discard a creature card this way,
    # return it from your graveyard to the battlefield …" (Aether Rift.) The
    # sample takes its cards inline, so this step knows *which* went as well as
    # how many: see ``oracle_types.DISCARDED_THIS_WAY``. The count stays the
    # primary, so "if you do" behind a random discard asks what it asks behind
    # every other one.
    "discard_x_target_cards": (
        "discarded_count", DISCARDED_THIS_WAY, DISCARDED_INTO_GRAVEYARD,
    ),
    # The per-seat form records the same thing, so a sentence reading "the
    # number of cards they discarded this way" has a producer to name — and
    # records it **twice**, flat and keyed by seat, which is what the prompt
    # has always written. Only the flat key was declared, so "then draws that
    # many cards" (Flux) had no per-seat producer to demand and the looped
    # draw would have read one seat's answer for everybody.
    "each_player_discards_up_to_cards": ("discarded_count", DISCARDED_BY_SEAT),
    # "…tokens equal to **the amount of mana they paid this way**." (Liege of
    # the Hollows.) See ``oracle_types.MANA_PAID_BY_SEAT``.
    "each_player_pays_any_mana": MANA_PAID_BY_SEAT,
    # "Each player may draw up to two cards. **For each card less than two a
    # player draws this way**, …" (Truce.) Written as each prompt is answered,
    # since how many a seat drew is a decision it has not made when the
    # instruction returns — see ``oracle_types.DREW_BY_SEAT``.
    "each_player_draws_up_to_cards": DREW_BY_SEAT,
    # "…equal to **the number of cards they drew this way**." (Malignant
    # Growth.) How many really arrived, which is not the count the first half
    # asked for once a replacement or an empty library has had its say — see
    # ``oracle_types.DREW_COUNT``.
    "draw_target_cards": DREW_COUNT,
    # "Target player discards two cards, **then draws as many cards as they
    # discarded this way**." (Forget.) The chosen-discard prompt is the same
    # one ``discard_controller_cards`` arms, so it records the same key — what
    # differs is whose hand it came out of, and the sentence behind it is about
    # that same seat. Without the row the back-reference has no producer to
    # name and the draw refuses (idiom 7), which is the honest failure; with it
    # the count is the one the player actually gave rather than the printed
    # two, and an empty hand draws none.
    "discard_target_cards": "discarded_count",
    # "Choose two cards in your hand … **For each of those cards**, …"
    # (Sylvan Library.) The pick records what it chose, which is the only
    # place the next sentence can read that set from: nothing about a hand
    # says which of its cards an earlier step named.
    "choose_cards_in_hand": "chosen_hand_cards",
    # "Choose X target attacking creatures. **For each of those creatures**, …"
    # (Winter's Chill.) The same shape one zone over — see
    # ``oracle_types.CHOSEN_TARGET_PERMANENTS``; by the time the loop runs, one
    # of them may have left combat.
    # Two records, because "controlled by the same opponent" names a *player*
    # as well as a set: "**That player** chooses and sacrifices one of those
    # creatures" (Retribution) reads the seat, and this step is the only one
    # that can supply it — the relation is what makes the answer a single seat,
    # and the sacrifice behind it is about to empty one of the two slots. The
    # set is the primary, being what a step of this kind always records.
    "choose_target_permanents": (CHOSEN_TARGET_PERMANENTS, CHOSEN_PLAYER),
    # "**You** choose target creature an opponent controls, and **that
    # opponent** chooses target creature." (Mogg Assassin.) The singular of the
    # row above, recording the same two things under the same two keys: which
    # permanent this effect announced, and whose it is. One object always has
    # one controller, so the seat needs no "controlled by the same" relation to
    # be well defined — which is the only reason the plural's row has to earn it.
    #
    # The set record is what "**the creature you chose**" reads two sentences
    # later: by then the resolution has armed a second, resolution-time choice,
    # and ``context.target`` is one slot that cannot hold both answers.
    "choose_target_permanent": (CHOSEN_TARGET_PERMANENTS, CHOSEN_PLAYER),
    # "**Choose two target creature cards in your graveyard.** … return **the
    # chosen cards** to the battlefield tapped." (Victimize.) See
    # ``oracle_types.CHOSEN_TARGET_GRAVEYARD_SLOTS``.
    "choose_target_cards": CHOSEN_TARGET_GRAVEYARD_SLOTS,
    # "Target player loses all poison counters. Leeches deals **that much**
    # damage to that player." See ``oracle_types.COUNTERS_REMOVED``.
    "remove_all_counters_from_target_player": COUNTERS_REMOVED,
    # "…remove all charge counters from it. **Add {C} for each charge counter
    # removed this way.**" (Ventifact Bottle.) The same record one object
    # over: that row empties a *player's* store and this one a permanent's,
    # and the sentence behind either asks the same question about the number.
    "remove_all_counters_from_self": COUNTERS_REMOVED,
    # "Remove any number of +1/+1 counters … create **that many** … tokens"
    # (Tetravus). The removal records how many it took, under the key the token
    # maker's "that many" already reads.
    "remove_any_number_of_counters_from_self": "trigger_count",
    # "Exile any number of tokens created with this creature. If you do, put
    # **that many** +1/+1 counters on this creature." The same key, for the same
    # reason: the count is what the next sentence is about.
    "exile_any_number_of_own_tokens": "trigger_count",
    # Whose permanent the exile removed, for "Its controller creates a token"
    # (Angelic Ascension) — see ``oracle_types.LAST_TARGET_CONTROLLER``.
    # …and its **toughness**: "Exile target nonwhite attacking creature. You
    # gain life equal to **its toughness**" (Exile) asks a question about an
    # object that by then is a card in exile with no computed characteristics
    # at all (CR 613.1), so the number is frozen where it still had one
    # (CR 608.2h), exactly as the destroy row below freezes its pair.
    #
    # The **power** is deliberately not declared, and this is the one place in
    # the table where a step records something the declaration withholds. That
    # reading of this sentence already has an owner:
    # ``_fused_exile_then_controller_life`` implements Swords to Plowshares,
    # and `test_exile_shapes_the_fused_handler_does_not_implement_refuse` holds
    # its two near-misses to a refusal. Declaring the power un-refuses both,
    # and one of them is wrong — "Exile target artifact. **Its controller**
    # gains life equal to its power" lowers with ``recipient: "target"``, a
    # different seat from the one the sentence names, while
    # ``last_target_controller`` (declared right here) is the key that
    # answers it. Widening the fusion to the artifact subject and routing the
    # recipient through that key is a round of its own; until then the words
    # refuse for want of a producer, which is the loud failure.
    "exile_target_permanent": (
        LAST_TARGET_CONTROLLER, _EVENT_SUBJECT_TOUGHNESS_RECORD,
        # …and the card itself (Liberate: "Return **that card** to the
        # battlefield …"). The key every other exile declares, written by the
        # single-target path of the handler.
        "exiled_cards",
        # …and what it was called (Eradicate) — see
        # ``oracle_types.LAST_TARGET_NAME``. Safe to declare where the *power*
        # above is not: nothing else in the grammar reads a name record, so
        # this un-refuses no near-miss.
        LAST_TARGET_NAME,
    ),
    # "Create Stangg Twin, a … token. Exile **that token** when …" (Stangg).
    # The token maker records which permanent it made, which is the only place
    # a later sentence of the same effect can name it from — a token is a new
    # object with a fresh id (CR 400.7), so there is nothing about it to look
    # up by.
    "create_token": (CREATED_TOKEN, CREATED_TOKENS),
    # "Create a token that's a copy of that creature. **That token** gains
    # haste until end of turn." (Echo Chamber.) The copy maker records what it
    # made under the same key the token maker above it does, and for that
    # entry's reason word for word — which token a sentence names is one
    # question however the token was built, and two keys would be two readers
    # of the same two printed words.
    "create_copy_token": CREATED_TOKEN,
    # Both exiles record what they exiled, which is what "you may play cards
    # exiled this way" / "you may cast them this turn" read.
    "exile_top_of_library": "exiled_cards",
    # …and Ice Cauldron's hand exile, written when its prompt is answered.
    "exile_chosen_card_from_hand": "exiled_cards",
    # "Exile all / any number of cards from your hand face down." (Duplicity,
    # Scroll Rack.) **Two** records for one step, and neither is the other:
    # ``exiled_cards`` is what a *count* behind it reads ("put that many cards
    # from the top of your library into your hand"), and ``exiled_entries`` is
    # what an *exclusion* behind it reads ("put all **other** cards … into your
    # hand"). Only the entries can answer the second — the pile may already
    # hold another copy of the same card, and a hand repeats one immutable
    # ``CardDefinition`` per copy, so the cards themselves are not distinct.
    # …and a **fourth**, the per-seat one: "each player … returns to their hand
    # each card **they** exiled this way" (Memory Jar) asks the question once
    # per player, and the flat list above answers it with the whole table's
    # hands. Declared for the kind rather than for the per-seat printing of it,
    # because ``exile_hand_slots`` writes it on every path — the seat is its own
    # parameter, and a record kept in one of two callers is the shape that seam
    # exists to prevent.
    "exile_hand_pile": (
        "exiled_cards", "exiled_entries", "exiled_count", EXILED_BY_SEAT,
    ),
    # "That player exiles a card at random from their hand." (Elkin Lair.) The
    # pile is one card and the seat is not the caster, neither of which the
    # back-references behind it care about: "that card" names what this step
    # exiled, whoever exiled it.
    "exile_random_card_from_hand": "exiled_cards",
    "search_and_exile_matching": "exiled_cards",
    # "**Choose a card name**, then target opponent mills a card. If a card
    # with the chosen name was milled this way, …" (Foreshadow.) The name is the
    # whole of what the first sentence does, and the only place the third can
    # read it from — CR 202.1 lets a player name any card, so nothing on a board
    # records the choice.
    "choose_card_name": "chosen_card_name",
    # "…then you choose a card other than a basic land card from it. Search
    # that player's … library for all cards with the same name as **the chosen
    # card**…" (Lobotomy.) The pick records the chosen card's *name*, under the
    # key the naming choice above writes — "the chosen card's name" and "the
    # chosen card name" are one question asked by two sentences, and two keys
    # would be two readers of it.
    #
    # Declared for the kind and written by every fate, which is what makes the
    # declaration true of Duress as well: the pick is a chosen card whatever
    # becomes of it.
    "reveal_hand_and_choose": "chosen_card_name",
    # "Look at the top card of target player's library. **If it's a nonland
    # card**, …" (Wand of Denial.) The card the look turned up, under the key
    # every "is it a …?" clause reads. A look and a reveal differ in who sees
    # the card, not in which object the pronoun behind them names.
    "look_at_target_library_top": "revealed_card",
    # "…that player discards all the cards in their hand, then draws **that
    # many** cards." (Shocker.) How many the sweep actually binned, under the
    # key the counted discards already write — the printed sentence names no
    # number, and an empty hand makes the draw zero rather than the hand's
    # printed size, which is the only reading CR 608.2 allows.
    # …and the per-seat map beside it, which the ``who: "each_player"`` form
    # writes: "the greatest number of cards **a player** discarded this way"
    # (Windfall) is a maximum across seats, and the flat number above is
    # whichever seat the loop emptied last.
    "discard_hand": ("discarded_count", DISCARDED_BY_SEAT),
    # "…**target opponent mills a card**. If a card with the chosen name was
    # milled this way, …" (Foreshadow.) See ``oracle_types.MILLED_THIS_WAY``,
    # the key the repeated mill below writes too.
    "mill_target_player": MILLED_THIS_WAY,
    # "…until a creature card **or X cards have been put into their graveyard
    # this way**" (Helm of Obedience). The loop records the cards it put there
    # that its own stopping filter matched, which is what both sentences behind
    # it read: "if one or more creature cards were put into that graveyard this
    # way" asks whether the set is empty, and "put one of them onto the
    # battlefield" takes from it. Nothing else can answer either, because a
    # graveyard holds cards this effect never touched.
    "mill_until_matching": MILLED_THIS_WAY,
    # And the graveyard exile, which is what "If **it** was a creature card"
    # reads (Scavenging Ooze) — the same key, because the question the
    # back-reference asks is the same one: what did this effect just exile?
    "exile_target_graveyard_card": "exiled_cards",
    # "Remove a pupa counter from this Aura. **If you can't**, …" (Cocoon).
    # The removal records whether a counter was there to remove, and the
    # if-you-can't branch reads the record back, negated.
    "remove_counter_from_self": "removed_counter",
    # "Sacrifice two Swamps. **If you can't**, …" (Infernal Denizen.) The
    # sacrifice records whether every payer could actually pay the printed
    # count — CR 701.21a, and CR 608.2's "as much as possible" is exactly why
    # it is the printed count rather than "at least one": a player with one
    # Swamp cannot sacrifice two, so nothing is sacrificed and the branch runs.
    # Written *before* the prompt is armed, because an interactive seat answers
    # a queued prompt long after this instruction has returned.
    #
    # ``sacrificed_cards`` is the second record and answers a different
    # question: not "could the printed count be paid" but "**what** went".
    # "If you sacrifice a **snow** Forest this way, …" (Gargantuan Gorilla,
    # Serendib Djinn) needs the card itself, and by the time the branch runs it
    # is in a graveyard and a different object (CR 400.7, CR 608.2h) — so the
    # sacrifice records it as it happens. It is written *after* the prompt is
    # answered, which is the opposite half of the note above and is why the two
    # are separate keys rather than one: only the first is available
    # synchronously, and only the second says what was chosen.
    #
    # ``SACRIFICED_CARDS_BY_SEAT`` is the third: **which seats** gave something
    # up (Desolation) — see ``oracle_types.SACRIFICED_CARDS_BY_SEAT``.
    #
    # ``SACRIFICED_COUNT`` is the fourth and the only *number*, for Last-Ditch
    # Effort's bare "that much" — see ``oracle_types.SACRIFICED_COUNT``.
    # (Reprocess's "for each permanent sacrificed this way" names its producer
    # outright and reads the list.) Last, so ``primary_produced`` still answers
    # "did the sacrifice happen" with the boolean it always has.
    "sacrifice_matching_permanent": (
        "sacrificed_this_way", "sacrificed_cards", SACRIFICED_CARDS_BY_SEAT,
        SACRIFICED_COUNT,
    ),
    # "…that creature's controller sacrifices it at end of combat. **If the
    # player does**, **they** create a 0/2 … Wall …" (Basalt Golem.) The same
    # two questions the row above answers, asked of the bound sacrifice: whether
    # it happened, and whose creature it was — and the second is the only place
    # the token's recipient can come from, because by then the creature is a
    # card in a graveyard.
    #
    # "At the beginning of the next end step, sacrifice it. **If you do**, you
    # gain life equal to **its toughness**." (Spinal Embrace.) And what it
    # *was*: a bound sacrifice names exactly one object, so the handler freezes
    # its computed P/T as it goes (CR 608.2h) under the keys the destroy step
    # and the chosen sacrifice write.
    "sacrifice_bound_permanent": (
        "sacrificed_this_way", LAST_TARGET_CONTROLLER,
        _EVENT_SUBJECT_POWER_RECORD, _EVENT_SUBJECT_TOUGHNESS_RECORD,
    ),
    # "Target creature you control can't be blocked this turn. **Destroy it**
    # and this creature at end of combat." (Goblin Sappers.) The grant records
    # the creature it chose, so the delayed destroy behind it has a producer to
    # gate on — without one the pronoun would name the ability's own source and
    # the Sappers would destroy themselves twice.
    "grant_unblockable_to_target": "unblockable_permanents",
    # "X target attacking creatures become blocked. Choking Vines deals 1 damage
    # to **each of those creatures**." See ``_record_keys._BLOCKED_PERMANENTS``;
    # a board read would find every blocked attacker, including the ones the
    # defending player blocked in the ordinary way.
    "become_blocked": "blocked_permanents",
    # "Put a paralyzation counter on each creature blocking or blocked by this
    # creature and tap **those creatures**." (Dread Wight.) See
    # ``_record_keys._PERMANENTS_GIVEN_COUNTERS``.
    "add_named_counter_to_creatures_in_combat_with_source": _PERMANENTS_GIVEN_COUNTERS,
    # "…**For each +1/+1 counter you put on a creature this way,** …" (Bounty
    # of the Hunt.) One entry per counter — see
    # ``oracle_types.COUNTERS_PLACED_THIS_WAY``; nothing on the board afterwards
    # can say which of a creature's counters this spell put there.
    "add_counter_to_target": _COUNTERS_PLACED_THIS_WAY,
    # "…**That creature** gains "Cumulative upkeep {2}."" (Dreams of the Dead.)
    # See ``_record_keys._REANIMATED_PERMANENTS``.
    # …**and the mana value of the card it moved**. "Put target creature card
    # from a graveyard onto the battlefield under your control. You lose life
    # equal to **that card's mana value**." (Reanimate.) The same record the
    # destroy row below declares and for the same reason: the number is about an
    # object the reader cannot go and look at — here because the sentence named
    # a card in a *graveyard*, so there was no permanent to read when the
    # ability was announced, and CR 400.7 makes what arrived a new object.
    # Frozen by the step that performs the move (CR 608.2h).
    #
    # ``_REANIMATED_PERMANENTS`` stays first: ``primary_produced`` reads the
    # head of this tuple as the record an "if you do" tests, and "if you do"
    # about a reanimation asks whether a permanent arrived, never how much it
    # cost.
    "reanimate_creature": (_REANIMATED_PERMANENTS, "its_mana_value"),
    # "…**return it to the battlefield** under your control and put a death
    # counter on **it**." (Bogardan Phoenix.) The reanimation asked of the
    # ability's own source, and it records under the same key for the same
    # reason: CR 400.7 makes what comes back a *new object*, so the pronoun
    # behind this step cannot mean the permanent that died — and every reader
    # in the resolution is still holding that one.
    "return_source_card_to_battlefield": _REANIMATED_PERMANENTS,
    # "…**That Dragon** gains haste until end of turn. Exile **it** at the
    # beginning of the next end step." (Zirilan of the Claw.) The reanimation's
    # twin one zone over — see ``oracle_types.SEARCHED_PERMANENTS``.
    "search_library": SEARCHED_PERMANENTS,
    # "You may put a creature card from your hand onto the battlefield. If you
    # do, sacrifice **it** …" (Flash.) The third member of the same family —
    # see ``_record_keys.PUT_FROM_HAND_PERMANENTS``.
    "put_chosen_card_from_hand_onto_battlefield": PUT_FROM_HAND_PERMANENTS,
    # "Take an extra turn after this one. At the beginning of **that turn's**
    # end step, you lose the game." (Final Fortune.) The queued turn, recorded
    # so the delay behind it has something to refer back to — see
    # ``_record_keys.EXTRA_TURN_GRANTED``.
    "grant_extra_turn": EXTRA_TURN_GRANTED,
    # "Tap all untapped Islands that player controls and this enchantment deals
    # X damage to the player, **where X is the number of Islands tapped this
    # way**." (Monsoon.) How many the sweep turned — by then the board says how
    # many *are* tapped rather than how many this effect tapped. And which
    # permanents the printed noun phrase named, for "**They** don't untap during
    # their controller's next untap step" (Joven's Ferrets): two records, for
    # the destroy family's reason. The count is the primary — it is what a step
    # of this kind has always written.
    "tap_all_matching": (TAPPED_THIS_WAY, TAPPED_THIS_WAY_OBJECTS),
    # "Each player may tap any number of untapped white creatures they control.
    # **For each creature tapped this way, that player** chooses…" (Raiding
    # Party.) Three records, because the sentence behind it asks three
    # questions: how many were tapped, which permanents they were, and whose
    # each of them was.
    #
    # The set is not something a later read of the board could supply, which is
    # the one place this differs from the destroy family's identical trio: the
    # objects are still on the battlefield, and asking the board would name
    # every tapped permanent rather than the ones this effect turned.
    "tap_any_number_matching": (
        TAPPED_THIS_WAY, TAPPED_THIS_WAY_OBJECTS,
        PER_OBJECT_SEAT_RECORDS["controller"],
    ),
    # "…**Then destroy all Plains that weren't chosen this way by any
    # player.**" (Raiding Party.) See ``oracle_types.CHOSEN_THIS_WAY_OBJECTS``.
    "choose_permanents": CHOSEN_THIS_WAY_OBJECTS,
    # "Target creature you cast this turn **has base power and toughness 0/1**
    # …. At the beginning of your next upkeep, put a +1/+1 counter on **that
    # creature**." (Cycle of Life.) See ``oracle_types.BASE_PT_SET_PERMANENTS``.
    "set_base_pt_target_until_eot": _BASE_PT_SET_PERMANENTS,
    # "Tap up to two target creatures. **Those creatures** don't untap…"
    # (Frost Breath.) The tap records which permanents it affected, by id, and
    # the sentence after it reads that record rather than re-resolving the slots
    # — by then a target may have left, and CR 611.2c fixed the set when the
    # effect began.
    "tap_target_permanent": "tapped_permanents",
    # "…tap the creature, **remove it** from combat" (Imprison). The Aura's tap
    # names its own attachment rather than a target, so it is a different
    # producer of the same record — what this effect just tapped.
    "tap_enchanted_creature": "tapped_permanents",
    # "Untap **it** and remove **it** from combat." (Melee's delayed ability.)
    # The same record from the other spelling of the same step: the sentence
    # names its own source rather than a target, so the pronoun that follows
    # has to read what *this* effect untapped — and the pair "untap … and
    # remove it from combat" is the same pair Disharmony prints below with a
    # target in front of it. Recorded whether or not the permanent was tapped:
    # CR 611.2c fixes the set when the effect begins, so a vigilance attacker
    # nobody tapped is still "it".
    "untap_self": "untapped_permanents",
    # "Remove target attacking creature you control from combat **and untap
    # it**." (Reconnaissance.) The same shape the untap below is in for
    # Disharmony, with the two steps in the other order — see
    # ``_record_keys.REMOVED_FROM_COMBAT_PERMANENTS``. Harmless for the
    # printings that read a record rather than write one (Disharmony, Imprison,
    # Melee): nothing is printed behind their removal, so the key is written and
    # never read.
    "remove_from_combat": REMOVED_FROM_COMBAT_PERMANENTS,
    # "Untap target attacking creature and remove **it** from combat. Gain
    # control of **that creature** until end of turn." (Disharmony.) The untap
    # records what it resolved — affected, not merely flipped: a vigilance
    # attacker that was never tapped is still "it" (CR 611.2c fixes the set
    # when the effect begins) — and both later sentences read the record.
    "untap_target_permanent": "untapped_permanents",
    # "…untap enchanted land. **You gain control of that land** until end of
    # turn." (Wellspring.) The Aura's own untap, recorded under the same key
    # the targeted one above uses: which untap put the permanent there is
    # not something the sentence behind it can see, so it must not be
    # something it has to know.
    "untap_enchanted_creature": "untapped_permanents",
    # "Target player reveals their hand." (Sirocco, Inquisition, Amnesia.) What
    # was shown, for the sentence that narrows it — see
    # ``oracle_types.REVEALED_HAND_CARDS``.
    "reveal_hand": REVEALED_HAND_CARDS,
    # "**Choose a number greater than 0 and a color.** … If that opponent
    # reveals exactly **the chosen number** of cards of **the chosen color**,
    # you draw a card." (Scrying Glass.) Two steps, two records — see
    # ``oracle_types.CHOSEN_NUMBER_THIS_WAY`` and ``CHOSEN_COLOR_THIS_WAY``.
    #
    # Declared unconditionally, the way ``count_objects`` declares the number
    # it takes: what a step records is a property of the step, and a producer
    # that only sometimes wrote its record would be a gate that only sometimes
    # protected the reader behind it.
    "choose_number": CHOSEN_NUMBER_THIS_WAY,
    "choose_color": CHOSEN_COLOR_THIS_WAY,
    # "Reveal any number of blue cards in your hand." (Brine Seer and the
    # eleven cards printed with it.) **Two** records, and the count is the
    # primary: every sentence in the pool that follows this one spends it — see
    # ``oracle_types.REVEALED_THIS_WAY``.
    #
    # Deliberately **not** in ``_record_keys._PRODUCED_QUANTITIES``: no card
    # prints a bare "that much" after a reveal, so admitting it there would be
    # a reading nothing exercises — and a second candidate for every bare
    # back-reference in a sentence that also reveals.
    "reveal_cards_from_hand": (REVEALED_THIS_WAY, REVEALED_HAND_CARDS),
    # "…reveal the top card of your library. **If it's** a creature or land
    # card, draw a card." (Track Down.) The reveal records what it showed and
    # the conditional after it reads that record — not the library, which the
    # draw in its own branch would have changed underneath it.
    "reveal_top_of_library": "revealed_card",
    # "Target player reveals a card at random from their hand." (Wand of
    # Ith.) The same record, from a different zone: the sentences behind it
    # ask what "it" is, and this is what answers.
    "reveal_random_card_from_hand": "revealed_card",
    # "Exile it. **If you do**, create a 5/5 black Demon creature token with
    # flying." (Archfiend's Vessel.) The self-exile records that it happened, so
    # the branch after it is the ordinary if-you-do rather than a fused kind.
    "exile_self": "exiled_self",
    # "Target spell's controller exiles it with X delay counters on it. At the
    # beginning of each of that player's upkeeps, …" (Ertai's Meddling.) Two
    # records from one step, and the delayed ability behind it needs both: the
    # exile register entry is what "remove a delay counter from **it**" reads,
    # and the seat is what "each of **that player's** upkeeps" fires on. Declared
    # here so the delay's lowering can refuse the sentence when no earlier step
    # exiled anything — a delay bound to nothing would arm an ability that
    # triggers every upkeep about a card nobody exiled.
    "exile_target_spell": (EXILED_SPELL_RECORD, EXILED_SPELL_CONTROLLER),
    # "Sacrifice this artifact. **If you do**, discard your hand, then put all
    # cards exiled with this artifact into their owner's hand." (Knowledge
    # Vault.) The same shape: the sacrifice records that it took place, so the
    # branch behind it is the ordinary if-you-do. A source that had already
    # left records nothing, and CR 608.2b's "as much as possible" is then
    # exactly the branch not running.
    "sacrifice_self": "sacrificed_self",
    # "Return another target creature you control to its owner's hand. If you
    # do, you gain life equal to **that creature's** mana value." (Niambi,
    # Esteemed Speaker.) The bounce records the mana value of what it returned,
    # because by the time the life gain runs the permanent is gone — reading it
    # off the battlefield would find nothing and gain nothing.
    "bounce_target_creature": "returned_mana_value",
    # "Destroy enchanted land **and this Aura deals 2 damage to that land's
    # controller**." (Orcish Mine.) See
    # ``oracle_types.ATTACHED_PERMANENT_CONTROLLER``.
    "destroy_attached_permanent": ATTACHED_PERMANENT_CONTROLLER,
    # "At the beginning of your upkeep, put a +1/+0 counter on **enchanted
    # creature**. If that creature has three or more … **it deals damage equal
    # to its power to its controller, then destroy that creature**."
    # (Consuming Ferocity.) The same record from the other verb: a step that
    # acts on the attachment is what makes every "that creature" and "its
    # controller" behind it readable, and which verb did it is not the
    # question — the destroy above records it because Orcish Mine's sentence
    # happened to be a destroy.
    "add_pt_counters_to_attached": ATTACHED_PERMANENT_CONTROLLER,
    # "Destroy target artifact. You gain life equal to **its** mana value."
    # (Divine Offering.) The destruction records the mana value of the
    # permanent it was aimed at — read *before* the destroy, so a regenerated
    # or indestructible artifact still supplies the number the second sentence
    # asks for: the words name the object, not the outcome.
    # "Destroy target land. **If that land was a snow land**, you gain 1 life."
    # (Thermokarst, Icequake.) The destruction also records the permanent it
    # was aimed at, read before the destroy for the reason the mana value is
    # (CR 608.2h, last-known information) — a condition asking what the land
    # *was* has nothing on the board left to look at.
    # "Destroy X target Mountains. …deals damage … equal to the number of
    # Mountains **put into a graveyard this way**." (Volcanic Eruption.) The
    # third record is what actually died — CR 701.8c keeps a regenerated
    # target out of it, where the two above are recorded before the destroy
    # precisely because they describe the object rather than the outcome.
    # Every branch of the handler writes it, because this table declares for
    # the *kind*: a branch that skipped it would be a producer the lowering
    # can cite and a record that reads as zero.
    # …and its power and its toughness, for the same reason and read at the same
    # moment: "Destroy target nonartifact attacking creature. … Its power is
    # equal to **that creature's power**" (Broken Visage) is a number about an
    # object that no longer exists by the time the token is built — CR 613.1
    # gives a card in a graveyard no computed characteristics at all, so the
    # numbers are frozen where the object still had them (CR 608.2h, idiom 6).
    # …and the victim's **controller**, the record the exile row above declares
    # (Afterlife, Polymorph) — see ``oracle_types.LAST_TARGET_CONTROLLER``.
    "destroy_target_permanent": (
        "its_mana_value", "destroyed_target", "destroyed_this_way",
        _EVENT_SUBJECT_POWER_RECORD, _EVENT_SUBJECT_TOUGHNESS_RECORD,
        LAST_TARGET_CONTROLLER,
        # …and what it was called (Wake of Destruction), for the reason the
        # exile row above declares the same key: the sweep in the second half
        # of that sentence compares against a permanent this step destroys.
        LAST_TARGET_NAME,
        # …and the victim's **owner** (Path of Peace) — see
        # ``oracle_types.LAST_TARGET_OWNER``.
        LAST_TARGET_OWNER,
        # "…equal to the number of artifacts **they controlled** that were put
        # into a graveyard this way." (Builder's Bane.) The same per-object
        # seat map the sweeps beside it write, read here as a per-seat tally
        # rather than one entry per loop iteration: "they" is every player at
        # once, so the sentence has one answer each and no loop to bind them.
        PER_OBJECT_SEAT_RECORDS["controller"],
    ),
    # "Prevent the next 3 damage … **for each 1 damage prevented this way**."
    # (Sacred Boon.) The shield object itself, because what it prevents is
    # not a number when it is armed — the total goes on accumulating for the
    # rest of the turn, and the reader is a delayed ability at the end step.
    "grant_prevention_shield": "prevention_shield",
}


#: Records a kind writes for **some payloads only**, as
#: ``kind -> (payload key, payload value, record)``.
#:
#: :data:`_PRODUCES` answers "what does a step of this kind write", which is the
#: whole answer for every kind but one. A library search puts its find wherever
#: the printed sentence sent it — a hand, a battlefield, the top of the library,
#: exile — and only the sentence that says *exile* leaves anything behind for
#: "until the beginning of your next upkeep, you may play that card" (Grinning
#: Totem) to read. Declaring ``exiled_cards`` flat on ``search_library`` would
#: admit a tutor-to-hand followed by that permission, which would compile clean
#: and permit nothing; leaving it out refuses the card that does print it.
#:
#: One table rather than a predicate, for :data:`_PRODUCES`' own reason: this is
#: a registry, and the thing being registered is a payload entry the lowering
#: already writes.
_PRODUCES_FOR_PAYLOAD: dict[str, tuple[str, object, str]] = {
    "search_library": ("destination", "exile", "exiled_cards"),
    # "Reveal the top three cards of your library and put one of them into
    # your hand. You gain life equal to **that card's mana value**." (Reviving
    # Vapors.) The pick writes the taken card's mana value only when the
    # sentence behind it asks — every other look-and-pick takes a card nobody
    # asks about again, and a flat row would let "its mana value" behind any of
    # them read a number no step of that card wrote.
    "look_top_pick_to_hand": ("record_pick", "its_mana_value", "its_mana_value"),
    # "**Each player** reveals the top card of their library." (Game Preserve.)
    # A row here rather than in ``_PRODUCES`` because it is not true of every
    # step of the kind: "reveal the top card of your library" opens one library
    # and records one card under ``revealed_card``, and declaring the per-seat
    # map flat would admit a one-library reveal followed by "put **those
    # cards** onto the battlefield under their owners' control" — a sentence
    # that would compile clean and put nothing.
    "reveal_top_of_library": ("whose", "each_player", REVEALED_TOP_CARDS_BY_SEAT),
    # "Counter target spell **or ability** … If a permanent's ability is
    # countered this way, destroy that permanent." (Teferi's Response.) The
    # union counter writes the record ``counter_stack_ability`` writes for
    # Interdict, and only the union can: a counter that names spells alone
    # refuses an ability outright, so declaring it flat would admit "that
    # permanent" behind Counterspell — a sentence that would compile clean and
    # destroy nothing.
    "counter_top_stack_spell": ("also_ability", True, COUNTERED_ABILITY_SOURCE),
    # "**Choose a source you control** and flip a coin." (Desperate Gambit.) The
    # same instruction Enchantment Alteration's host pick uses, sending its
    # answer somewhere else — and where it sends it is exactly what the
    # sentences behind it read. A row in ``_PRODUCES`` cannot say that: the
    # record is not a property of the kind, it is the payload's ``result_key``,
    # which is the one shape this table exists for.
    "choose_permanent": ("result_key", CHOSEN_DAMAGE_SOURCE, CHOSEN_DAMAGE_SOURCE),
    # "**Target opponent** chooses any number of creatures they control.
    # **During that player's next turn**, …" (Oracle en-Vec.) The plural pick
    # records *whom* it asked as well as what they chose, exactly as the
    # singular beside it has since Takklemaggot — and a row here rather than a
    # second entry in ``_PRODUCES`` because it is not true of every step of the
    # kind: inside "for each creature tapped this way, **that player**
    # chooses…" (Raiding Party) the seat comes from a per-object record and
    # changes every iteration, so nothing records one player.
    #
    # Keyed on the one chooser word the pool prints in front of a window —
    # ``"target"``, the announced seat. It under-declares by construction: the
    # handler writes the record for every seat it resolves outright, and
    # under-declaring is the safe direction here, because a gate that has not
    # been told about a record refuses the sentence rather than admitting one
    # that reads nothing.
    "choose_permanents": ("chooser", "target", CHOSEN_PLAYER),
    # Psychic Theft: the "and exile that card" ending only.
    "reveal_hand_and_choose": ("fate", "exile", "exiled_cards"),
}


#: Records a kind writes about **the one object** its step gave up, declared
#: only when none of the listed payload keys (another payer, another count) is
#: present. "Sacrifice a creature. Rupture deals damage equal to **that
#: creature's power** …": frozen as it is sacrificed (CR 608.2h), under the keys
#: the destroy step writes for Broken Visage, so one back-reference reader
#: answers both verbs. "Each player sacrifices a creature" names several
#: objects, so "that creature" behind it refuses rather than reading the last.
_PRODUCES_FOR_ONE_OBJECT: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "sacrifice_matching_permanent": (
        ("who", "count", "any_number", X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT,
         "amount_from", "amount_from_trigger"),
        (_EVENT_SUBJECT_POWER_RECORD, _EVENT_SUBJECT_TOUGHNESS_RECORD),
    ),
}


def produced_keys(instruction) -> frozenset[str]:
    """Every scratchpad value *instruction* records.

    Keyed by kind through :data:`_PRODUCES`, plus the one kind whose record
    depends on its payload (:data:`_PRODUCES_FOR_PAYLOAD`) — which is why this
    takes the instruction rather than the kind: "what does a step of this kind
    write" is not answerable for a search until you know where it was sending
    its find. :data:`_PRODUCES_FOR_ONE_OBJECT` is the same question asked of
    how *many* objects the step acts on.
    """
    single = _PRODUCES_FOR_ONE_OBJECT.get(instruction.kind)
    if single is not None:
        plural_keys, records = single
        if not any(key in (instruction.payload or {}) for key in plural_keys):
            return _produced_by_kind(instruction) | frozenset(records)
    return _produced_by_kind(instruction)


def _produced_by_kind(instruction) -> frozenset[str]:
    """:func:`produced_keys` without the single-object rows."""
    kind = instruction.kind
    recorded = _PRODUCES.get(kind)
    keys = (
        frozenset()
        if recorded is None
        else frozenset((recorded,) if isinstance(recorded, str) else recorded)
    )
    conditional = _PRODUCES_FOR_PAYLOAD.get(kind)
    if conditional is not None:
        payload_key, payload_value, record = conditional
        if (instruction.payload or {}).get(payload_key) == payload_value:
            keys = keys | {record}
    return keys


def primary_produced(kind: str) -> str | None:
    """The record "if you do" tests — the first of *kind*'s, or None."""
    recorded = _PRODUCES.get(kind)
    if recorded is None:
        return None
    return recorded if isinstance(recorded, str) else (recorded[0] if recorded else None)

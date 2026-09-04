"""What each instruction kind records in the resolution scratchpad.

One table, ``_PRODUCES``, and the two accessors that ask it. A *registry*
rather than logic, exactly as ``categories`` beside it is: a handler writes a
value and a later sentence of the same effect reads it back ("that much", "if
you do", "died this way"), and the only thing that can say the two agree is a
declaration both sides are held to.

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
"""

from __future__ import annotations

from .. import ast
from ..errors import LoweringError
from ...oracle_types import (CHOSEN_TARGET_PERMANENTS, CHOSEN_THIS_WAY_OBJECTS,
                             COUNTERED_SPELL_CONTROLLER, DREW_BY_SEAT,
                             COUNTERS_REMOVED, HAND_CARDS_TO_LIBRARY,
                             PER_OBJECT_SEAT_RECORDS,
                             TAPPED_THIS_WAY, TAPPED_THIS_WAY_OBJECTS)
from ._events import (ATTACHED_PERMANENT_CONTROLLER, CHOSEN_CAST_DAMAGE,
                      LAST_TARGET_CONTROLLER,
                      CHOSEN_PERMANENT, CHOSEN_PLAYER,
                      COUNTED_NUMBER, CREATED_TOKEN, DAMAGE_RECIPIENT,
                      EXILED_THIS_WAY, OTHER_CHOSEN_PERMANENT,
                      _EVENT_SUBJECT_POWER_RECORD,
                      _EVENT_SUBJECT_TOUGHNESS_RECORD,
                      _COUNTERS_PLACED_THIS_WAY,
                      _PERMANENTS_GIVEN_COUNTERS,
                      _REANIMATED_PERMANENTS)


_PRODUCES: dict[str, str | tuple[str, ...]] = {
    # Two records, because the sentence after a damage step may ask two
    # different questions about it. How much was dealt is the first and the
    # primary; who or what took it — and what it could absorb *before* the
    # damage — is the second, and the only place "…but not more life than the
    # player's life total before the damage was dealt" (Drain Life, Soul Burn)
    # has to read from. Reading the board instead would read the life total the
    # damage just changed, which is the number the words exclude.
    "deal_damage": ("damage_dealt", DAMAGE_RECIPIENT),
    # "This creature deals damage equal to its power to target creature.
    # **That creature** deals damage equal to its power to this creature."
    # (Tracker.) The bite records which permanent it chose, because that is the
    # only place the sentence after it can read the creature from: the ability
    # has one target and the second sentence names it without choosing again.
    "source_bites_target": "damaged_permanents",
    # "…chooses a creature that this card could enchant. **If the player does**,
    # return this card … **attached to that creature**." (Takklemaggot.) The
    # chosen permanent's id, which is both what the branch tests and what the
    # step behind it acts on — the choice is not a target, so nothing on the
    # board or on the stack records it.
    #
    # …and the **other** member of the set it was offered: "That player chooses
    # and sacrifices one of those creatures. Put a -1/-1 counter on **the
    # other**." (Retribution.) The pick is the only step holding both halves,
    # and by the sentence behind it the chosen one is in a graveyard — so a
    # read of the board would answer "whichever of the two is still there",
    # which is the right permanent only when nothing else went wrong.
    "choose_permanent": (CHOSEN_PERMANENT, OTHER_CHOSEN_PERMANENT),
    # "Count the number of permanents. **If the number** is odd, …" (Chaos
    # Moon.) The count is the whole of what the sentence does, and the only
    # place the two conditions behind it can read that number from — asking the
    # board again would be a second count, which is a different question the
    # moment anything between them changes it.
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
    # down.
    # …and **whose** spell it was: "Its controller may draw up to two cards at
    # the beginning of the next turn's upkeep." (Arcane Denial.) Two records for
    # one step, because the sentence behind a counter can ask two different
    # questions about the spell that is no longer there — how big it was, and
    # who cast it. The mana value stays primary: it is the one an "if you do"
    # would test, and it has been the primary since Mana Drain.
    "counter_top_stack_spell": (
        "countered_spell_mana_value", COUNTERED_SPELL_CONTROLLER,
    ),
    # "Destroy all nonblack creatures. … where X is the number of creatures
    # that **died this way**." (Hellfire.) A sweep records how many permanents
    # it actually destroyed, which is the only place a later clause can read
    # that set from — by then the board no longer holds it.
    # "…destroy the other creature at end of combat. At the beginning of the
    # next end step, **if that creature was destroyed this way**, …" (Infinite
    # Authority.) The delayed destroy records which creature it marked and which
    # one the trigger was about, because the sentence after it names both and by
    # then neither is anything the board can be asked for — the victim is in a
    # graveyard and the pair the trigger bound is long past.
    "delayed_destroy_blocked_or_blocker": "end_of_combat_destruction",
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
    "exile_all_matching": EXILED_THIS_WAY,
    # "…exile up to two target creature cards from defending player's
    # graveyard. If you do, you gain 1 life **for each card exiled this way**"
    # (Rysorian Badger). The same key the sweep above writes, because the
    # question the back-reference asks is the same one: how many did this step
    # exile? Written when the prompt is answered, which is why the offer's
    # ``then`` branch has to wait for it — the choice spec says ``suspends``.
    "exile_cards_from_graveyard": EXILED_THIS_WAY,
    # CR 705.2: only the player who flipped wins or loses that flip, and both
    # "if you win" and "if you lose" read the one result — so the flip records
    # it and the conditionals after it read the record, rather than each
    # sentence flipping a coin of its own.
    "flip_coin": "coin_flip",
    # "Target opponent puts the cards from their hand on top of their library.
    # Search that player's library for **that many** cards." (Jester's Mask.)
    # How many went is the only place the search behind it can read its count:
    # by then the hand is empty and the library has grown by an amount nothing
    # else records.
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
    # The per-seat form records the same thing, so a sentence reading "the
    # number of cards they discarded this way" has a producer to name.
    "each_player_discards_up_to_cards": "discarded_count",
    # "Each player may draw up to two cards. **For each card less than two a
    # player draws this way**, that player gains 2 life." (Truce.) The draw's
    # per-seat tally, written as each prompt is answered — the only place it
    # exists, since how many a seat drew is a decision it has not made when the
    # instruction returns. Per seat rather than a single number for
    # ``DISCARDED_BY_SEAT``'s reason: a shortfall is one answer per player, and
    # one key would let the last seat to answer decide everybody's life gain.
    "each_player_draws_up_to_cards": DREW_BY_SEAT,
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
    # (Winter's Chill.) The same shape one zone over: the choice records the set
    # it named, which is the only place the loop behind it can read it from —
    # nothing about a board says which attacking creatures a spell targeted, and
    # by the time the loop runs one of them may have left combat.
    # Two records, because "controlled by the same opponent" names a *player*
    # as well as a set: "**That player** chooses and sacrifices one of those
    # creatures" (Retribution) reads the seat, and this step is the only one
    # that can supply it — the relation is what makes the answer a single seat,
    # and the sacrifice behind it is about to empty one of the two slots. The
    # set is the primary, being what a step of this kind always records.
    "choose_target_permanents": (CHOSEN_TARGET_PERMANENTS, CHOSEN_PLAYER),
    # "Target player loses all poison counters. Leeches deals **that much**
    # damage to that player." The removal records how many actually came off,
    # which is the only place the sentence behind it can read the number: by
    # then the store holds zero, so a read of the board would deal none.
    "remove_all_counters_from_target_player": COUNTERS_REMOVED,
    # "Remove any number of +1/+1 counters … create **that many** … tokens"
    # (Tetravus). The removal records how many it took, under the key the token
    # maker's "that many" already reads.
    "remove_any_number_of_counters_from_self": "trigger_count",
    # "Exile any number of tokens created with this creature. If you do, put
    # **that many** +1/+1 counters on this creature." The same key, for the same
    # reason: the count is what the next sentence is about.
    "exile_any_number_of_own_tokens": "trigger_count",
    # The exile records whose permanent it removed, which is what "Its
    # controller creates a token" reads (Angelic Ascension, Secure the Scene).
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
    ),
    # "Create Stangg Twin, a … token. Exile **that token** when …" (Stangg).
    # The token maker records which permanent it made, which is the only place
    # a later sentence of the same effect can name it from — a token is a new
    # object with a fresh id (CR 400.7), so there is nothing about it to look
    # up by.
    "create_token": CREATED_TOKEN,
    # Both exiles record what they exiled, which is what "you may play cards
    # exiled this way" / "you may cast them this turn" read.
    "exile_top_of_library": "exiled_cards",
    # …and Ice Cauldron's hand exile, written when its prompt is answered.
    "exile_chosen_card_from_hand": "exiled_cards",
    "search_and_exile_matching": "exiled_cards",
    # "…until a creature card **or X cards have been put into their graveyard
    # this way**" (Helm of Obedience). The loop records the cards it put there
    # that its own stopping filter matched, which is what both sentences behind
    # it read: "if one or more creature cards were put into that graveyard this
    # way" asks whether the set is empty, and "put one of them onto the
    # battlefield" takes from it. Nothing else can answer either, because a
    # graveyard holds cards this effect never touched.
    "mill_until_matching": "milled_this_way",
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
    # count — CR 701.17b, and CR 608.2's "as much as possible" is exactly why
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
    "sacrifice_matching_permanent": ("sacrificed_this_way", "sacrificed_cards"),
    # "Tap up to two target creatures. **Those creatures** don't untap…"
    # (Frost Breath.) The tap records which permanents it affected, by id, and
    # the sentence after it reads that record rather than re-resolving the slots
    # — by then a target may have left, and CR 611.2c fixed the set when the
    # effect began.
    # "Target creature you control can't be blocked this turn. **Destroy it**
    # and this creature at end of combat." (Goblin Sappers.) The grant records
    # the creature it chose, so the delayed destroy behind it has a producer to
    # gate on — without one the pronoun would name the ability's own source and
    # the Sappers would destroy themselves twice.
    "grant_unblockable_to_target": "unblockable_permanents",
    # "Tap all untapped Islands that player controls and this enchantment deals
    # X damage to the player, **where X is the number of Islands tapped this
    # way**." (Monsoon.) How many the sweep turned, which is the only place the
    # clause behind it can read the number from — by then the board says how
    # many *are* tapped rather than how many this effect tapped. The count
    # alone: the victims are still on the battlefield, unlike a destruction
    # sweep's, so there is nothing about them a later sentence could not ask
    # the board for.
    # "Put a paralyzation counter on each creature blocking or blocked by this
    # creature and tap **those creatures**." (Dread Wight.) The placement is
    # the only step that can say which permanents the sentence is about: its
    # set is named by a combat relation, and the three sentences that read it
    # back run in the end-of-combat step, where the combat is on its way out
    # (CR 511.2). So the counters record their recipients by id, and the tap,
    # the untap restriction and the granted ability all read that record.
    "add_named_counter_to_creatures_in_combat_with_source": _PERMANENTS_GIVEN_COUNTERS,
    # "Distribute three +1/+1 counters among one, two, or three target
    # creatures. **For each +1/+1 counter you put on a creature this way,**
    # …" (Bounty of the Hunt.) The placement records one entry per counter,
    # which is what the sentence behind it counts — the division the caster
    # announced is on the stack item and says how many went where, and
    # nothing on the board afterwards can say which of a creature's counters
    # this spell put there.
    "add_counter_to_target": _COUNTERS_PLACED_THIS_WAY,
    # "Return target white or black creature card from your graveyard to the
    # battlefield. **That creature** gains "Cumulative upkeep {2}."" (Dreams of
    # the Dead.) The permanent did not exist when the ability was activated —
    # the ability's target is a *card* in a graveyard — so the reanimation is
    # the only step that can say which permanent the sentences behind it name.
    "reanimate_creature": _REANIMATED_PERMANENTS,
    # Two records, for the destroy family's reason: "…where X is the number of
    # Islands **tapped this way**" (Monsoon) asks how many the sweep turned, and
    # "**They** don't untap during their controller's next untap step" (Joven's
    # Ferrets) asks which permanents the printed noun phrase named. The count is
    # the primary — it is what a step of this kind has always written.
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
    # "…chooses up to two Plains. **Then destroy all Plains that weren't chosen
    # this way by any player.**" (Raiding Party.) What the pick named, so the
    # sweep behind it has a set to subtract. Written by every seat asked and
    # every iteration, into the one key — the sentence that reads it is one
    # question about all of the answers.
    "choose_permanents": CHOSEN_THIS_WAY_OBJECTS,
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
    # "Untap target attacking creature and remove **it** from combat. Gain
    # control of **that creature** until end of turn." (Disharmony.) The untap
    # records what it resolved — affected, not merely flipped: a vigilance
    # attacker that was never tapped is still "it" (CR 611.2c fixes the set
    # when the effect begins) — and both later sentences read the record.
    "untap_target_permanent": "untapped_permanents",
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
    # controller**." (Orcish Mine.) The victim's seat, read before the destroy:
    # the sentence behind this step names a player and the only place that
    # player exists by then is this record (CR 608.2h).
    "destroy_attached_permanent": ATTACHED_PERMANENT_CONTROLLER,
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
    # …and the victim's **controller**, which is the same record the exile row
    # above declares and was written here under a second name. "Destroy target
    # creature. **Its controller** creates a 1/1 white Spirit creature token"
    # (Afterlife) and "…**Its controller** reveals cards from the top of their
    # library" (Polymorph) are the exile's two riders printed behind a destroy,
    # and both refused for want of a producer that the handler had been writing
    # all along as ``last_target_controller_index``.
    "destroy_target_permanent": (
        "its_mana_value", "destroyed_target", "destroyed_this_way",
        _EVENT_SUBJECT_POWER_RECORD, _EVENT_SUBJECT_TOUGHNESS_RECORD,
        LAST_TARGET_CONTROLLER,
    ),
    # "Prevent the next 3 damage … **for each 1 damage prevented this way**."
    # (Sacred Boon.) The shield object itself, because what it prevents is
    # not a number when it is armed — the total goes on accumulating for the
    # rest of the turn, and the reader is a delayed ability at the end step.
    "grant_prevention_shield": "prevention_shield",
}


def produced_keys(kind: str) -> frozenset[str]:
    """Every scratchpad value *kind* records."""
    recorded = _PRODUCES.get(kind)
    if recorded is None:
        return frozenset()
    return frozenset((recorded,) if isinstance(recorded, str) else recorded)


def primary_produced(kind: str) -> str | None:
    """The record "if you do" tests — the first of *kind*'s, or None."""
    recorded = _PRODUCES.get(kind)
    if recorded is None:
        return None
    return recorded if isinstance(recorded, str) else (recorded[0] if recorded else None)


#: Which scratchpad key an activation **cost** writes when it is paid. The twin
#: of ``_PRODUCES`` for the cost side of a colon, and separate from it for the
#: same reason the two sides are separate: a cost is charged by
#: ``engine/mixins/stack/activation.py`` rather than by an instruction, so there
#: is no instruction kind to key it on. Land's Edge's "the discarded card" reads
#: the record this names; a cost added here needs the activation path to record
#: it under the same key, or the condition would compile and read nothing.
#:
#: Beside ``_PRODUCES`` because it is the same question about the other side of
#: the colon, and this module is the one home for "what does a step record?".
#: It sat in `lower.py` while that file was the only reader; the table is a
#: registry either way, and `lower.py` is dispatch.
#: The scratchpad key an untap cost writes. Named rather than spelled twice
#: because three files read it — the table below, the mana lowering's gate and
#: the activation path that writes it — and the failure a third spelling
#: produces is a gate that always refuses.
UNTAPPED_FOR_COST = "untapped_for_cost"

_COST_PRODUCES: dict[type, str] = {
    ast.DiscardCost: "discarded_cards",
    # "Sacrifice a creature: … **If the sacrificed creature was a Thrull**, …"
    # (Ebon Praetor.) The activation path records the permanent the cost ate
    # under ``sacrificed_for_cost``, and the cast path records the same key
    # for an additional cost (``engine/mixins/stack/casting.py``).
    #
    # **Nothing gates on this row today, and that is the honest state rather
    # than an oversight.** ``CostObjectWas`` reads both this channel and the
    # exile one, and it cannot use ``produced``: for a *spell* the cost is a
    # different printed line of the card, which the clause being lowered
    # cannot see, so the gate would refuse Soul Exchange outright. The row
    # stays because it states what the payment path writes, and the reader
    # that would use it is named: ``SacrificedForCost`` (the *amount* — Life
    # Chisel, Diamond Valley) has no check that its ability sacrifices
    # anything at all, and threading ``produced`` into that branch is what
    # this row is for.
    ast.SacrificeCost: "sacrificed_for_cost",
    # "{T}, **Untap a tapped land an opponent controls**: Add one mana of any
    # type **that land** could produce." (Benthic Explorers.) The land the cost
    # untapped, recorded by the activation path so the effect's back-reference
    # has something to name — and, unlike the two rows above, this row really is
    # a gate: the phrase is only meaningful on an ability whose own cost untaps
    # something, and `_lower_add_mana` refuses it without this key.
    ast.UntapPermanentCost: UNTAPPED_FOR_COST,
}


def names_the_shielded_object(subject) -> bool:
    """Whether *subject* names the object an earlier step of the effect shielded.

    "…put a +0/+1 counter on **that creature**" (Sacred Boon) and "…on **it**"
    (Scars of the Veteran) are one referent with two spellings: the only object
    either sentence has named. A bare pronoun arrives as the ability's own
    source, because that is what ``parse_recipient`` reads it as with nothing
    else in the sentence to name — and a spell is not a permanent, so read
    literally it would place a counter on nothing.

    A floor beside :func:`counts_prevented_damage` and for its reason: what the
    pronoun means has to be one answer, and the branch that reads the shield
    record is not the only one that looks at the subject.

    The whole subject test, narrowing included. "That **creature**" states the
    card type and the pronoun states nothing, and neither is a further
    restriction the handler could honour — it addresses the object by the id the
    shield step recorded. Any *other* field is one the sentence added and this
    reading would drop, so it refuses.
    """
    from .. import ast
    from ._common import _restrictions_beyond

    if not isinstance(subject, ast.TargetSpec):
        return False
    if _restrictions_beyond(subject.filter, frozenset({"card_types", "is_source"})):
        return False
    if subject.quantifier == "that":
        return True
    return subject.quantifier == "it" and subject.filter.is_source


def counts_prevented_damage(node) -> bool:
    """Whether a placement's count is "for each 1 damage prevented this way".

    (Sacred Boon, Scars of the Veteran.) A floor rather than a test written into
    the counter lowering, because **two** branches of that module have to agree
    about it: the branch that places a counter on the ability's own source must
    decline this count, and the branch that reads the shield record must claim
    it. Written twice they would eventually disagree, and the direction that
    fails is silent — the source branch claims the sentence first and refuses
    it, which reads as a card the grammar cannot parse.
    """
    from .. import ast
    from .counters import PREVENTION_SHIELD_RECORD

    count = getattr(node, "count", None)
    return (
        isinstance(count, ast.ThatMuch)
        and count.source == PREVENTION_SHIELD_RECORD
    )


def optional_cost_key(symbols: str) -> str:
    """The canonical spelling a CR 601.2b optional additional cost is recorded
    and read back under.

    Here rather than in either family that needs it — ``loops`` lowers "for each
    additional {1}{R} you paid" and ``game`` lowers "plus an additional 3 life
    for each …" — because a fragment two families need cannot live in one of
    them. And here rather than in ``_common`` because it is the same question
    this module already answers: what a step wrote down and how a later sentence
    names it. The step in this case is the *cast* (CR 601.2b), and the record is
    on the stack item's choices rather than in the resolution scratchpad,
    because the mana pool that paid the cost empties at the end of that step
    (CR 500.4).

    Through the same two functions ``cast_costs`` spells its offers with
    (``mana_cost_from_symbols`` then ``mana_cost_label``), so the sentence that
    spends the count and the payment that made it name the offer identically
    however the card printed it. Two readers would be two answers, and the quiet
    one is a loop that never runs.

    Raises when the printed run holds a symbol no payment can spend ({X}, a
    hybrid): the same refusal ``cast_costs`` makes of the offer itself, so a
    sentence cannot read back a cost that side declined to charge.
    """
    from ...mana_payment import mana_cost_from_symbols, mana_cost_label

    parsed = mana_cost_from_symbols(symbols)
    if not parsed:
        raise LoweringError(
            f"no payment spends {symbols!r}, so nothing records paying it"
        )
    return mana_cost_label(parsed)

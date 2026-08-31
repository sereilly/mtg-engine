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

from ...oracle_types import HAND_CARDS_TO_LIBRARY, PER_OBJECT_SEAT_RECORDS
from ._events import (CHOSEN_CAST_DAMAGE, CHOSEN_PERMANENT, CHOSEN_PLAYER,
                      CREATED_TOKEN, EXILED_THIS_WAY,
                      _PERMANENTS_GIVEN_COUNTERS, _REANIMATED_PERMANENTS)


_PRODUCES: dict[str, str | tuple[str, ...]] = {
    "deal_damage": "damage_dealt",
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
    "choose_permanent": CHOSEN_PERMANENT,
    # "Choose a player who cast one or more sorcery spells this turn.
    # Backdraft deals damage to **that player** …" The seat is the whole of what
    # the first sentence does, and the only place the second can read it: a
    # chosen player is not a target and nothing on a board records the choice.
    "choose_player_who_cast": CHOSEN_PLAYER,
    # "…equal to half the damage dealt by **one of those** sorcery spells this
    # turn." The pick records what the chosen cast dealt, because by the time
    # this is asked the spell has resolved and left the stack — the ledger is
    # the record, and this is which row of it the player named.
    "choose_cast_this_turn": CHOSEN_CAST_DAMAGE,
    # "Counter target spell. … an amount of {C} equal to **that spell's** mana
    # value." (Mana Drain.) The countered spell's mana value — the one thing
    # about it that survives the counter, and only because the counter wrote it
    # down.
    "counter_top_stack_spell": "countered_spell_mana_value",
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
    # "Choose two cards in your hand … **For each of those cards**, …"
    # (Sylvan Library.) The pick records what it chose, which is the only
    # place the next sentence can read that set from: nothing about a hand
    # says which of its cards an earlier step named.
    "choose_cards_in_hand": "chosen_hand_cards",
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
    "exile_target_permanent": "exiled_permanent_controller",
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
    "sacrifice_matching_permanent": "sacrificed_this_way",
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
    # "Return target white or black creature card from your graveyard to the
    # battlefield. **That creature** gains "Cumulative upkeep {2}."" (Dreams of
    # the Dead.) The permanent did not exist when the ability was activated —
    # the ability's target is a *card* in a graveyard — so the reanimation is
    # the only step that can say which permanent the sentences behind it name.
    "reanimate_creature": _REANIMATED_PERMANENTS,
    "tap_all_matching": "tapped_this_way",
    "tap_target_permanent": "tapped_permanents",
    # "…tap the creature, **remove it** from combat" (Imprison). The Aura's tap
    # names its own attachment rather than a target, so it is a different
    # producer of the same record — what this effect just tapped.
    "tap_enchanted_creature": "tapped_permanents",
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
    "destroy_target_permanent": ("its_mana_value", "destroyed_target"),
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

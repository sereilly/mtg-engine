from __future__ import annotations

import dataclasses
import random

from ..auras import AURA_ANY_COLOR_MANA, aura_additional_mana_on_tap
from ..delayed_triggers import matching_delayed_triggers
from ..keywords import abilities_lost_at
from ..cast_permissions import expire_at_turn_start as expire_turn_permissions
from ..hand_locks import expire_hand_locks
from ..land_mana_swaps import (production_snapshot, source_wide_swap,
                               substitute_production)
from ..mana_payment import answer_color_choices
from ..land_play_allowance import clear_turn_land_play_effects
from ..spell_prohibitions import clear_turn_spell_prohibitions
from ..game_types import OracleExecutionContext, SimulationResult
from ..oracle import compile_card_oracle
from ..replacements import apply_replacements
from ..trigger_utils import iter_triggered_abilities
from ._constants import phases_after


#: Every instruction kind ``_resolve_tapped_land_trigger_step`` has an arm for.
#:
#: Beside the dispatch rather than in the test that checks it. The guard used to
#: keep its own list, which is the second-copy class SET_PLAYBOOK.md's promotion
#: step calls the most expensive kind of guard — this one went stale the moment
#: the site learned Storm Cauldron's return and Winter's Night's untap marker,
#: and then reported two working cards as undispatched at the promotion gate.
#: The arms read it as their own precondition, so a kind added to one and not
#: the other is inert rather than silently mis-run, and the card's own test says
#: so.
TAP_TRIGGER_KINDS = frozenset({
    "add_mana_for_tapped_land",   # Mana Flare, Gauntlet of Might
    "return_tapped_land_to_hand", # Storm Cauldron
    "skip_next_untap",            # Winter's Night
    "deal_damage",                # Manabarbs
    "tap_lands_sharing_produced_mana",  # Mana Web
    # "…**you may gain 1 life**." (Sanctimony.) An *optional* effect under this
    # condition, which every kind above it is not — and the first one whose
    # answer belongs to a player rather than to this site.
    #
    # It reaches the ordinary dispatcher rather than an arm of its own, and that
    # is the point: `may` arms a prompt on the generic pending-choice queue,
    # which is the machinery built for a decision owed part-way through
    # something. What this site cannot give a trigger is a *priority window*;
    # a queued question needs none, so the reason the docstring below gives for
    # refusing control flow ("no priority window to run its branches") is a
    # reason about `if_then`'s branches and not about an offer.
    #
    # Without it, Sanctimony parsed, lowered, was announced by this very loop
    # and then gained nothing at all — the exact shape
    # `tests/engine/test_trigger_dispatchers.py` cannot see, because the
    # condition *is* dispatched and it is the effect that falls off the end.
    "may",
    "target_gains_life",
    # "Whenever you tap a land for mana, **remove a +1/+1 counter from this
    # creature**." (Savage Firecat.) "…if it's not that player's turn,
    # **destroy that land**." (Price of Glory.) Two more effects that are not
    # mana abilities, run through the ordinary dispatcher like the two above
    # them, with the event's seat and the event's land stamped in the context.
    "remove_counter_from_self",
    "destroy_event_subject",
})

#: The kinds above that reach ``EFFECT_HANDLERS`` through the engine's own
#: dispatcher rather than through an arm written out at the fire site.
_TAP_TRIGGER_HANDLER_KINDS = frozenset({
    "may", "target_gains_life", "remove_counter_from_self",
    "destroy_event_subject",
})


def _tap_trigger_steps(instruction) -> tuple:
    """A tap-for-mana trigger's effect as the clauses that make it up.

    One sentence is one instruction; two sentences are a ``sequence`` whose
    steps are those instructions (Winter's Night). Flattened one level only,
    because that is the shape the compiler produces for a printed paragraph —
    a deeper nesting is a control-flow instruction (`may`, `if_then`) whose
    branches this inline site has no priority window to run, and the arms below
    report it rather than guessing.
    """
    if instruction.kind == "sequence":
        return tuple(instruction.payload.get("steps") or ())
    return (instruction,)

def _is_free_beyond_tapping(cost) -> bool:
    """Whether *cost* is the tap symbol and nothing else.

    Compared against a default cost rather than by listing the fields that must
    be empty. A list would silently start ignoring any cost component added
    later — and ignoring a cost component here means performing an ability
    without paying for it, which is the one direction this check exists to
    prevent.
    """
    empty_mana = {symbol: 0 for symbol in cost.mana}
    return cost == dataclasses.replace(
        type(cost)(mana=empty_mana), requires_tap=True
    )


def _mana_made_since(player, before: dict) -> dict[str, int]:
    """What *player*'s pool gained since *before* (a
    ``land_mana_swaps.production_snapshot``), per symbol and summed across
    every bucket — the open pool and each CR 106.6 "spend this mana only…"
    bucket beside it, because restricted mana is still mana a land produced.

    The answer to two questions the tap-for-mana event asks of a production it
    did not perform itself: *did this make mana at all* (CR 106.12a) and
    *which type* (Mana Flare's "any type that land produced"). Insertion order
    is the pool's own symbol order, so "the first type it made" is stable.
    """
    made: dict[str, int] = {}
    buckets = [(None, player.mana_pool)]
    buckets.extend((getattr(player, "restricted_mana", None) or {}).items())
    for key, bucket in buckets:
        prior = before.get(key, {})
        for symbol, amount in bucket.items():
            gained = int(amount or 0) - int(prior.get(symbol, 0) or 0)
            if gained > 0:
                made[symbol] = made.get(symbol, 0) + gained
    return made
#: The six types of mana a tap can be asked for (CR 106.1b).
_TAPPABLE_SYMBOLS = frozenset({"W", "U", "B", "R", "G", "C"})


def is_tap_alone_mana_ability(ability) -> bool:
    """Whether *ability* is one the tap-for-mana seam may run: a supported mana
    ability (CR 605.1a; an ``if_then`` "…add {C}{C} instead" too) whose whole
    cost is {T} (CR 106.12's "tap for mana").

    One predicate for the three readers that ask it — the seam's own walk, the
    seam taking an ability the player chose by index, and the web route that
    decides which of the engine's two entry points a land click goes to. Those
    answering separately is how the route kept a three-kind set of its own
    while the seam asked CR 605.1a, and a land's coloured second ability went
    down the path that skips every swap and trigger the seam announces.
    """
    from ..activation_restrictions import prints_activation_restriction
    from ..mana_payment import carries_an_offer, is_mana_ability

    instruction = getattr(ability, "instruction", None)
    if instruction is None or not getattr(ability, "supported", False):
        return False
    if not (is_mana_ability(ability) or instruction.kind == "if_then"):
        return False
    cost = ability.cost
    if not (bool(cost.requires_tap) and _is_free_beyond_tapping(cost)):
        return False
    # **And nothing the seam cannot honour from inside a payment.** The seam is
    # reached part-way through paying a cost (CR 601.2g), with nobody holding
    # priority, and it asks no CR 602.5 gate — so a printed "Activate only …"
    # clause would go unenforced there; "only as an instant" is CR 304.5's
    # "the player must have priority". And an ability that asks another player
    # something has no mana to give until they answer. "{T}: Choose a color.
    # Add one mana of that color unless any player pays {1}. Activate only as
    # an instant." (Rhystic Cave) is both. Such an ability is the activation
    # path's, which gates it and runs it inline all the same (CR 605.3b); the
    # seam reports it priced, which is the answer it already refuses.
    return not (
        prints_activation_restriction(getattr(ability, "source_line", "") or "")
        or carries_an_offer(instruction)
    )


#: The tap refusals `tap_land_for_mana` logs, by the reason key
#: `land_mana_tap_refusal` returns, as the suffix after the land's name.
_LOGGED_TAP_REFUSALS = {
    "summoning_sick": " has summoning sickness",
    "activations_forbidden": "'s activated abilities can't be activated this turn",
}


class TurnManagementMixin:
    def select_starting_player(
        self, rng: random.Random | None = None
    ) -> int:
        """Rule 103.1: Simulate a coin flip to choose who takes the first turn.

        *rng* – optional seeded :class:`random.Random` instance.  Pass one to
        make the flip deterministic (e.g. derived from a session seed).  Omit
        to use the module-level global RNG.

        Returns the index of the player who wins the flip and chooses to go
        first.  In this simulator the flip winner always chooses themselves.
        """
        source: random.Random = rng if rng is not None else random  # type: ignore[assignment]
        winner = source.randrange(len(self.players))
        self.log.append(
            f"Coin flip: {self.players[winner].name} wins and chooses to go first"
        )
        return winner

    def deal_opening_hands(self, starting_player_index: int) -> None:
        """Rule 103.5: Shuffle each player's library and draw opening hands of 7 cards.

        Hands are dealt starting with *starting_player_index* and proceeding
        in turn order.

        CR 407.2 slots in between the two: when the game is played for ante,
        each player antes one random card from their (already shuffled) deck
        "after determining which player goes first but before players draw any
        cards", so every library is shuffled first, the ante is seeded, and
        only then are hands dealt.

        CR 903.6 comes *first* in a Commander game: each player puts their
        commander into the command zone and "then each player shuffles the
        remaining cards of their deck". Doing it before the shuffle rather than
        after is what makes a commander unreachable by 903.7's draw, and it is
        also where 903.7's 40 (or Brawl's 25/30) life total is set.
        """
        order = list(range(starting_player_index, len(self.players))) + list(
            range(0, starting_player_index)
        )
        self.begin_commander_game()
        for i in order:
            random.shuffle(self.players[i].library)
        # CR 903.11a asks what a player's *starting deck* held, so it is
        # recorded once the libraries are final and before anything moves.
        self.record_starting_decks()
        self.place_starting_ante(order)
        for i in order:
            player = self.players[i]
            # CR 103.5's opening hand, and one of the three draws that stay off
            # the replacement seam by rule rather than by oversight: the game has
            # not begun, so there is no permanent on any battlefield for a
            # CR 614 replacement to come from. `tests/engine/test_draw_seam.py`
            # names these three and why.
            drawn = player.draw(7)
            self.log.append(f"{player.name} drew opening hand of {drawn} card(s)")

    def mulligan_effective_count(self, player_index: int) -> int:
        """CR 800.6/103.5c: in a multiplayer game (3+ players), a player's FIRST
        mulligan doesn't count toward the number of cards they'll put on the
        bottom of their library or toward the 7-mulligan limit; every mulligan
        after that counts normally. In a 2-player game this is just the raw
        ``mulligans_taken`` count (no discount, matching 103.5's base rule).

        CR 903.12g gives the same free first mulligan to **any** Brawl game,
        two-player included — which is the only thing that separates a
        two-player Brawl's mulligans from a two-player Commander game's. The two
        discounts do not stack: 903.12g and 103.5c describe the same one
        mulligan, so a multiplayer Brawl still discounts exactly one."""
        from ..commander import free_first_mulligan

        player = self.players[player_index]
        free = len(self.players) >= 3 or free_first_mulligan(
            getattr(self, "commander_variant", None)
        )
        return max(0, player.mulligans_taken - (1 if free else 0))

    def take_mulligan(
        self,
        player_index: int,
        bottom_card_indices: list[int] | None = None,
    ) -> bool:
        """Rule 103.5: Player takes a mulligan.

        The player shuffles their hand into their library, draws 7 cards, then
        puts a number of cards equal to their new mulligan count on the bottom
        of their library (CR 800.6: one fewer in multiplayer, since the first
        mulligan there is free).

        *bottom_card_indices* – indices into the freshly drawn hand of the
        cards to place on the bottom.  Defaults to the last N cards drawn.

        Returns True if the mulligan was taken, False if the player cannot
        take further mulligans (they already have 0 cards).
        """
        player = self.players[player_index]
        if self.mulligan_effective_count(player_index) >= 7:
            self.log.append(
                f"{player.name} cannot take further mulligans (hand would be 0 cards)"
            )
            return False

        # Shuffle hand back into library.
        player.library.extend(player.hand)
        player.hand.clear()
        random.shuffle(player.library)

        player.mulligans_taken += 1
        n = self.mulligan_effective_count(player_index)

        # Draw a new hand of starting hand size (7).
        player.draw(7)

        # Put n cards on the bottom.
        if bottom_card_indices is None:
            cards_to_bottom = [player.hand.pop() for _ in range(min(n, len(player.hand)))]
        else:
            indices_sorted = sorted(set(bottom_card_indices), reverse=True)
            cards_to_bottom = [player.hand.pop(i) for i in indices_sorted]

        player.library.extend(cards_to_bottom)

        self.log.append(
            f"{player.name} took mulligan #{player.mulligans_taken}, drew 7, put {len(cards_to_bottom)}"
            f" card(s) on the bottom, keeping {len(player.hand)}"
        )
        return True

    def keep_hand(self, player_index: int) -> None:
        """Rule 103.5: Player declares to keep their current hand.

        The hand was drawn before the game's first turn (CR 103.5), and so were
        any mulligan redraws — none of them is a card drawn *this turn*, but
        every one of them went through ``PlayerState.draw`` and onto the
        per-turn record. The headless ``start_turn`` resets that record; the
        web layer's pregame starts turn 1 without it, so a "whenever you draw a
        card" permanent put onto the battlefield on turn 1 (Tolarian Kraken)
        announced the whole opening hand. Keeping is the last pregame step a
        seat takes, so it is where the record is wiped — together with the
        sweep memories that compare against it, or a check that ran during the
        pregame would leave them ahead of an empty record and swallow the first
        real draws of the turn.
        """
        player = self.players[player_index]
        player.cards_drawn_this_turn = []
        self.draws_announced_this_turn.pop(player_index, None)
        self.second_draw_fired_this_turn.discard(player_index)
        suffix = (
            f" ({player.mulligans_taken} mulligan(s) taken)"
            if player.mulligans_taken > 0
            else ""
        )
        self.log.append(
            f"{player.name} keeps opening hand of {len(player.hand)} card(s){suffix}"
        )

    def pregame_mulligan_draw(self, player_index: int) -> bool:
        """Pregame mulligan: shuffle hand back into library and draw 7 fresh cards.

        Bottom selection is deferred until the player keeps (web pregame flow only).
        Returns False if the player cannot take another mulligan (already at 7).
        """
        player = self.players[player_index]
        if self.mulligan_effective_count(player_index) >= 7:
            return False
        player.library.extend(player.hand)
        player.hand.clear()
        random.shuffle(player.library)
        player.mulligans_taken += 1
        player.draw(7)
        self.log.append(
            f"{player.name} took mulligan #{player.mulligans_taken}, redrew 7 cards"
        )
        return True

    def begin_turn_bookkeeping(self, player_index: int) -> None:
        """Per-turn state resets that must run whenever a new turn begins —
        both the headless ``start_turn`` flow and the web layer's step-by-step
        turn flow. Missing these leaves stale "this turn" counters (e.g.
        Scavenging Ghoul's end-step trigger firing on last turn's deaths)."""
        # The turn that is ending belonged to whoever is still recorded as
        # active, and this boundary is the one moment its per-turn records are
        # both complete and still readable — so the "during their last turn"
        # facts Arboria asks about (CR 506.3) are folded here, before anything
        # below resets them. Only the outgoing seat's own records fold: a spell
        # another player cast during this turn was not cast during *their* own
        # turn, and their fold happened when their own turn ended. No fold
        # before the first turn of the game — there is no last turn to
        # describe, and an absent entry reads as "did neither".
        if self.seat_turn_counts:
            prev_seat = self.active_player_index
            if 0 <= prev_seat < len(self.players):
                self.last_own_turn_activity[prev_seat] = bool(
                    self.players[prev_seat].spells_cast_this_turn
                ) or self.nontoken_permanents_entered_this_turn.get(prev_seat, 0) > 0
        self.nontoken_permanents_entered_this_turn = {}
        # The turn's phase plan (CR 500.1's five phases, in order), reset here
        # because this is the one hook both drivers call as a turn begins - the
        # headless ``start_turn`` and the web layer's ``_begin_turn``. The
        # beginning phase is the one now starting, so what is left is everything
        # behind it; CR 500.8's extras are inserted into this list as they are
        # created and spent as each phase is entered.
        self.turn_phases_remaining = phases_after("beginning")
        # The new turn's per-seat ordinal — what "your last turn" (Giant
        # Turtle) and "its controller's next turn" (Wall of Dust) compare
        # against. A skipped turn (Time Vault) still increments: the skip is
        # decided after the turn has begun, and the ordinal records beginnings.
        self.seat_turn_counts[player_index] = self.seat_turn_counts.get(player_index, 0) + 1
        self.active_player_index = player_index
        self.lands_played_this_turn[player_index] = 0
        # "…this turn" (Summer Bloom, Solfatara). Both records are about the
        # turn that has just ended, so they go here beside the count they
        # modify rather than in a sweep of their own — a prohibition that
        # outlived its turn is a seat that quietly stops playing lands.
        clear_turn_land_play_effects(self)
        # "**Until end of turn**, target player can't cast instant or sorcery
        # spells…" (Abeyance.) The same boundary and the same reason as the
        # land-play records above it: a prohibition that outlived its turn is a
        # seat that quietly stops casting.
        clear_turn_spell_prohibitions(self)
        # "Until that player's next turn" (Firestorm Phoenix) is an ordinal
        # against the counter just incremented, so this drops what has expired
        # rather than deciding anything — engine/hand_locks.py derives the
        # answer either way.
        expire_hand_locks(self)
        # "**Until your next turn**, you may play those cards." (Three Wishes.)
        # CR 800.4m: the duration ends when that player's turn would have begun,
        # which is here — beside the hand locks, whose printed duration is the
        # same words and whose sweep is the same boundary for the same reason.
        expire_turn_permissions(self, player_index)
        self.creatures_died_this_turn = 0
        self.destroyed_at_end_of_combat_this_turn = []
        self.nontoken_creatures_died_this_turn = 0
        self.permanents_to_hand_this_turn = {}
        # Aladdin's Lamp: an armed "next draw this turn" replacement expires
        # with the turn it was activated on.
        self.lamp_draw_replacements = {}
        # "…this turn" (Mangara's Tome), cleared here beside the two armings it
        # generalises rather than expiring by comparing turn numbers at the
        # draw: one sweep, and nothing left behind to be matched by accident.
        self.armed_draw_replacements = []
        # Ring of Ma'rûf's armed replacement likewise lasts only "this turn".
        self.outside_game_draw_replacements = set()
        # The second-draw sweep's once-per-turn memory (Mystic Skyfish), and the
        # per-draw sweep's (Lorescale Coatl). Both read
        # ``cards_drawn_this_turn``, which is emptied in the loop below, so both
        # have to forget in the same breath — a memory that outlived the record
        # would announce every card of the new turn's first draw all over again.
        self.second_draw_fired_this_turn = set()
        self.draws_announced_this_turn = {}
        # The turn's damage-and-cast record (engine/damage_ledger.py). Cleared
        # here beside `spells_cast_this_turn` below, because it is the same
        # "this turn": Blazing Effigy's "damage dealt to this creature this
        # turn" and Backdraft's "one of those sorcery spells this turn" are one
        # window, and a record outliving it would read last turn's board.
        self.damage_ledger.clear()
        for player in self.players:
            player.damage_taken_this_turn = 0
            player.artifact_damage_taken_this_turn = 0
            player.cards_drawn_this_turn = []
            # "This turn" is *the turn*, not the player's turn: lifelink on an
            # opponent's turn is life you gained this turn, and it stops being
            # so when the next turn begins. Every seat resets here, which is why
            # this loop is over self.players rather than the active one.
            player.life_gained_this_turn = 0
            player.noncombat_damage_dealt_to_opponents_this_turn = 0
            player.creatures_died_under_your_control_this_turn = 0
            player.creatures_put_into_your_graveyard_this_turn = 0
            player.cards_put_into_your_graveyard_from_battlefield_this_turn = []
            player.exile_cards_bound_for_graveyard_this_turn = False
            player.spells_cast_this_turn = []
            player.attacked_this_turn = False
            # Desolation's window is the turn, exactly as the attack record
            # above is, so the two forget in the same breath.
            player.tapped_land_for_mana_this_turn = False
        # A static ability whose condition is *whose turn it is* changes truth
        # value here and nowhere else (CR 611.3a: the effect is not locked in;
        # it applies at any given moment to whatever its text indicates).
        # "During your turn, creatures you control get +2/+0" (Vibrating
        # Sphere), "During your turn, Radha has first strike" and Angry Mob's
        # swamp-scaled P/T all reach the board through channels
        # `_recalculate_lord_buffs` / `_refresh_dynamic_creatures` clear and
        # rebuild — a *snapshot*, and every other recompute is driven by a board
        # change, which a turn passing is not.
        #
        # **What this actually buys**, stated precisely because the obvious
        # reading is too strong: the untap step recomputes too, so the headless
        # `start_turn` flow was already right by the time anyone had priority.
        # What was stale is the window *between* this bookkeeping and that
        # recompute — and `web/turn_steps._begin_turn` returns to the client
        # inside it, three ways: Time Vault's skip prompt, Winter Orb's
        # untap-land selection and Old Man of the Sea's keep-tapped choice. A
        # player answering any of those saw last turn's P/T and keywords.
        self._recalculate_lord_buffs()
        self._refresh_dynamic_creatures()

    def start_turn(self, player_index: int) -> None:
        self.begin_turn_bookkeeping(player_index)
        self.resolve_untap_step(player_index)
        self.resolve_upkeep(player_index)
        self.resolve_draw_step(player_index)
        # The phase after the beginning phase, asked of the turn's plan rather
        # than named here (CR 500.1). With nothing added that is the precombat
        # main phase, exactly as this line used to say outright.
        self.enter_next_turn_phase("beginning")

    def start_next_turn(self) -> int:
        self.turn += 1
        next_player = self._compute_next_active_player()
        self.start_turn(next_player)
        return next_player

    def use_channel_mana(self, player_index: int, amount: int) -> SimulationResult:
        """Pay `amount` life via an active Channel effect to add that many {C} mana."""
        player = self.players[player_index]
        if not player.channel_active_until_eot:
            return SimulationResult("Channel", False, "spell_pattern", "Channel is not active")
        if amount <= 0:
            return SimulationResult("Channel", False, "spell_pattern", "Amount must be positive")
        if amount > player.life:
            # CR 118.3: a player can pay any amount of life up to their total,
            # including all of it, but no more.
            return SimulationResult(
                "Channel", False, "spell_pattern",
                f"cannot pay {amount} life with only {player.life} remaining",
            )
        player.life -= amount
        player.mana_pool["C"] = player.mana_pool.get("C", 0) + amount
        self.log.append(f"{player.name} paid {amount} life via Channel for {amount} {{C}}")
        # Paying down to 0 is legal; the player then loses to SBAs (704.5a).
        self.check_state_based_actions()
        return SimulationResult("Channel", True, "spell_pattern", f"added {amount} C")

    @staticmethod
    def _land_mana_abilities(land):
        """``(free_instruction, priced)`` for the land's own mana abilities.

        The first is the instruction an ability whose cost is **the tap alone**
        produces -- what this entry point may run, having already tapped the
        land and charging nothing further. The second says whether the land has
        a mana ability the tap does *not* pay for.

        Both, from one walk, because the caller needs them together and the
        difference decides opposite answers. A land with neither is a basic or a
        Bazaar of Baghdad and falls through to the ``produced_mana`` summary; a
        land with the second and not the first must be **refused**, because that
        summary is Scryfall's list of symbols the land can make and says nothing
        at all about what they cost.

        **A land whose type an effect set has neither of its own** (CR 305.7):
        it "loses all abilities generated from its rules text … and gains the
        appropriate mana ability for each new basic land type", which is the
        summary path. ``land_types.lost_abilities_to_type_change`` named three
        readers — layer 6, the activation gate, the trigger scan — and this
        was the fourth that did not ask: a Karplusan Forest under Blood Moon
        tapped for its printed {C} through this seam while the activation path
        refused the very same ability, and a Mishra's Workshop still made
        {C}{C}{C}. It no longer asks either, because the walk below is over
        the land's *effective* card, which is the land with its own text
        struck — and what is left in it is what the rule keeps: a mana ability
        another effect **granted** the land ("Lands you control have '{T}: Add
        two mana of any one color.'", Overlaid Terrain), which the arm that
        stood here returned in front of.
        """
        from ..mana_payment import is_mana_ability, land_text_is_run

        if not land_text_is_run(land):
            # A land none of whose text compiles (Rhystic Cave, until PCY
            # W3G1): the summary below would be its whole reading — free mana
            # with every cost and condition taken out. Reported as priced,
            # which is the answer the tap seam refuses.
            return None, True
        priced = False
        for ability in compile_card_oracle(land.effective_card).activated_abilities:
            instruction = ability.instruction
            if instruction is None or not ability.supported:
                continue
            if not (is_mana_ability(ability) or instruction.kind == "if_then"):
                continue
            if is_tap_alone_mana_ability(ability):
                return instruction, priced
            priced = True
        return None, priced

    def _chosen_land_mana_ability(self, land, ability_index: int):
        """The instruction of the mana ability *ability_index* names on *land*,
        or None when that ability is not one this seam may run.

        CR 605: each mana ability is a separate ability its controller chooses
        to activate, and the index is the one the activation path and the wire
        already address a permanent's abilities by
        (``targeting.usable_activated_abilities`` over the playable card). So a
        Karplusan Forest's coloured second ability, or the "{T}: Add two mana
        of any one color" Overlaid Terrain grants it, is reachable through the
        seam rather than always losing to the land's own first ability.

        Only a tap-alone mana ability: anything costing more is the activation
        path's to pay (CR 602.2b), which this seam refuses by design.
        """
        usable = self.usable_abilities_of(land)
        if not 0 <= ability_index < len(usable):
            return None
        chosen = usable[ability_index]
        return chosen.instruction if is_tap_alone_mana_ability(chosen) else None

    def land_mana_ability_for(self, land, color: str) -> int | None:
        """Which of *land*'s mana abilities makes *color* — an index for
        ``tap_land_for_mana(ability_index=…)`` — or None for the seam's default.

        CR 605: each mana ability is its own ability, and the tap seam runs the
        land's **first** tap-alone one unless told which. For a painland that
        is "{T}: Add {C}", so a payer that counted a Karplusan Forest or an
        Underground River as a coloured mana and tapped it by colour alone got
        {C}. None whenever the default already makes the colour (a basic, a
        dual, City of Brass, a land under a swap the seam applies to any
        ability), so every land that taps correctly by default taps exactly
        as it did.

        On the game rather than in the AI's policy, where it was written
        (``ai_policy.planned_tap_ability`` asks here now): the engine's own
        payer — a cost an effect collects, ``_pay_planned_cost`` — taps lands
        for a colour a plan counted on exactly as an AI seat does, and two
        readers choosing an ability two ways is a land that pays for one
        player and not for the other.
        """
        from ..ai_valuation import mana_ability_symbols
        from ..land_mana_swaps import swapped_production

        free, _priced = self._land_mana_abilities(land)
        if free is None or color in mana_ability_symbols(free):
            return None
        # …nor where a land type the land **gained** makes it (CR 305.6:
        # "{T}: Add {B}" for a Swamp it was made): that is the seam's own arm,
        # which runs when no ability is named.
        if color in self._gained_type_mana(land):
            return None
        # **A land under a swap makes the swapped symbol by any of its
        # abilities** ("If a land is tapped for mana, it produces {B}
        # instead", Infernal Darkness), so the default one answers — and it is
        # the one that costs nothing more. Asked for the {B} the swap makes,
        # an Underground River was sent to its second ability because that is
        # the one whose *printed* symbols include {B}: the plan took a point
        # of damage to pay a generic pip its free {C} would have paid. The
        # one exception is a colours-only swap ("…instead of any other
        # **color**", Hall of Gemstone) over a default that makes only {C},
        # which the swap leaves alone.
        swap = swapped_production(self, land)
        if swap is not None and swap.produced is not None and not (
            swap.colors_only and mana_ability_symbols(free) <= {"C"}
        ):
            return None
        for index, ability in enumerate(self.usable_abilities_of(land)):
            if not is_tap_alone_mana_ability(ability):
                continue
            if color in mana_ability_symbols(ability.instruction) and (
                self.land_mana_tap_refusal(land, index) is None
            ):
                return index
        return None

    def land_mana_tap_refusal(self, land, ability_index: int | None = None) -> str | None:
        """Why tapping *land* for mana through :meth:`tap_land_for_mana` would
        be refused right now — a short reason key — or None when it would make
        mana. Pure: nothing is tapped, logged or produced.

        **The seam's own gate, made askable.** The AI's tap planner
        (`ai_policy._plan_land_taps`) counted every untapped land as a mana,
        while this seam refuses a storage or depletion land with no counter
        to pay (Sand Silos), a land with no mana ability at all (Bazaar of
        Baghdad), a summoning-sick land creature and a land under Interdict —
        so the AI tapped "for" a spell, the tap made nothing and the cast was
        refused for insufficient mana, the same spell every turn. Invisible
        while the simulator ignored mana costs; the web app's AI seat, which
        never did, had it all along. One predicate, asked by both, so what the
        planner counts and what the tap makes cannot disagree.
        """
        # ``has_type``, not the printed line: a Clone that copied a Forest some
        # Living Lands had animated is a Forest (CR 707.2) and taps for {G}.
        # Asked of the Clone's own card it was a creature, and no land at all.
        if land is None or not land.has_type("land") or land.tapped:
            return "not_an_untapped_land"

        # Tapping a land for mana *is* activating its mana ability (CR 106.12),
        # so the gates the activation path asks of that ability are asked here
        # too — this seam is the second door to the same ability, and a gate
        # one door asks and the other does not is a rule enforced on half the
        # wire. CR 302.6 (through CR 602.5a): a land that is a creature —
        # Mishra's Factory animated, a Forest under Living Lands — has the
        # summoning-sickness rule like any creature, and a {T} mana ability is
        # a {T} ability. CR 602.5's per-permanent ban ("That permanent's
        # activated abilities can't be activated this turn", Interdict) prints
        # no mana-ability exception. Both refused here as the activation path
        # refuses them, with nothing tapped.
        from ..spell_prohibitions import permanent_activations_forbidden

        if self._is_summoning_sick(land):
            return "summoning_sick"
        if permanent_activations_forbidden(self, land):
            return "activations_forbidden"

        # A land with no mana ability at all (Island of Wak-Wak, Bazaar of
        # Baghdad) can't be tapped for mana — without this, the color fallback
        # below would invent a green mana out of nothing. A compiled one the
        # summary does not know about (a mana ability granted to such a land)
        # is a mana ability all the same.
        if ability_index is not None:
            if self._chosen_land_mana_ability(land, ability_index) is None:
                return "no_such_mana_ability"
            return None
        mana_ability, priced_mana_ability = self._land_mana_abilities(land)
        if mana_ability is None and not land.effective_produced_mana:
            if not land.basic_land_types:
                return "no_mana_ability"
        # **A land that has lost all abilities has lost this one too**
        # (CR 613.1f). The mana ability a basic land type gives is an ability
        # like any other — CR 305.6 calls it intrinsic, not exempt — and
        # Humility's own ruling says so: "Removes all creature abilities. This
        # includes mana abilities. Animated lands will also lose the ability
        # to tap for mana." (2007-02-01.) A Forest under Living Lands and a
        # Humility is a 1/1 that taps for nothing. What is left to tap for is
        # a mana ability an effect granted it *afterwards*, which is the
        # compiled one above — the walk is over the effective card, where
        # only the newer grants remain. The summary path below is the type's
        # ability and the printed card's, and it asked nothing.
        if mana_ability is None and abilities_lost_at(land) is not None:
            return "no_mana_ability"

        # **And a land whose mana ability costs more than the tap cannot be
        # tapped for mana here either** (CR 602.2b: every cost, at one moment).
        # "{T}, Remove a depletion counter from this land: Add {B}{B}" (Peat Bog
        # and its four siblings) and "{T}, Remove any number of storage
        # counters ...: Add {B} for each" (the storage-land cycles, Gemstone
        # Mine) all fall past the compiled-ability branch below -- it takes only
        # a tap-alone cost, correctly -- and landed on the ``produced_mana``
        # fallback, which adds **one** mana of the summary's colour and charges
        # nothing. Sixteen lands in the pool tapped for a free mana for ever,
        # spending no counter and so never sacrificing themselves; six of them
        # ship. The amount is wrong too, but the unpaid cost is what makes it a
        # different card.
        #
        # Refused rather than approximated: the seat activates the ability and
        # pays, which is the path that works. Producing nothing is the honest
        # answer for a caller -- the AI's auto-tap, the web's land click -- that
        # asked to tap a land and cannot pay what the land asks.
        if (
            mana_ability is None and priced_mana_ability
            # …unless the land has a second, free one: the mana ability of a
            # basic land type it *gained* (see ``_gained_type_mana``).
            and not self._gained_type_mana(land)
        ):
            return "priced_mana_ability"
        return None

    @staticmethod
    def _gained_type_mana(land) -> tuple[str, ...]:
        """The mana symbols of the basic land types *land* gained "in addition
        to its other land types" (Blanket of Night) — CR 305.7's last
        sentence: it "keeps its land types and rules text, and it gains the
        new land types **and mana abilities**".

        So such a land has two kinds of mana ability, and they are not found
        in the same place: what it prints is a compiled ability, and what the
        gained type gives it is CR 305.6's intrinsic "{T}: Add [symbol]",
        which is no text at all. Empty for every other land, a land whose type
        an effect *set* included — that one has only the intrinsic ability,
        which the summary path below already is.
        """
        from ..land_types import added_land_types

        added = set(added_land_types(land))
        if not added:
            return ()
        return tuple(
            symbol
            for land_type, symbol in zip(land.basic_land_types, land.basic_land_mana)
            if land_type in added
        )

    def _default_tap_symbols(self, land, mana_ability) -> tuple[str, ...]:
        """The symbols *mana_ability* — the one a tap of *land* with no
        ability named runs — can make, read off the ability itself; the
        printed summary where its shape is not read."""
        from ..board_payment import _makes

        made = _makes(self, land, mana_ability)
        if made is None:
            return tuple(land.effective_card.produced_mana or ())
        return tuple(made)

    @staticmethod
    def _tap_alone_makes_only_gained_mana(land) -> tuple[str, ...]:
        """The symbols a **tap alone** makes from *land* where its own mana
        ability costs more than the tap and a gained land type's does not —
        or empty, for every other land.

        A Hickory Woodlot under Blanket of Night has two mana abilities: the
        one it prints ("{T}, Remove a depletion counter: Add {G}{G}"), which
        this seam does not run, and the gained Swamp's "{T}: Add {B}"
        (CR 305.6), which it does. So what the land can be *tapped for* is
        {B} and only {B} — per symbol, not per land — and every reader that
        counts the land as mana has to hear that: the planner's list
        (``mana_payment.taps_for_payment``) left it out altogether, and the
        planner's hook, the castable highlight and the wire's colour list
        each offered the {G} its summary names for a tap that makes {B}.
        """
        free, priced = TurnManagementMixin._land_mana_abilities(land)
        if free is None and priced:
            return TurnManagementMixin._gained_type_mana(land)
        return ()

    def tap_land_for_mana(
        self,
        player_index: int,
        land_name: str,
        chosen_color: str | None = None,
        permanent_index: int | None = None,
        *,
        permanent_id: int | None = None,
        ability_index: int | None = None,
    ) -> bool:
        """Tap one land for mana (CR 605.1a), as its controller.

        *chosen_color* is the mana symbol the seat asks the land for — one of
        the six types (CR 106.1b), or None for "whatever it makes". **Asking
        chooses the ability as well as the colour** (CR 605: each mana ability
        is its own, and the player picks which to activate): a Karplusan
        Forest asked for {R} runs "{T}: Add {R} or {G}. This land deals 1
        damage to you.", and asked for nothing runs "{T}: Add {C}."
        (``board_payment.tap_alone_ability_for``). It used to run the first
        one whatever was asked, so every reader that said the land pays {R}
        was contradicted by the tap. A symbol the land cannot make is no
        choice and takes the land's default, as it always has; a string that
        is no mana symbol at all is **refused**, with nothing tapped — it
        reached the colour normalizer inside a handler and raised.

        *ability_index* is which of the land's mana abilities the player chose
        outright, indexing the same list the activation path does, and wins
        over what the colour would have picked. With neither, the land's
        first tap-alone mana ability runs.

        *permanent_id* addresses the land the way the rest of the engine does
        and takes precedence over the name-and-slot pair above it, which exists
        because the web layer addresses a permanent by its **slot**. A caller
        walking a whole battlefield has no slot to quote and cannot use the
        name either: two Forests are one name, and
        ``_find_controlled_permanent`` answers with the first — which on a
        forced tap-out is the one already tapped, so the untapped one is
        skipped and the seat pays nothing. The id is stable across the loop
        (CR 400.7) where a slot is not.
        """
        player = self.players[player_index]
        if permanent_id is not None:
            land = self.permanent_by_id(permanent_id)
            if land is not None and self.controller_index_of(land) != player_index:
                land = None
        else:
            resolved = self._find_controlled_permanent(
                player, land_name, permanent_index
            )
            land = resolved[1] if resolved else None
        # What was *asked for*, kept apart from the default the rest of this
        # method falls back on: only a symbol somebody named picks an ability.
        asked = None if chosen_color is None else str(chosen_color).strip().upper()
        if asked is not None and asked not in _TAPPABLE_SYMBOLS:
            if asked:
                # Not one of the six mana types: nothing this land or any
                # other could be tapped for.
                return False
            asked = None
        chosen_color = asked or "G"
        if (
            ability_index is None and asked is not None
            and land is not None and land.has_type("land")
        ):
            from ..board_payment import tap_alone_ability_for

            ability_index = tap_alone_ability_for(self, land, asked)
        refusal = self.land_mana_tap_refusal(land, ability_index)
        if refusal is not None:
            # The two refusals a player can see the reason for are logged, as
            # they always were; the rest are a land that makes no mana here.
            if refusal in _LOGGED_TAP_REFUSALS:
                self.log.append(f"{land.card.name}{_LOGGED_TAP_REFUSALS[refusal]}")
            return False
        gained_symbol = None
        if ability_index is not None:
            mana_ability = self._chosen_land_mana_ability(land, ability_index)
        else:
            mana_ability, _priced = self._land_mana_abilities(land)
            # "Each land is a Swamp **in addition to its other land types**."
            # (Blanket of Night.) The land keeps the mana ability it prints
            # and gains its new type's (CR 305.7's last sentence, CR 305.6), so
            # the colour the seat asks for says which of the two it is
            # activating: the gained type's when only that one makes it — and
            # when the land's own mana ability costs more than the tap (a
            # depletion land's), which this seam does not run and must not
            # hand out free under the gained type's name. A land with no
            # compiled ability at all (a basic, a dual) is the summary path's
            # as it always was: its printed types and the gained one are both
            # in ``effective_produced_mana``.
            gained = self._gained_type_mana(land)
            if gained and (
                (mana_ability is None and _priced)
                or (
                    mana_ability is not None
                    and chosen_color in gained
                    # …and not what the ability about to run makes. This asked
                    # the printed summary, which lists what *every* ability of
                    # the land makes: an Underground River under the Blanket,
                    # asked for {B}, was "already a {B} land" by its painful
                    # second ability and so ran its first, for {C}.
                    and chosen_color not in self._default_tap_symbols(
                        land, mana_ability
                    )
                )
            ):
                mana_ability = None
                gained_symbol = chosen_color if chosen_color in gained else gained[0]

        # CR 701.26a's event, announced by the one tap seam. City of Brass
        # ("Whenever this land becomes tapped, it deals 1 damage to you") and
        # Psychic Venom ("Whenever enchanted land becomes tapped…") each used to
        # be dispatched by a hand-written pass here, which meant each fired on
        # *this* tapper and on none of the others — an Icy Manipulator, an
        # attack cost, or any of the other places `become_tapped` is called.
        # Both are ordinary `permanent_becomes_tapped` triggers now, so they go
        # on the stack (CR 603.3) from wherever the tap happens.
        self.become_tapped(land)

        def produce() -> str:
            # **The land's own compiled mana ability, when it has one.** This used
            # to add exactly one symbol chosen from `produced_mana`, which is right
            # for every land in the 1993-94 base sets and for the dual cycles — all
            # of them produce one mana — and silently wrong for the first land that
            # does not. Antiquities brought four: Mishra's Workshop prints
            # {C}{C}{C} and paid one, and the Urza's cycle's assembly could not be
            # read at all because the amount is behind a condition.
            #
            # `produced_mana` is Scryfall's summary of *which symbols* a land can
            # make; it says nothing about how many or under what condition. The
            # compiled ability says both, so it is what runs, and the summary is
            # the fallback for a basic whose whole ability line is CR 305.6
            # reminder text and compiles to nothing.
            # "One mana of any type **that land produced**" (Mana Flare) reads this
            # at the bottom of the method, and the compiled-ability branch below
            # writes into the pool without ever naming a symbol — so it was left
            # unbound there, and a Mana Flare over any land whose mana ability
            # compiles (every dual, every filter land) raised `UnboundLocalError`
            # instead of adding mana. Seeded with the colour the seat asked for,
            # which is the answer for a land that offers a choice and the closest
            # honest one for a land that does not.
            mana_symbol = chosen_color
            if mana_ability is not None:
                instruction = mana_ability
                # The colour arrives the way the activation path delivers it,
                # so "tap Badlands for {R}" keeps meaning what it did; the
                # handler ignores it unless the printed clause offers a choice.
                #
                # **A colour, or nothing.** The request is a mana *symbol*, and
                # {C} is one a land may be asked for — it is what
                # ``_land_payment_colors`` answers for every land under Ritual
                # of Subdual, so it is what the AI's plan and the client's
                # colour fan send. Injected as the answer to "{R} or {G}" it
                # reached the handler's colour normaliser, which raises: a dual
                # land under a colourless swap ended the game with a
                # ValueError. Colourless is not a colour (CR 105.1), so a land
                # asked for it has been told nothing about its choice and makes
                # its first printed alternative — which the swap then replaces.
                asked_color = self._chosen_mana_color(chosen_color)
                if asked_color:
                    instruction = dataclasses.replace(
                        instruction,
                        payload={**instruction.payload, "color": asked_color},
                    )
                # …and to the "Choose a color" step of a two-sentence spelling
                # ("Choose a color. Add one mana of that color."), which the
                # outer injection cannot reach — CR 605.3b, one helper for both
                # inline sites (``mana_payment.answer_color_choices``).
                instruction = answer_color_choices(
                    instruction, self._chosen_mana_color(chosen_color)
                )
                self._execute_oracle_instruction(
                    instruction,
                    OracleExecutionContext(
                        caster=player,
                        target=player,
                        card=land.card,
                        source_permanent=land,
                        # The colour again, on the key the activation path carries
                        # it on (``new_color``), because the payload injection above
                        # rewrites only the *outer* instruction: a painland's "Add
                        # {R} or {G}. This land deals 1 damage to you." lowers to a
                        # ``sequence`` whose nested add step never sees it, and asked
                        # for {G} would make the first printed alternative.
                        choices={"new_color": self._chosen_mana_color(chosen_color)},
                    ),
                )
            else:
                produced = land.effective_produced_mana
                if gained_symbol is not None:
                    mana_symbol = gained_symbol
                elif produced:
                    # A colour swapped away is still a legitimate request: the seat
                    # names the symbol the land prints and the swap decides what
                    # comes out, so the request is mapped through the swaps rather
                    # than dropped. `produced[0]` is the answer only when nothing
                    # maps — a land asked for a colour it never made.
                    mana_symbol = land.produced_symbol_for(chosen_color) or produced[0]
                else:
                    symbols = land.basic_land_mana
                    if symbols:
                        mana_symbol = symbols[0]
                player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1
            return mana_symbol

        # CR 106.12: what follows is the event — the record, the replacement
        # over the production, the production itself and everything that
        # watches a land tapped for mana. One method, because this is one of
        # three roads to it (:meth:`_land_tapped_for_mana`).
        self._land_tapped_for_mana(
            player_index, land, chosen_color, produce, land_name=land_name,
        )
        return True

    def _land_tapped_for_mana(
        self, player_index: int, land, chosen_color: str | None, produce,
        *, land_name: str | None = None,
    ) -> bool:
        """**A land was tapped for mana** (CR 106.12) — the one event.

        "To 'tap [a permanent] for mana' is to activate a mana ability of that
        permanent that includes the {T} symbol in its activation cost." Three
        roads do that, and until Odyssey's wave 2 only the first told anybody:

        * the player's own tap (:meth:`tap_land_for_mana`);
        * **a cost an effect collects** — "counter target spell unless its
          controller pays {1}", an upkeep price, an attack toll. The payer
          gets no priority window, so the engine plans the payment and taps
          the lands itself, which is the player activating mana abilities
          while an effect asks for mana (CR 605.3a). It tapped them with
          ``become_tapped``: no mana was produced, no ability ran, and
          nothing here was announced. Each planned land is tapped through
          :meth:`tap_land_for_mana` now (``Game._pay_planned_cost``), so this
          road *is* the first one;
        * **a land whose mana ability costs more than the tap** — "{1}, {T}:
          Add {U}{B}" (Darkwater Catacombs), a sacrifice land, a depletion
          land — which the seam above refuses by design (CR 602.2b) and the
          activation path resolves inline (CR 605.3b). That branch calls this
          method around the ability it runs.

        *produce* runs the land's own production and returns the symbol the
        seat asked it for; what it actually made is read off the pool, so
        "one mana of any type **that land produced**" (Mana Flare) is the
        type that came out. The land is already tapped: {T} is a cost, and
        every road pays it before it gets here.

        Returns whether mana was produced. CR 106.12a: an ability that
        triggers whenever a permanent is tapped for mana "triggers whenever
        such a mana ability resolves **and produces mana**" — a land whose
        ability made none this time (a Tolarian Academy beside no artifact)
        was tapped, and nothing watching for mana saw any.
        """
        player = self.players[player_index]
        if land_name is None:
            land_name = land.card.name

        # "…each player who **tapped a land for mana this turn**" (Desolation).
        # The seat's own per-turn record, written at the one tap-for-mana seam
        # — the same site that announces `land_tapped_for_mana` below, so what
        # a trigger fires on and what the record remembers cannot disagree.
        # A fact about the seat rather than about the land, for
        # `attacked_this_turn`'s reason: the land may untap, leave, or be
        # tapped again for something that is not mana, and the player still
        # tapped one for mana this turn.
        player.tapped_land_for_mana_this_turn = True
        # "Until end of turn, if you tap a land you control for mana, it
        # produces {U} instead of any other type." (Deep Water.) "If a land is
        # tapped for mana, it produces {B} instead…" (Infernal Darkness.)
        # CR 106.12b makes these replacement effects over the mana production
        # event, so they are asked through the CR 614 registry — one event kind
        # with its own contention set, and nothing consumed: mana is still
        # produced and the land is still tapped for mana (CR 106.12a).
        #
        # Read here, and applied to whatever the production below actually puts
        # in the pool, because this is the one place the two production paths
        # meet: a land with a compiled mana ability runs it and writes into the
        # pool itself, where a basic falls through to the `produced_mana`
        # summary — and the per-permanent swap `Permanent._swapped_mana`
        # applies is only on the second of those. Snapshotting the pool is what
        # makes "instead of any **other** type" mean what it says: whatever came
        # out, this is what it is instead.
        #
        # No `restart` thunk: a land is tapped for mana part-way through paying
        # a cost (CR 601.2g), before the spell it pays for is on the stack, so
        # there is no moment at which a CR 616.1e choice could be answered and
        # nothing to re-run it against.
        _, mana_event = apply_replacements(
            self, "land_mana_produced",
            {
                "land": land, "player": player, "produced": None,
                "produced_amount": None,
                # The colour the seat asked this land for. "…it produces one
                # mana of **a color of your choice** instead…" (Harvest Mage)
                # is chosen per tap, and this request is that choice — the
                # same channel a dual land's "{R} or {G}" is answered through.
                "requested": chosen_color,
            },
        )
        swapped_to = mana_event.get("produced")
        # "…instead of any other type **and amount**." (Contamination.) None is
        # every other substitution, which replaces the type and leaves the
        # count alone — an Ancient Tomb under Infernal Darkness makes {B}{B}
        # and under Contamination makes {B}.
        swapped_amount = mana_event.get("produced_amount")
        # Every bucket, not only the open pool: mana a "spend this mana only…"
        # clause narrowed is written into its own bucket (CR 106.6), and a
        # snapshot of the pool alone let it escape every swap — Mishra's
        # Workshop under Contamination made {C}{C}{C}, not one {B}.
        pool_before = production_snapshot(player)
        mana_symbol = produce()

        if swapped_to:
            # Whatever the land already put in under the swapped symbol itself
            # counts toward the replaced amount: a Swamp under Contamination
            # made its own {B}, and the sentence says the whole production is
            # one {B} rather than one more. Each bucket keeps its own mana, so a
            # restricted production stays restricted (CR 106.6).
            colors_only = bool(mana_event.get("colors_only"))
            moved = substitute_production(
                player, pool_before, swapped_to,
                None if swapped_amount is None else int(swapped_amount),
                colors_only=colors_only,
            )
            if moved:
                self.log.append(
                    f"{land_name} produced {{{swapped_to}}} instead"
                )
            # "One mana of any type **that land produced**" is what came out,
            # not what would have: a Mana Flare over a Ritual of Subdual board
            # matches the colourless the land really made. Except where a
            # colours-only swap moved nothing — Hall of Gemstone over a land
            # that made {C} changed nothing, and the {C} is what it made.
            if moved or not colors_only:
                mana_symbol = swapped_to

        self.log.append(f"{player.name} tapped {land_name} for mana")

        # What the land really made, across every bucket (CR 106.6: restricted
        # mana is still mana). Nothing made, nothing to announce — CR 106.12a.
        made = _mana_made_since(player, pool_before)
        if not made:
            return False
        # "One mana of any type **that land produced**" (Mana Flare) is a type
        # that came out. The seat's request stands when the land made it — a
        # dual asked for {R} — and otherwise the answer is read off the pool:
        # an Ancient Tomb asked for the route's default {G} made {C}{C}, and
        # the adder used to hand back the {G} it was asked for.
        if mana_symbol not in made:
            asked = (chosen_color or "").strip().upper()
            mana_symbol = asked if asked in made else next(iter(made))

        # Kudzu's "when enchanted land becomes tapped" used to be dispatched
        # here, from inside the *mana* path — so it was the one attached trigger
        # that could not see a land tapped any other way (CR 701.26a). It is an
        # ordinary compiled trigger now, announced by `become_tapped` above like
        # City of Brass's and Psychic Venom's, and nothing about it belongs in
        # this method.
        attached_aura = land.metadata.get("attached_aura")
        if attached_aura is not None:
            # Wild Growth: "Whenever enchanted land is tapped for mana, its controller
            # adds an additional {G}." The "for mana" phrasing isn't compiled as a
            # generic trigger, so the mana is read from the Aura's text here.
            #
            # The pattern is `auras.aura_additional_mana_on_tap`, not a regex of
            # this method's own. It used to be written out here alone, so the
            # support gate had no way to ask whether this line was implemented
            # and claimed every attached trigger with a wildcard instead — which
            # is how an Aura whose trigger nothing reads reported supported. One
            # pattern, two readers: this dispatcher and `attached_trigger_claim`.
            #
            # A *run* of symbols, because Overgrowth prints "{G}{G}" where Wild
            # Growth prints "{G}" — the count is data, and adding one symbol for
            # a card that says two is the quiet direction of wrong.
            for extra in aura_additional_mana_on_tap(
                attached_aura.effective_card.oracle_text
            ):
                if extra == AURA_ANY_COLOR_MANA:
                    # "…adds an additional **one mana of any color**" (Fertile
                    # Ground) rather than a printed pip. CR 106.6 leaves the
                    # colour to the controller, and CR 605.4a gives a triggered
                    # mana ability no window to be asked in — this is running
                    # inline, inside the cost payment that tapped the land, so
                    # there is no priority for a prompt. The seat's answer is
                    # already in hand: `chosen_color` is the colour this very
                    # call asked the land for, which is the same player making
                    # the same kind of choice at the same moment. It is
                    # normalized rather than trusted, because it arrives off the
                    # wire.
                    #
                    # **A land asked for {C} has named no colour for the Aura.**
                    # "Any color" is one of the five (CR 105.1), never
                    # colourless, so `{C}` is the land's own answer and says
                    # nothing here - the same case as a call that named no
                    # colour at all, and it takes the same default. Handed to
                    # the normalizer it raised: a Mishra's Factory or an
                    # Archaeological Dig under a Fertile Ground, tapped for the
                    # `{C}` the AI's plan counted, ended the game with a
                    # ValueError. Anything else that is not a colour is still
                    # refused.
                    asked = (chosen_color or "").strip().upper()
                    extra = (
                        None if asked == "C"
                        else self._normalize_mana_color(chosen_color)
                    ) or "G"
                # "…spells and abilities **you control** that would add colored
                # mana instead add that much white mana." (False Dawn.) This
                # triggered mana ability is the *Aura's* controller's, and it is
                # the one production here that is written inline rather than
                # through an instruction — so the seat's source-wide swap is
                # asked for it by name, where every other ability meets it at
                # the dispatch seam (``Game._execute_oracle_instruction``).
                aura_seat = self.controller_index_of(attached_aura)
                wide = (
                    source_wide_swap(self.players[aura_seat])
                    if aura_seat is not None else None
                )
                if wide is not None and (extra != "C" or not wide.colors_only):
                    extra = wide.symbol()
                player.mana_pool[extra] = player.mana_pool.get(extra, 0) + 1
                self.log.append(f"{attached_aura.card.name}: {player.name} added an additional {{{extra}}}")

        # "Whenever a player taps a land for mana" triggers (Manabarbs,
        # Mana Flare, Gauntlet of Might). The last two were name-keyed
        # MANA_PRODUCTION_MODIFIERS hooks fired further up this method; their
        # triggers now compile like any other, so they arrive here.
        #
        # The mana ones are triggered *mana* abilities (CR 605.1b: no target,
        # triggered by an activated mana ability, and they could add mana), so
        # CR 605.4a says they never use the stack — inline is what the rules
        # require, not a shortcut.
        #
        # Manabarbs' damage is not a mana ability and by the rules would use the
        # stack; it resolves inline because a land is tapped for mana
        # mid-cost-payment, before the spell being paid for is even on the
        # stack, so enqueuing here would order the trigger *under* that spell.
        # Stack routing would require deferring these across the
        # cost-payment/cast boundary.
        for _idx, perm, trig in iter_triggered_abilities(
            self, condition_kinds={"land_tapped_for_mana"}, first_match_only=False
        ):
            if not self._land_tap_trigger_fires(trig, perm, player_index, land):
                continue
            # "…that player adds one mana of any type that land produced.
            # **That land doesn't untap during its controller's next untap
            # step.**" (Winter's Night.) One trigger whose effect is two
            # sentences, so the compiler hands it a `sequence` — and this site
            # dispatched on `trig.instruction.kind` alone, which made every
            # clause of such a trigger unreachable. Flattened here rather than
            # by teaching each arm about sequences: what the arms answer is
            # "which effect is this", and how many sentences the ability was
            # printed in is not part of that question.
            # "…**if it's not that player's turn**, destroy that land." (Price
            # of Glory.) CR 603.4's intervening-if. This site triggers and
            # resolves in one motion, so the rule's two checks are one check:
            # false, the ability does not trigger and nothing below runs.
            gate = (trig.instruction.payload or {}).get("intervening_if")
            if gate is not None:
                from ..handlers.control_flow import evaluate_condition

                watcher = self.controller_index_of(perm)
                if watcher is None or not evaluate_condition(
                    self,
                    OracleExecutionContext(
                        caster=self.players[watcher], target=player,
                        card=perm.card, source_permanent=perm,
                        trigger_context={"event_subject_player": player_index},
                    ),
                    gate,
                ):
                    continue
            for step in _tap_trigger_steps(trig.instruction):
                self._resolve_tapped_land_trigger_step(
                    step, player_index, player, land, mana_symbol, perm
                )
            continue
        # The same ability created for a turn instead of printed on a permanent
        # (CR 603.7): "Until end of turn, … whenever a player taps a Mountain
        # for mana, that player adds an additional {R}." (Chaos Moon's odd
        # branch.) It belongs to no permanent, so the scan above cannot see it —
        # it waits on `game.delayed_triggers` and is announced here.
        #
        # **Resolved inline, not enqueued**, and that is CR 605.4a rather than a
        # convenience: a triggered mana ability does not use the stack, and the
        # rule's own example is this clause. `fire_delayed_triggers` always
        # enqueues, so this site asks `matching_delayed_triggers` for the
        # entries and performs them where the permanent-borne ones above are
        # performed — the same instruction, the same dispatcher, the same
        # cost-payment moment.
        for entry in matching_delayed_triggers(
            self, "land_tapped_for_mana", subject=land
        ):
            # The grammar admits no other effect under this event (it refuses
            # the sentence), so anything else here is an entry built by hand;
            # skipping it is the safe reading, because this site has no way to
            # give a non-mana effect the priority window the stack would.
            if entry.instruction.kind != "add_mana_for_tapped_land":
                continue
            self._add_triggered_land_mana(
                entry.instruction, player_index, land, mana_symbol,
                # CR 603.7d: the source is the object whose ability created the
                # delayed one — the enchantment, not the land being tapped. It
                # may have left by now, in which case the log falls back to the
                # name the entry froze when it was armed.
                self.permanent_by_id(entry.source_permanent_id),
                source_name=entry.source_name,
            )

        return True

    def _land_tap_trigger_fires(self, trig, perm, player_index: int, land) -> bool:
        """Whether *perm*'s "whenever … is tapped for mana" ability *trig*
        triggers for *player_index* tapping *land* — the printed narrowing,
        which rides the condition's payload.

        One predicate for the tap seam, which resolves the trigger, and for
        ``land_tap_mana_adders``, which says beforehand what the mana ones
        will add: a preview with a reading of its own would count a
        Gauntlet of Might's {R} over a Forest.
        """
        # "Whenever a **Mountain** is tapped for mana" — the narrowing rides
        # the condition's payload, so the land type is data rather than a
        # per-card hook. has_type, so a land made a Mountain by a layer-4
        # effect counts.
        subtype = trig.condition.payload.get("tapped_land_subtype")
        if subtype and not land.has_type(str(subtype)):
            return False
        # "Whenever a player taps a **snow** land for mana" (Winter's
        # Night). A supertype (CR 205.4a), not a type, so it is asked of
        # `has_supertype` — the accessor the type test above would answer
        # False for on every land, which is a trigger that never fires
        # rather than one that fires too often. Layer 4 either way: a land
        # an effect *made* snow counts and one that stopped being snow does
        # not.
        supertype = trig.condition.payload.get("tapped_land_supertype")
        if supertype and not land.has_supertype(str(supertype)):
            return False
        # "Whenever **a land an opponent controls** is tapped for mana"
        # (Mana Web). A whole noun phrase where the two rows above carry a
        # single word, so it is tested through the one matcher every other
        # narrowed subject in this engine goes through — and the seat it
        # carries is relative to *this ability's* controller (CR 109.5),
        # never to whoever tapped the land. Dropped, the trigger would fire
        # on its own controller's lands too, which on Mana Web is a card
        # that taps out the player who cast it.
        # "Whenever **an opponent** taps a Mountain for mana" (Sanctimony).
        # CR 109.5's seat, asked of whoever tapped the land against the seat
        # that controls the *watching permanent* — read through the control
        # seam, so a Sanctimony somebody has taken control of watches
        # **their** opponents from the moment they take it (CR 613 layer 2).
        #
        # This is the narrowing the two rows above are not: they describe
        # the *land*, and this describes the player who tapped it. Dropped,
        # the enchantment would gain its controller life for their own
        # Mountains — a trigger firing on a strictly larger set, which reads
        # to every census in this repo as an implemented card.
        if trig.condition.payload.get("tapped_by_opponent") is not None:
            watcher = self.controller_index_of(perm)
            if watcher is None or player_index == watcher:
                return False
        # "Whenever **you** tap a land for mana" (Savage Firecat). The
        # same seat test the other way round: only the watching
        # permanent's own controller's taps count.
        if trig.condition.payload.get("tapped_by_you") is not None:
            watcher = self.controller_index_of(perm)
            if watcher is None or player_index != watcher:
                return False
        described = trig.condition.payload.get("tapped_land_filter")
        if described:
            from ..subject_filters import subject_matches

            watcher = self.controller_index_of(perm)
            if not self.is_on_battlefield(land):
                # **A land its own cost sacrificed** ("{T}, Sacrifice this
                # land: Add {B}{B}", Ebon Stronghold). It was tapped for
                # mana and the ability has now resolved (CR 106.12a), but
                # the land is a card in a graveyard, which CR 109.4 gives
                # no controller — so "a land **an opponent controls**"
                # asked of the control seam answers no, and Mana Web
                # slept through every sacrifice land. Whose it was is the
                # seat that tapped it; the rest of the phrase is asked of
                # the object as it last was.
                described = dict(described)
                whose = described.pop("controller", None)
                if whose == "opponent" and (
                    watcher is None or watcher == player_index
                ):
                    return False
                if whose == "you" and watcher != player_index:
                    return False
                if whose not in (None, "opponent", "you"):
                    return False
            if not subject_matches(
                self, land, described, observer=watcher, source=perm,
            ):
                return False
        return True

    def land_tap_mana_adders(self, player_index: int, land) -> list:
        """The ``add_mana_for_tapped_land`` instructions that will resolve
        when *player_index* taps *land* for mana — Mana Flare's "one
        additional mana of any type that land produced", Gauntlet of
        Might's "an additional {R}", a Chaos Moon's turn-long one.

        Triggered mana abilities (CR 605.1b), so they resolve inside the
        tap (CR 605.4a) and what they add is mana the tap makes. The seam
        below performs them; this is the same walk with nothing performed,
        for the reader that has to know before anything is tapped
        (``engine/board_payment.py``).
        """
        found = []
        for _idx, perm, trig in iter_triggered_abilities(
            self, condition_kinds={"land_tapped_for_mana"}, first_match_only=False
        ):
            if not self._land_tap_trigger_fires(trig, perm, player_index, land):
                continue
            found.extend(
                step for step in _tap_trigger_steps(trig.instruction)
                if step.kind == "add_mana_for_tapped_land"
            )
        found.extend(
            entry.instruction
            for entry in matching_delayed_triggers(
                self, "land_tapped_for_mana", subject=land
            )
            if entry.instruction.kind == "add_mana_for_tapped_land"
        )
        return found

    def _resolve_tapped_land_trigger_step(
        self, instruction, player_index: int, player, land, mana_symbol, perm
    ) -> None:
        """One clause of a ``land_tapped_for_mana`` trigger, resolved inline.

        Inline rather than on the stack for Manabarbs' reason rather than
        CR 605.4a's, everywhere but the mana: none of these is a mana ability
        and by the rules they would use the stack, but the land is tapped
        part-way through paying a cost (CR 601.2g) and enqueuing here would
        order the trigger *under* the spell being paid for.

        **Every kind is named.** The damage arm used to be this loop's ``else``:
        any instruction kind it did not recognize was read for an ``amount`` and
        dealt as damage, defaulting to 1 when the payload had none — so a draw
        under this condition dealt a point of damage on a card reporting itself
        supported. A kind nobody has taught this site is skipped with a line in
        the log, which is the safe reading: this resolution cannot give a
        non-mana effect the priority window the stack would, and doing *nothing*
        visible beats doing something the card never said.
        """
        kind = instruction.kind
        if kind not in TAP_TRIGGER_KINDS:
            self.log.append(
                f"{perm.card.name}: nothing here resolves "
                f"{kind!r} inside a cost payment"
            )
            return
        # "Whenever an opponent taps a Mountain for mana, **you may gain 1
        # life**." (Sanctimony.) Run through the engine's own dispatcher, with
        # the ability's controller as the caster (CR 109.5) — never the seat
        # that tapped the land, which on this card is the opponent whose
        # Mountain it was.
        #
        # The tapping seat is frozen into the trigger's context under the key
        # every "that player" reader already asks for, because this site is the
        # fire site and holds it: an effect printed under this condition that
        # names the event's player has one place to read it, and it is here.
        if kind in _TAP_TRIGGER_HANDLER_KINDS:
            watcher = self.controller_index_of(perm)
            if watcher is None:
                self.log.append(
                    f"{perm.card.name}: its controller has left, so nothing is offered"
                )
                return
            self._execute_oracle_instruction(
                instruction,
                OracleExecutionContext(
                    caster=self.players[watcher],
                    target=player,
                    card=perm.card,
                    source_permanent=perm,
                    trigger_context={
                        "event_subject_player": player_index,
                        "event_subject_controller": player_index,
                        # The land the event was about, by id (CR 400.7) —
                        # what "destroy **that land**" reads (Price of Glory).
                        "event_subject_permanent_id": land.permanent_id,
                    },
                ),
            )
            return
        if kind == "add_mana_for_tapped_land":
            self._add_triggered_land_mana(
                instruction, player_index, land, mana_symbol, perm
            )
            return
        # "Whenever a land is tapped for mana, return it to its owner's hand."
        # (Storm Cauldron.) The mana has already been added, which is what the
        # rules say happens: the mana ability resolved (CR 605.3b) and the land
        # leaving afterwards takes nothing back.
        if kind == "return_tapped_land_to_hand":
            self._return_tapped_land_to_hand(land, perm)
            return
        # "…tap all lands that player controls that could produce any type of
        # mana that land could produce." (Mana Web.) The sweep whose set is
        # named by a comparison against the land this event was about — which
        # is why it is resolved here and by no ``@effect_handler``: this site
        # is the only one holding both lands at once.
        if kind == "tap_lands_sharing_produced_mana":
            self._tap_lands_sharing_produced_mana(
                instruction, player_index, land, perm
            )
            return
        # "**That land** doesn't untap during its controller's next untap
        # step." (Winter's Night.) CR 502.3's restriction on the land the event
        # was about — which only this site knows, so the marker is written here
        # through the same function the ordinary handler writes it with rather
        # than through a second copy of the merge rule.
        if kind == "skip_next_untap":
            if instruction.payload.get("subject") != "tapped_land":
                self.log.append(
                    f"{perm.card.name}: nothing here resolves an untap "
                    "restriction that does not name the tapped land"
                )
                return
            from ..handlers.tapping import mark_skip_next_untap

            mark_skip_next_untap(
                self, (land,),
                steps=max(1, int(instruction.payload.get("untap_steps") or 1)),
                # "…its controller's next untap step" names no seat, which the
                # untap step reads as "whichever controller's step reaches it".
                # The seated spelling would be "your", and no card prints it
                # under this condition.
                seat=None,
            )
            return
        # The compiled payload names its victim ``event_subject_player`` —
        # `land_tapped_for_mana` is in `_EVENT_SUBJECT_PLAYERS` on the strength
        # of this site — and the seat the event is about is ``player``, the one
        # tapping. This inline resolution *is* the fire site, still holding that
        # seat, so it executes the instruction against the seat it froze rather
        # than reading it back out of a context it never built.
        amount = int(instruction.payload.get("amount", 1))
        self._deal_damage_to_player(
            player, amount, source=perm,
            then=lambda damage: self.log.append(
                f"{perm.card.name} triggered: {player.name} took {damage} damage"
            ),
        )

    def _tap_lands_sharing_produced_mana(
        self, instruction, tapping_seat: int, land, source
    ) -> None:
        """Mana Web: tap every land that seat controls whose produced-mana set
        overlaps the one just tapped for mana.

        **Types, not colours** (CR 106.1b): a land that taps for {C} answers
        "any type of mana", which is why the sets come off
        ``Permanent.effective_produced_mana`` — the one place the engine asks
        what a land makes, so a land whose types were replaced (Evil Presence),
        whose production was swapped (Quarum Trench Gnomes) or which is a copy
        of another land is compared by what it makes now rather than by what it
        was printed as.

        The land that was tapped is in the set it describes, and is skipped
        rather than tapped again — it is already tapped, so nothing changes
        either way, and skipping keeps the log honest about what this ability
        did.

        The seat is the one that tapped the land, which is what the payload's
        ``controller: that_player`` names and what the lowering refuses any
        other value of.
        """
        produced = {
            str(symbol).upper()
            for symbol in (land.effective_produced_mana or ())
        }
        if not produced:
            return
        described = {
            key: value for key, value in instruction.payload.items()
            if key != "controller"
        }
        from ..subject_filters import subject_matches

        tapped: list[str] = []
        for candidate in self.controlled_by(self.players[tapping_seat]):
            if candidate is land or candidate.tapped:
                continue
            if not subject_matches(
                self, candidate, described,
                observer=tapping_seat, source=source,
            ):
                continue
            if not produced & {
                str(symbol).upper()
                for symbol in (candidate.effective_produced_mana or ())
            }:
                continue
            self.become_tapped(candidate)
            tapped.append(candidate.card.name)
        if tapped:
            self.log.append(
                f"{source.card.name} tapped {', '.join(tapped)}"
            )

    def _return_tapped_land_to_hand(self, land, source) -> None:
        """Storm Cauldron: the land that was just tapped for mana goes home.

        Guarded on the land still being on the battlefield, because two copies
        of this card are two triggers over one event: the second one finds a
        permanent that has already left, and bouncing it again would put a
        second copy of the card into its owner's hand out of nowhere.

        Through the two seams rather than a list rebuild:
        ``remove_from_battlefield`` is the one leave-the-battlefield transition,
        and ``put_card_into_hand`` is CR 903.9b's fire site as well as this one.
        """
        if not self.is_on_battlefield(land):
            return
        owner_index = self.owner_index_of(land)
        if owner_index is None:
            return
        owner = self.players[owner_index]
        self.remove_from_battlefield(land)
        self.put_card_into_hand(owner, land.card, from_battlefield=land)
        self.log.append(
            f"{land.card.name} was returned to {owner.name}'s hand "
            f"({source.card.name})"
        )

    def _add_triggered_land_mana(
        self,
        instruction,
        tapping_player_index: int,
        land,
        produced_symbol: str,
        source,
        *,
        source_name: str | None = None,
    ) -> None:
        """Resolve an ``add_mana_for_tapped_land`` instruction (Mana Flare,
        Gauntlet of Might).

        ``recipient`` names the clause's own subject. "That player" (the player
        who tapped the land) and "its controller" (the land's controller) are
        the same seat here, because a player may only tap lands they control —
        but they are resolved separately rather than assumed equal, so a future
        card that separates them does not silently pay the wrong player.

        **``optional`` is recorded and taken.** "…its controller **may** add an
        additional {U}" (Snowfall) is an offer, and CR 605.4a gives it no
        window in which to be answered: a triggered mana ability resolves
        without using the stack, here, inside the cost payment that tapped the
        land, before the spell being paid for is even announced. Nothing is
        lost by taking it in this engine — there is no mana burn (CR 500.5
        empties the pool at every step boundary and CR 106.4 makes that a loss
        with no penalty), and Snowfall's mana is restricted to cumulative
        upkeep costs, so unspent mana costs its controller nothing. A seat that
        could be asked would be asked here.
        """
        recipient = str(instruction.payload.get("recipient", "that_player"))
        if recipient == "land_controller":
            seat = self.controller_index_of(land)
            if seat is None:
                seat = tapping_player_index
        else:
            seat = tapping_player_index
        player = self.players[seat]

        # "**If that Island is snow**, its controller may add an additional
        # {U}{U} **instead**." (Snowfall.) The alternative *replaces* the base
        # production, so it is chosen here rather than added to it, and the
        # supertype is asked of `has_supertype` — computed through the layers,
        # so an Arcum's Weathervane that thawed the Island stops the upgrade.
        pips = tuple(instruction.payload.get("pips", ()))
        alt_supertype = instruction.payload.get("alt_supertype")
        if alt_supertype and land.has_supertype(str(alt_supertype)):
            pips = tuple(instruction.payload.get("alt_pips", ()))
        # "Spend this mana only to pay cumulative upkeep costs." The bucket is
        # `engine/restricted_mana.py`'s, the same one an activated mana ability
        # writes to, so the three payment paths already ask what it may pay for.
        spend_only = instruction.payload.get("spend_only")
        bucket = (
            player.restricted_mana.setdefault(str(spend_only), {})
            if spend_only else player.mana_pool
        )

        added: list[str] = []
        for symbol, count in pips:  # "an additional {R}"
            bucket[symbol] = bucket.get(symbol, 0) + int(count)
            added.append(f"{{{symbol}}}" * int(count))
        # "One mana of any type that land produced" — the type is whatever the
        # land just made, which is why it cannot be written as pips.
        produced = int(instruction.payload.get("of_type_produced", 0))
        if produced:
            player.mana_pool[produced_symbol] = (
                player.mana_pool.get(produced_symbol, 0) + produced
            )
            added.append(f"{{{produced_symbol}}}" * produced)
        if added:
            extra = " an additional" if instruction.payload.get("additional") else ""
            # A delayed ability's source may have left the battlefield since it
            # was created (CR 603.7d freezes the object, not its zone), so the
            # name the entry froze is what the log falls back to.
            name = source.card.name if source is not None else (
                source_name or "a delayed ability"
            )
            self.log.append(
                f"{name}: {player.name} added{extra} {''.join(added)}"
            )

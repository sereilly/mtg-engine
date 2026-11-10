"""The pregame and the turn's boundary.

The pregame (CR 103): the coin flip (``select_starting_player``), the opening
hands with the Commander setup and the ante slotted where CR 903.6 and
CR 407.2 put them (``deal_opening_hands``), mulligans (``take_mulligan``,
``pregame_mulligan_draw``, and ``mulligan_effective_count`` with CR 800.6's
and CR 903.12g's free first one), the cards a mulligan puts on the bottom
(``put_mulligan_cards_on_bottom``) and keeping a hand (``keep_hand``, and
``keep_opening_hand`` for a flow that bottoms the cards as it keeps).
Whether an AI seat keeps, and what it bottoms, is ``engine/ai_mulligan.py``.

The turn's boundary: ``begin_turn_bookkeeping`` is the one hook both turn
drivers call as a turn begins - the outgoing seat's "last turn" facts are
folded, the per-turn records are reset and the turn's phase plan (CR 500.1)
is laid down - and ``start_turn`` / ``start_next_turn`` are the headless
driver. ``use_channel_mana`` pays life for Channel's {C}.

Tapping a land for mana is ``land_mana_taps.py``, and the CR 106.12 event
the tap raises is ``land_tapped_for_mana.py``.
"""

from __future__ import annotations

from ..game_over_guard import goes_no_further

import random

from ..cast_permissions import expire_at_turn_start as expire_turn_permissions
from ..hand_locks import expire_hand_locks
from ..land_play_allowance import clear_turn_land_play_effects
from ..counter_conditions import clear_next_spell_promises
from ..spell_prohibitions import clear_turn_spell_prohibitions
from ..player_control import asks_a_person, begin_controlled_turn, decider_of
from ..game_types import SimulationResult
from ._constants import phases_after
from ..refusals import refuse


class TurnManagementMixin:
    # -- Who decides for a seat (CR 723, engine/player_control.py) ---------

    def decider_of(self, seat: int) -> int:
        """The seat making *seat*'s choices and decisions right now: its
        controller during a turn another player controls (CR 723.5), else
        itself."""
        return decider_of(self, seat)

    def asks_a_person(self, seat: int) -> bool:
        """Whether a person is asked *seat*'s decisions right now — the
        one membership question about ``interactive_seats``."""
        return asks_a_person(self, seat)

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
            bottom_card_indices = range(
                len(player.hand) - min(n, len(player.hand)), len(player.hand)
            )
        cards_to_bottom = self.put_mulligan_cards_on_bottom(
            player_index, sorted(set(bottom_card_indices), reverse=True)
        )

        self.log.append(
            f"{player.name} took mulligan #{player.mulligans_taken}, drew 7, put {len(cards_to_bottom)}"
            f" card(s) on the bottom, keeping {len(player.hand)}"
        )
        return True

    def put_mulligan_cards_on_bottom(
        self, player_index: int, hand_indices
    ) -> list:
        """CR 103.5's last step of a mulligan: the player "puts a number of
        those cards equal to the number of times that player has taken a
        mulligan on the bottom of their library in any order" — the cards at
        *hand_indices*, in the order given (the first lands nearest the
        middle). Returns the cards moved.

        The one way a mulligan's cards leave the hand: ``take_mulligan`` puts
        them there at once, and the deferred flows — the web table's bottom
        selection and the AI's opening hand (``ai_mulligan``), which choose
        out of the last seven drawn as the hand is kept — through
        :meth:`keep_opening_hand`. Each card goes through the hand and library
        seams (``take_card_from_hand``, ``put_card_into_library``) rather than
        a ``pop``, so a hand holding two copies of one card loses exactly one.
        """
        player = self.players[player_index]
        picked = [player.hand[index] for index in dict.fromkeys(hand_indices)]
        for card in picked:
            self.take_card_from_hand(player_index, card)
            self.put_card_into_library(player_index, card, "bottom")
        return picked

    def keep_opening_hand(self, player_index: int, bottom_indices=()) -> None:
        """Keep the hand drawn by the last mulligan, putting the cards at
        *bottom_indices* on the bottom first (CR 103.5, London mulligan).

        A flow that lets a player choose the cards as they keep rather than as
        they draw — the web table, the AI's mulligans — is the same choice
        out of the same seven cards, and how many it owes is
        :meth:`mulligan_effective_count` (CR 103.5c's free first mulligan
        counted), never the raw number taken.
        """
        self.put_mulligan_cards_on_bottom(player_index, bottom_indices)
        self.keep_hand(player_index)

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

    @goes_no_further()
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
        # "…if you had no cards in hand **at the beginning of this turn**"
        # (Mindstorm Crown). Taken here, as the turn begins and before its
        # untap step, because nothing after this moment is still that moment:
        # the upkeep that asks has its own hand. Every seat, for the reason the
        # per-turn records below reset every seat — the turn began for all.
        self.hand_sizes_at_turn_start = {
            seat: len(player.hand) for seat, player in enumerate(self.players)
        }
        # The turn's phase plan (CR 500.1's five phases, in order), reset here
        # because this is the one hook both drivers call as a turn begins - the
        # headless ``start_turn`` and the web layer's ``_begin_turn``. The
        # beginning phase is the one now starting, so what is left is everything
        # behind it; CR 500.8's extras are inserted into this list as they are
        # created and spent as each phase is entered.
        self.turn_phases_remaining = phases_after("beginning")
        # The new turn's per-seat ordinal — what "your last turn" (Giant
        # Turtle) and "its controller's next turn" (Wall of Dust) compare
        # against. It records turns taken: a skipped turn never reaches this
        # hook (CR 500.11 — the engine's skips are spent by
        # ``_compute_next_active_player``, Time Vault's is decided as the turn
        # would begin, ``Game.seat_after_skipped_turn``).
        self.seat_turn_counts[player_index] = self.seat_turn_counts.get(player_index, 0) + 1
        self.active_player_index = player_index
        # CR 723.1: a control from an earlier turn ends as this one begins,
        # and one waiting for this seat's next turn actually taken starts
        # (the skipped turns were spent before this hook, CR 723.1b).
        begin_controlled_turn(self, player_index)
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
        # "The next … spell you cast **this turn** can't be countered."
        # (Overmaster.) A promise no spell spent ends with its turn.
        clear_next_spell_promises(self)
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
        self.draw_charge_sources = {}
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
        # A simultaneous damage dealing (engine/simultaneous_damage.py) ends
        # with the step or the sweep that opened it; one still open at a new
        # turn was abandoned on an unanswered question and holds nothing anyone
        # will finish.
        self.simultaneous_damage = None
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
            player.nontoken_creatures_put_into_your_graveyard_this_turn = 0
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
        # inside it, two ways: Winter Orb's untap-land selection and Old Man
        # of the Sea's keep-tapped choice. A player answering either saw last
        # turn's P/T and keywords. (Time Vault's skip is asked before this
        # hook, as the turn would begin: the board it is answered on is the
        # last turn's, which is the true one.)
        self._recalculate_lord_buffs()
        self._refresh_dynamic_creatures()

    @goes_no_further()
    def start_turn(self, player_index: int) -> None:
        self.begin_turn_bookkeeping(player_index)
        self.resolve_untap_step(player_index)
        self.resolve_upkeep(player_index)
        self.resolve_draw_step(player_index)
        # The phase after the beginning phase, asked of the turn's plan rather
        # than named here (CR 500.1). With nothing added that is the precombat
        # main phase, exactly as this line used to say outright.
        self.enter_next_turn_phase("beginning")

    @goes_no_further(lambda game: game.active_player_index)
    def start_next_turn(self) -> int:
        self.turn += 1
        next_player = self._compute_next_active_player()
        self.start_turn(next_player)
        return next_player

    def use_channel_mana(self, player_index: int, amount: int) -> SimulationResult:
        """Pay `amount` life via an active Channel effect to add that many {C} mana."""
        player = self.players[player_index]
        if not player.channel_active_until_eot:
            return refuse("Channel", "spell_pattern", "Channel is not active")
        if amount <= 0:
            return refuse("Channel", "spell_pattern", "Amount must be positive")
        if amount > player.life:
            # CR 118.3: a player can pay any amount of life up to their total,
            # including all of it, but no more.
            return refuse(
                "Channel", "spell_pattern",
                f"cannot pay {amount} life with only {player.life} remaining",
            )
        player.life -= amount
        player.mana_pool["C"] = player.mana_pool.get("C", 0) + amount
        self.log.append(f"{player.name} paid {amount} life for {amount} {{C}}")
        # Paying down to 0 is legal; the player then loses to SBAs (704.5a).
        self.check_state_based_actions()
        return SimulationResult("Channel", True, "spell_pattern", f"added {amount} C")

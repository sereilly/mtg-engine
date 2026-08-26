from __future__ import annotations

import dataclasses
import random

from ..auras import aura_additional_mana_on_tap
from ..card_hooks import ENCHANTED_LAND_TAPPED_FOR_MANA
from ..hand_locks import expire_hand_locks
from ..game_types import OracleExecutionContext, SimulationResult
from ..oracle import compile_card_oracle
from ..trigger_utils import iter_triggered_abilities

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
            # CR 103.4's opening hand, and one of the three draws that stay off
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

        The hand was drawn before the game's first turn (CR 103.4), and so were
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
        # The new turn's per-seat ordinal — what "your last turn" (Giant
        # Turtle) and "its controller's next turn" (Wall of Dust) compare
        # against. A skipped turn (Time Vault) still increments: the skip is
        # decided after the turn has begun, and the ordinal records beginnings.
        self.seat_turn_counts[player_index] = self.seat_turn_counts.get(player_index, 0) + 1
        self.active_player_index = player_index
        self.lands_played_this_turn[player_index] = 0
        # "Until that player's next turn" (Firestorm Phoenix) is an ordinal
        # against the counter just incremented, so this drops what has expired
        # rather than deciding anything — engine/hand_locks.py derives the
        # answer either way.
        expire_hand_locks(self)
        self.creatures_died_this_turn = 0
        self.nontoken_creatures_died_this_turn = 0
        self.permanents_to_hand_this_turn = {}
        # Aladdin's Lamp: an armed "next draw this turn" replacement expires
        # with the turn it was activated on.
        self.lamp_draw_replacements = {}
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
            player.spells_cast_this_turn = []

    def start_turn(self, player_index: int) -> None:
        self.begin_turn_bookkeeping(player_index)
        self.resolve_untap_step(player_index)
        self.resolve_upkeep(player_index)
        self.resolve_draw_step(player_index)
        self._enter_main_phase(precombat=True)

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
    def _land_mana_instruction(land):
        """The instruction a land's own ``{T}: Add …`` ability produces, or None.

        None for a basic (no compiled ability at all) and for a land whose only
        abilities are something else — Bazaar of Baghdad draws and discards, and
        must not be mistaken for a mana source here.

        Requires the ability's cost to be the tap alone: this entry point has
        already tapped the land and charges nothing further, so an ability
        wanting mana or a sacrifice on top would be performed unpaid.
        """
        from ..mana_payment import is_mana_ability

        for ability in compile_card_oracle(land.effective_card).activated_abilities:
            instruction = ability.instruction
            if instruction is None or not ability.supported:
                continue
            cost = ability.cost
            if not cost.requires_tap or not _is_free_beyond_tapping(cost):
                continue
            if is_mana_ability(ability) or instruction.kind == "if_then":
                return instruction
        return None

    def tap_land_for_mana(
        self,
        player_index: int,
        land_name: str,
        chosen_color: str = "G",
        permanent_index: int | None = None,
        kudzu_reattach_index: int | None = None,
        defer_kudzu_choice: bool = False,
    ) -> bool:
        player = self.players[player_index]
        resolved = self._find_controlled_permanent(player, land_name, permanent_index)
        land = resolved[1] if resolved else None
        if land is not None and land.card.primary_type != "land":
            land = None
        if land is None or land.tapped:
            return False

        # A land with no mana ability at all (Island of Wak-Wak, Bazaar of
        # Baghdad) can't be tapped for mana — without this, the color fallback
        # below would invent a green mana out of nothing.
        if not land.effective_produced_mana:
            if not land.basic_land_types:
                return False

        # CR 701.26a's event, announced by the one tap seam. City of Brass
        # ("Whenever this land becomes tapped, it deals 1 damage to you") and
        # Psychic Venom ("Whenever enchanted land becomes tapped…") each used to
        # be dispatched by a hand-written pass here, which meant each fired on
        # *this* tapper and on none of the others — an Icy Manipulator, an
        # attack cost, or any of the other places `become_tapped` is called.
        # Both are ordinary `permanent_becomes_tapped` triggers now, so they go
        # on the stack (CR 603.3) from wherever the tap happens.
        self.become_tapped(land)
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
        mana_ability = self._land_mana_instruction(land)
        if mana_ability is not None:
            instruction = mana_ability
            if chosen_color:
                # The colour arrives the way the activation path delivers it,
                # so "tap Badlands for {R}" keeps meaning what it did; the
                # handler ignores it unless the printed clause offers a choice.
                instruction = dataclasses.replace(
                    instruction,
                    payload={**instruction.payload, "color": chosen_color},
                )
            self._execute_oracle_instruction(
                instruction,
                OracleExecutionContext(
                    caster=player,
                    target=player,
                    card=land.card,
                    source_permanent=land,
                ),
            )
        else:
            mana_symbol = chosen_color
            produced = land.effective_produced_mana
            if produced:
                if chosen_color in produced:
                    mana_symbol = chosen_color
                else:
                    mana_symbol = produced[0]
            else:
                symbols = land.basic_land_mana
                if symbols:
                    mana_symbol = symbols[0]
            player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1

        self.log.append(f"{player.name} tapped {land_name} for mana")

        # An Aura enchanting this land may have bespoke "when tapped for mana"
        # behavior (Kudzu destroys the land and re-attaches). Keyed by Aura name
        # in card_hooks so the card name stays out of this core flow; the hook
        # may set pending_kudzu_reattach for the interactive reattach choice. It
        # detaches the Aura from this land, so the generic trigger pass below
        # then sees no Aura here.
        aura = land.metadata.get("attached_aura")
        if aura is not None:
            tapped_hook = ENCHANTED_LAND_TAPPED_FOR_MANA.get(aura.card.name)
            if tapped_hook is not None:
                tapped_hook(
                    self, player_index, land, resolved[0], aura,
                    kudzu_reattach_index, defer_kudzu_choice,
                )

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
            extra = aura_additional_mana_on_tap(attached_aura.effective_card.oracle_text)
            if extra:
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
            # "Whenever a **Mountain** is tapped for mana" — the narrowing rides
            # the condition's payload, so the land type is data rather than a
            # per-card hook. has_type, so a land made a Mountain by a layer-4
            # effect counts.
            subtype = trig.condition.payload.get("tapped_land_subtype")
            if subtype and not land.has_type(str(subtype)):
                continue
            if trig.instruction.kind == "add_mana_for_tapped_land":
                self._add_triggered_land_mana(
                    trig.instruction, player_index, land, mana_symbol, perm
                )
                continue
            amount = int(trig.instruction.payload.get("amount", 1))
            self._deal_damage_to_player(
                player, amount, source=perm,
                then=lambda damage: self.log.append(
                    f"{perm.card.name} triggered: {player.name} took {damage} damage"
                ),
            )

        return True

    def _add_triggered_land_mana(
        self,
        instruction,
        tapping_player_index: int,
        land,
        produced_symbol: str,
        source,
    ) -> None:
        """Resolve an ``add_mana_for_tapped_land`` instruction (Mana Flare,
        Gauntlet of Might).

        ``recipient`` names the clause's own subject. "That player" (the player
        who tapped the land) and "its controller" (the land's controller) are
        the same seat here, because a player may only tap lands they control —
        but they are resolved separately rather than assumed equal, so a future
        card that separates them does not silently pay the wrong player.
        """
        recipient = str(instruction.payload.get("recipient", "that_player"))
        if recipient == "land_controller":
            seat = self.controller_index_of(land)
            if seat is None:
                seat = tapping_player_index
        else:
            seat = tapping_player_index
        player = self.players[seat]

        added: list[str] = []
        for symbol, count in instruction.payload.get("pips", ()):  # "an additional {R}"
            player.mana_pool[symbol] = player.mana_pool.get(symbol, 0) + int(count)
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
            self.log.append(
                f"{source.card.name}: {player.name} added{extra} {''.join(added)}"
            )

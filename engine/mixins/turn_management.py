from __future__ import annotations

import dataclasses
import random

from ..auras import aura_additional_mana_on_tap
from ..delayed_triggers import matching_delayed_triggers
from ..hand_locks import expire_hand_locks
from ..game_types import OracleExecutionContext, SimulationResult
from ..oracle import compile_card_oracle
from ..replacements import apply_replacements
from ..trigger_utils import iter_triggered_abilities


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
        self.destroyed_at_end_of_combat_this_turn = []
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
            player.creatures_put_into_your_graveyard_this_turn = 0
            player.spells_cast_this_turn = []
            player.attacked_this_turn = False
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
            {"land": land, "player": player, "produced": None},
        )
        swapped_to = mana_event.get("produced")
        pool_before = dict(player.mana_pool) if swapped_to else {}
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
            produced = land.effective_produced_mana
            if produced:
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

        if swapped_to:
            moved = 0
            for symbol, amount in list(player.mana_pool.items()):
                gained = int(amount) - int(pool_before.get(symbol, 0))
                if gained > 0 and symbol != swapped_to:
                    player.mana_pool[symbol] = int(amount) - gained
                    moved += gained
            if moved:
                player.mana_pool[swapped_to] = (
                    player.mana_pool.get(swapped_to, 0) + moved
                )
                self.log.append(
                    f"{land_name} produced {{{swapped_to}}} instead"
                )
            # "One mana of any type **that land produced**" is what came out,
            # not what would have: a Mana Flare over a Ritual of Subdual board
            # matches the colourless the land really made.
            mana_symbol = swapped_to

        self.log.append(f"{player.name} tapped {land_name} for mana")

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
            # "Whenever a player taps a **snow** land for mana" (Winter's
            # Night). A supertype (CR 205.4a), not a type, so it is asked of
            # `has_supertype` — the accessor the type test above would answer
            # False for on every land, which is a trigger that never fires
            # rather than one that fires too often. Layer 4 either way: a land
            # an effect *made* snow counts and one that stopped being snow does
            # not.
            supertype = trig.condition.payload.get("tapped_land_supertype")
            if supertype and not land.has_supertype(str(supertype)):
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
        lost by taking it in this engine — there is no mana burn (CR 500.4
        empties the pool at every step boundary), and Snowfall's mana is
        restricted to cumulative upkeep costs, so unspent mana costs its
        controller nothing. A seat that could be asked would be asked here.
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

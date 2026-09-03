from __future__ import annotations

"""Upkeep-trigger effects (CR 503), registered by (trigger condition, instruction kind).

``resolve_upkeep`` used to dispatch these with a hand-written if-chain — one
branch per card shape, ~430 lines of it — which meant supporting a new upkeep
card required editing turn-structure control flow. They are registry entries
now: :func:`upkeep_effect` keys a function by the pair the compiler already
produces (``trig.condition.kind``, ``trig.instruction.kind``) and the upkeep
step looks it up.

These are the *interactive* upkeep triggers specifically. An ordinary "at the
beginning of upkeep" effect goes on the stack and runs through EFFECT_HANDLERS
like anything else; the ones here are the pay-or-consequence shapes whose prompt
protocol (``human_choices`` / ``mana_prevention`` / ``sacrifice_choices`` /
``optional_choices`` / ``trigger_targets``) is driven directly by the web layer,
so they resolve inline while that answer is in hand. Folding them into the
generic pending-choice queue is phase 4's job; giving them a registry is not
blocked on it.

Everything a handler may read arrives on :class:`UpkeepContext` — including the
five prompt channels, so a new effect can join the protocol without changing
this seam.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable


if TYPE_CHECKING:
    from ..models import Permanent, PlayerState


@dataclass
class UpkeepContext:
    """One upkeep trigger about to resolve.

    player_index -- the seat whose upkeep it is (not necessarily the source's
                    controller: "at the beginning of EACH player's upkeep")
    controller   -- controller of the permanent the trigger came from
    permanent    -- that permanent
    trig         -- the compiled TriggeredAbility (condition + instruction)
    enqueue_damage -- queue an upkeep damage event onto the stack rather than
                    dealing it inline (CR 603.3)
    """

    game: Any
    player_index: int
    controller: "PlayerState"
    permanent: "Permanent"
    trig: Any
    cond: str
    kind: str
    human_choices: dict | None
    optional_choices: dict | None
    mana_prevention: dict | None
    sacrifice_choices: dict | None
    trigger_targets: dict | None
    enqueue_damage: Callable


def offer_declined(human_choices: dict | None, permanent) -> bool:
    """Whether the controller answered "no" at *permanent*'s upkeep prompt.

    The prompt protocol is keyed by printed card name on **both** sides — the
    arming side in ``upkeep_step.get_upkeep_pay_triggers`` and the reading side
    here — so the name is read once, in one place, rather than twice per
    handler in every handler. A seat that was never asked has not declined,
    which is what makes the headless and AI paths pay by default.

    Written as "declined" rather than "chose": the two are not complements for
    a seat with no entry, and every caller wants the same reading — *this*
    seat said no. `paid = not declined(...) and can_pay(...)` is then one line
    with one meaning, where the if/else it replaces spelled the affordability
    test twice and could drift between the branches.
    """
    if human_choices is None:
        return False
    name = permanent.card.name
    return name in human_choices and not human_choices[name]


UpkeepEffect = Callable[[Any, UpkeepContext], None]

UPKEEP_EFFECTS: dict[tuple[str, str], UpkeepEffect] = {}


def upkeep_effect(cond: str, kind: str) -> Callable[[UpkeepEffect], UpkeepEffect]:
    """Register the handler for one (trigger condition, instruction kind) pair.

    A duplicate pair raises at import: the if-chain resolved collisions by
    source order, which is exactly the kind of silent precedence this registry
    exists to remove.
    """

    def decorator(fn: UpkeepEffect) -> UpkeepEffect:
        key = (cond, kind)
        if key in UPKEEP_EFFECTS:
            raise ValueError(
                f"upkeep effect {key} already handled by {UPKEEP_EFFECTS[key].__name__}"
            )
        UPKEEP_EFFECTS[key] = fn
        return fn

    return decorator


class UpkeepEffectsMixin:
    """The registered handlers. Composed onto UpkeepStepMixin, so each body
    still calls the game's own helpers through ``self`` exactly as it did
    inside resolve_upkeep."""

    @upkeep_effect("upkeep_self", "upkeep_wind_counter_pay_or_sacrifice")
    def _on__upkeep_self__upkeep_wind_counter_pay_or_sacrifice(self, ctx: UpkeepContext) -> None:
        from ..cumulative_upkeep import scaled_cost
        from ..named_counters import add_counters

        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        # Cyclone: add a wind counter, then pay {G} per counter
        # or sacrifice; paying deals counter-many damage to each
        # creature and each player.
        #
        # The counter goes through `named_counters` and the cost through
        # `scaled_cost` — the same two seams cumulative upkeep uses, because
        # this is CR 702.24a's sentence with "wind" printed where the keyword
        # says "age". What stays this card's is the damage rider below.
        counters = add_counters(permanent, "wind", 1)
        self.log.append(f"{permanent.card.name} gains a wind counter ({counters} total)")
        cost = scaled_cost(ctx.trig.instruction, counters)
        paid = not offer_declined(human_choices, permanent) and self.can_pay_upkeep_cost(
            controller, cost
        )
        if paid:
            self.pay_upkeep_cost(controller, cost, reason=permanent.card.name)
            self.log.append(
                f"{controller.name} paid {counters} green for {permanent.card.name}"
            )
            for victim in self.players:
                self._deal_damage_to_player(victim, counters, source=permanent)
            for victim in self.players:
                for perm in list(victim.battlefield):
                    if perm.is_creature:
                        self._mark_damage_on_permanent(perm, counters, source=permanent)
            self.log.append(
                f"{permanent.card.name} dealt {counters} damage to each creature and each player"
            )
        else:
            self.sacrifice_permanent(permanent)
            self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")

    @upkeep_effect("upkeep_self", "cumulative_upkeep")
    def _on__upkeep_self__cumulative_upkeep(self, ctx: UpkeepContext) -> None:
        """Cumulative upkeep (CR 702.24a), the ability the keyword *is*.

        "Put an age counter on this permanent. Then you may pay [cost] for each
        age counter on it. If you don't, sacrifice it." The counter goes on
        first and unconditionally, so the cost this resolution asks for already
        counts it — which is why ``scaled_cost`` is handed the new total
        rather than being left to look one up.

        Partial payment is not allowed (702.24a's last sentence), which is what
        ``can_pay_upkeep_cost`` already answers: it is asked about the whole
        escalated cost — mana, life and sacrifice together — and a player who
        cannot cover all of it pays none of it.
        """
        from ..cumulative_upkeep import AGE_COUNTER, scaled_cost
        from ..named_counters import add_counters

        controller = ctx.controller
        permanent = ctx.permanent
        counter = str(ctx.trig.instruction.payload.get("per_counter") or AGE_COUNTER)
        total = add_counters(permanent, counter, 1)
        self.log.append(
            f"{permanent.card.name} gains an {counter} counter ({total} total)"
        )
        cost = scaled_cost(ctx.trig.instruction, total)
        # `can_pay_upkeep_cost` / `pay_upkeep_cost`, the pair every cost in this
        # file that is more than mana goes through — never a hand-rolled pool
        # read. Their mana half knows that generic mana can come from floating
        # mana *or* from tapping a land during upkeep, which is the difference
        # between a {1} that is free and a {1} that costs a land; the other two
        # halves are Glacial Chasm's life and Polar Kraken's land.
        # "Spend this mana only to pay cumulative upkeep costs." (Adarkar
        # Unicorn, Snowfall.) The purpose is what lets that bucket be seen at
        # all: restricted mana lives beside the pool, and a payment that does
        # not say what it is for is offered none of it.
        from ..restricted_mana import CUMULATIVE_UPKEEP, PaymentPurpose

        purpose = PaymentPurpose(CUMULATIVE_UPKEEP, source=permanent)
        human_choices = ctx.human_choices
        paid = not offer_declined(human_choices, permanent) and self.can_pay_upkeep_cost(
            controller, cost, purpose=purpose
        )
        if paid:
            self.pay_upkeep_cost(
                controller, cost, reason=permanent.card.name, purpose=purpose,
                source=permanent,
            )
            self.log.append(
                f"{controller.name} paid cumulative upkeep "
                f"({cost.describe()}) for {permanent.card.name}"
            )
        else:
            # "When a player doesn't pay this enchantment's cumulative upkeep,
            # that player exiles all cards from their library." (Thought Lash.)
            # CR 702.24a's non-payment is decided here and nowhere else, so this
            # is the trigger's one fire site — announced **before** the
            # sacrifice, because a permanent already in a graveyard is not one
            # `iter_triggered_abilities` scans, and CR 603.3 wants the ability on
            # the stack over the sacrifice either way.
            #
            # The seat is frozen on the event: nothing on a board records who
            # declined to pay, and "that player" behind it names exactly them.
            from ..events import emit

            emit(
                self, "cumulative_upkeep_unpaid",
                subject=permanent,
                event_subject_player=self.seat_index(controller),
            )
            self.sacrifice_permanent(permanent)
            self.log.append(
                f"{controller.name} sacrificed {permanent.card.name} to cumulative upkeep"
            )

    @upkeep_effect("upkeep_self", "upkeep_pay_or_sacrifice_enchantment")
    def _on__upkeep_self__upkeep_pay_or_sacrifice_enchantment(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        trig = ctx.trig
        mana: dict[str, int] = trig.instruction.payload.get("mana", {})
        # `can_pay_upkeep_mana` / `_spend_upkeep_mana`, the pair the wind-counter
        # handler beside this one already uses — never a hand-rolled pool read.
        # Both of these used to test the *coloured* pips alone:
        #
        #     paid = all(pool[sym] >= count for sym, count in mana.items()
        #                if sym != "generic")
        #
        # which is vacuously True for a cost with no coloured pips at all. Energy
        # Flux grants every artifact "sacrifice this artifact unless you pay
        # {2}", a generic-only cost, so every artifact on the board paid it for
        # free — and a partly generic {1}{U} charged the {U} and waived the {1}.
        # The helpers know that generic mana can come from floating mana *or*
        # from tapping a land during upkeep, which a pool read cannot see.
        if human_choices is not None and permanent.card.name in human_choices:
            paid = bool(human_choices[permanent.card.name]) and self.can_pay_upkeep_mana(
                controller, mana
            )
        else:
            paid = self.can_pay_upkeep_mana(controller, mana)
        if paid:
            self._spend_upkeep_mana(controller, mana)
            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
        else:
            self.sacrifice_permanent(permanent)
            self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")

    @upkeep_effect("upkeep_each", "deal_damage")
    def _on__upkeep_each__deal_damage(self, ctx: UpkeepContext) -> None:
        _enqueue_upkeep_damage = ctx.enqueue_damage
        controller = ctx.controller
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
        raw_amount = trig.instruction.payload.get("amount", 1)
        if raw_amount == "x":
            amount = self.untapped_lands_at_turn_start.get(player_index, 0)
        else:
            amount = int(raw_amount)
        _enqueue_upkeep_damage(
            permanent, self.players.index(controller), player_index, amount, trig.source_line
        )

    @upkeep_effect("upkeep_self", "deal_damage")
    def _on__upkeep_self__deal_damage(self, ctx: UpkeepContext) -> None:
        _enqueue_upkeep_damage = ctx.enqueue_damage
        controller = ctx.controller
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
        # Unconditional self-damage at the controller's own upkeep
        # (Juzám Djinn, Serendib Efreet: "this creature deals N
        # damage to you"). The upkeep_self guard above already
        # ensures controller is player_index, so the victim is the
        # controller.
        raw_amount = trig.instruction.payload.get("amount", 1)
        if raw_amount == "x":
            amount = self.untapped_lands_at_turn_start.get(player_index, 0)
        else:
            amount = int(raw_amount)
        _enqueue_upkeep_damage(
            permanent, self.players.index(controller), player_index, amount, trig.source_line
        )

    @upkeep_effect("upkeep_self", "upkeep_damage_unless_cost")
    def _on__upkeep_self__upkeep_damage_unless_cost(self, ctx: UpkeepContext) -> None:
        """"<source> deals N damage to you unless you <cost>. If it deals damage
        to you this way, tap it." (Mishra's War Machine, Minion of Leshrac.)

        Two riders the previous parse dropped, and they interact: the tap only
        happens on the *damage* branch, so it cannot be a separate instruction.

        **The cost is payload.** Mishra's War Machine discards a card and Minion
        of Leshrac sacrifices a creature other than itself; everything else
        about the sentence, and everything this does with it, is the same. It
        used to be one card hook keyed on Mishra's whole printed line, number
        and cost baked in, so the second card printing the template got nothing.

        With no way to pay there is no choice — the damage is taken and the
        source taps. Otherwise the controller pays; headless and AI play pay,
        which is deterministic and keeps the permanent untapped, and an
        interactive prompt can replace it without changing what the rules do
        here.
        """
        controller = ctx.controller
        permanent = ctx.permanent
        trig = ctx.trig
        payload = trig.instruction.payload
        amount = int(payload.get("amount", 0))
        taps_source = bool(payload.get("taps_source"))

        if payload.get("discard") and controller.hand:
            discarded = controller.hand.pop(0)
            # Through the one discard seam, not a bare graveyard append: this
            # skipped Library of Leng's CR 701.9c replacement *and* the card's
            # own discard trigger, which is what a second spelling of a move
            # always costs.
            self._discard_card(controller, discarded)
            self.log.append(
                f"{controller.name} discarded {discarded.name} to {permanent.card.name}"
            )
            return

        described = payload.get("sacrifice")
        if described is not None:
            # The charger's own candidate reader, and the exclusion compared by
            # identity: "a creature **other than this creature**" rules out
            # exactly one permanent, and `in`/`==` on a Permanent would match a
            # look-alike instead.
            seat = self.seat_index(controller)
            exclude = permanent if payload.get("exclude_self") else None
            if self._sacrifice_candidate_indices(controller, described, exclude):
                self.arm_forced_sacrifice(
                    seat, 1, filter=described, exclude=exclude,
                    reason=permanent.card.name,
                )
                return

        ctx.enqueue_damage(
            permanent,
            self.players.index(controller),
            ctx.player_index,
            amount,
            trig.source_line,
        )
        if taps_source:
            self.become_tapped(permanent)
            self.log.append(f"{permanent.card.name} tapped (it dealt damage this way)")

    # ("upkeep_self", "upkeep_put_counter_on_self") was Armageddon Clock's
    # entry — "put a doom counter on this artifact", read as one fused kind
    # because the grammar had no production for a CR 122.1 counter. It has one
    # now (`add_named_counter_to_self`), the trigger takes the ordinary
    # on-the-stack route, and the counter lands in the one store both the
    # removal handler and the draw-step damage already read. Removed rather than
    # left dark, on the reachability guard's insistence.

    @upkeep_effect("upkeep_self", "upkeep_gain_life_over_hand_size")
    def _on__upkeep_self__upkeep_gain_life_over_hand_size(self, ctx: UpkeepContext) -> None:
        """Ivory Tower. Never negative: "minus 4" with three cards in hand
        gains nothing, it does not drain."""
        controller = ctx.controller
        floor = int(ctx.trig.instruction.payload.get("floor", 0))
        amount = max(0, len(controller.hand) - floor)
        if amount:
            self._gain_life(controller, amount, ctx.permanent.card.name)

    @upkeep_effect("upkeep_each", "deal_damage_equal_to_swamps")
    def _on__upkeep_each__deal_damage_equal_to_swamps(self, ctx: UpkeepContext) -> None:
        _enqueue_upkeep_damage = ctx.enqueue_damage
        controller = ctx.controller
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
        swamp_count = sum(
            1 for perm in self.controlled_by(player_index) if perm.has_type("swamp")
        )
        _enqueue_upkeep_damage(
            permanent, self.players.index(controller), player_index, swamp_count, trig.source_line
        )

    @upkeep_effect("upkeep_enchanted_controller", "deal_damage")
    def _on__upkeep_enchanted_controller__deal_damage(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        mana_prevention = ctx.mana_prevention
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
        # This covers Auras that read "At the beginning of the upkeep of
        # enchanted enchantment's controller, this Aura deals N damage to that player."
        attached = permanent.metadata.get("attached_to")
        if attached is None:
            return
        if self.controller_index_of(attached) != player_index:
            return
        amount = int(trig.instruction.payload.get("amount", 1))
        victim = self.players[player_index]
        # Power Leak / Errant Minion: "that player may pay any amount of mana.
        # … Prevent X of that damage, where X is the amount of mana that player
        # paid this way." The damaged player may pay up to `amount` mana to
        # prevent that much damage.
        #
        # Read off the *payload*, not off a substring of the permanent's text.
        # The substring was the gate and the dispatch agreeing by coincidence:
        # the clause reached this handler only because a card hook keyed on
        # Power Leak's whole printed line produced the instruction, so Errant
        # Minion — the same sentence one noun over — got the substring's "yes"
        # and no instruction at all. One production reads the clause now
        # (`upkeep._parse_pay_mana_to_prevent_upkeep_damage`) and stamps
        # this key, so what is offered is exactly what was read.
        if trig.instruction.payload.get("prevent_up_to_paid_mana"):
            requested = 0
            if mana_prevention is not None and permanent.card.name in mana_prevention:
                requested = max(0, int(mana_prevention[permanent.card.name]))
            available = sum(victim.mana_pool.get(s, 0) for s in victim.mana_pool)
            paid = min(requested, amount, available)
            remaining = paid
            for sym in list(victim.mana_pool):
                while remaining > 0 and victim.mana_pool.get(sym, 0) > 0:
                    victim.mana_pool[sym] -= 1
                    remaining -= 1
            amount = max(0, amount - paid)
            if paid:
                self.log.append(f"{victim.name} paid {paid} mana to prevent {paid} damage from {permanent.card.name}")
        self._deal_damage_to_player(
            victim, amount, source=permanent,
            then=lambda damage: self.log.append(
                f"{permanent.card.name} dealt {damage} upkeep damage to {victim.name}"
            ),
        )

    @upkeep_effect("upkeep_enchanted_controller", "add_pt_counters_to_attached")
    def _on__upkeep_enchanted_controller__add_pt_counters_to_attached(
        self, ctx: UpkeepContext
    ) -> None:
        """"At the beginning of the upkeep of enchanted creature's controller,
        put a -1/-1 counter on that creature." (Unstable Mutation; Takklemaggot
        prints the same sentence with a -0/-1 pair.)

        The counters are real CR 122.1a counters, not an Aura grant — they stay
        if the Aura leaves, and CR 704.5f/704.5q apply — so the placement goes
        through ``place_pt_counters``, which writes the counter record and the
        P/T channel together.

        The CR 122.1a pair is payload, so a card printing any other one needs
        nothing here. This replaced a loop over every enchantment on every
        battlefield that matched one hard-coded instruction kind
        (``add_minus1_counter_to_enchanted``), reached by a card-name hook whose
        key spelled out "-1/-1".
        """
        permanent = ctx.permanent
        attached = permanent.metadata.get("attached_to")
        if attached is None:
            return
        if self.controller_index_of(attached) != ctx.player_index:
            return
        payload = ctx.trig.instruction.payload
        kind = str(payload.get("counter", ""))
        count = int(payload.get("count", 1))
        placed = self.place_pt_counters(attached, kind, count)
        if placed:
            self.log.append(
                f"{permanent.card.name}: {attached.card.name} gets "
                + (f"a {kind} counter" if placed == 1 else f"{placed} {kind} counters")
            )
            # CR 704.5f: a creature decayed to 0 toughness dies now.
            self.check_state_based_actions()

    @upkeep_effect("upkeep_enchanted_controller", "remove_counter_from_attached")
    def _on__upkeep_enchanted_controller__remove_counter_from_attached(self, ctx: UpkeepContext) -> None:
        """"At the beginning of the upkeep of enchanted creature's controller,
        remove a sleep counter from that creature." (Venarian Gold.)

        Nothing interactive: one counter of the named kind comes off the
        enchanted creature, and when the last one goes the untap restriction
        the counter conditions simply stops answering
        (auras.aura_restriction_active reads the count at ask time) — so the
        creature untaps again on its controller's next untap step with nothing
        to clear.
        """
        from ..named_counters import counters_on, remove_counters

        permanent = ctx.permanent
        attached = permanent.metadata.get("attached_to")
        if attached is None:
            return
        if self.controller_index_of(attached) != ctx.player_index:
            return
        counter = str(ctx.trig.instruction.payload.get("counter", ""))
        current = counters_on(attached, counter)
        if current <= 0:
            return
        remove_counters(attached, counter)
        self.log.append(
            f"{permanent.card.name}: removed a {counter} counter from "
            f"{attached.card.name} ({current - 1} left)"
        )

    @upkeep_effect("upkeep_each", "upkeep_chosen_player_hand_overflow_damage")
    @upkeep_effect("upkeep_chosen", "upkeep_chosen_player_hand_overflow_damage")
    def _on__upkeep_chosen__upkeep_chosen_player_hand_overflow_damage(self, ctx: UpkeepContext) -> None:
        _enqueue_upkeep_damage = ctx.enqueue_damage
        controller = ctx.controller
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
        # Two conditions, one arithmetic. Black Vise and The Rack name a player
        # as they enter and fire on that seat's upkeep; Storm World names none
        # and fires on every seat's. The chosen-player gate therefore belongs
        # to the *condition*, not to the effect — asking for
        # `chosen_player_index` under `upkeep_each` would read a key Storm
        # World never sets, compare it against a real seat and silently deal
        # nothing at all.
        if ctx.cond == "upkeep_chosen":
            chosen = permanent.metadata.get("chosen_player_index")
            if chosen != player_index:
                return
        victim = self.players[player_index]
        # Black Vise counts the excess over the threshold, The Rack the
        # shortfall below it. Both floor at zero: neither card heals.
        base = int(trig.instruction.payload.get("base", 4))
        if trig.instruction.payload.get("direction") == "deficit":
            damage = max(0, base - len(victim.hand))
        else:
            damage = max(0, len(victim.hand) - base)
        if damage > 0:
            _enqueue_upkeep_damage(
                permanent, self.players.index(controller), player_index, damage, trig.source_line
            )

    @upkeep_effect("upkeep_self", "upkeep_pay_or_deal_damage_to_controller")
    def _on__upkeep_self__upkeep_pay_or_deal_damage_to_controller(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        trig = ctx.trig
        mana = trig.instruction.payload.get("mana", {})
        damage_amt = int(trig.instruction.payload.get("damage", 0))
        # The pay-or-sacrifice handler's pair, for its reason and one more:
        # this read the coloured pips off the floating pool alone, spent
        # nothing else, and honoured a human "pay" without asking whether the
        # pool could cover it — so the price was unpayable on every AI turn
        # however many lands stood untapped, and free for a human with an
        # empty pool.
        if human_choices is not None and permanent.card.name in human_choices:
            paid = bool(human_choices[permanent.card.name]) and self.can_pay_upkeep_mana(
                controller, mana
            )
        else:
            paid = self.can_pay_upkeep_mana(controller, mana)
        if paid:
            self._spend_upkeep_mana(controller, mana)
            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
        else:
            self._deal_damage_to_player(
                controller, damage_amt, source=permanent,
                then=lambda dealt: self.log.append(
                    f"{permanent.card.name} dealt {dealt} upkeep damage to {controller.name}"
                ),
            )

    @upkeep_effect("upkeep_self", "upkeep_pay_to_untap_self")
    def _on__upkeep_self__upkeep_pay_to_untap_self(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        trig = ctx.trig
        # Mana Vault / Basalt Monolith: "you may pay {N}. If you do,
        # untap this artifact." No consequence on decline; the
        # beneficial default (AI/headless) untaps when affordable.
        # A human accept is honored only when the cost is actually
        # payable — choosing "pay" with no mana must not untap for free.
        mana = trig.instruction.payload.get("mana", {})
        if human_choices is not None and permanent.card.name in human_choices:
            paid = human_choices[permanent.card.name]
        else:
            paid = True
        paid = paid and self.can_pay_upkeep_mana(controller, mana)
        if paid and permanent.tapped:
            self._spend_upkeep_mana(controller, mana)
            ctx.game.become_untapped(permanent)
            self.log.append(f"{controller.name} paid to untap {permanent.card.name}")

    @upkeep_effect("upkeep_enchanted_controller", "upkeep_pay_to_untap_enchanted")
    def _on__upkeep_enchanted_controller__upkeep_pay_to_untap_enchanted(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
        # Paralyze: "that player may pay {N}. If the player does, untap
        # the creature." The enchanted creature's controller decides.
        attached = permanent.metadata.get("attached_to")
        if attached is None:
            return
        if self.controller_index_of(attached) != player_index:
            return
        payer = self.players[player_index]
        mana = trig.instruction.payload.get("mana", {})
        if human_choices is not None and permanent.card.name in human_choices:
            paid = human_choices[permanent.card.name]
        else:
            paid = True
        paid = paid and self.can_pay_upkeep_mana(payer, mana)
        if paid and attached.tapped:
            self._spend_upkeep_mana(payer, mana)
            ctx.game.become_untapped(attached)
            self.log.append(f"{payer.name} paid to untap {attached.card.name}")

    @upkeep_effect("upkeep_self", "upkeep_pay_or_tap_and_sacrifice_opponent_land")
    def _on__upkeep_self__upkeep_pay_or_tap_and_sacrifice_opponent_land(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        trig = ctx.trig
        mana = trig.instruction.payload.get("mana", {})
        # The shared pair, for the reason the pay-or-deal-damage handler gives.
        if human_choices is not None and permanent.card.name in human_choices:
            paid = bool(human_choices[permanent.card.name]) and self.can_pay_upkeep_mana(
                controller, mana
            )
        else:
            paid = self.can_pay_upkeep_mana(controller, mana)
        if paid:
            self._spend_upkeep_mana(controller, mana)
            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
        else:
            # "tap this creature and sacrifice a land of an opponent's
            # choice" — the CONTROLLER sacrifices one of their own lands
            # (the opponent merely chooses which; simplified to the first).
            self.become_tapped(permanent)
            self._force_sacrifice_first_land(controller, permanent)

    @upkeep_effect("upkeep_self", "upkeep_pay_or_cede_named_creatures")
    def _on__upkeep_self__upkeep_pay_or_cede_named_creatures(self, ctx: UpkeepContext) -> None:
        """Rohgahh of Kher Keep: "you may pay {R}{R}{R}. If you don't, tap
        Rohgahh and all creatures named Kobolds of Kher Keep, then an opponent
        gains control of them."

        "Them" is Rohgahh *and* the Kobolds — the master defects with his
        creatures. The named set is every creature wearing the name, any
        controller's, matched by ``subject_matches`` so "named" means here
        exactly what it means on the lord line one sentence down. The control
        change is a CR 613 layer-2 contribution keyed on the Rohgahh permanent
        with no revert condition: the card prints no duration, so nothing ends
        it — not even Rohgahh leaving the battlefield.

        "An opponent" is the ability controller's choice on resolution; with
        one living opponent there is nothing to choose, and in a larger game
        this takes the first living opponent in seat order after the
        controller (the same simplification Demonic Hordes' opponent-chosen
        sacrifice takes, and honest to name: a multiplayer seat *choice* wants
        the pending-choice queue).
        """
        from ..subject_filters import subject_matches

        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        trig = ctx.trig
        mana = trig.instruction.payload.get("mana", {})
        # The shared pair, for the reason the pay-or-deal-damage handler gives.
        if human_choices is not None and permanent.card.name in human_choices:
            paid = bool(human_choices[permanent.card.name]) and self.can_pay_upkeep_mana(
                controller, mana
            )
        else:
            paid = self.can_pay_upkeep_mana(controller, mana)
        if paid:
            self._spend_upkeep_mana(controller, mana)
            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
            return
        named = str(trig.instruction.payload.get("named") or "")
        described = {"type_filter": "creature", "named": named}
        ceded = [permanent] + [
            perm
            for _seat, perm in self.permanents_with_controller()
            if perm is not permanent and subject_matches(self, perm, described)
        ]
        seat = ctx.player_index
        living = [
            index
            for offset in range(1, len(self.players))
            for index in [(seat + offset) % len(self.players)]
            if not self.players[index].lost
        ]
        for perm in ceded:
            self.become_tapped(perm)
        if not living:
            return
        new_seat = living[0]
        for perm in ceded:
            self.take_control(perm, new_seat, source=permanent)
        self.log.append(
            f"{self.players[new_seat].name} gains control of "
            f"{', '.join(perm.card.name for perm in ceded)}"
        )

    @upkeep_effect("upkeep_self", "set_source_base_pt_from_target_until_next_upkeep")
    def _on__upkeep_self__set_source_base_pt_from_target_until_next_upkeep(self, ctx: UpkeepContext) -> None:
        """Halfdane: "…change Halfdane's base power and toughness to the power
        and toughness of target creature other than Halfdane until the end of
        your next upkeep."

        The stats are read as the trigger resolves (CR 608.2) — the copy does
        not track the chosen creature afterwards — and written through the one
        P/T seam as a persistent layer-7b base (a CR 613.4b setting effect).
        The duration is the ``BASE_PT_REVERT_KEY`` stamp ``engine/pt.py``
        documents: written *after* the base (a persistent write clears any
        stale stamp), it names this seat and this turn, and the draw step —
        the moment this upkeep has just ended — reverts a permanent whose
        stamp names an earlier turn. A re-resolving trigger overwrites the
        stamp each upkeep, which is how the effect outlives itself exactly one
        upkeep at a time; a trigger with no legal target leaves the old stamp
        standing, and the rewrite ends where the card says it does.
        """
        from ..pt import BASE_PT_REVERT_KEY, set_base_pt

        controller = ctx.controller
        permanent = ctx.permanent
        target_perm = self._resolve_upkeep_trigger_target(
            permanent.card.name,
            ctx.trigger_targets,
            self._base_pt_copy_candidates(permanent),
        )
        if target_perm is None:
            # CR 603.3d: no legal target, so the ability is removed rather
            # than resolved — nothing is written and nothing is re-stamped.
            return
        power = target_perm.effective_power
        toughness = target_perm.effective_toughness
        set_base_pt(permanent, power, toughness)
        permanent.metadata[BASE_PT_REVERT_KEY] = {
            "seat": ctx.player_index,
            "turn": self.turn,
        }
        self.log.append(
            f"{permanent.card.name}: base power and toughness become "
            f"{power}/{toughness} ({target_perm.card.name}'s) until the end of "
            f"{controller.name}'s next upkeep"
        )

    @upkeep_effect("upkeep_self", "upkeep_most_life_gains_control")
    def _on__upkeep_self__upkeep_most_life_gains_control(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        permanent = ctx.permanent
        # Ghazbân Ogre: control passes to whichever player has
        # STRICTLY more life than every other (a tie for the
        # lead means no change). Living players only (CR
        # 800.4a: a player who's left the game has no life
        # total to compare).
        living = [p for p in self.players if not p.lost]
        sole_leader = None
        if living:
            top_life = max(p.life for p in living)
            leaders = [p for p in living if p.life == top_life]
            if len(leaders) == 1:
                sole_leader = leaders[0]
        if sole_leader is not None and sole_leader is not controller:
            # A resolving ability's control change lasts indefinitely (CR
            # 611.2b), so it is a layer-2 contribution from the Ogre itself.
            # Re-recording on a later upkeep replaces it with a fresh
            # timestamp, which is how the lead moving from one player to
            # another is expressed without anyone tracking a previous value.
            self.take_control(permanent, sole_leader, source=permanent)
            self.log.append(
                f"{sole_leader.name} gains control of {permanent.card.name} (most life)"
            )

    @upkeep_effect("upkeep_self", "upkeep_destroy_least_power_creature")
    def _on__upkeep_self__upkeep_destroy_least_power_creature(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        permanent = ctx.permanent
        # Drop of Honey: destroy the creature with the least
        # power; it can't be regenerated. "If two or more
        # creatures are tied for least power, you choose one of
        # them" — a human controller gets a prompt
        # (confirm_least_power_choice); AI/headless play breaks
        # the tie by battlefield scan order.
        candidates = [
            (self.players[seat], perm)
            for seat, perm in self.permanents_with_controller()
            if perm.is_creature
        ]
        if candidates:
            least = min(perm.effective_power for _, perm in candidates)
            tied = [
                (owner, perm)
                for owner, perm in candidates
                if perm.effective_power == least
            ]
            controller_index = self.players.index(controller)
            if len(tied) > 1:
                # A real tie is the controller's choice. An interactive seat is
                # prompted; every other seat takes the kind's default (the first
                # tied creature in battlefield scan order) as this is armed.
                armed = self.arm_pending_choice(
                    "least_power_choice", controller_index,
                    card_name=permanent.card.name,
                    candidates=[
                        {
                            "seat": self.players.index(owner),
                            "index": next(
                                i for i, p in enumerate(owner.battlefield) if p is victim
                            ),
                            "name": victim.card.name,
                        }
                        for owner, victim in tied
                    ],
                    _candidate_perms=[victim for _, victim in tied],
                )
                if armed is not None:
                    self.log.append(
                        f"{permanent.card.name}: {controller.name} chooses which "
                        "creature tied for least power to destroy"
                    )
            else:
                owner, victim = tied[0]
                self._destroy_least_power_creature(owner, victim, permanent.card.name)

    @upkeep_effect("upkeep_self", "upkeep_pay_or_sacrifice_self")
    def _on__upkeep_self__upkeep_pay_or_sacrifice_self(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        trig = ctx.trig
        mana = trig.instruction.payload.get("mana", {})
        # `can_pay_upkeep_mana` / `_spend_upkeep_mana`, the pair the wind-counter
        # handler beside this one already uses — never a hand-rolled pool read.
        # Both of these used to test the *coloured* pips alone:
        #
        #     paid = all(pool[sym] >= count for sym, count in mana.items()
        #                if sym != "generic")
        #
        # which is vacuously True for a cost with no coloured pips at all. Energy
        # Flux grants every artifact "sacrifice this artifact unless you pay
        # {2}", a generic-only cost, so every artifact on the board paid it for
        # free — and a partly generic {1}{U} charged the {U} and waived the {1}.
        # The helpers know that generic mana can come from floating mana *or*
        # from tapping a land during upkeep, which a pool read cannot see.
        if human_choices is not None and permanent.card.name in human_choices:
            paid = bool(human_choices[permanent.card.name]) and self.can_pay_upkeep_mana(
                controller, mana
            )
        else:
            paid = self.can_pay_upkeep_mana(controller, mana)
        if paid:
            self._spend_upkeep_mana(controller, mana)
            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
        else:
            self.sacrifice_permanent(permanent)
            self.log.append(f"{controller.name} sacrificed {permanent.card.name} on upkeep")

    @upkeep_effect("upkeep_self", "upkeep_counter_toll_or_cede_control")
    def _on__upkeep_self__upkeep_counter_toll_or_cede_control(
        self, ctx: UpkeepContext
    ) -> None:
        """Rogue Skycaptain: "Put a wage counter on this creature. You may pay
        {2} for each wage counter on it. If you don't, remove all wage counters
        from this creature and an opponent gains control of it."

        CR 702.24a's ability with a different consequence, so everything up to
        the decision is the cumulative-upkeep handler's: the counter goes on
        first and unconditionally, and ``scaled_cost`` is handed the new total
        rather than being left to look one up. Partial payment is not allowed
        (CR 118.3), which ``can_pay_upkeep_cost`` already answers about the
        whole escalated cost.

        Both halves of the decline happen, and in the order the card prints
        them. Removing the counters first is not cosmetic: it is what stops the
        new controller inheriting an escalation they never grew, which is the
        whole reason the card says it.

        "An opponent" is the controller's choice; with one living opponent there
        is nothing to choose, and in a larger game this takes the first living
        opponent in seat order after them — the same simplification the Rohgahh
        handler above names, and honest for the same reason.

        The control change is a CR 613 layer-2 contribution keyed on this
        permanent with no revert condition: the card prints no duration, so
        nothing ends it — not even the Skycaptain leaving and returning, which
        CR 400.7 makes a new object with no contribution at all.
        """
        from ..cumulative_upkeep import scaled_cost
        from ..named_counters import add_counters, remove_counters

        controller = ctx.controller
        permanent = ctx.permanent
        counter = str(ctx.trig.instruction.payload.get("per_counter") or "")
        total = add_counters(permanent, counter, 1)
        self.log.append(
            f"{permanent.card.name} gains a {counter} counter ({total} total)"
        )
        cost = scaled_cost(ctx.trig.instruction, total)
        paid = not offer_declined(
            ctx.human_choices, permanent
        ) and self.can_pay_upkeep_cost(controller, cost)
        if paid:
            self.pay_upkeep_cost(
                controller, cost, reason=permanent.card.name, source=permanent
            )
            self.log.append(
                f"{controller.name} paid {cost.describe()} for {permanent.card.name}"
            )
            return
        remove_counters(permanent, counter, total)
        seat = ctx.player_index
        new_seat = next(
            (
                index
                for offset in range(1, len(self.players))
                for index in [(seat + offset) % len(self.players)]
                if not self.players[index].lost
            ),
            None,
        )
        if new_seat is None:
            return
        self.take_control(permanent, new_seat, source=permanent)
        self.log.append(
            f"{self.players[new_seat].name} gains control of {permanent.card.name}"
        )

    @upkeep_effect("upkeep_self", "upkeep_pay_or_destroy_self")
    def _on__upkeep_self__upkeep_pay_or_destroy_self(self, ctx: UpkeepContext) -> None:
        """Cosmic Horror: "destroy this creature unless you pay {3}{B}{B}{B}.
        If this creature is destroyed this way, it deals 7 damage to you."

        The sacrifice twin above with two differences, both of them the card's:

        * it **destroys**, so regeneration and indestructible answer it
          (CR 701.7c) — which is why it goes through
          ``_destroy_target_permanent`` rather than removing the permanent by
          hand, and why the rider can be answered at all;
        * "destroyed **this way**" is that call's own answer. A creature that
          regenerated was not destroyed and takes no damage, and nothing but
          the destroy itself knows which happened.
        """
        from ..cumulative_upkeep import scaled_cost
        from ..named_counters import counters_on

        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        trig = ctx.trig
        # "…unless you pay {1} **for each music counter on it**" — the ability
        # Musician grants. The printed cost charged once per counter, through
        # `scaled_cost`, which is the same escalation cumulative upkeep runs:
        # a second multiplier here would be a second answer to "what does this
        # cost right now". Unlike cumulative upkeep nothing is *added* first —
        # this trigger only reads what the counters already are, and the ability
        # that grants it is what put them there.
        counter = trig.instruction.payload.get("per_counter")
        cost = scaled_cost(
            trig.instruction,
            counters_on(permanent, str(counter)) if counter else 1,
        )
        # `can_pay_upkeep_cost` / `pay_upkeep_cost`: the pair every other
        # upkeep cost in this file uses, and never a hand-rolled pool read —
        # they know that generic mana can come from floating mana *or* from
        # tapping a land during upkeep.
        if human_choices is not None and permanent.card.name in human_choices:
            paid = bool(human_choices[permanent.card.name]) and self.can_pay_upkeep_cost(
                controller, cost
            )
        else:
            paid = self.can_pay_upkeep_cost(controller, cost)
        if paid:
            self.pay_upkeep_cost(controller, cost, reason=permanent.card.name)
            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
            return
        index = next(
            (i for i, perm in enumerate(controller.battlefield) if perm is permanent),
            None,
        )
        if index is None:
            return
        destroyed = self._destroy_target_permanent(
            controller, target_permanent_index=index
        )
        if destroyed is None:
            # Regenerated, indestructible or replaced: not destroyed, so the
            # rider does not happen.
            self.log.append(f"{permanent.card.name} was not destroyed on upkeep")
            return
        self.log.append(f"{controller.name} let {permanent.card.name} be destroyed")
        damage = int(trig.instruction.payload.get("damage_if_destroyed", 0))
        if damage:
            ctx.enqueue_damage(
                permanent,
                self.players.index(controller),
                self.players.index(controller),
                damage,
                trig.source_line,
            )

    # ("upkeep_self", "target_gains_life") was Living Artifact's entry — "you
    # may remove a vitality counter from this Aura. If you do, you gain 1 life",
    # read as one fused kind because the decomposed reading had nowhere to run.
    # It does now: the upkeep step puts an ordinary trigger on the stack, the
    # grammar reads the sentence as the `may` it is, and the answer arrives
    # through the general `optional_pay` prompt instead of this file's bespoke
    # `optional_choices` dict. Removed rather than left dark, on the reachability
    # guard's insistence: an entry no card can reach is one nothing checks.

    @upkeep_effect("controls_no_matching", "sacrifice_self")
    def _on__controls_no_matching__sacrifice_self(self, ctx: UpkeepContext) -> None:
        """"When you control no <noun>, sacrifice this creature." (Sea Serpent,
        Island Fish Jasconius, Gorilla Pack.)

        The noun is payload, asked through ``subject_matches`` — the same
        reader the state-based sweep in ``mixins/game_ending.py`` uses, so the
        upkeep answer and the immediate one cannot disagree about what the card
        names. This entry used to be keyed on a ``no_islands`` condition with
        one land type welded into the kind.
        """
        from ..subject_filters import subject_matches

        controller = ctx.controller
        permanent = ctx.permanent
        seat = self.players.index(controller)
        described = ctx.trig.condition.payload.get("controlled_filter") or {}
        if not any(
            subject_matches(self, perm, described, observer=seat, source=permanent)
            for perm in self.controlled_by(controller)
        ):
            self.sacrifice_permanent(permanent)
            self.log.append(
                f"{controller.name} sacrificed {permanent.card.name}: "
                "controls none of what its state trigger names"
            )

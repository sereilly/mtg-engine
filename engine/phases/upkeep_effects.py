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

from ..handlers._common import permanent_effective_colors

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
        controller = ctx.controller
        human_choices = ctx.human_choices
        permanent = ctx.permanent
        # Cyclone: add a wind counter, then pay {G} per counter
        # or sacrifice; paying deals counter-many damage to each
        # creature and each player.
        counters = int(permanent.metadata.get("wind_counters", 0)) + 1
        permanent.metadata["wind_counters"] = counters
        self.log.append(f"{permanent.card.name} gains a wind counter ({counters} total)")
        cost = {"G": counters}
        if human_choices is not None and permanent.card.name in human_choices:
            paid = bool(human_choices[permanent.card.name]) and self.can_pay_upkeep_mana(
                controller, cost
            )
        else:
            paid = self.can_pay_upkeep_mana(controller, cost)
        if paid:
            self._spend_upkeep_mana(controller, cost)
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

    @upkeep_effect("upkeep_self", "upkeep_damage_unless_discard")
    def _on__upkeep_self__upkeep_damage_unless_discard(self, ctx: UpkeepContext) -> None:
        """Mishra's War Machine: "deals N damage to you unless you discard a
        card. If it deals damage to you this way, tap it."

        Two riders the previous parse dropped, and they interact: the tap only
        happens on the *damage* branch, so it cannot be a separate instruction.

        With an empty hand there is no choice — discarding is impossible, so the
        damage is taken and the source taps. With cards in hand the controller
        chooses; headless and AI play discard, which is deterministic and keeps
        the machine untapped, and an interactive prompt can replace it without
        changing what the rules do here.
        """
        controller = ctx.controller
        permanent = ctx.permanent
        trig = ctx.trig
        amount = int(trig.instruction.payload.get("amount", 0))
        taps_source = bool(trig.instruction.payload.get("taps_source"))

        if controller.hand:
            discarded = controller.hand.pop(0)
            controller.graveyard.append(discarded)
            self.log.append(
                f"{controller.name} discarded {discarded.name} to {permanent.card.name}"
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

    @upkeep_effect("upkeep_self", "upkeep_put_counter_on_self")
    def _on__upkeep_self__upkeep_put_counter_on_self(self, ctx: UpkeepContext) -> None:
        """Armageddon Clock: "put a doom counter on this artifact."

        The counter's name comes from the payload, so the accumulation is one
        handler for every card that counts something up on its own upkeep.
        """
        permanent = ctx.permanent
        counter = str(ctx.trig.instruction.payload.get("counter", "doom"))
        key = f"{counter}_counters"
        permanent.metadata[key] = int(permanent.metadata.get(key, 0)) + 1
        self.log.append(
            f"{permanent.card.name} got a {counter} counter "
            f"({permanent.metadata[key]} total)"
        )

    @upkeep_effect("upkeep_self", "upkeep_gain_life_over_hand_size")
    def _on__upkeep_self__upkeep_gain_life_over_hand_size(self, ctx: UpkeepContext) -> None:
        """Ivory Tower. Never negative: "minus 4" with three cards in hand
        gains nothing, it does not drain."""
        controller = ctx.controller
        floor = int(ctx.trig.instruction.payload.get("floor", 0))
        amount = max(0, len(controller.hand) - floor)
        if amount:
            self._gain_life(controller, amount, ctx.permanent.card.name)

    @upkeep_effect("upkeep_each", "upkeep_pay_per_creature_untap_color")
    def _on__upkeep_each__upkeep_pay_per_creature_untap_color(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
        # Magnetic Mountain: "that player" is whoever's upkeep
        # is currently resolving (player_index), not this
        # enchantment's controller. No interactive per-creature
        # selection channel exists, so as many affordable
        # tapped creatures of the color are untapped as
        # possible (greedy, battlefield order) — not an
        # all-or-nothing simplification.
        color = str(trig.instruction.payload.get("color", ""))
        cost_per = int(trig.instruction.payload.get("cost_per", 0))
        victim = self.players[player_index]
        untapped_names = []
        for perm in self.controlled_by(player_index):
            if not (perm.is_creature and perm.tapped):
                continue
            if color not in permanent_effective_colors(perm):
                continue
            if not self.can_pay_upkeep_mana(victim, {"generic": cost_per}):
                continue
            self._spend_upkeep_mana(victim, {"generic": cost_per})
            ctx.game.become_untapped(perm)
            untapped_names.append(perm.card.name)
        if untapped_names:
            self.log.append(
                f"{victim.name} paid to untap {', '.join(untapped_names)} ({permanent.card.name})"
            )

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
        # Power Leak: "that player may pay any amount of mana. ...
        # Prevent X of that damage, where X is the amount of mana
        # that player paid this way." The controller may pay up to
        # `amount` mana to prevent that much damage.
        if "prevent x of that damage" in permanent.effective_card.oracle_text.lower():
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

    @upkeep_effect("upkeep_chosen", "upkeep_chosen_player_hand_overflow_damage")
    def _on__upkeep_chosen__upkeep_chosen_player_hand_overflow_damage(self, ctx: UpkeepContext) -> None:
        _enqueue_upkeep_damage = ctx.enqueue_damage
        controller = ctx.controller
        permanent = ctx.permanent
        player_index = ctx.player_index
        trig = ctx.trig
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
        if human_choices is not None and permanent.card.name in human_choices:
            paid = human_choices[permanent.card.name]
        else:
            paid = all(
                controller.mana_pool.get(sym, 0) >= count
                for sym, count in mana.items()
                if sym != "generic"
            )
        if paid:
            for sym, count in mana.items():
                if sym != "generic":
                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
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
        if human_choices is not None and permanent.card.name in human_choices:
            paid = human_choices[permanent.card.name]
        else:
            paid = all(
                controller.mana_pool.get(sym, 0) >= count
                for sym, count in mana.items()
                if sym != "generic"
            )
        if paid:
            for sym, count in mana.items():
                if sym != "generic":
                    controller.mana_pool[sym] = controller.mana_pool.get(sym, 0) - count
            self.log.append(f"{controller.name} paid upkeep for {permanent.card.name}")
        else:
            # "tap this creature and sacrifice a land of an opponent's
            # choice" — the CONTROLLER sacrifices one of their own lands
            # (the opponent merely chooses which; simplified to the first).
            self.become_tapped(permanent)
            self._force_sacrifice_first_land(controller, permanent)

    @upkeep_effect("upkeep_self", "upkeep_sacrifice_land_conditional_damage")
    def _on__upkeep_self__upkeep_sacrifice_land_conditional_damage(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        permanent = ctx.permanent
        trig = ctx.trig
        trigger_targets = ctx.trigger_targets
        # Serendib Djinn: "Sacrifice a land. If you sacrifice an
        # Island this way, this creature deals 3 damage to you."
        # The controller chooses which land (CR 701.17a) through
        # the upkeep trigger-target channel; AI/headless play
        # falls back to the first land.
        land_type = str(trig.instruction.payload.get("land_type", "")).lower()
        damage_amt = int(trig.instruction.payload.get("damage", 0))
        chosen_land = self._resolve_upkeep_trigger_target(
            permanent.card.name,
            trigger_targets,
            self._upkeep_land_sacrifice_candidates(controller),
        )
        removed = self._force_sacrifice_first_land(controller, permanent, chosen_land)
        if removed is not None:
            was_matching_type = removed.has_type(land_type)
            if was_matching_type:
                self._deal_damage_to_player(
                    controller, damage_amt, source=permanent,
                    then=lambda dealt: self.log.append(
                        f"{permanent.card.name} dealt {dealt} damage to {controller.name}"
                    ),
                )

    @upkeep_effect("upkeep_self", "grant_forestwalk_until_next_upkeep")
    def _on__upkeep_self__grant_forestwalk_until_next_upkeep(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        permanent = ctx.permanent
        trigger_targets = ctx.trigger_targets
        # Erhnam Djinn: "target non-Wall creature an opponent
        # controls". A human controller picks the target through
        # the upkeep trigger-target channel (trigger_targets,
        # gathered by get_upkeep_target_triggers); AI/headless
        # play falls back to the first legal creature.
        target_perm = self._resolve_upkeep_trigger_target(
            permanent.card.name,
            trigger_targets,
            self._forestwalk_grant_candidates(controller),
        )
        if target_perm is not None:
            target_perm.metadata["has_forestwalk"] = True
            target_perm.metadata["forestwalk_until_next_upkeep_of"] = self.players.index(controller)
            self.log.append(
                f"{permanent.card.name} grants {target_perm.card.name} forestwalk until {controller.name}'s next upkeep"
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

    @upkeep_effect("upkeep_self", "upkeep_sacrifice_other_creature_or_deal_damage")
    def _on__upkeep_self__upkeep_sacrifice_other_creature_or_deal_damage(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        kind = ctx.kind
        permanent = ctx.permanent
        trig = ctx.trig
        # Lord of the Pit: "sacrifice a creature other than this
        # creature. If you can't, this creature deals N damage to
        # you." The controller chooses which other creature (a human
        # is prompted; AI/headless picks inline). With no other
        # creature, the damage consequence applies instead.
        self.arm_forced_sacrifice(
            self.players.index(controller),
            1,
            filter={"type_filter": "creature"},
            exclude=permanent,
            reason=permanent.card.name,
            on_short={"kind": "damage", "amount": int(trig.instruction.payload.get("damage", 0))},
        )

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

    # ("upkeep_self", "target_gains_life") was Living Artifact's entry — "you
    # may remove a vitality counter from this Aura. If you do, you gain 1 life",
    # read as one fused kind because the decomposed reading had nowhere to run.
    # It does now: the upkeep step puts an ordinary trigger on the stack, the
    # grammar reads the sentence as the `may` it is, and the answer arrives
    # through the general `optional_pay` prompt instead of this file's bespoke
    # `optional_choices` dict. Removed rather than left dark, on the reachability
    # guard's insistence: an entry no card can reach is one nothing checks.

    @upkeep_effect("no_islands", "sacrifice_self")
    def _on__no_islands__sacrifice_self(self, ctx: UpkeepContext) -> None:
        controller = ctx.controller
        permanent = ctx.permanent
        has_island = any(
            perm.card.primary_type == "land" and perm.has_type("island")
            for perm in self.controlled_by(controller)
        )
        if not has_island:
            self.sacrifice_permanent(permanent)
            self.log.append(f"{controller.name} sacrificed {permanent.card.name} for lacking an Island")

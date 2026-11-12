"""Paying an upkeep cost: CR 702.24a's [cost], and every "unless you pay" an
upkeep trigger quotes.

What a pay-or-consequence upkeep trigger charges once its payer says yes. Mana,
from the pool and by tapping for it inside the resolution (CR 605.3a), with any
restricted bucket the cost's purpose admits (CR 106.6); life, down to 0 (CR
119.4); a sacrifice the payer chooses (CR 701.21a); cards off the top of the
library; tokens an opponent the payer names creates; or an act performed once
per age counter. The affordability test and the spend read one payment plan, so
what a seat is offered and what it is charged cannot disagree, and a cost that
cannot be paid in full is paid not at all (CR 118.3).

Asked by the upkeep registry's handlers (``upkeep_effects.py``), by the draw
step's pay-or-lose-life prompt (``draw_step.py``) and by the web seat's prompt
gate (``web/turn_steps.py``). What a printed price *is* — the parse of it and
its escalation — is ``engine/upkeep_costs.py``'s; this module only pays one.

Split out of ``upkeep_step.py`` at the pre-Fifth-Dawn split round, and composed
onto ``Game`` immediately after :class:`~engine.phases.upkeep_step.UpkeepStepMixin`.
"""

from __future__ import annotations

from ..mana_payment import mana_cost_label
from ..oracle import OracleInstruction


def _reason_card(reason: str):
    """A stand-in card naming the permanent a cost was paid for.

    ``pay_upkeep_cost`` takes the source permanent when its caller has one, and
    the token maker reads ``card.name`` for its log line and ``card.raw`` for
    the token's art. This covers the callers that pass only the name, so no
    reader has to test for None.
    """
    from ..models import CardDefinition

    return CardDefinition(
        name=reason, mana_cost="", cmc=0.0, type_line="", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": reason},
    )


class UpkeepPaymentMixin:
    """The upkeep cost payer, composed onto ``Game``."""

    def can_pay_upkeep_mana(self, player, mana: dict[str, int], *, purpose=None) -> bool:
        """Whether *player* can cover an upkeep cost's mana: from the pool and by
        tapping untapped mana-producing lands, coloured pips included.

        An upkeep payment happens inside the trigger's resolution with no
        priority window, so the payer may activate mana abilities while paying
        (CR 605.3a) and the question is ``mana_payment.plan_payment``'s — the
        one every other offered price in the engine asks. This used to cover
        the coloured pips from floating mana alone and let only the *generic*
        part tap, so Stasis, Glaciers, Demonic Hordes, every {U} cumulative
        upkeep and both FEM Chants were sacrificed on the first upkeep of every
        AI or headless game with the right lands untapped, and Island Fish
        Jasconius never untapped at all.

        *purpose* is what the cost is for, so "spend this mana only to pay
        cumulative upkeep costs" (Adarkar Unicorn, Snowfall) can be counted:
        that mana lives in its own bucket beside the pool, and a payment that
        does not ask cannot see it. Without a purpose only the ordinary pool is
        offered, which is what every caller written before this got.
        """
        return self._upkeep_payment_plan(player, mana, purpose) is not None

    def _upkeep_payment_plan(self, player, mana: dict[str, int], purpose):
        """How *player* would pay *mana* now, or None — asked once by the
        affordability test and once by the spend, so the two cannot disagree
        about which lands and which units are in play."""
        return self.effect_payment_plan(
            player, mana, pool=self._upkeep_pool(player, purpose),
        )

    def _upkeep_pool(self, player, purpose) -> dict[str, int]:
        """The mana an upkeep payment may draw on: the pool, plus any restricted
        bucket *purpose* admits (CR 106.6).

        One reader for both halves of the pair, so what is *offered* and what
        is *spent* cannot disagree about which buckets are in play — the split
        that let Energy Flux's generic-only cost be paid by every artifact on
        the board. The restricted units go in **first**: ``plan_payment`` pays
        the generic part from the pool in insertion order, and a restricted
        unit is lost at the next step boundary either way, so anything else
        spent ahead of it is thrown away (the casting path's reason).
        """
        from ..restricted_mana import spendable_restricted_mana

        merged = dict(spendable_restricted_mana(player, purpose))
        for symbol, amount in player.mana_pool.items():
            merged[symbol] = merged.get(symbol, 0) + amount
        return merged

    def _spend_upkeep_mana(self, player, mana: dict[str, int], *, purpose=None) -> bool:
        """Spend an upkeep cost validated by ``can_pay_upkeep_mana``: the plan's
        floating units out of the pool (restricted bucket first where the
        purpose admits it) and the plan's lands tapped.

        Both halves, because a plan is *how* a cost is paid and paying from one
        without the other would let the same land answer two costs — the
        sibling ``_pay_planned_cost`` says the same. A plan that cannot be
        formed here is a caller that skipped the affordability test, and that
        is raised rather than spent in part: a cost half charged is a free
        ability, the class Vodalian War Machine's tap costs were.

        True when the cost was paid. False is a plan that held when it was
        made and failed part-way — which, since the plan is made over
        ``Game.payment_lands``, takes a tap that changed the board under it
        (a watcher answering the first land by tapping the rest). It is said
        in the log rather than left to read as paid.
        """
        from ..restricted_mana import debit_restricted_mana, spendable_restricted_mana

        plan = self._upkeep_payment_plan(player, mana, purpose)
        if plan is None:
            raise ValueError(
                f"{player.name} cannot pay {mana} at upkeep; the caller must ask "
                "can_pay_upkeep_mana first"
            )

        def spend(final) -> None:
            restricted = spendable_restricted_mana(player, purpose)
            for symbol, amount in final.from_pool.items():
                from_restricted = min(amount, restricted.get(symbol, 0))
                if from_restricted:
                    debit_restricted_mana(player, purpose, symbol, from_restricted)
                player.mana_pool[symbol] = (
                    int(player.mana_pool.get(symbol, 0)) - (amount - from_restricted)
                )

        # The planned lands are tapped **for mana** (CR 605.3a) through the one
        # payer every effect-collected cost shares (``_pay_planned_cost``), and
        # the plan is asked again after each tap — so a Snowfall's extra mana,
        # which lands in the very bucket this purpose admits, pays the upkeep
        # it was made for instead of floating beside it.
        paid = self._pay_planned_cost(
            player, lambda: self._upkeep_payment_plan(player, mana, purpose),
            spend=spend,
        )
        if not paid:
            self.log.append(
                f"{player.name} could not pay {mana_cost_label(mana)} in full: "
                "a land the payment counted on made nothing it could spend"
            )
        return paid

    def can_pay_upkeep_cost(self, player, cost, *, purpose=None) -> bool:
        """Whether *player* can pay a whole upkeep cost — CR 702.24a's [cost],
        which is mana, life and a sacrifice in whatever combination the card
        printed (``upkeep_costs.UpkeepCost``).

        Asked about all of it at once, because partial payment is never allowed
        (CR 702.24a's last sentence, and CR 601.2h's rule for every other cost):
        a player who cannot cover the life half pays none of the mana half
        either. That is also why this wraps :meth:`can_pay_upkeep_mana` rather
        than replacing it — the mana question is unchanged and has one answer;
        what is new is that it is no longer the only question.
        """
        from ..handlers.life_and_game import can_pay_life

        if not self.can_pay_upkeep_mana(player, cost.mana, purpose=purpose):
            return False
        # CR 119.4: life may be paid only down to 0.
        if cost.life and not can_pay_life(player, cost.life):
            return False
        if cost.sacrifices:
            # The charger's own candidate reader, so what is *offered* and what
            # can actually be given up cannot disagree — the split that let
            # Energy Flux's generic cost be paid for free one method up.
            candidates = self._sacrifice_candidate_indices(player, cost.sacrifice)
            if len(candidates) < cost.sacrifices:
                return False
        # "Cumulative upkeep—Exile the top card of your library." (Thought
        # Lash.) CR 118.3 again: a library holding fewer cards than the cost
        # names cannot pay it *fully*, so it pays none of it — which for a
        # cumulative upkeep is the permanent being sacrificed rather than a
        # shorter exile.
        if cost.exile_top_of_library > len(player.library):
            return False
        # "Cumulative upkeep—Have an opponent create a 1/1 red Survivor creature
        # token." (Varchild's War-Riders.) The payer spends nothing, so there is
        # no resource to check — but CR 118.3 still asks whether the cost can be
        # paid *fully*, and with no living opponent there is nobody to have do
        # it. Answering True there would create the tokens for the payer, which
        # is the opposite of what the card says.
        if cost.opponent_tokens and not any(
            index != self.seat_index(player) and not other.lost
            for index, other in enumerate(self.players)
        ):
            return False
        # "Cumulative upkeep—Put a -1/-1 counter on this creature" (Aboroth),
        # "—Draw a card" (Psychic Vortex). No resource is spent, so CR 118.3
        # has nothing to ask about: `upkeep_costs._SELF_ACTION_KINDS` admits
        # only acts that cannot fail, and CR 121.4 makes a draw from an empty
        # library one of them — the player draws nothing and loses at the next
        # state-based check, which is not the same as being unable to pay.
        return True

    def pay_upkeep_cost(
        self, player, cost, *, reason: str, purpose=None, source=None
    ) -> None:
        """Pay an upkeep cost already validated by :meth:`can_pay_upkeep_cost`.

        The sacrifice goes through ``arm_forced_sacrifice``, which is what makes
        *which* permanent the payer's choice (CR 701.21a) and prompts a human
        seat for it; the affordability test above is what stops that prompt from
        being armed for a payment the player could not have made.
        """
        self._spend_upkeep_mana(player, cost.mana, purpose=purpose)
        if cost.life:
            player.life -= cost.life
            self.log.append(f"{player.name} paid {cost.life} life for {reason}")
        if cost.sacrifices:
            # `seat_index`, not `players.index`: the latter is an equality
            # search over a mutable dataclass, so two seats holding equal state
            # would resolve to the same one.
            self.arm_forced_sacrifice(
                self.seat_index(player),
                cost.sacrifices,
                filter=cost.sacrifice,
                reason=reason,
            )
        if cost.exile_top_of_library:
            # Nothing is chosen and nothing is prompted for: the cards are named
            # by position, so this is the whole payment. Sufficiency was checked
            # above, exactly as the life payment's was.
            taken = [
                player.library.pop(0)
                for _ in range(cost.exile_top_of_library)
            ]
            taken = self.put_cards_into_exile(player, taken)
            self.log.append(
                f"{player.name} exiled "
                + ", ".join(card.name for card in taken)
                + f" from the top of their library for {reason}"
            )
        if cost.opponent_tokens:
            self._have_an_opponent_create(player, cost, reason=reason, source=source)
        if cost.self_actions:
            self._pay_self_action(player, cost, reason=reason, source=source)

    def _pay_self_action(self, player, cost, *, reason: str, source) -> None:
        """Pay a "cumulative upkeep—<do something>" cost (Aboroth, Psychic
        Vortex).

        The act is performed by executing the instruction the grammar lowered
        the printed sentence to, against the payer's own seat and the permanent
        that printed it — the same shape :meth:`_have_an_opponent_create` uses,
        with the one difference that makes it safe to admit a wider set of
        kinds: nothing is re-aimed.

        Run **once per age counter** rather than once with a bigger number
        (CR 702.24a: "pay [cost] for each age counter on it"). That is the whole
        of the escalation for a cost whose content is an action, and it is why
        ``scaled_cost`` multiplies the repetition count and leaves the payload
        alone — three age counters buy three -1/-1 counters, and a payload
        scaled instead would need a different key per instruction kind.
        """
        from ..game_types import OracleExecutionContext

        action = cost.self_action or {}
        kind = str(action.get("kind") or "")
        if not kind:
            return
        instruction = OracleInstruction(kind, "", dict(action.get("payload") or {}))
        context = OracleExecutionContext(
            caster=player,
            target=player,
            card=source.card if source is not None else _reason_card(reason),
            source_permanent=source,
        )
        for _ in range(cost.self_actions):
            self._execute_oracle_instruction(instruction, context)
        self.log.append(
            f"{player.name} paid {cost.self_action_term()} for {reason}"
        )

    def _have_an_opponent_create(self, player, cost, *, reason: str, source) -> None:
        """Pay a "have an opponent create <token>" cost (Varchild's War-Riders).

        The tokens are made by executing the ``create_token`` instruction the
        grammar lowered the printed sentence to, against a context whose caster
        is the opponent — so this pays with the engine's one token maker rather
        than with a second construction of "1/1 red Survivor creature token".

        **One opponent per age counter, named by the payer.** CR 702.24a: "pay
        [cost] for each age counter on it", and the card's ruling (2004-10-04):
        "If you have multiple opponents, you can put the Survivor tokens onto
        the battlefield under the control of different players." Each is asked
        through the choosers' seam (``handlers/player_choices.
        ask_which_opponent``: one opponent is no question, a payer nobody asks
        takes the first offered), in one resumable loop whose last step makes
        the tokens — one creation per opponent named, so a payer nobody asks
        makes them in one, as before. Every token went to the first living
        opponent after the payer until then, whoever the payer was.

        The loop is the last thing here (``engine/resumption.py``): a person's
        answers suspend it, and what follows in :meth:`pay_upkeep_cost` (a
        self-action cost, which no card prints beside this one) runs as the
        payment's other parts do, before them.
        """
        from ..game_types import OracleExecutionContext
        from ..handlers.player_choices import ask_which_opponent
        from ..resumption import run_resumable

        card = source.card if source is not None else _reason_card(reason)
        asking = OracleExecutionContext(
            caster=player, target=player, card=card, source_permanent=source,
        )
        named: list[int] = []

        def ask(_counter) -> None:
            ask_which_opponent(
                self, asking, card_name=card.name,
                prompt=f"Choose the opponent who creates a token for {reason}.",
                then=lambda seat: named.append(seat) if seat is not None else None,
            )

        def create() -> None:
            for recipient in dict.fromkeys(named):
                payload = dict(cost.opponent_token or {})
                payload["count"] = named.count(recipient)
                self._execute_oracle_instruction(
                    OracleInstruction("create_token", "", payload),
                    OracleExecutionContext(
                        caster=self.players[recipient],
                        target=self.players[recipient],
                        card=card,
                        source_permanent=source,
                    ),
                )

        run_resumable(self, range(cost.opponent_tokens), ask, then=create)

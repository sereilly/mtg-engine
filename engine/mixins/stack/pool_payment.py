"""Spending the mana pool (CR 601.2g–h, CR 106), and the X it can pay for
(CR 107.3).

``_pay_mana_cost`` is the one payment every cast and every activation spends
through, and it is all or nothing: a pool it cannot pay from is left exactly
as it was, which is what lets the activation path treat it as its last gate.
CR 106.6's spending permissions (Celestial Dawn, Sunglasses of Urza) are its
``_pay_with_fungible_*`` and ``_pay_under_permissions`` arms.
``_pay_cast_cost`` pays a spell's own mana cost and reports what its X was
paid with ("Spend only black mana on X"); ``_infer_x_value`` is the largest X
a seat that announced none can pay for; ``_parse_mana_cost`` turns a printed
cost into the symbol dict all of them take.

Two steps of ``_cast_onto_stack`` live here, moved out of it whole at the
2,000-line cap: ``_resolved_cast_x`` (the X this cast is for, CR 601.2b) and
``_pay_cast_mana`` (the waiver, then the mana the cast owes).

Split out of ``casting.py`` at the 2,000-line cap, and composed onto ``Game``
with the other parts of ``SpellCastingMixin``, directly after it.
"""

from __future__ import annotations

import re

from .._constants import _MANA_SYMBOLS as _POOL_SYMBOLS
from ...cost_modifiers import CostReduction, reduce_cost
from ...models import PlayerState
from ...restricted_mana import CAST, PaymentPurpose
from ...cast_permissions import permission_for
from ...cost_modifiers import keyword_cost_modifiers
from ...cost_x_definitions import (
    caps_cast_x, cast_x_ceiling, cast_x_floor, cast_x_value, defines_cast_x,
    floors_cast_x,
)
from ...game_types import SimulationResult
from ...oracle_types import x_spend_colors_from_text


def _x_mana_actually_spent(
    allocation: dict[str, int], cost: dict[str, int]
) -> dict[str, int]:
    """The allocation, clamped to what the *reduced* cost really charged.

    A coloured cost reduction (CR 118.7b, "this spell costs {B} less to cast")
    comes off a flat symbol dict in which the printed {B} pip and a black mana
    put on X are the same entry, so the rules do not say which half of it the
    reduction takes. The caster would take it off the pip, keeping as much black
    on X as they can — which is exactly this clamp: X's share is whatever the
    cost still charges in that colour, up to what was allocated to X.

    Nothing is inflated. An over-reported symbol is life gained for mana nobody
    spent, and "not more than the amount of {B} spent on X" is a limit that must
    never err upward.
    """
    return {
        symbol: min(count, cost.get(symbol, 0))
        for symbol, count in allocation.items()
        if min(count, cost.get(symbol, 0)) > 0
    }


class PoolPaymentMixin:
    def _infer_x_value(
        self, player: PlayerState, mana_cost: str, extra_generic: int = 0,
        x_colors: tuple[str, ...] = (), reduction: CostReduction | None = None,
        extra_pips: dict[str, int] | None = None,
    ) -> int:
        """The largest X *player* can announce and then pay for (CR 107.3).

        Two answers, and the larger wins: what the pool pays on its own, and
        what it pays under a CR 609.4b grant the caster is holding ("For one
        spell this turn, you may spend mana as though it were mana of any
        type", North Star). The second was not asked at all, so an {X} spell
        cast under such a grant inferred **X = 0** — and then cast anyway,
        because the payment path *does* know about the grant: it paid the
        coloured pip, **spent the grant**, and resolved for nothing. A bounded
        permission burned on a spell that did nothing.

        Taking the maximum never burns a grant that was not already going to
        be spent. Everything but a coloured pip is payable from any unit either
        way, so the two answers can only differ when a pip is unpayable
        directly — and in that case the direct answer is 0 and the cost cannot
        be paid without the grant at all.
        """
        direct = self._infer_x_from_pool(
            player, mana_cost, extra_generic, x_colors, reduction, extra_pips,
        )
        grant = next(
            (g for g in player.spend_mana_as_though_grants
             if int(g.get("spells", 0)) > 0),
            None,
        )
        if grant is None:
            return direct
        from ...mana_payment import (fungible_colors_headroom,
                                     fungible_types_headroom)

        required = self._x_inference_cost(
            mana_cost, extra_generic, reduction, extra_pips
        )
        pool = {
            symbol: int(player.mana_pool.get(symbol, 0))
            for symbol in ("W", "U", "B", "R", "G", "C")
        }
        headroom = (
            fungible_types_headroom(pool, required) if grant.get("any_type")
            else fungible_colors_headroom(pool, required)
        )
        return direct if headroom is None else max(direct, headroom)

    def _x_inference_cost(
        self, mana_cost: str, extra_generic: int,
        reduction: CostReduction | None, extra_pips: dict[str, int] | None,
    ) -> dict[str, int]:
        """The cost X is inferred *against*: everything but X itself.

        The reduction is applied before X is inferred, because X is whatever is
        left after the rest of the cost is paid — inferring it from the
        undiscounted cost would spend the discount on nothing. One reader, so
        the direct answer and the grant's are measured against the same cost.
        """
        return reduce_cost(
            self._parse_mana_cost(
                mana_cost, x_value=0, extra_generic=extra_generic,
                extra_pips=extra_pips,
            ),
            reduction or CostReduction(),
        )

    def _infer_x_from_pool(
        self, player: PlayerState, mana_cost: str, extra_generic: int = 0,
        x_colors: tuple[str, ...] = (), reduction: CostReduction | None = None,
        extra_pips: dict[str, int] | None = None,
    ) -> int:
        """What the pool alone pays for, under the seat's *standing* spending
        permissions."""
        required = self._x_inference_cost(
            mana_cost, extra_generic, reduction, extra_pips
        )
        temp = {symbol: player.mana_pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}

        # "You may spend mana as though it were mana of any color." (Chromatic
        # Orrery.) The permission `_pay_mana_cost_directly` honours, asked here
        # too -- and it was not, for as long as both existed. The cascade below
        # tests each coloured pip against its own symbol, so a colourless pool
        # inferred X = 0 for **every** {X} spell with a coloured pip in it, and
        # the spell then resolved with X = 0 having spent nothing: Fireball
        # dealt 0 damage off four mana. A permission honoured at one payment
        # site out of several is an ability that works less often than the card
        # allows, which is the quieter half of `activation_restrictions`'
        # failure and just as silent.
        #
        # Ahead of the coloured cascade *and* of the restricted-X branch below.
        # "Spend only black mana on X" (Drain Life) is satisfied by every unit
        # under this permission, so the two questions collapse into one: what is
        # left after the pips and the printed generic are paid.
        # A permission the two booleans cannot describe (Celestial Dawn: white
        # pays any colour, everything else pays no colour at all). Asked first,
        # because it is the general arithmetic and the two branches under it are
        # the special cases it generalises -- and asked *here* as well as at the
        # spend, which is the lesson Chromatic Orrery taught: a permission
        # honoured at one payment site out of several is a card that works less
        # often than it reads.
        if player.mana_spending_is_general:
            from ...mana_payment import spend_under_permissions

            after = spend_under_permissions(
                temp, required, player.mana_spending_permissions
            )
            return 0 if after is None else sum(max(0, n) for n in after.values())

        if player.spends_mana_as_any_color:
            from ...mana_payment import fungible_colors_headroom

            headroom = fungible_colors_headroom(temp, required)
            return 0 if headroom is None else headroom

        if temp.get("W", 0) < required["W"]:
            return 0
        if temp.get("U", 0) < required["U"]:
            return 0
        if temp.get("B", 0) < required["B"]:
            return 0
        if temp.get("G", 0) < required["G"]:
            return 0
        if temp.get("C", 0) < required["C"]:
            return 0

        available_red = temp.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += temp.get("W", 0)
        if available_red < required["R"]:
            return 0

        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return 0
            if temp.get("W", 0) < red_to_pay:
                return 0
            temp["W"] -= red_to_pay

        available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
        if available_generic < required["generic"]:
            return 0

        restricted = tuple(sym for sym in x_colors if sym in _POOL_SYMBOLS)
        if restricted:
            # X may be paid only in these colours (CR 601.2h): reserve them by
            # covering the generic part from every *other* symbol first. A tuple
            # rather than one symbol -- "black and/or red" pools both, and asking
            # about black alone under-reported the affordable X by every red
            # mana the pool held.
            reserved = sum(max(0, temp.get(sym, 0)) for sym in restricted)
            other_available = available_generic - reserved
            generic_from_reserved = max(0, required["generic"] - other_available)
            return max(0, reserved - generic_from_reserved)

        return available_generic - required["generic"]
    def _parse_mana_cost(
        self, mana_cost: str, x_value: int | None, extra_generic: int = 0,
        x_allocation: dict[str, int] | None = None,
        extra_pips: dict[str, int] | None = None,
    ) -> dict[str, int]:
        """*mana_cost* as a symbol dict, with X worth *x_value*.

        *x_allocation* is how much of X is being paid in each colour -- the
        caster's CR 601.2h choice, already made. "Spend only black mana on X"
        (Drain Life) allocates all of X to {B}; "black and/or red" (Soul Burn)
        splits it, and ``_x_color_allocations`` below is what picks the split.
        Whatever X is not allocated stays generic, which is the unrestricted
        case with an empty allocation.

        A dict rather than the single ``x_color`` symbol this used to take: one
        symbol cannot describe a two-colour restriction, and it also cannot
        answer the question the split exists for -- how much {B} paid X, as
        opposed to the mandatory {B} pip or the {2} beside it.
        """
        required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": max(0, extra_generic)}
        # A coloured tax (Derelor's "{B}") joins the pips rather than the
        # generic part, which is what makes it unpayable from the wrong colour.
        for symbol, count in (extra_pips or {}).items():
            if symbol in _POOL_SYMBOLS:
                required[symbol] += max(0, int(count))
        if not mana_cost:
            return required

        allocation = {
            sym: max(0, int(count))
            for sym, count in (x_allocation or {}).items()
            if sym in _POOL_SYMBOLS
        }
        for token in re.findall(r"\{([^}]+)\}", mana_cost.upper()):
            if token.isdigit():
                required["generic"] += int(token)
                continue
            if token == "X":
                remaining = max(0, x_value or 0)
                for sym, count in allocation.items():
                    spent = min(remaining, count)
                    required[sym] += spent
                    remaining -= spent
                required["generic"] += remaining
                continue
            if token in _POOL_SYMBOLS:
                required[token] += 1
        return required

    @staticmethod
    def _x_color_allocations(
        x_colors: tuple[str, ...], x_value: int
    ) -> tuple[dict[str, int], ...]:
        """Every way to split *x_value* among *x_colors*, best split first.

        "Best" is as much as possible on the colour the card names first, then
        as much as possible on the next -- the caster's CR 601.2h choice, which
        this engine has no channel to ask for. The printed order is the
        preference because it is the only thing about the split the card itself
        says, and for the one card that can tell the difference it is also the
        caster-favourable reading: Soul Burn's life gain is capped by the {B}
        spent on X, and {B} is what it names first.

        Every split is returned, not just the best one, because the best one may
        not be payable -- X wholly in black cannot also leave a black for the
        mandatory {B} pip -- and the caller walks the list until the pool pays.
        Costing the whole cost each time is what makes that exact: the printed
        pips and the generic remainder are in the same question as the split.
        """
        if not x_colors:
            return ({},)
        wanted = max(0, x_value)
        if len(x_colors) == 1:
            return ({x_colors[0]: wanted},)
        head, tail = x_colors[0], x_colors[1:]
        return tuple(
            {head: taken, **rest}
            for taken in range(wanted, -1, -1)
            for rest in PoolPaymentMixin._x_color_allocations(tail, wanted - taken)
        )

    def _pay_cast_cost(
        self, caster: PlayerState, card, x_value: int | None,
        x_colors: tuple[str, ...], *, extra_generic: int,
        reduction: CostReduction | None,
        extra_pips: dict[str, int] | None = None,
        offer_x_colorings: tuple[tuple[str, ...], ...] = ((),),
        mana_cost: str | None = None,
    ) -> dict[str, int] | None:
        """Pay *card*'s mana cost, and report what X was paid with.

        *mana_cost* is the printed run of symbols to charge **in its place**:
        an alternative cost that is paid in mana (CR 118.9, CR 702.34a's
        flashback cost). Everything else about the payment is the cast's own —
        the increases, the reductions and the purpose a restricted bucket is
        asked about — because CR 118.9d applies them to an alternative cost
        exactly as it would have to the mana cost. None is the card's own.

        None when the pool cannot pay it under **any** split of X, and then
        nothing has been spent: ``_pay_mana_cost`` leaves the pool untouched on
        failure, so walking the candidate splits costs the caster nothing and
        the first one that pays is the payment that happened.

        *offer_x_colorings* is the other X a cast can owe: the X of an optional
        cost that must be paid "only [with] colored mana … no more than one
        mana of each color" (Emblazoned Golem's kicker,
        ``OptionalManaCost.x_colorings``). Each entry is one choice of colours;
        the first whose units the pool really holds *and* whose remainder the
        pool then pays is the payment that happened. The default is the one
        choice of nothing, which is every other cast.

        **Those units are taken out of the pool, not asked for as pips.** A
        coloured pip is "something that may be spent as this colour", and under
        a CR 609.4b permission that is not the same question: Celestial Dawn
        lets white mana pay a green pip, and "it doesn't change what mana was
        actually spent to pay that cost" -- so five Plains would pay a pip
        apiece and the card would count five colours where one was spent. The
        restriction is about the mana, so the mana is what is set aside
        (``_set_aside_one_of_each``) and the rest of the cost is then paid the
        ordinary way from what is left.
        """
        purpose = PaymentPurpose(CAST, card=card)
        for coloring in offer_x_colorings:
            give_back = self._set_aside_one_of_each(caster, coloring, purpose)
            if give_back is None:
                continue
            for allocation in self._x_color_allocations(
                x_colors, max(0, x_value or 0)
            ):
                cost = reduce_cost(
                    self._parse_mana_cost(
                        card.mana_cost if mana_cost is None else mana_cost,
                        x_value=x_value,
                        extra_generic=extra_generic, x_allocation=allocation,
                        extra_pips=extra_pips,
                    ),
                    reduction or CostReduction(),
                )
                if self._pay_mana_cost(caster, cost, purpose=purpose):
                    return _x_mana_actually_spent(allocation, cost)
            give_back()
        return None

    @staticmethod
    def _set_aside_one_of_each(caster: PlayerState, colors, purpose):
        """Spend one unit of *caster*'s mana of each colour in *colors*, by the
        mana's **actual** colour, and return the thunk that puts them back --
        or None, with nothing spent, when the pool does not hold them all.

        A restricted bucket *purpose* admits is spent first, for the reason
        ``_pay_mana_cost_directly`` attributes to one first: its units are lost
        otherwise. The undo restores both stores, because the caller tries the
        rest of the cost afterwards and a remainder the pool cannot pay must
        leave the caster exactly where they stood (CR 601.2e).
        """
        from ...restricted_mana import (debit_restricted_mana,
                                        spendable_restricted_mana)

        if not colors:
            return lambda: None
        pool_before = dict(caster.mana_pool)
        buckets = getattr(caster, "restricted_mana", None) or {}
        buckets_before = {key: dict(bucket) for key, bucket in buckets.items()}

        def give_back() -> None:
            caster.mana_pool = dict(pool_before)
            for key, bucket in buckets_before.items():
                buckets[key].clear()
                buckets[key].update(bucket)

        restricted = dict(spendable_restricted_mana(caster, purpose))
        for symbol in colors:
            if restricted.get(symbol, 0) > 0:
                debit_restricted_mana(caster, purpose, symbol, 1)
                restricted[symbol] -= 1
            elif caster.mana_pool.get(symbol, 0) > 0:
                caster.mana_pool[symbol] = caster.mana_pool[symbol] - 1
            else:
                give_back()
                return None
        return give_back  # _set_aside_one_of_each
    def _pay_mana_cost(
        self, player: PlayerState, required: dict[str, int], *, purpose=None
    ) -> bool:
        """Pay *required* from *player*'s pool, or leave the pool untouched.

        Two steps, and the order is what makes the second one honest. The
        ordinary payment goes first; only when it cannot pay is a CR 609.4
        "you may spend mana as though…" grant spent (North Star). A grant tried
        first would be consumed by a spell that never needed it — "for **one**
        spell this turn" is a bounded permission, and the player would choose
        the spell that could not otherwise be cast.

        An activated ability is not a spell, so no grant applies to one: the
        clause says "that **spell's** mana cost", and *purpose* not naming a
        cast is that rule rather than a missing argument.
        """
        from ...restricted_mana import CAST

        if self._pay_mana_cost_directly(player, required, purpose=purpose):
            return True
        if purpose is None or purpose.kind != CAST:
            return False
        spell = purpose.card
        grant = next(
            (g for g in player.spend_mana_as_though_grants if int(g.get("spells", 0)) > 0),
            None,
        )
        if grant is None:
            return False
        paid = (
            self._pay_with_fungible_types(player, required)
            if grant.get("any_type")
            else self._pay_with_fungible_colors(player, required)
        )
        if not paid:
            return False
        # Spent only when it actually paid, so a grant is never burned by a
        # cost the pool could not have covered under any permission.
        grant["spells"] = int(grant["spells"]) - 1
        self.log.append(
            f"{player.name} spent mana as though it were mana of any "
            f"{'type' if grant.get('any_type') else 'color'} to cast "
            f"{getattr(spell, 'name', 'a spell')}"
        )
        return True

    def _pay_mana_cost_directly(
        self, player: PlayerState, required: dict[str, int], *, purpose=None
    ) -> bool:
        # "Spend this mana only to…" (CR 106.6): a restricted bucket joins the
        # pool only for a payment its own restriction admits, and whatever the
        # payment consumes is attributed to the restricted bucket first (its
        # units are otherwise lost, so spending them first is the only rational
        # attribution).
        #
        # *purpose* is what the payment is for — a cast, an activation, an
        # upkeep cost. It used to be the card being cast, which made every
        # restriction a claim about a *spell* and left the other two payment
        # paths unable to spend restricted mana at all.
        from ...restricted_mana import (debit_restricted_mana,
                                        spendable_restricted_mana)

        restricted = spendable_restricted_mana(player, purpose)
        if restricted and any(restricted.values()):
            snapshot = dict(player.mana_pool)
            player.mana_pool = {
                sym: snapshot.get(sym, 0) + restricted.get(sym, 0)
                for sym in ("W", "U", "B", "R", "G", "C")
            }
            if not self._pay_mana_cost_directly(player, required):
                player.mana_pool = snapshot
                return False
            for sym in ("W", "U", "B", "R", "G", "C"):
                spent = snapshot.get(sym, 0) + restricted.get(sym, 0) - player.mana_pool.get(sym, 0)
                from_restricted = min(spent, restricted.get(sym, 0))
                if from_restricted:
                    debit_restricted_mana(player, purpose, sym, from_restricted)
                snapshot[sym] = snapshot.get(sym, 0) - (spent - from_restricted)
            player.mana_pool = snapshot
            return True
        pool = player.mana_pool

        # "You may spend mana as though it were mana of any color." (Chromatic
        # Orrery.) Every unit in the pool pays a coloured pip, colourless
        # included — the Orrery's own five {C} are what the card is for. Handled
        # before the per-colour cascade rather than woven through it: with the
        # permission the five checks below are one check about a total, and
        # threading a substitution through each of them is how the narrow
        # white-as-red permission ended up appearing in five places.
        #
        # A **{C} in the cost still wants colourless**, because colourless is not
        # a colour (CR 105.1) and this line grants colours. So the generic and
        # colourless halves are unchanged.
        if player.mana_spending_is_general:
            return self._pay_under_permissions(player, required)

        if player.spends_mana_as_any_color:
            return self._pay_with_fungible_colors(player, required)

        if pool.get("W", 0) < required["W"]:
            return False
        if pool.get("U", 0) < required["U"]:
            return False
        if pool.get("B", 0) < required["B"]:
            return False
        if pool.get("G", 0) < required["G"]:
            return False
        if pool.get("C", 0) < required["C"]:
            return False

        available_red = pool.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += pool.get("W", 0)
        if available_red < required["R"]:
            return False

        temp = {symbol: pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}
        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return False
            if temp.get("W", 0) < red_to_pay:
                return False
            temp["W"] -= red_to_pay

        generic = required["generic"]
        if generic > 0:
            available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
            if available_generic < generic:
                return False

            for sym in ("C", "W", "U", "B", "R", "G"):
                spend = min(temp.get(sym, 0), generic)
                temp[sym] -= spend
                generic -= spend
                if generic == 0:
                    break

        player.mana_pool = temp
        return True

    def _pay_with_fungible_types(
        self, player: PlayerState, required: dict[str, int]
    ) -> bool:
        """Pay *required* while every unit in the pool counts as any mana
        *type* — CR 106.1b's five colours **and** colorless.

        Its own function rather than a flag on the colour version above,
        because the two differ in exactly one place and it is the place that
        matters: with colorless in the set, a {C} the cost names is payable by
        a coloured mana, so there is nothing to reserve and no way for a pip to
        starve one. The payment collapses to a single question about the total,
        which is why this is short where that one is careful.
        """
        from ...mana_payment import fungible_types_headroom

        pool = {sym: int(player.mana_pool.get(sym, 0)) for sym in _POOL_SYMBOLS}
        owed = sum(required.get(sym, 0) for sym in _POOL_SYMBOLS)
        owed += required.get("generic", 0)
        # Payable at all is `mana_payment`'s question, for its colour sibling's
        # reason: the X inference asks the same thing of the same grant, and
        # two copies of one payment rule are how the two came to disagree.
        if fungible_types_headroom(pool, required) is None:
            return False
        for sym in _POOL_SYMBOLS:
            spend = min(pool[sym], owed)
            pool[sym] -= spend
            owed -= spend
            if owed == 0:
                break
        player.mana_pool = pool
        return True

    def _pay_under_permissions(
        self, player: PlayerState, required: dict[str, int]
    ) -> bool:
        """Pay *required* under CR 106.6 permissions the booleans cannot name.

        The arithmetic is `mana_payment.spend_under_permissions` and the
        *spending* is here, which is the same division `_pay_with_fungible_colors`
        below draws and for the same reason: the X inference and the client's
        affordability display ask the same question of the same permission, and
        three answers to it is how Chromatic Orrery came to be honoured at one
        site out of four. The pool is written only on success, so a refusal
        leaves it untouched like every other branch of this cascade.
        """
        from ...mana_payment import spend_under_permissions

        pool = {
            symbol: int(player.mana_pool.get(symbol, 0))
            for symbol in ("W", "U", "B", "R", "G", "C")
        }
        after = spend_under_permissions(
            pool, required, player.mana_spending_permissions
        )
        if after is None:
            return False
        for symbol, remaining in after.items():
            player.mana_pool[symbol] = max(0, int(remaining))
        return True

    def _pay_with_fungible_colors(
        self, player: PlayerState, required: dict[str, int]
    ) -> bool:
        """Pay *required* while every unit in the pool counts as any colour.

        Three buckets in order, and the order is the only thing that makes the
        payment maximal: the coloured pips first (they are the pickiest, and
        under this permission any unit satisfies one), then {C}, which nothing
        else can pay, then the generic remainder from whatever is left.

        Colourless is spent *last* among the coloured pips, so a cost that also
        wants {C} is not starved by a pip that a coloured unit could have paid.
        """
        from ...mana_payment import fungible_colors_headroom

        pool = {sym: int(player.mana_pool.get(sym, 0)) for sym in ("W", "U", "B", "R", "G", "C")}
        colored_pips = sum(required[sym] for sym in ("W", "U", "B", "R", "G"))
        # Whether it can be paid at all is `mana_payment`'s arithmetic, not a
        # second copy here: the X inference and the client's affordability
        # display ask the same question of the same permission, and the three
        # answers have to agree. What stays here is the *spending*, which is
        # the only half of the job those two do not want.
        if fungible_colors_headroom(pool, required) is None:
            return False

        temp = dict(pool)
        owed = colored_pips
        for sym in ("W", "U", "B", "R", "G", "C"):
            if owed <= 0:
                break
            # Leave enough colourless behind for the {C} the cost names.
            spendable = temp[sym] - (required["C"] if sym == "C" else 0)
            spend = max(0, min(spendable, owed))
            temp[sym] -= spend
            owed -= spend
        if owed > 0:
            return False

        if temp["C"] < required["C"]:
            return False
        temp["C"] -= required["C"]

        generic = required["generic"]
        for sym in ("C", "W", "U", "B", "R", "G"):
            if generic <= 0:
                break
            spend = min(temp[sym], generic)
            temp[sym] -= spend
            generic -= spend
        if generic > 0:
            return False

        player.mana_pool = temp
        return True

    def _resolved_cast_x(
        self, *, card, caster, caster_index, classification, cost_reduction,
        extra_generic_tax, extra_pip_tax, mode_index, target_permanent_ids,
        target_permanent_index, target_player_index, target_stack_item,
        x_value,
    ):
        """The X this cast is for (CR 107.3, CR 601.2b), before any cost is
        paid.

        Defined by the card, announced off the board ("…as you cast this
        spell"), fixed by a target "with mana value X", or inferred from what
        the pool can pay — then held to the card's printed bounds ("X can't be
        greater than …", "X can't be 0"). Also the colours X must be paid with,
        and the empty record of what the payment will put on it.

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or ``(announced_x, resolved_x_value, x_colors,
        x_mana_spent)``.
        """
        x_colors = x_spend_colors_from_text(card.oracle_text)
        # What the payment below actually put on X, per colour. Empty until
        # then, and legitimately empty afterwards for a waived cast (CR
        # 107.3b locks a waived X to 0) or a game not enforcing costs.
        x_mana_spent: dict[str, int] = {}
        resolved_x_value = x_value
        # CR 107.3c: some spells define X themselves, and then the caster does
        # not announce it — the definition wins over anything the wire sent, the
        # way it does for an activated ability's cost one table over. A card
        # that defines an X this cast cannot compute refuses, because the
        # alternative is letting the caster pick a number the card fixed.
        if defines_cast_x(card.oracle_text):
            defined = cast_x_value(self, caster_index, card.oracle_text)
            if defined is None:
                refusal = f"{card.name}: X cannot be determined for this cast"
                self.log.append(refusal)
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )
            resolved_x_value = defined
        # CR 601.2b's other definition, the one printed as the tail of the
        # sentence it sizes: "…, where X is the number of black permanents
        # target opponent controls **as you cast this spell**" (Reap). It takes
        # the announcement away from the caster exactly as the table above does,
        # so it overrides whatever the wire sent — and it is *stamped on the
        # stack item*, which is the half that matters: CR 601.2c fixes the
        # number of targets from it and says the number does not change even if
        # the board it was counted off does. Read through the one reader the
        # picker and the target gate already asked, so the number the caster was
        # offered, the number the announcement was checked against and the
        # number the resolution spends are one number.
        announced_x = self.announced_cast_x(caster_index, card, mode_index=mode_index)
        if announced_x is not None:
            resolved_x_value = announced_x
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            # "…with mana value X" (Spell Blast, Detonate). The target and the X
            # are announced together (CR 601.2b before 601.2c), and only one X
            # makes the pair legal — so a caster who named the target and not the
            # number named the number too. Inferring from the mana pool instead
            # produced a legal cast that then did nothing, which is a spell
            # spending its cost on the wrong value rather than on a choice.
            resolved_x_value = self._x_implied_by_target(
                card, target_player_index, target_permanent_index, target_stack_item,
                target_permanent_ids,
            )
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            resolved_x_value = self._infer_x_value(
                caster, card.mana_cost, extra_generic_tax, x_colors=x_colors,
                reduction=cost_reduction, extra_pips=extra_pip_tax,
            )

        # CR 601.2b's *bound*: "X can't be greater than the number of snow
        # lands you control." (Winter's Chill.) Unlike a definition the caster
        # still announces X, so this is checked against whatever they announced
        # — after the inference above, which is where an unstated X becomes a
        # number, and before any cost is paid so CR 601.2e can return the game
        # to the moment before an illegal proposal. A bound the board cannot be
        # counted for refuses too, for the definition's reason one block up:
        # the alternative is announcing past a limit the card prints.
        if caps_cast_x(card.oracle_text):
            bound = cast_x_ceiling(self, caster_index, card.oracle_text)
            if bound is None or int(resolved_x_value or 0) > bound[0]:
                allowed = "none" if bound is None else str(bound[0])
                printed = "" if bound is None else f" ({bound[1]})"
                refusal = (
                    f"{card.name}: X can't be greater than {allowed}{printed}"
                )
                self.log.append(refusal)
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )

        # CR 601.2b's other bound: "X can't be 0." (Ertai's Meddling.) Beside
        # the ceiling because it is the same rule read the other way, and
        # **after** the inference above for the same reason — a caster who
        # announced nothing has announced 0 here, which is exactly the
        # value this sentence forbids. Refused here, before any cost is paid,
        # so CR 601.2e returns the game to the moment before the proposal.
        if floors_cast_x(card.oracle_text):
            floor = cast_x_floor(card.oracle_text)
            if floor is None or int(resolved_x_value or 0) < floor:
                refusal = f"{card.name}: X can't be less than {floor or 1}"
                self.log.append(refusal)
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )
        return announced_x, resolved_x_value, x_colors, x_mana_spent

    def _pay_cast_mana(
        self, *, card, caster, caster_index, chosen_alternative,
        classification, cost_reduction, extra_generic_tax, extra_pip_tax,
        from_zone, held, offer_x_colorings, permission, resolved_x_value,
        use_free_permission, x_colors, x_mana_spent,
    ):
        """The mana payment (CR 601.2g–h).

        A cost waiver the cast may use (an X spell defaults to paying), then
        whichever of three is owed: the alternative cost's mana, the taxes a
        waived cast still owes (CR 118.9d), or the mana cost — each with every
        increase and reduction gathered for this cast, and X paid in the
        colours it must be.

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or ``(permission, resolved_x_value,
        x_mana_spent)``.
        """
        # A cost waiver ("cast spells from your hand without paying their mana
        # costs", Chandra, Flame's Catalyst's −8). An X spell defaults to
        # *paying*, because a waived {X} is locked to 0 (CR 107.3b) and paying
        # for X=5 usually beats a free X=0 — an explicit request wins either way.
        free_grant = permission if (permission is not None and permission.free) else None
        if (
            free_grant is None
            and card.primary_type != "land"
            and use_free_permission is not False
            and (use_free_permission or "{X}" not in card.mana_cost.upper())
            # CR 118.9a: "A player can't apply two alternative methods of
            # casting or two alternative costs to a single spell." A cost waiver
            # is an alternative cost (`CastPermission.free` cites the same rule),
            # so a caster who announced the spell's own printed one is not also
            # handed a waiver — which would otherwise make the printed cost a
            # pure loss, paid on top of a spell that was already free.
            and chosen_alternative is None
        ):
            waiver = permission_for(self, caster_index, held, "hand", spell=card)
            if waiver is not None and from_zone == "hand":
                free_grant = waiver
                if permission is None:
                    permission = waiver
        if chosen_alternative is not None and card.primary_type != "land":
            # CR 118.9: the alternative cost is paid **rather than** the mana
            # cost, so the mana payment below is skipped whole. Not a reduction
            # and not a waiver: the cost itself is charged just below, once the
            # spell is off the hand, beside the additional costs CR 118.9d keeps
            # in force.
            #
            # CR 118.9c is what this branch does *not* do: nothing here touches
            # `card.mana_cost`, so the taxes above, the commander tax and every
            # "with mana value X" reader still see the printed cost.
            alternative_mana = chosen_alternative.mana
            if "{X}" in card.mana_cost.upper() and "{X}" not in (
                alternative_mana or ""
            ).upper():
                # CR 107.3b: X is 0 when neither the mana cost nor an
                # alternative cost that includes X is paid. The one alternative
                # cost that *does* include it is a granted flashback "equal to
                # its mana cost" (Recoup) over an X spell, whose X is then the
                # one the caster announced.
                resolved_x_value = 0
            if self.enforce_mana_costs:
                # **An alternative cost paid in mana** (CR 702.34a: flashback's
                # "by paying [cost] rather than paying its mana cost"). Charged
                # where the mana cost would have been and by the same payment,
                # because CR 118.9d keeps every additional cost, increase and
                # reduction in force on top of it: the taxes and the discounts
                # gathered above for this cast apply to *this* total — "start
                # with the mana cost or alternative cost you're paying, add any
                # cost increases, then apply any cost reductions".
                #
                # **And an alternative cost paid in something else** — a
                # pitched card, life, a sacrifice (Force of Will, Fireblast,
                # Dream Halls' grant). Its mana is nothing, and CR 118.9d says
                # the same thing about it: the increases and the additional
                # costs are "applied to that alternative cost", so the payment
                # is this same one over an empty run of symbols. This branch
                # charged mana only when the alternative cost itself printed
                # some, which made a Sphere of Resistance, a per-target tax,
                # the commander tax and the mana of a kicker or a buyback the
                # caster had *announced* free for every such cast: 43 of 43
                # pitch spells were cast under a Sphere with an empty pool,
                # and Capsize came back to hand off a Dream Halls discard with
                # its {3} unpaid.
                if alternative_mana is not None and not alternative_mana.strip():
                    # A flashback cost "equal to its mana cost" over a card
                    # that has none (CR 118.6): unpayable, never free.
                    details = (
                        f"{card.name} has no mana cost, so its "
                        f"{chosen_alternative.keyword or 'alternative'} cost "
                        f"is unpayable (CR 118.6)"
                    )
                    self.log.append(details)
                    return SimulationResult(
                        card.name, False, classification.effect_kind, details,
                    )
                keyword_more, keyword_less, keyword_names = (
                    keyword_cost_modifiers(
                        self, caster_index, chosen_alternative.keyword
                    )
                )
                paid = self._pay_cast_cost(
                    caster, card, resolved_x_value, x_colors,
                    extra_generic=extra_generic_tax + keyword_more,
                    reduction=CostReduction(
                        cost_reduction.generic + keyword_less,
                        cost_reduction.colored,
                    ),
                    extra_pips=extra_pip_tax,
                    offer_x_colorings=offer_x_colorings,
                    mana_cost=alternative_mana or "",
                )
                if paid is None:
                    details = (
                        f"insufficient mana for {card.name}'s "
                        f"{chosen_alternative.keyword or 'alternative'} cost "
                        f"({alternative_mana})"
                    )
                    if alternative_mana is None:
                        details = self._mana_still_owed_refusal(
                            card,
                            f"its alternative cost "
                            f"({chosen_alternative.describe()})",
                            extra_generic_tax, extra_pip_tax, cost_reduction,
                        )
                    self.log.append(details)
                    return SimulationResult(
                        card.name, False, classification.effect_kind, details,
                    )
                x_mana_spent = paid
                if keyword_names:
                    self.log.append(
                        f"{card.name}'s {chosen_alternative.keyword} cost is "
                        f"changed by {', '.join(sorted(set(keyword_names)))}"
                    )
            self.log.append(
                f"{card.name} cast for its "
                f"{chosen_alternative.keyword or 'alternative'} cost "
                f"({chosen_alternative.describe()})"
            )
        elif free_grant is not None and card.primary_type != "land":
            if "{X}" in card.mana_cost.upper():
                resolved_x_value = 0  # CR 107.3b: the only legal choice for X
            if self.enforce_mana_costs:
                # "Without paying its mana cost" is an alternative cost
                # (CR 118.9), and CR 118.9d keeps every additional cost and
                # cost increase in force on top of one: what is waived is the
                # mana cost and nothing else. So the payment still runs, over
                # an empty run of symbols — the taxes, the commander tax and
                # the mana of every optional cost this caster announced. It
                # did not run at all, which made a kicker and a buyback free
                # under any waiver (61 of 73 such cards were cast, kicked, with
                # an empty pool) and Aluren a way round Sphere of Resistance.
                x_mana_spent = self._pay_cast_cost(
                    caster, card, resolved_x_value, x_colors,
                    extra_generic=extra_generic_tax, reduction=cost_reduction,
                    extra_pips=extra_pip_tax,
                    offer_x_colorings=offer_x_colorings,
                    mana_cost="",
                )
                if x_mana_spent is None:
                    details = self._mana_still_owed_refusal(
                        card, "cast without paying its mana cost",
                        extra_generic_tax, extra_pip_tax, cost_reduction,
                    )
                    self.log.append(details)
                    return SimulationResult(
                        card.name, False, classification.effect_kind, details,
                    )
            self.log.append(
                f"{card.name} cast without paying its mana cost"
                + (f" ({free_grant.source_name})" if free_grant.source_name else "")
            )
        elif self.enforce_mana_costs and card.primary_type != "land":
            # CR 118.6: an object with no mana cost (as opposed to {0}) has an
            # unpayable cost — attempting to cast it is illegal. (118.6a: a
            # waiver above is an alternative cost and may still be paid.)
            if not card.mana_cost.strip():
                details = f"{card.name} has no mana cost; the cost is unpayable (CR 118.6)"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)
            x_mana_spent = self._pay_cast_cost(
                caster, card, resolved_x_value, x_colors,
                extra_generic=extra_generic_tax, reduction=cost_reduction,
                extra_pips=extra_pip_tax,
                offer_x_colorings=offer_x_colorings,
            )
            if x_mana_spent is None:
                details = f"insufficient mana for {card.name}"
                if offer_x_colorings != ((),):
                    details = (
                        f"insufficient mana for {card.name} "
                        f"(X={len(offer_x_colorings[0])} is paid with one "
                        f"mana of each of that many colors)"
                    )
                elif x_colors:
                    spelling = " and/or ".join(f"{{{sym}}}" for sym in x_colors)
                    details = (
                        f"insufficient mana for {card.name} "
                        f"(X can be paid only with {spelling} mana)"
                    )
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)
        return permission, resolved_x_value, x_mana_spent

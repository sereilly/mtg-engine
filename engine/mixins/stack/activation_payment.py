"""Paying an activated ability's cost (CR 602.2b through CR 601.2h): whether
it can be paid, and what pays it.

``unpayable_activation_cost`` is the one gate over every part of a cost paid
in something other than mana (CR 118.3), asked by the activation path before
it collects anything and by the AI's chooser before it proposes. The
candidate lists beside it are what each chosen cost may be paid with ("Tap two
untapped Spirits you control", "Sacrifice a creature") — one list for the
gate and for the payment's own pick — and ``_named_cost_refusal`` refuses a
permanent the payer *named* that no list holds, rather than paying with
another. The chosen exile (City of Shadows, Necropolis) is chosen here
(``_choose_exile_cost``) and paid by ``activation_charges``, once the mana
payment has gone through.

The module functions price what CR 601.2f computes as the ability is
activated — ``activation_life_cost``, ``activation_mana_per_counter`` and
``activation_cost_choice`` (a printed "Pay 2 life or {2}") — each asked by the
gate and by the payment, which must get the same number.

Split out of ``activation.py`` at the 2,000-line cap, and composed onto
``Game`` with the other parts of ``AbilityActivationMixin``, directly after
it.
"""

from __future__ import annotations

from ...aura_grants import attached_ability_cost_reduction
from ...cost_modifiers import (ability_cost_reduction, ability_cost_tax,
                                sacrifice_taxes)
from ...cost_x_definitions import cost_x_is_defined, cost_x_value
from ...mana_payment import mana_cost_from_symbols
from ...oracle_types import x_spend_colors_from_text
from ...self_cost_modifiers import ability_self_reduction_amount
from ...handlers._filters import _card_matches_filter
from ...handlers._targets import attached_host
from ...subject_filters import card_matches_any, filter_head_noun, subject_matches


# Instruction kinds whose handler performs the sacrifice its own cost clause
# names. Diamond Valley's "{T}, Sacrifice a creature: You gain life equal to
# the sacrificed creature's toughness" is one resolution: the handler picks the
# creature *because* it has to read the toughness it had on the battlefield
# (CR 608.2h, last-known information). Charging the cost generically as well
# would sacrifice two creatures for one activation. Kinds here pay it
# themselves; everything else pays through the activation path's cost
# payment (``activation_charges._pay_activation_costs``).
#: Instruction kinds whose *handler* performs the sacrifice itself, so the
#: activation path must not also pay it — two creatures for one ability.
#:
#: `sacrifice_creature_for_mana` used to be listed here and does not belong:
#: its handler reads back what the cost ate (`sacrificed_for_cost`) and
#: sacrifices nothing. That was harmless while only Metamorphosis and Sacrifice
#: produced it — both sorceries, whose cost the *casting* path pays, so this
#: set never saw them — and it silently stopped paying the cost the moment an
#: activated ability produced the same kind (Priest of Yawgmoth).
#:
#: **Empty today, and that is the resting state.** The one entry was
#: `sacrifice_creature_gain_life_by_toughness`, Diamond Valley's fused hook: it
#: sacrificed the creature itself, so the cost path had to be told to stand
#: down. Life Chisel prints the same sentence with a different cost clause, so
#: the sentence became a production ("equal to the sacrificed creature's
#: toughness") that reads the cost's own record and sacrifices nothing — and a
#: handler that only reads does not belong here. The set survives because the
#: next fused kind will, and an empty frozenset says so more clearly than a
#: comment on an absence.
COST_PERFORMING_KINDS: frozenset[str] = frozenset()


#: The pool's symbols, in the order every payment path spends them.
_POOL_SYMBOLS = ("W", "U", "B", "R", "G", "C")


def activation_life_cost(cost, permanent, controller=None) -> int:
    """How much life activating this ability actually costs, right now.

    ``ActivatedAbilityCost.pay_life`` is the printed number and is usually the
    whole answer. Where ``pay_life_per_counter`` is set it is a **rate**:
    "Pay 3 life for each velocity counter on this enchantment" (Tornado) owes
    nothing on the first activation and three more on each one after, because
    the ability's own effect adds a counter as it resolves. And where
    ``pay_life_half_rounded_up`` is set there is no printed number at all: the
    amount is half the payer's own life total, rounded up (Lurking Evil,
    CR 107.2).

    CR 601.2f computes a cost as the ability is activated, so this is asked
    twice — once by the payability gate (CR 602.5c makes an unpayable cost an
    *unactivatable* ability rather than a free one) and once by the payment —
    and both must get the same number, which is why it is a function rather
    than two reads of the field.

    *controller* is the seat paying, needed only by the halving: the other two
    readings are about the printed cost and the ability's own source. Optional
    so the callers that hold no seat keep working, and a halved cost with no
    seat is 0 rather than a guess — the direction that refuses the activation
    (CR 602.5c) rather than making it free.
    """
    if getattr(cost, "pay_life_half_rounded_up", False):
        # CR 119.4: a life payment is legal while the total is at least the
        # amount, and half of a total rounded up never exceeds it — so this
        # cost is always payable, which is why the gate never refuses it and
        # the payment is the whole of what happens. Negative life (already lost
        # by CR 704.5a, but the sweep runs at priority) halves to nothing
        # rather than to a payment that would give life back.
        life = 0 if controller is None else int(getattr(controller, "life", 0))
        return max(0, -(-life // 2))
    per_counter = getattr(cost, "pay_life_per_counter", None)
    if not per_counter:
        return int(cost.pay_life)
    if permanent is None:
        return 0
    from ...named_counters import counters_on

    return int(cost.pay_life) * counters_on(permanent, str(per_counter))


def activation_mana_per_counter(cost, permanent) -> dict[str, int]:
    """The mana a per-counter rate owes right now, as a symbol dict.

    ``ActivatedAbilityCost.mana_per_counter_cost`` is what **one** counter
    costs; this multiplies it by how many the source carries.
    :func:`activation_life_cost`'s twin one resource over, and a function for
    its reason: CR 601.2f's cost is computed at activation and asked twice --
    once by the payability gate and once by the payment -- and both must get
    the same number.

    Empty for every ability printing no such rate, which is all but one card in
    the pool, and empty for a source that has left the battlefield: a counter
    nobody can count is none.
    """
    rate = getattr(cost, "mana_per_counter_cost", None)
    counter = getattr(cost, "mana_per_counter", None)
    if not rate or not counter or permanent is None:
        return {}
    from ...named_counters import counters_on

    many = counters_on(permanent, str(counter))
    return {
        symbol: amount * many
        for symbol, amount in rate.items()
        if amount and many
    }


def _pool_covers(pool: dict, required: dict) -> bool:
    """Whether *pool* alone pays *required*, coloured pips first.

    Deliberately narrower than ``_pay_mana_cost``: it ignores restricted
    buckets (CR 106.6) and the "spend as though it were any colour" grants.
    Its only caller is the choice below, where a **false negative** picks the
    other printed payment — a payment the card allows just as much — and a
    false positive would skip a life cost for mana that could not be spent.
    Under-reading is therefore the direction with no wrong answer in it.
    """
    left = {symbol: int(pool.get(symbol, 0)) for symbol in _POOL_SYMBOLS}
    for symbol in _POOL_SYMBOLS:
        need = int(required.get(symbol, 0))
        if left[symbol] < need:
            return False
        left[symbol] -= need
    return sum(left.values()) >= int(required.get("generic", 0))


def activation_cost_choice(controller, cost, permanent) -> tuple[int, dict]:
    """Which of a printed "or" is paid: ``(life owed, extra mana to charge)``.

    "Pay 2 life **or {2}**" (Tidal Control) is CR 601.2h's choice between two
    payments, made as the ability is activated. Both halves come back from one
    call because the gate that refuses an unpayable cost (CR 602.5c) and the
    payment itself must agree — asked twice with two rules they could pay the
    mana and charge the life as well, which is the flat reading this replaced.

    The rule is **spend what is already floating, else pay the life**: an
    activation spends the pool (producing the mana was the player's own prior
    action), so mana that is not there is not a payment this ability can make,
    and the life always is. It is a default rather than an offer — putting the
    choice to an interactive seat needs a cost-picker shape that does not exist
    (see ROADMAP's alternative-cost note, the same gap on the cast side).
    """
    life = activation_life_cost(cost, permanent, controller)
    alternative = getattr(cost, "alternative_mana", None)
    if not alternative or not life:
        return life, {}
    if _pool_covers(getattr(controller, "mana_pool", {}) or {}, alternative):
        return 0, dict(alternative)
    return life, {}


class ActivationPaymentMixin:

    def activation_mana_charge(
        self, controller_index, permanent, ability, *, x_value=None,
        alternative_mana=None, target_stack_item=None,
    ):
        """The mana activating *ability* of *permanent* charges (CR 601.2f
        via 602.2b): the printed symbols, a per-counter rate, the "…or {2}"
        the payer took (*alternative_mana*), an attached host's mana cost, X
        at *x_value* (or as the card defines it), then the increases and the
        reductions in force.

        Pure — nothing is paid, and the log lines the activation path writes
        about the price come back in ``log_lines`` for the path to append.
        Asked by the path (``_activate_onto_stack``) and by the wire's X
        prompt (``web/offers.x_payable``), which must price an X the way the
        payment will. Returns the refusal's sentence, or ``(required_cost,
        x_value, price_notes, log_lines)``: the symbol dict, the X the cost
        was priced at (a defined X replaces the announced one), what moved the
        price (for a refusal to name) and the lines to log.
        """
        alternative_mana = alternative_mana or {}
        price_notes: list[str] = []
        log_lines: list[str] = []
        required_cost = dict(ability.cost.mana)
        # "Pay {1} **for each +1/+1 counter on this creature**" (Skeleton
        # Scavengers). CR 601.2f computes the cost as the ability is
        # activated, so the rate is multiplied here -- the same moment
        # ``activation_life_cost`` reads its own counter, and by the same
        # count, so a card printing both would price them off one board.
        for symbol, count in activation_mana_per_counter(
            ability.cost, permanent
        ).items():
            required_cost[symbol] = required_cost.get(symbol, 0) + int(count)
        # "…**or {2}**" when the pool covered it. Folded into the ordinary
        # payment rather than charged beside it, so every tax, reduction and
        # restricted-bucket rule below applies to it exactly as to a printed
        # mana cost.
        for symbol, count in alternative_mana.items():
            required_cost[symbol] = required_cost.get(symbol, 0) + int(count)
        # "**Pay enchanted creature's mana cost**: …" (Merseine.) The symbols
        # are the *host's* and cannot be known when the card compiles, so the
        # cost dict is built here, at the one moment there is a host to read
        # (CR 202.1 — a permanent's mana cost is what is printed in its upper
        # right corner, whatever the copy and text-change layers have made of
        # the object).
        #
        # An Aura with no host, or a host whose printed cost carries a symbol
        # this engine cannot spend, refuses the activation with nothing paid
        # (CR 602.2b). Never a fallback to the empty dict beside it: an
        # unreadable cost read as zero is an ability activated for free, which
        # is the failure every cost reader in this engine is written against.
        if ability.cost.mana_from_attached:
            host = attached_host(self, permanent, last_known=False)
            printed = None if host is None else (
                getattr(host.card, "mana_cost", "") or ""
            )
            symbols = None if host is None else mana_cost_from_symbols(printed)
            if host is None or (symbols is None and printed.strip()):
                return (
                    f"{permanent.card.name}: the mana cost it charges is the "
                    "attached permanent's, and there is none to read"
                )
            for symbol, count in (symbols or {}).items():
                required_cost[symbol] = required_cost.get(symbol, 0) + count
        # Abilities with an "{X}" in their cost (e.g. Clockwork Beast's
        # "{X}, {T}: Put up to X +1/+0 counters") charge X generic mana on top of
        # the printed symbols, where X is the amount the player chose.
        #
        # **Per printed symbol, and only in the cost clause.** Voodoo Doll's
        # cost is "{X}{X}" — two of them, so it charges 2X — and a card whose
        # *effect* mentions X ("deals X damage") is not charging a second one.
        # A single substring test read both as one X, which is half the cost on
        # the one card in the pool that prints the double.
        x_symbols = (ability.source_line or "").lower().split(":", 1)[0].count("{x}")
        # "X is the number of pin counters on this artifact." (Voodoo Doll.)
        # The card *defines* X, so the activator does not announce it
        # (CR 601.2b) — and the definition is read from the same table the
        # grammar consumed the sentence through, because an X consumed by one
        # reader and unknown to the other is a cost nobody charges.
        # The chosen spell is handed over because a definition may read it:
        # "X is twice the mana value of **that spell**" (Reflecting Mirror) is
        # priced off the object the ability targets, not off the board.
        defined_x = cost_x_value(
            self, permanent, ability.source_line or "", target=target_stack_item
        )
        if defined_x is not None:
            x_value = defined_x
        elif cost_x_is_defined(ability.source_line or ""):
            # The card defines X and this activation cannot compute it — no
            # target was named, most often. **Not zero**: an {X} nobody charges
            # is a free ability, which is exactly the failure
            # ``engine/cost_x_definitions.py`` exists to prevent, so the
            # activation is refused with nothing paid (CR 601.2b via 602.2b).
            return (
                f"{permanent.card.name}: the value of X is defined by the card "
                "and nothing here determines it"
            )
        if x_value and x_symbols:
            # "Spend only red mana on X." (Crimson Hellkite.) The X pips are
            # charged as that colour rather than as generic, which is the whole
            # of the restriction: a generic pip is payable from any source, so
            # a clause consumed by the grammar and dropped here would be an
            # ability that works from a pool the card forbids.
            #
            # Read off the raw ability line, the same text
            # ``_parse_x_spend_restriction`` handed to this reader, so the
            # sentence the grammar consumed and the cost this charges cannot
            # come apart. Exactly one colour reaches here: the grammar refuses
            # the "and/or" pair, whose split is a choice this path cannot ask.
            x_colors = x_spend_colors_from_text(ability.source_line or "")
            if len(x_colors) == 1:
                symbol = x_colors[0]
                required_cost[symbol] = (
                    required_cost.get(symbol, 0) + int(x_value) * x_symbols
                )
            else:
                required_cost["generic"] = (
                    required_cost.get("generic", 0) + int(x_value) * x_symbols
                )
        # Ability cost taxes (Gloom: "Activated abilities of white enchantments
        # cost {3} more to activate"; the white-spell cast tax is applied
        # separately in cast_from_hand).
        extra_ability_tax, taxing_names = ability_cost_tax(
            self, controller_index, permanent, ability
        )
        # What moves the price, for the payment's refusal to say (the log
        # lines are taken back with a refused attempt, CR 733.1).
        if extra_ability_tax:
            required_cost["generic"] = required_cost.get("generic", 0) + extra_ability_tax
            log_lines.append(f"{permanent.card.name}'s ability is taxed by {', '.join(taxing_names)}")
            price_notes.append(
                f"costs {{{extra_ability_tax}}} more: {', '.join(taxing_names)}"
            )
        # "This ability costs {1} less to activate for each Shrine you control."
        # (Sanctum of Tranquil Light.) After the tax, because CR 601.2f applies
        # increases before reductions, and clamped at zero because a cost cannot
        # go below {0} — the same clamp `reduce_cost` makes for a spell.
        discount = ability_self_reduction_amount(self, controller_index, permanent)
        if discount:
            before = required_cost.get("generic", 0)
            required_cost["generic"] = max(0, before - discount)
            log_lines.append(
                f"{permanent.card.name}'s ability costs "
                f"{{{before - required_cost['generic']}}} less to activate"
            )
            price_notes.append(f"costs {{{before - required_cost['generic']}}} less")
        # "Enchanted artifact's activated abilities cost {2} less to activate.
        # **This effect can't reduce the mana in that cost to less than one
        # mana.**" (Power Artifact.) The reduction is on the *Aura*, not on the
        # permanent whose ability it is, so it is read off what is attached
        # rather than off this card's own text.
        #
        # The floor is over the *whole* cost, coloured pips included — "the
        # mana in that cost", not the generic part of it — which is why it is
        # applied after the subtraction rather than as a clamp inside it. A {2}
        # ability reduced by {2} pays {1}, not nothing; a {B} ability is
        # already at the floor and pays {B}.
        aura_discount, aura_floor = attached_ability_cost_reduction(permanent)
        # "Activated abilities of creatures cost {1} less to activate. This
        # effect can't reduce the mana in that cost to less than one mana."
        # (Heartstone.) The identical rider from a permanent that enchants
        # nothing, so it is read off the board rather than off what is attached
        # -- and folded into the *same* application, because CR 601.2f applies
        # every reduction to one cost. Two applications would each measure the
        # floor against a cost the other had already cut.
        board_discount, reducing_names, board_floor = ability_cost_reduction(
            self, controller_index, permanent, ability
        )
        aura_discount += board_discount
        # The **highest** floor, for ``attached_ability_cost_reduction``'s
        # reason: two reductions must not cancel each other's protection
        # against a free ability.
        floor = max(aura_floor, board_floor)
        if reducing_names:
            log_lines.append(
                f"{permanent.card.name}'s ability is cheapened by "
                f"{', '.join(reducing_names)}"
            )
        if aura_discount:
            before_total = sum(required_cost.values())
            generic = required_cost.get("generic", 0)
            coloured = before_total - generic
            reduced_generic = max(0, generic - aura_discount)
            if reduced_generic + coloured < floor:
                reduced_generic = max(0, floor - coloured)
            required_cost["generic"] = reduced_generic
            if before_total != reduced_generic + coloured:
                log_lines.append(
                    f"{permanent.card.name}'s ability costs "
                    f"{{{before_total - reduced_generic - coloured}}} less to activate"
                )
                price_notes.append(
                    f"costs {{{before_total - reduced_generic - coloured}}} less"
                    + (f": {', '.join(reducing_names)}" if reducing_names else "")
                )
        return required_cost, x_value, price_notes, log_lines

    # -- Whether an activation's cost can be paid at all ----------------------

    def unpayable_activation_cost(
        self, controller_index: int, permanent, ability, *,
        x_value: int | None = None,
    ) -> str | None:
        """Why *ability*'s cost cannot be paid from this board, or None.

        CR 601.2h, reached through CR 602.2b: "Unpayable costs can't be paid"
        — and CR 118.3 says when a cost is unpayable: the payer lacks the
        resources to pay it **fully**. So this asks, of every part of the
        cost that is paid in something other than mana, whether the board
        holds enough of that something: cards in the hand, the library and the
        graveyard, life, counters, and the permanents a chosen cost names
        (to sacrifice, tap, return, untap, put a counter on, take one off,
        exile), the host an attached cost names, and the sacrifices a board
        tax adds (Drought). Mana is the payment's own question, and a named
        payment's legality is the announcement's (``_named_cost_refusal``).

        **The activation path's one gate, and its readers ask it.** The path
        calls this once, after its {T} checks and before it collects a single
        cost — the words it returns are the ones it logs — and the AI's
        chooser asks it before it proposes an activation. The chooser used to
        ask about the costs it knew one at a time and none it did not, so it
        proposed Grim Lavamancer's "Exile two cards from your graveyard" over
        an empty graveyard every turn, and thirty other abilities like it
        (``tests/ai/test_ai_activation_cost_census.py``). The cast side has
        had this shape all along (``_unpayable_additional_cost``).

        Pure: it spends nothing and moves nothing, so asking it costs a scan
        and cannot leave a half-paid cost behind. *x_value* is the announced
        X (CR 601.2b) a cost sized by X is held to; a caller announcing none
        announces zero, the path's stated default.
        """
        from ...graveyard_order import positions_named
        from ...named_counters import counters_on

        cost = ability.cost
        controller = self.players[controller_index]
        name = permanent.card.name

        # "Remove a <kind> counter from this creature" (Scavenging Ghoul), "…X
        # charge counters" (Kyren Toy). "Any number of" and "all" are payable
        # with none, since zero is a number and all of zero is zero.
        if cost.remove_counter and cost.remove_counter_filter is None:
            kind = cost.remove_counter
            held = counters_on(permanent, kind)
            wanted = cost.remove_counter_count
            if wanted == "x":
                total = max(0, int(x_value or 0))
                if held < total:
                    return (
                        f"{name} has {held} {kind} counter(s), "
                        f"fewer than the {total} announced for X"
                    )
            elif wanted not in ("any", "all") and held < int(wanted):
                return f"{name} has no {kind} counters to remove"
        # Jandor's Ring: a card drawn this turn still in hand.
        if cost.discard_last_drawn and controller.last_card_drawn_this_turn() is None:
            return f"{name}: no card drawn this turn remains in hand to discard"
        # "Discard a card" / "Discard a land card or Shrine card". Naming the
        # phrase when there is one: "not enough cards in hand" is a falsehood
        # for a hand full of cards that simply do not answer it.
        if cost.discard_cards and len(
            self._discard_cost_payable(cost, controller)
        ) < cost.discard_cards:
            shortfall = (
                "no card in hand answers this cost"
                if cost.discard_filters
                else "not enough cards in hand to discard"
            )
            return f"{name}: {shortfall}"
        # "Exile the top creature card of your graveyard" (Necratog): the pile
        # is scanned, so a graveyard with no creature card pays nothing.
        if cost.exile_graveyard_position is not None and not positions_named(
            controller.graveyard, cost.exile_graveyard_position,
            game=self, owner=controller,
        ):
            return (
                f"{name}: {controller.name}'s graveyard has "
                f"nothing its cost can exile"
            )
        if cost.hand_to_library_top > len(controller.hand):
            return (
                f"{name}: {controller.name} has "
                f"{len(controller.hand)} card(s) in hand and its cost puts "
                f"{cost.hand_to_library_top} on top of their library"
            )
        # "Put three cards from your graveyard on the bottom of your library"
        # (Battlefield Scrounger): CR 118.3 — a pile one card short pays none.
        if cost.graveyard_to_library_bottom > len(controller.graveyard):
            return (
                f"{name}: {controller.name} has "
                f"{len(controller.graveyard)} card(s) in their graveyard and its "
                f"cost puts {cost.graveyard_to_library_bottom} on the bottom of "
                "their library"
            )
        if cost.exile_top_of_library > len(controller.library):
            return (
                f"{name}: {controller.name} has "
                f"{len(controller.library)} card(s) left and its cost exiles "
                f"{cost.exile_top_of_library}"
            )
        # CR 701.17b: a mill cost owes cards out of the pile the library
        # exile above shares.
        if getattr(cost, "mill_cards", 0) and (
            cost.mill_cards + cost.exile_top_of_library > len(controller.library)
        ):
            return (
                f"{name}: {controller.name} has "
                f"{len(controller.library)} card(s) left and its cost mills "
                f"{cost.mill_cards}"
            )
        # CR 119.4: life is paid only up to the total. The choice between a
        # printed "or" is the payment's own (``activation_cost_choice``).
        life_owed, _alternative = activation_cost_choice(controller, cost, permanent)
        if life_owed and controller.life < life_owed:
            return (
                f"{name}: {controller.name} cannot pay "
                f"{life_owed} life with {controller.life} remaining"
            )
        # The chosen sacrifice: "Sacrifice X lands" against the announced X,
        # "Sacrifice two Goblins" against its printed count. "Any number of"
        # is payable with none.
        sacrifice_victim = None
        if cost.sacrifice_filter is not None and cost.sacrifice_count == "x":
            wanted = max(0, int(x_value or 0))
            found = self._sacrifice_cost_candidates(
                cost, controller_index, permanent, keep_source=True,
            )
            if len(found) < wanted:
                return (
                    f"{name}: {len(found)} "
                    f"{filter_head_noun(cost.sacrifice_filter)}(s) to sacrifice, "
                    f"fewer than the {wanted} announced for X"
                )
        elif (
            cost.sacrifice_filter is not None
            and cost.sacrifice_count != "any"
            and ability.instruction is not None
            and ability.instruction.kind not in COST_PERFORMING_KINDS
        ):
            found = self._sacrifice_cost_candidates(cost, controller_index, permanent)
            noun = filter_head_noun(cost.sacrifice_filter)
            if not found:
                return f"{name}: no {noun} available to sacrifice"
            wanted = cost.sacrifice_count if isinstance(cost.sacrifice_count, int) else 1
            if len(found) < wanted:
                return f"{name}: not enough {noun}s to sacrifice for its cost"
            if wanted == 1:
                # The charger's own default (``_choose_activation_cost_payers``), so
                # the conjoined half below is asked beside the same victim.
                sacrifice_victim = self.default_sacrifice_pick(
                    found, paying_for=permanent,
                )
        if cost.sacrifice_attached:
            host = permanent.metadata.get("attached_to")
            if host is None or not self.is_on_battlefield(host):
                return (
                    f"{name}: the permanent it is attached to "
                    "cannot be sacrificed to pay its cost"
                )
        if cost.tap_count and len(
            self._tap_cost_candidates(cost, controller_index)
        ) < cost.tap_count:
            return (
                f"{name}: not enough untapped "
                f"{filter_head_noun(cost.tap_filter or {})}s to tap for its cost"
            )
        if cost.return_to_hand_count and len(
            self._return_cost_candidates(cost, controller_index)
        ) < cost.return_to_hand_count:
            return (
                f"{name}: not enough "
                f"{filter_head_noun(cost.return_to_hand_filter or {})}s to "
                "return for its cost"
            )
        if cost.untap_filter is not None and not self._untap_cost_candidates(
            cost, controller_index, permanent
        ):
            return (
                f"{name}: no tapped "
                f"{filter_head_noun(cost.untap_filter)} to untap for its cost"
            )
        if cost.put_counter_filter is not None and not self._put_counter_cost_candidates(
            cost, controller_index, permanent
        ):
            return (
                f"{name}: no {filter_head_noun(cost.put_counter_filter)} to put "
                f"a {cost.put_counter} counter on"
            )
        if (
            cost.remove_counter_filter is not None
            and not self._remove_counter_cost_candidates(
                cost, controller_index, permanent
            )
        ):
            return (
                f"{name}: no {filter_head_noun(cost.remove_counter_filter)} "
                f"with a {cost.remove_counter} counter to remove"
            )
        # "Sacrifice a creature **and a Swamp**": the second must be another
        # permanent than the one the first sacrifice takes.
        if cost.sacrifice_also_filter is not None and not self._sacrifice_also_candidates(
            cost, controller_index, permanent, sacrifice_victim,
        ):
            return (
                f"{name}: no {filter_head_noun(cost.sacrifice_also_filter)} "
                "available to sacrifice"
            )
        if cost.tap_attached:
            host = permanent.metadata.get("attached_to")
            if host is None or not self.is_on_battlefield(host) or host.tapped:
                return (
                    f"{name}: the permanent it is attached to "
                    "cannot be tapped to pay its cost"
                )
        if cost.exile_filter is not None and self._choose_exile_cost(
            cost, controller, controller_index, permanent, None,
        ) is None:
            return f"{name}: nothing available to exile as a cost"
        # "Pay enchanted creature's mana cost" (Merseine): a host to read, and
        # a printed cost this engine can spend.
        if cost.mana_from_attached:
            host = attached_host(self, permanent, last_known=False)
            printed = None if host is None else (
                getattr(host.card, "mana_cost", "") or ""
            )
            symbols = None if host is None else mana_cost_from_symbols(printed)
            if host is None or (symbols is None and printed.strip()):
                return (
                    f"{name}: the mana cost it charges is the "
                    "attached permanent's, and there is none to read"
                )
        # A sacrifice a board adds to the cost (Drought, Brutal Suppression).
        victims = self._sacrifice_tax_victims(
            controller_index,
            sacrifice_taxes(self, controller_index, cost.mana, "activate", source=permanent),
        )
        if isinstance(victims, str):
            return f"{name}: {victims} (CR 601.2h)"
        return None

    # The candidate lists a chosen cost is paid from. One list per cost for
    # the gate above and for the payment's own pick in
    # ``_choose_activation_cost_payers``, so the two cannot count different sets.

    def _discard_cost_payable(self, cost, controller) -> list:
        """The cards in hand a "Discard a <phrase>" cost may take — asked with
        the game and the payer, whose statics colour the hand (CR 613.1)."""
        return [
            card for card in controller.hand
            if card_matches_any(
                card, cost.discard_filters, game=self, owner=controller,
            )
        ]

    def _sacrifice_cost_candidates(
        self, cost, controller_index: int, permanent, *, keep_source: bool = False,
    ) -> list:
        """What a "Sacrifice <noun phrase>" cost may take. "Sacrifice two lands
        **and this artifact**" (Sandstone Deadfall) prints the source as its
        own entry, so it cannot also be one of the chosen ones — unless
        *keep_source*, the "Sacrifice X <noun phrase>" reading, which has
        never excluded it."""
        return [
            perm for perm in self.controlled_by(controller_index)
            if subject_matches(
                self, perm, cost.sacrifice_filter,
                observer=controller_index, source=permanent,
            )
            and (keep_source or not (cost.sacrifice_self and perm is permanent))
        ]

    def _tap_cost_candidates(self, cost, controller_index: int) -> list:
        """What "Tap N untapped <noun phrase> you control" may tap: untapped by
        construction, and the source only if the phrase names it."""
        described = cost.tap_filter or {}
        return [
            perm for perm in self.controlled_by(controller_index)
            if not perm.tapped and subject_matches(self, perm, described)
        ]

    def _choose_tap_cost_permanents(
        self, cost, candidates: list, cost_permanent_ids,
    ) -> list:
        """Which of *candidates* a "Tap N untapped <noun phrase>" cost taps:
        the ones the payer named by id (CR 601.2b), deduplicated by identity —
        two references to one permanent do not pay a two-permanent cost — and
        then the deterministic pick, in board order, for the rest. Too few
        candidates is the cost gate's refusal, asked before this."""
        named = [
            found
            for found in (
                self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
            )
            if found is not None and any(c is found for c in candidates)
        ]
        chosen: list = []
        for perm in named:
            if not any(perm is already for already in chosen):
                chosen.append(perm)
        for perm in candidates:
            if len(chosen) >= cost.tap_count:
                break
            if not any(perm is already for already in chosen):
                chosen.append(perm)
        return chosen[:cost.tap_count]

    def _return_cost_candidates(self, cost, controller_index: int) -> list:
        """What "Return N <noun phrase> you control to their owner's hand" may
        return."""
        described = cost.return_to_hand_filter or {}
        return [
            perm for perm in self.controlled_by(controller_index)
            if subject_matches(self, perm, described)
        ]

    def _untap_cost_candidates(self, cost, controller_index: int, permanent) -> list:
        """What "Untap a tapped <noun phrase>" may untap — off every
        battlefield, since the printed seat clause is what narrows it."""
        return [
            perm for perm in self.all_permanents()
            if perm.tapped and subject_matches(
                self, perm, cost.untap_filter,
                observer=controller_index, source=permanent,
            )
        ]

    def _put_counter_cost_candidates(
        self, cost, controller_index: int, permanent,
    ) -> list:
        """What "Put a <kind> counter on a <noun phrase> you control" may mark."""
        return [
            perm for perm in self.controlled_by(controller_index)
            if subject_matches(
                self, perm, cost.put_counter_filter,
                observer=controller_index, source=permanent,
            )
        ]

    def _remove_counter_cost_candidates(
        self, cost, controller_index: int, permanent,
    ) -> list:
        """What "Remove a <kind> counter from a <noun phrase> you control" may
        take the counters off: the permanent must match **and** hold them."""
        from ...named_counters import counters_on

        wanted = cost.remove_counter_count
        needed = int(wanted) if isinstance(wanted, int) else 1
        return [
            perm for perm in self.controlled_by(controller_index)
            if subject_matches(
                self, perm, cost.remove_counter_filter,
                observer=controller_index, source=permanent,
            )
            and counters_on(perm, str(cost.remove_counter)) >= needed
        ]

    def _sacrifice_also_candidates(
        self, cost, controller_index: int, permanent, victim,
    ) -> list:
        """What the *second* object of a conjoined sacrifice may be: anything
        the phrase names except the permanent the first sacrifice takes."""
        return [
            perm for perm in self.controlled_by(controller_index)
            if subject_matches(
                self, perm, cost.sacrifice_also_filter,
                observer=controller_index, source=permanent,
            )
            and perm is not victim
        ]

    def _choose_exile_cost(
        self, cost, controller, controller_index: int, permanent,
        cost_permanent_index, cost_permanent_ids=None,
        cost_graveyard_indices=None, spare_graveyard_slot=None,
        price: bool = False,
    ) -> "tuple | None":
        """What an "Exile <noun phrase>" activation cost will eat, chosen and
        **not yet paid** — or None when nothing in the named zone could pay,
        which makes the ability unactivatable (CR 602.2b) with nothing spent.

        ``(zone, pile, slots, objects)``: the zone, the seat whose hand or
        graveyard pays (None on the battlefield), the chosen slots in that pile
        and the objects in them. :meth:`_pay_exile_cost` moves them. Two steps
        because a choice is a check and a payment is not: this used to exile
        as it chose, above every refusal still to come, so a refused
        activation had already eaten the card (CR 601.2h; CR 733.1).

        Three zones, one rule. The battlefield enumerates the *permanents the
        payer controls* through the control seam and asks ``subject_matches``,
        the same predicate the picker offers by. A graveyard and a hand
        enumerate the payer's own pile and ask the card matcher instead,
        because a card in a zone has no computed characteristics at all
        (CR 613.1).

        **Idiom 11**: in a graveyard, two copies of a card are literally one
        object, so the chosen slot is resolved to its card *before* anything
        leaves the zone and removed by index — a scan by value takes whichever
        copy comes first.

        The named choice is honoured where it is legal and otherwise the first
        eligible object is taken, which is what every other cost payment in this
        file does for a non-interactive seat. *price* says the cards out of the
        payer's own graveyard are a plain payment — the effect does not read
        which they were (``ai_prompt_readers.reads_what_its_cost_exiled``) — and then
        "first" is the least valuable (``ai_prompt_readers.graveyard_price_order``):
        Grim Lavamancer gave up the bottom two cards of its pile, a flashback
        spell as soon as a land.
        """
        described = cost.exile_filter or {}
        # "Exile **any number of** cards from your graveyard" (Painbringer):
        # the payer's own count, so nothing is owed beyond what was named and
        # nothing is defaulted — choosing cards for a seat that named none
        # would exile a graveyard to pay a cost of zero (the reading the
        # sacrifice's "any number of" gets, for the same reason).
        any_number = getattr(cost, "exile_count", 1) == "any"
        wanted = 0 if any_number else max(
            1, int(getattr(cost, "exile_count", 1) or 1)
        )
        if cost.exile_zone == "hand":
            # "Exile a card from your hand" (Cadaverous Bloom). The payer's own
            # hand, always: a hand is hidden (CR 400.2), so a cost naming
            # somebody else's would ask a player to choose a card they cannot
            # see, and the grammar's gate refuses that phrase for the same
            # reason.
            #
            # Through ``take_card_from_hand``, not a filter over the list: a
            # deck repeats one immutable ``CardDefinition`` per copy, so every
            # copy of a card in a hand is the same Python object and an identity
            # filter removes all of them where this cost eats exactly one.
            # Resolved to *cards* before anything moves, for the graveyard
            # branch's reason one screen up — every removal renumbers the slots
            # behind it.
            slots = [
                index for index, card in enumerate(controller.hand)
                if _card_matches_filter(
                    card, described, game=self, owner=controller,
                )
            ]
            if len(slots) < wanted:
                return None
            named = (
                [cost_permanent_index]
                if isinstance(cost_permanent_index, int)
                and cost_permanent_index in slots
                else []
            )
            chosen_slots: list[int] = []
            for slot in [*named, *slots]:
                if len(chosen_slots) >= wanted:
                    break
                if slot not in chosen_slots:
                    chosen_slots.append(slot)
            return (
                "hand", controller, tuple(chosen_slots),
                tuple(controller.hand[slot] for slot in chosen_slots),
            )
        if cost.exile_zone == "graveyard":
            # Whose pile. "your graveyard" (Necropolis) is one seat;
            # ``exile_zone_owner`` of None is "a graveyard" — anybody's — and
            # then **one** of them has to hold the whole payment: "from a
            # single graveyard" (Night Soil) is a fact about the set, so the
            # piles are tried whole rather than pooled. Pooled, the cost would
            # be payable with one card from each of two graveyards, which is
            # strictly cheaper than the card prints.
            owner = getattr(cost, "exile_zone_owner", "you")
            piles = (
                [controller] if owner == "you"
                # The payer's own pile first, then the rest in seat order, so a
                # seat that names nothing is deterministic — the rule every
                # other default pick of the activation path follows.
                else [
                    controller,
                    *(seat for seat in self.players if seat is not controller),
                ]
            )
            for pile in piles:
                slots = [
                    index for index, card in enumerate(pile.graveyard)
                    if _card_matches_filter(
                        card, described, game=self, owner=pile,
                    )
                ]
                if len(slots) < wanted:
                    continue
                # The whole set by slot where the payer named one
                # (``cost_graveyard_indices``), else the one-card spelling.
                named = [
                    slot for slot in (
                        cost_graveyard_indices
                        if cost_graveyard_indices is not None
                        else [cost_permanent_index]
                    )
                    if isinstance(slot, int) and slot in slots
                ]
                # The default fills from the pile in order, **the ability's own
                # target last** (``spare_graveyard_slot``, a ``(seat, slot)``):
                # "Exile two cards from your graveyard: Return target creature
                # card from your graveyard to your hand" (Cabal Surgeon) named
                # its target first (CR 601.2c), and a payer who names no cards
                # is not choosing to exile it — the first two in pile order
                # ate the Grizzly Bears the ability was aimed at whenever it
                # sat on top. Still taken when nothing else can pay: CR 601.2h
                # lets the cost be paid with it, and the ability then has no
                # legal target (CR 608.2b).
                default_order = slots
                if price and pile is controller:
                    from ...ai_prompt_readers import graveyard_price_order

                    default_order = graveyard_price_order(
                        self, controller_index, slots,
                    )
                if (
                    spare_graveyard_slot is not None
                    and pile is self.players[spare_graveyard_slot[0]]
                ):
                    spared = spare_graveyard_slot[1]
                    default_order = [
                        *(slot for slot in slots if slot != spared),
                        *(slot for slot in slots if slot == spared),
                    ]
                chosen_slots: list[int] = []
                for slot in named if any_number else [*named, *default_order]:
                    if not any_number and len(chosen_slots) >= wanted:
                        break
                    if slot not in chosen_slots:
                        chosen_slots.append(slot)
                # Resolved to *cards* before anything leaves (idiom 11): a
                # graveyard holds several copies of a popular card under one
                # name, so a scan by value at payment would take the wrong one.
                return (
                    "graveyard", pile, tuple(chosen_slots),
                    tuple(pile.graveyard[slot] for slot in chosen_slots),
                )
            return None
        candidates = self._exile_cost_candidates(cost, controller_index, permanent)
        if len(candidates) < wanted:
            return None
        named = (
            self.permanent_at(controller, cost_permanent_index)
            if isinstance(cost_permanent_index, int) else None
        )
        if named is None:
            # …or by **id**, the channel every other chosen cost reads. This
            # block read the slot alone, so "exile a creature you control"
            # (City of Shadows, Food Chain) named by id was not read at all and
            # the first creature on the battlefield went instead.
            named = next(
                (
                    found for found in (
                        self.permanent_by_id(permanent_id)
                        for permanent_id in (cost_permanent_ids or [])
                        if permanent_id is not None
                    )
                    if found is not None
                    and any(found is option for option in candidates)
                ),
                None,
            )
        victim = (
            named if any(named is option for option in candidates) else candidates[0]
        )
        # A counted battlefield exile would take *wanted* of them; no card in
        # the pool prints one, so the picks after the first follow the same
        # deterministic order the branch above uses.
        picked = [victim]
        for option in candidates:
            if len(picked) >= wanted:
                break
            if not any(option is already for already in picked):
                picked.append(option)
        return ("battlefield", None, (), tuple(picked))

    def _exile_cost_candidates(self, cost, controller_index: int, permanent) -> list:
        """The permanents an "Exile <noun phrase> you control" cost may eat:
        what the payer controls that answers the printed phrase. One list for
        the chooser above and for ``_named_cost_refusal``."""
        described = cost.exile_filter or {}
        return [
            perm for perm in self.controlled_by(controller_index)
            if subject_matches(
                self, perm, described, observer=controller_index, source=permanent,
            )
        ]

    def _named_exile_slot_refusal(
        self, cost, controller, named_slot, *, named_slots=None
    ) -> str | None:
        """Why the hand or graveyard slot the payer **named** for an exile cost
        cannot pay it, or None (CR 601.2h through CR 602.2b).

        The pile half of :meth:`_named_cost_refusal`, for a cost whose object
        is a card in a zone and so has no id to be named by. Asked only where
        the slot counts into one known pile — the payer's hand, or the payer's
        own graveyard. A cost that may be paid out of *any* graveyard
        (``exile_zone_owner``) takes one index and does not say whose pile it
        counts into, so there the chooser's standing order of piles answers,
        as it did.
        """
        # The graveyard's whole-set channel where the payer used it, else the
        # one slot every earlier caller names.
        if named_slots is not None and cost.exile_zone == "graveyard":
            slots = list(named_slots)
        elif isinstance(named_slot, int) and not isinstance(named_slot, bool):
            slots = [named_slot]
        else:
            return None
        if cost.exile_zone == "hand":
            pile, where = controller.hand, "hand position"
        elif (
            cost.exile_zone == "graveyard"
            and getattr(cost, "exile_zone_owner", "you") == "you"
        ):
            pile, where = controller.graveyard, "graveyard position"
        else:
            return None
        described = cost.exile_filter or {}
        for slot in slots:
            if not (
                isinstance(slot, int) and not isinstance(slot, bool)
                and 0 <= slot < len(pile)
                and _card_matches_filter(
                    pile[slot], described, game=self, owner=controller,
                )
            ):
                return f"no card at {where} {slot} that can be exiled for its cost"
        if len(set(slots)) != len(slots):
            # One slot named twice is one card: it does not pay for two.
            return f"{where} {slots} names one card more than once for its cost"
        wanted = getattr(cost, "exile_count", 1)
        if isinstance(wanted, int) and len(slots) > max(1, wanted):
            return (
                f"{len(slots)} cards named for a cost that exiles "
                f"{max(1, wanted)}"
            )
        return None

    def _named_cost_refusal(
        self, permanent, controller, candidates, cost_permanent_ids,
        cost_permanent_index,
    ) -> str | None:
        """Why a permanent the payer **named** to pay a chosen cost cannot pay
        it, or None.

        CR 601.2h, reached through CR 602.2b: "Unpayable costs can't be paid",
        and CR 601.2e sends an activation that cannot be completed as proposed
        back to the moment before it. A payer who names what they will
        sacrifice, tap, return, untap or exile has *announced* that payment
        (CR 601.2b); if the named permanent cannot make it, the activation is
        illegal — it is not a different activation paid with something else.

        Every chosen-cost block in ``_activate_onto_stack`` honoured a named
        permanent "where it is legal" and otherwise fell to its default pick,
        which is right for a seat that named nothing and wrong for one that
        did: Ertai, the Corrupted ("{U}, {T}, Sacrifice a creature or
        enchantment: Counter target spell"), told to sacrifice a Sol Ring,
        sacrificed **Ertai**. One check here, over the union of the candidate
        lists those blocks build, rather than a branch in each of the ten:
        the next cost block gets it by adding its candidates.

        *candidates* empty means the ability has no chosen permanent cost, and
        then a stray cost field names nothing and substitutes nothing. A cost
        the caller did **not** name still takes each block's default — the
        headless convention, which the AI and the test corpus rely on.
        """
        if not candidates:
            return None
        # A permanent on every path but one: an ability activated from a
        # graveyard (Ashen Ghoul) has a card for its source.
        source_name = getattr(getattr(permanent, "card", permanent), "name", "")
        named: list = [
            self.permanent_by_id(permanent_id)
            for permanent_id in (cost_permanent_ids or [])
            if permanent_id is not None
        ]
        if isinstance(cost_permanent_index, int) and not isinstance(
            cost_permanent_index, bool
        ):
            named.append(self.permanent_at(controller, cost_permanent_index))
        for found in named:
            if found is None:
                return (
                    f"{source_name}: the permanent named to pay its "
                    "cost is not on the battlefield"
                )
            if not any(found is option for option in candidates):
                return f"{source_name}: {found.card.name} cannot pay its cost"
        return None

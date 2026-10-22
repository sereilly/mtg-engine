"""The AI's payment: what a cast costs this seat, which of its sources pay it,
and the taps that do.

Three questions, in order:

* **What is owed** (:func:`_cost_for`) — CR 601.2f's increases then
  reductions, through the functions the cast path calls, over the mana cost
  or whatever a permission charges in its place (CR 118.9d); and the largest
  X a board can afford (:func:`_max_affordable_x`).
* **Which sources pay it** (:func:`_plan_land_taps`) — one exact matching of
  pips to units, the engine's own (``mana_payment.plan_payment``, which the
  castable highlight asks too), over what each source's tap makes
  (``ai_mana_sources``), reached for in a fixed order: floating mana, lands,
  non-land sources that only tap, a source sacrificed for mana only to cast
  a spell (:func:`_may_sacrifice_for`), and last a source whose mana costs
  mana (:func:`_plan_through_a_priced_source`). The plan is told what it pays
  for where its caller knows (:func:`_paying_for`) rather than guessing.
* **The taps themselves** (:func:`tap_planned_lands`) — every executor's,
  the simulator's and the web app's AI seat's: each source tapped through the
  engine's own seams, for the colour the plan counted on and by the mana
  ability that makes it (:func:`planned_tap_color`,
  :func:`planned_tap_ability`), with every slot the action names bound to its
  permanent before the first tap and read back after, because a sacrifice
  renumbers the battlefield (CR 400.7).

``web/payment_plan.py`` asks the same planner for a person's auto-tap, so the
taps a click previews are the taps the AI would make.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from itertools import combinations, product
from dataclasses import dataclass, replace

from .ai_weighed_cast import cast_weighed
from .cost_modifiers import (
    CostReduction,
    cost_reduction_for_cast,
    keyword_cost_modifiers,
    reduce_cost,
    spell_cost_tax,
    spell_symbol_tax,
)
from .game import Game
from .mana_payment import (
    COLOR_SYMBOLS,
    PIP_SYMBOLS,
    _match_colored,
    may_pay_pip,
    plan_payment,
)
from .models import CardDefinition, Permanent, PlayerState
from .oracle_types import x_spend_colors_from_text
from .ai_mana_sources import (
    _MANA_SYMBOLS,
    _priced_mana_source,
    _nonland_mana_source,
    _TapOption,
    _land_tap_options,
    _nonland_tap_options,
    _land_symbols,
)


def planned_tap_color(action, position: int) -> str:
    """The colour an executor asks the *position*-th planned land for.

    The plan's own colour where it has one (``land_tap_colors``), and otherwise
    the tap seam's default, which is what every executor sent before the plan
    carried colours — so an action built without them taps exactly as it did.
    """
    colors = getattr(action, "land_tap_colors", ()) or ()
    return colors[position] if position < len(colors) else "G"


def planned_tap_ability(game: Game, land: Permanent, color: str) -> int | None:
    """Which of *land*'s mana abilities makes *color* — an index for
    ``tap_land_for_mana(ability_index=…)`` — or None for the seam's default.

    CR 605: each mana ability is its own ability, and the tap seam runs the
    land's **first** tap-alone one unless told which. For a painland that is
    "{T}: Add {C}", so a plan that counted a Karplusan Forest or an
    Underground River as a coloured mana tapped it for {C} and the spell was
    refused "insufficient mana" — every turn, once the simulator enforced
    costs. None whenever the default already makes the colour (a basic, a
    dual, City of Brass, a land under a swap the seam applies to any ability),
    so every land that tapped correctly taps exactly as it did.
    """
    # The game's own answer (``Game.land_mana_ability_for``): the engine's
    # payer for a cost an effect collects asks the same question, and it is
    # not a policy.
    return game.land_mana_ability_for(land, color)


def tap_planned_lands(game: Game, seat: int, action):
    """Tap the mana sources *action*'s plan names into *seat*'s pool, each for
    the colour the plan counted on and through the mana ability that makes it
    — and return *action* **as it reads once that is done**.

    **The AI's payment**, shared by every executor — the simulator's and the
    web app's AI seat — so the two pay the same way: the policy plans the taps
    (`_plan_land_taps`), this fills the pool, and the cast or activation that
    follows spends it (CR 601.2g-h). Every slot is resolved to its permanent
    before the first tap and tapped **by id**, so a tap that moved anything
    cannot shift a later slot onto a different permanent.

    A **land** goes through the engine's tap seam. A **non-land** source the
    plan counted (`_nonland_mana_source`: Sol Ring, a Mox, Llanowar Elves, and
    Black Lotus) has no seam — CR 605.1a makes its "{T}: Add …" an activated
    ability like any other — so it is activated, which for a mana ability
    resolves inline (CR 605.3b) and leaves the mana in the pool exactly as a
    land's tap does.

    **The returned action is the one to announce.** A `ai_actions.CastAction` and an
    `ai_actions.ActivationAction` name their targets — and an activation its own source —
    by battlefield **slot**, and a source that pays by leaving ("{T}, Sacrifice
    this artifact: Add three mana of any one color") renumbers every slot
    behind it (CR 400.7: what is in slot 4 afterwards is a different object).
    That is why no such source was ever planned: a Giant Growth announced at
    slot 3 and paid for with the Lotus in slot 1 would have landed on whatever
    slid into slot 3. So every slot the action names is bound to its permanent
    before the first tap and read back afterwards (`_bind_action_slots`,
    `_rebound_action`); an executor announces what this returns, never the
    action it handed in. When nothing moved the same object comes back.
    """
    bound = _bind_action_slots(game, seat, action)
    before = _battlefield_order(game)
    planned = [game.permanent_at(seat, index) for index in action.land_tap_indices]
    for position, land in enumerate(planned):
        permanent_id = game.permanent_id_of(land)
        if permanent_id is None:
            continue
        color = planned_tap_color(action, position)
        source = _nonland_mana_source(game, seat, land, may_sacrifice=True)
        if source is not None:
            slot = game.battlefield_index_of(land)
            if slot is None:
                continue
            game.activate_permanent_ability(
                seat, land.card.name,
                permanent_index=slot,
                ability_index=source.ability_index,
                # "Any color" is one of the five (CR 105.1): a source asked for
                # the {C} a generic cost was planned at names no colour, and
                # the ability's own default answers.
                mana_color=color if color in ("W", "U", "B", "R", "G") else None,
            )
            continue
        # A source whose mana ability costs mana ("{1}, {T}: Add {U}{B}.", the
        # Odyssey filter lands; Mana Cylix). The plan put the tap that pays
        # for it immediately in front of it (`_plan_through_a_priced_source`),
        # so the pool holds its price now; activated like the non-land source
        # above, and for the same reason — the tap seam runs only an ability
        # whose whole cost is {T}.
        priced = _priced_mana_source(game, seat, land)
        if priced is not None:
            slot = next(
                (
                    index for index, permanent in enumerate(game.controlled_by(seat))
                    if permanent is land
                ),
                None,
            )
            if slot is None:
                continue
            game.activate_permanent_ability(
                seat, land.card.name,
                permanent_index=slot,
                ability_index=priced.ability_index,
                mana_color=color if color in ("W", "U", "B", "R", "G") else None,
            )
            continue
        game.tap_land_for_mana(
            seat, land.card.name,
            chosen_color=color,
            permanent_id=permanent_id,
            ability_index=planned_tap_ability(game, land, color),
        )
    if _battlefield_order(game) == before:
        return action
    return _rebound_action(game, action, bound)


def _battlefield_order(game: Game) -> list[list[int]]:
    """Which object is in which slot, per seat — by identity, so a look-alike
    that slid into a vacated slot reads as the change it is."""
    return [
        [id(permanent) for permanent in game.controlled_by(seat)]
        for seat in range(len(game.players))
    ]


def _bind_action_slots(game: Game, seat: int, action) -> dict:
    """Every battlefield slot *action* names, as the permanent that is in it
    now — the half of `tap_planned_lands`' re-binding taken before a payment.

    One reader for the three places an action keeps a slot: a cast's or an
    activation's ``target_permanent_index`` (one slot or several, counted into
    ``target_player_index``'s battlefield), a divided announcement's
    ``(seat, slot[, share])`` entries, a several-mode cast's per-mode slot —
    and an activation's own ``permanent_index``, counted into
    ``source_controller_index``'s battlefield when it names one. A field the
    action does not have is simply not bound, so the three action shapes need
    no arm each.
    """
    bound: dict = {}
    target_seat = getattr(action, "target_player_index", None)
    slots = getattr(action, "target_permanent_index", None)
    if isinstance(slots, int):
        bound["target"] = game.permanent_at(target_seat, slots)
    elif slots:
        bound["targets"] = [game.permanent_at(target_seat, slot) for slot in slots]
    divided = getattr(action, "divided_targets", None)
    if divided:
        bound["divided"] = [
            game.permanent_at(entry[0], entry[1]) if entry[1] is not None else None
            for entry in divided
        ]
    modes = getattr(action, "mode_choices", None)
    if modes:
        bound["modes"] = [
            game.permanent_at(
                choice.get("target_player_index"), choice.get("target_permanent_index")
            )
            if choice.get("target_permanent_index") is not None else None
            for choice in modes
        ]
    if getattr(action, "permanent_index", None) is not None:
        source_seat = getattr(action, "source_controller_index", None)
        bound["source"] = game.permanent_at(
            seat if source_seat is None else source_seat, action.permanent_index
        )
    return bound


def _rebound_action(game: Game, action, bound: dict):
    """*action* with every slot `_bind_action_slots` took read back off the
    battlefield as it stands now.

    A permanent that has left has no slot: a single target reads None (the
    announcement names no object and the engine's own gate answers), and it is
    dropped from a list. The plan never spends a permanent the action names
    (`ai_policy.choose_cast_action`), so that is the engine's answer to a board something
    else moved rather than a path this policy takes.
    """
    changes: dict = {}
    if "target" in bound:
        changes["target_permanent_index"] = game.battlefield_index_of(bound["target"])
    if "targets" in bound:
        changes["target_permanent_index"] = [
            slot for slot in (
                game.battlefield_index_of(permanent) for permanent in bound["targets"]
            )
            if slot is not None
        ]
    if "divided" in bound:
        changes["divided_targets"] = [
            entry if permanent is None
            else (entry[0], game.battlefield_index_of(permanent), *entry[2:])
            for entry, permanent in zip(action.divided_targets, bound["divided"])
        ]
    if "modes" in bound:
        changes["mode_choices"] = [
            choice if permanent is None
            else {**choice, "target_permanent_index": game.battlefield_index_of(permanent)}
            for choice, permanent in zip(action.mode_choices, bound["modes"])
        ]
    if "source" in bound:
        slot = game.battlefield_index_of(bound["source"])
        if slot is not None:
            changes["permanent_index"] = slot
    return replace(action, **changes) if changes else action


@dataclass(frozen=True)
class _PaymentContext:
    """What the payment plan being drawn up is **for**, where its caller knows.

    A context variable rather than a parameter, for `ai_actions._OFFERS_ANNOUNCED`'s
    reason: `_plan_land_taps` is reached through the cast candidates'
    builders, which take a card and a board and know nothing of where the card
    is or what its cast will be charged. Set around the one call that builds a
    candidate (`ai_policy.choose_cast_action`); None is every other plan — an ability's
    cost, a toll, an instant in combat — and reads exactly as plans always
    did.
    """

    #: The spell being cast. What a "spend this mana only to cast …" land's
    #: mana may pay for (CR 106.6), and what a permanent given up for mana is
    #: weighed against (`_may_sacrifice_for`). What the cast is *charged* is
    #: not here: a waiver or a flashback cost is the permission's
    #: (`ai_weighed_cast.casting_under`), read by `_cost_for`.
    spell: "CardDefinition | None" = None


_PAYING_FOR: ContextVar["_PaymentContext | None"] = ContextVar(
    "ai_paying_for", default=None
)


@contextmanager
def _paying_for(spell: "CardDefinition | None"):
    """Run a block in which every plan drawn up is the payment for *spell*."""
    token = _PAYING_FOR.set(_PaymentContext(spell=spell))
    try:
        yield
    finally:
        _PAYING_FOR.reset(token)


def _may_sacrifice_for(spell: "CardDefinition | None", permanent: Permanent) -> bool:
    """Whether a plan paying for *spell* may count mana *permanent* makes by
    being sacrificed.

    **What the AI will give up for mana, stated once.** Only to cast a spell —
    never to activate an ability, pay a toll or keep a permanent, where the
    plan is told of no spell and this answers no. And only for a spell **worth
    more than the permanent, measured in mana value** (CR 202.3): Black Lotus
    and Lotus Petal (0) for anything that costs; Blood Pet and Tinder Wall (1)
    for a two-drop or better; Basal Thrull (2) for a three-drop; never a
    creature for a spell no bigger than itself. Which *kinds* of source are
    asked at all is `_nonland_mana_source`'s half (itself, and nothing with a
    free mana ability); that they are reached for last, and as few as pay, is
    `_plan_land_taps`'.
    """
    if spell is None or spell.primary_type == "land":
        return False
    return float(permanent.effective_card.cmc or 0) < float(spell.cmc or 0)


def _cost_for(
    game: Game,
    player: PlayerState,
    card: CardDefinition,
    x_value: int | None,
    extra_generic: int = 0,
) -> dict[str, int]:
    """What *player* actually pays for *card* — CR 601.2f, increases then
    reductions, through the same three functions the cast path calls.

    *extra_generic* is a generic surcharge the cast will carry that no
    registered modifier states — today the commander tax (CR 903.8), which the
    cast path adds to its own ``extra_generic_tax`` the same way. Zero for
    every hand cast.

    The seat is threaded rather than assumed. This used to pass 0 with a comment
    saying no registered modifier depended on it, which was true while every one
    of them was scoped by the *card's* colour; it stopped being true the moment
    a card printed "spells **you cast** cost {1} less", and a claim about the
    pool expires without anyone editing the comment. Identity, not
    ``players.index``: PlayerState is value-compared.

    **What is charged in the mana cost's place** is the permission's, when
    the cast being weighed is made under one (`_charged_in_place_of_mana_cost`):
    a flashback cost (CR 702.34a), or nothing for a waiver. CR 118.9d then
    applies the same increases and reductions to *that* total — "start with
    the mana cost or alternative cost you're paying, add any cost increases,
    then apply any cost reductions" — which is the order below and the one
    ``_cast_onto_stack`` pays in.
    """
    seat = next((i for i, seated in enumerate(game.players) if seated is player), 0)
    mana_cost, keyword = _charged_in_place_of_mana_cost(card)
    tax, _names = spell_cost_tax(game, seat, card)
    tax += max(0, extra_generic)
    # The coloured half of the same taxes (Derelor). Asked here too, because the
    # AI prices a spell to decide whether it can cast it — priced without the
    # pip it proposes a cast the rules then refuse, every turn, forever.
    pips, _pip_names = spell_symbol_tax(game, seat, card)
    reduction, _reducers = cost_reduction_for_cast(game, seat, card)
    # "Flashback costs you pay cost {2} less." (Catalyst Stone.) CR 601.2f
    # over the keyword's cost, through the reader the cast path charges with;
    # nothing for a cost that is the price of no keyword.
    more, less, _by = keyword_cost_modifiers(game, seat, keyword)
    if more or less:
        tax += more
        reduction = CostReduction(reduction.generic + less, reduction.colored)
    # The best split of X among the colours the card allows, which is the one
    # the cast path will try first (`casting._x_color_allocations`). The AI is
    # sizing the cost, so it wants the payment that will actually be attempted;
    # a split the cast would not choose prices a different spell.
    allocation = game._x_color_allocations(
        x_spend_colors_from_text(card.oracle_text), max(0, x_value or 0)
    )[0]
    return reduce_cost(
        game._parse_mana_cost(
            mana_cost,
            x_value=x_value,
            extra_generic=tax,
            x_allocation=allocation,
            extra_pips=pips,
        ),
        reduction,
    )


def _charged_in_place_of_mana_cost(card: CardDefinition) -> "tuple[str, str | None]":
    """``(mana symbols, keyword)`` — the run of mana a cast of *card* is
    charged where its mana cost would be, and the keyword that run is the
    price of.

    The card's own mana cost and no keyword for every ordinary cast. Under the
    permission being weighed (`ai_weighed_cast.cast_weighed`), what the cast path
    charges for it: the **required alternative cost's** mana (CR 118.9b;
    ``CastPermission.cost`` — "Flashback {4}{R}"), which may be none where that
    cost is paid in something else; or **nothing** under a waiver ("without
    paying its mana cost", CR 118.9). A permission that names no price — a
    card played out of exile, a graveyard under Yawgmoth's Will — charges the
    mana cost like any cast.

    Read off the permission, never recomputed: the price of a flashback is
    whatever `flashback_permission` / `granted_cost` built, so a flashback
    cost "equal to its mana cost" (Recoup) and a printed one are one reading.
    """
    under = cast_weighed(card)
    if under is None:
        return card.mana_cost, None
    if under.cost is not None:
        return under.cost.mana or "", under.cost.keyword
    if under.waives_mana_cost:
        return "", None
    return card.mana_cost, None


def _max_affordable_x(
    game: Game, player: PlayerState, card: CardDefinition, extra_generic: int = 0
) -> int:
    # Through the tap planner rather than a summed preview pool: the preview
    # counted each land as one fixed symbol, so a dual or a swapped land could
    # only ever pay for the first colour it listed, and the X it sized was the
    # X a board of single-colour lands would afford.
    # One reading of the board for all sixteen sizes: what the sources make
    # does not depend on the X being priced.
    planner = _PaymentPlanner(game, player)
    for x_value in range(15, -1, -1):
        required = _cost_for(game, player, card, x_value, extra_generic=extra_generic)
        if planner.plan(required) is not None:
            return x_value
    return 0


@dataclass(frozen=True)
class _ManaSource:
    """One permanent a payment plan may tap, with every way its tap comes out."""

    #: Its battlefield slot — what a plan names it by.
    slot: int
    options: "tuple[_TapOption, ...]"
    #: Reached for in this order: 0 a land, 1 a non-land source that only
    #: taps, 2 a source that is sacrificed.
    rank: int
    #: The symbol it makes unasked — what a generic pip is paid with.
    default: str


#: The most ways of tapping the sources that are tried one by one. Past it
#: each source is read as its largest outcome alone (`board_payment` keeps the
#: same bound for the same reason).
_MAX_TAP_COMBINATIONS = 3125

#: The most sacrificed sources one plan may count.
_MAX_SACRIFICED_FOR_MANA = 3

#: A mark every unit carries so the matching counts it toward a generic cost
#: (`mana_payment.plan_payment` spends on generic only a source that makes
#: something). No pip is spelled this way.
_ANY_PIP = "*"


def _unit_pays(player: PlayerState, symbols, reading: str | None = None) -> frozenset[str]:
    """The pips one mana that may be any of *symbols* can pay for *player*.

    CR 609.4's spending permissions, asked per unit the way
    `board_payment.board_can_pay` asks them of the same matching: Chromatic
    Orrery's "as though it were mana of any color" (every unit pays a coloured
    pip, and {C} still wants colourless), a CR 106.6 permission
    (`mana_payment.may_pay_pip` — Celestial Dawn), Sunglasses of Urza's
    white-as-red. *reading* is a one-spell grant being tried (North Star):
    "any_type" or "any_color".
    """
    if reading == "any_type":
        return frozenset(PIP_SYMBOLS) | {"C", _ANY_PIP}
    pays: set[str] = {_ANY_PIP}
    if "C" in symbols:
        pays.add("C")
    if reading == "any_color" or player.spends_mana_as_any_color:
        return frozenset(pays | set(PIP_SYMBOLS))
    if player.mana_spending_is_general:
        permissions = player.mana_spending_permissions
        pays.update(
            pip for pip in PIP_SYMBOLS
            if any(may_pay_pip(permissions, symbol, pip) for symbol in symbols)
        )
        return frozenset(pays)
    pays.update(symbol for symbol in symbols if symbol in PIP_SYMBOLS)
    if player.can_spend_white_as_red and "W" in symbols:
        pays.add("R")
    return frozenset(pays)


class _PaymentPlanner:
    """`_plan_land_taps` with the board read once.

    What the sources make does not depend on the cost being asked about, and
    a caller sizing an X asks sixteen costs of one board (`_max_affordable_x`).
    """

    def __init__(
        self, game: Game, player: PlayerState, *,
        paying_for: "Permanent | None" = None,
        without: "frozenset[int]" = frozenset(),
    ):
        from .restricted_mana import ACTIVATE, CAST, PaymentPurpose, spendable_restricted_mana

        self.game = game
        self.player = player
        context = _PAYING_FOR.get()
        self.spell = context.spell if context is not None else None
        # What the payment is for decides what restricted mana counts toward
        # it (CR 106.6) — Mishra's Workshop's {C}{C}{C} for an artifact spell
        # and for nothing else. With no purpose none of it counts, which is
        # what this planner assumed of all of it.
        if self.spell is not None:
            purpose = PaymentPurpose(CAST, card=self.spell)
        elif paying_for is not None:
            purpose = PaymentPurpose(ACTIVATE, source=paying_for)
        else:
            purpose = None
        self.purpose = purpose
        held = {symbol: int(player.mana_pool.get(symbol, 0) or 0) for symbol in _MANA_SYMBOLS}
        for symbol, amount in spendable_restricted_mana(player, purpose).items():
            held[symbol] = held.get(symbol, 0) + int(amount)
        #: Mana already floating, one unit each. Spent first: it is there.
        self.floating = [
            frozenset({symbol})
            for symbol in _MANA_SYMBOLS for _ in range(max(0, held.get(symbol, 0)))
        ]
        self.seat = next(
            (i for i, seated in enumerate(game.players) if seated is player), None
        )
        self.sources: list[_ManaSource] = []
        #: Sources that pay by being sacrificed, in board order — counted only
        #: when everything above cannot pay (`plan`).
        self.sacrificed: list[_ManaSource] = []
        if self.seat is None:
            return
        # Only a land the tap seam will make mana from, and only what it will
        # make (`land_tap_yields` asks `land_mana_tap_refusal`, the seam's own
        # gate): an untapped land is not a mana. A storage land with no
        # counter, a Bazaar of Baghdad or a summoning-sick land creature
        # counted as one here, the executor's tap of it made nothing, and the
        # cast it was planned for was refused "insufficient mana" — the same
        # spell every turn, once the simulator enforced costs (5ED: Sand
        # Silos, 14 refusals a run).
        #
        # **Rhystic Cave is the land that must never be here**: "Activate only
        # as an instant" means its mana needs priority (CR 304.5), which
        # nobody has while a cost is being paid, and any player may deny it.
        # The seam's gate reads `_land_mana_abilities`, whose answer for the
        # Cave is "cannot be run inside a payment" — the same reading
        # `mana_payment.taps_for_payment` gives the optional-pay planner.
        #
        # Then the non-land sources (`_nonland_mana_source`: the Moxen, Sol
        # Ring, Llanowar Elves), ranked after every land because a land is the
        # source that costs nothing to tap: a Mana Vault stays tapped, an
        # Elves of Deep Shadow deals its controller a damage, and a creature
        # tapped for mana does not attack.
        #
        # Never the permanent whose own ability is being paid for
        # (*paying_for*): its {T} may be that ability's cost, and one tap
        # cannot pay both. *without* is the slots a caller has already spoken
        # for — the two halves of `_plan_through_a_priced_source` plan against
        # disjoint sources.
        for slot, permanent in enumerate(game.controlled_by(player)):
            if permanent is paying_for or slot in without:
                continue
            if permanent.has_type("land"):
                if permanent.tapped:
                    continue
                options = _land_tap_options(game, permanent, purpose)
                if options:
                    self.sources.append(_ManaSource(
                        slot, options, 0, _land_symbols(game, permanent)[0],
                    ))
                continue
            source = _nonland_mana_source(game, self.seat, permanent, may_sacrifice=True)
            if source is None:
                continue
            entry = _ManaSource(
                slot, _nonland_tap_options(source), 2 if source.sacrifices else 1,
                source.symbols[0],
            )
            if not source.sacrifices:
                self.sources.append(entry)
            elif _may_sacrifice_for(self.spell, permanent):
                self.sacrificed.append(entry)
        # The order the matching reaches for them in: lands before non-lands,
        # and within each the source with the fewest colours to offer first —
        # a Forest pays the {G} and the Taiga beside it is still there for
        # either colour the next spell wants. Board order breaks ties, so a
        # board of basics is planned as it always was.
        self.sources.sort(key=lambda source: (source.rank, self._breadth(source), source.slot))

    def _breadth(self, source: _ManaSource) -> int:
        offered = frozenset().union(*(unit for option in source.options for unit in option.units))
        return len(_unit_pays(self.player, offered) & set(PIP_SYMBOLS))

    def _readings(self) -> "list[str | None]":
        """CR 609.4's one-spell grants (North Star), tried only where the
        ordinary reading cannot pay — the order the payment spends them in."""
        from .restricted_mana import CAST

        readings: "list[str | None]" = [None]
        if self.purpose is not None and self.purpose.kind == CAST:
            for grant in self.player.spend_mana_as_though_grants:
                if int(grant.get("spells", 0)) > 0:
                    readings.append("any_type" if grant.get("any_type") else "any_color")
                    break
        return readings

    def plan(self, required: dict[str, int]) -> "tuple[tuple[int, ...], tuple[str, ...]] | None":
        """``(slots, colours)`` in tap order, or None — see `_plan_land_taps`."""
        found = self._plan_with(self.sources, required)
        if found is not None or not self.sacrificed:
            return found
        # **A permanent given up for mana is the last thing reached for**, and
        # as few of them as pay: every plan the lands and the tap-only sources
        # can make has been tried and refused before the first is counted.
        extras = self.sacrificed[:_MAX_SACRIFICED_FOR_MANA]
        for count in range(1, len(extras) + 1):
            for chosen in combinations(extras, count):
                found = self._plan_with([*self.sources, *chosen], required)
                if found is not None:
                    return found
        return None

    def _plan_with(self, sources, required):
        owed = sum(max(0, int(required.get(key, 0) or 0)) for key in (*_MANA_SYMBOLS, "generic"))
        most = len(self.floating) + sum(
            max(len(option.units) for option in source.options) for source in sources
        )
        if most < owed:
            return None
        choices = [source.options for source in sources]
        ways = 1
        for options in choices:
            ways *= len(options)
        if ways > _MAX_TAP_COMBINATIONS:
            choices = [(max(options, key=lambda option: len(option.units)),) for options in choices]
        for reading in self._readings():
            for picked in product(*choices):
                found = self._match(sources, picked, required, reading)
                if found is not None:
                    return found
        return None

    def _match(self, sources, picked, required, reading):
        """The exact matching (`mana_payment.plan_payment`, the one the
        optional-pay planner and the castable highlight ask) over the floating
        mana and every unit *picked* would add; then which sources it used and
        the colour to ask each for."""
        units: list[frozenset[str]] = list(self.floating)
        owner: "list[int | None]" = [None] * len(units)
        for position, option in enumerate(picked):
            for unit in option.units:
                units.append(unit)
                owner.append(position)
        pays = [_unit_pays(self.player, unit, reading) for unit in units]
        payment = plan_payment({}, range(len(units)), required, produces=pays.__getitem__)
        if payment is None:
            return None
        used = sorted(payment.tapped)
        # Which pip each used unit pays. `plan_payment` says which units and
        # not which pip, and the colour to ask a land for is the pip: the
        # matching again, over the units it chose.
        pips = [
            symbol for symbol in COLOR_SYMBOLS
            for _ in range(max(0, int(required.get(symbol, 0) or 0)))
        ]
        assigned = _match_colored(pips, [(index, pays[index]) for index in used]) if pips else {}
        if assigned is None:
            return None
        tapped: dict[int, list] = {}
        for index in used:
            if owner[index] is not None:
                tapped.setdefault(owner[index], [])
        if not tapped:
            return (), ()
        for position in tapped:
            first = owner.index(position)
            tapped[position] = [
                assigned.get(first + offset) for offset in range(len(picked[position].units))
            ]
        # Tap order: the sources paying a coloured pip first, in pip order,
        # then the ones paying generic — the order this plan has always been
        # reported in.
        def pip_rank(position: int) -> int:
            ranks = [COLOR_SYMBOLS.index(pip) for pip in tapped[position] if pip is not None]
            return min(ranks) if ranks else len(COLOR_SYMBOLS)

        order = sorted(tapped, key=lambda position: (pip_rank(position), position))
        return (
            tuple(sources[position].slot for position in order),
            tuple(
                _asked_color(self.player, sources[position], picked[position], tapped[position], reading)
                for position in order
            ),
        )


def _asked_color(
    player: PlayerState, source: _ManaSource, option: _TapOption, unit_pips, reading,
) -> str:
    """The colour an executor asks *source* for, to get *option* with the mana
    the matching assigned (*unit_pips*, one entry per unit; None is a unit
    spent on generic or not spent).

    The option's own colour where it fixes one. Otherwise the first unit that
    offers a choice decides: the symbol **it** can be that pays the pip it was
    given — under Sunglasses of Urza a Plains pays {R} and is still asked for
    {W} — and for a unit spent on generic, what the source makes unasked (a
    painland's painless {C}).
    """
    if option.ask is not None:
        return option.ask
    for unit, pip in zip(option.units, unit_pips):
        if len(unit) <= 1:
            continue
        if pip is not None:
            for symbol in _MANA_SYMBOLS:
                if symbol in unit and pip in _unit_pays(player, frozenset({symbol}), reading):
                    return symbol
        if source.default in unit:
            return source.default
        return next(symbol for symbol in _MANA_SYMBOLS if symbol in unit)
    return next(iter(option.units[0]))


def _plan_land_taps(
    game: Game, player: PlayerState, required: dict[str, int],
    *, paying_for: "Permanent | None" = None,
    without: "frozenset[int]" = frozenset(),
    through_priced: bool = True,
) -> tuple[tuple[int, ...], tuple[str, ...]] | None:
    """Which untapped mana sources to tap for *required*, and **which colour
    to ask each one for**: ``(slots, colours)`` in tap order, or None when the
    board cannot pay.

    **An exact matching, and the engine's own** — `mana_payment.plan_payment`,
    the augmenting-path assignment of pips to sources the optional-pay planner
    was written around and the castable highlight asks
    (`board_payment.board_can_pay`). This was a greedy pass: each coloured pip
    took the first land that could make it and never gave it back, so a
    Reflecting Pool spent on the {B} left a Swamp and a Forest unable to find
    the second {G} of a {B}{G}{G} spell they could pay between them — a card
    held and never cast, where the highlight over the same board glowed. One
    matching now answers "can this be paid" for the engine, the highlight and
    this policy, over one reading of what a land's tap makes
    (`_land_tap_options`).

    What a land can make is the engine's answer, not the printed summary's
    first symbol, which is what this once read. That one symbol was wrong
    three ways, measured at NEM: under a seat-wide swap (Deep Water, Harvest
    Mage) a Forest makes {U} or a colour of the tapper's choice; a land
    carrying a granted ability (Overlaid Terrain's "{T}: Add two mana of any
    one color") was still the colour it was printed; and a dual land could
    only ever pay its first colour.

    The colour travels with the plan because the tap seam asks for one
    (``tap_land_for_mana``'s ``chosen_color``) and the executors sent the
    default "G" for every land — so a Taiga the plan counted as {R} made {G}.

    Sources are reached for in a fixed order (`_PaymentPlanner`): floating
    mana, lands, non-land sources that only tap, and — only for a spell, only
    where those cannot pay and only under `_may_sacrifice_for` — a source that
    is sacrificed. And when even those cannot pay, **a source whose mana costs
    mana** (a filter land, Mana Cylix: `_plan_through_a_priced_source`), with
    the taps that pay its price in front of it.
    """
    found = _PaymentPlanner(
        game, player, paying_for=paying_for, without=without,
    ).plan(required)
    if found is None and through_priced and not without:
        return _plan_through_a_priced_source(game, player, required, paying_for)
    return found


def _plan_through_a_priced_source(
    game: Game, player: PlayerState, required: dict[str, int],
    paying_for: "Permanent | None",
) -> "tuple[tuple[int, ...], tuple[str, ...]] | None":
    """`_plan_land_taps` for a cost the free sources cannot pay, through **one**
    source whose mana costs mana (`_priced_mana_source`: "{1}, {T}: Add
    {U}{B}.") — or None.

    Three parts, in the order they are tapped:

    1. the free sources that pay the source's **price**;
    2. the source itself;
    3. the free sources that pay what is left of *required* once the source's
       output is counted — its symbols against the pips they match, any
       surplus against the generic part.

    **The order is the plan.** The executor taps a plan's slots in sequence
    (`tap_planned_lands`), so with the price tapped immediately in front of
    the source, the pool holds exactly that price when the source is activated
    and there is no choice of which unit pays it. Tapped all together first,
    the engine could pay the {1} with the one green mana the spell's {G} was
    counting on. For the same reason this plans nothing while mana is already
    floating: which floating unit a generic price would take is not this
    planner's to say.

    One priced source per plan. Two filter lands feeding one another is a
    longer chain than this walks.
    """
    if any(int(player.mana_pool.get(symbol, 0) or 0) for symbol in _MANA_SYMBOLS):
        return None
    seat = next((i for i, seated in enumerate(game.players) if seated is player), None)
    if seat is None:
        return None
    for index, permanent in enumerate(game.controlled_by(player)):
        if permanent is paying_for:
            continue
        source = _priced_mana_source(game, seat, permanent)
        if source is None:
            continue
        for asked, made in source.outputs():
            rest = _plan_land_taps(
                game, player, _less_mana(required, made), paying_for=paying_for,
                without=frozenset({index}), through_priced=False,
            )
            if rest is None:
                continue
            price = _plan_land_taps(
                game, player, {"generic": source.price}, paying_for=paying_for,
                without=frozenset({index, *rest[0]}), through_priced=False,
            )
            if price is None:
                continue
            return (
                (*price[0], index, *rest[0]),
                (*price[1], asked, *rest[1]),
            )
    return None


def _less_mana(required: dict[str, int], made: dict[str, int]) -> dict[str, int]:
    """*required* with the mana *made* already in the pool: each symbol against
    the pips it matches, and whatever is left over against the generic part.

    A copy in *required*'s own key order — the planner walks the dict it is
    handed, and a simulated game has to reproduce from its seed.
    """
    left = {symbol: int(amount or 0) for symbol, amount in required.items()}
    spare = 0
    for symbol, count in made.items():
        used = min(int(count), left.get(symbol, 0))
        if used:
            left[symbol] -= used
        spare += int(count) - used
    if spare and left.get("generic", 0):
        left["generic"] = max(0, left["generic"] - spare)
    return left


def _can_pay_cost(
    pool: dict[str, int], required: dict[str, int], payer: PlayerState
) -> bool:
    """Whether *payer* could pay *required* out of *pool*.

    *pool* is a **preview** — the seat's floating mana plus whatever its
    untapped lands would make — so it is passed rather than read off the payer;
    the payer is here for the CR 609.4 spending permissions, which are facts
    about the seat rather than about the pool.

    Both permissions, from one argument. This took ``can_spend_white_as_red``
    as a bare bool, so the wider one beside it (Chromatic Orrery's "you may
    spend mana as though it were mana of any color") was simply not asked, and
    a seat with a colourless pool judged every coloured spell in its hand
    uncastable. Nothing breaks visibly when an AI under-reports what it can pay
    — it just never casts, which is the "a seat doing nothing all game" shape
    ``simulate_ai_games.py`` counts as a refused cast.
    """
    can_spend_white_as_red = payer.can_spend_white_as_red
    if payer.spends_mana_as_any_color:
        # Every unit pays a coloured pip and a {C} still wants colourless —
        # through the engine's own arithmetic, so the AI's answer and the
        # payment's cannot drift.
        from .mana_payment import fungible_colors_headroom

        return fungible_colors_headroom(pool, required) is not None
    if pool.get("W", 0) < required.get("W", 0):
        return False
    if pool.get("U", 0) < required.get("U", 0):
        return False
    if pool.get("B", 0) < required.get("B", 0):
        return False
    if pool.get("G", 0) < required.get("G", 0):
        return False
    if pool.get("C", 0) < required.get("C", 0):
        return False

    available_red = pool.get("R", 0)
    if can_spend_white_as_red:
        available_red += pool.get("W", 0)
    if available_red < required.get("R", 0):
        return False

    temp = {symbol: pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    temp["W"] -= required.get("W", 0)
    temp["U"] -= required.get("U", 0)
    temp["B"] -= required.get("B", 0)
    temp["G"] -= required.get("G", 0)
    temp["C"] -= required.get("C", 0)

    red_to_pay = required.get("R", 0)
    from_red = min(temp.get("R", 0), red_to_pay)
    temp["R"] -= from_red
    red_to_pay -= from_red
    if red_to_pay > 0:
        if not can_spend_white_as_red:
            return False
        if temp.get("W", 0) < red_to_pay:
            return False
        temp["W"] -= red_to_pay

    generic = required.get("generic", 0)
    if generic <= 0:
        return True

    available_generic = sum(max(0, temp.get(symbol, 0)) for symbol in ("C", "W", "U", "B", "R", "G"))
    return available_generic >= generic

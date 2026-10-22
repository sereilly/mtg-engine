"""What a choice the rules leave to a player does, read off the compiled
program for the answer a seat nobody asks gives.

A prompt's default (``engine/pending_choices.py``) states a policy — take
gifts, pay tolls, make no trades — and a policy needs to know which offers
are gifts. Each reader here names the cards a default reaches by what their
program does, never by name, for the resolution path that arms the prompt
(``mixins/stack/choices``, ``handlers/zones``, ``handlers/control_flow``, the
cast and activation paths) or the policy's answer to it (``ai_prompts``):

* **an offer's price** — whether taking it spends the taker's own resources
  (:func:`offered_action_is_a_payment`), the trade a "you may A. If you do,
  B." makes (:func:`offer_trade`), whether an alternative of a CR 608.2d
  choice changes nothing, and what each branch of a toll takes
  (:func:`toll_branch_loss`);
* **a colour, a name, a number, a creature type** — the colour an opposing
  object threatens, the colour a sweep is worth naming, where a chosen name
  is looked for, the flip run a chosen number buys, whose creatures a chosen
  type names (:func:`chosen_creature_type_side`);
* **a pile** — whether what a search exiled comes back, all at once or a
  card a turn, and whether a pick is tested for a shared colour;
* **a graveyard card** — the pile an exile denies, the order denial and a
  cost's exile take cards in (:func:`graveyard_denial_order`,
  :func:`graveyard_price_order`), and whether an effect reads which cards its
  cost exiled.

The engine's resolution paths import most of these from ``ai_valuation``,
which binds them for that reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CardDefinition
from .oracle import OracleInstruction, compile_card_oracle
from .ai_weighed_cast import _effect_steps, _walk_program
from .ai_rehearsal import permanent_worth


def _reads_chosen_creature_type(value) -> bool:
    """Whether a payload, at any depth, names "the chosen type" (CR 614.1c's
    entry record), by the ``chosen_creature_type`` key or the token's
    ``from_chosen`` list."""
    if isinstance(value, dict):
        if value.get("chosen_creature_type"):
            return True
        if "creature_type" in tuple(value.get("from_chosen") or ()):
            return True
        return any(_reads_chosen_creature_type(inner) for inner in value.values())
    if isinstance(value, (list, tuple)):
        return any(_reads_chosen_creature_type(inner) for inner in value)
    if isinstance(value, OracleInstruction):
        return _reads_chosen_creature_type(value.payload)
    return False


def chosen_creature_type_side(card: CardDefinition) -> str | None:
    """Whose creatures *card*'s "choose a creature type" should name — "you",
    "opponent", or None when nothing it prints says.

    The entry default read the **opponents'** board for every such card, which
    is right for the ones that hose the type and backwards for the ones that
    feed it. W1G5 watched Belbe's Portal pay {3} every turn to put a creature of
    the opponent's type out of a hand that held none. The answer is in what the
    card does with the word:

    * a P/T change to the type, by its sign ("All creatures of the chosen type
      get -1/-1", Engineered Plague);
    * something put onto the battlefield **for its controller** that the type
      describes — a card from the controller's own hand (Belbe's Portal), a
      token the card creates (Volrath's Laboratory);
    * cards of the type taken out of the controller's **own library** into
      their hand (Brass Herald's reveal) — a type the deck does not hold makes
      that sentence a four-card mill to the bottom;
    * the two derivation tables that read "of the chosen type" on lines the
      compiled program does not carry: an untap lock is a denial (An-Zerrin
      Ruins), a cost reduction a gift (Urza's Incubator) and a cost increase a
      tax.

    Readings that disagree, or none at all (Conspiracy, whose type is about the
    controller's creatures *becoming* it), are None and keep the standing
    default.
    """
    from .cost_modifiers import cost_modifiers_for
    from .untap_restrictions import untap_restriction_for

    sides: set[str] = set()
    for instruction in _walk_program(compile_card_oracle(card)):
        payload = instruction.payload or {}
        if not _reads_chosen_creature_type(payload):
            continue
        if instruction.kind == "lord_buff":
            total = sum(
                value for value in (payload.get("power"), payload.get("toughness"))
                if isinstance(value, int) and not isinstance(value, bool)
            )
            if total:
                sides.add("you" if total > 0 else "opponent")
        elif instruction.kind == "create_token":
            sides.add("you")
        elif instruction.kind == "put_chosen_card_from_hand_onto_battlefield" and (
            payload.get("whose") in (None, "you")
        ):
            sides.add("you")
        elif instruction.kind == "reveal_top_sorting_by_filter" and (
            # The caster's own pile only: "each player reveals …" hands every
            # seat its cards of the type, which says nothing about whose to
            # name.
            payload.get("whose") is None
        ):
            sides.add("you")
    text = card.oracle_text or ""
    restriction = untap_restriction_for(text)
    if restriction is not None and _reads_chosen_creature_type(
        getattr(restriction, "blocked", None)
    ):
        sides.add("opponent")
    for modifier in cost_modifiers_for(text):
        if modifier.chosen_creature_type:
            sides.add("you" if modifier.reduces else "opponent")
    return next(iter(sides)) if len(sides) == 1 else None


#: Instruction kinds whose whole effect is that the player performing them
#: **pays** — CR 118.3's list of what a cost can be, restricted to the ones the
#: rules define as done to oneself, which is why no payload has to be consulted
#: to know whose resources are spent:
#:
#: * CR 701.21a — "A player can't sacrifice ... something that's a permanent
#:   they don't control": a sacrifice is always of your own permanent;
#: * CR 701.9a — a discard moves a card "from its **owner's** hand";
#: * CR 118.3b — life is subtracted from the paying player's own life total;
#: * CR 407.4 — "the owner of an object is the only player who can ante that
#:   object", and CR 407.2 hands the ante zone to the winner, so it is the one
#:   price on this list a player does not get back at end of game;
#: * CR 701.13a — an exile, here out of the offered seat's own hand or off its
#:   own battlefield, which is what the two kinds below name.
#:
#: A kind, never a card: "you may sacrifice a creature" is one price whoever
#: prints it, so the eight cards in the pool that print it and every card still
#: to come are classified by construction. Held to live handler kinds by
#: ``tests/engine/test_optional_offer_defaults.py``, which is the guard
#: ``ai_valuation.MANA_ABILITY_KINDS`` above wants for the same reason: a rename that
#: emptied this set would silently restore the always-accept default.
SELF_PAYMENT_KINDS = frozenset({
    "sacrifice_matching_permanent",
    "sacrifice_self",
    "sacrifice_attached_permanent",
    "discard_controller_cards",
    "pay_life",
    "ante_top_card",
    "exile_chosen_card_from_hand",
    # "You may **exile all cards from your hand** face down." (Duplicity.) The
    # pile spelling of the row above, and a price for exactly its reason: the
    # cards come out of the offered seat's own hand. Without it the offer read
    # as free — the cost is lowered *into* the offered action, where the
    # affordability test cannot find it — and a headless seat would exile its
    # whole hand every upkeep, which is the failure this set is written to
    # catch.
    "exile_hand_pile",
    "exile_any_number_of_own_tokens",
})


def payload_reference(step) -> str:
    """The printed player reference a step aimed at a *named* seat names.

    ``who`` where the lowering wrote one ("defending player discards three
    cards", Mindstab Thrull) and "target" where it did not — an absent key is
    the handler reading ``context.target``, which is the seat the sentence
    chose. One reader, because the answer decides whether a step is a price and
    a second spelling would price the same sentence two ways.
    """
    return str((getattr(step, "payload", None) or {}).get("who") or "target")


def _step_is_a_payment(step, self_recipients: frozenset[str]) -> bool:
    kind = getattr(step, "kind", None)
    if kind in SELF_PAYMENT_KINDS:
        return True
    if kind == "deal_damage":
        # "…**or have this enchantment deal 5 damage to that player**" (Worms
        # of the Earth). Damage is a price only when the player taking the
        # offer is the one dealt it, which the payload cannot say on its own —
        # the recipient is a printed reference ("caster", "target_player") that
        # the resolution binds. So the caller resolves those references to
        # seats and passes in the ones that name the offered seat; Goblin
        # Arsonist's "you may have it deal 1 damage to any target" names no
        # player recipient at all and is a gift.
        return step.payload.get("recipient") in self_recipients
    if kind == "discard_target_cards":
        # "…unless that player **discards a card**" (Forbidden Ritual). A
        # discard out of the offered seat's own hand is a price, and this kind
        # is how the grammar lowers one aimed at a *named* seat —
        # ``discard_controller_cards`` in the set above is the same deed
        # aimed at "you". Which seat it is cannot be read off the payload
        # alone, exactly as it cannot for damage above: the discarder is a
        # printed reference the resolution binds, absent meaning the target the
        # sentence chose. So the caller's resolved set answers it, and a
        # sentence making somebody *else* discard stays what it is — a gift.
        return str(payload_reference(step)) in self_recipients
    if kind == "choose_one":
        # "…sacrifice a creature **or** discard a creature card" (Crypt
        # Lurker). CR 601.2b lets the payer pick, so the offer is a price only
        # when *every* alternative left on it is one — an offer with a way out
        # that costs nothing is not a price. The modes read here are the ones
        # ``_narrow_to_takeable_actions`` left, so a mode the seat could not
        # take is not counted against it.
        modes = tuple(step.payload.get("modes") or ())
        chosen = [
            mode["instruction"]
            for mode in modes
            if isinstance(mode, dict) and mode.get("instruction") is not None
        ]
        return bool(chosen) and all(
            _step_is_a_payment(instruction, self_recipients)
            for instruction in chosen
        )
    return False


def offered_action_is_a_payment(steps, self_recipients=()) -> bool:
    """Whether taking this offer spends the offered seat's **own** resources.

    *steps* is the offer's accept branch as the compiled program holds it, and
    the leading step is the one the printed sentence offers: the grammar splits
    "You may **A**. If you do, B." into ``action`` and ``then``, and
    ``handlers/control_flow._offer_to_seat`` concatenates them in that order. So
    A is what the seat is being asked to *do* and B is what follows from it —
    which is the whole difference between Sylvan Library ("you may **draw two
    additional cards**. If you do, … pay 4 life or put the card back") and
    Crypt Lurker ("you may **sacrifice a creature or discard a creature card**.
    If you do, draw a card"). Reading the branch as a whole would call both of
    them payments, and reading it as a whole *backwards* would call both gifts.

    *self_recipients* is the set of printed player references that resolve to
    the offered seat, for the one kind whose answer depends on it.
    """
    leading = next((step for step in steps if getattr(step, "kind", None)), None)
    if leading is None:
        return False
    return _step_is_a_payment(leading, frozenset(self_recipients))


@dataclass(frozen=True)
class OfferTrade:
    """A "You may A. If you do, B." offer whose two halves are a **price** the
    taker pays and a **purchase** it gets, each named in the terms a policy can
    weigh — see :func:`offer_trade`."""

    #: "card" — a card out of the taker's own hand; "draw" — the taker's own
    #: draw step.
    price: str
    #: "untap_source" — the offer's own source untaps; "land_card" — a land
    #: card searched out of the taker's library.
    purchase: str


#: Leading steps that take a card out of the taker's own hand.
_HAND_CARD_PRICE_KINDS = frozenset({"exile_chosen_card_from_hand"})


def offer_trade(steps) -> OfferTrade | None:
    """The trade an offer's accept branch makes, or None when it is not one of
    the two shapes this can price on both sides.

    *steps* is the branch as ``_offer_to_seat`` builds it: the offered action
    first, then what follows from taking it.

    The optional-pay default was two constants and each was wrong on one
    card. An offer whose **leading** step spends something is refused
    ("make no trades"), so Forsaken City's "you may exile a card from your
    hand. If you do, untap this land" was declined at every upkeep of every
    game — 122 offers and no untap in six simulated games — and the land was a
    mana once. An offer whose leading step is a gift is taken, so Elfhame
    Sanctuary's "you may search your library for a basic land card … If you
    do, **you skip your draw step this turn**" was taken at every upkeep: 56
    offers, 56 draw steps skipped, a seat that never drew again. The price is
    in the *consequence*, where a reader of the leading step does not look.

    Both are one question — what does it cost and what does it buy — and the
    answer depends on the board (a land is worth a draw to a seat short of
    them; a mana is worth a card to a seat about to discard one), so this names
    the two halves and `ai_prompts.offer_trade_is_worth_taking` weighs them.
    """
    steps = [step for step in steps if getattr(step, "kind", None)]
    if len(steps) < 2:
        return None
    leading, rest = steps[0], steps[1:]
    if leading.kind in _HAND_CARD_PRICE_KINDS and all(
        step.kind == "untap_self" for step in rest
    ):
        return OfferTrade(price="card", purchase="untap_source")
    if (
        leading.kind == "search_library"
        and (leading.payload or {}).get("card_type") == "land"
        and all(
            step.kind == "skip_next_step"
            and (step.payload or {}).get("step") == "draw"
            and (step.payload or {}).get("seat") == "you"
            for step in rest
        )
    ):
        return OfferTrade(price="draw", purchase="land_card")
    return None


#: The alternatives whose whole effect is to give one permanent a keyword, or
#: take one away, and whose recipient a resolution context names: the source
#: itself, or the object the ability was announced with (CR 602.2b).
_GRANTS_TO_SOURCE = frozenset({"grant_self_keyword_until_eot", "grant_self_flying_until_eot"})
_GRANTS_TO_TARGET = frozenset({"grant_target_keyword_until_eot", "grant_target_flying_until_eot"})
_REMOVES_FROM_TARGET = frozenset({"remove_target_keyword_until_eot"})


def offered_alternative_changes_nothing(game, instruction, context) -> bool:
    """Whether taking this alternative of a CR 608.2d choice would leave the
    board exactly as it is.

    The choice is made *while the effect is applied*, so the board it is made
    on is the one the opponent's response left — which is the whole point of
    asking then rather than at activation, and what makes a better default
    than printed order possible. "Target creature loses first strike **or**
    swampwalk" (Urborg) aimed at a swampwalker, or "loses your choice of
    flying, first strike, or trample" (Walking Sponge) aimed at a trampler,
    takes nothing if the first printed word is taken; "this creature gains
    flying, first strike, or trample" (Flowstone Sculpture) on a creature that
    already flies grants nothing.

    Answered for one shape only — a keyword given or taken — because that is
    the one whose effect is fully read off the board. Every other alternative
    answers False, which leaves the caller's printed-order policy exactly as it
    was.
    """
    kind = getattr(instruction, "kind", None)
    payload = getattr(instruction, "payload", None) or {}
    if kind in _GRANTS_TO_SOURCE:
        recipient = getattr(context, "source_permanent", None)
    elif kind in _GRANTS_TO_TARGET or kind in _REMOVES_FROM_TARGET:
        announced = getattr(context, "target_permanent_id", None)
        if isinstance(announced, list):
            announced = announced[0] if len(announced) == 1 else None
        recipient = game.permanent_by_id(announced) if isinstance(announced, int) else None
    else:
        return False
    if recipient is None or not game.is_on_battlefield(recipient):
        return False
    keywords = tuple(payload.get("keywords") or ())
    if not keywords and kind.endswith("_flying_until_eot"):
        keywords = ("flying",)
    if not keywords:
        return False
    held = [bool(game._has_keyword(recipient, keyword)) for keyword in keywords]
    if kind in _REMOVES_FROM_TARGET:
        return not any(held)
    return all(held)


def threatening_color(game, seat: int) -> str | None:
    """The colour of the opposing object a colour chosen *now* is answering,
    or None when nothing on the stack is one.

    "The color of your choice" is named while the effect is applied (CR
    608.2d), which is after every response has resolved and with the stack
    beneath it still waiting — so when Mother of Runes resolves in answer to a
    Lightning Bolt, the Bolt is the topmost object under it, and red is the
    colour whose protection makes the Bolt's target illegal (CR 702.16b). That
    is the whole of the derivation: the topmost object on the stack an opponent
    of *seat* controls, and the first of its colours in CR 105.1's order.
    Through ``_stack_item_colors``, so a spell a Lace recoloured answers as the
    colour it now is, and an ability answers as its source's colour — the
    colour CR 702.16e's damage prevention asks about.

    Nothing on the stack names no colour, and the caller falls back to its own
    board-wide policy.
    """
    for item in reversed(getattr(game, "stack", ()) or ()):
        controller = getattr(item, "caster_index", None)
        if controller is None or controller == seat:
            continue
        colors = set(game._stack_item_colors(item))
        for color in ("W", "U", "B", "R", "G"):
            if color in colors:
                return color
    return None


#: Board sweeps that read "the chosen color" off the resolution's scratchpad,
#: and where each keeps the noun phrase it sweeps: ``destroy_all_matching``
#: carries it as its own payload keys, ``return_all_matching`` under
#: ``filter``. Held to live handler kinds by ``tests/ai/test_ai_valuation.py``.
_COLOR_SWEEP_KINDS = {"destroy_all_matching": None, "return_all_matching": "filter"}
#: Payload keys of a sweep that are not part of the noun phrase.
_SWEEP_RIDERS = frozenset({"color_filter_from", "bypass_regeneration", "targets"})


def chosen_color_sweeps(card: CardDefinition) -> tuple[dict, ...]:
    """The noun phrase of every board sweep on *card* that is narrowed by "the
    color of your choice" — "Destroy all **enchantments** of the color of your
    choice" (Root Greevil), "Return all **permanents** of the color of your
    choice to their owners' hands" (Wash Out), "…all **creatures** of that
    color" (Dromar, the Banisher) — as the filter the sweep's own matcher
    reads, less the colour.

    What the choice is *for*, read off the step that spends it. The default
    colour was the one the opponents held most of among every permanent, so
    Root Greevil named the colour of an opposing army and destroyed no
    enchantment.
    """
    from .oracle_types import CHOSEN_COLOR_THIS_WAY

    sweeps: list[dict] = []
    for step in _walk_program(compile_card_oracle(card)):
        payload = step.payload or {}
        if (
            step.kind not in _COLOR_SWEEP_KINDS
            or payload.get("color_filter_from") != CHOSEN_COLOR_THIS_WAY
        ):
            continue
        nested = _COLOR_SWEEP_KINDS[step.kind]
        described = dict((payload.get(nested) if nested else {
            key: value for key, value in payload.items() if key not in _SWEEP_RIDERS
        }) or {})
        # Once each: a permanent's activated ability is on the program twice,
        # as the ability and mirrored into ``instructions``.
        if described not in sweeps:
            sweeps.append(described)
    return tuple(sweeps)


def color_most_worth_sweeping(game, seat: int, card: CardDefinition) -> str | None:
    """The colour *seat* should name for *card*'s "…of the color of your
    choice" sweep (:func:`chosen_color_sweeps`): the one whose sweep takes
    most from the other seats and least from its own, by
    :func:`permanent_worth` — or None when the card prints no such sweep, or
    no colour's sweep is worth more than nothing.

    Through ``subject_matches``, the matcher the sweep itself asks, with the
    colour read through CR 613's layer 5.
    """
    from .subject_filters import subject_matches

    sweeps = chosen_color_sweeps(card)
    if not sweeps:
        return None
    best, best_worth = None, 0.0
    for color in ("W", "U", "B", "R", "G"):
        worth = 0.0
        for controller, permanent in game.permanents_with_controller():
            if any(
                subject_matches(
                    game, permanent, {**described, "color_filter": color},
                    observer=seat,
                )
                for described in sweeps
            ):
                worth += permanent_worth(permanent) * (-1.0 if controller == seat else 1.0)
        if worth > best_worth + 1e-9:
            best, best_worth = color, worth
    return best


@dataclass(frozen=True)
class TollLoss:
    """What one branch of a *toll* takes from the offered seat, as resources.

    A toll is an offer with a printed penalty for refusing ("…unless you pay 2
    life", "…deals 2 damage to that player unless they sacrifice that
    artifact"), so both of its branches are losses and the seat's answer is
    whichever loss is smaller. This is the loss as the compiled program states
    it — counts of resources, with the permanents resolved to the very objects
    the engine's own deterministic picks would give up — and pricing those
    resources against each other is the weights' job in ``ai_policy``
    (`ai_prompts._toll_loss_price`), which is the same split as every other derivation
    here.
    """

    life: int = 0
    #: Cards leaving the seat's hand or (for an ante) its library for good.
    cards: int = 0
    #: Cards milled off the seat's own library — a loss, but a far smaller one.
    milled: int = 0
    #: The permanents this branch takes off the seat's battlefield: the source
    #: itself, the attached host, or the engine's own default sacrifice picks.
    permanents: tuple = ()
    #: Whether the branch taps the source permanent (a turn's use, not a card).
    taps_source: bool = False

    def plus_life(self, amount: int) -> "TollLoss":
        return TollLoss(
            life=self.life + amount, cards=self.cards, milled=self.milled,
            permanents=self.permanents, taps_source=self.taps_source,
        )


def _offer_target_permanent(game, context):
    """The one permanent the offer's resolution announced as its target, or
    None where it named none, named several, or the permanent has left."""
    named = getattr(context, "target_permanent_id", None)
    # One id, or the one-slot list an announcement made by id arrives as.
    if isinstance(named, (list, tuple)) and len(named) == 1:
        named = named[0]
    if not isinstance(named, int):
        return None
    return game.permanent_by_id(named)


def toll_branch_loss(
    game, player_index: int, steps, self_recipients=(), source_permanent=None,
    context=None,
) -> TollLoss | None:
    """The loss running *steps* costs seat *player_index*, or None when a step's
    loss is not derivable from the compiled program.

    None is a refusal, not a zero: a branch containing any step this cannot
    price ("counter that spell", "creatures able to block it do so") makes the
    whole branch unpriceable, and the caller keeps the standing policy — pay
    tolls — rather than comparing a number to a guess.

    The permanents are resolved to the engine's own answers so the valuation
    and the execution cannot disagree about what is given up:
    ``_sacrifice_candidate_indices`` is what a forced sacrifice may take and
    ``default_sacrifice_pick``'s ordering is which one a seat nobody asked
    gives, exactly as ``ai_valuation.destroyed_permanent_filter`` above reuses the engine's
    filter matcher instead of holding a second opinion.

    *self_recipients* is the same set ``offered_action_is_a_payment`` takes,
    resolved by the caller, for the steps whose payload names a printed player
    reference (``deal_damage``, a self-mill).

    *context* is the resolution the offer sits inside, for the two penalties
    aimed at the **permanent the spell targeted** rather than at a seat or at
    the source: "deals 3 damage to target creature unless …" (Blazing Salvo)
    and "destroy target nonbasic land unless …" (Lava Blister). The loss is
    that permanent when the offered seat controls it and the step would take
    it — a creature the damage does not kill is no loss at all, and neither is
    somebody else's permanent. Without a context those steps stay unpriceable,
    which is what they were.
    """
    from .handlers._targets import attached_host

    player = game.players[player_index]
    recipients = frozenset(self_recipients)
    life = 0
    cards = 0
    milled = 0
    permanents: list = []
    taps_source = False
    for step in steps:
        kind = getattr(step, "kind", None)
        payload = getattr(step, "payload", None) or {}
        if kind == "pay_life":
            amount = payload.get("amount")
            if not isinstance(amount, int):
                return None
            life += amount
        elif kind == "deal_damage":
            amount = payload.get("amount")
            if not isinstance(amount, int):
                return None
            if payload.get("recipient") in recipients:
                life += amount
                continue
            if payload.get("recipient") is not None or not payload.get("targets"):
                return None
            # Damage aimed at the announced permanent. Lethal to a creature
            # the seat controls is that creature gone; anything less is
            # nothing this valuation counts.
            victim = _offer_target_permanent(game, context)
            if victim is None or not victim.is_creature:
                return None
            if (
                game.controller_index_of(victim) == player_index
                and amount >= victim.effective_toughness - victim.damage_marked
            ):
                permanents.append(victim)
        elif kind == "destroy_target_permanent":
            victim = _offer_target_permanent(game, context)
            if victim is None:
                return None
            if game.controller_index_of(victim) == player_index:
                permanents.append(victim)
        elif kind in ("sacrifice_self", "destroy_self"):
            if source_permanent is None or not game.is_on_battlefield(source_permanent):
                return None
            permanents.append(source_permanent)
        elif kind in ("sacrifice_attached_permanent", "destroy_attached_permanent"):
            host = attached_host(game, source_permanent)
            if host is None:
                return None
            permanents.append(host)
        elif kind == "sacrifice_matching_permanent":
            count = int(payload.get("count", 1) or 1)
            exclude = source_permanent if payload.get("exclude_self") else None
            # Indices resolved through the seam (`permanent_at`), never by
            # subscripting the battlefield here — the slot is the engine's to
            # interpret (tests/engine/test_control_reads.py).
            candidates = [
                permanent
                for index in game._sacrifice_candidate_indices(
                    player, dict(payload.get("filter") or {}), exclude
                )
                for permanent in (game.permanent_at(player, index),)
                if permanent is not None
            ]
            if len(candidates) < count:
                return None
            candidates.sort(key=game.sacrifice_preference_key)
            permanents.extend(candidates[:count])
        elif kind == "discard_controller_cards":
            amount = payload.get("amount")
            if not isinstance(amount, int):
                return None
            cards += amount
        elif kind == "discard_x_target_cards":
            # "Target player discards two cards at random unless that player
            # has Skullscorch deal 4 damage to them." A random discard out of
            # the offered seat's own hand (the discarder is a printed reference
            # the resolution binds, read as ``offered_action_is_a_payment``
            # reads it), and only the cards that hand **holds**: CR 609.3's
            # "only as much as possible" makes two random cards out of an
            # empty hand no loss at all. Unpriced, the standing policy paid 4 life
            # to keep a hand of nothing.
            amount = payload.get("amount")
            if not isinstance(amount, int) or payload_reference(step) not in recipients:
                return None
            cards += min(amount, len(player.hand))
        elif kind == "ante_top_card":
            cards += 1
        elif kind == "mill_target_player":
            amount = payload.get("amount")
            if not isinstance(amount, int) or payload.get("recipient") not in recipients:
                return None
            milled += amount
        elif kind == "tap_self":
            taps_source = True
        else:
            return None
    return TollLoss(
        life=life, cards=cards, milled=milled,
        permanents=tuple(permanents), taps_source=taps_source,
    )


#: Instruction kinds that read back a pile something else exiled. A search whose
#: finds one of these reaches is a search whose cards **come back**, and taking
#: the maximum costs the searcher nothing; a search with none of them behind it
#: spends its own library for good.
#:
#: Derived from the compiled program rather than named per card, which is the
#: rule for anything that decides which cards a policy reaches. Erring towards
#: "it comes back" is deliberate: that is the older behaviour, so a kind left
#: off this list changes nothing until somebody notices, where a kind wrongly on
#: it would make a card cheaper than it is.
_EXILED_PILE_READERS = frozenset({
    # "You may cast them this turn." (Chandra, Heart of Fire's -9.)
    "grant_cast_permission",
    "cast_from_exiled_with",
    # "At the beginning of your next upkeep, put those cards into your hand."
    # (Foresight.) The delayed ability is where the return lives, and its own
    # effect is a payload this scan does not open — which is the erring above:
    # a delayed trigger that did something else would read as a return.
    "create_delayed_trigger",
    # The linked-pile readers (Mangara's Tome, Knowledge Vault, Cold Storage).
    "put_exiled_pile_top_into_hand",
    "put_exiled_with_source",
    "put_exiled_pile_on_library",
})


def exiled_search_pile_comes_back(card: CardDefinition) -> bool:
    """Whether anything on *card* reads back what its exile-search found.

    The question a headless seat needs before answering "search your library
    for any number of X, exile them": Foresight, Mangara's Tome and Chandra's
    -9 all hand the cards back and taking the maximum costs nothing, while Mana
    Severance exiles them for good and taking the maximum empties the seat's
    own library of lands. The stated default was written for the first three
    and reasoned from them ("the cards come back castable"), which is a fact
    about those cards rather than about the sentence.

    Program-derived and name-free: a card printing a new "search and exile"
    with a return behind it is covered the day it lands, and one without is
    answered correctly without anybody adding it to a list.

    ``face_down_pile`` counts on its own — that is CR 610.3's recorded pile, and
    a pile the card bothered to record is one it means to read.
    """
    program = compile_card_oracle(card)
    for instruction in _walk_program(program):
        if instruction.kind in _EXILED_PILE_READERS:
            return True
        if instruction.kind == "search_and_exile_matching" and instruction.payload.get(
            "face_down_pile"
        ):
            return True
    return False


def pick_is_tested_for_a_shared_color(card: CardDefinition, result_key: str) -> bool:
    """Whether a later step of *card* asks if its target **shares a color with**
    the permanent a ``choose_permanent`` recorded under *result_key*.

    "Choose a permanent you control. Prevent all combat damage target creature
    would deal this turn **if it shares a color with that permanent**." (Guard
    Dogs.) The pick is the whole of whether the ability does anything, and a
    seat nobody asks took the first candidate in board order — a land, which
    is colourless and shares a colour with nothing (CR 105.2c), so the ability
    resolved and prevented no damage in every simulated game.

    Read off the compiled condition (``target_shares_color_with_chosen`` and
    the record it names), so any card printing the relation is answered and no
    card is named.
    """

    def walk(instructions) -> bool:
        for instruction in instructions:
            payload = getattr(instruction, "payload", None) or {}
            condition = payload.get("condition")
            if (
                isinstance(condition, dict)
                and condition.get("kind") == "target_shares_color_with_chosen"
                and condition.get("permanent_from") == result_key
            ):
                return True
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)) and walk(nested):
                    return True
        return False

    program = compile_card_oracle(card)
    return (
        walk(program.instructions)
        or walk(a.instruction for a in program.activated_abilities if a.instruction is not None)
        or walk(t.instruction for t in program.triggered_abilities if t.instruction is not None)
    )


#: The pile readers that hand back **one card** per use.
_ONE_CARD_PILE_READERS = frozenset({
    "put_exiled_pile_top_into_hand",
    "put_exiled_with_source",
})


def exiled_search_pile_comes_back_one_at_a_time(card: CardDefinition) -> bool:
    """Whether the only thing on *card* that reads its exile-search's pile back
    is an **activated ability with a cost** that returns one card per use.

    "{4}, {T}: Choose a card at random that was exiled with Skyship
    Weatherlight. Put that card into its owner's hand." The pile comes back,
    so :func:`exiled_search_pile_comes_back` says yes and the headless default
    took everything "any number" admits — every artifact and creature in the
    seat's library, to be bought back one a turn at four mana each, at random.
    The cards a game will not last long enough to return are spent exactly as
    Mana Severance's are.

    Derived from where the reader sits in the compiled program, never from the
    card: a pile returned whole (Foresight's delayed draw, Chandra's "you may
    cast them this turn") has a reader outside any activated ability and
    answers False, and a search with a printed ceiling (Mangara's Tome's five)
    is bounded by its own card whatever this says.
    """
    program = compile_card_oracle(card)
    priced: list[OracleInstruction] = []
    for ability in program.activated_abilities:
        if ability.instruction is None:
            continue
        cost = ability.cost
        free = not (
            getattr(cost, "requires_tap", False)
            or any((getattr(cost, "mana", None) or {}).values())
        )
        for step in (ability.instruction, *_effect_steps(ability.instruction)):
            if step.kind in _ONE_CARD_PILE_READERS:
                if free or int((step.payload or {}).get("count", 1) or 1) != 1:
                    return False
                priced.append(step)
    if not priced:
        return False

    def reads_elsewhere(instructions) -> bool:
        for instruction in instructions:
            if instruction.kind in _EXILED_PILE_READERS:
                return True
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = (instruction.payload or {}).get(key)
                if isinstance(nested, (list, tuple)) and reads_elsewhere(nested):
                    return True
        return False

    # A program mirrors each activated ability into ``instructions``, so the
    # spell-side list is read with those mirrors taken out.
    mirrored = {id(step) for step in priced}
    own = [
        instruction for instruction in program.instructions
        if id(instruction) not in mirrored
        and not any(instruction is ability.instruction for ability in program.activated_abilities)
        and instruction.kind not in _ONE_CARD_PILE_READERS
    ]
    if reads_elsewhere(own):
        return False
    return not reads_elsewhere(
        trigger.instruction for trigger in program.triggered_abilities
        if trigger.instruction is not None
    )


# --- "Choose a card name": where the name will be looked for ----------------

#: The steps that read a chosen name against cards of the **chooser's own**,
#: and the zone each one looks in. A player built their own deck, so what
#: their library still holds is theirs to work out (CR 401.2 hides which card
#: is where), and they see their own hand outright — so for these the name
#: worth choosing is one of their own cards.
_OWN_ZONE_NAME_READERS = {
    "reveal_top_sorting_by_chosen_name": "library",
    "reveal_random_card_from_hand": "hand",
}


#: How many flips a seat nobody asks takes when a chosen number is the length
#: of a run that stops at the first loss (Squee's Revenge: two cards for each
#: flip, if every flip is won). A weight. The expected draw is ``2n / 2**n`` —
#: one card at one flip *and* at two, less from three on — and two is the
#: larger prize at the same expectation.
FLIP_RUN_LENGTH = 2


def chosen_number_bounds_flip_run(card: CardDefinition, instruction) -> bool:
    """Whether the number *instruction* chooses is the length of a run of coin
    flips — "Choose a number. Flip a coin **that many times** or until you lose
    a flip…" (Squee's Revenge).

    Read off the steps **behind** the choice in the sequence that holds it, for
    ``chosen_name_own_zone``'s reason directly below: the choice is a step that
    produces a value, and what the value is for is the next sentence. The
    default every other chosen number takes counts mana values on the board
    (``_most_telling_mana_value``, Void's question), which for this card names
    zero flips on an empty board and a dozen on a full one.
    """
    program = compile_card_oracle(card)

    def follows(step) -> bool:
        payload = getattr(step, "payload", None) or {}
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            for position, inner in enumerate(nested):
                if inner is instruction:
                    return any(
                        later.kind == "flip_coins_until_loss"
                        for later in nested[position + 1:]
                    )
                if follows(inner):
                    return True
        return False

    return any(
        follows(root)
        for root in (
            *program.instructions,
            *(ability.instruction for ability in program.activated_abilities),
            *(ability.instruction for ability in program.triggered_abilities),
        )
        if root is not None
    )


def chosen_name_own_zone(card: CardDefinition, instruction) -> str | None:
    """The chooser's own zone *instruction*'s "choose a card name" is then
    looked for in — ``"library"``, ``"hand"`` — or None when it is looked for
    somewhere else (Foreshadow mills an opponent) or nowhere this can see.

    Read off the steps **behind** the choice in the sequence that holds it,
    found by identity in the card's compiled program: the choice is a step
    that produces a value, and what the value is for is the next sentence.
    Wood Sage and Desperate Research reveal the top of *your* library; Cursed
    Scroll reveals a card from *your* hand.
    """
    program = compile_card_oracle(card)
    roots = [
        *program.instructions,
        *(ability.instruction for ability in program.activated_abilities),
        *(ability.instruction for ability in program.triggered_abilities),
    ]

    def search(step) -> str | None:
        if step is None:
            return None
        payload = getattr(step, "payload", None) or {}
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            for position, inner in enumerate(nested):
                if inner is instruction:
                    for later in nested[position + 1:]:
                        zone = _OWN_ZONE_NAME_READERS.get(later.kind)
                        if zone is None:
                            continue
                        if (later.payload or {}).get("revealer", "you") != "you":
                            return None
                        return zone
                    return None
                found = search(inner)
                if found is not None:
                    return found
        return None

    for root in roots:
        found = search(root)
        if found is not None:
            return found
    return None


#: The steps that read a chosen name against a card off the top of **the
#: targeted player's** library: "Choose a card name, then target player mills
#: a card. If a card with the chosen name was milled this way…" (Predict;
#: Foreshadow says "target opponent"). Whose library that is, is settled by
#: the announcement, so this is half an answer and the game supplies the rest.
_TARGET_LIBRARY_NAME_READERS = frozenset({"mill_target_player"})


def chosen_name_is_read_off_the_targets_library(card: CardDefinition, instruction) -> bool:
    """Whether *instruction*'s "choose a card name" is looked for among cards
    milled from **the target player's** library — so that, when that player is
    the chooser, the name worth choosing is one of the chooser's own cards.

    :func:`chosen_name_own_zone`'s question one seat over, and read the same
    way: the steps behind the choice in the sequence that holds it, found by
    identity. A player built their own deck, so what their own library still
    holds is theirs to work out (CR 401.2 hides only *which card is where*) —
    and an **opponent's** library is a hidden zone outright (CR 400.2), which
    is why the answer for a milled opponent stays what it was: that seat's
    graveyard, the public evidence of what its deck holds.
    """
    program = compile_card_oracle(card)

    def search(step) -> bool:
        if step is None:
            return False
        payload = getattr(step, "payload", None) or {}
        for key in ("steps", "then", "else", "action", "otherwise"):
            nested = payload.get(key)
            if not isinstance(nested, (list, tuple)):
                continue
            for position, inner in enumerate(nested):
                if inner is instruction:
                    return any(
                        later.kind in _TARGET_LIBRARY_NAME_READERS
                        for later in nested[position + 1:]
                    )
                if search(inner):
                    return True
        return False

    return any(
        search(root)
        for root in (
            *program.instructions,
            *(ability.instruction for ability in program.activated_abilities),
            *(ability.instruction for ability in program.triggered_abilities),
        )
    )


#: Instruction kinds that take a **targeted card out of a graveyard and out of
#: the game** — "Exile target card from a graveyard." (Coffin Purge, Cremate,
#: Headstone; Crypt Creeper's, Steamclaw's and Scavenging Ooze's abilities.)
#: Spelled out and held to registered handlers by
#: ``tests/ai/test_ai_graveyard_denial.py``, for :data:`ai_valuation.MANA_ABILITY_KINDS`'
#: reason: a kind renamed out from under a set like this stops matching in
#: silence.
#:
#: Denial, and so wanted from an **opponent's** pile: a card in a graveyard is
#: a resource for the seat that owns it (a flashback cast, a reanimation
#: target, a card toward threshold), and removing the caster's own is the
#: effect spent on itself. A kind that *returns* the card it names — to a
#: hand, to the battlefield — is not here: its printed phrase is almost always
#: "from your graveyard", and where it is not, either pile is a gain.
GRAVEYARD_DENIAL_KINDS = frozenset({"exile_target_graveyard_card"})


def exiles_a_graveyard_target(instructions) -> bool:
    """Whether a step of *instructions* (wrappers opened) is one of
    :data:`GRAVEYARD_DENIAL_KINDS` — the question the cast and activation
    choosers ask before naming whose graveyard a card is exiled from."""
    def walk(steps) -> bool:
        for step in steps or ():
            if getattr(step, "kind", None) in GRAVEYARD_DENIAL_KINDS:
                return True
            payload = getattr(step, "payload", None) or {}
            for key in ("steps", "then", "else", "action", "otherwise", "effect"):
                nested = payload.get(key)
                if isinstance(nested, (list, tuple)) and walk(nested):
                    return True
        return False

    return walk(instructions)


def denied_graveyard_pile(player_index: int, piles) -> "int | None":
    """Which of *piles* (seats, in the order offered) a seat takes cards **out
    of the game** from: the first that is not its own, and its own only when
    there is no other. None for no pile at all.

    "Exile up to three target cards from **a single graveyard**" (Decompose,
    Rapid Decay, Ebony Charm; Carrion Beetles' and Famished Ghoul's abilities)
    leaves the pile to the chooser, and the default took the first in seat
    order — so the seat in chair 0 exiled its own graveyard and the seat in
    chair 1 its opponent's, the same card played two ways by where a player
    sat. See :data:`GRAVEYARD_DENIAL_KINDS` for why the opponent's.
    """
    piles = list(piles or ())
    if not piles:
        return None
    return next((seat for seat in piles if seat != player_index), piles[0])


def graveyard_denial_order(game, owner_seat: int, slots) -> list:
    """*slots* — positions in *owner_seat*'s graveyard a seat may exile — with
    the cards their owner could still **cast from there** first, each group
    in pile order.

    A card with flashback (CR 702.34a; printed, or granted by Recoup) is a
    spell its owner still holds; any other card in a graveyard is, to a seat
    removing "up to three", one card among equals. Asked of
    ``flashback.has_flashback`` with the game and the pile's seat, which is
    what sees a grant. A stable sort, so a pile holding none is exiled in the
    order it always was — and a seed that met none replays as it did.
    """
    from .flashback import has_flashback

    pile = game.players[owner_seat].graveyard
    return sorted(
        slots,
        key=lambda slot: 0 if (
            isinstance(slot, int) and 0 <= slot < len(pile)
            and has_flashback(pile[slot], game=game, owner_seat=owner_seat)
        ) else 1,
    )


def graveyard_price_order(game, owner_seat: int, slots) -> list:
    """*slots* — positions in *owner_seat*'s own graveyard that seat is giving
    up **as a price** — least valuable first.

    :func:`graveyard_denial_order` read the other way round, because it is the
    same question asked by the card's owner: a card its owner could still
    **cast from there** (flashback, CR 702.34a — printed, or granted by
    Recoup) is a spell that seat still holds, so it goes last. Among the rest,
    mana value, the one ranking every card in the pool answers (the reading
    Forgotten Lore's default gives the pile an opponent picks from): a land
    goes before a spell and a cheap spell before a dear one. Ties keep pile
    order, so a seed that met none of this replays as it did.

    For every pick out of a seat's own pile whose cards are a payment and not
    what the effect then reads: an offer's or a toll's price ("any player may
    exile a card from their graveyard", Carrion Rats; Gurzigost's "unless you
    put two cards from your graveyard on the bottom"), a replacement's (Nefarious
    Lich), an activation cost (Grim Lavamancer) and a spell's additional cost
    (Haunting Misery). The defaults took the pile in order, so the price was
    whatever sat at the bottom — a flashback spell as soon as a land.
    """
    from .flashback import has_flashback

    pile = game.players[owner_seat].graveyard

    def worth(slot) -> tuple:
        if not (isinstance(slot, int) and 0 <= slot < len(pile)):
            return (1, 0.0)
        card = pile[slot]
        castable = has_flashback(card, game=game, owner_seat=owner_seat)
        return (1 if castable else 0, float(getattr(card, "cmc", 0) or 0))

    return sorted(slots, key=worth)


#: The record keys through which an effect reads **which** cards its own cost
#: exiled: a characteristic of the exiled card ("put X +1/+1 counters, where X
#: is the exiled card's mana value", Necropolis) or a condition on it. The
#: count alone (``cost_exiled_count``, Painbringer) is not on the list — any
#: cards make the same count.
_COST_EXILE_READERS = frozenset({
    "cost_exile_characteristic", "exiled_for_cost", "exiled_set_for_cost",
})


def reads_what_its_cost_exiled(instructions) -> bool:
    """Whether a step of *instructions* reads which cards its own cost exiled
    — so the cards an exile cost takes are not a plain price and
    :func:`graveyard_price_order` must not choose them (the effect wants the
    dearest, not the cheapest)."""
    def mentions(value) -> bool:
        if isinstance(value, str):
            return value in _COST_EXILE_READERS
        if isinstance(value, dict):
            return any(
                key in _COST_EXILE_READERS or mentions(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(mentions(item) for item in value)
        payload = getattr(value, "payload", None)
        return isinstance(payload, dict) and mentions(payload)

    return mentions(tuple(instructions or ()))


__all__ = [
    "GRAVEYARD_DENIAL_KINDS",
    "SELF_PAYMENT_KINDS",
    "OfferTrade",
    "TollLoss",
    "chosen_color_sweeps",
    "chosen_creature_type_side",
    "color_most_worth_sweeping",
    "chosen_name_is_read_off_the_targets_library",
    "denied_graveyard_pile",
    "exiled_search_pile_comes_back",
    "exiled_search_pile_comes_back_one_at_a_time",
    "exiles_a_graveyard_target",
    "graveyard_denial_order",
    "graveyard_price_order",
    "reads_what_its_cost_exiled",
    "offer_trade",
    "offered_action_is_a_payment",
    "pick_is_tested_for_a_shared_color",
    "toll_branch_loss",
]

"""What an offer a resolution makes a player costs and buys, read off the
compiled program for the answer a seat nobody asks gives.

A "you may A. If you do, B.", an "unless … pays" and a CR 608.2d choice
between alternatives are prompts whose default (``mixins/stack/choices``'
``optional_pay`` and ``triggers``) states a policy — take gifts, pay tolls,
make no trades — and a policy needs to know which offers are gifts. Each
reader here names what an offer does by its program, never by a card's name,
for the resolution path that arms the prompt or the policy's answer to it
(``ai_offer_answers``):

* **its price** — whether taking it spends the taker's own resources
  (:func:`offered_action_is_a_payment`, over :data:`SELF_PAYMENT_KINDS`), the
  trade a "you may A. If you do, B." makes (:func:`offer_trade`), and an
  imprint taken out of the hand (:func:`offers_a_hand_imprint`);
* **a purchase that changes nothing** — an alternative of a CR 608.2d choice
  the board already answers (:func:`offered_alternative_changes_nothing`), an
  untap of an untapped target, a gift to an opponent's permanent, a counter
  no card the seat could put would read;
* **a toll's branches** — what each takes from the offered seat, as
  resources (:class:`TollLoss`, :func:`toll_branch_loss`), priced against
  each other by the weights in ``ai_offer_answers``.

Every other choice the rules leave to a player — a colour, a name, a number,
a creature type, a pile, a graveyard card, a discard — is read by
``ai_prompt_readers``. The engine's resolution paths import these from here,
inside the function that asks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .oracle import compile_card_oracle


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
    #: draw step; "source" — the offer's own source, sacrificed.
    price: str
    #: "untap_source" — the offer's own source untaps; "land_card" — a land
    #: card searched out of the taker's library; "target_permanent" — control
    #: of the permanent the ability targets, for good.
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
    the two halves and `ai_offer_answers.offer_trade_is_worth_taking` weighs them.
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
    # "…you may sacrifice it. If you do, gain control of target creature that
    # player controls." (Riptide Entrancer.) The price is the source and the
    # purchase the trigger's target, both permanents a standing prices — so
    # the "make no trades" default that declined it every time it connected
    # (ONS W1G10; nine declines in one seeded game) is a weighing instead.
    if leading.kind == "sacrifice_self" and all(
        step.kind == "gain_control_of_target" for step in rest
    ):
        return OfferTrade(price="source", purchase="target_permanent")
    return None


#: CR 607.2a's two phrases: an ability printed on an object that refers to
#: "the exiled card(s)" or to cards "exiled with [this object]" is linked to
#: the ability of that object that exiled them.
_LINKED_EXILE_PHRASE = re.compile(
    r"\bthe exiled cards?\b|\bexiled with (?:this|that) ", re.IGNORECASE,
)


def offers_a_hand_imprint(steps, source) -> bool:
    """Whether an offer is an **imprint** taken out of the taker's hand: its
    whole accept branch is "you may exile <a card> from your hand", and
    *source* — the permanent whose ability made the offer — prints another
    ability linked to that exile (CR 607.2a).

    "Imprint — When this artifact enters, you may exile a nonartifact,
    nonland card from your hand. / {T}: Add one mana of any of **the exiled
    card's** colors." (Chrome Mox; Isochron Scepter and Soul Foundry print the
    same pair.) The exile is the leading step of the offer and a payment out
    of the seat's own hand, so "make no trades" declined every one — and the
    purchase is not in the offer at all but in the linked ability, which with
    nothing exiled does nothing: a Chrome Mox that taps for no mana, an
    Isochron Scepter that copies nothing, every game.

    The link is read as CR 607.2a states it, off the other abilities the
    permanent has (its *effective* card's lines, so a copy of one is read as
    what it copies). An offer whose purchase follows in the same branch
    (Forsaken City's untap, Ice Cauldron's cast permission) is not this
    shape: there the price and the purchase are both in front of the
    reader (:func:`offer_trade`).
    """
    steps = [step for step in steps or () if getattr(step, "kind", None)]
    if len(steps) != 1 or steps[0].kind not in _HAND_CARD_PRICE_KINDS:
        return False
    if source is None:
        return False
    program = compile_card_oracle(source.effective_card)
    return any(
        _LINKED_EXILE_PHRASE.search(line)
        for line in (program.normalized_text or "").splitlines()
    )


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
        from .game_types import single_chosen_id

        announced = single_chosen_id(getattr(context, "target_permanent_id", None))
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


def offered_untap_changes_nothing(game, entry: dict) -> bool:
    """Whether what an offer buys is an untap of the announced target, and
    that target is untapped — a purchase that leaves the board as it is.

    "Whenever a player casts a red spell, you may pay {3}. If you do, untap
    target permanent." (the Mirage Talismans.) The target is announced as the
    trigger goes on the stack (CR 603.3d) and the price is asked as it
    resolves (CR 608.2d); a seat with nothing tapped on its side still had to
    name something, and the gift rule then tapped three lands to untap a
    permanent that was untapped. Read off the accept branch the offer was
    armed with, so it answers for any offer whose whole purchase is that
    untap (``ai_target_sides.UNTAP_TARGET_KINDS``) and for nothing else.
    """
    from .ai_target_sides import UNTAP_TARGET_KINDS
    from .game_types import single_chosen_id

    steps = [step for step in entry.get("_on_accept") or () if getattr(step, "kind", None)]
    if not steps or not all(step.kind in UNTAP_TARGET_KINDS for step in steps):
        return False
    context = entry.get("_context")
    announced = single_chosen_id(getattr(context, "target_permanent_id", None))
    target = game.permanent_by_id(announced) if isinstance(announced, int) else None
    return target is not None and game.is_on_battlefield(target) and not target.tapped


def offered_gift_lands_on_the_wrong_side(game, seat: int, entry: dict) -> bool:
    """Whether what an offer buys is a gift to its announced target, and that
    target is a permanent an opponent of *seat* controls.

    "When this permanent is put into a graveyard from the battlefield, you may
    put a +1/+1 counter on target artifact creature for each +1/+1 counter on
    this permanent." (CR 702.43a, every Arcbound.) The target is mandatory
    while one exists (CR 603.3d), so a seat whose only artifact creature left
    is an opponent's still names it, and "take gifts" then put the dying
    creature's counters on the opposing creature. The "may" is the card's own
    answer to that board, asked as it resolves (CR 608.2d): declined where
    every step that names the target helps it (``ai_target_sides.
    ability_target_side`` is "you") and the target sits across the table.
    """
    from .ai_target_sides import ability_target_side
    from .game_types import single_chosen_id

    steps = [step for step in entry.get("_on_accept") or () if getattr(step, "kind", None)]
    if not steps or {ability_target_side(step) for step in steps} != {"you"}:
        return False
    context = entry.get("_context")
    announced = single_chosen_id(getattr(context, "target_permanent_id", None))
    target = game.permanent_by_id(announced) if isinstance(announced, int) else None
    if target is None or not game.is_on_battlefield(target):
        return False
    controller = game.controller_index_of(target)
    return controller is not None and controller != seat


def offered_counter_misses_every_card(game, seat: int, entry: dict) -> bool:
    """Whether an offer's whole purchase is a counter on its own source that
    another of the source's abilities reads as a mana value, and the counter
    leaves that reading on no card the seat could put with it.

    "At the beginning of your upkeep, you may put a charge counter on this
    artifact. / {T}: You may put a creature card with mana value equal to the
    number of charge counters on this artifact from your hand onto the
    battlefield." (Aether Vial.) "Take gifts" added a counter every upkeep —
    seven, in a deck with no creature card over four (DST W1G3). Declined
    where a card in the hand answers the count **now** (the counter would
    take it off the one the Vial can put this turn), and where no card of
    the seat's own — its hand and its library, whose contents its owner knows
    though not their order — has a mana value the count would ever reach
    again. Which cards the reading admits is the handler's matcher, over the
    filter the handler resolves (``handlers.hand.
    resolve_source_counted_mana_value``)."""
    from .ai_valuation import hand_entry_steps
    from .handlers._filters import _card_matches_filter
    from .handlers.hand import resolve_source_counted_mana_value
    from .named_counters import counters_on
    from .subject_filters import SOURCE_COUNTED_MANA_VALUE

    steps = [step for step in entry.get("_on_accept") or () if getattr(step, "kind", None)]
    if len(steps) != 1 or steps[0].kind != "add_named_counter_to_self":
        return False
    kind = str(steps[0].payload.get("counter") or "")
    source = entry.get("_source_permanent")
    if not kind or source is None or not game.is_on_battlefield(source):
        return False
    filters = [
        dict(payload.get("card_filter") or {})
        for ability in game.usable_abilities_of(source)
        for payload in hand_entry_steps(ability.instruction)
        if (payload.get("card_filter") or {}).get(SOURCE_COUNTED_MANA_VALUE) == kind
    ]
    if not filters:
        return False
    now = counters_on(source, kind)
    player = game.players[seat]

    def answers(card, described) -> bool:
        return _card_matches_filter(card, described, game=game, owner=player)

    for described in filters:
        at_now = resolve_source_counted_mana_value(described, source)
        if any(answers(card, at_now) for card in player.hand):
            return True
    after = now + int(steps[0].payload.get("count", 1) or 1)
    for described in filters:
        unbound = {key: value for key, value in described.items() if key != SOURCE_COUNTED_MANA_VALUE}
        reached = {**unbound, "mana_value": {"op": "ge", "value": after}}
        if any(answers(card, reached) for card in (*player.hand, *player.library)):
            return False
    return True


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
    (`ai_offer_answers._toll_loss_price`), which is the same split as every other derivation
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
    #: Cards the seat exiles out of its own graveyard as the price (Rotting
    #: Giant's "unless you exile a card from your graveyard", Web of
    #: Inertia's offer) — a pile threshold, flashback and the rest still read.
    exiled_from_graveyard: int = 0

    def plus_life(self, amount: int) -> "TollLoss":
        return TollLoss(
            life=self.life + amount, cards=self.cards, milled=self.milled,
            permanents=self.permanents, taps_source=self.taps_source,
            exiled_from_graveyard=self.exiled_from_graveyard,
        )


def _offer_target_permanent(game, context):
    """The one permanent the offer's resolution announced as its target, or
    None where it named none, named several, or the permanent has left."""
    from .game_types import single_chosen_id

    named = single_chosen_id(getattr(context, "target_permanent_id", None))
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
    exiled_from_graveyard = 0
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
                    player, dict(payload.get("filter") or {}), exclude,
                    # Not what this loop has already chosen to give up
                    # (Fade Away's earlier repetitions).
                    held=getattr(context, "sacrifice_batch", None),
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
        elif kind == "mill_target_player" and payload.get("recipient") is None:
            # "…target player mills six cards" (Book Burning's unpaid branch).
            # The announced player, who is this seat exactly when the
            # resolution's target is (``target_player`` among *recipients*);
            # another seat's library is no loss of this seat's.
            amount = payload.get("amount")
            if not isinstance(amount, int) or not payload.get("targets"):
                return None
            if "target_player" in recipients:
                milled += amount
        elif kind == "mill_target_player":
            amount = payload.get("amount")
            if not isinstance(amount, int) or payload.get("recipient") not in recipients:
                return None
            milled += amount
        elif kind == "destroy_all_creatures":
            # "…destroy all creatures. Creatures destroyed this way can't be
            # regenerated." (Breaking Point's unpaid branch.) This seat's share
            # of the sweep — its own creatures the destruction would take, read
            # the way ``destroy_sweeps._sweep_by_type`` reads them: through
            # layer 4 (``is_creature``), sparing what is indestructible and,
            # unless the card forbids it, what has a regeneration shield up.
            regenerates = not payload.get("bypass_regeneration")
            permanents.extend(
                permanent for permanent in game.controlled_by(player_index)
                if permanent.is_creature
                and not game._has_keyword(permanent, "indestructible")
                and not (regenerates and permanent.regeneration_shield > 0)
            )
        elif kind == "tap_self":
            taps_source = True
        elif (
            kind == "exile_cards_from_graveyard"
            and payload.get("graveyard_owner") == "you"
            and not payload.get("targets")
        ):
            # "…unless you exile a card from your graveyard" (Rotting Giant);
            # "that player may exile a card from their graveyard" (Web of
            # Inertia). One pick out of the performer's own pile — "you" is
            # whoever performs it, the offered seat itself when ``caster`` is
            # among *recipients* — and only as many as the pile holds.
            count = payload.get("count")
            if not isinstance(count, int) or "caster" not in recipients:
                return None
            exiled_from_graveyard += min(count, len(player.graveyard))
        elif kind == "cant_attack_until_eot" and payload.get("controller_seat_record"):
            # "…creatures they control can't attack you this turn" (Web of
            # Inertia's decline). Whether an attack is worth anything is not
            # derivable here — but having no creature that could make one is:
            # then the restriction takes nothing, and refusing the offer is
            # free. Anything else stays unpriceable. "Could attack" is the
            # declaration's own reader (untapped, not summoning sick, every
            # restriction already standing), asked against the seat the entry
            # will protect — the source's controller, as the handler reads it.
            defender = (
                game.controller_or_last_known(source_permanent)
                if source_permanent is not None else None
            )
            if defender is None or game.legal_attacker_indices(
                player_index, against=defender
            ):
                return None
        else:
            return None
    return TollLoss(
        life=life, cards=cards, milled=milled,
        permanents=tuple(permanents), taps_source=taps_source,
        exiled_from_graveyard=exiled_from_graveyard,
    )


__all__ = [
    "SELF_PAYMENT_KINDS",
    "OfferTrade",
    "TollLoss",
    "offer_trade",
    "offered_action_is_a_payment",
    "toll_branch_loss",
]

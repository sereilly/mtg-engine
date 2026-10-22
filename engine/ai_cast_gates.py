"""Whether a cast the policy would propose can be made as it would be
announced — asked before the cast is weighed.

Each is a refusal the cast path would make, or a trade the seat should
decline, asked here so the policy proposes nothing the engine refuses (a
refused cast costs nothing and breaks no rule, and the seat re-proposes it
every turn):

* **a legal target to name** (CR 601.2c) — :func:`_can_cast_with_targets`
  and :func:`_no_legal_cast_target`, over the engine's own enumeration for
  the candidate's mode and zone, with :func:`_targets_are_optional` for an
  "up to";
* **a target an opponent's permanent requires** (the Flagbearers) — the
  announcement re-aimed to obey it (:func:`_aimed_under_target_requirements`);
* **every cost beyond mana** (CR 601.2b, 601.2h, 118.9) — printed additional
  costs, the life it pays (:func:`_cast_life_price`), and an alternative cost
  with the mana a tax still adds to it (:func:`_alternative_cost_tap_plan`);
* **what the cast asks of its caster** — the sacrifices its effect makes
  (:func:`_caster_can_make_its_sacrifices`), a card in hand its own pick needs
  (:func:`_caster_holds_a_hand_pick_entrant`), and an entry gate that gives
  back more than it brings (:func:`_entry_gate_gives_back_more_than_it_brings`,
  with :func:`given_back_first`, the order a seat returns its own permanents
  in).

The engine's own gate is asked wherever there is one, for the reason every
affordability question in the policy is: a policy that judged a cost by its
own reading would propose casts the cast path then refuses.
"""

from __future__ import annotations

from .ai_weighed_cast import SPELL_TYPES, PermittedCast
from .ai_target_sides import spell_target_side
from .ai_valuation import (
    entry_self_return_gate,
    caster_sacrifice_steps,
    spell_hand_pick_entries,
)
from .cast_costs import additional_costs
from .cast_prohibitions import cast_prohibition
from .game import Game
from .models import CardDefinition, Permanent
from .oracle import compile_card_oracle
from .subject_filters import subject_matches
from .targeting import bounce_subject_filter, spec_roles
from .ai_payment import _plan_land_taps
from .ai_actions import (
    _OFFERS_ANNOUNCED,
    _announced_mode,
    _announced_steps,
    _cast_zone,
    _cast_spec,
)
from .ai_scoring import choose_attack_target, _permanent_value


def _cast_life_price(
    card: CardDefinition, from_zone: str, x_value: "int | None",
    offers: "dict[str, int] | None", under: "PermittedCast | None",
) -> int:
    """The life the announcement being built pays **as a cost** (CR 601.2h):
    every printed additional cost that applies to a cast from *from_zone* and
    is mandatory or taken (`optional_cost_taken`, the cast path's own reader),
    at the announced X, plus what a required alternative cost asks
    (`PermittedCast.cost`: a flashback cost printed with "Pay 3 life")."""
    from .mixins.stack.casting import optional_cost_taken

    total = 0
    for cost in additional_costs(card):
        if cost.from_zone not in (None, from_zone):
            continue
        if not optional_cost_taken(cost, offers):
            continue
        total += int(cost.life_charged(x_value) or 0)
    if under is not None and under.cost is not None:
        total += int(getattr(under.cost, "pay_life", 0) or 0)
    return total


def _aimed_under_target_requirements(
    game: Game, player_index: int, card: CardDefinition, from_zone: str,
    target, target_permanent_index, target_permanent_ids, divided_targets,
):
    """The announcement ``(seat, slot, ids, division)`` as the cast gate will
    accept it under a requirement an opponent's permanent prints about it
    ("…that player must choose at least one Flagbearer on the battlefield if
    able", ``engine/target_requirements.py``) — unchanged where nothing binds
    it or it already obeys, **re-aimed** where it can, None where this seat
    should not make it at all.

    Asked of the engine's own gate (`Game.cast_target_requirement_refusal`)
    for the reason every gate in the candidate builders is: a cast the engine
    will refuse costs nothing, and the seat re-proposes it every turn —
    `refused_casts`, for as long as the Flagbearer lives.

    The re-aim is onto a required permanent **on the board the policy already
    chose**, which is what keeps it a decision about the rule and not about
    the card: removal and burn pointed at the opponent land on the opponent's
    Flagbearer, and a Giant Growth pointed at this seat's own creature is not
    turned into a gift — with no Flagbearer of its own to put it on, the seat
    holds the card. One slot, or the first entry of a division; an
    announcement of several objects or of roles is not rebuilt here.
    """
    from .target_requirements import one_slot

    mode_index = _announced_mode(card)
    offers = _OFFERS_ANNOUNCED.get()
    standing = (target, target_permanent_index, target_permanent_ids, divided_targets)
    if game.cast_target_requirement_refusal(
        player_index, card,
        announcements=[
            (mode_index, target, target_permanent_index, target_permanent_ids, None)
        ],
        divided_targets=divided_targets,
        from_zone=from_zone,
        optional_cost_payments=offers,
    ) is None:
        return standing
    spec = game.cast_target_spec(
        player_index, card, from_zone=from_zone,
        optional_cost_payments=offers, mode_index=mode_index,
    )
    wanted = [
        entry for entry in spec.get("required_targets") or ()
        if entry.get("seat") == target
    ]
    if not wanted:
        return None
    pick = wanted[0]
    if divided_targets:
        first = tuple(divided_targets[0])
        return (
            target, target_permanent_index, target_permanent_ids,
            [(pick["seat"], pick["index"], *first[2:]), *divided_targets[1:]],
        )
    if not one_slot(spec):
        return None
    return pick["seat"], pick["index"], [pick["id"]], None


def _printed_costs_are_payable(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    from_zone: str,
    x_value: int | None,
    taken: "dict[str, int] | None" = None,
) -> bool:
    """Whether *card*'s printed additional costs (CR 601.2b) can be paid now.

    *taken* is the candidate's answer to the optional ones: a price nobody
    took is not charged and cannot make the spell uncastable, and one that
    was taken ("Buyback—Sacrifice a land") is gated like any other.

    Asked of ``_unpayable_additional_cost`` rather than re-derived, for the
    reason :func:`_alternative_cost_is_payable` beside it gives: a policy that
    judged a cost by its own reading would propose casts the cast path then
    refuses. The gate is pure — it spends nothing and moves nothing — so asking
    it here cannot leave a half-paid cost behind.

    The costs are filtered by zone first, exactly as ``queue_from_hand`` filters
    them: a cost naming a zone is a price for casting from *that* zone, so a
    hand cast must not be gated on the graveyard price of the same card
    (Demonic Embrace).
    """
    from .cast_costs import additional_costs

    printed = tuple(
        cost for cost in additional_costs(card)
        if cost.from_zone is None or cost.from_zone == from_zone
    )
    if not printed:
        return True
    return game._unpayable_additional_cost(
        player_index, card, printed,
        spell_hand_index=hand_index if from_zone == "hand" else None,
        from_zone=from_zone,
        x_value=x_value,
        taken=taken,
    ) is None


def _alternative_cost_is_payable(
    game: Game, player_index: int, card: CardDefinition, hand_index: int
) -> bool:
    """Whether *card*'s printed alternative cost (CR 118.9) can be paid now.

    Asked of the engine's own gate rather than re-derived here, for the reason
    every other affordability question in this policy is: a policy that judged
    a cost by its own reading would propose casts the cast path then refuses,
    and `refused_casts` counts exactly that.

    The gate is a pure predicate over the board — it spends nothing and moves
    nothing — so asking it here costs a lookup and cannot leave a half-paid
    cost behind.
    """
    # Printed **and** granted (Dream Halls' board-wide offer), through the one
    # reader the cast path itself asks. A policy reading only the printed half
    # would be a second answer to "what may this be paid with", and the
    # direction it fails in is a seat that holds a castable spell all game --
    # which is the shape this function was written for in the first place.
    printed = game.applicable_alternative_costs(player_index, card)
    if len(printed) != 1:
        # None to take, or more than one and CR 118.9a lets only one be
        # applied — a choice this policy has no card to make and the cast path
        # refuses outright.
        return False
    return game._unpayable_alternative_cost(
        player_index, card, printed[0], spell_hand_index=hand_index,
    ) is None


def _alternative_cost_tap_plan(
    game: Game, player_index: int, card: CardDefinition, *, extra_generic: int = 0,
) -> "tuple[tuple[int, ...], tuple[str, ...]] | None":
    """The taps that pay the **mana** an alternative-cost cast of *card* still
    owes (CR 118.9d), or None when the board cannot pay it.

    The amount is the engine's (`Game.alternative_cost_mana`): nothing on an
    untaxed board, which plans no tap at all and is every such cast this policy
    made before the cast path charged the increases.

    A plan that would tap the creature the cost itself must tap ("you may tap
    an untapped creature you control rather than pay this spell's mana cost",
    Lashknife, with a Llanowar Elves the only creature) is no plan: the mana
    would be made and the cast refused for want of an untapped creature.
    """
    printed = game.applicable_alternative_costs(player_index, card)
    if len(printed) != 1:
        return None
    cost = printed[0]
    owed = game.alternative_cost_mana(
        player_index, card, cost, extra_generic=extra_generic,
    )
    plan = _plan_land_taps(game, game.players[player_index], owed)
    if plan is None or not cost.tap_count:
        return plan
    planned = [game.permanent_at(player_index, index) for index in plan[0]]
    left = [
        permanent
        for permanent in game._additional_cost_candidates(
            player_index, cost, giving_up="tap"
        )
        if not any(permanent is tapped for tapped in planned)
    ]
    return plan if len(left) >= cost.tap_count else None


def _can_cast_with_targets(game: Game, caster_index: int, card: CardDefinition) -> bool:
    """Whether *card* has a legal target for the effect it carries out **as it
    is cast**.

    Only a spell does; see ``ai_weighed_cast.SPELL_TYPES``. A permanent's
    instruction list mirrors its *abilities*, which choose their own targets on
    activation — so reading it here would refuse to cast Flying Carpet while the
    AI controls no creature, and refuse Pyramids while the opponent controls no
    enchantment, for permanents that are perfectly castable and simply have
    nothing to point at yet. That is the same misreading ``SPELL_TYPES`` exists
    to prevent one module over, and ``targeting.derive_cast_spec`` guards with
    the same gate for the UI's benefit.
    """
    if cast_prohibition(
        game, caster_index, card, from_zone=_cast_zone(card)
    ) is not None:
        # CR 601.3, through the predicate the cast path itself refuses with
        # (`engine/cast_prohibitions.py`): a prohibited spell is refused before
        # any cost, nothing is spent, and a seat that goes on proposing it does
        # nothing for the rest of the game — which is exactly what
        # `simulate_ai_games.py`'s `refused_casts` counts. Asked for every
        # card and not only a spell, because some prohibitions stop a land
        # being *played* too (City in a Bottle, Null Chamber, Cornered Market)
        # and the predicate knows which it was handed.
        #
        # This was seven of the cast path's thirteen bans, each added here the
        # day a simulation found a seat stuck behind it; the six it lacked
        # (Steel Golem, Arcane Laboratory, Damping Engine, City of Solitude,
        # Hand to Hand, Cornered Market) were six seats still stuck.
        return False

    if card.primary_type not in SPELL_TYPES:
        return True

    # The engine's own enumeration, asked **before** the arms below. Those arms
    # are preferences as much as legality — "is there something on the
    # opponent's board worth destroying" — and each reads one or two payload
    # keys, so a narrowing the key does not carry is invisible to it: Tunnel
    # ("destroy target Wall") reads `type_filter == "creature"` and answers yes
    # to any creature at all, then the cast path checks `wall_only` and
    # refuses. Putting the engine's answer first can only ever skip *more*
    # casts, and only ones it can prove have no legal target.
    if _no_legal_cast_target(game, caster_index, card):
        return False

    opponent = game.players[choose_attack_target(game, caster_index)]

    program = compile_card_oracle(card)
    # The steps of the mode being weighed (`_announced_steps`): these arms are
    # keyed on the *first* kind they meet, and for a modal card that was
    # always mode 0's.
    for instruction in _announced_steps(card, program):
        kind = instruction.kind

        if kind == "bounce_target_creature":
            # What the bounce named is payload, not the word "creature":
            # Boomerang names any permanent and Flash Flood names a Mountain,
            # and a check keyed to one card's noun would have the AI hold a
            # Boomerang while the opponent's board was all lands. The same
            # reading the cast gate uses, tested with the same matcher.
            wanted = bounce_subject_filter(instruction.payload)
            return any(
                subject_matches(game, perm, wanted, observer=caster_index)
                for perm in game.controlled_by(opponent)
            )

        if kind == "destroy_target_permanent":
            type_filter = instruction.payload.get("type_filter")
            color_filter = instruction.payload.get("color_filter")
            if type_filter or color_filter:
                # "Is there something on the opponent's board this may
                # destroy" — the engine's own list of what the announcement
                # may name, filtered to that seat. It was a matcher of this
                # arm's own over two payload keys, comparing the permanent's
                # *printed, collapsed* type word to the filter: an artifact
                # creature is "creature", so Shatter was never cast at one, and
                # a filter naming several types ("Destroy target artifact or
                # land", Pillage; Creeping Mold, Fissure, Eliminate) is a list,
                # which equals no word at all — those spells were never cast.
                return _a_legal_target_is_controlled_by(
                    game, caster_index, card, choose_attack_target(game, caster_index)
                )

        if kind in {"pump_target_creature_until_eot", "grant_regeneration_to_target_creature",
                    "grant_target_flying_until_eot", "berserk_pump"}:
            # A gift wants one of the caster's own creatures to land on — and
            # a pump is not always a gift. "Target creature gets -2/-2 until
            # end of turn" is this same kind, so the arm asked a seat casting
            # a kill spell whether it had a creature *of its own* to shrink,
            # and held the card until it did. Which board is the effect's own
            # reading (`spell_target_side`: the sign of the change), and what
            # is on it is the engine's list.
            wanted = (
                choose_attack_target(game, caster_index)
                if spell_target_side(card) == "opponent" else caster_index
            )
            return _a_legal_target_is_controlled_by(game, caster_index, card, wanted)

    return True


def _no_legal_cast_target(game: Game, caster_index: int, card: CardDefinition) -> bool:
    """Whether *card* names a mandatory target and the board offers none.

    The chain above is an if-chain over instruction kinds, so every kind it does
    not name fell out of the bottom as "castable" — and for a spell that
    *targets*, castable-with-no-target is a turn the AI spends on an action the
    engine then refuses. It does not lose the game or break a rule (the cast
    gate declines before any mana is spent, CR 601.2c), which is why nothing
    caught it: it is silent, and it repeats. The simulator's old eight-card
    decklist could not reach it because every card in it had an arm. Random
    decks reach it immediately — Deathlace and Thoughtlace (``spell_or
    _permanent``, a kind with no arm) were chosen, refused, and chosen again
    every turn of every game, so a seat holding one never did anything else.

    Rather than adding two more arms — the next unnamed kind would just repeat
    this — ask the enumeration the picker and the cast path already use. That
    is the same move ``activation_target_refusal`` made when it replaced the
    per-kind if-chain in ``activation.py``.

    **Two layers since INV W2G7.** The first is the engine's own CR 601.2c
    predicate, so the rule has one definition; the second is this policy's
    wider preference, which also declines casts the engine *accepts* because
    they are legal and useless. "Is every quantifier an *up to*?" is the
    second layer's question now and no longer the definition of a targeted
    spell — it called "X target creatures" and "any number of target
    creatures" mandatory, which the engine does not, and that reading must not
    travel back into the cast path.
    """
    # **The engine's rule first, through the engine's predicate** (CR 601.2c,
    # `legality.no_legal_cast_target_refusal`) — the very call the cast path
    # refuses with, so a spell the engine would decline for want of a target is
    # one this policy cannot propose, by construction rather than by two
    # readers happening to agree. They did not: this function decided "needs a
    # target" from every quantifier in the program, the cast path from a
    # per-kind arm, and 182 spells sat between the two.
    #
    # Asked about the candidate being built (`_OFFERS_ANNOUNCED`): CR 702.33g
    # makes a kicked-only target a target of the kicked cast alone, so the
    # obligation — and, below, the enumeration that probes each candidate
    # against the spell's own spec — is a different one per announcement. Read
    # as the card's every arm, an unkicked Rushing River was a two-target spell
    # with one target named for it, which no list is ever legal for: the seat
    # held it until it could spare a land for the kicker.
    announced = _OFFERS_ANNOUNCED.get()
    mode_index = _announced_mode(card)
    if game.no_legal_cast_target_refusal(
        caster_index, card, optional_cost_payments=announced,
        mode_index=mode_index, from_zone=_cast_zone(card),
    ) is not None:
        return True
    # What follows is **preference and remainder**, and is deliberately wider
    # than the rule: the shape the engine's predicate leaves to another gate
    # (a target on the stack), and the casts that are legal and buy nothing —
    # "X target creatures" at an X of zero, "any number of target" at none, a
    # *source of your choice* with no source in play. Declining those is this
    # policy's business; refusing them is not the engine's.
    program = compile_card_oracle(card)
    # **A modal spell is asked about the mode being weighed** (`_announced
    # _mode`), and so is every question above and below. It was asked about
    # mode 0, because this policy named no mode and that is what the engine
    # resolves a cast naming none as: Blue Elemental Blast's first bullet
    # counters a red spell, so with an empty stack the whole card was
    # uncastable to an AI seat while its second bullet had a red permanent to
    # destroy. A mode whose target is **on the stack** is not this function's
    # (`ai_targets._NOT_OBJECT_SPECS`): the modes weighed are the engine's own list of
    # the announceable ones, and that list has asked the stack gate already.
    spec = _cast_spec(card, program)
    if spec is None or spec.get("kind") in ("none", "modal") or spec_roles(spec):
        # No spec, no target; roles are `ai_targets._choose_role_targets`' question and it
        # already declines an unfillable chain.
        return False
    if _targets_are_optional(_announced_steps(card, program)):
        # "Up to one target" is castable with none (CR 601.2c).
        return False
    return not game._enumerate_targets(
        caster_index, card, spec, for_cast=True, optional_cost_payments=announced,
        mode_index=mode_index,
    )


def _a_legal_target_is_controlled_by(
    game: Game, caster_index: int, card: CardDefinition, seat: int
) -> bool:
    """Whether the candidate being built could name a permanent *seat*
    controls: the engine's own enumeration for the announcement (the list a
    human's picker is built from), read for one battlefield.

    For a preference arm that wants its target on a particular board. True
    when the announcement names roles instead — `ai_targets._choose_role_targets` picks a
    side per role and declines an unfillable chain — or nothing a picker lists.
    """
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec_roles(spec):
        return True
    legal = game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    )
    return any(
        entry.get("kind") == "permanent" and entry.get("seat") == seat
        for entry in legal
    )


def _targets_are_optional(instructions) -> bool:
    """True when every ``targets`` quantifier *instructions* carry is an
    "up to". The caller hands the steps of the candidate being built
    (`_announced_steps`), so a modal spell is asked about the mode weighed."""
    quantifiers: list[str] = []

    def walk(instruction) -> None:
        if instruction is None:
            return
        payload = getattr(instruction, "payload", None) or {}
        targets = payload.get("targets")
        if isinstance(targets, dict) and "quantifier" in targets:
            quantifiers.append(targets.get("quantifier"))
        for step in payload.get("steps") or ():
            walk(step)

    for instruction in instructions:
        walk(instruction)
    return bool(quantifiers) and all(q == "up_to" for q in quantifiers)


def _caster_can_make_its_sacrifices(
    game: Game, caster_index: int, card: CardDefinition
) -> bool:
    """Whether every sacrifice *card*'s own effect has its caster make will
    give something up (``ai_valuation.caster_sacrifice_steps``).

    Asked of the engine's own candidate list — the one the sacrifice handler
    picks from — so the policy and the resolution cannot disagree about what
    "a creature" admits. "Sacrifice **any number of** …" is answered by the
    seat's own default, which is the stated policy in
    ``_resolve_sacrifice_inline``: a seat nobody asks gives up none. So this
    seat's Renounce, Reprocess or Landslide would sacrifice nothing and the
    rest of the spell, counting what went, would do nothing — measured at
    MMQ, where skipping a self-exiling Last Breath left Renounce as the cast
    and it resolved for zero.
    """
    player = game.players[caster_index]
    for step in caster_sacrifice_steps(card):
        if step["any_number"]:
            return False
        if not game._sacrifice_candidate_indices(player, step["filter"]):
            return False
    return True


def _entry_gate_gives_back_more_than_it_brings(
    game: Game, caster_index: int, card: CardDefinition
) -> bool:
    """Whether casting *card* now is a trade down: it prints "when this
    enters, return a <noun> you control to its owner's hand"
    (``ai_valuation.entry_self_return_gate``), it is itself such a <noun>, and
    what the seat would have to give back is worth more than *card*.

    Two boards, one answer. With **no other** such permanent the pick is forced
    onto the entering one — the cast ends with the card back in hand and the
    mana spent, and the seat re-proposes it next turn and the turn after. With
    one, the seat gives back whatever `given_back_first` puts first, and when
    that costs more to replace than *card* itself the cast has shrunk the board
    (Horned Kavu returning Shivan Wurm, which then returns Horned Kavu: nine
    casts in six simulated games, each undoing the last). Not proposed in
    either, for the reason every gate in `ai_casts._cast_candidate_announcing` is there.

    Both halves through the matchers the resolution itself asks —
    ``_card_matches_filter`` for the card in hand, ``subject_matches`` for the
    board (colour through the layers, so a creature turned red counts as red).
    A card its own noun does not admit is left alone: with nothing to return
    the trigger does nothing, and the permanent stays.
    """
    from .handlers._filters import _card_matches_filter

    gate = entry_self_return_gate(card)
    if gate is None:
        return False
    described = dict(gate.get("filter") or {})
    player = game.players[caster_index]
    if not _card_matches_filter(card, described, game=game, owner=player):
        return False
    others = [
        permanent for permanent in game.controlled_by(caster_index)
        if subject_matches(game, permanent, described, observer=caster_index)
    ]
    if not others:
        return True
    given = given_back_first(others, None)[0]
    loss = _given_back_loss(given)
    if loss != float(card.cmc):
        return loss > float(card.cmc)
    # An even swap, which is a cast only when it is not half of a loop: the
    # permanent given back is itself a gate whose noun admits *card*, so
    # recasting it gives *card* back, and the seat spends every turn's mana
    # exchanging one for the other. Measured in six seeded Planeshift games
    # with Sawtooth Loon and Doomsday Specter pinned (both four mana, each a
    # blue creature the other's gate admits): Loon returned Specter, Specter
    # returned Loon, Loon returned Specter — the "A returns B, B returns A" of
    # the paragraph above, with nothing dearer on either side for the
    # comparison to catch. An even swap for anything else develops the board a
    # turn later and is left alone.
    answering = entry_self_return_gate(given.effective_card)
    return answering is not None and _card_matches_filter(
        card, dict(answering.get("filter") or {}), game=game, owner=player
    )


def _given_back_loss(permanent: Permanent) -> float:
    """What a seat loses by returning *permanent* to its owner's hand.

    A card comes back for its mana value. A *token* does not come back at all
    (CR 111.7), so it is priced as the body the board loses
    (`_permanent_value`) — which keeps a 1/1 token on the table beside a
    one-drop and gives it up before a six-drop.
    """
    if permanent.metadata.get("is_token"):
        return _permanent_value(permanent)
    return float(permanent.card.cmc)


def given_back_first(permanents, source) -> list:
    """*permanents* — one seat's own — in the order that seat gives them back
    to its hand when a permanent it controls makes it return one.

    For ``_default_permanent_set_choice``, and only where *source* (the
    permanent asking) is itself one of them: gating, Shrieking Drake,
    Stampeding Wildebeests. Three rules, in order:

    * **the asking permanent last** — returning it undoes the cast that asked;
    * **the smallest loss first** (`_given_back_loss`);
    * **board order** between equals, which is the determinism every default
      in the registry keeps.

    The weights are tuning and live here; that they are consulted at all is
    the registry's decision, made where the candidates are known.
    """
    ranked = sorted(
        enumerate(permanents),
        key=lambda entry: (
            entry[1] is source, _given_back_loss(entry[1]), entry[0],
        ),
    )
    return [permanent for _slot, permanent in ranked]


def _caster_holds_a_hand_pick_entrant(
    game: Game, caster_index: int, card: CardDefinition, hand_index: int | None
) -> bool:
    """Whether the caster holds — besides *card* itself, which is on the stack
    by then (CR 601.2a) — a card the spell's own "choose a card in your hand"
    pick could put onto the battlefield
    (``ai_valuation.spell_hand_pick_entry_filters``).

    Through ``_card_matches_filter``, the matcher the entering step itself asks.

    …and through the **guard** around the entering step, where there is one
    ("…put that card onto the battlefield if it has the same name as a
    permanent", Retraced Image): a held card the guard refuses enters nothing,
    so a cast whose every pick would be refused is a card spent on a reveal.
    The guard is the engine's own evaluator, handed the card under the record
    the pick writes.
    """
    from .game_types import OracleExecutionContext
    from .handlers._filters import _card_matches_filter
    from .handlers.control_flow import evaluate_condition

    entries = spell_hand_pick_entries(card)
    if not entries:
        return True
    player = game.players[caster_index]
    held = [c for slot, c in enumerate(player.hand) if slot != hand_index]

    def enters(entry: dict, held_card) -> bool:
        if not _card_matches_filter(
            held_card, entry["card_filter"], game=game, owner=player
        ):
            return False
        guard = entry.get("guard")
        if not guard:
            return True
        context = OracleExecutionContext(
            caster=player, target=player, card=card,
            results={entry["result_key"]: [held_card]},
        )
        return bool(evaluate_condition(game, context, guard))

    return all(any(enters(entry, c) for c in held) for entry in entries)

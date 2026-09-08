"""What a seat nobody asked does with a free "you may …" offer.

``_default_optional_pay`` decided by **affordability**, which for a free offer
is vacuously true — so every free offer was accepted, and nobody chose that.
It was right for a gift ("you may draw a card") and wrong for a price the
grammar had put somewhere the affordability test could not look: "you may
sacrifice another creature", "you may ante the top card of your library". Those
are costs printed as deeds rather than as mana, and the seat paid them every
time it was not asked.

The policy now is one line — **take gifts, pay tolls, make no trades** — and
both halves of it are read off the compiled program:

* the *price* is ``ai_valuation.offered_action_is_a_payment``, over the
  instruction kinds the rules define as done to oneself (CR 701.21a, 701.9a,
  118.3b, 407.4, 701.13a). A kind, never a card name, so the eight cards in the
  pool that print "you may sacrifice …" and every card still to come are
  classified by construction;
* the *penalty* is whether the offer has an "if you don't" branch at all. With
  one, refusing is not free either and which of two losses is smaller is the
  seat's judgement rather than a default's.

These tests ask the property of **every** free offer the pool compiles, found
by walking the programs rather than by naming cards, so a newly ingested card
is covered the day it is ingested.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_valuation import SELF_PAYMENT_KINDS, offered_action_is_a_payment
from engine.handlers.registry import EFFECT_HANDLERS
from engine.oracle import compile_card_oracle
from engine.pending_choices import PendingChoice

#: Payload keys that hold nested instructions. The walk has to be wide because a
#: ``may`` can sit under any of them — Oath of Lim-Dûl's is under ``effect`` (a
#: ``for_each`` body), Tolarian Kraken's under ``reflexive`` (CR 603.12), Mystic
#: Remora's under ``otherwise``.
_NESTED_KEYS = (
    "steps", "then", "otherwise", "else", "action", "instruction",
    "unpaid", "reflexive", "effect", "option_effects",
)

#: The actors whose offer rebinds the resolution's ``caster`` **and** ``target``
#: to the offered seat, mirroring ``handlers/control_flow._EACH_ACTORS``.
_REBINDING_ACTORS = frozenset({"each_player", "each_opponent", "defending_player"})
#: The actors whose offer is made to a seat the ability already chose: the
#: back-reference names them, the resolution's controller does not.
_OTHER_SEAT_ACTORS = frozenset({"that_player", "target_opponent", "controller"})


def _walk(instruction):
    yield instruction
    for key in _NESTED_KEYS:
        value = instruction.payload.get(key) or ()
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            nested = item if isinstance(item, (list, tuple)) else (item,)
            for step in nested:
                if hasattr(step, "payload"):
                    yield from _walk(step)


def _program_instructions(program):
    for instruction in program.instructions:
        yield from _walk(instruction)
    for ability in program.activated_abilities:
        if ability.instruction is not None:
            yield from _walk(ability.instruction)
    for ability in program.triggered_abilities:
        if ability.instruction is not None:
            yield from _walk(ability.instruction)


def _free_offers(catalog):
    """Every free ``may`` every supported card in the pool compiles.

    "Free" as the *entry* states it: no mana cost, no life cost and no CR 118.8
    alternative. A printed cost is already answered correctly — the seat spends
    what is floating and taps nothing — and this is the half nobody chose.
    """
    seen = set()
    for card in sorted(catalog, key=lambda c: c.name):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for instruction in _program_instructions(program):
            if instruction.kind != "may":
                continue
            payload = instruction.payload
            if (
                payload.get("cost")
                or payload.get("life_cost")
                or payload.get("cost_alternatives")
            ):
                continue
            action = tuple(payload.get("action") or ())
            then = tuple(payload.get("then") or ())
            otherwise = tuple(payload.get("otherwise") or ())
            key = (
                card.name,
                tuple(step.kind for step in action),
                tuple(step.kind for step in then),
                tuple(step.kind for step in otherwise),
            )
            if key in seen:
                continue
            seen.add(key)
            yield card, payload, action + then, otherwise


def _decision(accept_steps, otherwise, actor: str) -> str:
    """The engine's own answer, through the method the default calls.

    The entry is built the way ``handlers/control_flow._offer_to_seat`` builds
    it — accept branch as ``action`` then ``then``, decline branch as
    ``otherwise`` — because that convention is what the default reads, and a
    test that rebuilt it differently would stop noticing if the handler changed
    its mind.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    seat = game.players[0]
    other = game.players[1]

    class _Context:
        caster = seat if actor not in _OTHER_SEAT_ACTORS else other
        target = seat if actor != "you" else other

    entry = {
        "card_name": "probe",
        "cost": {},
        "life_cost": 0,
        "_on_accept": tuple(accept_steps),
        "_on_decline": tuple(otherwise),
        "_context": _Context(),
    }
    choice = PendingChoice("optional_pay", 0, entry)
    return "decline" if game._offer_is_an_unpriced_trade(choice) else "accept"


def _expected(accept_steps, otherwise, actor: str) -> str:
    """The same answer re-derived from the printed shape, in the terms the
    policy is stated in — a price with no penalty is refused, everything else
    is taken."""
    if otherwise:
        return "accept"
    recipients = {"caster"}
    if actor in _REBINDING_ACTORS:
        recipients |= {"target", "target_player"}
    elif actor in _OTHER_SEAT_ACTORS:
        recipients = {"target", "target_player"}
    return "decline" if offered_action_is_a_payment(accept_steps, recipients) else "accept"


def test_every_self_payment_kind_is_a_live_instruction_kind():
    """``MANA_ABILITY_KINDS``' guard, for the same reason it exists: the set it
    replaced named two kinds that had both been renamed out from under it, so
    the check it guarded silently stopped firing. A rename that emptied
    ``SELF_PAYMENT_KINDS`` would silently restore the always-accept default —
    no error, no missing behaviour, just a seat paying every price again."""
    missing = sorted(SELF_PAYMENT_KINDS - set(EFFECT_HANDLERS))
    assert not missing, missing


def test_every_self_payment_kind_is_still_printed_by_the_pool():
    """Both directions, the way ``test_effect_labels`` holds its tables: a kind
    nothing in the pool offers is a claim about a card that is not there, and a
    frozen list nothing checks rots into a description of a pool that has moved
    on. Prune for cause, not by guesswork.

    **Both manifest roles**, unlike the shape guard below. This one asks whether
    any card in the game prints the offer, and the compiler reads a `measured`
    set exactly as it reads a shipped one — so a kind added for a card that has
    not been promoted yet is a claim about a card that *is* there. The other
    direction is the one that costs: a new offered-action kind is **free** until
    somebody lists it here, and the failure is silent (the price is lowered into
    the offered action, where the affordability test cannot find it), so a
    guard that made a group wait for promotion before listing one would be a
    guard arguing for the bug. Scoping by the shipped half alone is right for a
    ratchet and wrong for a completeness check.
    """
    from engine.card_loader import load_cards, manifest_set_paths

    everything = load_cards(manifest_set_paths(include_measured=True))
    offered = set()
    for _card, _payload, accept, _otherwise in _free_offers(everything):
        for step in accept:
            offered.add(step.kind)
            for mode in step.payload.get("modes") or ():
                if isinstance(mode, dict) and mode.get("instruction") is not None:
                    offered.add(mode["instruction"].kind)
    unreached = sorted(SELF_PAYMENT_KINDS - offered)
    assert not unreached, unreached


def test_the_pools_free_offers_are_decided_by_shape_and_nothing_else(catalog):
    """The whole policy, asked of every free offer the pool compiles.

    Derived twice over: the offers come from walking the compiled programs, and
    the expected answer comes from the printed shape (is the offered deed a
    price? does refusing cost anything?). No card is named on either side, so a
    newly ingested "you may sacrifice a Forest" is covered the day it lands.
    """
    disagreements = []
    for card, payload, accept, otherwise in _free_offers(catalog):
        actor = payload.get("actor", "you")
        got = _decision(accept, otherwise, actor)
        want = _expected(accept, otherwise, actor)
        if got != want:
            disagreements.append((card.name, got, want))
    assert not disagreements, disagreements


def test_the_pool_holds_free_offers_of_both_kinds(catalog):
    """Neither half of the policy may pass vacuously. A sweep that found no
    price would agree with an always-accept default, and a sweep that found no
    gift would agree with an always-decline one — and both are what this round
    was fixing."""
    decisions = [
        _decision(accept, otherwise, payload.get("actor", "you"))
        for _card, payload, accept, otherwise in _free_offers(catalog)
    ]
    assert decisions.count("decline") >= 5, decisions
    assert decisions.count("accept") >= 20, decisions


def test_a_toll_is_still_paid_because_refusing_it_is_not_free(catalog):
    """The line the *trade* question draws, asked of the pool rather than
    asserted about one card: **no** offer with a printed "if you don't" branch
    is an unpriced trade, however expensive taking it is. Elder Spawn's Island
    is a price and so is the 6 damage and the 7/7 behind refusing it; picking
    the cheaper of two losses is a different question with its own answer —
    ``ai_policy.toll_decline_is_smaller_loss``, tested in
    ``tests/ai/test_ai_toll_valuation.py`` — and where its derivation cannot
    price a side, this default (pay tolls) is still what stands."""
    refused_tolls = [
        card.name
        for card, payload, accept, otherwise in _free_offers(catalog)
        if otherwise
        and _decision(accept, otherwise, payload.get("actor", "you")) == "decline"
    ]
    assert not refused_tolls, refused_tolls


@pytest.mark.parametrize(
    "kind, expected",
    [
        ("sacrifice_matching_permanent", True),
        ("discard_controller_cards", True),
        ("pay_life", True),
        ("ante_top_card", True),
        ("draw_controller_cards", False),
        ("search_library", False),
        ("remove_counter_from_self", False),
    ],
)
def test_the_leading_step_is_what_the_sentence_offers(kind, expected):
    """"You may **A**. If you do, B." — the grammar splits the sentence at the
    comma and ``_offer_to_seat`` concatenates ``action`` then ``then``, so A
    leads. Reading the branch as a whole would make Sylvan Library ("draw two
    additional cards … then pay 4 life or put the card back") a price and Crypt
    Lurker ("sacrifice a creature … draw a card") a gift, which is both answers
    exactly backwards.

    ``remove_counter_from_self`` is the deliberate exclusion: Living Artifact's
    counters are not an object anybody owns (CR 122.1), so trading one for a
    life is the card working rather than a price being paid.
    """
    from engine.oracle_types import OracleInstruction

    steps = (
        OracleInstruction(kind, "", {}),
        OracleInstruction("draw_controller_cards", "", {"amount": 1}),
    )
    assert offered_action_is_a_payment(steps, {"caster"}) is expected


# ---------------------------------------------------------------------------
# The same policy one layer in: a "Choose one —" whose alternatives are not
# alike. ``_default_mode_choice`` took printed order, which is a fine policy
# while the modes are two ways of doing the same size of thing and a bad one
# the moment a price is printed beside a free alternative.
# ---------------------------------------------------------------------------


def _modal_choices(catalog):
    """Every ``choose_one`` the pool compiles, with its modes' instructions."""
    seen = set()
    for card in sorted(catalog, key=lambda c: c.name):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for instruction in _program_instructions(program):
            if instruction.kind != "choose_one":
                continue
            modes = [
                mode for mode in (instruction.payload.get("modes") or ())
                if isinstance(mode, dict) and mode.get("instruction") is not None
            ]
            if not modes:
                continue
            key = (card.name, tuple(mode["label"] for mode in modes))
            if key in seen:
                continue
            seen.add(key)
            yield card, modes


def _mode_taken(modes) -> int:
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])

    class _Context:
        caster = game.players[0]
        target = game.players[1]

    choice = PendingChoice("mode_choice", 0, {
        "card_name": "probe",
        "labels": [mode["label"] for mode in modes],
        "_modes": tuple(mode["instruction"] for mode in modes),
        "_context": _Context(),
    })
    return game._first_unpriced_mode(choice)


def test_a_modal_choice_prefers_an_alternative_that_costs_the_chooser_nothing(catalog):
    """Asked of every modal choice in the pool, by shape: the first alternative
    that is not paid out of the chooser's own resources, and printed order when
    every one of them is (Crypt Lurker's "sacrifice a creature or discard a
    creature card" — two prices, and picking the smaller is valuation)."""
    wrong = []
    for card, modes in _modal_choices(catalog):
        priced = [
            offered_action_is_a_payment((mode["instruction"],), {"caster"})
            for mode in modes
        ]
        want = next((i for i, p in enumerate(priced) if not p), 0)
        got = _mode_taken(modes)
        if got != want:
            wrong.append((card.name, got, want))
    assert not wrong, wrong


def test_the_pool_still_contains_a_modal_choice_that_is_not_uniform(catalog):
    """The guard above passes vacuously if every modal in the pool offers two
    alternatives of the same kind. Exactly one does not, which is why printed
    order survived this long."""
    mixed = [
        card.name
        for card, modes in _modal_choices(catalog)
        if len({
            offered_action_is_a_payment((mode["instruction"],), {"caster"})
            for mode in modes
        }) > 1
    ]
    assert mixed, "no modal choice mixes a price with a free alternative"


# --- EXO W1G2: an offer nobody could take is not made, and its rider does not
# fire ---
#
# SET_PLAYBOOK.md's Known gaps carried this for two sets as "``control_flow.may``
# runs its ``then`` branch whenever the offer is accepted, whether or not the
# action did anything", wanting "a decision about what 'did anything' means per
# instruction kind, which is a registry question rather than a branch".
#
# **The registry already existed.** ``_action_is_takeable`` is exactly that
# table, and it asks the question one step *earlier* and better: CR 601.2 offers
# a choice, an action nobody could take is not among the things offered, so the
# offer is never made and the rider never runs. What was missing was rows.
#
# Measured rather than guessed: of the instruction kinds that appear as a
# ``may``'s action with a ``then`` behind it across both manifest roles, all but
# two either always do something (a coin flip, a life gain, a reveal), legally
# do nothing (Tetravus' "any number of", Scroll Rack's), or are *targeted* and
# so already refused at CR 601.2c / 608.2b. Those two are the ones whose
# emptiness is real, silent, and in the player's favour.

from engine.game_types import OracleExecutionContext as _G2Ctx
from engine.models import Permanent


def _g2_offer_duel():
    """Two seats with costs off. Its own name and its own last line."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, game.players[0], game.players[1]


def _g2_bone_dancer_turn(catalog_by_name, victim_graveyard):
    """Bone Dancer's trigger resolved against a defending graveyard holding
    *victim_graveyard*, and the permanent it acted on."""
    from engine.handlers.control_flow import may

    game, _alice, bob = _g2_offer_duel()
    card = catalog_by_name["Bone Dancer"]
    dancer = Permanent(card=card)
    dancer.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(dancer)
    game._sync_control()
    bob.graveyard.extend(victim_graveyard)

    program = compile_card_oracle(card)
    context = _G2Ctx(
        card=card, caster=game.players[0], target=bob, source_permanent=dancer,
    )
    context.trigger_context = {"trigger_defending_player_index": 1}
    may(game, program.triggered_abilities[0].instruction, context)
    game.auto_resolve_pending_choices()
    return game, dancer


def test_bone_dancer_assigns_damage_when_the_graveyard_had_nothing(catalog_by_name):
    """The Known-gaps entry's own card, reproduced and closed.

    "You may put the top creature card of defending player's graveyard onto the
    battlefield under your control. **If you do**, this creature assigns no
    combat damage this turn." Over a graveyard with no creature card in it,
    accepting reanimated nothing and the attacker still gave up its damage —
    and ``reanimate_graveyard_position``'s own docstring claimed the opposite,
    which is how the defect survived: the assertion was written down and never
    held.
    """
    game, dancer = _g2_bone_dancer_turn(
        catalog_by_name, [catalog_by_name["Giant Growth"]]
    )
    assert "assigns_no_combat_damage_until_eot" not in dancer.metadata
    # And the offer was never *made*, which is the shape of the fix: the
    # withdrawal happens ahead of the prompt, so the handler that would have
    # logged "nothing Bone Dancer can return" is never reached either.
    assert not game.pending_choices
    assert [p.card.name for p in game.controlled_by(game.players[0])] == [
        "Bone Dancer",
    ]


def test_bone_dancer_still_gives_up_its_damage_for_a_real_creature(catalog_by_name):
    """The other direction, which is the one a wrongly-False answer would
    break: the offer is still made when the pile has a creature card, and
    taking it still costs the attacker its combat damage."""
    game, dancer = _g2_bone_dancer_turn(
        catalog_by_name, [catalog_by_name["Grizzly Bears"]]
    )
    assert dancer.metadata.get("assigns_no_combat_damage_until_eot")
    assert sorted(
        p.card.name for p in game.controlled_by(game.players[0])
    ) == ["Bone Dancer", "Grizzly Bears"]


def test_duplicity_does_not_refill_from_an_empty_hand(catalog_by_name):
    """"You may exile all cards from your hand face down. **If you do**, put
    all other cards you own exiled with this enchantment into your hand."
    (Duplicity.) The trade *is* the card, so an empty hand paying nothing and
    taking the whole pile back is Bone Dancer's failure with the reward on the
    other side of it."""
    from engine.handlers.control_flow import may

    game, alice, _bob = _g2_offer_duel()
    card = catalog_by_name["Duplicity"]
    enchantment = Permanent(card=card)
    game.players[0].battlefield.append(enchantment)
    game._sync_control()
    program = compile_card_oracle(card)
    entry = next(
        t for t in program.triggered_abilities
        if t.condition is not None and t.condition.kind == "enters_battlefield"
    )
    upkeep = next(
        t for t in program.triggered_abilities
        if t.condition is not None and t.condition.kind == "upkeep_self"
    )
    context = _G2Ctx(
        card=card, caster=alice, target=alice, source_permanent=enchantment,
    )
    alice.library.extend([catalog_by_name["Grizzly Bears"]] * 5)
    game._execute_oracle_instruction(entry.instruction, context)
    assert alice.hand == []
    assert alice.library == []

    may(game, upkeep.instruction, context)
    game.auto_resolve_pending_choices()

    assert alice.hand == []


def test_every_offer_with_a_rider_names_a_reviewed_action_kind(catalog):
    """The property, over the whole pool rather than over two cards: no
    ``may`` carrying a ``then`` may name an action kind nobody has read. Most
    new ones will be fine — they always do something — but the list is what
    makes "we decided about each one" a fact rather than a memory, so a new
    kind fails here and is read before it is added.
    """
    reviewed = {
        # Always does something, or legally does nothing and the rider is right
        # to fire: a flip, a life gain, a reveal, a mana ability, an "any number
        # of" pick whose zero is an answer.
        "activate_each_lands_mana_ability", "assign_no_combat_damage_until_eot",
        "choose_one", "draw_controller_cards", "exile_any_number_of_own_tokens",
        "flip_coin", "grant_self_ability_text", "lose_all_unspent_mana",
        "put_cards_from_hand_onto_battlefield",
        "remove_any_number_of_counters_from_self", "reveal_hand",
        "reveal_hand_while_source_present", "target_gains_life",
        # Targeted, so an empty case is already refused at announcement
        # (CR 601.2c) or at resolution (CR 608.2b).
        "bounce_target_creature", "deal_damage", "destroy_target_permanent",
        "exile_cards_from_graveyard", "gain_control_of_target",
        "source_bites_target", "steal_target_linked_to_source",
        "untap_target_permanent",
        # Empty, and the rider behind it is itself a no-op — the same shape as
        # the two rows this round added, with nothing at stake. Ice Cauldron
        # grants permission over an empty pile; Flash offers a cost computed
        # from a permanent nothing recorded and then sacrifices nothing.
        #
        # Sneak Attack (USG) is the third card behind the put-from-hand row and
        # the first whose rider is not obviously nothing: "That creature gains
        # haste. Sacrifice the creature at the beginning of the next end step."
        # Both halves read the permanent that step recorded, and with an empty
        # record the grant finds nothing to grant to and
        # ``create_delayed_trigger`` arms **nothing** rather than binding a
        # bystander — so the row still holds, and it holds because it was
        # re-checked rather than because it was already written down.
        # `tests/sets/test_usg_enchantments.py` is where that is a game.
        "exile_chosen_card_from_hand",
        "put_chosen_card_from_hand_onto_battlefield",
        # Answered by `_action_is_takeable`, so the offer is withdrawn.
        "ante_top_card", "choose_permanent", "choose_permanents",
        "discard_controller_cards", "discard_target_cards",
        "discard_x_target_cards", "exile_graveyard_position",
        "exile_hand_pile", "pay_life", "put_hand_cards_on_library",
        "reanimate_graveyard_position", "remove_counter_from_self",
        "return_creature_from_graveyard_to_hand", "sacrifice_attached_permanent",
        "sacrifice_matching_permanent", "sacrifice_permanents_totalling",
        "sacrifice_self",
    }
    found: set[str] = set()
    for card in catalog:
        for instruction in _program_instructions(compile_card_oracle(card)):
            payload = instruction.payload or {}
            if instruction.kind != "may" or not payload.get("then"):
                continue
            found.update(step.kind for step in (payload.get("action") or ()))
    assert not found - reviewed, sorted(found - reviewed)

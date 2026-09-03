"""Per-card tests for Alliances' instants.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G4: alternative and repeated costs ---
#
# CR 118.9 alternative costs ("rather than pay this spell's mana cost"), the
# Alliances pitch cycle, plus the narrowed additional-cost discard beside it.
# The rules-level assertions live in ``tests/rules/test_alternative_costs.py``;
# what is here is per card. Every decline below names the *part* that is
# missing rather than calling the card complex — the missing part is usually
# another group's round, and the card falls out for free when it lands.

import pytest

from engine import Game, PlayerState, load_cards
from engine.alternative_costs import alternative_costs
from engine.card_loader import manifest_set_path
from engine.cast_costs import additional_costs
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W1G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w1g4_duel(hand: list) -> tuple[Game, PlayerState]:
    """A costs-enforced duel holding *hand*. Alliances is measured, so its cards
    are placed into the game directly rather than decked."""
    caster = PlayerState(name="A", hand=list(hand))
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = True
    return game, caster


def _w1g4_spell_to_counter(game: Game) -> None:
    game.players[1].hand.append(_W1G4_LEA["Lightning Bolt"])
    game.enforce_mana_costs = False
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.enforce_mana_costs = True


def test_force_of_will_counters_a_spell_for_a_life_and_a_blue_card(set_pool):
    """The card the whole cycle is named for. {3}{U}{U} on the card, and cast
    here with no lands at all — which is the behaviour it reported ``supported``
    without having, on the strength of its second line alone."""
    force = set_pool("ALL")["Force of Will"]
    game, caster = _w1g4_duel([force, _W1G4_LEA["Counterspell"]])
    _w1g4_spell_to_counter(game)

    result = game.cast_from_hand(0, "Force of Will", alternative_cost=True)

    assert result.supported, result.details
    assert caster.life == 19
    assert [c.name for c in caster.exile] == ["Counterspell"]
    assert not game.stack


def test_pyrokinesis_pitches_a_red_card_and_costs_no_life(set_pool):
    """The same cycle without the life clause — so a clause dropped from either
    card would show up as the two behaving identically."""
    pyro = set_pool("ALL")["Pyrokinesis"]
    game, caster = _w1g4_duel([pyro, _W1G4_LEA["Lightning Bolt"]])
    game.players[1].battlefield.append(Permanent(card=_W1G4_LEA["Grizzly Bears"]))

    result = game.cast_from_hand(
        0, "Pyrokinesis", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )

    assert result.supported, result.details
    assert caster.life == 20, "Pyrokinesis prints no life clause"
    assert [c.name for c in caster.exile] == ["Lightning Bolt"]


@pytest.mark.parametrize(
    "name, color, life",
    [
        ("Force of Will", "U", 1),
        ("Pyrokinesis", "R", 0),
        ("Scars of the Veteran", "W", 0),
        ("Bounty of the Hunt", "G", 0),
        ("Contagion", "B", 1),
    ],
)
def test_the_alliances_pitch_cycle_is_one_template_not_five_cards(
    set_pool, name, color, life
):
    """Five printings of one sentence with one colour changed, which is what
    makes it a table rather than five name-keyed hooks. Read off the *cost*
    rather than the text, so a card whose clause stopped being charged shows up
    here even while its sentence still reads correctly.

    Two of these five are unsupported for reasons that have nothing to do with
    the cost (see the declines below); the cost is still read, because a price
    is not an effect and the card's other half is not this half's business."""
    (cost,) = alternative_costs(set_pool("ALL")[name])
    assert cost.pay_life == life
    assert cost.exile_from_hand == ({"color_filter": color},)


def test_surge_of_strength_discards_a_red_or_green_card_to_be_cast(set_pool):
    """"As an additional cost to cast this spell, discard a **red or green**
    card." The narrowing is a shared-head disjunction, which the cost table read
    as nothing — so the card compiled ``supported``, was cast, and discarded
    nothing at all."""
    surge = set_pool("ALL")["Surge of Strength"]
    (cost,) = additional_costs(surge)
    assert cost.discard_cards == 1
    assert cost.discard_filters == ({"any_colors": ["R", "G"]},)

    game, caster = _w1g4_duel(
        [surge, _W1G4_LEA["Island"], _W1G4_LEA["Grizzly Bears"]]
    )
    game.enforce_mana_costs = False
    caster.battlefield.append(Permanent(card=_W1G4_LEA["Grizzly Bears"]))

    result = game.cast_from_hand(0, "Surge of Strength", target_permanent_index=0)

    assert result.supported, result.details
    # The green card paid; the Island — colourless, CR 202.2 — did not.
    assert [c.name for c in caster.hand] == ["Island"]
    assert "Grizzly Bears" in [c.name for c in caster.graveyard]


# --- W1G4 declines, each naming the part it is waiting on -------------------
#
# These assert the card is *still* unsupported. That is deliberate: a decline
# whose missing part later lands should fail loudly here rather than sit
# unnoticed, and the message says what to do about it.


def test_bounty_of_the_hunt_no_longer_declines_on_its_counter_loop(set_pool):
    """Was the decline. W2G2 landed part 1 (the enumerated bound) and **W3G1**
    landed parts 2 and 3: "for each +1/+1 counter you put on a creature this
    way" is its own iterator over a record the distributed placement now writes,
    and "remove a +1/+1 counter from that creature" is the counted twin of the
    bound removal Giant Oyster already had. The behavioural tests are in the
    W3G1 block at the bottom of this file; what this keeps is the pairing the
    decline named — the pitch cost and the effect, both read, on one card."""
    program = compile_card_oracle(set_pool("ALL")["Bounty of the Hunt"])
    assert program.supported
    assert alternative_costs(set_pool("ALL")["Bounty of the Hunt"])


def test_contagion_no_longer_declines_on_the_bounded_target_count(set_pool):
    """Was the decline. W2G2 landed the enumerated "among" form and the bound
    that CR 601.2c fixes at announcement, and this card needed nothing else —
    its pitch half was already done here. The cast-both-ways assertions are in
    the W2G2 block below; what this keeps is the pairing the decline named:
    the alternative cost and the effect are both read, on the same card."""
    program = compile_card_oracle(set_pool("ALL")["Contagion"])
    assert program.supported
    assert alternative_costs(set_pool("ALL")["Contagion"])


def test_undergrowth_no_longer_declines_on_its_optional_mana_cost(set_pool):
    """Was the decline, and both named parts landed in W3G1: an optional mana
    clause in ``cast_costs._COST_CLAUSES`` with the count carried to resolution,
    and a prevention that can be narrowed by the damage's source. What this
    keeps is the pairing — the cost is read *and* the effect reads it back, on
    one card. The behaviour is in the W3G1 block at the bottom of this file and
    in ``tests/rules/test_optional_additional_costs.py``."""
    assert compile_card_oracle(set_pool("ALL")["Undergrowth"]).supported
    (cost,) = additional_costs(set_pool("ALL")["Undergrowth"])
    assert [(o.symbols, o.repeatable) for o in cost.optional_mana] == [
        ("{2}{R}", False)
    ], "printed without 'any number of times', so it may be taken once"


# --- W1G5: delayed triggers ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.game_types import StackItem
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w1g5_lea(name: str):
    """One Limited Edition Alpha card, for the boards these tests need.

    Alliances is `measured`, so its own basics and vanilla creatures are the
    only ones its file carries and several of these boards want neither. Loaded
    through the manifest like every other set here.
    """
    for card in load_cards(manifest_set_path("LEA", include_measured=True)):
        if card.name == name:
            return card
    raise AssertionError(f"{name} is not in LEA")


def _w1g5_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def test_w1g5_arcane_denial_counters_the_spell_it_targets(set_pool):
    """The counter is the card's first sentence and it was not compiled at all.

    Arcane Denial reported **supported** on the strength of its second line's
    delayed draw plus two whitelist substrings, with "Counter target spell"
    reaching no instruction — a supported counterspell that countered nothing.
    """
    denial = set_pool("ALL")["Arcane Denial"]
    kinds = [instruction.kind for instruction in compile_card_oracle(denial).instructions]
    assert "sequence" in kinds
    steps = next(
        instruction for instruction in compile_card_oracle(denial).instructions
        if instruction.kind == "sequence"
    ).payload["steps"]
    assert [step.kind for step in steps] == [
        "counter_top_stack_spell", "create_delayed_trigger",
    ]


def test_w1g5_arcane_denial_offers_a_spell_picker(set_pool):
    """The Roots class: text names a choice and the derivation offers no picker,
    so the client sends a bare cast and the spell resolves against nothing."""
    from engine.targeting import derive_cast_spec

    denial = set_pool("ALL")["Arcane Denial"]
    spec = derive_cast_spec(denial, compile_card_oracle(denial))
    assert spec is not None and spec.get("kind") == "stack"


def test_w1g5_arcane_denial_lets_the_countered_spells_controller_draw(set_pool):
    """CR 603.7 end to end: counter now, and the *other* player is offered two
    cards at the next turn's upkeep.

    The seat is the whole point. By the time the delayed ability fires the
    countered spell is a card in a graveyard, and CR 108.4 gives that card no
    controller — so the seat has to have been written down as the counter
    happened.
    """
    denial = set_pool("ALL")["Arcane Denial"]
    game, p1, p2 = _w1g5_duel()
    game.interactive_seats = {1}
    victim = _w1g5_lea("Giant Growth")
    game.stack.append(StackItem(
        card=victim, caster_index=1, target_player_index=None,
        target_permanent_index=None, x_value=None,
    ))

    game._apply_spell_text(p1, p2, denial, stack_target=game.stack[-1])
    game._settle()
    assert game.stack == []
    assert any(card is victim for card in p2.graveyard)

    # Nothing yet — the draw waits for the next turn's upkeep, whoever's it is.
    assert p2.hand == []
    p2.library.extend([_w1g5_lea("Mountain")] * 4)
    game.active_player_index = 1
    game.resolve_upkeep(1)
    game._settle()
    assert game.confirm_draw_up_to(1, 2)
    assert len(p2.hand) == 2


def test_w1g5_death_spark_returns_itself_from_the_graveyard(set_pool):
    """CR 113.6b: the intervening-if is where this card says it functions from a
    graveyard, and the upkeep step had no graveyard scan at all."""
    pool = set_pool("ALL")
    spark = pool["Death Spark"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.battlefield.append(Permanent(card=_w1g5_lea("Mountain")))
    game._sync_control()
    p1.graveyard.extend([spark, _w1g5_lea("Grizzly Bears")])

    game.resolve_upkeep(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Death Spark", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Death Spark"]
    assert p1.graveyard == [_w1g5_lea("Grizzly Bears")]


def test_w1g5_death_spark_stays_put_with_a_land_directly_above_it(set_pool):
    """"**Directly** above" is a different question from a count of one: a
    creature card above with a land between them satisfies neither."""
    pool = set_pool("ALL")
    spark = pool["Death Spark"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.battlefield.append(Permanent(card=_w1g5_lea("Mountain")))
    game._sync_control()
    p1.graveyard.extend(
        [spark, _w1g5_lea("Grizzly Bears"), _w1g5_lea("Forest")]
    )

    game.resolve_upkeep(0)
    game._settle()

    assert p1.hand == []
    assert p1.graveyard[0] is spark


def test_w1g5_reinforcements_moves_chosen_creature_cards_to_the_library_top(set_pool):
    """"Up to three target creature cards from **your** graveyard on top of
    **your** library" — the seat is the caster's on both halves, where Drafna's
    Restoration's is the target player's on both."""
    reinforcements = set_pool("ALL")["Reinforcements"]
    game, p1, p2 = _w1g5_duel()
    bear = _w1g5_lea("Grizzly Bears")
    ogre = _w1g5_lea("Hurloon Minotaur")
    p1.graveyard.extend([bear, _w1g5_lea("Forest"), ogre])

    game._apply_spell_text(p1, p2, reinforcements, target_permanent_index=[0, 2])
    game._settle()

    assert [card.name for card in p1.library[:2]] == ["Grizzly Bears", "Hurloon Minotaur"]
    assert [card.name for card in p1.graveyard] == ["Forest"]


def test_w1g5_reinforcements_offers_only_its_own_graveyard(set_pool):
    """The picker is scoped to the caster's pile. Left unscoped it would offer
    the opponent's creature cards, and the handler — which indexes the caster's
    graveyard — would then move whatever card sat at that slot."""
    from engine.targeting import derive_cast_spec

    reinforcements = set_pool("ALL")["Reinforcements"]
    spec = derive_cast_spec(reinforcements, compile_card_oracle(reinforcements))
    assert spec is not None
    assert spec.get("own_graveyard_only") is True
    assert spec.get("count") == 3


def test_w1g5_lat_nams_legacy_shuffles_a_chosen_card_and_cantrips_next_upkeep(set_pool):
    """Three things in one sentence, and the middle one is the hard one: the
    shuffle *suspends* the resolution on a prompt (CR 402.1 — only the hand's
    owner may look), so the "if you do" behind it has to run after the answer
    rather than before it."""
    legacy = set_pool("ALL")["Lat-Nam's Legacy"]
    game, p1, p2 = _w1g5_duel()
    game.interactive_seats = {0}
    bear = _w1g5_lea("Grizzly Bears")
    forest = _w1g5_lea("Forest")
    p1.hand.extend([bear, forest])
    p1.library.extend([forest] * 6)

    game._apply_spell_text(p1, p2, legacy)
    game._settle()
    assert [c.kind for c in game.pending_choices] == ["hand_to_library"]

    assert game.confirm_hand_to_library(0, [0])
    game._settle()
    assert [card.name for card in p1.hand] == ["Forest"]
    assert len(p1.library) == 7

    # The draw waits: "at the beginning of the next turn's upkeep" is whichever
    # upkeep comes next, so it lands on the opponent's turn.
    assert [t.event for t in game.delayed_triggers] == ["next_turns_upkeep"]
    game.active_player_index = 1
    game.resolve_upkeep(1)
    game._settle()
    assert len(p1.hand) == 3


def test_w1g5_lat_nams_legacy_draws_nothing_from_an_empty_hand(set_pool):
    """"If you do" reads what the step really moved. CR 608.2 does as much as it
    can, and with no card to shuffle the sentence did not happen — so the
    delayed ability is never created at all."""
    legacy = set_pool("ALL")["Lat-Nam's Legacy"]
    game, p1, p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.library.extend([_w1g5_lea("Forest")] * 6)

    game._apply_spell_text(p1, p2, legacy)
    game._settle()

    assert game.pending_choices == []
    assert game.delayed_triggers == []


# --- W2G2: costs ---
#
# The bounded distributed target count (CR 601.2c) — the part W1G4 named as
# unowned and cheapest — plus the cards the other cost work unblocked. Imports
# are in this block, per the header's parallel-authorship convention.

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.divided_damage import division_refusal
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W2G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g2_board(hand, mine=(), theirs=()):
    """A costs-enforced duel with named LEA creatures on each battlefield.

    Alliances is `measured`, so its cards are placed into the game directly
    rather than decked.
    """
    caster = PlayerState(name="A", hand=list(hand))
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = True
    for name in mine:
        caster.battlefield.append(Permanent(card=_W2G2_LEA[name]))
    for name in theirs:
        game.players[1].battlefield.append(Permanent(card=_W2G2_LEA[name]))
    game._settle()
    return game, caster


def test_contagion_pitched_puts_its_counters_on_two_creatures(set_pool):
    """The whole card, cast the way it is famous for: no lands at all, 1 life
    and a black card out of hand, and two -2/-1 counters split one and one.

    Both halves are asserted because both were missing until this wave — the
    pitch was W1G4's and the distribution is this one's, and a card is not
    "supported" until the sentence *and* the price have been watched running.
    """
    contagion = set_pool("ALL")["Contagion"]
    game, caster = _w2g2_board(
        [contagion, _W2G2_LEA["Bog Wraith"]], theirs=["Grizzly Bears", "Hill Giant"]
    )
    bears, giant = game.players[1].battlefield

    result = game.cast_from_hand(
        0, "Contagion", alternative_cost=True,
        divided_targets=[(1, 0, 1), (1, 1, 1)],
    )
    game._settle()

    assert result.supported, result.details
    assert caster.life == 19, "pay 1 life"
    assert [c.name for c in caster.exile] == ["Bog Wraith"], "exile a black card"
    # One counter each, not both on one: 2/2 becomes 0/1 and 3/3 becomes 1/2.
    # The Bears at 0 power is exactly why the split has to be *read* — a
    # handler that put both counters on the first target would kill them.
    assert (bears.effective_power, bears.effective_toughness) == (0, 1)
    assert (giant.effective_power, giant.effective_toughness) == (1, 2)
    assert [p.card.name for p in game.controlled_by(1)] == [
        "Grizzly Bears", "Hill Giant"
    ]


def test_contagion_may_put_both_counters_on_one_creature(set_pool):
    """"among **one** or two": the lower end of the enumeration is a legal
    announcement, and the whole distribution then lands on the one target."""
    contagion = set_pool("ALL")["Contagion"]
    game, _caster = _w2g2_board(
        [contagion, _W2G2_LEA["Bog Wraith"]], theirs=["Hill Giant"]
    )
    giant = game.players[1].battlefield[0]

    result = game.cast_from_hand(
        0, "Contagion", alternative_cost=True, divided_targets=[(1, 0, 2)],
    )
    game._settle()

    assert result.supported, result.details
    assert (giant.effective_power, giant.effective_toughness) == (-1, 1)


@pytest.mark.parametrize(
    "named, why",
    [
        (3, "Contagion prints 'one or two' and three is past its ceiling"),
        (4, "and a longer list is refused by the same ceiling"),
    ],
)
def test_contagion_refuses_more_targets_than_it_prints(set_pool, named, why):
    """CR 601.2c fixes the number of targets **at announcement**, so this is a
    refusal with nothing spent rather than an effect that quietly divides three
    ways. Read off the life total: the alternative cost is paid at CR 601.2h,
    after the targets are checked, so a refusal that came too late would show up
    here as a life payment for a spell that was never cast."""
    contagion = set_pool("ALL")["Contagion"]
    game, caster = _w2g2_board(
        [contagion, _W2G2_LEA["Bog Wraith"]],
        theirs=["Grizzly Bears"] * named,
    )

    result = game.cast_from_hand(
        0, "Contagion", alternative_cost=True,
        divided_targets=[(1, i, 1) for i in range(named)],
    )

    assert not result.supported, why
    assert caster.life == 20, "nothing is paid for a refused announcement"
    assert not caster.exile
    assert not game.stack


def test_the_bound_is_checked_before_the_division_is(set_pool):
    """The ceiling is CR 601.2c and the shares are CR 601.2d, and the order
    matters: a seat that announced **no** shares still may not name three
    targets. Asked of the rule directly, because the even-split fallback that
    excuses an absent division is exactly what would excuse an over-long list.
    """
    over_long = [(0, 0), (0, 1), (0, 2)]
    assert division_refusal(2, over_long, division="chosen", max_targets=2)
    assert division_refusal(2, over_long, division="chosen") is None
    assert division_refusal(
        2, [(0, 0), (0, 1)], division="chosen", max_targets=2
    ) is None


def test_the_unbounded_spelling_is_not_a_ceiling_of_infinity(set_pool):
    """"among **any number of** target creatures" (Spoils of War) prints no
    ceiling at all, and the description must carry no key rather than a large
    one — an absent key is what every reader written before the bound existed
    already means."""
    bounded = compile_card_oracle(set_pool("ALL")["Contagion"])
    (described,) = [
        i.payload["targets"] for i in bounded.instructions
        if isinstance(i.payload.get("targets"), dict)
    ]
    assert described["max_targets"] == 2

    from engine.grammar import compile_line

    unbounded = compile_line(
        "Distribute two -2/-1 counters among any number of target creatures.",
        card_name="Test",
    )
    assert "max_targets" not in unbounded.instructions[0].payload["targets"]


# --- W2G4: library and modal ---
"""Misinformation: an instant that reaches into a graveyard nobody targeted.

"an opponent's graveyard" chooses no player — CR 601.2c chooses the *cards*, and
CR 404.1 puts a card in the graveyard of the player who owns it, so the pile and
the seat are one answer. What the printed words add is a restriction on which
piles may be reached, and left unscoped the picker would offer the caster their
own graveyard: a strictly better card than the one printed.
"""

from engine import Game, PlayerState
from engine.game_types import CardDefinition


def _w2g4_gy_card(name: str, type_line: str = "Artifact") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _w2g4_misinformation(set_pool, *, mine=(), theirs=()):
    p1 = PlayerState(
        name="P1", hand=[set_pool("ALL")["Misinformation"]],
        graveyard=list(mine), library=[_w2g4_gy_card("Deck")] * 3,
    )
    p2 = PlayerState(
        name="P2", graveyard=list(theirs), library=[_w2g4_gy_card("Their Deck")] * 3,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_w2g4_misinformation_never_offers_the_casters_own_graveyard(set_pool):
    """CR 115.4's own-seat exclusion, applied to the pile the cards are chosen
    from rather than to a chosen player."""
    game, _p1, _p2 = _w2g4_misinformation(
        set_pool,
        mine=[_w2g4_gy_card("My Relic")],
        theirs=[_w2g4_gy_card("Their Relic")],
    )

    offered = game.cast_target_spec(0, set_pool("ALL")["Misinformation"])["valid_targets"]

    assert [(t["seat"], t["name"]) for t in offered] == [(1, "Their Relic")]


def test_w2g4_misinformation_offers_every_card_type(set_pool):
    """"up to three target **cards**" — a head noun with no card type is not the
    absence of a narrowing but a narrowing that says "any card"."""
    game, _p1, _p2 = _w2g4_misinformation(
        set_pool,
        theirs=[
            _w2g4_gy_card("Bear", "Creature — Bear"),
            _w2g4_gy_card("Relic"),
            _w2g4_gy_card("Wastes", "Land"),
        ],
    )

    offered = game.cast_target_spec(0, set_pool("ALL")["Misinformation"])["valid_targets"]

    assert [t["name"] for t in offered] == ["Bear", "Relic", "Wastes"]


def test_w2g4_misinformation_stacks_them_in_the_order_they_were_named(set_pool):
    """"…in any order." Nothing else on the wire could carry an ordering, so the
    order the targets were chosen in (CR 601.2c) is the controller's choice of
    order — first named, top of the library."""
    game, _p1, p2 = _w2g4_misinformation(
        set_pool,
        theirs=[
            _w2g4_gy_card("First"), _w2g4_gy_card("Untouched"), _w2g4_gy_card("Second"),
        ],
    )

    game._apply_spell_text(
        game.players[0], p2, set_pool("ALL")["Misinformation"],
        target_permanent_index=[2, 0],
    )
    game._settle()

    assert [c.name for c in p2.library[:2]] == ["Second", "First"]
    assert [c.name for c in p2.graveyard] == ["Untouched"]


# --- W2G5: damage, prevention and zones ---
#
# Four instants whose refusal sites were accurate and whose gaps were each one
# reader that already read the sentence: a second damage clause that read one
# recipient where the first reads a list, a global buff that dropped a printed
# type exclusion, an "any number of" quantifier one word from "one or more",
# and a pronoun for a back-reference the amount table already read with the
# noun spelled out. The declines below name the *part* each is waiting on.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.damage_events import deal_damage
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W2G5_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_W2G5_ALL: dict = {}


def _w2g5_all(name: str):
    """One Alliances card. The set is `measured`, so its cards are placed into a
    driven game directly — no player can deck one."""
    if not _W2G5_ALL:
        _W2G5_ALL.update({
            card.name: card
            for card in load_cards(manifest_set_path("ALL", include_measured=True))
        })
    return _W2G5_ALL[name]


def _w2g5_duel() -> Game:
    """A two-seat duel with mana enforcement off (the standard rig)."""
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    return game


def _w2g5_put(game: Game, seat: int, name: str, *, ready: bool = False) -> Permanent:
    card = _W2G5_LEA.get(name) or _w2g5_all(name)
    perm = Permanent(card=card)
    if ready:
        perm.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _w2g5_damage(game, recipient, amount, source=None, combat=False) -> int:
    """One damage event through CR 120.4, reporting what survived the shields.
    Applying the result is deliberately not done here — see tests/helpers.py."""
    return deal_damage(
        game,
        {"recipient": recipient, "amount": amount, "source": source, "combat": combat},
    ).dealt


def test_hail_storm_hits_three_described_sets_with_two_amounts(set_pool):
    """"...2 damage to each attacking creature **and** 1 damage to you **and each
    creature you control**." The second damage clause read one recipient where
    the first reads a list, so the third recipient was stranded and the whole
    line failed. All three sets, and the two amounts kept apart."""
    game = _w2g5_duel()
    game.players[0].hand.append(set_pool("ALL")["Hail Storm"])
    attacker = _w2g5_put(game, 1, "Grizzly Bears")
    attacker.attacking = True
    mine = _w2g5_put(game, 0, "Hill Giant")

    assert game.cast_from_hand(0, "Hail Storm").supported

    assert attacker.damage_marked == 2, "each attacking creature takes 2"
    assert mine.damage_marked == 1, "each creature you control takes 1"
    assert game.players[0].life == 19, "and so does its caster"
    assert game.players[1].life == 20, "the opponent is not a recipient"


def test_stench_of_decay_spares_artifact_creatures(set_pool):
    """"**Nonartifact** creatures get -1/-1." The exclusion is the whole card:
    dropped, the sweep also shrinks the caster's own artifact creatures."""
    game = _w2g5_duel()
    game.players[0].hand.append(set_pool("ALL")["Stench of Decay"])
    flesh = _w2g5_put(game, 1, "Grizzly Bears")
    metal = _w2g5_put(game, 1, "Obsianus Golem")
    before = (metal.effective_power, metal.effective_toughness)

    assert game.cast_from_hand(0, "Stench of Decay").supported

    assert (flesh.effective_power, flesh.effective_toughness) == (1, 1)
    assert (metal.effective_power, metal.effective_toughness) == before


def test_exile_gains_life_equal_to_the_toughness_it_exiled(set_pool):
    """"Exile target nonwhite attacking creature. You gain life equal to **its
    toughness**." By the second sentence the creature is a card in exile with no
    computed characteristics at all (CR 613.1), so the number is the one frozen
    where it still had one (CR 608.2h) - and it is the *effective* toughness,
    not the printed one."""
    game = _w2g5_duel()
    game.players[0].hand.append(set_pool("ALL")["Exile"])
    victim = _w2g5_put(game, 1, "Grizzly Bears")
    victim.attacking = True
    victim.toughness_bonus = 3

    assert game.cast_from_hand(
        0, "Exile", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(victim),
    ).supported

    assert [card.name for card in game.players[1].exile] == ["Grizzly Bears"]
    assert game.players[0].life == 25, "2 printed toughness plus the +0/+3"


def test_exile_is_a_card_whose_own_name_is_its_verb(set_pool):
    """The lexer collapses a card's self-references to one SELF token, and this
    card's name is the verb its only sentence opens with. Collapsed, the
    sentence has a subject and no verb, and the card refuses on "unrecognized
    effect verb" - a refusal naming a word it does not print."""
    program = compile_card_oracle(set_pool("ALL")["Exile"])

    assert program.supported, program.reason
    assert [i.kind for i in program.instructions[0].payload["steps"]] == [
        "exile_target_permanent", "target_gains_life",
    ]


def test_energy_arc_untaps_any_number_and_shields_both_ends(set_pool):
    """"Untap **any number of** target creatures. Prevent all combat damage that
    would be dealt to and dealt by **those creatures** this turn." The shield
    reaches a set - the one the sentence in front of it recorded - and it is
    combat damage in both directions and nothing else."""
    game = _w2g5_duel()
    game.players[0].hand.append(set_pool("ALL")["Energy Arc"])
    first = _w2g5_put(game, 0, "Grizzly Bears")
    second = _w2g5_put(game, 0, "Wall of Wood")
    bystander = _w2g5_put(game, 1, "Hill Giant")
    first.tapped = second.tapped = True

    assert game.cast_from_hand(
        0, "Energy Arc",
        target_permanent_ids=[first.permanent_id, second.permanent_id],
    ).supported

    assert not first.tapped and not second.tapped
    assert _w2g5_damage(game, first, 3, source=bystander, combat=True) == 0
    assert _w2g5_damage(game, second, 3, source=bystander, combat=True) == 0
    assert _w2g5_damage(game, game.players[1], 2, source=first, combat=True) == 0
    assert _w2g5_damage(game, first, 3, source=bystander, combat=False) == 3, (
        "the card says combat damage"
    )
    assert _w2g5_damage(game, bystander, 3, source=first.card, combat=True) == 3, (
        "a creature the spell never named is untouched"
    )


# --- W2G5 declines, each naming the part it is waiting on -------------------
#
# Two instants this group did not implement. Each is recorded as the pieces it
# needs rather than as "too complex", because a named part is one another group
# may build incidentally - and the card then falls out for free.


# W2G5's `test_martyrdom_is_declined_naming_three_parts` stood here and is
# **deleted** by W3G2, not edited: the card landed, so its
# "assert not program.supported" is false and a decline test whose subject works
# cannot be kept in any form. All three named parts were right and all three
# were built - the trailing sentence folds into the quoted text
# (`parser._attach_granted_ability_permission`), the counted redirect reads
# CR 115.4's union and hangs its record off a seat
# (`handlers/damage.redirect_next_damage_to_source_until_eot`), and the "who
# may activate" clause is a row in `engine/activation_permissions.py` rather
# than in `activation_restrictions.py` - part 3 named the wrong file, which is
# a decline list working exactly as intended: it pointed at the question and
# the next reader corrected the address. The card's tests are in W3G2's block
# in this file.
#
# Recorded here because this is a non-append edit to another group's block, and
# the integrator's "both sides are pure appends" assertion is meant to fire on
# it.


# --- W2G3: upkeep and counters ---
#
# Scars of the Veteran's effect half. W1G4 finished its pitch cost and declined
# the rest as "a delayed triggered ability that reads back how much a CR 615
# shield absorbed"; the shield's own running total (``Shield.prevented``) and
# the end-step reader were both already there for Sacred Boon, so what was
# missing was the two spellings this card prints instead - "on **it**" for
# Sacred Boon's "that creature", and the "if it's a creature" guard "any target"
# needs and "target creature" does not.

from engine import Game, PlayerState, load_cards
from engine.alternative_costs import alternative_costs as _w2g3_alt_costs
from engine.card_loader import manifest_set_path
from engine.damage_events import deal_damage
from engine.models import Permanent
from engine.oracle import compile_card_oracle as _w2g3_compile

_W2G3_LEA_I = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g3_cast_scars(set_pool, board, **targets):
    p1 = PlayerState(name="P1", battlefield=list(board))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    p1.hand = [set_pool("ALL")["Scars of the Veteran"]]
    result = game.cast_from_hand(0, "Scars of the Veteran", **targets)
    assert result.supported, result
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()
    return game, p1, p2


def test_w2g3_scars_of_the_veteran_counts_what_its_shield_absorbed(set_pool):
    """CR 615.5's "damage prevented this way" is the shield's own running
    total, read a whole turn after the spell resolved (CR 603.7) - so the
    counters are a reading of the shield rather than of the spell."""
    bear = Permanent(card=_W2G3_LEA_I["Grizzly Bears"])
    bear.metadata["summoning_sickness_turn"] = -99
    game, p1, _p2 = _w2g3_cast_scars(
        set_pool, [bear], target_player_index=0, target_permanent_index=0
    )

    deal_damage(
        game, {"recipient": bear, "amount": 3, "source": None, "combat": False}
    )
    game._settle()
    assert bear.damage_marked == 0, "the shield ate all three"

    game.resolve_end_step(0)
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()
    assert (bear.effective_power, bear.effective_toughness) == (2, 5)


def test_w2g3_scars_of_the_veteran_places_nothing_on_a_player(set_pool):
    """"If it's a creature" is the guard "any target" needs (CR 115.4). It is
    also the arm's own precondition - the end-step reader addresses a
    ``permanent_id`` the shield step recorded, and a shield armed on a player
    recorded none - so the seat takes the prevention and no counters exist to
    go anywhere."""
    game, p1, _p2 = _w2g3_cast_scars(set_pool, [], target_player_index=0)

    deal_damage(
        game, {"recipient": p1, "amount": 3, "source": None, "combat": False}
    )
    game._settle()
    game.resolve_end_step(0)
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()
    assert p1.life == 20
    assert p1.battlefield == []


def test_w2g3_scars_of_the_veteran_keeps_its_pitch_cost(set_pool):
    """The CR 118.9 half W1G4 landed is still read now that the effect half
    compiles - the two are different readings of the same card and a card
    supported on one of them is exactly the failure this round removed."""
    card = set_pool("ALL")["Scars of the Veteran"]
    assert _w2g3_compile(card).supported
    assert _w2g3_alt_costs(card)


# --- W3G1: repeated additional costs ---
#
# Undergrowth's optional additional cost (CR 601.2b) and the width it buys the
# prevention (CR 615), plus Bounty of the Hunt's delayed counter removal
# (CR 603.7 at CR 514's cleanup step). The rules-level tests for the cost
# machinery are in ``tests/rules/test_optional_additional_costs.py``. Imports
# are in this block, per the header's parallel-authorship convention.

from engine import Game as _W3G1Game, PlayerState as _W3G1Player, load_cards as _w3g1_load
from engine.card_loader import manifest_set_path as _w3g1_path
from engine.models import Permanent as _W3G1Permanent
from engine.oracle import compile_card_oracle as _w3g1_compile

_W3G1_LEA = {c.name: c for c in _w3g1_load(_w3g1_path("LEA"))}


def _w3g1_bounty_game(set_pool):
    """Bounty of the Hunt in hand, a 2/2 and a 3/3 on the caster's board."""
    caster = _W3G1Player(name="A", hand=[set_pool("ALL")["Bounty of the Hunt"]])
    game = _W3G1Game(players=[caster, _W3G1Player(name="B")])
    game.enforce_mana_costs = False
    bear = _W3G1Permanent(card=_W3G1_LEA["Grizzly Bears"])
    giant = _W3G1Permanent(card=_W3G1_LEA["Hill Giant"])
    caster.battlefield.extend([bear, giant])
    game._settle()
    return game, bear, giant


def test_undergrowth_prevention_narrows_only_when_its_cost_was_paid(set_pool):
    """"Prevent all combat damage that would be dealt this turn. If this spell's
    additional cost was paid, this effect doesn't affect combat damage that
    would be dealt by red creatures."

    Two sentences, **one** effect: the second is a rider on the first ("*this*
    effect" names it), so it lowers to a choice between two widths rather than
    to a second prevention that would apply alongside the first. The compiled
    shape is the assertion, because the behavioural halves are in
    ``tests/rules/test_optional_additional_costs.py`` where the combat setup
    lives."""
    (branch,) = _w3g1_compile(set_pool("ALL")["Undergrowth"]).instructions[:1]
    assert branch.kind == "if_then"
    assert branch.payload["condition"] == {"kind": "additional_cost_paid"}
    (narrow,) = branch.payload["then"]
    (wide,) = branch.payload["else"]
    assert narrow.kind == "prevent_all_combat_damage_except_from"
    assert narrow.payload["filter"] == {"type_filter": "creature", "color_filter": "R"}
    assert wide.kind == "prevent_all_combat_damage"


def test_bounty_of_the_hunt_distributes_three_counters_over_a_bounded_count(set_pool):
    """"Distribute three +1/+1 counters among one, two, or three target
    creatures." The enumerated bound W2G2 built for Contagion, with one more
    term — so this half needed nothing new, which is worth pinning: a later
    round reading the census would otherwise rebuild it."""
    (place,) = [
        i for i in _w3g1_compile(set_pool("ALL")["Bounty of the Hunt"]).instructions
        if i.kind == "add_counter_to_target"
    ] or [
        step
        for i in _w3g1_compile(set_pool("ALL")["Bounty of the Hunt"]).instructions
        for step in i.payload.get("steps", ())
        if step.kind == "add_counter_to_target"
    ]
    assert place.payload["count"] == 3
    assert place.payload["targets"]["max_targets"] == 3
    assert place.payload["targets"]["division"] == "chosen"

    game, bear, giant = _w3g1_bounty_game(set_pool)
    result = game.cast_from_hand(
        0, "Bounty of the Hunt", target_player_index=0,
        divided_targets=[(0, 0, 2), (0, 1, 1)],
    )
    game._settle()

    assert result.supported, result.details
    assert (bear.effective_power, bear.effective_toughness) == (4, 4)
    assert (giant.effective_power, giant.effective_toughness) == (4, 4)


def test_bounty_of_the_hunt_takes_the_counters_back_at_cleanup(set_pool):
    """"For each +1/+1 counter you put on a creature this way, remove a +1/+1
    counter from that creature at the beginning of the next cleanup step."

    One delayed ability **per counter** (CR 603.7), not per creature: the loop
    walks the counters, so the creature given two of them is iterated twice and
    gets two of them. Counting the creatures instead would hand back one counter
    of the two and leave the card permanently pumping.

    The trailing delay is pushed *inside* the loop for the same reason it is the
    printed reading: left wrapped around it the loop would run a turn later,
    when the record it iterates is out of scope and "that creature" names
    nobody."""
    game, bear, giant = _w3g1_bounty_game(set_pool)
    game.cast_from_hand(
        0, "Bounty of the Hunt", target_player_index=0,
        divided_targets=[(0, 0, 2), (0, 1, 1)],
    )
    game._settle()

    assert [t.event for t in game.delayed_triggers] == ["next_cleanup_step"] * 3
    assert sorted(t.bound_permanent_id for t in game.delayed_triggers) == [
        bear.permanent_id, bear.permanent_id, giant.permanent_id,
    ]

    game.resolve_cleanup_step(0)
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert (giant.effective_power, giant.effective_toughness) == (3, 3)


# --- W3G5: hollow lines, pickers and unclaimed text ---
#
# The family that already *looked* done: cards the census counts as supported
# while a sentence of theirs does nothing. Every test below is behavioural,
# because that is the check the instruments cannot make.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

_W3G5_POOLS: dict = {}


def _w3g5_from(code: str, name: str) -> CardDefinition:
    """One card of one set, by code. The ALL pool is `measured`, so its cards
    are placed into a driven game directly - no player can deck one."""
    if code not in _W3G5_POOLS:
        _W3G5_POOLS[code] = {
            card.name: card
            for card in load_cards(manifest_set_path(code, include_measured=True))
        }
    return _W3G5_POOLS[code][name]


def _w3g5_duel() -> Game:
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    return game


def _w3g5_put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _w3g5_names(game: Game, seat: int) -> list[str]:
    return sorted(perm.card.name for perm in game.controlled_by(seat))


def test_omen_of_fire_bounces_the_islands_and_scales_the_sacrifice_per_seat():
    """Both sentences, and the second is the one nothing implemented.

    The count is per *payer* - "for each white permanent **they** control" - so
    the two seats owe different numbers off one resolution, which is the whole
    reason it rides `X_FROM_COUNT_PER_RECIPIENT` rather than a printed count.
    And what may be given up is a union across two axes ("a Plains **or** a
    white permanent"), which `subtypes` plus `colors` would AND into a *white
    Plains* - a set no board has.
    """
    game = _w3g5_duel()
    _w3g5_put(game, 0, _w3g5_from("LEA", "Island"))
    _w3g5_put(game, 1, _w3g5_from("LEA", "Island"))
    # Seat 0 owes two: two white permanents. Its Plains is colourless and is
    # payable only because the union names the subtype as well.
    _w3g5_put(game, 0, _w3g5_from("LEA", "Plains"))
    _w3g5_put(game, 0, _w3g5_from("LEA", "Savannah Lions"))
    _w3g5_put(game, 0, _w3g5_from("LEA", "White Knight"))
    # Seat 1 owes one, and has a green permanent that is in neither half.
    _w3g5_put(game, 1, _w3g5_from("LEA", "Savannah Lions"))
    _w3g5_put(game, 1, _w3g5_from("LEA", "Grizzly Bears"))

    game.players[0].hand.append(_w3g5_from("ALL", "Omen of Fire"))
    assert game.cast_from_hand(0, "Omen of Fire").supported
    game.resolve_stack()

    assert "Island" not in _w3g5_names(game, 0) and "Island" not in _w3g5_names(game, 1)
    assert game.players[0].hand.count(_w3g5_from("LEA", "Island")) == 1
    assert len(_w3g5_names(game, 0)) == 1, (
        "two white permanents means two sacrifices, out of three eligible"
    )
    assert _w3g5_names(game, 1) == ["Grizzly Bears"], (
        "one white permanent means one sacrifice, and green is in neither half"
    )


def test_gorilla_war_cry_gives_menace_to_both_players_creatures():
    """"**All** creatures gain menace until end of turn" — every creature on
    the table, not the caster's.

    The keyword and its blocking restriction were both already there: menace is
    in `IMPLEMENTED_KEYWORDS`, `layer_bridge` grants it, and
    `_minimum_blockers` enforces CR 702.111a. What refused was the *scope* —
    the team grant's lowering said "the team keyword grant reads one player's
    board", which had stopped being true when Stampede taught the handler
    `every_seat`.
    """
    game = _w3g5_duel()
    mine = _w3g5_put(game, 0, _w3g5_from("LEA", "Grizzly Bears"))
    theirs = _w3g5_put(game, 1, _w3g5_from("LEA", "Hill Giant"))
    game.players[0].hand.append(_w3g5_from("ALL", "Gorilla War Cry"))

    # "Cast this spell only during combat before blockers are declared."
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.cast_from_hand(0, "Gorilla War Cry").supported
    game.resolve_stack()

    assert mine.has_keyword("menace") and theirs.has_keyword("menace"), (
        "\"all creatures\" is every seat's, and the caster does not choose which"
    )
    assert game._minimum_blockers(theirs) == 2, (
        "CR 702.111a: the grant reaches the enforcement, not just the word"
    )


def test_suffocation_is_declined_naming_four_parts():
    """Its cast restriction and its damage sentence are the same missing
    record, read at two moments. Both remain unclaimed, and both would be
    *silent* if admitted: a cast gate nothing enforces is a spell castable when
    the card forbids it, and a recipient nothing resolves is 4 damage to
    somebody the card never named.

    1. **A per-seat record of what dealt damage to you this turn, in order.**
       ``PlayerState.damage_taken_this_turn`` is a total and
       ``damaged_by_sources_this_turn`` lives on *permanents*; neither can
       answer "the **last** red instant or sorcery **spell**". The fire site
       exists and is single (``Game._on_player_dealt_damage``), and the seat is
       already derivable there through ``damage_events.damage_source_seat`` —
       so what is missing is the field, its per-turn clear beside
       ``damage_taken_this_turn``'s in ``turn_management``, and the write.
    2. **A `cast_restrictions.py` row for "only if you were dealt damage this
       turn by <noun phrase>".** Textual like every row in that table, and the
       noun phrase reads with the existing card matcher once the record above
       holds card definitions.
    3. **A `PlayerRef` kind for "the controller of the last <noun phrase> that
       dealt damage to you this turn".** The grammar has `that_player` (a seat
       an event froze) and `target_player` (a seat the spell chose); this is
       neither - it is a seat read out of a *history* at resolution, which no
       referent in `ast/_references.py` names today.
    4. **The `deal_damage` recipient arm behind it**, resolving that referent
       and dealing nothing when the record is empty - which cannot happen while
       part 2 gates the cast, but must be right on its own because CR 608.2b
       lets the board change between announcement and resolution.

    Parts 1 and 2 are what another group is most likely to build incidentally:
    the record is the same shape several "damaged you this turn" cards want.
    """
    program = compile_card_oracle(_w3g5_from("ALL", "Suffocation"))
    # It compiles supported on its delayed draw plus `SUPPORTED_SPELL_PATTERNS`;
    # what this asserts is that neither remaining sentence produced anything.
    kinds = [instruction.kind for instruction in program.instructions]
    assert "deal_damage" not in kinds


# --- W3G2: modes, counters and granted abilities ---
#
# Martyrdom grants a whole printed ability (CR 113.3) and then says who may use
# it. Three separate readings meet on one line: the quoted text is compiled by
# `granted_abilities.py` when the grant is recorded, the trailing permission
# belongs to *that* ability rather than to the spell, and the ability's own
# recipient is CR 115.4's union spelled out the long way.

from engine import Game, PlayerState  # noqa: E402
from engine.activation_permissions import (  # noqa: E402
    activation_permission_denial as _w3g2_permission_denial,
)
from engine.card_loader import load_cards as _w3g2_load  # noqa: E402
from engine.card_loader import manifest_set_path as _w3g2_path  # noqa: E402
from engine.models import Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g2_compile  # noqa: E402

_W3G2_LEA = {c.name: c for c in _w3g2_load(_w3g2_path("LEA"))}


def _w3g2_martyrdom_board(set_pool):
    """Martyrdom in hand, one 2/2 each, both seats interactive."""
    p1 = PlayerState(
        name="P1", hand=[set_pool("ALL")["Martyrdom"]],
        library=[_W3G2_LEA["Forest"]] * 5,
    )
    p2 = PlayerState(name="P2", library=[_W3G2_LEA["Forest"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for seat in (0, 1):
        game._put_permanent_onto_battlefield(
            seat, Permanent(card=_W3G2_LEA["Grizzly Bears"]), None
        )
    mine = list(game.controlled_by(p1))[0]
    theirs = list(game.controlled_by(p2))[0]
    return game, p1, p2, mine, theirs


def _w3g2_cast_martyrdom(game, mine):
    return game.queue_from_hand(
        0, "Martyrdom",
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(mine),
        target_permanent_ids=[mine.permanent_id],
    )


def test_w3g2_martyrdom_grants_the_whole_printed_ability(set_pool):
    """CR 113.3: what the creature gains is a printed ability, so the engine
    records the *text* and the compiler makes the ability from it. The
    trailing permission is part of that text — printed outside the quotes,
    but about the granted ability rather than about the spell, which is in a
    graveyard by the time anybody activates."""
    game, _p1, _p2, mine, _theirs = _w3g2_martyrdom_board(set_pool)

    assert _w3g2_cast_martyrdom(game, mine).supported
    game.resolve_stack(pause_for_choices=True)

    program = _w3g2_compile(mine.effective_card)
    assert len(program.activated_abilities) == 1
    line = program.activated_abilities[0].source_line
    assert "Only you may activate this ability" in line
    assert program.activated_abilities[0].instruction.kind == (
        "redirect_next_damage_to_source_until_eot"
    )


def test_w3g2_only_the_granting_player_may_activate_martyrdoms_ability(set_pool):
    """"Only **you**" is the seat that cast Martyrdom, not the creature's
    controller — read the second way the sentence would be no rule at all,
    because CR 602.1a already says that. The seat travels on the grant."""
    game, _p1, _p2, mine, _theirs = _w3g2_martyrdom_board(set_pool)
    assert _w3g2_cast_martyrdom(game, mine).supported
    game.resolve_stack(pause_for_choices=True)
    line = _w3g2_compile(mine.effective_card).activated_abilities[0].source_line

    assert _w3g2_permission_denial(game, 0, mine, line) is None
    assert "may activate" in (_w3g2_permission_denial(game, 1, mine, line) or "")


def test_w3g2_martyrdom_redirects_exactly_one_damage_from_a_player(set_pool):
    """The granted ability's recipient is CR 115.4's union written out
    ("target creature, planeswalker, or player"), and a **player** is the half
    no counted redirect in the pool had a record home for. One point moves and
    the rest of the event lands normally (CR 615.7's arithmetic with CR 614.9's
    verb), so the damage is still dealt in full by the same source."""
    game, p1, p2, mine, _theirs = _w3g2_martyrdom_board(set_pool)
    assert _w3g2_cast_martyrdom(game, mine).supported
    game.resolve_stack(pause_for_choices=True)

    activated = game.activate_permanent_ability(
        0, mine.card.name, target_player_index=0, ability_index=0,
    )
    assert activated.supported
    game.resolve_stack(pause_for_choices=True)

    p2.hand.append(_W3G2_LEA["Lightning Bolt"])
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.resolve_stack(pause_for_choices=True)

    assert p1.life == 18, "one of the three points moved"
    assert mine.damage_marked == 1


def test_w3g2_martyrdom_can_protect_a_creature_too(set_pool):
    """The other half of the same union. The record hangs off whatever the
    damage would be dealt to, which ``engine/damage_redirects`` has always
    allowed to be a player or a permanent (CR 615.1's sibling wording)."""
    game, _p1, p2, mine, theirs = _w3g2_martyrdom_board(set_pool)
    assert _w3g2_cast_martyrdom(game, mine).supported
    game.resolve_stack(pause_for_choices=True)

    activated = game.activate_permanent_ability(
        0, mine.card.name, target_player_index=1, ability_index=0,
        target_permanent_index=game.battlefield_index_of(theirs),
    )
    assert activated.supported
    game.resolve_stack(pause_for_choices=True)

    p2.hand.append(_W3G2_LEA["Lightning Bolt"])
    game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(theirs),
    )
    game.resolve_stack(pause_for_choices=True)

    assert theirs.damage_marked == 2, "one of the three points moved"
    assert mine.damage_marked == 1


# --- W3G3: iterative library procedures ---
#
# Lim-Dul's Vault, whose three sentences are one procedure: a look, an offer
# repeated as many times as the caster chooses, and a shuffle that stacks the
# last cards looked at on top. The order of those last two halves is the whole
# card - the kept cards come out of the library *before* the shuffle and go
# back on top after it, which is what makes it a tutor rather than a look.

import random as _w3g3_random

import pytest as _w3g3_pytest

from engine import Game as _W3G3IGame, PlayerState as _W3G3IPlayerState
from engine.card_loader import load_cards as _w3g3i_load_cards
from engine.card_loader import manifest_set_path as _w3g3i_set_path

_W3G3I_LEA = {c.name: c for c in _w3g3i_load_cards(_w3g3i_set_path("LEA"))}

#: Fifteen distinct cards, so every "top five" in a test names a different set
#: and a bottoming that did nothing would show.
_W3G3I_DECK = (
    "Black Lotus", "Healing Salve", "Grizzly Bears", "Lightning Bolt",
    "Ancestral Recall", "Mox Pearl", "Mox Ruby", "Mox Jet", "Mox Emerald",
    "Mox Sapphire", "Time Walk", "Timetwister", "Fastbond", "Sol Ring",
    "Icy Manipulator",
)


def _w3g3i_vault(set_pool, deck=_W3G3I_DECK, interactive=True, life=20):
    """Cast Lim-Dul's Vault with *deck* stacked, and stop on its first offer."""
    _w3g3_random.seed(4242)
    game = _W3G3IGame(
        players=[_W3G3IPlayerState(name="A"), _W3G3IPlayerState(name="B")]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0, 1} if interactive else set()
    game._settle()
    game.players[0].life = life
    game.players[0].library = [_W3G3I_LEA[name] for name in deck]
    game.players[0].hand = [set_pool("ALL")["Lim-D\u00fbl's Vault"]]
    game.cast_from_hand(0, "Lim-D\u00fbl's Vault")
    game._settle()
    return game


def test_lim_duls_vault_shuffles_before_it_stacks_the_cards_you_kept(set_pool):
    """"Then shuffle and put the last cards you looked at this way on top in
    any order."

    The order of the two halves is the card. Shuffling with the five still in
    the library would lose them; stacking before shuffling would shuffle them
    away again. Either mistake leaves a card that reports supported and is a
    look rather than a tutor, so the assertion is on the *set* of five that
    ends up on top rather than on any one ordering.
    """
    game = _w3g3i_vault(set_pool)
    looked = [c.name for c in game.players[0].library[:5]]
    assert looked == list(_W3G3I_DECK[:5]), "the look changes no zone"

    assert game.confirm_library_cycle_offer(0, False)
    game._settle()

    assert len(game.players[0].library) == 15, "nothing left the library"
    assert sorted(c.name for c in game.players[0].library[:5]) == sorted(looked)


def test_lim_duls_vault_lets_the_caster_order_the_five_it_stacked(set_pool):
    """The ordering is chained onto the answer that ends the loop rather than
    done inside it: ``reorder_library`` is a prompt that already exists with
    its own UI, AI default and action, and a decision armed by answering
    another stays inside the same resolution (CR 608.2)."""
    game = _w3g3i_vault(set_pool)
    game.confirm_library_cycle_offer(0, False)
    game._settle()

    ordering = game.pending_choice_of("reorder_library", 0)
    assert ordering is not None
    assert ordering.data["top_count"] == 5
    assert ordering.data["may_shuffle"] is False

    before = [c.name for c in game.players[0].library[:5]]
    assert game.confirm_reorder_library(0, [4, 3, 2, 1, 0])
    game._settle()

    assert [c.name for c in game.players[0].library[:5]] == list(reversed(before))
    assert game.stack == [], "the spell finished once the last prompt was answered"


def test_lim_duls_vault_pays_a_life_a_round_and_asks_again(set_pool):
    """"As many times as you choose, you may pay 1 life…"

    Each acceptance bottoms the five just looked at, looks at the next five and
    arms the *same* offer again - a prompt armed by answering an earlier one,
    which is how a chain of decisions stays one resolution.
    """
    game = _w3g3i_vault(set_pool)

    assert game.confirm_library_cycle_offer(0, True)
    game._settle()
    assert game.players[0].life == 19
    assert [c.name for c in game.players[0].library[:5]] == list(_W3G3I_DECK[5:10])
    assert [c.name for c in game.players[0].library[-5:]] == list(_W3G3I_DECK[:5])
    assert game.pending_choice_of("library_cycle_offer", 0) is not None

    assert game.confirm_library_cycle_offer(0, True)
    game._settle()
    assert game.players[0].life == 18
    third = [c.name for c in game.players[0].library[:5]]
    assert third == list(_W3G3I_DECK[10:15])

    assert game.confirm_library_cycle_offer(0, False)
    game._settle()
    assert game.players[0].life == 18, "declining costs nothing"
    assert sorted(c.name for c in game.players[0].library[:5]) == sorted(third)


def test_lim_duls_vault_accepted_with_no_life_ends_the_loop(set_pool):
    """CR 119.4 lets a player pay N life only with N or more to pay it from. A
    yes that cannot be paid for is a decline, not a refused answer: refusing it
    would leave the prompt queued with no answer that could ever clear it, and
    the game waits on this prompt."""
    game = _w3g3i_vault(set_pool, life=0)

    assert game.confirm_library_cycle_offer(0, True)
    game._settle()

    assert game.players[0].life == 0
    assert game.pending_choice_of("library_cycle_offer", 0) is None
    assert game.pending_choice_of("reorder_library", 0) is not None


def test_lim_duls_vault_declines_at_once_for_a_headless_seat(set_pool):
    """The stated policy, and not ``_default_optional_pay``'s "pay tolls":
    that policy is written for an offer made once, and this one is made again
    every time it is taken. A seat that paid whenever it could afford to would
    pay its life total down to 1 for a shuffle it cannot evaluate."""
    game = _w3g3i_vault(set_pool, interactive=False)

    assert game.players[0].life == 20
    assert game.pending_choice_of("library_cycle_offer", 0) is None
    assert len(game.players[0].library) == 15


def test_lim_duls_vault_survives_a_library_shorter_than_the_look(set_pool):
    """"Look at the top five cards" of a two-card library is two cards, and
    the loop still ends in a shuffle. Nothing here is a draw, so CR 704.5b
    never fires."""
    game = _w3g3i_vault(set_pool, deck=("Black Lotus", "Sol Ring"))

    assert game.confirm_library_cycle_offer(0, True)
    game._settle()
    assert game.players[0].life == 19
    assert len(game.players[0].library) == 2

    assert game.confirm_library_cycle_offer(0, False)
    game._settle()
    assert len(game.players[0].library) == 2
    assert not game.players[0].lost


def test_the_vault_loop_refuses_a_second_look_of_a_different_size(set_pool):
    """One production over three sentences has to read both numbers. Quietly
    reusing the first is how a card comes to do something it does not say."""
    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError

    with _w3g3_pytest.raises(GrammarError):
        parse_line(
            "Look at the top five cards of your library. As many times as you "
            "choose, you may pay 1 life, put those cards on the bottom of your "
            "library in any order, then look at the top three cards of your "
            "library. Then shuffle and put the last cards you looked at this "
            "way on top in any order."
        )


# --- W3-divided: the divided-target announcement ---
#
# CR 601.2d is announced as the spell is cast, and the AI had no field to
# announce it in: every divided spell it cast arrived with no division at all.
# Contagion and Bounty of the Hunt then resolved putting no counters anywhere,
# and Pyrokinesis -- which names only creatures -- dealt its four damage to a
# player's face. Which *side* the shares land on is the half no "did it place a
# counter?" assertion can see, so every test below checks the seat.

def _w3d_board(set_pool, name, creature="Gorilla Chieftain", each=2):
    """Seat 0 holding *name*, with *each* copies of one creature per side.

    Deliberately symmetric: a chooser that ignores the sign of the counter it
    divides still lands on a legal target here, so only the seat tells a right
    answer from a backwards one.
    """
    from engine import Game
    from engine.models import Permanent, PlayerState

    pool = set_pool("ALL")
    p0 = PlayerState(
        name="P0", life=20, hand=[pool[name]],
        battlefield=[Permanent(card=pool[creature]) for _ in range(each)],
    )
    p1 = PlayerState(
        name="P1", life=20,
        battlefield=[Permanent(card=pool[creature]) for _ in range(each)],
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w3d_cast(game, seat, name, card, x_value=None):
    """Cast *name* the way an AI seat now does: announce the division first."""
    from engine.ai_policy import choose_divided_targets

    announced = choose_divided_targets(game, seat, card, x_value)
    result = game.cast_from_hand(
        seat, name, target_player_index=1 - seat, x_value=x_value,
        divided_targets=announced,
    )
    game._settle()
    return announced, result


def _w3d_counters(game, seat, key):
    """How many counters of one kind sit on each of *seat*'s permanents, by
    battlefield position -- counted per position rather than per name, because
    the boards are two copies of one card."""
    return [
        int(perm.metadata.get(key, 0)) for perm in game.players[seat].battlefield
    ]


def test_contagion_puts_its_minus_counters_on_the_opponents_creatures(set_pool):
    """"Distribute two -2/-1 counters among one or two target creatures."

    CR 601.2d's announcement, aimed by the *sign* of the counter (CR 122.1a)
    rather than by the card's name: a -2/-1 is removal, so both counters go on
    the opponent's board. They used to go nowhere at all -- the resolver read
    an empty division and logged "no creatures were given counters".
    """
    game = _w3d_board(set_pool, "Contagion")
    announced, result = _w3d_cast(game, 0, "Contagion", set_pool("ALL")["Contagion"])

    assert result.supported, result.details
    assert announced and all(entry[0] == 1 for entry in announced), announced
    assert _w3d_counters(game, 1, "-2/-1_counters") == [1, 1], \
        "the printed count is two targets, each of which must get at least one"
    assert _w3d_counters(game, 0, "-2/-1_counters") == [0, 0], \
        "a -2/-1 counter on the caster's own creature is the sign read backwards"


def test_bounty_of_the_hunt_puts_its_plus_counters_on_the_casters_own(set_pool):
    """"Distribute three +1/+1 counters among one, two, or three target
    creatures."

    The same derivation with the sign the other way round, and the boundary
    that makes it a derivation rather than a guess: this card and Contagion
    compile to one instruction kind, and only the counter distinguishes them.
    """
    game = _w3d_board(set_pool, "Bounty of the Hunt")
    announced, result = _w3d_cast(
        game, 0, "Bounty of the Hunt", set_pool("ALL")["Bounty of the Hunt"],
    )

    assert result.supported, result.details
    assert announced and all(entry[0] == 0 for entry in announced), announced
    assert sum(_w3d_counters(game, 0, "plus_counters")) == 3
    assert _w3d_counters(game, 1, "plus_counters") == [0, 0], \
        "a +1/+1 counter on the opponent's creature is the sign read backwards"


def test_pyrokinesis_divides_its_damage_among_creatures_not_a_face(set_pool):
    """"Pyrokinesis deals 4 damage divided as you choose among any number of
    **target creatures**."

    The printed noun names no player, so a seat is not a legal target of it
    (CR 601.2c). With no division announced the resolver fell through to the
    engine's older single-target path, which has only ``target_player_index``
    to read -- so a creature-only spell burned a player for four.
    """
    game = _w3d_board(set_pool, "Pyrokinesis")
    announced, result = _w3d_cast(
        game, 0, "Pyrokinesis", set_pool("ALL")["Pyrokinesis"],
    )

    assert result.supported, result.details
    assert announced == [(1, 0, 4)], announced
    assert game.players[1].life == 20, "the card names creatures, not a player"
    assert len(game.players[1].battlefield) == 1, \
        "four damage is lethal to a 3/3 (CR 704.5g)"
    assert len(game.players[0].battlefield) == 2


def test_a_divided_spell_naming_no_target_at_all_is_refused(set_pool):
    """CR 601.2d divides "among **one or more** targets", so a divided spell
    proposed with none is an illegal proposal and CR 601.2e returns the game to
    the moment before it -- nothing spent.

    Contagion is the sharpest case in the set: its alternative cost is "pay 1
    life and exile a black card", so a cast that got past the gate paid a real
    price for an announcement the rules never allowed.
    """
    from engine import Game
    from engine.models import PlayerState

    pool = set_pool("ALL")
    p0 = PlayerState(name="P0", life=20, hand=[pool["Contagion"]])
    game = Game(players=[p0, PlayerState(name="P1", life=20)])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.cast_from_hand(0, "Contagion")

    assert not result.supported
    assert "601.2d" in result.details, result.details
    assert [card.name for card in game.players[0].hand] == ["Contagion"]
    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert not game.stack
# --- end W3-divided ---

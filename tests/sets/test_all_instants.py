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


def test_scars_of_the_veteran_declines_on_its_delayed_trigger(set_pool):
    """The pitch half is done (see the cycle test above). What is missing is one
    part: **a delayed triggered ability created at resolution** (CR 603.7) —
    "put a +0/+1 counter on it for each 1 damage prevented this way at the
    beginning of the next end step", which also has to read back how much a
    CR 615 shield actually absorbed. W1G5 owns the delayed-trigger mechanism;
    when it lands, this card needs only the counter-per-damage-prevented
    reader."""
    program = compile_card_oracle(set_pool("ALL")["Scars of the Veteran"])
    assert not program.supported
    assert alternative_costs(set_pool("ALL")["Scars of the Veteran"]), (
        "the alternative cost is read even while the effect half is not"
    )


def test_bounty_of_the_hunt_declines_on_two_named_parts(set_pool):
    """Two parts, both outside this round's subsystem:

    1. ~~a bounded distributed target count~~ — **landed in W2G2**: the
       enumerated "among one, two, or three" form parses into
       ``TargetSpec.max_count`` and the bound is enforced at announcement in
       ``divided_damage.division_refusal``. This card's first line is no longer
       what holds it;
    2. **the loop iterator "for each +1/+1 counter you put on a creature this
       way"**. ``records._parse_for_each_this_way`` reads exactly ``for each
       <one word> <one participle> this way`` against a two-entry table
       (``card discarded`` / ``card exiled``, plus Sacred Boon's ``damage
       prevented``). Here the noun is a **PT token** and the participle is a
       four-word relative clause, so nothing is consumed at all — and there is
       no record behind it either: the distributed placement writes no
       "counters placed this way" key for a ``ThatMuch`` to read;
    3. **"remove a +1/+1 counter from that creature"** — the removal's subject
       is the creature this same sentence just chose, and the only
       counter-removal lowering reads the ability's own source. It refuses at
       *lowering*, not at parse, which is why the sentence looks readable.

    The delayed trigger the earlier decline named is **not** a missing part any
    more: W1G5 landed "at the beginning of the next cleanup step" end to end,
    and the tail alone ("remove … at the beginning of the next cleanup step")
    parses today and stops only on part 3."""
    program = compile_card_oracle(set_pool("ALL")["Bounty of the Hunt"])
    assert not program.supported
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


def test_undergrowth_declines_on_an_optional_mana_additional_cost(set_pool):
    """Two parts, neither of them the pitch cycle:

    1. **an optional additional cost paid in mana** — "As an additional cost to
       cast this spell, you may pay {2}{R}." ``cast_costs._COST_CLAUSES`` has no
       mana clause at all, and it has no notion of an *optional* cost either:
       every clause it reads is mandatory, which is what makes the CR 601.2h
       gate a refusal rather than a choice;
    2. **a rider that reads back whether that cost was paid** — "If this spell's
       additional cost was paid, this effect doesn't affect combat damage that
       would be dealt by red creatures", which needs the answer recorded on the
       stack item the way ``sacrificed_for_cost`` already is, and a
       ``prevent_all_combat_damage`` that can carry an exclusion filter."""
    program = compile_card_oracle(set_pool("ALL")["Undergrowth"])
    assert not program.supported
    assert not additional_costs(set_pool("ALL")["Undergrowth"]), (
        "an optional mana cost is deliberately not read: reading it as "
        "mandatory would make the spell uncastable without {2}{R}"
    )


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

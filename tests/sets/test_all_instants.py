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


def test_martyrdom_is_declined_naming_three_parts(set_pool):
    """Three independent gaps, none of them the granted ability itself:

    1. **The trailing sentence after a quoted grant.** "Only you may activate
       this ability." sits outside the closing quote, and the quote guard in
       ``parser._parse_line`` hands the whole line to the quoted-token reader,
       which has no reading for anything after the quote. The same line with
       nothing behind the quote parses today.
    2. **A counted redirect onto a player.** "The next 1 damage that would be
       dealt to **target creature, planeswalker, or player**" is CR 115.4's
       "any target", and ``redirect_next_damage_to_source_until_eot`` hangs its
       record off the *protected permanent* - Daughter of Autumn and Hazduhr
       the Abbot both print a creature-only slot. A player recipient needs the
       record to live on a seat.
    3. **A "who may activate" restriction.** ``activation_restrictions.py``
       gates *when* an ability may be activated; "Only you may activate this
       ability" gates *who*, and on a granted ability that is the granting
       player rather than the permanent's controller.
    """
    program = compile_card_oracle(set_pool("ALL")["Martyrdom"])
    assert not program.supported


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

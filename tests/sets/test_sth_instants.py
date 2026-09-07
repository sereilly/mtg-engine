"""Stronghold instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""



# --- W1G2: combat restrictions and requirements ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2i_creature(name, power, toughness):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g2i_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g2i_game(mine, theirs, hand=()) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine), hand=list(hand)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_change_of_heart_marks_one_creature_and_not_the_board(set_pool):
    """"Target creature can't attack this turn."

    A *targeted* restriction, which is the whole reason it is not the blanket
    one printed with the same words: routed through that kind it would ground
    every creature the noun phrase describes, and "target creature" describes
    all of them. The bystander is the assertion.
    """
    heart = set_pool("STH")["Change of Heart"]
    program = compile_card_oracle(heart)
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == [
        "target_cant_attack_until_eot"
    ]

    marked = _g2i_nosick(Permanent(card=_g2i_creature("Raider", 2, 2)))
    bystander = _g2i_nosick(Permanent(card=_g2i_creature("Rider", 2, 2)))
    game = _g2i_game([marked, bystander], [], hand=[heart])
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.can_attack(marked, 1)

    result = game.cast_from_hand(
        0, "Change of Heart", target_player_index=0, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)

    assert not game.can_attack(marked, 1)
    assert game.can_attack(bystander, 1), (
        "the spell named one creature; a blanket reading would ground both"
    )


def test_change_of_heart_s_mark_is_swept_with_the_turn(set_pool):
    """"This turn" is the cleanup sweep and nothing else.

    A mark no ``_EOT_METADATA_KEYS`` entry names would ground the creature for
    the rest of the game while the card reported supported - the failure Blaze
    of Glory's pair records in ``engine/combat_permissions.py``.
    """
    from engine.combat_permissions import CANT_ATTACK_UNTIL_EOT

    marked = _g2i_nosick(Permanent(card=_g2i_creature("Raider", 2, 2)))
    game = _g2i_game([], [marked])
    marked.metadata[CANT_ATTACK_UNTIL_EOT] = True
    game.start_turn(0)
    game.resolve_cleanup_step(0)

    assert CANT_ATTACK_UNTIL_EOT not in marked.metadata


def test_provoke_untaps_a_creature_and_makes_it_block(set_pool):
    """"Untap target creature you don't control. That creature blocks this turn
    if able."

    Both sentences, and the second one is why: the card reported *supported* on
    its "Draw a card" line alone, with the untap and the requirement dropped
    together. CR 509.1c's weakest requirement - block **something** - so the
    declaration that leaves the provoked creature at home is the illegal one.
    """
    provoke = set_pool("STH")["Provoke"]
    program = compile_card_oracle(provoke)
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "untap_target_permanent", "force_bound_to_block_until_eot",
    ]

    attacker = _g2i_nosick(Permanent(card=_g2i_creature("Raider", 2, 2)))
    provoked = _g2i_nosick(Permanent(card=_g2i_creature("Guard", 2, 2)))
    provoked.tapped = True
    game = _g2i_game([attacker], [provoked], hand=[provoke])
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.cast_from_hand(
        0, "Provoke", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)
    assert not provoked.tapped, "the first sentence untaps it"

    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()

    ok, message = game.declare_blockers(1, {})
    assert not ok and "blocks each combat if able" in message, message
    assert game.declare_blockers(1, {0: 0})[0]


# --- W1G3: combat triggers, delayed effects and retargeting ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w1g3_rebound_game(set_pool, spell, spell_set="LEA"):
    """Rebound in seat 0's hand, *spell* in seat 1's, a creature on seat 0's board."""
    perm = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    game = Game(players=[
        PlayerState(
            name="P1", hand=[set_pool("STH")["Rebound"]],
            battlefield=[perm], life=20,
        ),
        PlayerState(name="P2", hand=[set_pool(spell_set)[spell]], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    return game, perm


def _w1g3_rebound_spec(set_pool):
    card = set_pool("STH")["Rebound"]
    return derive_cast_spec(card, compile_card_oracle(card))


def test_rebound_is_supported_and_bounds_both_ends(set_pool):
    """"Change the target of target spell that targets only a player. The new
    target must be a player."

    Both printed restrictions land on the payload: the clause is CR 115.9a's
    count plus the shape of the one target — the same node Meddle builds from a
    condition and Reflecting Mirror from a noun phrase plus an "if".
    """
    card = set_pool("STH")["Rebound"]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [step.kind for step in steps] == [
        "choose_new_spell_target", "change_target_spell_target",
    ]
    assert steps[0].payload["current_target_type"] == "player"
    assert steps[0].payload["new_target"] == "player"
    assert _w1g3_rebound_spec(set_pool)["stack_single_target_type"] == "player"


def test_rebound_re_aims_a_spell_at_the_other_player(set_pool):
    """CR 115.7a: everything else the spell announced stays, and only the face
    it points at moves — so the Lava Burst's caster takes its own damage."""
    game, _perm = _w1g3_rebound_game(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    game.queue_from_hand(0, "Rebound", target_stack_index=0)
    game.resolve_stack()

    assert game.players[0].life == 20, game.log
    assert game.players[1].life == 17, game.log


def test_rebound_is_not_offered_a_spell_aimed_at_a_creature(set_pool):
    """The clause is a restriction, not decoration: a production that consumed
    "that targets only a player" and dropped it would let Rebound re-aim a
    Terror, which is a strictly larger card than the one printed."""
    game, perm = _w1g3_rebound_game(set_pool, "Terror", spell_set="LEA")
    game.queue_from_hand(1, "Terror", target_permanent_ids=[perm.permanent_id])

    offered = game._enumerate_targets(
        0, set_pool("STH")["Rebound"], _w1g3_rebound_spec(set_pool), for_cast=True
    )
    assert offered == [], game.log


def test_rebound_is_offered_a_spell_aimed_at_a_player(set_pool):
    """The other side of the same gate, so the test above is not passing for
    the wrong reason."""
    game, _perm = _w1g3_rebound_game(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)

    offered = game._enumerate_targets(
        0, set_pool("STH")["Rebound"], _w1g3_rebound_spec(set_pool), for_cast=True
    )
    assert [entry["name"] for entry in offered] == ["Lightning Bolt"], game.log


# --- W1G1: damage prevention, redirection and damage-event triggers ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _w1g1_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game


def _w1g1_bear(name="Bear", power=2, toughness=2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Bear",
            "power": str(power), "toughness": str(toughness),
        },
    )


def _w1g1_temper(set_pool, x_value):
    """Temper cast for *x_value* over a 2/2, with the shield armed."""
    game = _w1g1_duel()
    p1, _ = game.players
    bear = _nosick(Permanent(card=_w1g1_bear("Shielded Bear")))
    p1.battlefield.append(bear)
    p1.hand.append(set_pool("STH")["Temper"])
    result = game.cast_from_hand(
        0, "Temper", target_player_index=0, target_permanent_index=0,
        x_value=x_value,
    )
    assert result.supported
    return game, bear


def test_temper_puts_a_counter_on_as_each_point_is_prevented(set_pool):
    """"Prevent the next X damage that would be dealt to target creature this
    turn. For each 1 damage prevented this way, put a +1/+1 counter on that
    creature."

    CR 615.5: "the prevention takes place at the time the original event would
    have happened; the rest of the effect takes place immediately afterward."
    So the counters arrive **inside the damage event**, which is the assertion
    that matters — a reading that placed them when the spell resolved would put
    down zero for ever, and would report exactly the same "supported".

    Three numbers, because each is a different way to get it wrong: no damage
    marked (the points really were prevented), two counters (one per point, not
    one per event), and the shield spent down to nothing.
    """
    game, bear = _w1g1_temper(set_pool, 2)
    printed = bear.effective_power

    assert bear.effective_power == printed, "nothing is placed at resolution"

    game._mark_damage_on_permanent(bear, 2)

    assert bear.damage_marked == 0
    assert bear.effective_power == printed + 2
    assert bear.damage_prevention_pool == 0


def test_temper_only_pays_for_the_damage_its_shield_actually_absorbed(set_pool):
    """The pool is X points wide and the counters count points, not events
    (CR 615.7). An event larger than the pool leaves its remainder marked and
    buys exactly as many counters as the shield had left — a rider that read
    the *event* would grow the creature by the whole Fireball.
    """
    game, bear = _w1g1_temper(set_pool, 1)
    printed_toughness = bear.effective_toughness

    game._mark_damage_on_permanent(bear, 3)

    assert bear.damage_marked == 2, "only one point was in the pool"
    assert bear.effective_toughness == printed_toughness + 1


# --- W1G4: library, graveyard and unusual costs ---

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.cast_costs import (buyback_cost, buyback_paid, expand_buyback_line,
                               unread_cost_sentence)
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g4_duel(hand: list) -> tuple[Game, PlayerState, PlayerState]:
    """A two-seat game with mana enforcement off, so a test about a *cost
    sentence* is not also a test about the pool."""
    caster, victim = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, caster, victim


@pytest.mark.cr("702.27a", "601.2b")
def test_g4_constant_mists_buyback_is_a_non_mana_offer(set_pool):
    """"Buyback—Sacrifice a land."

    CR 702.27's cost is *any* cost, and the rewrite could read only a run of
    mana symbols — so this line was refused by the support gate, which is the
    gate working (a spell cast for its printed {1}{G} with the price nobody was
    offered and no hand-return is worse than an unsupported card). It rewrites
    into CR 601.2b's optional sentence with the printed clause after "you may",
    and the announcement key is that clause.
    """
    card = set_pool("STH")["Constant Mists"]
    printed = card.oracle_text.split("\n")[0]

    assert expand_buyback_line(printed) == (
        "As an additional cost to cast this spell, you may sacrifice a land."
    )
    assert buyback_cost(card.oracle_text) == "sacrifice a land"
    assert unread_cost_sentence(printed) is None
    assert compile_card_oracle(card).supported


@pytest.mark.cr("702.27a", "601.2b")
def test_g4_constant_mists_declined_keeps_the_land_and_bins_the_spell(set_pool):
    """An offer nobody took costs nothing, and CR 702.27a's hand-return is
    conditional on the payment — so the declined cast is an ordinary instant."""
    game, caster, _ = _g4_duel([set_pool("STH")["Constant Mists"]])
    caster.battlefield.append(Permanent(card=_G4_LEA["Forest"]))

    result = game.cast_from_hand(0, "Constant Mists")
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert [p.card.name for p in caster.battlefield] == ["Forest"]
    assert [c.name for c in caster.graveyard] == ["Constant Mists"]
    assert caster.hand == []


@pytest.mark.cr("702.27a", "601.2b")
def test_g4_constant_mists_bought_back_eats_a_land_and_returns(set_pool):
    """The two halves of CR 702.27a in one cast: the land is gone before the
    spell is on the stack, and the spell goes to the hand rather than the
    graveyard as it resolves."""
    game, caster, _ = _g4_duel([set_pool("STH")["Constant Mists"]])
    caster.battlefield.append(Permanent(card=_G4_LEA["Forest"]))

    result = game.cast_from_hand(
        0, "Constant Mists", optional_cost_payments={"sacrifice a land": 1},
    )
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert caster.battlefield == [], "the buyback ate the land"
    assert [c.name for c in caster.graveyard] == ["Forest"]
    assert [c.name for c in caster.hand] == ["Constant Mists"]
    assert buyback_paid(
        set_pool("STH")["Constant Mists"],
        {"additional_costs_paid": {"sacrifice a land": 1}},
    )


@pytest.mark.cr("601.2h", "702.27a")
def test_g4_a_buyback_announced_off_an_empty_board_refuses_the_cast(set_pool):
    """CR 601.2h: an announced price that cannot be paid is a cast that does
    not happen, never one that happens for less. Nothing is spent, and the same
    caster who *declines* casts the spell off the same empty board — which is
    the half a gate reading the cost as mandatory would have got wrong.
    """
    card = set_pool("STH")["Constant Mists"]

    game, caster, _ = _g4_duel([card])
    refused = game.cast_from_hand(
        0, "Constant Mists", optional_cost_payments={"sacrifice a land": 1},
    )
    assert not refused.supported
    assert "CR 601.2h" in refused.details
    assert [c.name for c in caster.hand] == ["Constant Mists"]

    game, caster, _ = _g4_duel([card])
    assert game.cast_from_hand(0, "Constant Mists").supported


@pytest.mark.cr("601.2b")
def test_g4_the_buyback_offer_reaches_the_picker_only_when_it_is_taken(set_pool):
    """The offer is what the client is shown, and the *picker* follows the
    answer: a caster who declines is asked to name no land, and one who takes it
    gets the sacrifice picker on the same re-asked spec."""
    card = set_pool("STH")["Constant Mists"]
    game, caster, _ = _g4_duel([card])
    caster.battlefield.append(Permanent(card=_G4_LEA["Forest"]))

    offers = game.cast_cost_offers(0, card)
    assert offers == [{
        "kind": "optional_cost", "symbols": "sacrifice a land",
        "label": "buyback", "repeatable": False, "max_times": 1, "times": 0,
    }]

    declined = game.cast_target_spec(0, card)
    assert declined["kind"] == "none"
    assert not declined.get("sacrifice_cost")

    taken = game.cast_target_spec(
        0, card, optional_cost_payments={"sacrifice a land": 1},
    )
    assert taken["kind"] == "land" and taken["sacrifice_cost"] is True
    assert [t["name"] for t in taken["valid_targets"]] == ["Forest"]


@pytest.mark.cr("601.2b", "201.2", "701.23a")
def test_g4_mask_of_the_mimic_tutors_the_targets_name(set_pool):
    """"As an additional cost to cast this spell, sacrifice a creature." /
    "Search your library for a card with the same name as target nontoken
    creature, put that card onto the battlefield, then shuffle."

    The cost sentence was already read — the census' refusal site for it was
    the *grammar's*, and ``cast_costs.additional_cost_for_line`` claims that
    line in full. What nothing read was the search's noun phrase: a name
    comparison against an object the same sentence **chooses**, so the name is
    not knowable until the spell is cast and what the payload carries is the
    question rather than the answer.
    """
    game, caster, victim = _g4_duel([set_pool("STH")["Mask of the Mimic"]])
    caster.battlefield.append(Permanent(card=_G4_LEA["Mons's Goblin Raiders"]))
    victim.battlefield.append(Permanent(card=_G4_LEA["Serra Angel"]))
    caster.library = [
        _G4_LEA["Black Lotus"], _G4_LEA["Serra Angel"], _G4_LEA["Forest"],
    ]

    spec = game.cast_target_spec(0, set_pool("STH")["Mask of the Mimic"])
    assert spec["kind"] == "creature"
    assert spec["cost_spec"]["sacrifice_cost"] is True, "the sacrifice is its own picker"

    result = game.cast_from_hand(
        0, "Mask of the Mimic", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert caster.battlefield == [], "the additional cost ate the Goblin"

    game.resolve_top_of_stack()
    pending = game.pending_search_library
    assert pending is not None
    assert pending["restrictions"]["named"] == "Serra Angel", (
        "the name is read off the chosen target as the search is armed"
    )

    assert not game.confirm_search_library(0, 0), "Black Lotus is not that name"
    assert game.confirm_search_library(0, 1)
    assert [p.card.name for p in caster.battlefield] == ["Serra Angel"]


@pytest.mark.cr("608.2b", "701.23a")
def test_g4_a_name_from_a_target_that_left_finds_nothing(set_pool):
    """The dropped-narrowing direction, asserted rather than assumed.

    ``named_from_target`` is a question, and a search whose question nothing
    answered must find **no** card rather than every card — so the key alone,
    with no name behind it, refuses each candidate.
    """
    from engine.search_filters import search_matches

    card = _G4_LEA["Serra Angel"]
    assert not search_matches(card, {"restrictions": {"named_from_target": True}})
    assert search_matches(
        card,
        {"restrictions": {"named_from_target": True, "named": "Serra Angel"}},
    )

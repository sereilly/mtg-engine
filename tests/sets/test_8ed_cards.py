"""Eighth Edition — the reprint set that brought eleven cards.

The fourth core set in a row of the same shape: 342 unique cards, 331 of them
already in the pool and **eleven** that were not, because Portal, Portal Three
Kingdoms and the Starter sets printed them first and `cards/manifest.json`
carries none of those. So the premise is asserted by name, as 6ED's and 7ED's
twins assert theirs.

Ten of the eleven arrived compiling; Balance of Power is the one this file's
grammar work bought ("if target opponent has more cards in hand than you" as a
condition, and "the difference" bound to the two counts it compared). Each was
driven in a headless game before its test was written, and the tests assert
what the games showed. Nothing else in the set has a test here — a test that
Air Elemental flies would be another copy of one written for Alpha.
"""

from __future__ import annotations

import json

import pytest

from engine import Game, PlayerState
from engine.card_loader import (manifest_measured_sets, manifest_set_path,
                                manifest_sets)
from engine.models import Permanent
from engine.oracle import compile_card_oracle, simple_card_keywords

from tests.helpers import resolve_stack

# The eleven cards 8ED brings to this pool. Named rather than derived, for
# 7ED's reason: a derived list agrees with whatever the card file says, and the
# assertion below exists to disagree with it when a re-fetch changes it.
NEW_TO_THE_POOL = [
    "Ambition's Cost", "Balance of Power", "Coral Eel", "Giant Badger",
    "Norwood Ranger", "Peach Garden Oath", "Primeval Force", "Sea Eagle",
    "Silverback Ape", "Swarm of Rats", "Vampiric Spirit",
]

_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}


def _printed_before_eighth_edition(set_cards) -> set[str]:
    """The oracle ids printed in a shipped set released **before** 8ED.

    By release date rather than by manifest index, so it answers in either
    manifest role, and no set shipped later can change it — 7ED's premise
    tests asked "every other shipped set" and went red at this set's promotion,
    because 8ED reprints nine of 7ED's seventeen."""
    released = {
        entry["code"]: entry["released"]
        for entry in (*manifest_sets(), *manifest_measured_sets())
    }
    return {
        card.oracle_id
        for code, date in released.items()
        if date < released["8ED"]
        for card in set_cards(code)
        if card.oracle_id
    }


def _duel(pool, *, hand=(), opp_hand=(), library=(), mana=None,
          interactive=(0, 1)) -> Game:
    """Two seats, costs enforced, and a pool of mana to pay them from."""
    me = PlayerState(
        name="Me", hand=[pool[n] for n in hand],
        library=[pool[n] for n in library] or [pool["Forest"]] * 12,
    )
    opp = PlayerState(
        name="Opp", hand=[pool[n] for n in opp_hand], library=[pool["Island"]] * 12,
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    me.mana_pool.update(_RICH if mana is None else mana)
    return game


def _put(game: Game, seat: int, card) -> Permanent:
    """Onto the battlefield through the engine's own entry seam, past its
    summoning sickness."""
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _resolve_until_asked(game: Game) -> None:
    """Resolve until the stack is empty or a prompt is owed — `resolve_stack`
    would answer the very prompt a test is about to read."""
    for _ in range(20):
        if not game.stack or game.pending_choices:
            return
        if not game.resolve_top_of_stack():
            return
    raise AssertionError("the stack never settled")


def _to_declare_attackers(game: Game, active: int = 0) -> None:
    """Step the real turn structure into the declare-attackers step."""
    game.active_player_index = active
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            return
    raise AssertionError(f"combat never reached declare attackers: {game.current_step}")


# --- the set's relationship to the pool ---


def test_eighth_edition_brings_exactly_eleven_cards_the_pool_did_not_have(set_cards):
    """Both directions: each of the eleven is printed in no shipped set
    released before 8ED, and no twelfth card is — and, with nothing of 8ED's
    in M21 alone (next test), these are the cards the pool had never seen.
    Asked of the earlier sets rather than of every other shipped set, so a
    later set reprinting one of them cannot turn this red."""
    earlier = _printed_before_eighth_edition(set_cards)
    novel = sorted(
        card.name for card in set_cards("8ED") if card.oracle_id not in earlier
    )
    assert novel == NEW_TO_THE_POOL, (
        f"8ED cards printed in no shipped set released before it: {novel}"
    )


def test_no_reprint_takes_its_origin_from_the_manifest_index(set_cards):
    """The origin trap (CLAUDE.md, "The manifest"): a card printed here and in
    M21 — the one shipped set ahead of its turn in release order — and in no
    earlier set would have its origin decided by where 8ED is inserted, with
    every other guard green. 8ED has none.

    Asked of M21 rather than of "every other printing is later", which grows
    with each later set reprinting an 8ED original though none of those is
    position-dependent (each is inserted after 8ED). No later promotion can
    change this answer.
    """
    earlier = _printed_before_eighth_edition(set_cards)
    in_m21 = {card.oracle_id for card in set_cards("M21")}
    position_dependent = sorted(
        card.name
        for card in set_cards("8ED")
        if card.oracle_id in in_m21 and card.oracle_id not in earlier
    )
    assert position_dependent == []


def test_the_set_is_342_unique_cards_from_710_printings(set_cards):
    """Eighth Edition is 350 numbered cards each with its foil (42 and 42★),
    plus ten printings with no foil twin: S1–S7, the seven cards printed only in
    the starter decks (two of them, Sea Eagle and Silverback Ape, among the
    eleven new to the pool), and three alternate arts (121s, 125s, 129s).
    Pinned because the dedupe happens in `load_cards`, so the raw file is the
    only place the printing count is visible.
    """
    raw = json.loads(
        manifest_set_path("8ED", include_measured=True).read_text(encoding="utf-8")
    )
    assert len(raw) == 710
    assert len(set_cards("8ED")) == 342

    numbers = [entry["collector_number"] for entry in raw]
    foils = sorted(number.replace("★", "") for number in numbers if "★" in number)
    plain = sorted(number for number in numbers if "★" not in number)
    assert len(foils) == 350 and set(foils) <= set(plain)
    specials = {
        entry["collector_number"]: entry["name"]
        for entry in raw
        if entry["collector_number"] in set(plain) - set(foils)
    }
    assert specials == {
        "S1": "Eager Cadet", "S2": "Vengeance", "S3": "Giant Octopus",
        "S4": "Sea Eagle", "S5": "Vizzerdrix", "S6": "Enormous Baloth",
        "S7": "Silverback Ape", "121s": "Carrion Wall",
        "125s": "Death Pits of Rath", "129s": "Drudge Skeletons",
    }


def test_every_card_compiles_supported(set_cards):
    """What promotion will claim, asserted of the set by name. 341 of the 342
    arrived this way; Balance of Power is the one this file's grammar bought."""
    unsupported = sorted(
        card.name for card in set_cards("8ED") if not compile_card_oracle(card).supported
    )
    assert not unsupported, f"unsupported 8ED cards: {unsupported}"


# --- PROMOTION ---------------------------------------------------------------
#
# Asserted from the day 8ED moved to `sets` at index 37, between Scourge and
# M21. They read `load_catalog`, which does not load a measured set.


def test_eleven_cards_are_originally_printed_in_eighth_edition(set_cards, catalog_by_name):
    """Exactly the eleven the pool had never seen: with no reprint whose only
    other printing here is later (the origin-trap test above), the insert
    position decides no card's origin, so this list is the novelty list. The
    wrong-insert rehearsal (8ED appended after M21) turned only the
    printing-order guard red, as it must when nothing here depends on the
    index."""
    originates = sorted(
        card.name
        for card in set_cards("8ED")
        if catalog_by_name[card.name].original_printing == "8ed"
    )
    assert originates == NEW_TO_THE_POOL


def test_promoting_the_set_actually_recorded_its_printings(set_cards, catalog_by_name):
    """The positive half, and what makes the origin test mean anything: "only
    eleven cards originate in 8ED" also passes if the set was never loaded.
    Every 8ED card carries `8ed` in `printings` — that, and not its origin, is
    what promotion added for the other 331."""
    cards = set_cards("8ED")
    assert len(cards) == 342
    missing = sorted(
        card.name for card in cards
        if "8ed" not in catalog_by_name[card.name].printings
    )
    assert not missing, f"8ED cards the catalog records no 8ed printing for: {missing}"


def test_every_card_ships_supported(set_cards, catalog_by_name):
    """What promotion claims, asserted of the set by name so a card dropped
    from the catalog fails here rather than passing by absence."""
    unsupported = sorted(
        card.name
        for card in set_cards("8ED")
        if not compile_card_oracle(catalog_by_name[card.name]).supported
    )
    assert not unsupported, f"8ED cards the catalog does not support: {unsupported}"


# --- Balance of Power ---


def test_balance_of_power_compiles_to_the_two_counts_its_condition_compared(set_pool):
    """"If target opponent has more cards in hand than you, draw cards equal to
    the difference."

    The condition is the hand count measured against the caster's
    (``more_than_you``, the op "an opponent controls more lands than you"
    already carries), and "the difference" is bound to the same two counts —
    the target's hand less the caster's, the ``minus_count`` spec Bulwark's
    "the number of cards in your hand minus the number of cards in that
    player's hand" travels. The two halves name one seat: the opponent the
    spell targets.
    """
    (instruction,) = compile_card_oracle(set_pool("8ED")["Balance of Power"]).instructions
    assert instruction.kind == "if_then"
    assert instruction.payload["condition"] == {
        "kind": "zone_card_count", "player": "target_opponent", "zone": "hand",
        "op": "more_than_you", "value": 0,
    }
    (draw,) = instruction.payload["then"]
    assert draw.kind == "draw_controller_cards"
    assert draw.payload == {
        "amount": "x",
        "x_from_count": {
            "zone": "hand", "owner": "target_opponent", "filter": {},
            "minus_count": {"zone": "hand", "owner": "you", "filter": {}},
        },
    }


def test_balance_of_power_draws_the_difference_counted_as_it_resolves(set_pool):
    """Five cards against one: four drawn. The caster's hand is counted while
    the spell is on the stack, so Balance of Power itself is not in it — the
    card's ruling (2004-10-04): "The number of cards is counted during
    resolution." The opponent's hand is looked at, not touched."""
    pool = set_pool("8ED")
    game = _duel(
        pool, hand=["Balance of Power", "Plains"], opp_hand=["Island"] * 5,
        library=["Forest", "Swamp", "Mountain", "Island", "Plains", "Forest"],
    )
    me, opp = game.players

    assert game.cast_from_hand(0, "Balance of Power", target_player_index=1).supported
    resolve_stack(game)

    assert _names(me.hand) == ["Plains", "Forest", "Swamp", "Mountain", "Island"]
    assert len(opp.hand) == 5
    assert "Me drew 4 card(s) (Balance of Power)" in game.log
    assert _names(me.graveyard) == ["Balance of Power"]


@pytest.mark.parametrize(
    ("mine", "theirs"), [(3, 3), (4, 2)], ids=["level hands", "the caster ahead"],
)
def test_balance_of_power_does_nothing_unless_the_opponent_is_ahead(set_pool, mine, theirs):
    """"More" is strict: level hands draw nothing, and a caster who is ahead
    draws nothing rather than a negative number (CR 107.1b)."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Balance of Power"] + ["Plains"] * mine, opp_hand=["Island"] * theirs)
    me = game.players[0]

    assert game.cast_from_hand(0, "Balance of Power", target_player_index=1).supported
    resolve_stack(game)

    assert _names(me.hand) == ["Plains"] * mine
    assert len(me.library) == 12
    assert not any("drew" in line for line in game.log)


def test_balance_of_power_recounts_a_hand_that_changed_in_response(set_pool):
    """CR 608.2h: the counts are taken once, when the effect is applied — not
    when the spell was cast. Cast at one card against six (a difference of
    five), then Inspiration in response puts two more in the caster's hand: the
    spell resolves at three against six and draws three."""
    pool = set_pool("8ED")
    game = _duel(
        pool, hand=["Balance of Power", "Inspiration", "Plains"],
        opp_hand=["Island"] * 6, library=["Forest"] * 12,
    )
    me = game.players[0]

    assert game.queue_from_hand(0, "Balance of Power", target_player_index=1).supported
    assert game.queue_from_hand(0, "Inspiration", target_player_index=0).supported
    assert _names(game.stack) == ["Balance of Power", "Inspiration"]
    resolve_stack(game)

    assert _names(me.hand) == ["Plains"] + ["Forest"] * 5, "two from Inspiration, three from the difference"
    assert "Me drew 3 card(s) (Balance of Power)" in game.log


def test_balance_of_power_targets_an_opponent_and_counts_only_that_one(set_pool):
    """The picker offers opponents only, and a self-target is refused before
    anything is paid. At a three-seat table the condition and the difference
    are both about the opponent the spell named: aimed at the one with the
    smaller hand it draws nothing, though the other opponent is far ahead."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Balance of Power"], opp_hand=["Island"] * 5)
    spec = game.cast_target_spec(0, pool["Balance of Power"])
    assert spec["valid_targets"] == [{"kind": "player", "seat": 1}]
    refused = game.cast_from_hand(0, "Balance of Power", target_player_index=0)
    assert not refused.supported
    assert _names(game.players[0].hand) == ["Balance of Power"]
    assert sum(game.players[0].mana_pool.values()) == sum(_RICH.values()), "nothing was spent"

    me = PlayerState(name="Me", hand=[pool["Balance of Power"], pool["Plains"]],
                     library=[pool["Forest"]] * 12)
    short = PlayerState(name="Short", hand=[pool["Island"]])
    long = PlayerState(name="Long", hand=[pool["Island"]] * 7)
    table = Game(players=[me, short, long])
    table.interactive_seats = set()
    me.mana_pool.update(_RICH)

    assert table.cast_from_hand(0, "Balance of Power", target_player_index=1).supported
    resolve_stack(table)
    assert _names(me.hand) == ["Plains"]

    me.hand.append(pool["Balance of Power"])
    assert table.cast_from_hand(0, "Balance of Power", target_player_index=2).supported
    resolve_stack(table)
    assert _names(me.hand) == ["Plains"] + ["Forest"] * 6, "seven against one"


# --- the ten that arrived compiling ---


def test_ambitions_cost_draws_three_and_loses_three(set_pool):
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Ambition's Cost"], library=["Island", "Swamp", "Forest", "Plains"])
    me = game.players[0]

    assert game.cast_from_hand(0, "Ambition's Cost").supported
    resolve_stack(game)

    assert _names(me.hand) == ["Island", "Swamp", "Forest"]
    assert me.life == 17
    assert _names(me.graveyard) == ["Ambition's Cost"]


def test_peach_garden_oath_gains_two_for_each_creature_its_caster_controls(set_pool):
    """Two creatures are four life; the opponent's creature is nobody's count
    but its controller's."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Peach Garden Oath", "Peach Garden Oath"])
    me = game.players[0]
    _put(game, 1, pool["Silverback Ape"])

    assert game.cast_from_hand(0, "Peach Garden Oath").supported
    resolve_stack(game)
    assert me.life == 20, "no creature of its caster's, no life"

    _put(game, 0, pool["Coral Eel"])
    _put(game, 0, pool["Sea Eagle"])
    assert game.cast_from_hand(0, "Peach Garden Oath").supported
    resolve_stack(game)
    assert me.life == 24
    assert "Me gained 4 life from Peach Garden Oath (20 -> 24)" in game.log


def test_vampiric_spirits_life_loss_is_an_entry_trigger_on_the_stack(set_pool):
    """"When this creature enters, you lose 4 life." CR 603.3: the Spirit is on
    the battlefield, a 4/3 flier, with its controller's life still untouched
    until the trigger resolves."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Vampiric Spirit"])
    me = game.players[0]

    assert game.queue_from_hand(0, "Vampiric Spirit").supported
    assert game.resolve_top_of_stack(), "the creature spell resolves"
    (spirit,) = game.controlled_by(0)
    assert [item.ability_text for item in game.stack] == [
        "When this creature enters, you lose 4 life.",
    ]
    assert me.life == 20

    resolve_stack(game)
    assert me.life == 16
    assert (spirit.effective_power, spirit.effective_toughness) == (4, 3)
    assert spirit.has_keyword("flying")


def test_swarm_of_rats_counts_the_rats_its_controller_controls(set_pool):
    """A characteristic-defining ability (CR 604.3): power is the number of
    Rats its controller controls, itself included, and toughness is the printed
    1. An opponent's Rat is not counted."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Swarm of Rats", "Swarm of Rats"])

    assert game.cast_from_hand(0, "Swarm of Rats").supported
    resolve_stack(game)
    (first,) = game.controlled_by(0)
    assert (first.effective_power, first.effective_toughness) == (1, 1)

    theirs = _put(game, 1, pool["Swarm of Rats"])
    assert first.effective_power == 1, "the opponent's Rat is not counted"
    assert theirs.effective_power == 1

    assert game.cast_from_hand(0, "Swarm of Rats").supported
    resolve_stack(game)
    assert [(p.effective_power, p.effective_toughness) for p in game.controlled_by(0)] == [(2, 1), (2, 1)]


def test_primeval_force_stays_when_three_forests_are_sacrificed(set_pool):
    """"When this creature enters, sacrifice it unless you sacrifice three
    Forests." CR 118.12a: "unless" is an offer to its controller, asked as the
    trigger resolves. Taken, the three Forests go and the 8/8 stays."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Primeval Force"])
    for _ in range(3):
        _put(game, 0, pool["Forest"])

    assert game.cast_from_hand(0, "Primeval Force").supported
    _resolve_until_asked(game)
    (choice,) = game.pending_choices_of("optional_pay", 0)
    assert choice.data["card_name"] == "Primeval Force"
    assert game.confirm_optional_pay(0, accept=True)
    resolve_stack(game)

    (force,) = game.controlled_by(0)
    assert force.card.name == "Primeval Force"
    assert (force.effective_power, force.effective_toughness) == (8, 8)
    assert _names(game.players[0].graveyard) == ["Forest"] * 3


def test_primeval_force_is_sacrificed_when_its_controller_declines(set_pool):
    """The other answer: declined, the Force goes and the Forests stay."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Primeval Force"])
    for _ in range(3):
        _put(game, 0, pool["Forest"])

    assert game.cast_from_hand(0, "Primeval Force").supported
    _resolve_until_asked(game)
    assert game.confirm_optional_pay(0, accept=False)
    resolve_stack(game)

    assert _names(game.controlled_by(0)) == ["Forest"] * 3
    assert _names(game.players[0].graveyard) == ["Primeval Force"]


def test_primeval_force_with_two_forests_cannot_pay_and_is_sacrificed(set_pool):
    """Two Forests cannot pay three, so the Force is sacrificed and the two
    Forests are not — nothing is paid part of the way (CR 118.12)."""
    pool = set_pool("8ED")
    game = _duel(pool, hand=["Primeval Force"], interactive=())
    for _ in range(2):
        _put(game, 0, pool["Forest"])

    assert game.cast_from_hand(0, "Primeval Force").supported
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert _names(game.controlled_by(0)) == ["Forest", "Forest"]
    assert _names(game.players[0].graveyard) == ["Primeval Force"]


def test_giant_badger_gets_plus_two_plus_two_when_it_blocks(set_pool):
    """"Whenever this creature blocks, it gets +2/+2 until end of turn." The
    trigger goes on the stack as the block is declared (CR 509.3a) and resolves
    before damage, so the 4/4 Badger kills a Hill Giant and survives it; the
    bonus ends at cleanup (CR 514.2)."""
    pool = set_pool("8ED")
    game = _duel(pool)
    giant = _put(game, 0, pool["Hill Giant"])
    badger = _put(game, 1, pool["Giant Badger"])

    _to_declare_attackers(game)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    assert _names(game.stack) == ["Giant Badger"]
    resolve_stack(game)
    assert (badger.effective_power, badger.effective_toughness) == (4, 4)

    for _ in range(8):
        if game.current_turn_phase != "combat":
            break
        game.advance_combat_phase()
    assert giant not in list(game.controlled_by(0))
    assert badger in list(game.controlled_by(1)) and badger.damage_marked == 3

    game.resolve_cleanup_step(0)
    assert (badger.effective_power, badger.effective_toughness) == (2, 2)
    assert badger.damage_marked == 0


def test_giant_badger_stays_a_two_two_when_it_does_not_block(set_pool):
    pool = set_pool("8ED")
    game = _duel(pool)
    _put(game, 0, pool["Hill Giant"])
    badger = _put(game, 1, pool["Giant Badger"])

    _to_declare_attackers(game)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]

    assert game.stack == []
    assert (badger.effective_power, badger.effective_toughness) == (2, 2)


#: The four new cards with nothing to do but be their numbers — three vanilla
#: and one with a lone keyword — as (cost, type line, power, toughness,
#: keywords).
PLAIN = {
    "Coral Eel": ("{1}{U}", "Creature — Fish", 2, 1, ()),
    "Norwood Ranger": ("{G}", "Creature — Elf Scout Ranger", 1, 2, ()),
    "Silverback Ape": ("{3}{G}{G}", "Creature — Ape", 5, 5, ()),
    "Sea Eagle": ("{1}{U}", "Creature — Bird", 1, 1, ("flying",)),
}


@pytest.mark.parametrize("name", sorted(PLAIN))
def test_a_plain_new_creature_is_its_printed_numbers_and_nothing_else(set_pool, name):
    """`simple_card_keywords` answering the keyword list (or `()`) is what
    auto-passes the card in `CARD_VERIFICATION.md`, so the text is asserted to
    be exactly that and the card is cast for its printed cost and read back off
    the battlefield, through the layers."""
    pool = set_pool("8ED")
    card = pool[name]
    cost, type_line, power, toughness, keywords = PLAIN[name]
    program = compile_card_oracle(card)

    assert simple_card_keywords(card) == keywords
    assert program.supported
    assert [(i.kind, i.value) for i in program.instructions] == [
        ("keyword_line", word) for word in keywords
    ], "nothing but its keyword lines"
    assert not (program.activated_abilities or program.triggered_abilities)
    assert (card.mana_cost, card.type_line) == (cost, type_line)

    colour = cost[-2]
    game = _duel(pool, hand=[name], mana={colour: int(card.cmc)}, interactive=())
    assert game.cast_from_hand(0, name).supported
    resolve_stack(game)
    (perm,) = game.controlled_by(0)
    assert (perm.effective_power, perm.effective_toughness) == (power, toughness)
    assert all(perm.has_keyword(word) for word in keywords)
    assert sum(game.players[0].mana_pool.values()) == 0, "it cost exactly what it prints"

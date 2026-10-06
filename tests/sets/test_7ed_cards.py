"""Seventh Edition — the reprint set that brought seventeen cards.

4ED and 5ED shipped without implementing a card, and Classic Sixth Edition was
the first where that was only *almost* true: two of its 335 had their earlier
printing in Portal, a set `cards/manifest.json` does not carry. 7ED is the
same shape with the number moved — 335 unique cards, 318 of them already in
the pool and **seventeen** that were not, for 6ED's reason (Portal, Portal
Second Age and Starter printed them first).

So the premise is asserted by name, as `test_6ed_cards.py` asserts its own:
exactly these seventeen are new. Which cards *originate* in 7ED is a different
question and is not answered here — it turns on the set's manifest index, and
the promotion section below says what is left for the day that index exists.

The seventeen get per-card tests for the ordinary reason (SET_PLAYBOOK.md
Phase 3). Fifteen of them arrived compiling, and "supported" means only that
some line compiled, so each of those was driven in a headless game before its
test was written and the tests assert what the games showed: boards, life
totals, zones, the log. Nothing else in the set has a test here — a test that
Air Elemental flies would be a seventh copy of one written for Alpha.
"""

from __future__ import annotations

import collections
import json

import pytest

from engine import Game, PlayerState
from engine.card_loader import (manifest_measured_sets, manifest_set_path,
                                manifest_sets)
from engine.color_changes import change_color
from engine.combat_assignment import may_assign_as_unblocked
from engine.models import Permanent
from engine.oracle import compile_card_oracle, simple_card_keywords
from engine.targeting import derive_cast_spec

from tests.helpers import _mk_card, resolve_stack

# The seventeen cards 7ED brings to this pool. Named rather than derived: a
# derived list agrees with whatever the card file happens to say, and the point
# of the assertion below is to disagree with it when a re-fetch changes it.
NEW_TO_THE_POOL = [
    "Baleful Stare", "Breath of Life", "Dakmor Lancer", "Eager Cadet",
    "Giant Octopus", "Goblin Chariot", "Goblin Glider", "Knight Errant",
    "Monstrous Growth", "Pride of Lions", "Sacred Nectar", "Sleight of Hand",
    "Starlight", "Trained Orgg", "Vengeance", "Vizzerdrix", "Volcanic Hammer",
]

_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}


def _other_shipped_codes() -> list[str]:
    """Every shipped set but this one — true while 7ED is `measured` and still
    true the day it moves, which is what lets these tests survive promotion."""
    return [entry["code"] for entry in manifest_sets() if entry["code"] != "7ED"]


def _duel(pool, *, hand=(), opp_hand=(), library=(), graveyard=(),
          opp_graveyard=(), mana=None, interactive=(0, 1)) -> Game:
    """Two seats, costs enforced, and a pool of mana to pay them from — so a
    refused cast can be shown to have spent nothing."""
    me = PlayerState(
        name="Me", hand=[pool[n] for n in hand],
        library=[pool[n] for n in library] or [pool["Forest"]] * 12,
        graveyard=[pool[n] for n in graveyard],
    )
    opp = PlayerState(
        name="Opp", hand=[pool[n] for n in opp_hand],
        library=[pool["Forest"]] * 12,
        graveyard=[pool[n] for n in opp_graveyard],
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    me.mana_pool.update(_RICH if mana is None else mana)
    return game


def _put(game: Game, seat: int, card, *, tapped: bool = False) -> Permanent:
    """Onto the battlefield through the engine's own entry seam, past its
    summoning sickness."""
    perm = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    perm.tapped = tapped
    return perm


def _names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _names_offered(game: Game, card) -> list[str]:
    """The permanents or graveyard cards the cast picker offers seat 0."""
    return [target["name"] for target in game.cast_target_spec(0, card)["valid_targets"]]


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
    """Step the real turn structure into the declare-attackers step, where
    `advance_combat_phase` stops because a declaration is owed."""
    game.active_player_index = active
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            return
    raise AssertionError(f"combat never reached declare attackers: {game.current_step}")


def _finish_combat(game: Game) -> None:
    for _ in range(8):
        if game.current_turn_phase != "combat":
            return
        game.advance_combat_phase()
    raise AssertionError(f"combat never ended: {game.current_step}")


# --- the set's relationship to the pool ---


def test_seventh_edition_brings_exactly_seventeen_cards_the_pool_did_not_have(set_cards):
    """The premise everything else about this set rests on, in both directions:
    each of the seventeen is printed in no other shipped set, and no eighteenth
    card is.

    "New to the pool" is asked of the whole shipped pool and not of the sets to
    7ED's left, which is the one place this departs from 6ED's twin. That
    question needs a manifest index, and 7ED has none while it is `measured` —
    and the two answers differ by a card (see the next test).
    """
    elsewhere = {
        card.oracle_id
        for code in _other_shipped_codes()
        for card in set_cards(code)
        if card.oracle_id
    }
    novel = sorted(
        card.name for card in set_cards("7ED") if card.oracle_id not in elsewhere
    )
    assert novel == NEW_TO_THE_POOL, f"7ED cards printed in no other shipped set: {novel}"


def test_one_reprint_takes_its_origin_from_the_manifest_index(set_cards):
    """Mind Rot is in 7ED and M21 and nowhere earlier, so where 7ED is inserted
    decides whether its origin reads `7ed` or `m21` — Stronghold's Shock, Urza's
    Saga's three, Invasion's Opt, Planeshift's Quirion Dryad, one more time.

    Measured against release dates rather than against an index, so it holds in
    either manifest role: a reprint is position-dependent when **every** other
    set that prints it was released after this one. Exactly one card is. When a
    re-fetch or a newly shipped set changes that list, the wrong-insert
    rehearsal at promotion has a different card to watch, and this says which.
    """
    released = {
        entry["code"]: entry["released"]
        for entry in (*manifest_sets(), *manifest_measured_sets())
    }
    printed_in: dict[str, set[str]] = collections.defaultdict(set)
    for code in _other_shipped_codes():
        for card in set_cards(code):
            printed_in[card.oracle_id].add(code)

    position_dependent = sorted(
        card.name
        for card in set_cards("7ED")
        if printed_in.get(card.oracle_id)
        and all(released[code] > released["7ED"] for code in printed_in[card.oracle_id])
    )
    assert position_dependent == ["Mind Rot"]


def test_the_set_is_335_unique_cards_from_708_printings(set_cards):
    """Seventh Edition is the first core set printed with a foil of every card,
    and Scryfall lists the foil as a printing of its own: collector number 42
    and 42★. So the raw file holds every card at least twice, and "708 vs 335"
    is not 373 cards going missing in the loader.

    Pinned for the reason 4ED's and 6ED's twins are: the dedupe happens in
    `load_cards`, so the raw file is the only place the printing count is
    visible, and a re-fetch that drops the foils (or doubles something else)
    changes a number nothing else reads.
    """
    raw = json.loads(
        manifest_set_path("7ED", include_measured=True).read_text(encoding="utf-8")
    )
    assert len(raw) == 708
    assert len(set_cards("7ED")) == 335

    numbers = [entry["collector_number"] for entry in raw]
    plain = sorted(number for number in numbers if "★" not in number)
    foils = sorted(number.replace("★", "") for number in numbers if "★" in number)
    assert len(plain) == 354 and plain == foils, (
        "every printing has its foil twin and nothing else is doubled"
    )
    counts = collections.Counter(entry["name"] for entry in raw)
    assert sorted(name for name, n in counts.items() if n > 2) == [
        "Charcoal Diamond", "Drudge Skeletons", "Forest", "Island", "Mountain",
        "Plains", "Raise Dead", "Scathe Zombies", "Swamp",
    ], "the cards printed with more than one art"


def test_every_card_compiles_supported(set_cards):
    """What promotion will claim, asserted of the set by name. 333 of the 335
    arrived this way; Sleight of Hand and Baleful Stare are the two this file's
    grammar work bought."""
    unsupported = sorted(
        card.name for card in set_cards("7ED") if not compile_card_oracle(card).supported
    )
    assert not unsupported, f"unsupported 7ED cards: {unsupported}"


# --- PROMOTION ---------------------------------------------------------------
#
# Asserted from the day 7ED moved to `sets` at index 29, between Planeshift and
# M21. Both depend on that index and on `load_catalog` reading the set, which
# is why the card group left them to the promotion.

#: Mind Rot is printed in 7ED and M21 and nowhere earlier in this pool, so the
#: set's manifest index decides its origin. Rehearsed both ways with the
#: promotion's own move script: appended after M21 it read `m21`, with the
#: prefix guard green and only `test_the_shipped_sets_are_in_printing_order`
#: failing; at index 29 it reads `7ed`.
ORIGIN_DECIDED_BY_THE_INDEX = "Mind Rot"


def test_eighteen_cards_are_originally_printed_in_seventh_edition(
    set_cards, catalog_by_name,
):
    """The seventeen the pool had never seen, **and Mind Rot** — the one
    reprint whose only other printing here is later. A reprint set is the shape
    for which the prefix guard is silent twice over (every other card already
    has an earlier origin, and the guard compares what was there before), so
    this is the assertion that goes red if the set is ever moved: appended
    after M21 the answer is seventeen."""
    originates = sorted(
        card.name
        for card in set_cards("7ED")
        if catalog_by_name[card.name].original_printing == "7ed"
    )
    assert originates == sorted(NEW_TO_THE_POOL + [ORIGIN_DECIDED_BY_THE_INDEX])
    assert list(catalog_by_name[ORIGIN_DECIDED_BY_THE_INDEX].printings) == ["7ed", "m21"]


def test_promoting_the_set_actually_recorded_its_printings(set_cards, catalog_by_name):
    """The positive half, and the reason the origin test above means anything:
    "only eighteen cards originate in 7ED" also passes if the set was never
    loaded. Every 7ED card must carry `7ed` in `printings` — that, and not its
    origin, is what promotion added for the other 317."""
    cards = set_cards("7ED")
    assert len(cards) == 335
    missing = sorted(
        card.name for card in cards
        if "7ed" not in catalog_by_name[card.name].printings
    )
    assert not missing, f"7ED cards the catalog records no 7ed printing for: {missing}"


def test_every_card_ships_supported(set_cards, catalog_by_name):
    """What promotion claims, asserted of the set by name so a card dropped
    from the catalog fails here rather than passing by absence."""
    unsupported = sorted(
        card.name
        for card in set_cards("7ED")
        if not compile_card_oracle(catalog_by_name[card.name]).supported
    )
    assert not unsupported, f"7ED cards the catalog does not support: {unsupported}"


# -----------------------------------------------------------------------------


# --- Sleight of Hand ---


def test_sleight_of_hand_keeps_the_chosen_card_and_bottoms_the_other(set_pool):
    """"Look at the top two cards of your library. Put one of them into your
    hand and the other on the bottom of your library."

    Impulse's sentence with "the other" where that prints "the rest", and no
    "in any order" behind it — one card has no order. Paid for with a real
    Island, and answered with the *second* card so the test cannot pass by
    taking whatever is on top.
    """
    pool = set_pool("7ED")
    game = _duel(
        pool, hand=["Sleight of Hand"], mana={},
        library=["Grizzly Bears", "Counterspell", "Forest", "Shock"],
    )
    island = _put(game, 0, pool["Island"])
    me = game.players[0]

    assert not game.cast_from_hand(0, "Sleight of Hand").supported, "{U} is owed"
    assert game.tap_land_for_mana(0, "Island", "U", permanent_id=island.permanent_id)
    assert game.cast_from_hand(0, "Sleight of Hand").supported
    assert game.waiting_prompt() is not None, "the resolution waits (CR 608.2)"
    assert _names(me.graveyard) == [], "and the spell is still resolving"

    assert game.confirm_look_top_pick(0, 1)

    assert _names(me.hand) == ["Counterspell"]
    assert _names(me.library) == ["Forest", "Shock", "Grizzly Bears"], (
        "the other card is under the library, not back on top"
    )
    assert _names(me.graveyard) == ["Sleight of Hand"]
    assert not game.stack


def test_sleight_of_hand_asks_which_card_and_never_for_an_order(set_pool):
    """The prompt is a choice between the two cards and nothing else.

    Not optional (the card says "put", not "you may"), bounded to the two
    looked-at positions, and — the part worth pinning — followed by no
    `reorder_library` prompt: with one card left there is nothing to order, and
    asking would be a decision the card never prints.
    """
    pool = set_pool("7ED")
    game = _duel(
        pool, hand=["Sleight of Hand"], library=["Grizzly Bears", "Counterspell", "Forest"],
    )
    assert game.cast_from_hand(0, "Sleight of Hand").supported

    (choice,) = game.pending_choices_of("look_top_pick")
    assert choice.player_index == 0
    assert choice.data["top_count"] == 2
    assert game.live_look_top_candidates(choice) == [0, 1]
    assert not game.confirm_look_top_pick(0, 2), "the third card was never looked at"
    assert not game.resolve_pending_choice("look_top_pick", 0, keep_index=None), (
        "taking neither is not an answer"
    )

    assert game.confirm_look_top_pick(0, 0)
    assert game.pending_choices == [], "no order is asked for"
    assert _names(game.players[0].library) == ["Forest", "Counterspell"]


@pytest.mark.parametrize(
    ("library", "hand_after"),
    [(["Shock"], ["Shock"]), ([], [])],
    ids=["one card left", "an empty library"],
)
def test_sleight_of_hand_over_a_short_library(set_pool, library, hand_after):
    """As much as can be done (CR 609.3): one card is looked at and taken with
    nothing to bottom, and none is a spell that resolves and does nothing —
    looking is not drawing, so an empty library costs nobody the game."""
    pool = set_pool("7ED")
    me = PlayerState(name="Me", hand=[pool["Sleight of Hand"]], library=[pool[n] for n in library])
    game = Game(players=[me, PlayerState(name="Opp")])
    game.interactive_seats = set()

    assert game.cast_from_hand(0, "Sleight of Hand").supported
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    game.check_state_based_actions()

    assert _names(me.hand) == hand_after
    assert me.library == []
    assert _names(me.graveyard) == ["Sleight of Hand"]
    assert not me.lost


# --- Baleful Stare ---


def test_baleful_stare_draws_for_each_mountain_and_each_red_card(set_pool):
    """"Target opponent reveals their hand. You draw a card for each Mountain
    and red card in it."

    Two Mountains and a Shock are three; a Taiga is a fourth, because "Mountain"
    is a land type and a dual land has it (CR 305.6); the Bears, the Island and
    the Counterspell are nothing. The hand is *revealed* — named in the log and
    on the structured feed the client reads — and it is not touched: this card
    looks, it does not take.
    """
    pool = set_pool("7ED")
    game = _duel(
        pool, hand=["Baleful Stare"],
        opp_hand=["Mountain", "Shock", "Grizzly Bears", "Mountain", "Island", "Counterspell"],
        library=["Forest", "Plains", "Swamp", "Island", "Mountain", "Forest"],
    )
    me, opp = game.players
    opp.hand.append(set_pool("LEA")["Taiga"])
    shown = _names(opp.hand)

    assert game.cast_from_hand(0, "Baleful Stare", target_player_index=1).supported
    resolve_stack(game)

    assert _names(me.hand) == ["Forest", "Plains", "Swamp", "Island"]
    assert _names(opp.hand) == shown, "a reveal moves nothing"
    assert f"Opp reveals their hand: {', '.join(shown)}" in game.log
    assert game.reveal_events[-1]["seat"] == 1
    assert game.reveal_events[-1]["cards"] == shown
    assert _names(me.graveyard) == ["Baleful Stare"]


def test_a_card_that_is_both_a_mountain_and_red_is_one_card(set_pool):
    """"Each Mountain and red card" counts cards, not qualities. A red card
    that is also a Mountain answers both halves of the union and is drawn for
    once — the reading a sum of two counts gets wrong, and no printed card in
    this pool can show, so the hand holds an invented one."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Baleful Stare"], opp_hand=["Shock", "Grizzly Bears"])
    me, opp = game.players
    opp.hand.append(
        _mk_card("Molten Peak", "{R}", "Land Creature — Mountain Elemental", "", colors=("R",))
    )

    assert game.cast_from_hand(0, "Baleful Stare", target_player_index=1).supported
    resolve_stack(game)

    assert len(me.hand) == 2, "the Shock and the Peak; the Peak once"


def test_baleful_stare_draws_nothing_from_an_empty_hand(set_pool):
    """An empty hand is still a reveal — the record is written, so the count
    behind it reads zero rather than a back-reference with nothing behind it."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Baleful Stare"])

    assert game.cast_from_hand(0, "Baleful Stare", target_player_index=1).supported
    resolve_stack(game)

    assert game.players[0].hand == []
    assert "Opp reveals their hand: (empty)" in game.log
    assert len(game.players[0].library) == 12


def test_baleful_stare_is_aimed_at_an_opponent_or_not_cast(set_pool):
    """"Target opponent" is a target: the picker offers the opposing seat and
    not the caster's own, and with no opponent who can be targeted the spell
    cannot be cast at all (CR 601.2c) — refused before anything is paid.

    Ivory Mask gives its controller shroud, which is the one way a two-player
    table has no opponent to name.
    """
    pool = set_pool("7ED")
    stare = pool["Baleful Stare"]
    game = _duel(pool, hand=["Baleful Stare"], opp_hand=["Mountain"], mana={"U": 3})

    assert derive_cast_spec(stare, compile_card_oracle(stare)) == {
        "kind": "player", "opponents_only": True,
    }
    spec = game.cast_target_spec(0, stare)
    assert spec["requires_target"]
    assert spec["valid_targets"] == [{"kind": "player", "seat": 1}]

    _put(game, 1, set_pool("MMQ")["Ivory Mask"])
    assert game.cast_target_spec(0, stare)["valid_targets"] == []
    refused = game.cast_from_hand(0, "Baleful Stare", target_player_index=1)
    assert not refused.supported
    assert game.players[0].mana_pool["U"] == 3, "nothing was spent"
    assert _names(game.players[0].hand) == ["Baleful Stare"]


# --- Breath of Life ---


def test_breath_of_life_offers_only_creature_cards_in_its_casters_graveyard(set_pool):
    """"Return target creature card from **your** graveyard to the battlefield."

    The picker is the possessive and the noun: two creature cards of the
    caster's, by graveyard slot, with the Shock between them and the
    opponent's Serra Angel left out. Naming either of those is refused and
    spends nothing — the picker is a hint, the cast path is the gate.
    """
    pool = set_pool("7ED")
    breath = pool["Breath of Life"]
    game = _duel(
        pool, hand=["Breath of Life"],
        graveyard=["Grizzly Bears", "Shock", "Hill Giant"], opp_graveyard=["Serra Angel"],
    )
    me, opp = game.players

    spec = game.cast_target_spec(0, breath)
    assert spec["kind"] == "graveyard_creature" and spec["own_graveyard_only"]
    assert [(t["seat"], t["index"], t["name"]) for t in spec["valid_targets"]] == [
        (0, 0, "Grizzly Bears"), (0, 2, "Hill Giant"),
    ]

    stolen = game.cast_from_hand(0, "Breath of Life", target_player_index=1, target_permanent_index=0)
    not_a_creature = game.cast_from_hand(0, "Breath of Life", target_player_index=0, target_permanent_index=1)
    assert not stolen.supported and not not_a_creature.supported
    assert me.mana_pool["W"] == 9 and _names(me.hand) == ["Breath of Life"]
    assert _names(opp.graveyard) == ["Serra Angel"]


def test_breath_of_life_returns_the_card_it_named(set_pool):
    """The chosen card, not the first creature card it finds — and onto the
    battlefield under its owner, where it is a new object that just arrived."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Breath of Life"], graveyard=["Grizzly Bears", "Shock", "Hill Giant"])
    me = game.players[0]

    assert game.cast_from_hand(
        0, "Breath of Life", target_player_index=0, target_permanent_index=2
    ).supported
    resolve_stack(game)

    assert _names(game.controlled_by(0)) == ["Hill Giant"]
    assert _names(me.graveyard) == ["Grizzly Bears", "Shock", "Breath of Life"]
    assert sum(me.mana_pool.values()) == sum(_RICH.values()) - 4, "{3}{W}"


def test_breath_of_life_does_nothing_if_its_card_is_gone_by_resolution(set_pool):
    """CR 608.2b. The named card is exiled in response; the spell leaves the
    stack without resolving and — the half that matters — does not fall back to
    the other creature card lying beside it, which nobody named."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Breath of Life"], graveyard=["Grizzly Bears", "Hill Giant"])
    me = game.players[0]

    assert game.queue_from_hand(
        0, "Breath of Life", target_player_index=0, target_permanent_index=1
    ).supported
    me.exile.append(me.graveyard.pop(1))
    resolve_stack(game)

    assert list(game.controlled_by(0)) == []
    assert _names(me.graveyard) == ["Grizzly Bears", "Breath of Life"]
    assert any("608.2b" in line for line in game.log)


# --- Starlight ---


def test_starlight_counts_the_black_creatures_its_target_controls(set_pool):
    """"You gain 3 life for each black creature target opponent controls."

    Two black creatures across the table are six life. The caster's own black
    creature is not the opponent's, the opponent's Bears are not black, and
    their Swamp is not a creature — each is on the board to be not counted.
    """
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Starlight"])
    _put(game, 1, pool["Scathe Zombies"])
    _put(game, 1, pool["Bog Imp"])
    _put(game, 1, pool["Grizzly Bears"])
    _put(game, 1, pool["Swamp"])
    _put(game, 0, pool["Drudge Skeletons"])

    assert game.cast_target_spec(0, pool["Starlight"])["valid_targets"] == [
        {"kind": "player", "seat": 1},
    ]
    assert game.cast_from_hand(0, "Starlight", target_player_index=1).supported
    resolve_stack(game)

    assert game.players[0].life == 26
    assert game.players[1].life == 20


def test_starlight_reads_colour_through_the_layers(set_pool):
    """Colour is CR 613 layer 5's answer, not the printed one. A green creature
    turned black counts and a black creature turned white does not — a count
    read off `card.colors` gets both of these backwards and passes every test
    with an unmodified board."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Starlight", "Starlight"])
    zombies = _put(game, 1, pool["Scathe Zombies"])
    bears = _put(game, 1, pool["Grizzly Bears"])
    change_color(zombies, "W")

    assert game.cast_from_hand(0, "Starlight", target_player_index=1).supported
    resolve_stack(game)
    assert game.players[0].life == 20, "the Zombies are white now"

    change_color(bears, "B")
    assert game.cast_from_hand(0, "Starlight", target_player_index=1).supported
    resolve_stack(game)
    assert game.players[0].life == 23, "and the Bears are black"


# --- Vengeance ---


def test_vengeance_may_only_name_a_tapped_creature(set_pool):
    """"Destroy target **tapped** creature." The adjective is the whole card.

    An untapped creature is not offered and naming it is refused with nothing
    spent (CR 601.2c); with nothing tapped anywhere the spell cannot be cast.
    """
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Vengeance"])
    me = game.players[0]
    giant = _put(game, 1, pool["Hill Giant"], tapped=True)
    bears = _put(game, 1, pool["Grizzly Bears"])

    assert _names_offered(game, pool["Vengeance"]) == ["Hill Giant"]
    refused = game.cast_from_hand(0, "Vengeance", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert me.mana_pool["W"] == 9 and _names(me.hand) == ["Vengeance"]

    giant.tapped = False
    assert _names_offered(game, pool["Vengeance"]) == []
    assert not game.cast_from_hand(0, "Vengeance").supported

    giant.tapped = True
    assert game.cast_from_hand(0, "Vengeance", target_permanent_ids=[giant.permanent_id]).supported
    resolve_stack(game)
    assert _names(game.controlled_by(1)) == ["Grizzly Bears"]
    assert _names(game.players[1].graveyard) == ["Hill Giant"]


def test_vengeance_misses_a_creature_that_untaps_in_response(set_pool):
    """CR 608.2b: the target is judged again as the spell resolves, against the
    same description it was announced under. A creature that has untapped is
    no longer "a tapped creature", so the spell leaves the stack unresolved —
    and the other creature, which is tapped and was never named, is left alone.
    """
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Vengeance"])
    giant = _put(game, 1, pool["Hill Giant"], tapped=True)
    _put(game, 1, pool["Grizzly Bears"], tapped=True)

    assert game.queue_from_hand(0, "Vengeance", target_permanent_ids=[giant.permanent_id]).supported
    giant.tapped = False
    resolve_stack(game)

    assert _names(game.controlled_by(1)) == ["Hill Giant", "Grizzly Bears"]
    assert _names(game.players[0].graveyard) == ["Vengeance"]
    assert any("608.2b" in line for line in game.log)


# --- Dakmor Lancer ---


def test_dakmor_lancers_entry_trigger_is_a_stack_object(set_pool):
    """"When this creature enters, destroy target nonblack creature."

    CR 603.3: the trigger goes on the stack when the Lancer enters, so there is
    a moment with the Lancer on the battlefield and its victim still alive. The
    target is named as the Lancer is cast — the engine's kept convention for an
    entry trigger — and a black creature is not among the ones it may name.
    """
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Dakmor Lancer"])
    _put(game, 1, pool["Scathe Zombies"])
    giant = _put(game, 1, pool["Hill Giant"])

    assert _names_offered(game, pool["Dakmor Lancer"]) == ["Hill Giant"]
    assert game.queue_from_hand(
        0, "Dakmor Lancer", target_permanent_ids=[giant.permanent_id]
    ).supported
    assert game.resolve_top_of_stack(), "the creature spell resolves"

    assert _names(game.controlled_by(0)) == ["Dakmor Lancer"]
    assert [item.ability_text for item in game.stack] == [
        "When this creature enters, destroy target nonblack creature.",
    ]
    assert giant in list(game.controlled_by(1)), "nothing has been destroyed yet"

    resolve_stack(game)
    assert _names(game.controlled_by(1)) == ["Scathe Zombies"]
    assert _names(game.players[1].graveyard) == ["Hill Giant"]


def test_dakmor_lancer_returned_by_breath_of_life_asks_for_its_target(set_pool):
    """The road onto the battlefield that is not a cast, taken with another of
    the set's new cards. Nothing was announced, so the trigger's controller is
    asked as it goes on the stack: the two nonblack creatures are offered, the
    black one is not an answer, and the creature named is the one destroyed.
    """
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Breath of Life"], graveyard=["Dakmor Lancer"])
    zombies = _put(game, 1, pool["Scathe Zombies"])
    _put(game, 1, pool["Grizzly Bears"])
    giant = _put(game, 1, pool["Hill Giant"])

    assert game.cast_from_hand(
        0, "Breath of Life", target_player_index=0, target_permanent_index=0
    ).supported
    _resolve_until_asked(game)

    (choice,) = game.pending_choices_of("trigger_target")
    assert choice.player_index == 0
    assert [target["name"] for target in choice.data["targets"]] == ["Grizzly Bears", "Hill Giant"]
    assert not game.confirm_trigger_target(0, permanent_id=zombies.permanent_id, seat=1)
    assert game.confirm_trigger_target(0, permanent_id=giant.permanent_id, seat=1)
    resolve_stack(game)

    assert _names(game.controlled_by(0)) == ["Dakmor Lancer"]
    assert _names(game.controlled_by(1)) == ["Scathe Zombies", "Grizzly Bears"]
    assert _names(game.players[1].graveyard) == ["Hill Giant"]


def test_dakmor_lancers_trigger_is_not_optional_and_needs_a_target(set_pool):
    """There is no "may". With one nonblack creature on the table and it the
    Lancer's own controller's, that creature is the target and dies; with none
    — the Lancer itself is black — the trigger has no legal target and is
    removed from the stack (CR 603.3d) rather than resolving at nothing.
    """
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Dakmor Lancer"], interactive=())
    _put(game, 1, pool["Scathe Zombies"])
    _put(game, 0, pool["Grizzly Bears"])

    assert game.cast_from_hand(0, "Dakmor Lancer").supported
    resolve_stack(game)
    assert _names(game.controlled_by(0)) == ["Dakmor Lancer"]
    assert _names(game.players[0].graveyard) == ["Grizzly Bears"]

    game = _duel(pool, hand=["Dakmor Lancer"], interactive=())
    _put(game, 1, pool["Scathe Zombies"])
    assert game.cast_from_hand(0, "Dakmor Lancer").supported
    resolve_stack(game)
    assert _names(game.controlled_by(0)) == ["Dakmor Lancer"]
    assert _names(game.controlled_by(1)) == ["Scathe Zombies"]
    assert any("no legal target" in line for line in game.log)


def test_dakmor_lancer_spares_a_creature_that_turns_black_in_response(set_pool):
    """The description is asked again at resolution: a target recoloured black
    while the trigger waits is no longer a nonblack creature and survives."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Dakmor Lancer"])
    bears = _put(game, 1, pool["Grizzly Bears"])

    assert game.queue_from_hand(
        0, "Dakmor Lancer", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.resolve_top_of_stack()
    change_color(bears, "B")
    resolve_stack(game)

    assert bears in list(game.controlled_by(1))


# --- Pride of Lions ---


def test_pride_of_lions_sends_its_damage_past_a_blocker(set_pool):
    """"You may have this creature assign its combat damage as though it
    weren't blocked." Thorn Elemental's line, word for word, and the same
    instruction — the offer is one static two cards print.

    Through the real combat steps: declared, blocked by the Bears, and — both
    seats here being interactive — **stopped at the damage step to be asked**,
    then answered with the offer taken (CR 510.1b in place of CR 510.1c). Four
    to the player; the blocker is untouched and still deals its own two.

    This test used to step straight through, "the damage step taken with no
    assignment given", and that was the defect it was standing on: a person at
    the table was never asked, so the offer was always taken for them. The
    unasked default is still the offer taken and is still pinned, for a seat
    nobody is sitting in, by Lone Wolf's twin of this test.
    """
    pool = set_pool("7ED")
    game = _duel(pool)
    pride = _put(game, 0, pool["Pride of Lions"])
    bears = _put(game, 1, pool["Grizzly Bears"])

    assert may_assign_as_unblocked(pride)
    assert [i.kind for i in compile_card_oracle(pool["Pride of Lions"]).instructions] == [
        i.kind for i in compile_card_oracle(pool["Thorn Elemental"]).instructions
    ] == ["may_assign_as_unblocked"]

    _to_declare_attackers(game)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()
    assert game.current_step == "combat_damage" and not game.combat_damage_resolved
    assert game.unblocked_assignments_to_ask() == [0]
    assert game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[pride.permanent_id]
    )[0]
    _finish_combat(game)

    assert game.players[1].life == 16
    assert bears.damage_marked == 0, "the blocker was assigned nothing"
    assert pride.damage_marked == 2, "and was not ignored by it"


def test_pride_of_lions_may_fight_its_blocker_instead(set_pool):
    """The other answer. The "may" is declined by assigning to the blocker,
    which is CR 510.1c's ordinary assignment: the Bears die and no damage
    reaches the player. Without this half the line would be a restriction.

    Given at the damage step directly, as Lone Wolf's twin of this test does.
    (That was once the only way to give it: the stepping resolved a single
    block's damage as it entered the step and had no point at which the
    attacker was asked. It stops there for an interactive seat now — the test
    above — and this is the other thing that seat may say.)
    """
    pool = set_pool("7ED")
    game = _duel(pool)
    pride = _put(game, 0, pool["Pride of Lions"])
    _put(game, 1, pool["Grizzly Bears"])

    _to_declare_attackers(game)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.current_step = "combat_damage"
    assert game.resolve_combat_damage(0, attacker_damage={0: {0: 4}})[0]
    game.check_state_based_actions()

    assert game.players[1].life == 20
    assert _names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert pride.damage_marked == 2


def test_pride_of_lions_is_asked_about_two_blockers_and_may_still_go_past(set_pool):
    """Double-blocked, the damage step stops for an assignment (two blockers is
    a division only the attacker can make) — and answering with none is still
    the offer taken: all four to the player, both blockers undamaged, and the
    Pride dead to the five they deal it."""
    pool = set_pool("7ED")
    game = _duel(pool)
    pride = _put(game, 0, pool["Pride of Lions"])
    bears = _put(game, 1, pool["Grizzly Bears"])
    giant = _put(game, 1, pool["Hill Giant"])

    _to_declare_attackers(game)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0, 1: 0})[0]
    game.advance_combat_phase()
    assert game.current_step == "combat_damage" and not game.combat_damage_resolved

    assert game.resolve_combat_damage(0)[0]
    game.check_state_based_actions()

    assert game.players[1].life == 16
    assert (bears.damage_marked, giant.damage_marked) == (0, 0)
    assert pride not in list(game.controlled_by(0))


# --- Goblin Glider ---


def test_goblin_glider_flies_over_and_never_blocks(set_pool):
    """"Flying" and "This creature can't block." Two lines that pull opposite
    ways, which is the card: a ground creature cannot block it and a flier can,
    and it blocks neither of them — not even the flier its flying would
    otherwise let it stop.
    """
    pool = set_pool("7ED")
    game = _duel(pool)
    glider = _put(game, 0, pool["Goblin Glider"])
    bears = _put(game, 1, pool["Grizzly Bears"])
    angel = _put(game, 1, pool["Serra Angel"])

    assert simple_card_keywords(pool["Goblin Glider"]) is None, "not a keyword-only card"
    assert game._has_keyword(glider, "flying")
    assert not game._can_block_attacker(bears, glider)
    assert game._can_block_attacker(angel, glider)
    assert not game._can_block_attacker(glider, bears)
    assert not game._can_block_attacker(glider, angel)

    _to_declare_attackers(game)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {0: 0})[0], "the Bears cannot reach it"
    assert game.declare_blockers(1, {})[0]
    _finish_combat(game)
    assert game.players[1].life == 19


def test_goblin_glider_cannot_be_declared_as_a_blocker(set_pool):
    """The restriction where it bites: its controller is attacked by a 2/2 the
    Glider would gladly chump, the declaration naming it is refused, and the
    damage comes through."""
    pool = set_pool("7ED")
    game = _duel(pool)
    _put(game, 0, pool["Goblin Glider"])
    _put(game, 1, pool["Grizzly Bears"])

    _to_declare_attackers(game, active=1)
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]
    game.advance_combat_phase()
    refused, why = game.declare_blockers(0, {0: 0})
    assert not refused and "Goblin Glider cannot block" in why
    assert game.declare_blockers(0, {})[0]
    _finish_combat(game)

    assert game.players[0].life == 18
    assert _names(game.controlled_by(0)) == ["Goblin Glider"]


# --- Goblin Chariot ---


def test_goblin_chariot_attacks_the_turn_it_is_cast(set_pool):
    """Haste (CR 702.10), against a control cast in the same main phase: the
    Trained Orgg beside it is refused as an attacker for the summoning sickness
    the Chariot ignores. A keyword-only card, so the verification tracker
    auto-passes it — and this is the game that claim is resting on.
    """
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Goblin Chariot", "Trained Orgg"], mana={"R": 10})
    game.active_player_index = 0

    assert simple_card_keywords(pool["Goblin Chariot"]) == ("haste",)
    assert game.cast_from_hand(0, "Goblin Chariot").supported
    assert game.cast_from_hand(0, "Trained Orgg").supported
    resolve_stack(game)
    assert game.players[0].mana_pool["R"] == 0, "{2}{R} and {6}{R}"
    chariot, orgg = game.controlled_by(0)

    _to_declare_attackers(game)
    assert not game.declare_attackers(
        0, [game.battlefield_index_of(orgg)], defending_player_index=1
    )[0]
    assert game.declare_attackers(
        0, [game.battlefield_index_of(chariot)], defending_player_index=1
    )[0]
    _finish_combat(game)

    assert game.players[1].life == 18
    assert chariot.tapped and not orgg.tapped


# --- Volcanic Hammer ---


def test_volcanic_hammer_deals_three_to_any_target(set_pool):
    """"Volcanic Hammer deals 3 damage to any target." Both halves of "any
    target" (CR 115.4), because they travel different paths: a creature has the
    damage marked and dies to it as a state-based action, a player loses life.
    """
    pool = set_pool("7ED")
    hammer = pool["Volcanic Hammer"]
    game = _duel(pool, hand=["Volcanic Hammer", "Volcanic Hammer"])
    giant = _put(game, 1, pool["Hill Giant"])

    assert derive_cast_spec(hammer, compile_card_oracle(hammer)) == {"kind": "any"}
    offered = game.cast_target_spec(0, hammer)["valid_targets"]
    assert [t["kind"] for t in offered] == ["player", "player", "permanent"]

    assert game.cast_from_hand(0, "Volcanic Hammer", target_player_index=1).supported
    resolve_stack(game)
    assert game.players[1].life == 17

    assert game.cast_from_hand(
        0, "Volcanic Hammer", target_permanent_ids=[giant.permanent_id]
    ).supported
    resolve_stack(game)
    game.check_state_based_actions()
    assert _names(game.players[1].graveyard) == ["Hill Giant"], "3 damage on a 3/3 (CR 704.5g)"
    assert sum(game.players[0].mana_pool.values()) == sum(_RICH.values()) - 4, "{1}{R}, twice"


# --- Monstrous Growth ---


def test_monstrous_growth_is_plus_four_plus_four_until_end_of_turn(set_pool):
    """"Target creature gets +4/+4 until end of turn." The number is the card
    (Giant Growth is three), and the duration is the other half of it: gone at
    cleanup, not a permanent pair of counters."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Monstrous Growth"])
    bears = _put(game, 0, pool["Grizzly Bears"])

    assert game.cast_from_hand(
        0, "Monstrous Growth", target_permanent_ids=[bears.permanent_id]
    ).supported
    resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)

    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


# --- Sacred Nectar ---


def test_sacred_nectar_gains_four_life_and_asks_for_nothing(set_pool):
    """"You gain 4 life." No target, so the picker has nothing to offer and the
    cast names nobody; the opponent's total is not part of the sentence."""
    pool = set_pool("7ED")
    game = _duel(pool, hand=["Sacred Nectar"])

    spec = game.cast_target_spec(0, pool["Sacred Nectar"])
    assert spec["kind"] == "none" and not spec["requires_target"]
    assert game.cast_from_hand(0, "Sacred Nectar").supported
    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (24, 20)
    assert _names(game.players[0].graveyard) == ["Sacred Nectar"]


# --- the five vanilla creatures ---

# Printed cost, type line, power and toughness, written out rather than read:
# these are the only things a vanilla creature is, so a table that agreed with
# the card file by construction would be asserting nothing.
VANILLA = {
    "Eager Cadet": ("{W}", "Creature — Human Soldier", 1, 1),
    "Knight Errant": ("{1}{W}", "Creature — Human Knight", 2, 2),
    "Giant Octopus": ("{3}{U}", "Creature — Octopus", 3, 3),
    "Vizzerdrix": ("{6}{U}", "Creature — Rabbit Beast", 6, 6),
    "Trained Orgg": ("{6}{R}", "Creature — Orgg", 6, 6),
}


@pytest.mark.parametrize("name", sorted(VANILLA))
def test_a_vanilla_creature_is_its_printed_numbers_and_nothing_else(set_pool, name):
    """A vanilla creature's test is that it *is* vanilla.

    `simple_card_keywords` answering `()` is what auto-passes the card in
    `CARD_VERIFICATION.md` — no abilities, so a manual check would exercise
    nothing card-specific. That claim is exactly as strong as the emptiness of
    the text, so the text is asserted empty and the card is then cast for its
    printed cost and read back off the battlefield, through the layers.
    """
    pool = set_pool("7ED")
    card = pool[name]
    cost, type_line, power, toughness = VANILLA[name]
    program = compile_card_oracle(card)

    assert card.oracle_text.strip() == ""
    assert simple_card_keywords(card) == ()
    assert program.supported
    assert not (program.instructions or program.activated_abilities or program.triggered_abilities)
    assert (card.mana_cost, card.type_line) == (cost, type_line)

    colour = cost[-2]
    game = _duel(pool, hand=[name], mana={colour: int(card.cmc)})
    assert game.cast_from_hand(0, name).supported
    resolve_stack(game)
    (perm,) = game.controlled_by(0)
    assert (perm.effective_power, perm.effective_toughness) == (power, toughness)
    assert perm.effective_colors == {colour}
    assert sum(game.players[0].mana_pool.values()) == 0, "it cost exactly what it prints"
    assert game.players[0].hand == []


def test_a_three_three_survives_two_damage_and_dies_to_the_third(set_pool):
    """The generic damage code the auto-pass defers to, run once for one of the
    five, so "no abilities" is a statement about a creature that has been in a
    game rather than one that has only been compiled."""
    pool = set_pool("7ED")
    game = _duel(pool)
    octopus = _put(game, 1, pool["Giant Octopus"])
    bears = _put(game, 0, pool["Grizzly Bears"])

    assert game._mark_damage_on_permanent(octopus, 2, source=bears) == 2
    game.check_state_based_actions()
    assert octopus in list(game.controlled_by(1))

    assert game._mark_damage_on_permanent(octopus, 1, source=bears) == 1
    game.check_state_based_actions()
    assert octopus not in list(game.controlled_by(1)), "CR 704.5g"

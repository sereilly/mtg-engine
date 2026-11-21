"""Champions of Kamigawa creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.named_counters import counters_on as _w1g6_counters_on
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=(), opponent_hand=(), interactive=()):
    """Two seats on seat 0's first main phase, mana costs off, libraries to
    draw from."""
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand if seat == 0 else opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def _w1g6_put(game, card, seat):
    """*card* onto *seat*'s battlefield through the entry seam — not cast."""
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g6_settle(game)
    return permanent


def _w1g6_cast(game, name, seat=0, **kwargs):
    result = game.cast_from_hand(seat, name, **kwargs)
    assert result.supported, (result, game.log[-4:])
    _w1g6_settle(game)
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g6_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))


def test_w1g6_myojin_of_cleansing_fire_cast_from_hand_is_divine_until_it_spends(set_pool):
    """Cast from a hand: a divinity counter (CR 614.1c), indestructible while
    it lasts — a Terror bounces off — and "Remove a divinity counter: Destroy
    all other creatures" spends it, killing both sides' creatures but itself,
    which is then an ordinary creature a second Terror kills."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[chk["Myojin of Cleansing Fire"]])
    _w1g6_put(game, lea["Grizzly Bears"], 0)
    _w1g6_put(game, lea["Hill Giant"], 1)
    myojin = _w1g6_cast(game, "Myojin of Cleansing Fire")
    assert _w1g6_counters_on(myojin, "divinity") == 1
    assert game._has_keyword(myojin, "indestructible")

    game.players[1].hand.append(lea["Terror"])
    game.cast_from_hand(1, "Terror", target_permanent_ids=[myojin.permanent_id])
    _w1g6_settle(game)
    assert game.is_on_battlefield(myojin)

    result = game.activate_permanent_ability(0, "Myojin of Cleansing Fire")
    assert result.supported, result
    _w1g6_settle(game)
    assert _w1g6_names(game, 0) == ["Myojin of Cleansing Fire"]
    assert _w1g6_names(game, 1) == []
    assert _w1g6_counters_on(myojin, "divinity") == 0
    assert not game._has_keyword(myojin, "indestructible")
    # No counter left to remove: the cost cannot be paid.
    assert not game.activate_permanent_ability(0, "Myojin of Cleansing Fire").supported

    game.players[1].hand.append(lea["Terror"])
    game.cast_from_hand(1, "Terror", target_permanent_ids=[myojin.permanent_id])
    _w1g6_settle(game)
    assert not game.is_on_battlefield(myojin)


def test_w1g6_a_myojin_put_onto_the_battlefield_was_not_cast_and_has_no_counter(set_pool):
    """"…if you cast it from your hand": a Myojin that enters any other way
    (here, put straight onto the battlefield) has no divinity counter, no
    indestructible and nothing to pay its ability with."""
    chk = set_pool("CHK")
    game = _w1g6_table(set_pool)
    myojin = _w1g6_put(game, chk["Myojin of Infinite Rage"], 0)
    assert _w1g6_counters_on(myojin, "divinity") == 0
    assert not game._has_keyword(myojin, "indestructible")
    assert not game.activate_permanent_ability(0, "Myojin of Infinite Rage").supported


def test_w1g6_myojin_of_infinite_rage_destroys_every_land(set_pool):
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[chk["Myojin of Infinite Rage"]])
    for seat in (0, 1):
        _w1g6_put(game, lea["Mountain"], seat)
    _w1g6_put(game, lea["Grizzly Bears"], 1)
    _w1g6_cast(game, "Myojin of Infinite Rage")
    assert game.activate_permanent_ability(0, "Myojin of Infinite Rage").supported
    _w1g6_settle(game)
    assert _w1g6_names(game, 0) == ["Myojin of Infinite Rage"]
    assert _w1g6_names(game, 1) == ["Grizzly Bears"]


def test_w1g6_myojin_of_seeing_winds_draws_one_for_each_permanent_you_control(set_pool):
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[chk["Myojin of Seeing Winds"]])
    _w1g6_put(game, lea["Island"], 0)
    _w1g6_put(game, lea["Grizzly Bears"], 0)
    _w1g6_put(game, lea["Hill Giant"], 1)
    _w1g6_cast(game, "Myojin of Seeing Winds")
    assert game.players[0].hand == []
    assert game.activate_permanent_ability(0, "Myojin of Seeing Winds").supported
    _w1g6_settle(game)
    # Island, Bears and the Myojin itself — not the opponent's Giant.
    assert len(game.players[0].hand) == 3


def test_w1g6_myojin_of_nights_reach_empties_each_opponents_hand_only(set_pool):
    """"Each opponent discards their hand": the opponent's two cards go to
    their graveyard; the controller's own hand is untouched."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(
        set_pool, hand=[chk["Myojin of Night's Reach"], lea["Lightning Bolt"]],
        opponent_hand=[lea["Giant Growth"], lea["Counterspell"]],
    )
    _w1g6_cast(game, "Myojin of Night's Reach")
    assert game.activate_permanent_ability(0, "Myojin of Night's Reach").supported
    _w1g6_settle(game)
    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt"]
    assert game.players[1].hand == []
    assert sorted(c.name for c in game.players[1].graveyard) == ["Counterspell", "Giant Growth"]


def test_w1g6_myojin_of_lifes_web_puts_any_number_of_creature_cards(set_pool):
    """"Put any number of creature cards from your hand onto the
    battlefield": a person picks one of the two creature cards and keeps the
    other (none is a legal answer too); the instant is never offered. A seat
    nobody sits in puts every creature card."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    hand = [chk["Myojin of Life's Web"], lea["Craw Wurm"], lea["Grizzly Bears"],
            lea["Giant Growth"]]

    game = _w1g6_table(set_pool, hand=hand, interactive=(0,))
    _w1g6_cast(game, "Myojin of Life's Web")
    assert game.activate_permanent_ability(0, "Myojin of Life's Web").supported
    owed = _w1g6_settle(game, defaults=False)
    assert owed is not None and owed.kind == "choose_cards_in_hand"
    offered = sorted(game.players[0].hand[i].name for i in game.live_choose_cards_in_hand(owed))
    assert offered == ["Craw Wurm", "Grizzly Bears"]
    wurm = next(i for i, c in enumerate(game.players[0].hand) if c.name == "Craw Wurm")
    assert game.confirm_choose_cards_in_hand(0, [wurm])
    _w1g6_settle(game)
    assert _w1g6_names(game, 0) == ["Craw Wurm", "Myojin of Life's Web"]
    assert sorted(c.name for c in game.players[0].hand) == ["Giant Growth", "Grizzly Bears"]

    game = _w1g6_table(set_pool, hand=hand)
    _w1g6_cast(game, "Myojin of Life's Web")
    assert game.activate_permanent_ability(0, "Myojin of Life's Web").supported
    _w1g6_settle(game)
    assert _w1g6_names(game, 0) == ["Craw Wurm", "Grizzly Bears", "Myojin of Life's Web"]
    assert [c.name for c in game.players[0].hand] == ["Giant Growth"]


def test_w1g6_shimatsu_enters_with_a_counter_for_each_permanent_sacrificed(set_pool):
    """"As Shimatsu enters, sacrifice any number of permanents. Shimatsu
    enters with that many +1/+1 counters on it." The choice is made before
    it enters (CR 614.12a), so Shimatsu is not offered; a land and a
    creature given up make a 2/2. A seat nobody asks gives up nothing (the
    stated policy for an optional entry cost) and the 0/0 dies."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, hand=[chk["Shimatsu the Bloodcloaked"]], interactive=(0,))
    forest = _w1g6_put(game, lea["Forest"], 0)
    bears = _w1g6_put(game, lea["Grizzly Bears"], 0)
    _w1g6_put(game, lea["Llanowar Elves"], 0)
    game.cast_from_hand(0, "Shimatsu the Bloodcloaked")
    owed = _w1g6_settle(game, defaults=False)
    assert owed is not None and owed.kind == "sacrifice"
    offered = game.pending_sacrifice_state()
    assert sorted(
        game.permanent_at(game.players[0], i).card.name for i in offered["valid_indices"]
    ) == ["Forest", "Grizzly Bears", "Llanowar Elves"]
    assert game.confirm_sacrifice(0, permanent_ids=[forest.permanent_id, bears.permanent_id])
    _w1g6_settle(game)
    shimatsu = next(p for p in game.controlled_by(0) if p.card.name == "Shimatsu the Bloodcloaked")
    assert _w1g6_counters_on(shimatsu, "+1/+1") == 2
    assert (shimatsu.effective_power, shimatsu.effective_toughness) == (2, 2)
    assert _w1g6_names(game, 0) == ["Llanowar Elves", "Shimatsu the Bloodcloaked"]

    game = _w1g6_table(set_pool, hand=[chk["Shimatsu the Bloodcloaked"]])
    _w1g6_put(game, lea["Forest"], 0)
    game.cast_from_hand(0, "Shimatsu the Bloodcloaked")
    _w1g6_settle(game)
    assert _w1g6_names(game, 0) == ["Forest"]
    assert "Shimatsu the Bloodcloaked" in [c.name for c in game.players[0].graveyard]


def test_w1g6_eight_and_a_half_tails_whitens_a_bolt_then_protects_from_white(set_pool):
    """The card's own combination: an opponent's Lightning Bolt aimed at a
    Grizzly Bears is made white ("{1}: Target spell or permanent becomes white
    until end of turn"), then the Bears gains protection from white ("{1}{W}:
    Target permanent you control gains protection from white"), and the Bolt
    is removed for want of a legal target (CR 608.2b)."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, opponent_hand=[lea["Lightning Bolt"]])
    tails = _w1g6_put(game, chk["Eight-and-a-Half-Tails"], 0)
    bears = _w1g6_put(game, lea["Grizzly Bears"], 0)
    whitening = compile_card_oracle(tails.card).activated_abilities[1]
    assert derive_activation_spec(whitening)["kind"] == "spell_or_permanent"

    game.active_player_index = 1
    assert game.queue_from_hand(1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]).supported
    bolt = game.stack[-1]
    assert game.queue_permanent_ability(
        0, "Eight-and-a-Half-Tails", ability_index=1, target_stack_index=0,
    ).supported
    assert game.resolve_top_of_stack()
    assert sorted(game._stack_item_colors(bolt)) == ["W"]
    assert game.queue_permanent_ability(
        0, "Eight-and-a-Half-Tails", ability_index=0, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert game.is_on_battlefield(bears)
    assert any("every target is illegal" in line for line in game.log[-3:])


def test_w1g6_eight_and_a_half_tails_whitens_a_permanent_for_the_turn(set_pool):
    """The permanent half: an opponent's Hill Giant is white until end of turn,
    and red again once cleanup ends the effect (CR 514.2)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool)
    _w1g6_put(game, chk["Eight-and-a-Half-Tails"], 0)
    giant = _w1g6_put(game, lea["Hill Giant"], 1)
    assert game.activate_permanent_ability(
        0, "Eight-and-a-Half-Tails", ability_index=1, target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert sorted(game._effective_colors(giant)) == ["W"]
    game.resolve_cleanup_step(0)
    assert sorted(game._effective_colors(giant)) == ["R"]


def test_w1g6_pious_kitsune_gains_per_counter_only_beside_eight_and_a_half_tails(set_pool):
    """"At the beginning of your upkeep, put a devotion counter on this
    creature. Then if a creature named Eight-and-a-Half-Tails is on the
    battlefield, you gain 1 life for each devotion counter on this creature."
    Beside a Grizzly Bears it only collects counters; beside an opponent's
    Eight-and-a-Half-Tails (any battlefield) the second upkeep gains two. "{T},
    Remove a devotion counter: You gain 1 life" spends one."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    for neighbour, gained in ((lea["Grizzly Bears"], 0), (chk["Eight-and-a-Half-Tails"], 2)):
        game = _w1g6_table(set_pool)
        kitsune = _w1g6_put(game, chk["Pious Kitsune"], 0)
        _w1g6_put(game, neighbour, 1)
        game.start_turn(0)
        _w1g6_settle(game)
        assert _w1g6_counters_on(kitsune, "devotion") == 1
        game.start_turn(0)
        _w1g6_settle(game)
        assert _w1g6_counters_on(kitsune, "devotion") == 2
        assert game.players[0].life == 20 + (1 if gained else 0) + gained
        life = game.players[0].life
        assert game.activate_permanent_ability(0, "Pious Kitsune").supported
        _w1g6_settle(game)
        assert _w1g6_counters_on(kitsune, "devotion") == 1
        assert game.players[0].life == life + 1


def test_w1g6_blood_speaker_trades_itself_for_a_demon_and_comes_back_for_it(set_pool):
    """"At the beginning of your upkeep, you may sacrifice this creature. If
    you do, search your library for a Demon card …": a person accepts and
    finds Kuro, Pitlord. "Whenever a Demon you control enters, return this
    card from your graveyard to your hand": casting Kuro brings the Speaker
    back from the graveyard (CR 113.6m: the trigger functions there)."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g6_table(set_pool, interactive=(0,))
    game.players[0].library = [lea["Forest"], chk["Kuro, Pitlord"], lea["Island"]]
    _w1g6_put(game, chk["Blood Speaker"], 0)
    game.start_turn(0)
    _w1g6_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=True),
    })
    assert [c.name for c in game.players[0].hand] == ["Kuro, Pitlord"]
    assert [c.name for c in game.players[0].graveyard] == ["Blood Speaker"]

    game.interactive_seats = set()
    _w1g6_cast(game, "Kuro, Pitlord")
    assert [c.name for c in game.players[0].hand] == ["Blood Speaker"]
    assert game.players[0].graveyard == []

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import drive_combat as _w1g7_drive_combat
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, mine=(), theirs=(), library=None, hand=(),
                interactive=()):
    """Two seats on seat 0's first main phase, costs off; *library* is seat
    0's, top first."""
    lea = set_pool("LEA")
    chk = set_pool("CHK")

    def named(name):
        return chk[name] if name in chk else lea[name]

    game = _W1G7Game(players=[
        _W1G7PlayerState(
            "P0", hand=[named(n) for n in hand],
            library=[named(n) for n in (library or ["Forest"] * 10)],
        ),
        _W1G7PlayerState("P1", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = []
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G7Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.append(permanent)
    game.start_turn(0)
    _w1g7_settle(game)
    return game, placed


_W1G7_DECEIVERS = {
    # name: (P/T before, P/T after a land, keyword gained)
    "Brutal Deceiver": ((2, 2), (3, 2), "first strike"),
    "Callous Deceiver": ((1, 3), (2, 3), "flying"),
    "Feral Deceiver": ((3, 2), (5, 4), "trample"),
    "Harsh Deceiver": ((1, 4), (2, 5), None),
    "Cruel Deceiver": ((2, 1), (2, 1), None),
}


@_w1g7_pytest.mark.parametrize("name", sorted(_W1G7_DECEIVERS))
def test_w1g7_a_deceiver_looks_at_its_top_card_privately(set_pool, name):
    """"{1}: Look at the top card of your library." — shown to its controller
    on a prompt (CR 400.2: the log is every seat's), nothing moved, nothing
    rearrangeable."""
    game, (deceiver,) = _w1g7_table(
        set_pool, mine=[name], library=["Lightning Bolt", "Forest", "Island"],
        interactive={0},
    )
    assert game.activate_permanent_ability(0, name, ability_index=0).supported
    asked = _w1g7_settle(game, defaults=False)
    assert asked is not None and asked.kind == "reorder_library"
    assert asked.player_index == 0 and asked.data["target_index"] == 0
    assert asked.data["top_count"] == 1 and asked.data["may_reorder"] is False
    assert not asked.data["may_shuffle"]
    # The card is not named where the other seat can read it.
    assert not any("Lightning Bolt" in line for line in game.log)
    _w1g7_settle(game)
    assert [c.name for c in game.players[0].library] == ["Lightning Bolt", "Forest", "Island"]


@_w1g7_pytest.mark.parametrize("name", sorted(_W1G7_DECEIVERS))
def test_w1g7_a_deceiver_reveals_a_land_once_each_turn(set_pool, name):
    before, after, keyword = _W1G7_DECEIVERS[name]
    game, (deceiver,) = _w1g7_table(set_pool, mine=[name], library=["Forest", "Lightning Bolt"])
    if name == "Harsh Deceiver":
        deceiver.tapped = True
    assert (deceiver.effective_power, deceiver.effective_toughness) == before
    assert game.activate_permanent_ability(0, name, ability_index=1).supported
    _w1g7_settle(game)
    assert any("revealed Forest" in line for line in game.log)
    assert (deceiver.effective_power, deceiver.effective_toughness) == after
    if keyword:
        assert game._has_keyword(deceiver, keyword)
    if name == "Harsh Deceiver":
        assert not deceiver.tapped
    # "Activate only once each turn."
    assert not game.activate_permanent_ability(0, name, ability_index=1).supported
    assert [c.name for c in game.players[0].library] == ["Forest", "Lightning Bolt"]
    game.resolve_cleanup_step(0)
    assert (deceiver.effective_power, deceiver.effective_toughness) == before


def test_w1g7_a_deceiver_revealing_a_nonland_does_nothing(set_pool):
    game, (deceiver,) = _w1g7_table(
        set_pool, mine=["Feral Deceiver"], library=["Lightning Bolt", "Forest"],
    )
    assert game.activate_permanent_ability(0, "Feral Deceiver", ability_index=1).supported
    _w1g7_settle(game)
    assert any("revealed Lightning Bolt" in line for line in game.log)
    assert (deceiver.effective_power, deceiver.effective_toughness) == (3, 2)
    assert not game._has_keyword(deceiver, "trample")


def test_w1g7_cruel_deceivers_granted_trigger_destroys_its_blocker(set_pool):
    game, (deceiver, wurm) = _w1g7_table(
        set_pool, mine=["Cruel Deceiver"], theirs=["Craw Wurm"],
        library=["Forest"] * 4,
    )
    assert game.activate_permanent_ability(0, "Cruel Deceiver", ability_index=1).supported
    _w1g7_settle(game)
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_drive_combat(game)
    assert [c.name for c in game.players[1].graveyard] == ["Craw Wurm"]
    assert any("Cruel Deceiver destroyed Craw Wurm" in line for line in game.log)


def _w1g7_hisoka_against(set_pool, spell, discard, announce):
    lea = set_pool("LEA")
    game, (hisoka, wurm) = _w1g7_table(
        set_pool, mine=["Hisoka, Minamo Sensei"], theirs=["Craw Wurm"],
        hand=["Lightning Bolt", "Grizzly Bears", "Wrath of God"],
    )
    game.players[1].hand.append(lea[spell])
    game.queue_from_hand(1, spell, **announce(wurm))
    held = [card.name for card in game.players[0].hand]
    assert game.activate_permanent_ability(
        0, "Hisoka, Minamo Sensei", target_stack_index=0,
        cost_hand_index=held.index(discard),
    ).supported
    _w1g7_settle(game)
    return game, wurm


def test_w1g7_hisoka_counters_a_spell_matching_the_discarded_card(set_pool):
    game, wurm = _w1g7_hisoka_against(
        set_pool, "Giant Growth", "Lightning Bolt",
        lambda wurm: {"target_permanent_ids": [wurm.permanent_id]},
    )
    assert [c.name for c in game.players[1].graveyard] == ["Giant Growth"]
    assert wurm.effective_power == 6                  # never pumped
    assert [c.name for c in game.players[0].graveyard] == ["Lightning Bolt"]


def test_w1g7_hisoka_does_not_counter_a_spell_of_another_mana_value(set_pool):
    game, wurm = _w1g7_hisoka_against(
        set_pool, "Giant Growth", "Grizzly Bears",
        lambda wurm: {"target_permanent_ids": [wurm.permanent_id]},
    )
    assert wurm.effective_power == 9                  # Giant Growth resolved
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears"]


def test_w1g7_rag_dealer_announces_three_cards_of_a_single_graveyard(set_pool):
    """"{2}{B}, {T}: Exile up to three target cards from a single graveyard."
    The cards are targets, named as the ability is activated (CR 602.2b,
    601.2c) in one pile, and CR 608.2b judges each one: a card gone in
    response is not made up for."""
    from engine.stack_targets import chosen_targets

    game, (dealer,) = _w1g7_table(set_pool, mine=["Rag Dealer"], interactive={0, 1})
    lea = set_pool("LEA")
    game.players[0].graveyard.extend([lea["Forest"], lea["Grizzly Bears"]])
    game.players[1].graveyard.extend(
        [lea["Swamp"], lea["Hill Giant"], lea["Terror"], lea["Island"]]
    )
    spec = game.activation_target_spec(0, 0, ability_index=0)
    assert spec["single_graveyard"] and spec["max_targets"] == 3
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}
    # Unnamed pile, a fourth slot: refused, nothing paid.
    assert not game.queue_permanent_ability(
        0, "Rag Dealer", ability_index=0, target_permanent_index=[0, 1],
    ).supported
    assert not game.queue_permanent_ability(
        0, "Rag Dealer", ability_index=0, target_player_index=1,
        target_permanent_index=[0, 1, 2, 3],
    ).supported
    assert not dealer.tapped
    assert game.queue_permanent_ability(
        0, "Rag Dealer", ability_index=0, target_player_index=1,
        target_permanent_index=[1, 2, 3],
    ).supported
    assert [t.stamp.card.name for t in chosen_targets(game, game.stack[-1])] == [
        "Hill Giant", "Terror", "Island",
    ]
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(1))       # Hill Giant, in response
    _w1g7_settle(game)
    assert [c.name for c in victim.graveyard] == ["Swamp"]
    assert sorted(c.name for c in victim.exile) == ["Hill Giant", "Island", "Terror"]
    assert [c.name for c in game.players[0].graveyard] == ["Forest", "Grizzly Bears"]
    assert dealer.tapped


def test_w1g7_hisoka_reads_an_x_spells_mana_value_on_the_stack(set_pool):
    """CR 202.3e: Fireball cast for X=3 has mana value 4 on the stack."""
    game, wurm = _w1g7_hisoka_against(
        set_pool, "Fireball", "Wrath of God",
        lambda wurm: {"target_player_index": 0, "x_value": 3},
    )
    assert game.players[0].life == 20
    assert [c.name for c in game.players[1].graveyard] == ["Fireball"]

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (
    _game as _w1g8_game,
    _nosick as _w1g8_nosick,
    declare_attack as _w1g8_declare_attack,
    drive_combat as _w1g8_drive_combat,
    settle as _w1g8_settle,
    stock_libraries as _w1g8_stock_libraries,
)


def _w1g8_table(mine=(), theirs=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's precombat main phase of turn 2, the permanents
    placed through the entry funnel without a beginning phase run (so no
    upkeep trigger of theirs has fired), libraries stocked."""
    game = _w1g8_game(
        _w1g8_PlayerState(name="P1", hand=list(hand), life=20),
        _w1g8_PlayerState(name="P2", hand=list(opponent_hand), life=20),
    )
    _w1g8_stock_libraries(game)
    game.turn = 2
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        row = []
        for card in cards:
            permanent = _w1g8_Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            row.append(_w1g8_nosick(permanent))
        placed.append(row)
    game._sync_control()
    _w1g8_settle(game)
    return game, placed[0], placed[1]


# --- Shisato, Whispering Hunter ---------------------------------------------
# "Whenever Shisato deals combat damage to a player, that player skips their
# next untap step." The seat is the one the damage event froze (CR 603.10),
# and the skip is CR 614.10's one-shot: spent by the damaged player's next
# untap step, never by Shisato's controller's.


def test_w1g8_shisato_skips_the_damaged_players_next_untap_step(set_pool):
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, (hunter,), (bear,) = _w1g8_table([shisato], [bears])
    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 18
    hunter.tapped = True
    bear.tapped = True

    game.start_turn(1)
    _w1g8_settle(game)
    assert bear.tapped, game.log[-6:]
    assert "P2 skips their untap step" in game.log
    # Shisato's controller's untap step was not the one named.
    game.start_turn(0)
    _w1g8_settle(game)
    assert not hunter.tapped
    # Spent once: the damaged player's next untap step happens.
    game.start_turn(1)
    assert not bear.tapped


def test_w1g8_a_blocked_shisato_skips_nothing(set_pool):
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    wall = set_pool("LEA")["Wall of Stone"]
    game, _, _ = _w1g8_table([shisato], [wall])
    _w1g8_declare_attack(game, 0, blocks={0: 0})
    _w1g8_drive_combat(game)
    assert game.players[1].life == 20
    assert not game.skip_step_counts


def test_w1g8_shisato_sacrifices_a_snake_at_its_controllers_upkeep(set_pool):
    """"At the beginning of your upkeep, sacrifice a Snake." Shisato is a
    Snake itself, so alone it is the one sacrificed."""
    shisato = set_pool("CHK")["Shisato, Whispering Hunter"]
    game, (hunter,), _ = _w1g8_table([shisato], [])
    game.start_turn(1)
    _w1g8_settle(game)
    assert game.is_on_battlefield(hunter)
    game.start_turn(0)
    _w1g8_settle(game)
    assert not game.is_on_battlefield(hunter)
    assert shisato in game.players[0].graveyard


# --- Dosan the Falling Leaf ---------------------------------------------------
# "Players can cast spells only during their own turns." CR 601.3a on every
# battlefield's seats alike (its controller too), casting alone: the ruling
# (2004-12-01) — "It doesn't stop activated or triggered abilities."


def test_w1g8_dosan_stops_casting_on_another_players_turn(set_pool):
    from engine.cast_prohibitions import cast_prohibition

    dosan = set_pool("CHK")["Dosan the Falling Leaf"]
    bolt = set_pool("LEA")["Lightning Bolt"]
    game, _, _ = _w1g8_table([], [dosan], hand=[bolt], opponent_hand=[bolt])
    # Seat 0's own turn: its instant is cast.
    assert cast_prohibition(game, 0, bolt) is None
    # On seat 0's turn the Dosan's own controller is bound as well.
    refused = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not refused.supported
    assert "another player's turn" in refused.details
    assert game.players[0].life == 20
    assert [card.name for card in game.players[1].hand] == ["Lightning Bolt"]

    game.active_player_index = 1
    refused = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not refused.supported
    assert [card.name for card in game.players[0].hand] == ["Lightning Bolt"]
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8_settle(game)
    assert game.players[0].life == 17


def test_w1g8_dosan_leaves_activated_abilities_alone(set_pool):
    dosan = set_pool("CHK")["Dosan the Falling Leaf"]
    sorcerer = set_pool("LEA")["Prodigal Sorcerer"]
    game, _, _ = _w1g8_table([sorcerer], [dosan])
    game.active_player_index = 1
    used = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)
    assert used.supported, used.details
    _w1g8_settle(game)
    assert game.players[1].life == 19


# --- Frostwielder, Kumano's Pupils, Kumano, Master Yamabushi -------------------
# "If a creature dealt damage by this creature [Kumano] this turn would die,
# exile it instead." A static replacement of the damager (CR 614.1a), read
# off the turn's damage ledger at the death: by any means for the rest of the
# turn (CR 700.4), only while the source is on the battlefield — "even if
# it's going to the graveyard at the same time" (the 2004-12-01 rulings).


def _w1g8_zone_names(game, seat, zone):
    return [card.name for card in getattr(game.players[seat], zone)]


def test_w1g8_frostwielder_exiles_what_its_ping_kills(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    elves = set_pool("LEA")["Llanowar Elves"]
    game, _, (elf,) = _w1g8_table([frost], [elves])
    used = game.activate_permanent_ability(
        0, "Frostwielder", target_permanent_ids=[elf.permanent_id]
    )
    assert used.supported, used.details
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Llanowar Elves"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []


def test_w1g8_frostwielder_exiles_a_damaged_creature_destroyed_later_that_turn(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    giant = set_pool("LEA")["Hill Giant"]
    terror = set_pool("LEA")["Terror"]
    game, _, (hill,) = _w1g8_table([frost], [giant], hand=[terror])
    assert game.activate_permanent_ability(
        0, "Frostwielder", target_permanent_ids=[hill.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.is_on_battlefield(hill)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[hill.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]


def test_w1g8_frostwielder_must_be_on_the_battlefield_when_the_creature_dies(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    giant = set_pool("LEA")["Hill Giant"]
    terror = set_pool("LEA")["Terror"]
    unsummon = set_pool("LEA")["Unsummon"]
    game, (wielder,), (hill,) = _w1g8_table(
        [frost], [giant], hand=[unsummon, terror]
    )
    assert game.activate_permanent_ability(
        0, "Frostwielder", target_permanent_ids=[hill.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.cast_from_hand(
        0, "Unsummon", target_permanent_ids=[wielder.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[hill.permanent_id]).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Hill Giant"]
    assert _w1g8_zone_names(game, 1, "exile") == []


def test_w1g8_frostwielder_does_not_exile_what_another_source_damaged(set_pool):
    frost = set_pool("CHK")["Frostwielder"]
    elves = set_pool("LEA")["Llanowar Elves"]
    bolt = set_pool("LEA")["Lightning Bolt"]
    game, _, (elf,) = _w1g8_table([frost], [elves], hand=[bolt])
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[elf.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Llanowar Elves"]


def test_w1g8_kumanos_pupils_exiles_the_blocker_it_trades_with(set_pool):
    """The ruling: "even if it's going to the graveyard at the same time as
    Kumano's Pupils" — one state-based check, both seats swept, the Pupils'
    seat first."""
    pupils = set_pool("CHK")["Kumano's Pupils"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, _ = _w1g8_table([pupils], [giant])
    _w1g8_declare_attack(game, 0, blocks={0: 0})
    _w1g8_drive_combat(game)
    assert _w1g8_zone_names(game, 0, "graveyard") == ["Kumano's Pupils"]
    assert _w1g8_zone_names(game, 1, "exile") == ["Hill Giant"]
    assert _w1g8_zone_names(game, 1, "graveyard") == []


def test_w1g8_kumano_names_itself(set_pool):
    kumano = set_pool("CHK")["Kumano, Master Yamabushi"]
    elves = set_pool("LEA")["Llanowar Elves"]
    game, _, (elf,) = _w1g8_table([kumano], [elves])
    assert game.activate_permanent_ability(
        0, "Kumano, Master Yamabushi", target_permanent_ids=[elf.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert _w1g8_zone_names(game, 1, "exile") == ["Llanowar Elves"]


def test_w1g8_wicked_akuba_targets_only_a_player_it_damaged_this_turn(set_pool):
    """"{B}: Target player dealt damage by this creature this turn loses 1
    life." The narrowing is the picker's (CR 601.2c), read off the turn's
    damage ledger from this Akuba to the seat."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    akuba = set_pool("CHK")["Wicked Akuba"]
    ability = compile_card_oracle(akuba).activated_abilities[0]
    assert derive_activation_spec(ability) == {
        "kind": "player", "did": {"kind": "dealt_damage_by_source_this_turn"},
    }
    game, _, _ = _w1g8_table([akuba], [])
    refused = game.activate_permanent_ability(0, "Wicked Akuba", target_player_index=1)
    assert not refused.supported
    assert game.players[1].life == 20

    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 18
    used = game.activate_permanent_ability(0, "Wicked Akuba", target_player_index=1)
    assert used.supported, used.details
    _w1g8_settle(game)
    assert game.players[1].life == 17
    # Its own controller was dealt nothing by it.
    assert not game.activate_permanent_ability(
        0, "Wicked Akuba", target_player_index=0
    ).supported

    # The window is the turn: the next one starts with an empty ledger.
    game.start_turn(1)
    _w1g8_settle(game)
    assert not game.activate_permanent_ability(
        0, "Wicked Akuba", target_player_index=1
    ).supported


# --- Horobi, Death's Wail -----------------------------------------------------
# "Whenever a creature becomes the target of a spell or ability, destroy that
# creature." The targeted permanent is the object the becomes-target event
# froze (CR 603.2, 603.10); the ruling (2023-04-14): "If the creature is the
# only target of the spell or ability, that spell or ability won't resolve."


def test_w1g8_horobi_destroys_a_creature_a_spell_targets(set_pool):
    horobi = set_pool("CHK")["Horobi, Death's Wail"]
    bears = set_pool("LEA")["Grizzly Bears"]
    growth = set_pool("LEA")["Giant Growth"]
    game, (bear,), (wail,) = _w1g8_table([bears], [horobi], hand=[growth])
    queued = game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bear.permanent_id]
    )
    assert queued.supported, queued.details
    # The trigger sits above the spell that set it off.
    assert [(item.card.name, item.ability_kind) for item in game.stack] == [
        ("Giant Growth", None), ("Horobi, Death's Wail", "triggered"),
    ]
    _w1g8_settle(game)
    assert not game.is_on_battlefield(bear)
    assert _w1g8_zone_names(game, 0, "graveyard") == ["Grizzly Bears", "Giant Growth"]
    assert any("every target is illegal" in line for line in game.log)
    assert game.is_on_battlefield(wail)


def test_w1g8_horobis_trigger_resolves_after_horobi_has_left(set_pool):
    """The trigger is independent of its source once on the stack (CR
    113.7a): Horobi sacrificed in response still destroys the creature."""
    horobi = set_pool("CHK")["Horobi, Death's Wail"]
    bears = set_pool("LEA")["Grizzly Bears"]
    growth = set_pool("LEA")["Giant Growth"]
    game, (bear,), (wail,) = _w1g8_table([bears], [horobi], hand=[growth])
    assert game.queue_from_hand(
        0, "Giant Growth", target_permanent_ids=[bear.permanent_id]
    ).supported
    game.sacrifice_permanent(wail)
    assert not game.is_on_battlefield(wail)
    _w1g8_settle(game)
    assert not game.is_on_battlefield(bear)


def test_w1g8_horobi_sees_an_abilitys_target_and_ignores_a_players(set_pool):
    horobi = set_pool("CHK")["Horobi, Death's Wail"]
    sorcerer = set_pool("LEA")["Prodigal Sorcerer"]
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (_, hill) = _w1g8_table([sorcerer], [horobi, giant])
    assert game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1
    ).supported
    _w1g8_settle(game)
    assert game.players[1].life == 19 and game.is_on_battlefield(hill)
    game.start_turn(0)
    _w1g8_settle(game)
    assert game.activate_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[hill.permanent_id]
    ).supported
    _w1g8_settle(game)
    assert not game.is_on_battlefield(hill)
    assert _w1g8_zone_names(game, 1, "graveyard") == ["Hill Giant"]
    assert any("every target is illegal" in line for line in game.log)


# --- Masako the Humorless -----------------------------------------------------
# "Tapped creatures you control can block as though they were untapped." CR
# 509.1a's untapped requirement waived for its controller's creatures, and
# nothing else (the 2004-12-01 ruling: "only if they could otherwise block").


def _w1g8_to_blocks(game):
    game._set_phase_and_step("combat", "declare_attackers")
    attackers = [
        slot for slot, perm in enumerate(game.players[0].battlefield)
        if perm.is_creature
    ]
    ok, why = game.declare_attackers(0, attackers, defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step


def _w1g8_slot(game, seat, permanent):
    return next(
        slot for slot, perm in enumerate(game.players[seat].battlefield)
        if perm is permanent
    )


def test_w1g8_masako_lets_a_tapped_creature_block(set_pool):
    masako = set_pool("CHK")["Masako the Humorless"]
    giant = set_pool("LEA")["Hill Giant"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, (hill,), (_, wurm) = _w1g8_table([giant], [masako, craw])
    wurm.tapped = True
    _w1g8_to_blocks(game)
    ok, why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm): 0})
    assert ok, why
    _w1g8_drive_combat(game)
    assert not game.is_on_battlefield(hill)
    assert game.players[1].life == 20
    # Blocking does not untap it.
    assert wurm.tapped and wurm.damage_marked == 3


def test_w1g8_without_masako_a_tapped_creature_cannot_block(set_pool):
    giant = set_pool("LEA")["Hill Giant"]
    craw = set_pool("LEA")["Craw Wurm"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, _, (wurm, bear) = _w1g8_table([giant], [craw, bears])
    wurm.tapped = True
    _w1g8_to_blocks(game)
    ok, why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm): 0})
    assert not ok and "is tapped" in why


def test_w1g8_masako_waives_nothing_but_the_untapped_requirement(set_pool):
    """Its controller's creatures only, and a tapped creature still can't
    block what it otherwise couldn't (a flier)."""
    masako = set_pool("CHK")["Masako the Humorless"]
    roc = set_pool("LEA")["Mahamoti Djinn"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, _, (_, wurm) = _w1g8_table([roc], [masako, craw])
    wurm.tapped = True
    _w1g8_to_blocks(game)
    ok, _why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm): 0})
    assert not ok

    # An opponent's Masako lends nothing.
    giant = set_pool("LEA")["Hill Giant"]
    game, _, (wurm2,) = _w1g8_table([giant, masako], [craw])
    wurm2.tapped = True
    _w1g8_to_blocks(game)
    ok, why = game.declare_blockers(1, {_w1g8_slot(game, 1, wurm2): 0})
    assert not ok and "is tapped" in why


def test_w1g8_the_ai_blocks_with_a_tapped_creature_under_masako(set_pool):
    from engine.ai_declarations import choose_combat_blockers

    masako = set_pool("CHK")["Masako the Humorless"]
    giant = set_pool("LEA")["Hill Giant"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, _, (sage, wurm) = _w1g8_table([giant], [masako, craw])
    sage.tapped = True
    wurm.tapped = True
    _w1g8_to_blocks(game)
    blocks = choose_combat_blockers(game, 1)
    assert _w1g8_slot(game, 1, wurm) in blocks, blocks


# --- Sosuke, Son of Seshiro ---------------------------------------------------
# "Whenever a Warrior you control deals combat damage to a creature, destroy
# that creature at end of combat." The creature dealt damage (the only thing
# "that creature" can name beside "a Warrior"), destroyed by a delayed
# triggered ability as the end of combat step begins (CR 603.7, 511.2).


def test_w1g8_sosuke_destroys_what_a_warrior_hit_at_end_of_combat(set_pool):
    sosuke = set_pool("CHK")["Sosuke, Son of Seshiro"]
    ranger = set_pool("CHK")["Orochi Ranger"]
    craw = set_pool("LEA")["Craw Wurm"]
    game, (_, scout), (wurm,) = _w1g8_table([sosuke, ranger], [craw])
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [_w1g8_slot(game, 0, scout)], defending_player_index=1
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: _w1g8_slot(game, 0, scout)})[0]
    # In the combat damage step: dealt, not yet destroyed.
    _w1g8_drive_combat(game, through="declare_blockers")
    assert wurm.damage_marked == 3 and game.is_on_battlefield(wurm)
    _w1g8_drive_combat(game)
    assert not game.is_on_battlefield(wurm)
    assert "Craw Wurm" in _w1g8_zone_names(game, 1, "graveyard")


def test_w1g8_sosuke_ignores_a_non_warrior_and_an_opponents_warrior(set_pool):
    sosuke = set_pool("CHK")["Sosuke, Son of Seshiro"]
    ranger = set_pool("CHK")["Orochi Ranger"]
    craw = set_pool("LEA")["Craw Wurm"]
    giant = set_pool("LEA")["Hill Giant"]
    # Sosuke itself is a Snake Warrior, so the non-Warrior is the Giant.
    game, (_, hill), (wurm,) = _w1g8_table([sosuke, giant], [craw])
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [_w1g8_slot(game, 0, hill)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: _w1g8_slot(game, 0, hill)})[0]
    _w1g8_drive_combat(game)
    assert game.is_on_battlefield(wurm)

    # The opponent's Warrior blocking seat 0's creature fires nothing.
    game, (_, hill), (scout,) = _w1g8_table([sosuke, giant], [ranger])
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [_w1g8_slot(game, 0, hill)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: _w1g8_slot(game, 0, hill)})[0]
    _w1g8_drive_combat(game)
    assert game.is_on_battlefield(hill)


# --- Kiki-Jiki, Mirror Breaker ------------------------------------------------
# "{T}: Create a token that's a copy of target nonlegendary creature you
# control, except it has haste. Sacrifice it at the beginning of the next end
# step." CR 707.9a's exception, part of the copiable values (CR 707.9b, the
# 2021-03-19 ruling: a copy of the token has haste too).


def test_w1g8_kiki_jiki_makes_a_hasty_copy_that_is_sacrificed_at_end_step(set_pool):
    from engine.copies import copiable_card

    kiki = set_pool("CHK")["Kiki-Jiki, Mirror Breaker"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, (_, bear), _ = _w1g8_table([kiki, bears], [])
    used = game.activate_permanent_ability(
        0, "Kiki-Jiki, Mirror Breaker", target_permanent_ids=[bear.permanent_id]
    )
    assert used.supported, used.details
    _w1g8_settle(game)
    tokens = [
        p for p in game.controlled_by(game.players[0]) if p.metadata.get("is_token")
    ]
    assert len(tokens) == 1
    token = tokens[0]
    assert token.effective_card.name == "Grizzly Bears"
    assert (token.effective_power, token.effective_toughness) == (2, 2)
    assert token.has_keyword("haste")
    assert game.can_attack(token, 1) and not game._is_summoning_sick(token)
    # The haste is a copiable value of the token (CR 707.9b).
    assert "Haste" in copiable_card(token).oracle_text.splitlines()
    # The original is untouched.
    assert not bear.has_keyword("haste")

    game._set_phase_and_step("ending", "end")
    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert not game.is_on_battlefield(token)
    assert game.is_on_battlefield(bear)


def test_w1g8_kiki_jiki_cannot_copy_a_legendary_or_an_opponents_creature(set_pool):
    kiki = set_pool("CHK")["Kiki-Jiki, Mirror Breaker"]
    sosuke = set_pool("CHK")["Sosuke, Son of Seshiro"]
    bears = set_pool("LEA")["Grizzly Bears"]
    game, (_, legend), (theirs,) = _w1g8_table([kiki, sosuke], [bears])
    for chosen in (legend, theirs):
        refused = game.activate_permanent_ability(
            0, "Kiki-Jiki, Mirror Breaker", target_permanent_ids=[chosen.permanent_id]
        )
        assert not refused.supported
    assert not any(p.metadata.get("is_token") for p in game.all_permanents())


def test_w1g8_the_dealt_damage_exile_reads_only_a_line_about_itself():
    """The subject is the card itself — "this creature" or its own name (CR
    201.5, the legend's short name included) — never another card's."""
    from engine.replacements import replacement_claims_line
    from engine.replacements.zone_changes import dealt_damage_exile_line

    line = "If a creature dealt damage by Kumano this turn would die, exile it instead."
    assert dealt_damage_exile_line(line, "Kumano, Master Yamabushi")
    assert replacement_claims_line(line, "Kumano, Master Yamabushi")
    assert not dealt_damage_exile_line(line, "Frostwielder")
    assert not replacement_claims_line(line)
    assert dealt_damage_exile_line(
        "If a creature dealt damage by this creature this turn would die, exile it instead."
    )

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), library=("Island",) * 12):
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card(n) for n in library]),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    placed = []
    for name in mine:
        permanent = _W1G9Permanent(card=card(name))
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed


def test_w1g9_godo_fetches_an_equipment_as_it_enters(set_pool):
    """"When Godo enters, you may search your library for an Equipment card,
    put it onto the battlefield, then shuffle." Cast, the entry trigger finds
    Tenza among the lands and puts it onto the battlefield."""
    game, _mine = _w1g9_table(
        set_pool, hand=["Godo, Bandit Warlord"],
        library=("Island", "Tenza, Godo's Maul", "Island", "Island"),
    )
    assert game.cast_from_hand(0, "Godo, Bandit Warlord").supported
    _w1g9_settle(game)
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert names == ["Godo, Bandit Warlord", "Tenza, Godo's Maul"]
    assert "Tenza, Godo's Maul" not in [c.name for c in game.players[0].library]


def test_w1g9_godo_untaps_samurai_and_adds_a_combat_only_on_its_first_attack(set_pool):
    """"Whenever Godo attacks for the first time each turn, untap it and all
    Samurai you control. After this phase, there is an additional combat
    phase." (CR 500.8; no extra main phase, the 2020-08-07 ruling.) Godo and a
    tapped Samurai untap, a tapped Bear does not, and the turn's second combat
    follows the first; Godo attacking again there sets nothing off."""
    game, mine = _w1g9_table(
        set_pool, mine=["Godo, Bandit Warlord", "Kitsune Blademaster", "Grizzly Bears"],
    )
    godo, blademaster, bears = mine
    blademaster.tapped = True
    bears.tapped = True
    alice, bob = game.players
    game._set_phase_and_step("combat", "declare_attackers")
    slot = [p.permanent_id for p in alice.battlefield].index(godo.permanent_id)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why
    _w1g9_settle(game)
    assert not godo.tapped and not blademaster.tapped and bears.tapped
    _w1g9_drive_combat(game)
    assert bob.life == 17
    assert game.current_turn_phase == "combat", "the additional combat phase"

    _w1g9_drive_combat(game, through="beginning_of_combat")
    assert game.current_step == "declare_attackers"
    slots = [
        i for i, p in enumerate(alice.battlefield) if p.is_creature and not p.tapped
    ]
    ok, why = game.declare_attackers(0, slots, defending_player_index=1)
    assert ok, why
    _w1g9_settle(game)
    assert game.stack == [] and godo.tapped and blademaster.tapped
    _w1g9_drive_combat(game)
    assert bob.life == 17 - 3 - 2
    assert game.current_turn_phase == "postcombat_main"

# ==== end w1g9 ======================================================

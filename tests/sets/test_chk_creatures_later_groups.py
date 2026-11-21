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

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================

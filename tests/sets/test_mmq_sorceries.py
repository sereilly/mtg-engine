"""Mercadian Masques sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: alternative and additional casting costs ---
# Land Grant, the one card in this pool whose CR 118.9 alternative cost is
# paid by **information**: "If you have no land cards in hand, you may reveal
# your hand rather than pay this spell's mana cost." Both halves are unusual --
# the condition reads a hand rather than a board, and the payment moves nothing
# -- so the two are asserted apart: an offer that appeared on a hand holding a
# land would be a free Rampant Growth, and a payment nobody could see would be
# a free spell with a log line.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g1_grant_table(set_pool, hand, mine=()):
    """A two-seat board with mana-cost enforcement **on**.

    On, deliberately and unlike the house rig: this card is about not paying a
    mana cost, and a game that charges none cannot tell a free cast from an
    ordinary one.
    """
    pool = set_pool("MMQ")
    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    caster.library = [pool["Forest"], pool["Plains"], pool["Wild Jhovall"]]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    for name in mine:
        caster.battlefield.append(Permanent(card=pool[name]))
    game._sync_control()
    return game, caster, other


def _g1_grant_offers(game, card):
    return [
        (offer["label"], offer["payable"])
        for offer in game.cast_cost_offers(0, card, spell_hand_index=0)
        if offer["kind"] == "alternative"
    ]


def test_g1_land_grant_is_free_only_with_no_land_in_hand(set_pool):
    """CR 601.2b: the condition is a **hand**, and it is checked at the cast.

    A card in a hand has no computed characteristics (CR 613.1), so the phrase
    is put to the card matcher rather than to ``subject_matches`` -- a narrowing
    only the permanent matcher could answer would be silently dropped by the
    hand scan, and the offer would stand on a hand the card does not name.
    """
    card = set_pool("MMQ")["Land Grant"]

    game, _, _ = _g1_grant_table(set_pool, ["Land Grant", "Forest"])
    assert _g1_grant_offers(game, card) == []

    game, _, _ = _g1_grant_table(set_pool, ["Land Grant", "Brainstorm"])
    assert _g1_grant_offers(game, card) == [("reveal your hand", True)]


def test_g1_land_grant_offer_survives_an_empty_hand(set_pool):
    """An empty hand holds no land card, so the offer stands and is payable.

    CR 601.2h has no shortfall to find in a reveal: showing nothing is still
    showing what you have. A gate that treated "nothing to reveal" as unpayable
    would refuse the card on exactly the board it is designed for.
    """
    card = set_pool("MMQ")["Land Grant"]
    game, _, _ = _g1_grant_table(set_pool, ["Land Grant"])

    assert _g1_grant_offers(game, card) == [("reveal your hand", True)]


def test_g1_land_grant_reveals_the_hand_and_fetches_for_nothing(set_pool):
    """The whole card: the hand is shown, the Forest arrives, no mana is spent.

    The reveal goes through ``record_reveal`` -- the feed the web layer reads,
    the same seam the ``reveal_hand`` *effect* uses -- rather than a log line
    alone: a reveal the client cannot show is a reveal the opponent has to take
    on trust, and here it is the entire price of the spell.

    The spell is already off the hand when the price is paid (CR 601.2a), so
    what is shown is the hand Land Grant's own condition is about.
    """
    game, caster, _ = _g1_grant_table(
        set_pool, ["Land Grant", "Brainstorm", "Wild Jhovall"],
    )

    result = game.cast_from_hand(0, "Land Grant", alternative_cost=True)
    resolve_stack(game)
    # The library search is a queued decision the spell does not wait on, so it
    # is drained the way an AI or headless seat drains one.
    game.auto_resolve_pending_choices(0)

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert caster.battlefield == []
    assert "Forest" in [held.name for held in caster.hand]
    revealed = [line for line in game.log if "revealed their hand" in line]
    assert len(revealed) == 1
    assert "Brainstorm" in revealed[0] and "Wild Jhovall" in revealed[0]
    # CR 601.2a: the spell is on the stack and cannot be among what it reveals.
    assert "Land Grant" not in revealed[0].split(": ", 1)[1]


def test_g1_land_grant_still_costs_its_mana_when_a_land_is_held(set_pool):
    """CR 118.9b: the alternative is optional and the printed cost stands.

    Which is exactly what Land Grant did on every board before this round -- the
    line was claimed by nothing, so it was always cast at ``{1}{G}``. The
    regression to watch for is the other direction, and it is the one this
    asserts: with a land in hand the offer is gone and the mana is still spent.
    """
    game, caster, _ = _g1_grant_table(
        set_pool, ["Land Grant", "Forest"], mine=("Forest", "Forest"),
    )
    caster.mana_pool["G"] = 1
    caster.mana_pool["C"] = 1

    result = game.cast_from_hand(0, "Land Grant")
    resolve_stack(game)

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert not any("revealed their hand" in line for line in game.log)


# --- W2G2: libraries and graveyards ---
# Bribery, Clear the Land, Midnight Ritual and Revive. The shared question is
# **whose pile**, and each of these four answers it with a seat that is not the
# obvious one: an opponent's library, every player's library, the caster's own
# graveyard read by an announced X, and a graveyard narrowed by a printed
# colour.
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from tests.helpers import resolve_stack

_W2G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g2_table(mine=(), theirs=()):
    """A two-seat game with the two libraries stocked, top card first.

    Every card in this block reads a library or a graveyard by position, so the
    order matters and the helper takes it. Mana enforcement is off, which is the
    standard rig.
    """
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.players[0].library.extend(mine)
    game.players[1].library.extend(theirs)
    return game, game.players[0], game.players[1]
    # end of _w2g2_table


def test_w2g2_revive_only_reaches_the_printed_colour(set_pool):
    """"Return target **green** card from your graveyard to your hand."

    The colour is this card's *whole* restriction -- its noun phrase names no
    card type at all -- so a lowering that dropped it would make Revive a
    Regrowth. Both directions, because a narrowing is only implemented when the
    illegal choice is refused as well as the legal one taken.
    """
    pool = set_pool("MMQ")
    game, caster, _ = _w2g2_table()
    caster.graveyard.extend(
        [_W2G2_LEA["Black Knight"], _W2G2_LEA["Llanowar Elves"]]
    )
    caster.hand.append(pool["Revive"])

    refused = game.cast_from_hand(0, "Revive", target_permanent_index=0)
    assert not refused.supported
    assert [c.name for c in caster.hand] == ["Revive"]

    taken = game.cast_from_hand(0, "Revive", target_permanent_index=1)
    resolve_stack(game)

    assert taken.supported, taken.details
    assert "Llanowar Elves" in [c.name for c in caster.hand]
    assert [c.name for c in caster.graveyard] == ["Black Knight", "Revive"]
    # end of test_w2g2_revive_only_reaches_the_printed_colour


def test_w2g2_midnight_ritual_exiles_announced_x_and_pays_per_card(set_pool):
    """"Exile **X target** creature cards from your graveyard. For each creature
    card exiled this way, create a 2/2 black Zombie creature token."

    Three things at once, each a separate refusal before this round: the pile is
    the caster's **own** (the counted graveyard exile read only a named
    opponent's), the count is the **announced X** (CR 601.2b -- written as a
    literal it arrives as 0 and the spell exiles nothing), and the tokens are
    one per card actually exiled rather than one per X.

    The non-creature card in the pile is the assertion that matters: it stays,
    and it buys no Zombie.
    """
    pool = set_pool("MMQ")
    game, caster, _ = _w2g2_table()
    caster.graveyard.extend([
        _W2G2_LEA["Grizzly Bears"],
        _W2G2_LEA["Lightning Bolt"],
        _W2G2_LEA["Black Knight"],
    ])
    caster.hand.append(pool["Midnight Ritual"])

    result = game.cast_from_hand(
        0, "Midnight Ritual", x_value=2, target_permanent_index=[0, 2],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert sorted(c.name for c in caster.exile) == [
        "Black Knight", "Grizzly Bears",
    ]
    assert [c.name for c in caster.graveyard] == [
        "Lightning Bolt", "Midnight Ritual",
    ]
    zombies = [p for p in game.controlled_by(0) if p.card.name == "Zombie Token"]
    assert len(zombies) == 2
    assert all(p.card.colors == ("B",) for p in zombies)
    # end of test_w2g2_midnight_ritual_exiles_announced_x_and_pays_per_card


def test_w2g2_bribery_steals_out_of_the_opponents_library(set_pool):
    """"Search **target opponent's** library for a creature card and put that
    card onto the battlefield **under your control**."

    The first card in this pool that separates *whose library is opened* from
    *whose battlefield receives*. ``search_filters.landing_seat`` follows the
    zone by default, so with the printed possessive dropped the Angel would
    enter on the side it came from -- which is this card backwards.

    And CR 108.3: it is still Bob's card. ``owner_index_of`` answered with the
    base controller on a stated assumption that every permanent enters under its
    owner's control, which this card is the first to falsify -- so the Angel
    would have gone to the thief's graveyard when it died (CR 404.1).
    """
    pool = set_pool("MMQ")
    game, caster, victim = _w2g2_table(theirs=[
        _W2G2_LEA["Mox Jet"], _W2G2_LEA["Serra Angel"], _W2G2_LEA["Forest"],
    ])
    caster.hand.append(pool["Bribery"])

    result = game.cast_from_hand(0, "Bribery", target_player_index=1)
    resolve_stack(game)
    assert result.supported, result.details

    owed = [c for c in game.pending_choices if c.kind == "search_library"]
    assert owed, "the caster should be owed the search"
    assert owed[0].player_index == 0
    assert owed[0].data["zone_seat"] == 1
    assert game.resolve_pending_choice(
        "search_library", 0, zone="library", library_index=1,
    )
    resolve_stack(game)

    mine = list(game.controlled_by(0))
    assert [p.card.name for p in mine] == ["Serra Angel"]
    assert not list(game.controlled_by(1))
    assert "Serra Angel" not in [c.name for c in victim.library]
    assert game.owner_index_of(mine[0]) == 1
    # end of test_w2g2_bribery_steals_out_of_the_opponents_library


def test_w2g2_clear_the_land_sorts_every_players_own_top_five(set_pool):
    """"**Each player** reveals the top five cards of **their** library, puts
    all land cards revealed this way onto the battlefield **tapped**, and exiles
    the rest."

    One sentence performed once per seat, and every clause of it is asserted:
    each player's *own* five (not the caster's ten), each player's lands onto
    that player's *own* battlefield, tapped (CR 110.5b), and everything else to
    that card's owner's exile rather than to a graveyard.
    """
    pool = set_pool("MMQ")
    game, caster, other = _w2g2_table(
        mine=[
            _W2G2_LEA["Forest"], _W2G2_LEA["Grizzly Bears"],
            _W2G2_LEA["Mountain"], _W2G2_LEA["Lightning Bolt"],
            _W2G2_LEA["Plains"], _W2G2_LEA["Black Lotus"],
        ],
        theirs=[
            _W2G2_LEA["Island"], _W2G2_LEA["Black Knight"],
            _W2G2_LEA["Swamp"], _W2G2_LEA["Mox Jet"],
            _W2G2_LEA["Llanowar Elves"], _W2G2_LEA["Serra Angel"],
        ],
    )
    caster.hand.append(pool["Clear the Land"])

    result = game.cast_from_hand(0, "Clear the Land")
    resolve_stack(game)

    assert result.supported, result.details
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Forest", "Mountain", "Plains",
    ]
    assert sorted(p.card.name for p in game.controlled_by(1)) == [
        "Island", "Swamp",
    ]
    assert all(p.tapped for p in game.controlled_by(0))
    assert all(p.tapped for p in game.controlled_by(1))
    assert sorted(c.name for c in caster.exile) == [
        "Grizzly Bears", "Lightning Bolt",
    ]
    assert sorted(c.name for c in other.exile) == [
        "Black Knight", "Llanowar Elves", "Mox Jet",
    ]
    # The sixth card of each library is untouched: the reveal is five deep.
    assert [c.name for c in caster.library] == ["Black Lotus"]
    assert [c.name for c in other.library] == ["Serra Angel"]
    # end of test_w2g2_clear_the_land_sorts_every_players_own_top_five


# --- W2G4: mass effects that count something ---
from engine import Game as _S4Game
from engine import PlayerState as _S4PlayerState
from engine.models import Permanent as _S4Permanent
from tests.helpers import _mk_creature_card as _s4_creature_card
from tests.helpers import resolve_stack as _s4_resolve


def _w2g4_table(set_pool, hand, mine=(), theirs=()):
    """A duel with *hand* on seat 0 and named permanents on both battlefields.

    Mana enforcement off, the house rig: nothing in this block is about paying
    for anything, so a charged cast would only add a way for a test to fail for
    a reason it is not about. A card given as a string comes from the set; one
    given as a `CardDefinition` is a fixture, so a sweep can be aimed at printed
    numbers the set does not happen to contain.
    """
    pool = set_pool("MMQ")
    caster, other = _S4PlayerState("Caster"), _S4PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    game = _S4Game(players=[caster, other])
    game.enforce_mana_costs = False
    for perm in mine:
        caster.battlefield.append(
            _S4Permanent(card=pool[perm] if isinstance(perm, str) else perm)
        )
    for perm in theirs:
        other.battlefield.append(
            _S4Permanent(card=pool[perm] if isinstance(perm, str) else perm)
        )
    game._settle()
    return game, caster, other


def test_w2g4_wave_of_reckoning_makes_every_creature_bite_itself(set_pool):
    """"Each creature deals damage to itself equal to its power."
    (Wave of Reckoning.)

    Every creature on the table, not one seat's — and the number is each
    creature's *own* power, so a 4/4 dies and a 1/5 does not. Both boards are
    populated, because a sweep that read one battlefield would pass this test
    with half the board untouched.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Wave of Reckoning"],
        mine=[_s4_creature_card("Bear", 2, 2), _s4_creature_card("Wall", 1, 5)],
        theirs=[_s4_creature_card("Giant", 4, 4)],
    )

    result = game.cast_from_hand(0, "Wave of Reckoning")
    _s4_resolve(game)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert sorted(p.card.name for p in game.all_permanents()) == ["Wall"]


def test_w2g4_wave_of_reckoning_deals_the_damage_as_the_permanent(set_pool):
    """CR 120.7: each creature is the *source* of the damage it takes.

    Routed through the sorcery instead, a creature with protection from white
    would shrug the whole card off and a lifelinker would gain nothing — so the
    log naming the creature is the observable half of the rule. A zero-power
    creature is not dealt to at all (CR 120.8), which is the other half.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Wave of Reckoning"],
        mine=[_s4_creature_card("Ox", 3, 9), _s4_creature_card("Nought", 0, 4)],
    )

    game.cast_from_hand(0, "Wave of Reckoning")
    _s4_resolve(game)

    board = {p.card.name: p for p in game.all_permanents()}
    assert board["Ox"].damage_marked == 3
    assert board["Nought"].damage_marked == 0
    assert any("Ox (3)" in line for line in game.log)


def test_w2g4_tectonic_break_sacrifices_x_lands_from_each_player(set_pool):
    """"Each player sacrifices X lands of their choice." (Tectonic Break.)

    CR 107.3: X is the announced number, carried as ``"x"`` and resolved at
    resolution. The count is a *flag* rather than a printed 0 or 1 precisely so
    this cannot pass by accident — read as the zero the noun phrase carries,
    each player would sacrifice nothing however large X was.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Tectonic Break"],
        mine=["Mountain", "Mountain", "Mountain"],
        theirs=["Plains", "Plains"],
    )

    result = game.cast_from_hand(0, "Tectonic Break", x_value=2)
    _s4_resolve(game)

    assert result.supported, result.details
    assert len(list(game.controlled_by(0))) == 1
    assert len(list(game.controlled_by(1))) == 0


def test_w2g4_tectonic_break_at_x_zero_takes_nothing(set_pool):
    """An announced X of 0 is a real answer (CR 107.3b) and costs both seats
    nothing — the assertion that the count is resolved rather than defaulted to
    the one every other printed sacrifice carries."""
    game, _caster, _other = _w2g4_table(
        set_pool, ["Tectonic Break"], mine=["Mountain"], theirs=["Plains"],
    )

    game.cast_from_hand(0, "Tectonic Break", x_value=0)
    _s4_resolve(game)

    assert len(list(game.controlled_by(0))) == 1
    assert len(list(game.controlled_by(1))) == 1


def test_w2g4_misstep_holds_down_the_named_players_creatures_only(set_pool):
    """"Creatures target player controls don't untap during that player's next
    untap step." (Misstep.)

    Two narrowings, each asserted against what it excludes: only *creatures*
    (the target's land is untouched) and only the *target's* (the caster's own
    creature unmarked). A sweep handed no seat matches nothing, and one handed
    the wrong seat holds down the caster's own board — so both directions have
    a permanent in this board to catch them.
    """
    game, _caster, _other = _w2g4_table(
        set_pool, ["Misstep"],
        mine=[_s4_creature_card("Mine", 2, 2)],
        theirs=[_s4_creature_card("Theirs", 2, 2), "Plains"],
    )

    result = game.cast_from_hand(0, "Misstep", target_player_index=1)
    _s4_resolve(game)

    assert result.supported, result.details
    assert {
        p.card.name: int(p.metadata.get("skip_next_untap") or 0)
        for p in game.all_permanents()
    } == {"Mine": 0, "Theirs": 1, "Plains": 0}


def test_w2g4_misstep_waits_for_the_named_players_untap_step(set_pool):
    """"…during **that player's** next untap step" — the seat the spell chose,
    frozen as the marker is made (CR 115.4).

    Not "their controller's", which is the elision one word away and the same
    answer until the creature changes hands. The seat is the whole of what this
    asserts, because the marker itself is identical either way — and an unseated
    marker is spent by whichever untap step reaches the permanent first.
    """
    from engine.handlers.tapping import SKIP_NEXT_UNTAP_SEAT

    game, _caster, _other = _w2g4_table(
        set_pool, ["Misstep"], theirs=[_s4_creature_card("Theirs", 2, 2)],
    )
    game.cast_from_hand(0, "Misstep", target_player_index=1)
    _s4_resolve(game)

    marked = next(p for p in game.all_permanents() if p.card.name == "Theirs")
    assert marked.metadata[SKIP_NEXT_UNTAP_SEAT] == 1


# --- W3G3: a round-robin over a shared pile of exiled cards ---
# Thieves' Auction: "Exile all nontoken permanents. Starting with you, each
# player chooses one of the exiled cards and puts it onto the battlefield tapped
# under their control. Repeat this process until all cards exiled this way have
# been chosen." One pile, every seat in turn (CR 101.4), and the loop ends on the
# pile rather than on a round -- so a board that does not divide evenly is the
# case worth asserting. What is checked below is the two boards, who owns what
# and what is left in exile, never that a sentence parsed.
from engine import Game as _W3G3Game
from engine import PlayerState as _W3G3PlayerState
from engine.models import Permanent as _W3G3Permanent


def _w3g3_auction(set_pool, mine=(), theirs=(), seats=2, interactive=()):
    """A table with Thieves' Auction in seat 0's hand and the named permanents
    on the first two boards."""
    pool = set_pool("MMQ")
    players = [
        _W3G3PlayerState(name) for name in ("Caster", "Opponent", "Third")[:seats]
    ]
    game = _W3G3Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    players[0].hand = [pool["Thieves' Auction"]]
    for name in mine:
        players[0].battlefield.append(_W3G3Permanent(card=pool[name]))
    for name in theirs:
        players[1].battlefield.append(_W3G3Permanent(card=pool[name]))
    return game, players


def _w3g3_settle(game):
    """Resolve the spell and answer every pick the round-robin arms.

    ``resolve_stack`` is not enough on its own here: the object leaves the stack
    on the headless path and the prompts are drained afterwards, which is the
    arrangement that keeps a seeded run reproducible.
    """
    game.resolve_top_of_stack()
    for _ in range(60):
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()
    raise AssertionError(
        f"the auction never finished; owed {[c.kind for c in game.pending_choices]}"
    )


def test_w3g3_auction_deals_the_whole_pile_out_in_turn(set_pool):
    """CR 101.4: every seat picks in turn, starting with the spell's controller,
    and the rounds go on while cards are left.

    Five permanents between two seats is three picks for the caster and two for
    the opponent -- which is the round-robin rather than a split of each board,
    and the exile zones being empty is what says the pile really ran out.
    """
    game, players = _w3g3_auction(
        set_pool,
        mine=("Alabaster Wall", "Plains"),
        theirs=("Charm Peddler", "Forest", "Cho-Manno, Revolutionary"),
    )
    game.queue_from_hand(0, "Thieves' Auction")

    _w3g3_settle(game)

    assert len(players[0].battlefield) == 3
    assert len(players[1].battlefield) == 2
    assert [card.name for card in players[0].exile] == []
    assert [card.name for card in players[1].exile] == []
    assert all(
        perm.tapped for player in players for perm in player.battlefield
    ), "'onto the battlefield tapped' is printed and is not a default"


def test_w3g3_auction_keeps_the_owner_when_it_changes_hands(set_pool):
    """CR 108.3: the card enters under the chooser's control and stays *owned*
    by the player whose permanent it was.

    The one fact the entry cannot re-derive, and the one that is invisible until
    the creature dies: without it Thieves' Auction quietly rewrites who owns a
    deck, and every card it handed over goes to the wrong graveyard.
    """
    game, players = _w3g3_auction(
        set_pool, mine=("Alabaster Wall",), theirs=("Cho-Manno, Revolutionary",),
    )
    game.queue_from_hand(0, "Thieves' Auction")

    _w3g3_settle(game)

    owners = {
        perm.card.name: game.owner_index_of(perm)
        for player in players for perm in player.battlefield
    }
    controllers = {
        perm.card.name: seat
        for seat, player in enumerate(players) for perm in player.battlefield
    }
    assert owners == {"Alabaster Wall": 0, "Cho-Manno, Revolutionary": 1}
    assert controllers["Cho-Manno, Revolutionary"] == 0, (
        "the caster picks first and takes the biggest card on the pile"
    )
    assert controllers["Alabaster Wall"] == 1


def test_w3g3_auction_stops_when_the_pile_runs_out_mid_round(set_pool):
    """"...until all cards exiled this way have been chosen" ends a round
    part-way.

    Four cards among three seats is one full pass and then one more pick: the
    seats behind the caster in the second round are asked nothing at all. A loop
    bounded by the *round* instead of the pile would either deal a fifth card
    that does not exist or stop a card early.
    """
    game, players = _w3g3_auction(
        set_pool,
        mine=("Alabaster Wall", "Plains"),
        theirs=("Charm Peddler", "Forest"),
        seats=3,
    )
    game.queue_from_hand(0, "Thieves' Auction")

    _w3g3_settle(game)

    assert [len(player.battlefield) for player in players] == [2, 1, 1]
    assert not any(player.exile for player in players)


def test_w3g3_auction_waits_for_an_interactive_seat(set_pool):
    """CR 608.2 / CR 117.3b: the spell stays on the stack while a pick is owed.

    And the offered list is the pile as it *stands* -- the answer is an index
    into what the prompt showed, and the resolver re-checks it against the same
    list, so a seat cannot claim a card another seat has already taken.
    """
    game, players = _w3g3_auction(
        set_pool,
        mine=("Alabaster Wall",),
        theirs=("Charm Peddler", "Cho-Manno, Revolutionary"),
        interactive=(0,),
    )
    game.queue_from_hand(0, "Thieves' Auction")
    game.resolve_top_of_stack(pause_for_choices=True)

    owed = game.waiting_prompt()
    assert owed is not None and owed.kind == "exiled_pile_claim"
    assert owed.player_index == 0
    assert owed.data["options"] == [
        "Alabaster Wall", "Charm Peddler", "Cho-Manno, Revolutionary"
    ]
    assert game.stack, "a resolution that stopped to ask keeps its object"

    assert game.confirm_exiled_pile_claim(0, 1) is True
    for _ in range(60):
        if not game.pending_choices:
            break
        game.auto_resolve_pending_choices()

    # The answered pick, and then the third card on the caster's second turn of
    # the round-robin: the opponent's default took the most expensive of what
    # was left in between.
    assert [perm.card.name for perm in players[0].battlefield] == [
        "Charm Peddler", "Alabaster Wall",
    ]
    assert [perm.card.name for perm in players[1].battlefield] == [
        "Cho-Manno, Revolutionary",
    ]
    assert not game.stack


def test_w3g3_auction_refuses_a_pile_index_that_is_not_on_offer(set_pool):
    """Idiom 9: the answer is re-checked against the pile, not trusted.

    A client holding a list from before the seats ahead answered would otherwise
    hand out a card that is no longer there -- or, past the end, nothing at all
    while the loop counted it as a pick and moved on.
    """
    game, _players = _w3g3_auction(
        set_pool, mine=("Alabaster Wall",), theirs=("Charm Peddler",),
        interactive=(0,),
    )
    game.queue_from_hand(0, "Thieves' Auction")
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.confirm_exiled_pile_claim(0, 7) is False
    assert game.waiting_prompt() is not None, "a refused answer leaves the prompt"


def test_w3g3_auction_carries_the_repeat_clause_into_the_round(set_pool):
    """The printed "repeat this process" is the difference between this card and
    one where each seat takes exactly one.

    Asserted on the compiled payload because a duel cannot tell the two apart on
    a two-card board -- and the flag is what the handler reads to decide whether
    there is another round at all.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("MMQ")["Thieves' Auction"])
    steps = program.instructions[0].payload["steps"]

    assert [step.kind for step in steps] == [
        "exile_all_matching", "claim_exiled_cards_in_turn",
    ]
    assert steps[1].payload == {
        "claim_order": "you", "tapped": True, "until_pile_empty": True,
    }

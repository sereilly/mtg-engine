"""Per-card tests for Alliances' lands.

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


# --- W1G1: the land cycle ---
"""The Alliances entry toll (CR 614.1a / 614.12) and the two shapes it prints.

Five lands say "sacrifice <a permanent> instead. If you do, put this land onto
the battlefield. If you don't, put it into its owner's graveyard"; Sheltered
Valley says "instead sacrifice each other permanent named Sheltered Valley you
control, then put this land onto the battlefield" -- the same replacement with
no failure branch, because an empty set is something every player can give up.

Checked from both ends deliberately. The census can only say the cards compile;
what these assert is that the *toll is charged* -- which permanent goes, that a
tapped one does not answer a clause printed "untapped", and that a board with
nothing to pay leaves the land in a graveyard having never entered.
"""

from engine import Game, PlayerState
from engine.models import Permanent


def _w1g1_board(set_pool, *land_names, seat1=(), interactive=()):
    """Seat 0 holding *land_names*, seat 1 holding *seat1*.

    Names resolve out of ALL first and LEA second, so "Sheltered Valley" and
    "Mountain" are both spellable in one list.
    """
    all_pool, lea = set_pool("ALL"), set_pool("LEA")

    def card(name):
        return all_pool.get(name) or lea[name]

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=card(n)) for n in land_names])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=card(n)) for n in seat1])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game.interactive_seats = set(interactive)
    return game, p1, p2, card


def _w1g1_play(game, card, seat=0):
    """Put *card* onto *seat*'s battlefield through the one entry path there is,
    which is where the CR 614 replacement is asked."""
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def test_w1g1_the_toll_is_paid_and_the_land_enters(set_pool):
    game, p1, _p2, card = _w1g1_board(set_pool, "Mountain")

    _w1g1_play(game, card("Balduvian Trading Post"))

    assert [p.card.name for p in p1.battlefield] == ["Balduvian Trading Post"]
    assert [c.name for c in p1.graveyard] == ["Mountain"]


def test_w1g1_nothing_to_pay_with_puts_the_land_in_its_owners_graveyard(set_pool):
    """"If you don't, put it into its owner's graveyard." A *consuming*
    replacement: the land never enters, so nothing that watches an entry sees
    it -- the battlefield is untouched and the card is in the graveyard."""
    game, p1, _p2, card = _w1g1_board(set_pool, "Forest")

    _w1g1_play(game, card("Balduvian Trading Post"))

    assert [p.card.name for p in p1.battlefield] == ["Forest"]
    assert [c.name for c in p1.graveyard] == ["Balduvian Trading Post"]


def test_w1g1_a_tapped_mountain_cannot_pay_an_untapped_clause(set_pool):
    """The printed word "untapped" is enforced, not carried and dropped.

    This is the half a census cannot see: the card compiles either way, and a
    toll that accepted a tapped Mountain would be a land that entered more
    often than it prints.
    """
    game, p1, _p2, card = _w1g1_board(set_pool, "Mountain")
    p1.battlefield[0].tapped = True

    _w1g1_play(game, card("Balduvian Trading Post"))

    assert [c.name for c in p1.graveyard] == ["Balduvian Trading Post"]
    assert p1.battlefield[0].card.name == "Mountain", "still there, still tapped"


def test_w1g1_lake_of_the_dead_accepts_a_tapped_swamp(set_pool):
    """Its sibling prints no "untapped", so the same machinery must not add
    one -- the noun phrase is payload and the five cards differ only by it."""
    game, p1, _p2, card = _w1g1_board(set_pool, "Swamp")
    p1.battlefield[0].tapped = True

    _w1g1_play(game, card("Lake of the Dead"))

    assert [p.card.name for p in p1.battlefield] == ["Lake of the Dead"]
    assert [c.name for c in p1.graveyard] == ["Swamp"]


def test_w1g1_an_opponents_mountain_cannot_pay_the_toll(set_pool):
    """CR 701.21a: a player can only sacrifice something they control. The toll
    reads one seat's battlefield -- the one the land would enter under."""
    game, p1, p2, card = _w1g1_board(set_pool, "Forest", seat1=["Mountain"])

    _w1g1_play(game, card("Balduvian Trading Post"))

    assert [c.name for c in p1.graveyard] == ["Balduvian Trading Post"]
    assert [p.card.name for p in p2.battlefield] == ["Mountain"], "untouched"


def test_w1g1_two_mountains_ask_the_player_which(set_pool):
    """CR 701.21a leaves the choice to the sacrificing player, so an interactive
    seat is prompted rather than having one picked for it."""
    game, p1, _p2, card = _w1g1_board(
        set_pool, "Mountain", "Mountain", interactive=[0]
    )

    _w1g1_play(game, card("Balduvian Trading Post"))
    prompt = game.pending_sacrifice_state()

    assert prompt is not None
    assert prompt["count"] == 1 and not prompt["up_to"]
    assert len(prompt["valid_indices"]) == 2

    assert game.confirm_sacrifice(0, [prompt["valid_indices"][0]])
    assert [c.name for c in p1.graveyard] == ["Mountain"]
    assert "Balduvian Trading Post" in [p.card.name for p in p1.battlefield]


def test_w1g1_every_land_of_the_cycle_reads_its_own_noun(set_pool):
    """One production, five cards, one word changed. Asked of the reader both
    seams share, so what is claimed and what is charged cannot drift."""
    from engine.enter_effects import entry_sacrifice_requirement

    pool = set_pool("ALL")
    expected = {
        "Balduvian Trading Post": {"subtype_filter": "mountain", "untapped_only": True},
        "Heart of Yavimaya": {"subtype_filter": "forest"},
        "Kjeldoran Outpost": {"subtype_filter": "plains"},
        "Lake of the Dead": {"subtype_filter": "swamp"},
        "Soldevi Excavations": {"subtype_filter": "island", "untapped_only": True},
    }
    for name, described in expected.items():
        toll = entry_sacrifice_requirement(pool[name])
        assert toll == {"filter": described, "count": 1, "unpaid": "graveyard"}, name


def test_w1g1_sheltered_valley_enters_with_no_other_copy(set_pool):
    """No failure branch: an empty set is something everybody can give up, so
    the land enters whatever the board holds."""
    game, p1, _p2, card = _w1g1_board(set_pool, "Forest")

    _w1g1_play(game, card("Sheltered Valley"))

    assert [p.card.name for p in p1.battlefield] == ["Forest", "Sheltered Valley"]
    assert not p1.graveyard


def test_w1g1_sheltered_valley_sacrifices_every_other_copy_you_control(set_pool):
    game, p1, _p2, card = _w1g1_board(
        set_pool, "Sheltered Valley", "Sheltered Valley", "Forest"
    )

    _w1g1_play(game, card("Sheltered Valley"))

    assert [p.card.name for p in p1.battlefield] == ["Forest", "Sheltered Valley"]
    assert [c.name for c in p1.graveyard] == ["Sheltered Valley"] * 2


def test_w1g1_sheltered_valley_leaves_an_opponents_copy_alone(set_pool):
    """"...you control" is a restriction, and one dropped here would sacrifice
    permanents on a board the card never names."""
    game, p1, p2, card = _w1g1_board(
        set_pool, "Sheltered Valley", seat1=["Sheltered Valley"]
    )

    _w1g1_play(game, card("Sheltered Valley"))

    assert [c.name for c in p1.graveyard] == ["Sheltered Valley"]
    assert [p.card.name for p in p2.battlefield] == ["Sheltered Valley"]
    assert not p2.graveyard


def test_w1g1_sheltered_valley_names_itself_and_not_the_phrase_this_creature(set_pool):
    """The regression the self-reference collapse would have caused.

    ``_self_normalized`` rewrites a card that names itself into "this <noun>",
    and it rewrites the *whole line* -- so "each other permanent **named
    Sheltered Valley**" arrived asking for permanents named "this creature",
    a name nothing has. The card would have compiled supported and sacrificed
    nothing, silently, every time.
    """
    from engine.enter_effects import entry_sacrifice_requirement

    toll = entry_sacrifice_requirement(set_pool("ALL")["Sheltered Valley"])

    assert toll == {
        "filter": {"named": "sheltered valley"}, "count": "all", "unpaid": None,
    }


def test_w1g1_sheltered_valleys_upkeep_gain_reads_its_intervening_if(set_pool):
    """"At the beginning of your upkeep, **if you control three or fewer
    lands**, you gain 1 life." (CR 603.4.) The bound is the whole card, so a
    gate nothing checks is a land that gains life every upkeep forever."""
    game, p1, _p2, _card = _w1g1_board(
        set_pool, "Sheltered Valley", "Forest", "Forest"
    )
    p1.life = 20

    game.resolve_upkeep(0)
    game._settle()

    assert p1.life == 21

    game, p1, _p2, _card = _w1g1_board(
        set_pool, "Sheltered Valley", "Forest", "Forest", "Forest", "Forest"
    )
    p1.life = 20

    game.resolve_upkeep(0)
    game._settle()

    assert p1.life == 20, "five lands is more than three"


def test_w1g1_the_cycles_other_lines_still_work(set_pool):
    """The toll is one line of three, and a land that pays it and then taps for
    nothing is a card doing less than it prints."""
    game, p1, _p2, card = _w1g1_board(set_pool, "Plains")
    outpost = _w1g1_play(game, card("Kjeldoran Outpost"))
    outpost.metadata["summoning_sickness_turn"] = -99
    p1.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}

    assert game.tap_land_for_mana(0, "Kjeldoran Outpost", permanent_index=0)

    assert p1.mana_pool["W"] == 1
# --- end W1G1 ---

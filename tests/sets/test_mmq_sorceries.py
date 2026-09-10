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

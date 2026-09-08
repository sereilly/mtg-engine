"""Urza's Saga sorceries.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The three sorceries with cycling. All three reported supported before the
#: rewrite, with the keyword unclaimed — see the instants file for why that is
#: the interesting half.
_G1_CYCLING_SORCERIES = ("Lay Waste", "Hush", "Rejuvenate")


def _g1_sorcery_game(card, *, library=4):
    """Seat 0 holds *card* over a library of copies of it. Named for this block."""
    player = PlayerState(name="G1-S", hand=[card], library=[card] * library)
    return Game(players=[player, PlayerState(name="G1-T")]), player


@pytest.mark.parametrize("name", _G1_CYCLING_SORCERIES)
def test_w1g1_a_cycling_sorcery_is_discarded_for_a_card(set_pool, name):
    """Rejuvenate is the one to read: cycled, it gains no life. A rewrite that
    let the spell's own line resolve would be invisible on the other two."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    game, player = _g1_sorcery_game(card)
    game.enforce_mana_costs = False
    life_before = player.life

    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert [c.name for c in player.graveyard] == [name]
    assert len(player.library) == 3
    assert player.life == life_before


# --- W2G2: the graveyard as a zone — Planar Birth, Exhume, Gamble, Yawgmoth's Will ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2s_cast(set_pool, name, *, seat=0):
    """Two seats, *name* in *seat*'s hand, costs off. W2G2's own sorcery helper."""
    alice, bob = PlayerState(name="G2S-A"), PlayerState(name="G2S-B")
    alice.hand = [set_pool("USG")[name]] if seat == 0 else []
    bob.hand = [set_pool("USG")[name]] if seat == 1 else []
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    return game, alice, bob


def test_w2g2_planar_birth_returns_every_seat_s_basics_tapped(set_pool):
    """"Return all basic land cards from all graveyards to the battlefield
    tapped under their owners' control."

    Four claims, one per printed word: *all graveyards* (the opponent's pile is
    swept too), *basic* (the nonbasic land stays put), *tapped*, and *their
    owners'* (each land arrives on its own owner's side, not the caster's).
    """
    pool = set_pool("USG")
    game, alice, bob = _g2s_cast(set_pool, "Planar Birth")
    alice.graveyard = [pool["Plains"], pool["Gaea's Cradle"]]
    bob.graveyard = [pool["Swamp"]]

    game.cast_from_hand(0, "Planar Birth")
    resolve_stack(game)

    mine = [p.card.name for p in game.controlled_by(0)]
    theirs = [p.card.name for p in game.controlled_by(1)]
    assert mine == ["Plains"]
    assert theirs == ["Swamp"]
    assert all(p.tapped for p in game.all_permanents())
    assert [c.name for c in alice.graveyard] == ["Gaea's Cradle", "Planar Birth"]
    assert not bob.graveyard


def test_w2g2_gamble_discards_after_the_tutor_not_before(set_pool):
    """"Search your library for a card, put that card into your hand, discard a
    card at random, then shuffle."

    The whole card is the order: the tutored card is in the hand the random
    discard reaches, which is why a hand of exactly one card — the find — must
    end up empty. A lowering that put the discard first would leave the find
    sitting in hand and the test would read as a pass with the card broken.
    """
    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Gamble")
    wanted = pool["Shivan Hellkite"]
    alice.library = [wanted, wanted]

    game.cast_from_hand(0, "Gamble")
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="library"
    )
    game._settle()

    assert not alice.hand
    assert [c.name for c in alice.graveyard] == [wanted.name, "Gamble"]


def test_w2g2_gamble_leaves_a_second_card_alone(set_pool):
    """One card is discarded, not the hand: the count is data. Read over a hand
    of two so a discard that emptied it would show."""
    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Gamble")
    alice.hand.append(pool["Serra Zealot"])
    alice.library = [pool["Shivan Hellkite"]] * 2

    game.cast_from_hand(0, "Gamble")
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="library"
    )
    game._settle()

    assert len(alice.hand) == 1


def test_w2g2_exhume_gives_every_seat_its_own_pick(set_pool):
    """"Each player puts a creature card from their graveyard onto the
    battlefield."

    Two prompts, one per seat, each over that seat's own pile — and the seat
    that answers is not the seat that cast the spell, which is the half a
    reanimation resolving one target could not express. The opponent's creature
    must arrive on the opponent's side.
    """
    pool = set_pool("USG")
    game, alice, bob = _g2s_cast(set_pool, "Exhume")
    alice.graveyard = [pool["Serra Zealot"]]
    bob.graveyard = [pool["Shivan Hellkite"]]

    game.cast_from_hand(0, "Exhume")

    owed = [c.player_index for c in game.pending_choices if c.kind == "search_library"]
    assert sorted(owed) == [0, 1]

    for seat in (0, 1):
        assert game.resolve_pending_choice(
            "search_library", seat, library_index=0, zone="graveyard"
        )
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Serra Zealot"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Shivan Hellkite"]


def test_w2g2_exhume_asks_nobody_over_an_empty_graveyard(set_pool):
    """A prompt over a pile with no creature card in it is a decision with one
    answer, and arming it would stop the game to ask it. CR 608.2's "as much as
    possible": the seat with nothing puts nothing."""
    pool = set_pool("USG")
    game, alice, bob = _g2s_cast(set_pool, "Exhume")
    alice.graveyard = [pool["Serra Zealot"]]
    bob.graveyard = [pool["Gamble"]]

    game.cast_from_hand(0, "Exhume")

    owed = [c.player_index for c in game.pending_choices if c.kind == "search_library"]
    assert owed == [0]


def test_w2g2_ill_gotten_gains_empties_both_hands_then_offers_both_graveyards(set_pool):
    """"Exile Ill-Gotten Gains. Each player discards their hand, then returns up
    to three cards from their graveyard to their hand."

    Three claims in printed order: the spell exiles itself rather than going to
    a graveyard it is about to let people raid, both hands are emptied — not
    just the caster's — and each seat is then offered its *own* pile. The
    discarded cards are in the graveyard the offer reads, which is the whole
    card.
    """
    pool = set_pool("USG")
    game, alice, bob = _g2s_cast(set_pool, "Ill-Gotten Gains")
    alice.hand.append(pool["Serra Zealot"])
    bob.hand = [pool["Shivan Hellkite"], pool["Gamble"]]

    game.cast_from_hand(0, "Ill-Gotten Gains")

    assert not alice.hand and not bob.hand

    owed = {
        c.player_index: c.data["count"]
        for c in game.pending_choices if c.kind == "search_library"
    }
    assert owed == {0: 1, 1: 2}, "the ceiling is capped by each seat's own pile"

    # A one-slot offer takes the single-find answer and a counted one is
    # answered whole; both are the ordinary search prompt's two shapes.
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="graveyard"
    )
    assert game.confirm_search_library_picks(
        1, [{"zone": "graveyard", "index": 0}]
    )
    game._settle()

    assert [c.name for c in alice.hand] == ["Serra Zealot"]
    # One of the two the ceiling allowed: "up to" is an offer, and a seat that
    # takes fewer has answered it.
    assert len(bob.hand) == 1
    # CR 608.2n: the spell is binned as the last part of its own resolution,
    # which is after the prompts it armed have been answered — so it goes to
    # exile rather than to the graveyard the offer had just read.
    assert [c.name for c in alice.exile] == ["Ill-Gotten Gains"]
    assert not any(c.name == "Ill-Gotten Gains" for c in alice.graveyard)


def test_w2g2_victimize_returns_both_announced_cards_tapped(set_pool):
    """"Choose two target creature cards in your graveyard. Sacrifice a
    creature. If you do, return the chosen cards to the battlefield tapped."

    Four claims: the picker offers two cards out of the caster's own pile, the
    sacrifice is paid, both announced cards come back (not one), and they come
    back tapped. The third card in the graveyard is the control — a return that
    swept the pile would bring it too.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Victimize")
    zealot, hellkite = pool["Serra Zealot"], pool["Shivan Hellkite"]
    alice.graveyard = [zealot, hellkite, pool["Sanctum Custodian"]]
    fodder = Permanent(card=pool["Sanctum Custodian"])
    game._put_permanent_onto_battlefield(0, fodder, None)

    spec = derive_cast_spec(
        pool["Victimize"], compile_card_oracle(pool["Victimize"])
    )
    assert spec["own_graveyard_only"] and spec["max_targets"] == 2
    assert spec["exact_targets"], "'two target' is a number, not a ceiling"

    game.cast_from_hand(0, "Victimize", target_permanent_index=[0, 1])
    resolve_stack(game)

    back = sorted(p.card.name for p in game.controlled_by(0))
    assert back == ["Serra Zealot", "Shivan Hellkite"]
    assert all(p.tapped for p in game.controlled_by(0))
    assert [c.name for c in alice.graveyard] == [
        "Sanctum Custodian", "Sanctum Custodian", "Victimize",
    ]


def test_w2g2_victimize_returns_nothing_with_no_creature_to_sacrifice(set_pool):
    """"**If you do**" — the price is real. With nothing to sacrifice the cards
    stay in the graveyard, which is the half `_action_is_takeable` exists for:
    an empty action firing its rider is a spell that reanimates for free.
    """
    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Victimize")
    alice.graveyard = [pool["Serra Zealot"], pool["Shivan Hellkite"]]

    game.cast_from_hand(0, "Victimize", target_permanent_index=[0, 1])
    resolve_stack(game)

    assert not list(game.controlled_by(0))
    assert [c.name for c in alice.graveyard] == [
        "Serra Zealot", "Shivan Hellkite", "Victimize",
    ]


def test_w2g2_yawgmoths_will_opens_the_graveyard_to_lands_and_spells(set_pool):
    """"Until end of turn, you may play lands and cast spells from your
    graveyard."

    Both halves, because "play" is the word that covers both (CR 305.1 plays a
    land, CR 601.2 casts a spell) and a grant read as "cast" alone would offer
    the sorcery and refuse the land. The opponent's pile is the control: the
    permission is one seat's.
    """
    from engine.cast_permissions import playable_from_zones

    pool = set_pool("USG")
    game, alice, bob = _g2s_cast(set_pool, "Yawgmoth's Will")
    alice.graveyard = [pool["Gamble"], pool["Plains"]]
    bob.graveyard = [pool["Gamble"]]

    game.cast_from_hand(0, "Yawgmoth's Will")
    resolve_stack(game)

    offered = {
        (entry["owner_seat"], entry["name"])
        for entry in playable_from_zones(game, 0)
    }
    assert offered == {(0, "Gamble"), (0, "Plains")}
    assert not playable_from_zones(game, 1)


def test_w2g2_yawgmoths_will_exiles_what_would_reach_your_graveyard(set_pool):
    """"If a card would be put into your graveyard from anywhere this turn,
    exile that card instead."

    CR 614, and the seat is real: the caster's card is exiled and the
    opponent's still reaches their graveyard. The spell itself is the third
    assertion — it is a card put into its controller's graveyard, so its own
    replacement catches it (CR 608.2n happens while the effect is still on).
    """
    pool = set_pool("USG")
    game, alice, bob = _g2s_cast(set_pool, "Yawgmoth's Will")

    game.cast_from_hand(0, "Yawgmoth's Will")
    resolve_stack(game)

    assert alice.exile_cards_bound_for_graveyard_this_turn
    assert [c.name for c in alice.exile] == ["Yawgmoth's Will"]
    assert not alice.graveyard

    game.put_card_into_graveyard(alice, pool["Gamble"])
    game.put_card_into_graveyard(bob, pool["Gamble"])

    assert [c.name for c in alice.exile] == ["Yawgmoth's Will", "Gamble"]
    assert not alice.graveyard
    assert [c.name for c in bob.graveyard] == ["Gamble"]


def test_w2g2_yawgmoths_will_forgets_at_the_turn_boundary(set_pool):
    """"This turn" is the window. Both halves end at cleanup (CR 514.2), and the
    replacement is the one that would be silently permanent if nothing swept
    it — a card whose graveyard never fills again is a different game."""
    from engine.cast_permissions import playable_from_zones

    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Yawgmoth's Will")
    alice.graveyard = [pool["Gamble"]]

    game.cast_from_hand(0, "Yawgmoth's Will")
    resolve_stack(game)
    assert playable_from_zones(game, 0)

    # Two sweeps, because the two halves forget in two places: the permission
    # at CR 514.2's cleanup, and the per-seat record with every other "this
    # turn" record as the next turn's bookkeeping runs. The replacement is
    # therefore still armed *during* the cleanup step, which is what CR 514.2
    # says — a card discarded to hand size is still exiled.
    game.resolve_cleanup_step(0)
    assert alice.exile_cards_bound_for_graveyard_this_turn
    assert not playable_from_zones(game, 0)

    game.begin_turn_bookkeeping(1)
    assert not alice.exile_cards_bound_for_graveyard_this_turn


def test_w2g2_yawgmoths_will_actually_plays_the_land_and_casts_the_spell(set_pool):
    """The Rock Hydra half of the permission: both halves are driven rather
    than read off a list.

    And the two lines meet at the end — the sorcery cast out of the graveyard
    does not go back to it, because the *other* line is still on (CR 608.2n
    puts a resolving spell's card into its owner's graveyard, and this turn
    that is an exile).
    """
    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Yawgmoth's Will")
    alice.graveyard = [pool["Gamble"], pool["Plains"]]
    alice.library = [pool["Serra Zealot"]] * 3
    game.active_player_index = 0

    game.cast_from_hand(0, "Yawgmoth's Will")
    resolve_stack(game)

    assert game.cast_from_hand(0, "Plains", from_zone="graveyard").supported
    assert [p.card.name for p in game.controlled_by(0)] == ["Plains"]

    assert game.cast_from_hand(0, "Gamble", from_zone="graveyard").supported
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="library"
    )
    game._settle()

    assert not alice.graveyard
    assert sorted(c.name for c in alice.exile) == [
        "Gamble", "Serra Zealot", "Yawgmoth's Will",
    ]

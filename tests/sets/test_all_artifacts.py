"""Per-card tests for Alliances' artifacts.

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


# --- W1G1: the land-family artifacts ---
"""Mishra's Groundbreaker and Storm Cauldron.

Both are artifacts about *lands*, and each needed a piece the pool had never
printed: an animation with no duration at all (CR 611.2a -- "if no duration is
stated, it lasts until the end of the game"), and a land-play permission that
names every seat rather than the source's controller (CR 305.2).

Storm Cauldron's second line is the one worth watching. It compiles a real
instruction and is carried out *inline* at the tap-for-mana seam rather than on
the stack, because a land is tapped part-way through paying a cost (CR 601.2g)
and there is no stack to enqueue onto yet -- the same arrangement Manabarbs'
damage has. So the assertions below are behavioural: the mana arrives, and then
the land does not.
"""

from engine import Game, PlayerState
from engine.models import Permanent


def _w1g1a_board(set_pool, *names, seat1=()):
    """Seat 0 holding *names*, seat 1 holding *seat1*; ALL first, LEA second."""
    all_pool, lea = set_pool("ALL"), set_pool("LEA")

    def card(name):
        return all_pool.get(name) or lea[name]

    p1 = PlayerState(name="P1", battlefield=[Permanent(card=card(n)) for n in names])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=card(n)) for n in seat1])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    for perm in (*p1.battlefield, *p2.battlefield):
        perm.metadata["summoning_sickness_turn"] = -99
    return game, p1, p2


def test_w1g1_groundbreaker_animates_a_land(set_pool):
    """"Target land becomes a 3/3 artifact creature that's still a land."

    Three claims in one sentence and each is asserted: the P/T, the added
    artifact type ("a land animated without it is a permanent Shatter cannot
    reach"), and the land type it keeps.
    """
    game, p1, _p2 = _w1g1a_board(set_pool, "Mishra's Groundbreaker", "Forest")
    forest = p1.battlefield[1]
    assert not forest.is_creature

    result = game.activate_permanent_ability(
        0, "Mishra's Groundbreaker", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    assert result.supported
    assert forest.is_creature
    assert forest.has_type("artifact"), "a 3/3 **artifact** creature"
    assert forest.has_type("land"), "that's still a land"
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)
    assert [c.name for c in p1.graveyard] == ["Mishra's Groundbreaker"], "sacrificed"


def test_w1g1_groundbreakers_animation_outlives_the_turn(set_pool):
    """"(This effect lasts indefinitely.)" -- CR 611.2a's default duration,
    which the printed sentence states by saying nothing.

    The whole point of the second instruction kind: the record goes on a key
    the cleanup sweep does not clear, and the P/T on the persistent channel
    rather than the until-end-of-turn one. A record on the swept key would end
    the effect the turn it began; a P/T on the swept channel would leave a land
    that is a creature with no size and dies to CR 704.5f.
    """
    game, p1, _p2 = _w1g1a_board(set_pool, "Mishra's Groundbreaker", "Forest")
    forest = p1.battlefield[1]
    game.activate_permanent_ability(
        0, "Mishra's Groundbreaker", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()

    game.resolve_cleanup_step(0)
    game.resolve_untap_step(1)
    game.resolve_cleanup_step(1)

    assert forest.is_creature
    assert forest.has_type("artifact") and forest.has_type("land")
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)


def test_w1g1_storm_cauldron_grants_every_seat_a_second_land_drop(set_pool):
    """"**Each player** may play an additional land during each of their
    turns." The seat the sentence names is the whole difference from Fastbond's
    "you", and reading one as the other is a card that only ever helped
    whoever cast it."""
    game, _p1, _p2 = _w1g1a_board(set_pool, "Storm Cauldron")

    game.lands_played_this_turn[0] = 1
    assert game._may_play_another_land(0)
    game.lands_played_this_turn[0] = 2
    assert not game._may_play_another_land(0), "one additional, not any number"

    game.lands_played_this_turn[1] = 1
    assert game._may_play_another_land(1), "an opponent's Cauldron grants it too"


def test_w1g1_storm_cauldron_returns_the_tapped_land_and_keeps_the_mana(set_pool):
    """"Whenever a land is tapped for mana, return it to its owner's hand."

    The mana ability already resolved (CR 605.3b), so the land leaving
    afterwards takes nothing back -- which is what makes the card playable at
    all rather than a blank.
    """
    game, p1, _p2 = _w1g1a_board(set_pool, "Storm Cauldron", "Mountain")
    p1.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}

    assert game.tap_land_for_mana(0, "Mountain", permanent_index=1)

    assert p1.mana_pool["R"] == 1
    assert [p.card.name for p in p1.battlefield] == ["Storm Cauldron"]
    assert [c.name for c in p1.hand] == ["Mountain"]


def test_w1g1_storm_cauldron_bounces_an_opponents_land_too(set_pool):
    """"Whenever **a land** is tapped for mana" names no seat, so a Cauldron
    reaches every board. Scoping it to its controller's would have been right
    in a duel by coincidence and wrong about the card."""
    game, _p1, p2 = _w1g1a_board(set_pool, "Storm Cauldron", seat1=["Forest"])
    p2.mana_pool = {symbol: 0 for symbol in ("W", "U", "B", "R", "G", "C")}

    assert game.tap_land_for_mana(1, "Forest", permanent_index=0)

    assert p2.mana_pool["G"] == 1
    assert not p2.battlefield
    assert [c.name for c in p2.hand] == ["Forest"]


def test_w1g1_two_storm_cauldrons_bounce_the_land_once(set_pool):
    """Two copies are two triggers over one event. The second finds a permanent
    that has already left, and bouncing it again would put a second copy of the
    card into its owner's hand out of nowhere."""
    game, p1, _p2 = _w1g1a_board(
        set_pool, "Storm Cauldron", "Storm Cauldron", "Mountain"
    )

    assert game.tap_land_for_mana(0, "Mountain", permanent_index=2)

    assert [c.name for c in p1.hand] == ["Mountain"]
# --- end W1G1 ---


# --- W1G2: library-top costs ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g2_card(
    name: str, type_line: str, mana_cost: str = "", cmc: float = 0.0,
    *, keywords: tuple[str, ...] = (), toughness: int = 1,
) -> CardDefinition:
    """A vanilla card to stack a library, a graveyard or a battlefield with."""
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line,
        oracle_text="\n".join(word.capitalize() for word in keywords),
        colors=(), color_identity=(), keywords=keywords, produced_mana=(),
        raw={
            "name": name, "type_line": type_line,
            "power": "1", "toughness": str(toughness),
        },
    )


def _w1g2_board(set_pool, name: str, *, library=(), graveyard=(), opposing=()):
    """*name* on the battlefield, with the zones each test needs under it."""
    perm = Permanent(card=set_pool("ALL")[name])
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(
            name="P1", battlefield=[perm], library=list(library),
            graveyard=list(graveyard),
        ),
        PlayerState(
            name="P2",
            battlefield=[Permanent(card=card) for card in opposing],
            library=[_w1g2_card("Filler", "Artifact")] * 5,
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, perm


def test_whirling_catapult_exiles_two_cards_and_sweeps_the_fliers(set_pool):
    """"{2}, Exile the top two cards of your library: This artifact deals 1
    damage to each creature with flying and each player."

    The counted cost paid in full, and the effect behind it — a card whose
    cost the engine parsed and nobody charged would look exactly like a
    working card from the effect alone.
    """
    flier = _w1g2_card(
        "Winged Thing", "Creature - Bird", keywords=("flying",), toughness=3
    )
    ground = _w1g2_card("Ground Thing", "Creature - Bear", toughness=3)
    game, _catapult = _w1g2_board(
        set_pool, "Whirling Catapult",
        library=[_w1g2_card("Card", "Artifact")] * 3, opposing=[flier, ground],
    )
    me, them = game.players
    assert game.activate_permanent_ability(0, "Whirling Catapult").supported
    assert len(me.library) == 1 and len(me.exile) == 2
    game.resolve_top_of_stack()
    assert me.life == 19 and them.life == 19
    marked = {
        perm.card.name: perm.damage_marked for perm in game.controlled_by(1)
    }
    assert marked == {"Winged Thing": 1, "Ground Thing": 0}


def test_whirling_catapult_is_unactivatable_on_a_one_card_library(set_pool):
    """CR 118.3: one card does not pay a two-card cost, and the one card stays
    where it is rather than being eaten for half an activation."""
    game, _catapult = _w1g2_board(
        set_pool, "Whirling Catapult", library=[_w1g2_card("Card", "Artifact")]
    )
    me = game.players[0]
    assert not game.activate_permanent_ability(0, "Whirling Catapult").supported
    assert len(me.library) == 1 and not me.exile
    assert not game.stack


def test_phyrexian_devourer_counts_the_mana_value_of_what_its_cost_exiled(set_pool):
    """"Exile the top card of your library: Put X +1/+1 counters on this
    creature, where X is the exiled card's mana value."

    The cost has **no mana component at all**, and the effect reads the card
    the cost ate (CR 608.2h) — a channel the payment path is the only possible
    source for, since the card is in exile by resolution.
    """
    game, devourer = _w1g2_board(
        set_pool, "Phyrexian Devourer",
        library=[_w1g2_card("Cheap", "Artifact", "{1}", 1.0)] * 4,
    )
    assert game.activate_permanent_ability(0, "Phyrexian Devourer").supported
    game.resolve_top_of_stack()
    assert (devourer.effective_power, devourer.effective_toughness) == (2, 2)
    assert len(game.players[0].library) == 3


def test_phyrexian_devourer_sacrifices_itself_at_seven_power(set_pool):
    """"When this creature's power is 7 or greater, sacrifice it."

    CR 603.8's state trigger, watched by the state-based sweep rather than
    announced from a call site — a power can move from a counter, an Aura, an
    anthem or a layer effect ending, and a list of those goes stale.
    """
    game, devourer = _w1g2_board(
        set_pool, "Phyrexian Devourer",
        library=[_w1g2_card("Fatty", "Creature - Giant", "{6}", 6.0)],
    )
    assert game.activate_permanent_ability(0, "Phyrexian Devourer").supported
    game.resolve_top_of_stack()
    game.check_state_based_actions()
    assert not game.is_on_battlefield(devourer)
    assert [card.name for card in game.players[0].graveyard] == ["Phyrexian Devourer"]


def test_soldevi_digger_bottoms_the_most_recent_card_in_the_graveyard(set_pool):
    """"{2}: Put the top card of your graveyard on the bottom of your library."

    CR 404.1 makes a graveyard an ordered pile whose *top* is what went in
    last — so this is the card most recently put there, not the first one the
    pile ever held.
    """
    game, _digger = _w1g2_board(
        set_pool, "Soldevi Digger",
        library=[_w1g2_card("Deck Card", "Artifact")],
        graveyard=[
            _w1g2_card("Oldest", "Artifact"), _w1g2_card("Newest", "Artifact"),
        ],
    )
    me = game.players[0]
    assert game.activate_permanent_ability(0, "Soldevi Digger").supported
    game.resolve_top_of_stack()
    assert [card.name for card in me.graveyard] == ["Oldest"]
    assert [card.name for card in me.library] == ["Deck Card", "Newest"]


def test_soldevi_digger_on_an_empty_graveyard_moves_nothing(set_pool):
    """CR 608.2: the ability still resolves, and the cost was paid at
    activation either way."""
    game, _digger = _w1g2_board(
        set_pool, "Soldevi Digger", library=[_w1g2_card("Deck Card", "Artifact")]
    )
    assert game.activate_permanent_ability(0, "Soldevi Digger").supported
    game.resolve_top_of_stack()
    assert [card.name for card in game.players[0].library] == ["Deck Card"]

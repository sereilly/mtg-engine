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


# --- W2G4: library and modal ---
"""Ashnod's Cylix and Lodestone Bauble — two artifacts about somebody else's
library.

The Cylix is the look-and-pick template with its **looker printed**: every card
in that family before it looked at its own controller's library, so "your
library" was a literal and the seat was never a field. Here the pile, the pick
and the exile all belong to the targeted player, and the kept card goes back on
*top* rather than into a hand — the difference between a Cylix that mills three
and one that gives its victim a free tutor.

The Bauble is the graveyard-to-library production reaching a pile nobody chose.
"A player's graveyard" targets no player at all — the *cards* are the targets —
so the seat comes off the chosen slots, and the delayed draw a sentence later
has to find that same seat.
"""

from engine import Game, PlayerState
from engine.game_types import CardDefinition, Permanent


def _w2g4_art_card(name: str, type_line: str = "Artifact") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _w2g4_board(set_pool, card_name, *, interactive, p2_library=(), p2_graveyard=()):
    p1 = PlayerState(name="P1", library=[_w2g4_art_card("Mine")] * 5)
    p2 = PlayerState(
        name="P2", library=list(p2_library), graveyard=list(p2_graveyard),
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("ALL")[card_name]), None
    )
    return game, p1, p2


def test_w2g4_cylix_asks_the_targeted_player_not_its_controller(set_pool):
    """CR 602.2b chose the seat as the ability was activated, and the sentence
    says *that* player looks. The prompt is theirs — the controller never sees
    the three cards, which is what the hidden zone (CR 400.2) requires."""
    game, _p1, p2 = _w2g4_board(
        set_pool, "Ashnod's Cylix", interactive={0, 1},
        p2_library=[_w2g4_art_card(f"Theirs {i}") for i in range(4)],
    )

    assert game.activate_permanent_ability(
        0, "Ashnod's Cylix", target_player_index=1
    ).supported

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("look_top_pick", 1)
    ]


def test_w2g4_cylix_keeps_one_on_top_and_exiles_the_other_two(set_pool):
    """"…puts one of them **back on top of their library**, then exiles the
    rest." The kept card is not drawn — it is the next card that player draws,
    a difference nobody can see until the draw step."""
    game, _p1, p2 = _w2g4_board(
        set_pool, "Ashnod's Cylix", interactive={0, 1},
        p2_library=[_w2g4_art_card(f"Theirs {i}") for i in range(4)],
    )
    assert game.activate_permanent_ability(
        0, "Ashnod's Cylix", target_player_index=1
    ).supported

    assert game.confirm_look_top_pick(1, 2)
    game._settle()

    assert [c.name for c in p2.library] == ["Theirs 2", "Theirs 3"]
    assert [c.name for c in p2.exile] == ["Theirs 0", "Theirs 1"]
    assert p2.hand == [], "the kept card goes on top, not into a hand"


def test_w2g4_bauble_offers_only_basic_lands_out_of_the_graveyard(set_pool):
    """"up to four target **basic land** cards". The supertype is read off the
    printed type line, which for a card in a graveyard is the whole of what
    there is (CR 613.1) — and dropping it would let the Bauble return any land,
    a strictly better card than the one printed."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    game, _p1, _p2 = _w2g4_board(
        set_pool, "Lodestone Bauble", interactive={0},
        p2_graveyard=[
            _w2g4_art_card("Mountain", "Basic Land — Mountain"),
            _w2g4_art_card("Black Lotus"),
            _w2g4_art_card("Dwarven Ruins", "Land"),
        ],
    )
    bauble = set_pool("ALL")["Lodestone Bauble"]
    spec = derive_activation_spec(compile_card_oracle(bauble).activated_abilities[0])
    assert spec is not None
    assert spec.get("supertypes") == ["basic"]

    offered = game.activation_target_spec(0, 0, 0)["valid_targets"]
    assert [t["name"] for t in offered] == ["Mountain"]


def test_w2g4_bauble_moves_the_cards_and_the_owner_draws_next_upkeep(set_pool):
    """Two sentences and one seat. The graveyard is not a target, so "that
    player" in the delayed half names whoever the chosen *cards* belonged to —
    and the cards go back in the order they were named (CR 601.2c)."""
    game, _p1, p2 = _w2g4_board(
        set_pool, "Lodestone Bauble", interactive={0},
        p2_library=[_w2g4_art_card("Deck")],
        p2_graveyard=[
            _w2g4_art_card("Mountain", "Basic Land — Mountain"),
            _w2g4_art_card("Black Lotus"),
            _w2g4_art_card("Island", "Basic Land — Island"),
        ],
    )

    assert game.activate_permanent_ability(
        0, "Lodestone Bauble", target_player_index=1,
        target_permanent_index=[2, 0],
    ).supported
    game._settle()

    assert [c.name for c in p2.library] == ["Island", "Mountain", "Deck"]
    assert [c.name for c in p2.graveyard] == ["Black Lotus"]

    assert [t.event for t in game.delayed_triggers] == ["next_turns_upkeep"]
    game.resolve_upkeep(1)
    game._settle()
    assert [c.name for c in p2.hand] == ["Island"]


# --- W2G5: damage, prevention and zones ---
#
# Two artifacts and one decline. Both landed cards refused on a narrowing the
# *lowering* had written down and the handler never had: a several-targets tap
# that demanded creatures where its untap twin demands nothing, and an
# attachment host the sweep could describe but not choose.

from engine import Game, PlayerState, load_cards
from engine.auras import attach_aura
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W2G5A_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g5a_duel() -> Game:
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    return game


def _w2g5a_put(game: Game, seat: int, card, *, ready: bool = False) -> Permanent:
    perm = Permanent(card=card if not isinstance(card, str) else _W2G5A_LEA[card])
    if ready:
        perm.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def test_floodwater_dam_taps_exactly_x_lands_and_nothing_else(set_pool):
    """"{X}{X}{1}, {T}: Tap **X target lands**." The several-targets tap arm
    demanded creatures where its untap twin (Candelabra of Tawnos, shipped)
    demands nothing at all - so a card type, the one thing the pure matcher can
    always answer, was the restriction that refused the line."""
    game = _w2g5a_duel()
    dam = _w2g5a_put(game, 0, set_pool("ALL")["Floodwater Dam"], ready=True)
    lands = [_w2g5a_put(game, 1, "Forest") for _ in range(3)]
    creature = _w2g5a_put(game, 1, "Grizzly Bears")

    assert game.activate_permanent_ability(
        0, "Floodwater Dam", x_value=2,
        target_permanent_ids=[lands[0].permanent_id, lands[1].permanent_id],
    ).supported

    assert [land.tapped for land in lands] == [True, True, False]
    assert not creature.tapped
    assert dam.tapped, "the ability's own {T} was paid"


def test_floodwater_dam_charges_one_generic_per_x_symbol(set_pool):
    """Its cost prints **two** {X}, so X=2 is {5} and not {3}. The activation
    path counts the symbols in the printed cost rather than reading a number off
    the parsed cost, which is why neither this card nor Candelabra carries an X
    in ``ActivatedAbilityCost.mana``."""
    game = _w2g5a_duel()
    game.enforce_mana_costs = True
    _w2g5a_put(game, 0, set_pool("ALL")["Floodwater Dam"], ready=True)
    land = _w2g5a_put(game, 1, "Forest")
    game.players[0].mana_pool["C"] = 4

    refused = game.activate_permanent_ability(
        0, "Floodwater Dam", x_value=2,
        target_permanent_ids=[land.permanent_id],
    )
    assert not refused.supported, "{1} plus two lots of X=2 is five mana, not four"

    game.players[0].mana_pool["C"] = 5
    assert game.activate_permanent_ability(
        0, "Floodwater Dam", x_value=2,
        target_permanent_ids=[land.permanent_id],
    ).supported


def test_scarab_of_the_unseen_returns_each_aura_to_its_own_owner(set_pool):
    """"Return all Auras attached to **target permanent you own** to **their
    owners'** hands." Two things this checks that the compile cannot: the host
    is a permanent the ability *chooses*, and each Aura goes to the seat that
    owns it rather than to the activator."""
    game = _w2g5a_duel()
    _w2g5a_put(game, 0, set_pool("ALL")["Scarab of the Unseen"], ready=True)
    host = _w2g5a_put(game, 0, "Grizzly Bears")
    elsewhere = _w2g5a_put(game, 0, "Hill Giant")
    mine = _w2g5a_put(game, 0, "Holy Strength")
    theirs = _w2g5a_put(game, 1, "Unholy Strength")
    untouched = _w2g5a_put(game, 0, "Firebreathing")
    attach_aura(mine, host)
    attach_aura(theirs, host)
    attach_aura(untouched, elsewhere)

    assert game.activate_permanent_ability(
        0, "Scarab of the Unseen", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(host),
    ).supported

    assert [c.name for c in game.players[0].hand] == ["Holy Strength"]
    assert [c.name for c in game.players[1].hand] == ["Unholy Strength"]
    assert untouched in game.players[0].battlefield, "a different host is untouched"


def test_scarab_of_the_unseen_refuses_a_host_it_does_not_own(set_pool):
    """"target permanent **you own**" is enforced before anything is paid
    (CR 602.2b): the artifact's cost sacrifices it, so an unenforced restriction
    here would be a card thrown away for nothing."""
    game = _w2g5a_duel()
    scarab = _w2g5a_put(game, 0, set_pool("ALL")["Scarab of the Unseen"], ready=True)
    host = _w2g5a_put(game, 1, "Grizzly Bears")
    attach_aura(_w2g5a_put(game, 0, "Holy Strength"), host)

    refused = game.activate_permanent_ability(
        0, "Scarab of the Unseen", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(host),
    )

    assert not refused.supported
    assert scarab in game.players[0].battlefield, "nothing was paid"


# --- W2G5 declines, each naming the part it is waiting on -------------------


def test_gusthas_scepter_was_declined_naming_four_parts_and_landed_in_w3g3(set_pool):
    """W2G5 declined this card naming four parts. W3G3 built it; the record of
    which of the four were real is worth more than the decline was.

    1. **A face-down exile from a hand** was real, and half of it already
       existed: ``engine/linked_exile.py`` has carried a ``face_down`` flag and
       ``web/serialization.py`` has hidden those entries since Knowledge Vault,
       so "no zone in ``PlayerState`` distinguishes" named the wrong layer —
       CR 406.3 is answered by the *record of the exiling*, not by a zone.
    2. **A per-viewer look permission** was real and is the one part the
       decline sized correctly.
    3. **A picked return out of the linked pile** was real: one new
       ``PendingChoice`` kind, ``linked_exile_return``.
    4. **A "when you lose control" trigger** was real, and its fire site was
       *not* where the decline pointed. ``engine/control.py`` records a
       contribution and never moves anything; the two events are the change of
       hands in ``Game._sync_control`` and the leave transition in
       ``remove_all_from_battlefield`` (CR 603.10d looks back in time, which is
       what lets the second one fire at all).
    """
    program = compile_card_oracle(set_pool("ALL")["Gustha's Scepter"])
    assert program.supported
    assert [ability.effect_kind for ability in program.activated_abilities] == [
        "activated_sequence", "activated_zones",
    ]
    assert [
        trigger.condition.kind for trigger in program.triggered_abilities
    ] == ["lose_control_of_source"]


# --- W3G3: iterative library procedures ---
#
# Gustha's Scepter, the group's one landed artifact. Every part of it was a
# *procedure* rather than an effect, and the two that took the work were the
# ones where the pile has to be readable long after the resolution that filled
# it: a face-down exile whose owner may look (CR 406.3 hides it from everyone,
# its owner included, so the look is an effect and not a courtesy) and a
# lose-control trigger with two different fire sites (CR 603.10d).

import pytest

from engine import Game as _W3G3Game, PlayerState as _W3G3PlayerState
from engine.card_loader import manifest_set_path as _w3g3_set_path
from engine.card_loader import load_cards as _w3g3_load_cards
from engine.linked_exile import face_down_exiled_cards, linked_entries
from engine.models import Permanent as _W3G3Permanent
from engine.oracle import compile_card_oracle as _w3g3_compile

_W3G3_LEA = {c.name: c for c in _w3g3_load_cards(_w3g3_set_path("LEA"))}


def _w3g3_duel() -> "_W3G3Game":
    """A duel with both seats interactive, so a prompt queues instead of being
    answered by its default the moment it is armed."""
    game = _W3G3Game(
        players=[_W3G3PlayerState(name="A"), _W3G3PlayerState(name="B")]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = {0, 1}
    game._settle()
    return game


def _w3g3_put(game, seat: int, card, *, ready: bool = True):
    perm = _W3G3Permanent(card=card if not isinstance(card, str) else _W3G3_LEA[card])
    if ready:
        perm.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(seat, perm, None)
    return perm


def _w3g3_scepter(set_pool, hand=("Black Lotus", "Healing Salve")):
    game = _w3g3_duel()
    scepter = _w3g3_put(game, 0, set_pool("ALL")["Gustha's Scepter"])
    game.players[0].hand = [_W3G3_LEA[name] for name in hand]
    return game, scepter


def _w3g3_exile_one(game, scepter, hand_index=0):
    """Activate the first ability and answer its pick."""
    scepter.tapped = False
    game.activate_permanent_ability(0, "Gustha's Scepter", permanent_index=0)
    game._settle()
    answered = game.confirm_exile_from_hand_choice(0, hand_index)
    game._settle()
    return answered


def test_gusthas_scepter_exiles_face_down_and_only_its_owner_may_look(set_pool):
    """"{T}: Exile a card from your hand face down. You may look at it for as
    long as it remains exiled."

    CR 406.3 hides a face-down exiled card from **every** player, its owner
    included - Knowledge Vault's controller cannot read its own pile. So the
    second sentence is an effect with a per-seat answer, and the two halves are
    asserted separately: the opponent still sees a card back, and the seat that
    exiled it does not.
    """
    game, scepter = _w3g3_scepter(set_pool)

    assert _w3g3_exile_one(game, scepter)

    assert [c.name for c in game.players[0].hand] == ["Healing Salve"]
    assert [c.name for c in game.players[0].exile] == ["Black Lotus"]
    entry = linked_entries(scepter)[0]
    assert entry["face_down"] is True and entry["looker_index"] == 0
    assert [c.name for c in face_down_exiled_cards(game, 0, 1)] == ["Black Lotus"]
    assert face_down_exiled_cards(game, 0, 0) == []
    # With no viewer named the pile reads as the rules describe it, which is
    # what Knowledge Vault's own serialization asks for.
    assert [c.name for c in face_down_exiled_cards(game, 0)] == ["Black Lotus"]


def test_gusthas_scepter_exile_is_mandatory_where_ice_cauldrons_is_an_offer(set_pool):
    """The bare sentence has no "may" in it, so the prompt refuses a decline.

    That distinction is the whole of what stops the ability resolving having
    moved nothing: the pick shares its prompt with Ice Cauldron's *offered*
    exile, whose stated default is to decline, and a headless seat taking that
    default here would tap the artifact for no effect every turn.
    """
    game, scepter = _w3g3_scepter(set_pool)
    game.activate_permanent_ability(0, "Gustha's Scepter", permanent_index=0)
    game._settle()

    assert not game.confirm_exile_from_hand_choice(0, None)
    assert game.pending_choice_of("exile_from_hand_choice", 0) is not None
    assert game.confirm_exile_from_hand_choice(0, 1)
    game._settle()
    assert [c.name for c in game.players[0].exile] == ["Healing Salve"]


def test_gusthas_scepter_returns_one_chosen_card_and_leaves_the_rest(set_pool):
    """"{T}: Return a card you own exiled with this artifact to your hand."

    *One* card and the activator says which, where Knowledge Vault's linked
    ability empties the pile - so the record is drained by exactly one entry
    and the cards left behind are still exiled with the artifact.
    """
    game, scepter = _w3g3_scepter(set_pool)
    _w3g3_exile_one(game, scepter)
    _w3g3_exile_one(game, scepter)
    assert [e["card"].name for e in linked_entries(scepter)] == [
        "Black Lotus", "Healing Salve",
    ]

    scepter.tapped = False
    game.activate_permanent_ability(
        0, "Gustha's Scepter", permanent_index=0, ability_index=1
    )
    game._settle()
    pick = game.pending_choice_of("linked_exile_return", 0)
    assert pick is not None
    assert game.live_linked_exile_return_choices(pick) == [0, 1]

    assert game.confirm_linked_exile_return(0, 1)
    game._settle()

    assert [c.name for c in game.players[0].hand] == ["Healing Salve"]
    assert [c.name for c in game.players[0].exile] == ["Black Lotus"]
    assert [e["card"].name for e in linked_entries(scepter)] == ["Black Lotus"]


def test_gusthas_scepter_offers_only_the_cards_the_chooser_owns(set_pool):
    """"a card **you own** exiled with this artifact". The restriction only
    ever bites once somebody else is using the artifact, which is precisely
    when it has to: a thief must not be able to pull the previous controller's
    cards out of exile."""
    game, scepter = _w3g3_scepter(set_pool)
    _w3g3_exile_one(game, scepter)

    scepter.tapped = False
    game.activate_permanent_ability(
        0, "Gustha's Scepter", permanent_index=0, ability_index=1
    )
    game._settle()
    pick = game.pending_choice_of("linked_exile_return", 0)
    # Seat 1 owns nothing under the artifact, so the same record offers it
    # nothing - asserted through the engine's own candidate rule, which is the
    # list the renderer draws and the resolver checks.
    pick.player_index = 1
    assert game.live_linked_exile_return_choices(pick) == []


def test_gusthas_scepter_bins_its_pile_when_the_artifact_leaves(set_pool):
    """"When you lose control of this artifact, put all cards exiled with this
    artifact into their owner's graveyard."

    A permanent leaving the battlefield **is** its controller losing control of
    it, and CR 603.10d makes the trigger look back in time - so it is still
    there to fire although the artifact has gone. Without this the cards are
    stranded in exile for the rest of the game.
    """
    game, scepter = _w3g3_scepter(set_pool)
    _w3g3_exile_one(game, scepter)
    _w3g3_exile_one(game, scepter)

    game.remove_from_battlefield(scepter)
    game.players[0].graveyard.append(scepter.card)
    assert game.stack, "the lose-control trigger was announced"
    game.resolve_top_of_stack()

    assert [c.name for c in game.players[0].graveyard] == [
        "Gustha's Scepter", "Black Lotus", "Healing Salve",
    ]
    assert game.players[0].exile == []


def test_gusthas_scepter_bins_its_pile_when_it_changes_hands(set_pool):
    """The other half of the same event, and the reason there are two fire
    sites: a control change is not a zone change (CR 613 layer 2 leaves the
    permanent on the battlefield), so the leave transition cannot see it.

    The cards go to their **owner's** graveyard - seat 0's - not to the new
    controller's.
    """
    game, scepter = _w3g3_scepter(set_pool, hand=("Black Lotus",))
    _w3g3_exile_one(game, scepter)

    thief = _w3g3_put(game, 1, "Grizzly Bears")
    game.take_control(scepter, 1, source=thief)

    assert game.controller_index_of(scepter) == 1
    assert game.stack, "the change of hands announced the trigger"
    while game.stack:
        game.resolve_top_of_stack()

    assert [c.name for c in game.players[0].graveyard] == ["Black Lotus"]
    assert game.players[1].graveyard == []
    assert game.players[0].exile == []


def test_a_face_down_exile_with_no_permanent_to_link_to_does_not_happen(set_pool):
    """CR 406.3 needs a record to mean anything, and the record lives on the
    exiling permanent. With nothing to link to, the exile does not happen at
    all rather than happening in full view - the same refusal
    ``exile_top_of_library`` already makes one handler over."""
    from engine.grammar import parse_line
    from engine.grammar.lower import lower_ability
    from engine.game_types import OracleExecutionContext

    game = _w3g3_duel()
    game.players[0].hand = [_W3G3_LEA["Black Lotus"]]
    instruction = lower_ability(
        parse_line("Exile a card from your hand face down.")
    )[0]
    context = OracleExecutionContext(
        card=_W3G3_LEA["Black Lotus"], caster=game.players[0],
        target=game.players[1], source_permanent=None,
    )
    game._execute_oracle_instruction(instruction, context)

    assert game.pending_choice_of("exile_from_hand_choice", 0) is None
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"]


def test_a_face_down_rider_on_any_other_exile_refuses(set_pool):
    """The rider is implemented by exactly one branch, so every other reading
    of it refuses rather than dropping it. An exile that silently happened face
    *up* is the quiet kind of wrong: every player would be reading a card the
    card says nobody may see."""
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    with pytest.raises(LoweringError):
        lower_ability(parse_line("Exile target creature face down."))


def _w3g3_helm(set_pool, library, x_value):
    """Helm out, an opponent's library stacked, and its ability on the stack."""
    game = _w3g3_duel()
    helm = _w3g3_put(game, 0, set_pool("ALL")["Helm of Obedience"])
    game.players[1].library = [_W3G3_LEA[name] for name in library]
    result = game.activate_permanent_ability(
        0, "Helm of Obedience", permanent_index=0,
        x_value=x_value, target_player_index=1,
    )
    game._settle()
    return game, helm, result


def test_helm_of_obedience_stops_the_loop_on_the_first_creature_card(set_pool):
    """"Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first."

    A loop, not a count: the library is asked one card at a time and *what came
    off the top* decides whether the next iteration happens. Read as a mill of
    X it would take four cards here and leave the Lotus in the graveyard.
    """
    game, helm, result = _w3g3_helm(
        set_pool, ["Lightning Bolt", "Healing Salve", "Grizzly Bears", "Black Lotus"],
        x_value=10,
    )

    assert result.supported
    assert [c.name for c in game.players[1].library] == ["Black Lotus"]
    # The Bears was milled and then taken out of the graveyard by the sentence
    # behind the loop, so what is left is the two cards in front of it.
    assert [c.name for c in game.players[1].graveyard] == [
        "Lightning Bolt", "Healing Salve",
    ]
    assert helm not in game.players[0].battlefield
    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]


def test_helm_of_obedience_stops_the_loop_on_x_cards(set_pool):
    """The other printed exit, and the reason both are fields: a loop that only
    watched for the creature would empty the library looking for one.

    Nothing is sacrificed and nothing is reanimated - the conditional behind
    the loop reads the loop's own record, which is empty.
    """
    game, helm, result = _w3g3_helm(
        set_pool, ["Lightning Bolt", "Healing Salve", "Black Lotus", "Grizzly Bears"],
        x_value=2,
    )

    assert result.supported
    assert [c.name for c in game.players[1].graveyard] == [
        "Lightning Bolt", "Healing Salve",
    ]
    assert [c.name for c in game.players[1].library] == ["Black Lotus", "Grizzly Bears"]
    assert helm in game.players[0].battlefield, "nothing was sacrificed"
    assert [p.card.name for p in game.players[0].battlefield] == ["Helm of Obedience"]


def test_helm_of_obedience_stops_on_an_empty_library_without_a_loss(set_pool):
    """The third exit, which the card does not print because the rules supply
    it. CR 704.5b fires on an attempted *draw* from an empty library and a mill
    is not a draw, so the loop simply runs out of cards."""
    game, helm, _ = _w3g3_helm(set_pool, ["Lightning Bolt"], x_value=10)

    assert game.players[1].library == []
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt"]
    assert not game.players[1].lost
    assert helm in game.players[0].battlefield


def test_helm_of_obedience_refuses_x_of_zero_with_nothing_paid(set_pool):
    """"X can't be 0." A constraint on the value chosen for X (CR 601.2b), not
    on when the ability may be activated - which is why it is enforced beside
    the {X} payment rather than through the activation-restriction table, whose
    every row is answered from the game state alone.

    The grammar consumes the sentence on that same reader's say-so, so what is
    claimed and what is enforced are one reading of the words.
    """
    game = _w3g3_duel()
    helm = _w3g3_put(game, 0, set_pool("ALL")["Helm of Obedience"])
    game.players[1].library = [_W3G3_LEA["Grizzly Bears"]]

    result = game.activate_permanent_ability(
        0, "Helm of Obedience", permanent_index=0, x_value=0, target_player_index=1,
    )

    assert not result.supported
    assert not helm.tapped, "nothing was paid"
    assert game.players[1].graveyard == []


def test_helm_of_obedience_keeps_the_stolen_creatures_owner(set_pool):
    """CR 108.3: the creature is put onto the battlefield under *your* control
    out of its owner's graveyard, so when it dies it goes back to that owner's
    graveyard and not to the thief's. Recorded on the permanent as it arrives,
    because by then the graveyard it came from is the only thing that knew."""
    game, _, _ = _w3g3_helm(set_pool, ["Grizzly Bears"], x_value=5)
    bears = next(
        p for p in game.players[0].battlefield if p.card.name == "Grizzly Bears"
    )
    assert bears.metadata["owner_player_index"] == 1

    game._permanent_to_graveyard(game.players[0], bears)
    game._settle()

    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]
    assert "Grizzly Bears" not in [c.name for c in game.players[0].graveyard]


def test_a_repeated_mill_refuses_a_count_other_than_one(set_pool):
    """The loop is asked after every single card, so a wording that milled two
    at a time would step past its own stopping card. It refuses loudly rather
    than being read as this loop with a different number in it."""
    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError

    with pytest.raises(GrammarError):
        parse_line(
            "Target opponent mills two cards, then repeats this process until "
            "a creature card or X cards have been put into their graveyard "
            "this way, whichever comes first."
        )


def test_one_of_them_refuses_with_no_loop_in_front_of_it(set_pool):
    """"Them" names a set an earlier step of this same effect recorded. With
    nothing in front of it the words name a record nothing writes, and an
    unwritten record reads as empty - so the sentence would compile and put
    nothing onto the battlefield."""
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    with pytest.raises(LoweringError):
        lower_ability(
            parse_line("Put one of them onto the battlefield under your control.")
        )


#: Twelve distinct cards, so the ten the Portal takes leave two behind and a
#: shuffle that lost or duplicated a card would show in the count.
_W3G3_PORTAL_DECK = (
    "Black Lotus", "Healing Salve", "Grizzly Bears", "Lightning Bolt",
    "Ancestral Recall", "Mox Pearl", "Mox Ruby", "Mox Jet", "Mox Emerald",
    "Mox Sapphire", "Time Walk", "Timetwister",
)


def _w3g3_portal(set_pool, deck=_W3G3_PORTAL_DECK, interactive=True):
    """The Portal out, seat 0's library stacked, and its ability activated at
    seat 1."""
    import random

    random.seed(31)
    game = _w3g3_duel()
    if not interactive:
        game.interactive_seats = set()
    portal = _w3g3_put(game, 0, set_pool("ALL")["Phyrexian Portal"])
    game.players[0].library = [_W3G3_LEA[name] for name in deck]
    result = game.activate_permanent_ability(
        0, "Phyrexian Portal", permanent_index=0, target_player_index=1
    )
    game._settle()
    return game, portal, result


def test_phyrexian_portal_divides_chooses_and_searches_across_two_seats(set_pool):
    """The whole procedure, and the asymmetry that is the card: the **opponent**
    divides knowing what is in the piles, and the controller chooses and
    searches without knowing.

    Each decision is armed by answering the one before it, so the three stay
    inside one resolution (CR 608.2, CR 117.3b) and the game waits on each.
    """
    game, _, result = _w3g3_portal(set_pool)
    assert result.supported

    split = game.pending_choice_of("library_pile_split", 1)
    assert split is not None, "the division is owed by the opponent"
    assert game.waiting_prompt()
    assert len(game.players[0].library) == 2, "the ten cards left the library"
    assert [c.name for c in split.data["_cards"]] == list(_W3G3_PORTAL_DECK[:10])

    assert game.confirm_library_pile_split(1, [0, 1, 2])
    game._settle()
    pick = game.pending_choice_of("pile_exile_choice", 0)
    assert pick is not None, "the choice is owed by the controller"
    assert [len(pile) for pile in pick.data["_piles"]] == [3, 7]

    assert game.confirm_pile_exile_choice(0, 0)
    game._settle()
    assert [c.name for c in game.players[0].exile] == list(_W3G3_PORTAL_DECK[:3])

    search = game.pending_choice_of("pile_search", 0)
    assert search is not None
    assert [c.name for c in search.data["_pile"]] == list(_W3G3_PORTAL_DECK[3:10])

    assert game.confirm_pile_search(0, 1)
    game._settle()

    assert [c.name for c in game.players[0].hand] == ["Ancestral Recall"]
    # Two left behind plus the six the search did not take.
    assert len(game.players[0].library) == 8
    assert game.pending_choices == []
    assert not game.waiting_prompt()


def test_phyrexian_portals_exiled_pile_is_face_down_to_everyone(set_pool):
    """CR 406.3, and it is the reason the second decision is a decision at all:
    the piles were divided face down and the choice was made blind, so a pile
    that arrived in exile face up would tell the table what the choice cost.

    Hidden from its **owner** too - the same reading Knowledge Vault's pile
    gets, and the opposite of Gustha's Scepter, whose next sentence grants its
    controller a look.
    """
    game, portal, _ = _w3g3_portal(set_pool)
    game.confirm_library_pile_split(1, [0, 1])
    game._settle()
    game.confirm_pile_exile_choice(0, 0)
    game._settle()

    hidden = [c.name for c in face_down_exiled_cards(game, 0, 0)]
    assert hidden == list(_W3G3_PORTAL_DECK[:2])
    assert [c.name for c in face_down_exiled_cards(game, 0, 1)] == hidden
    assert all(entry["face_down"] for entry in linked_entries(portal))


def test_phyrexian_portal_does_nothing_with_fewer_than_ten_cards(set_pool):
    """"If your library has ten or more cards in it". Read when the instruction
    is followed (CR 608.2c), and the whole effect is inside the branch - so a
    short library divides nothing rather than dividing what there is."""
    game, _, result = _w3g3_portal(set_pool, deck=_W3G3_PORTAL_DECK[:9])

    assert result.supported
    assert game.pending_choices == []
    assert len(game.players[0].library) == 9
    assert game.players[0].exile == []


def test_phyrexian_portal_allows_failing_to_find(set_pool):
    """CR 701.23b: a player may always fail to find. The rest of the pile is
    still shuffled back in, so the only thing the decline costs is the card."""
    game, _, _ = _w3g3_portal(set_pool)
    game.confirm_library_pile_split(1, [0])
    game._settle()
    game.confirm_pile_exile_choice(0, 0)
    game._settle()

    assert game.confirm_pile_search(0, None)
    game._settle()

    assert game.players[0].hand == []
    assert len(game.players[0].exile) == 1
    # Two left behind plus all nine of the searched pile.
    assert len(game.players[0].library) == 11


def test_phyrexian_portal_accepts_an_empty_pile(set_pool):
    """One pile of ten and one of none is a legal division, and a real one: it
    makes the controller choose between searching everything and searching
    nothing."""
    game, _, _ = _w3g3_portal(set_pool)

    assert game.confirm_library_pile_split(1, [])
    game._settle()
    pick = game.pending_choice_of("pile_exile_choice", 0)
    assert [len(pile) for pile in pick.data["_piles"]] == [0, 10]

    assert game.confirm_pile_exile_choice(0, 0)
    game._settle()
    assert game.players[0].exile == []
    assert len(game.pending_choice_of("pile_search", 0).data["_pile"]) == 10


def test_phyrexian_portal_finishes_itself_for_headless_seats(set_pool):
    """Every one of the three prompts refuses other actions, so a seat that
    never answered would freeze the game. All three take their default at arm,
    and the stated policies are neutral-divider / exile-the-smaller /
    take-the-first."""
    game, _, _ = _w3g3_portal(set_pool, interactive=False)

    assert game.pending_choices == []
    assert len(game.players[0].hand) == 1
    assert len(game.players[0].exile) == 5, "the even split, smaller half exiled"
    assert len(game.players[0].library) == 6
    assert not game.waiting_prompt()

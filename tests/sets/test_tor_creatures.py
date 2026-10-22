"""Torment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and eight branches editing eight disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("TOR")` / `set_cards("TOR")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
#
# Madness (CR 702.35): the two madness creatures, and the creature half of the
# drive list — every Torment creature whose ability discards, each driven by
# discarding a madness card through it. Each is a different road into the
# discard seam (a cost, a cost "at random"), and a road that skipped the seam
# would be a madness card that never offered its cast.

import pytest as _w1g1_pytest

from engine import Game as _w1g1_Game, PlayerState as _w1g1_PlayerState
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import _nosick as _w1g1_nosick, resolve_stack as _w1g1_resolve


def _w1g1_seat(set_pool, battlefield, hand, *, library=("Forest",) * 4):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    pool = {**lea, **tor}
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P0",
            battlefield=[_w1g1_nosick(_w1g1_Permanent(card=pool[n])) for n in battlefield],
            hand=[pool[n] for n in hand],
            library=[pool[n] for n in library],
        ),
        _w1g1_PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = True
    return game


def test_w1g1_arrogant_wurm_enters_for_its_madness_cost(set_pool):
    """Discarded to Aquamoeba with three Forests out — its mana cost {3}{G}{G}
    is five — the Wurm is cast for {2}{G} by a seat nobody asks and enters as a
    4/4 trampler."""
    game = _w1g1_seat(
        set_pool, ["Aquamoeba", "Forest", "Forest", "Forest"], ["Arrogant Wurm"],
    )
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    wurm = next(p for p in game.players[0].battlefield if p.card.name == "Arrogant Wurm")
    assert (wurm.effective_power, wurm.effective_toughness) == (4, 4)
    assert game._has_keyword(wurm, "trample")
    assert all(
        land.tapped for land in game.players[0].battlefield if land.card.name == "Forest"
    )
    assert not game.players[0].exile and not game.players[0].graveyard


def test_w1g1_basking_rootwalla_enters_free_and_pumps_only_once_a_turn(set_pool):
    """Madness {0}: discarded with no land at all, it is cast for nothing.
    Then "{1}{G}: … +2/+2 until end of turn. Activate only once each turn." —
    the second activation in the turn is refused (CR 602.5b)."""
    game = _w1g1_seat(set_pool, ["Aquamoeba"], ["Basking Rootwalla"])
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    walla = next(
        p for p in game.players[0].battlefield if p.card.name == "Basking Rootwalla"
    )
    assert (walla.effective_power, walla.effective_toughness) == (1, 1)
    walla.metadata["summoning_sickness_turn"] = -99
    game.enforce_mana_costs = False
    assert game.activate_permanent_ability(0, "Basking Rootwalla").supported
    assert (walla.effective_power, walla.effective_toughness) == (3, 3)
    again = game.activate_permanent_ability(0, "Basking Rootwalla")
    assert not again.supported and "only once each turn" in again.details
    assert (walla.effective_power, walla.effective_toughness) == (3, 3)


#: The drive list's creatures: ``outlet -> (lands to tap for its own cost,
#: target seat or None)``. Each discards Obsessive Search (madness {U}), whose
#: cast is paid by the one Island left untapped.
_W1G1_CREATURE_OUTLETS = {
    "Aquamoeba": ((), None),
    "Skywing Aven": ((), None),
    "Aven Trooper": (("Plains", "Plains", "Plains"), None),
    "Hell-Bent Raider": ((), None),
    "Pardic Lancer": ((), None),
    "Putrid Imp": ((), None),
    "Grotesque Hybrid": ((), None),
}


@_w1g1_pytest.mark.parametrize("outlet", sorted(_W1G1_CREATURE_OUTLETS))
def test_w1g1_every_creature_discard_outlet_offers_the_madness_cast(set_pool, outlet):
    lands, _target = _W1G1_CREATURE_OUTLETS[outlet]
    game = _w1g1_seat(
        set_pool, [outlet, *lands, "Island"], ["Obsessive Search"],
    )
    for slot, land in enumerate(lands, start=1):
        assert game.tap_land_for_mana(0, land, permanent_index=slot)
    result = game.activate_permanent_ability(0, outlet, cost_hand_index=0)
    assert result.supported, (outlet, result.details)
    _w1g1_resolve(game)
    assert any(
        "discarded Obsessive Search into exile (madness)" in line for line in game.log
    ), outlet
    assert any(
        "cast Obsessive Search for its madness cost" in line for line in game.log
    ), outlet
    assert [c.name for c in game.players[0].graveyard] == ["Obsessive Search"], outlet
    # The card the Search drew (Skywing Aven's own ability returns it to the
    # hand beside it).
    assert "Forest" in [c.name for c in game.players[0].hand], outlet


def test_w1g1_pitchstone_wall_finds_no_madness_card_in_the_graveyard(set_pool):
    """The meeting point with W1G5's Pitchstone Wall ("Whenever you discard a
    card, you may sacrifice this creature. If you do, return the discarded card
    from your graveyard to your hand.").

    A madness card is discarded **into exile**, so it is not in the graveyard
    the Wall's ability looks in: the madness trigger goes on the stack inside
    the discard and the Wall's when the discard is announced, so the Wall's
    resolves first and finds nothing (CR 400.7). Whatever the Wall's
    controller then does, the card is cast or binned by madness and never
    returned to the hand. (Had the madness trigger resolved first and been
    declined, CR 400.7k would let the Wall find it — which is why the order is
    asserted, not assumed.)

    Skipped while the Wall is unsupported: it lands with W1G5, and the
    integrator merges that branch first.
    """
    from engine.oracle import compile_card_oracle

    tor, lea = set_pool("TOR"), set_pool("LEA")
    if not compile_card_oracle(tor["Pitchstone Wall"]).supported:
        _w1g1_pytest.skip("Pitchstone Wall lands with W1G5")
    game = _w1g1_seat(
        set_pool, ["Aquamoeba", "Pitchstone Wall", "Mountain"], ["Fiery Temper"],
    )
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    assert "Fiery Temper" not in [c.name for c in game.players[0].hand]
    log = game.log
    exiled = next(i for i, line in enumerate(log) if "Fiery Temper into exile" in line)
    offered = [
        i for i, line in enumerate(log)
        if "for its madness cost" in line and "Fiery Temper" in line
    ]
    assert offered and offered[0] > exiled


# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, *, hand0=(), hand1=(), gy0=(), bf0=(), bf1=(),
                interactive=()):
    """A two-seat game with costs off, built from card names (TOR over LEA)."""
    pool = {**set_pool("LEA"), **set_pool("TOR")}
    seats = [
        _w1g2_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            graveyard=[pool[n] for n in gy], library=[pool["Forest"]] * 10,
        )
        for seat, (hand, gy) in enumerate(((hand0, gy0), (hand1, ())))
    ]
    game = _w1g2_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g2_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g2_on_board(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


def _w1g2_body(perm):
    return perm.effective_power, perm.effective_toughness


def _w1g2_set_graveyard(set_pool, game, seat, size):
    """Make *seat*'s graveyard *size* Forests and let the statics re-read it."""
    game.players[seat].graveyard[:] = [set_pool("LEA")["Forest"]] * size
    game._recompute_continuous_effects()


# --- Mystic Familiar: a threshold static that grants protection --------------

def test_mystic_familiar_has_protection_from_black_only_at_threshold(set_pool):
    """"Threshold — As long as there are seven or more cards in your
    graveyard, this creature gets +1/+1 and has protection from black." Both
    halves ride one condition, re-read on every ask (CR 611.3a): the black
    removal spell is offered the Familiar at six cards and not at seven."""
    game = _w1g2_table(
        set_pool, hand1=["Terror"], gy0=["Forest"] * 6, bf0=["Mystic Familiar"],
    )
    familiar = _w1g2_on_board(game, 0, "Mystic Familiar")

    def terror_offers():
        spec = game.cast_target_spec(1, game.players[1].hand[0])
        return [target["name"] for target in spec["valid_targets"]]

    assert _w1g2_body(familiar) == (1, 2)
    assert game._protection_qualities(familiar) == set()
    assert terror_offers() == ["Mystic Familiar"]

    _w1g2_set_graveyard(set_pool, game, 0, 7)
    assert _w1g2_body(familiar) == (2, 3)
    assert game._protection_qualities(familiar) == {("color", "B")}
    assert terror_offers() == []

    _w1g2_set_graveyard(set_pool, game, 0, 6)
    assert _w1g2_body(familiar) == (1, 2)
    assert game._protection_qualities(familiar) == set()


def test_mystic_familiar_s_protection_prevents_black_damage_at_threshold(set_pool):
    """CR 702.16e: damage from a black source is prevented — the protection is
    a real one, not a targeting flag."""
    from tests.helpers import _damage_dealt

    game = _w1g2_table(
        set_pool, gy0=["Forest"] * 7, bf0=["Mystic Familiar"],
        bf1=["Black Knight", "Grizzly Bears"],
    )
    familiar = _w1g2_on_board(game, 0, "Mystic Familiar")
    knight = _w1g2_on_board(game, 1, "Black Knight")
    bears = _w1g2_on_board(game, 1, "Grizzly Bears")
    assert _damage_dealt(game, familiar, 2, source=knight) == 0
    assert _damage_dealt(game, familiar, 2, source=bears) == 2


# --- Nantuko Blightcutter: a counted bonus under a threshold -----------------

def test_nantuko_blightcutter_counts_opponents_black_permanents_at_threshold(set_pool):
    """"…gets +1/+1 for each black permanent your opponents control as long as
    there are seven or more cards in your graveyard." Your own black
    permanents and an opponent's nonblack ones do not count; below threshold
    nothing does."""
    game = _w1g2_table(
        set_pool, gy0=["Forest"] * 6,
        bf0=["Nantuko Blightcutter", "Scathe Zombies"],
        bf1=["Scathe Zombies", "Black Knight", "Swamp", "Grizzly Bears"],
    )
    blightcutter = _w1g2_on_board(game, 0, "Nantuko Blightcutter")
    assert _w1g2_body(blightcutter) == (2, 2)

    _w1g2_set_graveyard(set_pool, game, 0, 7)
    assert _w1g2_body(blightcutter) == (4, 4)

    game.remove_from_battlefield(_w1g2_on_board(game, 1, "Black Knight"))
    game._recompute_continuous_effects()
    assert _w1g2_body(blightcutter) == (3, 3), "the count is taken on every refresh"

    _w1g2_set_graveyard(set_pool, game, 0, 6)
    assert _w1g2_body(blightcutter) == (2, 2)


def test_a_counted_conditional_bonus_refuses_an_otherwise_arm_and_a_second_delta():
    """The counted channel has no complement and one instruction cannot carry
    two deltas sized two ways — so either spelling refuses rather than
    dropping half the sentence."""
    from engine.oracle import compile_card_oracle
    from tests.helpers import _mk_card

    def supported(text):
        return compile_card_oracle(
            _mk_card("Counted Thing", "{2}{G}", "Creature — Insect", text, power=2, toughness=2)
        ).supported

    assert supported(
        "This creature gets +1/+1 for each black permanent your opponents "
        "control as long as there are seven or more cards in your graveyard."
    )
    assert not supported(
        "As long as there are seven or more cards in your graveyard, this "
        "creature gets +1/+1 for each black permanent your opponents control "
        "and has flying."
    )


# --- The drive list: threshold cards supported on arrival, given a game ------

import pytest as _w1g2_pytest  # noqa: E402

_W1G2_POSSESSED = (
    # (card, printed colour, a creature of the colour its ability names)
    ("Possessed Aven", "U", "Prodigal Sorcerer"),
    ("Possessed Centaur", "G", "Grizzly Bears"),
    ("Possessed Barbarian", "R", "Hill Giant"),
    ("Possessed Nomad", "W", "Savannah Lions"),
)


@_w1g2_pytest.mark.parametrize(
    "name, printed_color, victim", _W1G2_POSSESSED, ids=[r[0] for r in _W1G2_POSSESSED]
)
def test_the_possessed_are_black_bigger_and_armed_only_at_threshold(
    set_pool, name, printed_color, victim,
):
    """"…this creature gets +1/+1, is black, and has "{2}{B}, {T}: Destroy
    target <colour> creature."" — three layers (7c, 5, 6) on one condition.
    Below threshold the granted ability is not there to activate; at
    threshold its picker offers only the colour it names."""
    def board(graveyard_size):
        game = _w1g2_table(
            set_pool, gy0=["Forest"] * graveyard_size, bf0=[name],
            bf1=[victim, "Scathe Zombies"],
        )
        return game, _w1g2_on_board(game, 0, name)

    game, possessed = board(6)
    assert _w1g2_body(possessed) == (3, 3)
    assert game._effective_colors(possessed) == {printed_color}
    target = _w1g2_on_board(game, 1, victim)
    assert not game.activate_permanent_ability(
        0, name, target_permanent_ids=[target.permanent_id],
    ).supported
    assert _w1g2_on_board(game, 1, victim) is not None

    game, possessed = board(7)
    assert _w1g2_body(possessed) == (4, 4)
    assert game._effective_colors(possessed) == {"B"}
    slot = game.players[0].battlefield.index(possessed)
    assert [t["name"] for t in game.activation_target_spec(0, slot)["valid_targets"]] == [
        victim
    ]
    zombies = _w1g2_on_board(game, 1, "Scathe Zombies")
    assert not game.activate_permanent_ability(
        0, name, target_permanent_ids=[zombies.permanent_id],
    ).supported, "a black creature is not the colour the ability names"
    target = _w1g2_on_board(game, 1, victim)
    assert game.activate_permanent_ability(
        0, name, target_permanent_ids=[target.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_on_board(game, 1, victim) is None and possessed.tapped


@_w1g2_pytest.mark.parametrize("name, below, at", [
    ("Seton's Scout", (2, 1), (4, 3)),
    ("Nantuko Calmer", (2, 3), (3, 4)),
])
def test_a_threshold_size_bonus_follows_the_graveyard(set_pool, name, below, at):
    game = _w1g2_table(set_pool, gy0=["Forest"] * 6, bf0=[name])
    creature = _w1g2_on_board(game, 0, name)
    assert _w1g2_body(creature) == below
    _w1g2_set_graveyard(set_pool, game, 0, 7)
    assert _w1g2_body(creature) == at


def _w1g2_cast_at(set_pool, name, graveyard_size, *, bf1=("Grizzly Bears",)):
    game = _w1g2_table(
        set_pool, hand0=[name], gy0=["Forest"] * graveyard_size,
        bf0=["Savannah Lions"], bf1=bf1,
    )
    assert game.cast_from_hand(0, name).supported
    _w1g2_resolve_stack(game)
    return game


def test_a_granted_entry_trigger_is_there_only_if_threshold_holds_as_it_enters(set_pool):
    """"…this creature has "When this creature enters, …"" — the static
    applies as the creature enters (CR 614.12's moment), so with seven cards
    already in the graveyard the trigger fires, and with six it does not
    exist to fire. Four cards, four effects."""
    # Centaur Chieftain: creatures you control get +1/+1 and gain trample.
    quiet = _w1g2_cast_at(set_pool, "Centaur Chieftain", 6)
    assert _w1g2_body(_w1g2_on_board(quiet, 0, "Savannah Lions")) == (2, 1)
    loud = _w1g2_cast_at(set_pool, "Centaur Chieftain", 7)
    lions = _w1g2_on_board(loud, 0, "Savannah Lions")
    assert _w1g2_body(lions) == (3, 2) and loud._has_keyword(lions, "trample")
    assert _w1g2_body(_w1g2_on_board(loud, 1, "Grizzly Bears")) == (2, 2)

    # Pardic Arsonist: 3 damage to any target.
    assert [p.life for p in _w1g2_cast_at(set_pool, "Pardic Arsonist", 6).players] == [20, 20]
    assert [p.life for p in _w1g2_cast_at(set_pool, "Pardic Arsonist", 7).players] == [20, 17]

    # Teroh's Vanguard: creatures you control gain protection from black.
    quiet = _w1g2_cast_at(set_pool, "Teroh's Vanguard", 6)
    assert quiet._protection_qualities(_w1g2_on_board(quiet, 0, "Savannah Lions")) == set()
    loud = _w1g2_cast_at(set_pool, "Teroh's Vanguard", 7)
    assert loud._protection_qualities(_w1g2_on_board(loud, 0, "Savannah Lions")) == {
        ("color", "B")
    }

    # Gloomdrifter: nonblack creatures get -2/-2 — its own controller's too.
    quiet = _w1g2_cast_at(
        set_pool, "Gloomdrifter", 6, bf1=("Grizzly Bears", "Scathe Zombies"),
    )
    assert _w1g2_on_board(quiet, 0, "Savannah Lions") is not None
    loud = _w1g2_cast_at(
        set_pool, "Gloomdrifter", 7, bf1=("Grizzly Bears", "Scathe Zombies"),
    )
    assert _w1g2_on_board(loud, 0, "Savannah Lions") is None
    assert _w1g2_on_board(loud, 1, "Grizzly Bears") is None
    assert _w1g2_on_board(loud, 1, "Scathe Zombies") is not None
    assert _w1g2_body(_w1g2_on_board(loud, 0, "Gloomdrifter")) == (2, 2)


def test_boneshard_slasher_sacrifices_itself_when_targeted_at_threshold(set_pool):
    """"…gets +2/+2 and has "When this creature becomes the target of a spell
    or ability, sacrifice it."" — and the spell aimed at it then has no legal
    target (CR 608.2b)."""
    for size, survives in ((6, True), (7, False)):
        game = _w1g2_table(
            set_pool, hand1=["Lightning Bolt"], gy0=["Forest"] * size,
            bf0=["Boneshard Slasher"],
        )
        slasher = _w1g2_on_board(game, 0, "Boneshard Slasher")
        assert _w1g2_body(slasher) == ((1, 1) if survives else (3, 3))
        assert game.queue_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[slasher.permanent_id],
        ).supported
        _w1g2_resolve_stack(game)
        game.check_state_based_actions()
        # A 1/1 dies to the Bolt; the 3/3 is sacrificed before the Bolt lands.
        assert _w1g2_on_board(game, 0, "Boneshard Slasher") is None
        assert any("was sacrificed" in line for line in game.log) is not survives
        assert any("every target is illegal" in line for line in game.log) is not survives


def test_reborn_hero_may_come_back_only_if_it_died_at_threshold(set_pool):
    """CR 603.10a: a dies trigger looks back in time, so whether the Hero had
    the granted ability is asked of the board just before it died — six cards
    (then seven with the Hero itself) is no trigger; seven is."""
    for size, returns in ((6, False), (7, True)):
        game = _w1g2_table(
            set_pool, hand1=["Terror"], gy0=["Forest"] * size,
            bf0=["Reborn Hero", "Plains", "Plains"],
        )
        hero = _w1g2_on_board(game, 0, "Reborn Hero")
        assert game.cast_from_hand(
            1, "Terror", target_permanent_ids=[hero.permanent_id],
        ).supported
        _w1g2_resolve_stack(game)
        game.auto_resolve_pending_choices()
        _w1g2_resolve_stack(game)
        assert (_w1g2_on_board(game, 0, "Reborn Hero") is not None) is returns

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
#
# Linked exile and leaving the battlefield (CR 607.2a): "return the exiled
# cards" in three destinations (Gravegouger, Hypnox, Petradon), Mesmeric
# Fiend's chosen card, and Chainer's reanimation. Each card is driven through
# the real cast / activation / response path, and each "old-style O-Ring"
# card is also killed with its entry trigger on the stack: the leave trigger
# resolves first and returns nothing, then the entry trigger exiles for good
# (Mesmeric Fiend's ruling, 2018-03-16).

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.linked_exile import linked_entries as _w1g3_linked_entries
from engine.models import Permanent as _W1G3Permanent
from engine.object_colors import object_colors as _w1g3_object_colors
from engine.layer_bridge import computed_types as _w1g3_computed_types
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_card(set_pool, name):
    for code in ("TOR", "LEA", "ODY"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g3_game(set_pool, *, hand=(), opp_hand=(), opp_graveyard=(), graveyard=()):
    card = lambda name: _w1g3_card(set_pool, name)  # noqa: E731
    p0 = _W1G3PlayerState(
        name="P0", hand=[card(n) for n in hand],
        graveyard=[card(n) for n in graveyard],
        library=[card("Swamp")] * 5,
    )
    p1 = _W1G3PlayerState(
        name="P1", hand=[card(n) for n in opp_hand],
        graveyard=[card(n) for n in opp_graveyard],
        library=[card("Forest")] * 5,
    )
    game = _W1G3Game(players=[p0, p1])
    game.enforce_mana_costs = False
    return game


def _w1g3_put(game, set_pool, seat, name):
    permanent = _W1G3Permanent(card=_w1g3_card(set_pool, name))
    permanent.metadata["summoning_sickness_turn"] = -5
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _w1g3_resolve_stack(game)
    return permanent


def _w1g3_named(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g3_drain(game):
    for _ in range(4):
        _w1g3_resolve_stack(game)
        game._settle()
        if game.pending_choices:
            game.auto_resolve_pending_choices()
        if not game.stack and not game.pending_choices:
            return


def _w1g3_swords_in_response(game, victim):
    """Exile *victim* with Swords to Plowshares while its entry trigger is
    still on the stack — the response CR 603.3 made possible."""
    result = game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[victim.permanent_id],
    )
    assert result.supported, game.log[-5:]
    _w1g3_drain(game)


# --- Gravegouger: "return the exiled cards to their owner's graveyard" -----


def test_w1g3_gravegouger_exiles_two_cards_and_returns_them_when_it_leaves(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Gravegouger", "Swords to Plowshares"],
        opp_graveyard=["Lightning Bolt", "Grizzly Bears", "Giant Growth"],
    )
    p1 = game.players[1]
    game.cast_from_hand(0, "Gravegouger")
    _w1g3_drain(game)

    assert len(p1.exile) == 2, game.log[-5:]
    assert len(p1.graveyard) == 1
    gouger = _w1g3_named(game, 0, "Gravegouger")
    # CR 607.2a: the two cards are recorded as exiled *with* the Gravegouger.
    assert sorted(e["card"].name for e in _w1g3_linked_entries(gouger)) == sorted(
        c.name for c in p1.exile
    )

    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[gouger.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.graveyard) == [
        "Giant Growth", "Grizzly Bears", "Lightning Bolt",
    ]


def test_w1g3_gravegouger_killed_in_response_exiles_for_good(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Gravegouger", "Swords to Plowshares"],
        opp_graveyard=["Lightning Bolt", "Grizzly Bears"],
    )
    p1 = game.players[1]
    game.queue_from_hand(0, "Gravegouger")
    game.resolve_top_of_stack()
    gouger = _w1g3_named(game, 0, "Gravegouger")
    assert game.stack, "the entry trigger is a stack object (CR 603.3)"

    _w1g3_swords_in_response(game, gouger)

    # The leave trigger resolved first and found nothing; the entry trigger
    # then exiled both cards, and nothing is left to bring them back.
    assert sorted(c.name for c in p1.exile) == ["Grizzly Bears", "Lightning Bolt"]
    assert p1.graveyard == []


# --- Petradon: "…to the battlefield under their owners' control" -----------


def test_w1g3_petradon_exiles_two_lands_and_returns_them_to_their_owners(set_pool):
    game = _w1g3_game(set_pool, hand=["Petradon", "Swords to Plowshares"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    mountain = _w1g3_put(game, set_pool, 1, "Mountain")
    game.cast_from_hand(
        0, "Petradon", target_player_index=1,
        target_permanent_ids=[forest.permanent_id, mountain.permanent_id],
    )
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Mountain"]

    petradon = _w1g3_named(game, 0, "Petradon")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[petradon.permanent_id],
    )
    _w1g3_drain(game)

    # Under their owner's control (CR 110.2a), and as new objects (CR 400.7).
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Forest", "Mountain"]
    assert game.players[1].exile == []
    assert all(p.permanent_id not in (forest.permanent_id, mountain.permanent_id)
               for p in game.controlled_by(1))


def test_w1g3_petradon_killed_in_response_keeps_the_lands_exiled(set_pool):
    game = _w1g3_game(set_pool, hand=["Petradon", "Swords to Plowshares"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    mountain = _w1g3_put(game, set_pool, 1, "Mountain")
    game.queue_from_hand(
        0, "Petradon", target_player_index=1,
        target_permanent_ids=[forest.permanent_id, mountain.permanent_id],
    )
    game.resolve_top_of_stack()
    petradon = _w1g3_named(game, 0, "Petradon")

    _w1g3_swords_in_response(game, petradon)

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Mountain"]


def test_w1g3_petradon_owes_two_targets_or_none(set_pool):
    """"Exile **two** target lands": a printed count with no "up to" is owed
    whole (CR 601.2c). A one-land board offers no legal announcement, so
    CR 603.3d takes the trigger off the stack — it does not exile the one land
    it could reach. A cast naming one land is set aside the same way."""
    game = _w1g3_game(set_pool, hand=["Petradon"])
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    game.cast_from_hand(
        0, "Petradon", target_player_index=1, target_permanent_ids=[forest.permanent_id],
    )
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(1)] == ["Forest"]
    assert game.players[1].exile == []
    assert any("needs 2 targets" in line for line in game.log), game.log[-4:]


def test_w1g3_petradon_asked_for_its_targets_takes_exactly_two(set_pool):
    """Put onto the battlefield (nothing announced), a human controller is
    asked: one land is refused, two are the announcement."""
    game = _w1g3_game(set_pool)
    game.interactive_seats = {0}
    forest = _w1g3_put(game, set_pool, 1, "Forest")
    island = _w1g3_put(game, set_pool, 1, "Island")
    permanent = _W1G3Permanent(card=_w1g3_card(set_pool, "Petradon"))
    game._put_permanent_onto_battlefield(0, permanent, None)

    (asked,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert asked.data["max_targets"] == 2 and asked.data.get("exact_targets")
    # …and the web layer tells the client so (its Confirm is wave 2's).
    from web.prompts import PromptContext, render_prompts

    shown = render_prompts(PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    ))["trigger_target"]
    assert shown["max_targets"] == 2 and shown["exact_targets"] is True
    assert "up_to" not in shown
    assert not game.confirm_trigger_target(0, permanent_id=forest.permanent_id)
    assert not game.confirm_trigger_target(0, permanent_ids=[forest.permanent_id])
    assert game.confirm_trigger_target(
        0, permanent_ids=[forest.permanent_id, island.permanent_id]
    )
    game.interactive_seats = set()
    _w1g3_drain(game)

    assert sorted(c.name for c in game.players[1].exile) == ["Forest", "Island"]


# --- Hypnox: "if you cast it from your hand" and the whole hand --------------


def test_w1g3_hypnox_cast_from_hand_exiles_the_hand_and_gives_it_back(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Hypnox", "Swords to Plowshares"],
        opp_hand=["Lightning Bolt", "Island", "Grizzly Bears"],
    )
    p1 = game.players[1]
    game.cast_from_hand(0, "Hypnox", target_player_index=1)
    _w1g3_drain(game)

    assert p1.hand == []
    assert sorted(c.name for c in p1.exile) == ["Grizzly Bears", "Island", "Lightning Bolt"]

    hypnox = _w1g3_named(game, 0, "Hypnox")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[hypnox.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.hand) == ["Grizzly Bears", "Island", "Lightning Bolt"]


def test_w1g3_hypnox_put_onto_the_battlefield_does_not_trigger(set_pool):
    """CR 603.4: a permanent that was never cast was not cast from a hand."""
    game = _w1g3_game(set_pool, opp_hand=["Lightning Bolt", "Island"])
    _w1g3_put(game, set_pool, 0, "Hypnox")

    assert sorted(c.name for c in game.players[1].hand) == ["Island", "Lightning Bolt"]
    assert any("didn't trigger" in line for line in game.log), game.log[-3:]


def test_w1g3_hypnox_killed_in_response_exiles_the_hand_for_good(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Hypnox", "Swords to Plowshares"],
        opp_hand=["Lightning Bolt", "Island"],
    )
    game.queue_from_hand(0, "Hypnox", target_player_index=1)
    game.resolve_top_of_stack()
    hypnox = _w1g3_named(game, 0, "Hypnox")

    _w1g3_swords_in_response(game, hypnox)

    # The condition is still true as the trigger resolves (it *was* cast from
    # a hand), so the hand is exiled — after the leave trigger found nothing.
    assert game.players[1].hand == []
    assert sorted(c.name for c in game.players[1].exile) == ["Island", "Lightning Bolt"]


# --- Mesmeric Fiend: the chosen card, linked --------------------------------


def test_w1g3_mesmeric_fiend_exiles_a_nonland_card_and_returns_it(set_pool):
    game = _w1g3_game(
        set_pool, hand=["Mesmeric Fiend", "Swords to Plowshares"],
        opp_hand=["Island", "Lightning Bolt"],
    )
    game.interactive_seats = {0}
    p1 = game.players[1]
    game.cast_from_hand(0, "Mesmeric Fiend", target_player_index=1)
    game._settle()
    (choice,) = [c for c in game.pending_choices if c.kind == "revealed_hand_pick"]
    # Only the nonland card is offered.
    assert [p1.hand[i].name for i in choice.data["legal_indices"]] == ["Lightning Bolt"]
    assert game.confirm_revealed_hand_pick(0, choice.data["legal_indices"][0])

    assert [c.name for c in p1.exile] == ["Lightning Bolt"]
    fiend = _w1g3_named(game, 0, "Mesmeric Fiend")
    assert [e["card"].name for e in _w1g3_linked_entries(fiend)] == ["Lightning Bolt"]

    game.interactive_seats = set()
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[fiend.permanent_id],
    )
    _w1g3_drain(game)

    assert p1.exile == []
    assert sorted(c.name for c in p1.hand) == ["Island", "Lightning Bolt"]


def test_w1g3_mesmeric_fiend_killed_in_response_exiles_indefinitely(set_pool):
    """The card's ruling (2018-03-16): "its second ability will trigger and do
    nothing. Then its first ability will resolve and exile a nonland card from
    the target opponent's hand indefinitely.\""""
    game = _w1g3_game(
        set_pool, hand=["Mesmeric Fiend", "Swords to Plowshares"],
        opp_hand=["Island", "Lightning Bolt"],
    )
    game.queue_from_hand(0, "Mesmeric Fiend", target_player_index=1)
    game.resolve_top_of_stack()
    fiend = _w1g3_named(game, 0, "Mesmeric Fiend")

    _w1g3_swords_in_response(game, fiend)

    assert [c.name for c in game.players[1].exile] == ["Lightning Bolt"]
    assert [c.name for c in game.players[1].hand] == ["Island"]


# --- Chainer, Dementia Master -------------------------------------------------


def _w1g3_chainer(set_pool, opp_graveyard=("Grizzly Bears",)):
    game = _w1g3_game(set_pool, opp_graveyard=list(opp_graveyard))
    chainer = _w1g3_put(game, set_pool, 0, "Chainer, Dementia Master")
    return game, chainer


def test_w1g3_chainer_reanimates_a_black_nightmare_under_your_control(set_pool):
    game, _chainer = _w1g3_chainer(set_pool)
    life = game.players[0].life
    result = game.activate_permanent_ability(
        0, "Chainer, Dementia Master", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, game.log[-3:]
    _w1g3_drain(game)

    assert game.players[0].life == life - 3, "Pay 3 life"
    bears = _w1g3_named(game, 0, "Grizzly Bears")
    # The ruling (2022-12-08): "black only, not black in addition to its other
    # colors … a Nightmare in addition to its other creature types".
    assert set(_w1g3_object_colors(game, bears)) == {"B"}
    _card_types, subtypes = _w1g3_computed_types(bears)
    assert {"bear", "nightmare"} <= set(subtypes)
    # "All Nightmares get +1/+1." — the Nightmares include the reanimated one.
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    # CR 108.3: still its owner's card.
    assert game.owner_index_of(bears) == 1


def test_w1g3_chainer_leaving_exiles_every_nightmare(set_pool):
    game, chainer = _w1g3_chainer(set_pool)
    game.activate_permanent_ability(
        0, "Chainer, Dementia Master", target_player_index=1, target_permanent_index=0,
    )
    _w1g3_drain(game)
    _w1g3_put(game, set_pool, 1, "Gravegouger")  # a printed Nightmare
    _w1g3_put(game, set_pool, 1, "Grizzly Bears")  # not one

    game.remove_from_battlefield(chainer)
    game._permanent_to_graveyard(game.players[0], chainer)
    _w1g3_drain(game)

    assert [p.card.name for p in game.controlled_by(0)] == []
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    # Each to its owner's exile (CR 400.3).
    assert sorted(c.name for c in game.players[1].exile) == ["Gravegouger", "Grizzly Bears"]


# --- The drive list: supported on arrival, driven -----------------------------


def test_w1g3_slithery_stalker_gives_back_what_it_exiled(set_pool):
    """The ingest's red census named this card, and the card was right: its
    swampwalk reminder text says "as long as", which the census had read as a
    duration (now stripped, CR 207.2a). Driven both ways round."""
    game = _w1g3_game(set_pool, hand=["Slithery Stalker", "Swords to Plowshares"])
    bears = _w1g3_put(game, set_pool, 1, "Grizzly Bears")
    game.cast_from_hand(
        0, "Slithery Stalker", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g3_drain(game)
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]

    stalker = _w1g3_named(game, 0, "Slithery Stalker")
    game.queue_from_hand(
        0, "Swords to Plowshares", target_player_index=0,
        target_permanent_ids=[stalker.permanent_id],
    )
    _w1g3_drain(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert game.players[1].exile == []


def test_w1g3_laquatus_champion_killed_in_response_gives_the_life_first(set_pool):
    """The ruling (2018-03-16): "the player who gains 6 life is the player who
    was the target of the first ability (or, if that ability is still on the
    stack, the player who is its target)." So the gain resolves first and the
    loss after it."""
    game = _w1g3_game(set_pool, hand=["Laquatus's Champion", "Swords to Plowshares"])
    game.queue_from_hand(0, "Laquatus's Champion", target_player_index=1)
    game.resolve_top_of_stack()
    champion = _w1g3_named(game, 0, "Laquatus's Champion")

    _w1g3_swords_in_response(game, champion)

    gained = next(i for i, line in enumerate(game.log) if "gained 6 life from Laquatus" in line)
    lost = next(i for i, line in enumerate(game.log) if "lost 6 life" in line)
    assert gained < lost
    assert game.players[1].life == 20


def test_w1g3_an_ai_aims_the_champions_life_loss_across_the_table(set_pool):
    """"Target player loses 6 life" names a seat the cast announces, and the
    AI's spell scorer cannot read a trigger: with no side to go on it named its
    own seat and lost the 6 life itself (Soul Scourge the same, for 3).
    ``ai_target_sides._SEAT_DENIAL_KINDS`` now files the life loss as a denial."""
    from engine.ai_actions import cast_announcement
    from engine.ai_policy import choose_cast_action

    for name, amount in (("Laquatus's Champion", 6), ("Soul Scourge", 3)):
        game = _w1g3_game(set_pool, hand=[name])
        game.interactive_seats = set()
        game.active_player_index = 0
        action = choose_cast_action(game, 0)
        assert action is not None and action.card_name == name
        announced = cast_announcement(action)
        assert announced["target_player_index"] == 1, name
        announced.pop("from_zone", None)
        game.cast_from_hand(0, name, **announced)
        _w1g3_drain(game)
        assert [p.life for p in game.players] == [20, 20 - amount], name

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _W1g4Game, PlayerState as _W1g4PlayerState
from engine.models import Permanent as _W1g4Permanent
from tests.helpers import (_mk_creature_card as _w1g4_creature,
                           resolve_stack as _w1g4_resolve_stack)


def _w1g4_table(set_pool, *, hand=(), interactive=()):
    """Two seats with Swamps to draw, costs unenforced; *interactive* names
    the seats that are asked rather than defaulted."""
    swamp = set_pool("LEA")["Swamp"]
    game = _W1g4Game(players=[
        _W1g4PlayerState("P1", library=[swamp] * 10, hand=list(hand)),
        _W1g4PlayerState("P2", library=[swamp] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g4_put(game, seat, card):
    permanent = _W1g4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g4_settle(game):
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    game.check_state_based_actions()


def _w1g4_owed(game):
    return [(choice.kind, choice.player_index) for choice in game.pending_choices]


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_to_declare_attackers(game):
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            return
    raise AssertionError(f"never reached declare attackers ({game.current_step})")


def _w1g4_four_cards(set_pool):
    lea = set_pool("LEA")
    return [lea["Giant Growth"], lea["Lightning Bolt"], lea["Shivan Dragon"], lea["Swamp"]]


# --- Anurid Scavenger / Gurzigost: a toll paid out of the graveyard ----------

@_w1g4_pytest.mark.parametrize("name, owed", [("Anurid Scavenger", 1), ("Gurzigost", 2)])
def test_w1g4_graveyard_toll_is_paid_by_bottoming_the_printed_count(set_pool, name, owed):
    """"At the beginning of your upkeep, sacrifice this creature unless you put
    a card / two cards from your graveyard on the bottom of your library."

    A seat nobody asks pays the toll (the stated policy for an "unless"), so
    the printed number of cards leaves the graveyard for the library's bottom
    and the creature stays."""
    game = _w1g4_table(set_pool)
    me = game.players[0]
    pile = _w1g4_four_cards(set_pool)[:3]
    me.graveyard = list(pile)
    creature = _w1g4_put(game, 0, set_pool("TOR")[name])

    game.resolve_upkeep(0)
    _w1g4_settle(game)

    assert game.is_on_battlefield(creature)
    assert _w1g4_names(me.graveyard) == _w1g4_names(pile[owed:])
    assert _w1g4_names(me.library[-owed:]) == _w1g4_names(pile[:owed])
    assert len(me.library) == 10 + owed


@_w1g4_pytest.mark.parametrize("name, held", [("Anurid Scavenger", 0), ("Gurzigost", 1)])
def test_w1g4_graveyard_toll_a_pile_short_of_the_count_sacrifices(set_pool, name, held):
    """A graveyard holding fewer cards than the toll prints cannot pay it, so
    the offer is not made and the creature is sacrificed — Gurzigost with one
    card behind it goes, and that card stays where it is."""
    game = _w1g4_table(set_pool)
    me = game.players[0]
    pile = _w1g4_four_cards(set_pool)[:held]
    me.graveyard = list(pile)
    creature = _w1g4_put(game, 0, set_pool("TOR")[name])

    game.resolve_upkeep(0)
    _w1g4_settle(game)

    assert not game.is_on_battlefield(creature)
    assert _w1g4_names(me.graveyard) == _w1g4_names(pile) + [name]
    assert len(me.library) == 10


def test_w1g4_gurzigost_toll_asks_a_person_which_cards_and_their_order(set_pool):
    """An interactive seat is asked whether to pay, then which two cards
    (the graveyard pick, saying where the cards go), then — CR 401.4 — the
    order of the two now on the bottom of the library."""
    game = _w1g4_table(set_pool, interactive=(0,))
    me = game.players[0]
    pile = _w1g4_four_cards(set_pool)[:3]
    me.graveyard = list(pile)
    gurzigost = _w1g4_put(game, 0, set_pool("TOR")["Gurzigost"])

    game.resolve_upkeep(0, defer_priority=True)
    game.resolve_top_of_stack()
    assert _w1g4_owed(game) == [("optional_pay", 0)]
    assert game.confirm_optional_pay(0, accept=True)

    (pick,) = game.pending_choices
    assert (pick.kind, pick.data["count"], pick.data["destination"]) == (
        "graveyard_exile_pick", 2, "library_bottom",
    )
    assert game.live_graveyard_exile_candidates(pick) == [0, 1, 2]
    assert not game.confirm_graveyard_exile_pick(0, [0])  # one is not two
    assert game.confirm_graveyard_exile_pick(0, [2, 0])

    assert _w1g4_names(me.graveyard) == ["Lightning Bolt"]
    assert _w1g4_names(me.library[-2:]) == ["Shivan Dragon", "Giant Growth"]
    assert _w1g4_owed(game) == [("reorder_library", 0)]
    assert game.pending_choices[0].data["position"] == "bottom"
    assert game.is_on_battlefield(gurzigost)


def test_w1g4_gurzigost_toll_declined_by_a_person_sacrifices(set_pool):
    game = _w1g4_table(set_pool, interactive=(0,))
    me = game.players[0]
    me.graveyard = _w1g4_four_cards(set_pool)[:3]
    gurzigost = _w1g4_put(game, 0, set_pool("TOR")["Gurzigost"])

    game.resolve_upkeep(0, defer_priority=True)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=False)
    _w1g4_settle(game)

    assert not game.is_on_battlefield(gurzigost)
    assert len(me.graveyard) == 4 and len(me.library) == 10


# --- Gurzigost: its own assignment, chosen as the ability resolves ----------

def _w1g4_gurzigost_into_a_wall(set_pool, *, interactive=(), accept=True, activate=True):
    """Gurzigost (6/8) attacking into a 0/10 wall, its ability activated in
    the declare-attackers step first unless told otherwise."""
    game = _w1g4_table(
        set_pool, hand=[set_pool("LEA")["Giant Growth"]], interactive=interactive,
    )
    gurzigost = _w1g4_put(game, 0, set_pool("TOR")["Gurzigost"])
    wall = _w1g4_put(game, 1, _w1g4_creature("W1G4 Wall", 0, 10))
    _w1g4_to_declare_attackers(game)
    if activate:
        game.activate_permanent_ability(0, "Gurzigost")
        if interactive:
            assert _w1g4_owed(game) == [("optional_pay", 0)]
            assert game.confirm_optional_pay(0, accept=accept)
        _w1g4_settle(game)
        assert _w1g4_names(game.players[0].graveyard) == ["Giant Growth"]  # the discard
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 0})
    assert ok, why
    game.advance_combat_phase()
    assert game.combat_damage_resolved
    return game, gurzigost, wall


@_w1g4_pytest.mark.parametrize("interactive", [(), (0,)])
def test_w1g4_gurzigost_activated_assigns_its_damage_past_the_blocker(set_pool, interactive):
    """"{G}{G}, Discard a card: You may have this creature assign its combat
    damage this turn as though it weren't blocked." Answered yes as the
    ability resolves — "You decide how it will assign its damage at the time
    the ability resolves." (ruling, 2008-04-01) — so the damage step asks
    nothing more and the 6 goes to the player."""
    game, _gurzigost, wall = _w1g4_gurzigost_into_a_wall(set_pool, interactive=interactive)

    assert game.players[1].life == 14
    assert wall.damage_marked == 0
    assert any("as though it weren't blocked" in line for line in game.log)


def test_w1g4_gurzigost_declined_or_unactivated_hits_its_blocker(set_pool):
    game, gurzigost, wall = _w1g4_gurzigost_into_a_wall(
        set_pool, interactive=(0,), accept=False,
    )
    assert game.players[1].life == 20 and wall.damage_marked == 6

    game, gurzigost, wall = _w1g4_gurzigost_into_a_wall(set_pool, activate=False)
    assert game.players[1].life == 20 and wall.damage_marked == 6


# --- Ichorid: back from the graveyard for another black creature card -------

def _w1g4_ichorid_two_turns(set_pool, graveyard, *, interactive=(), accept=True, pick=0):
    """Ichorid cast with haste, sacrificed at the end step, and its upkeep
    trigger answered at the next upkeep."""
    tor = set_pool("TOR")
    game = _w1g4_table(set_pool, hand=[tor["Ichorid"]], interactive=interactive)
    me = game.players[0]
    me.graveyard = list(graveyard)
    game.current_step = "precombat_main"
    assert game.cast_from_hand(0, "Ichorid").details == "resolved"
    _w1g4_settle(game)
    (ichorid,) = [p for p in game.controlled_by(0) if p.card.name == "Ichorid"]
    assert game.can_attack(ichorid, 1)  # haste

    game.current_step = "end"
    game.resolve_end_step(0)
    _w1g4_settle(game)
    assert not game.is_on_battlefield(ichorid)
    assert me.graveyard[-1].name == "Ichorid"

    if interactive:
        game.resolve_upkeep(0, defer_priority=True)
        game.resolve_top_of_stack()
        if game.pending_choices:
            assert game.confirm_optional_pay(0, accept=accept)
            chosen = next(
                (c for c in game.pending_choices if c.kind == "graveyard_exile_pick"),
                None,
            )
            if chosen is not None:
                live = game.live_graveyard_exile_candidates(chosen)
                assert game.confirm_graveyard_exile_pick(0, [live[pick]])
        _w1g4_settle(game)
    else:
        game.resolve_upkeep(0)
        _w1g4_settle(game)
    return game, me


def test_w1g4_ichorid_returns_by_exiling_another_black_creature_card(set_pool):
    zombies = set_pool("LEA")["Scathe Zombies"]
    game, me = _w1g4_ichorid_two_turns(set_pool, [zombies])

    assert [p.card.name for p in game.controlled_by(0)] == ["Ichorid"]
    assert _w1g4_names(me.exile) == ["Scathe Zombies"]
    assert me.graveyard == []


@_w1g4_pytest.mark.parametrize("graveyard", [[], ["Grizzly Bears"], ["Dark Ritual"]])
def test_w1g4_ichorid_stays_without_another_black_creature_card(set_pool, graveyard):
    """Nothing black, nothing a creature, or nothing at all: the only black
    creature card in the pile is Ichorid itself, which "other than this card"
    leaves out — so no offer, and no return."""
    lea = set_pool("LEA")
    game, me = _w1g4_ichorid_two_turns(set_pool, [lea[name] for name in graveyard])

    assert list(game.controlled_by(0)) == []
    assert me.exile == []
    assert _w1g4_names(me.graveyard) == graveyard + ["Ichorid"]


def test_w1g4_ichorid_may_exile_another_ichorid_which_then_cannot_return(set_pool):
    """"If one Ichorid's ability exiles another, the exiled Ichorid's ability
    can't return it to the battlefield." (ruling, 2016-06-08.) Two Ichorids
    in the pile trigger twice; the first exiles the other copy — a second
    copy of the card is not "this card" — and returns, and the second finds
    its card gone."""
    ichorid = set_pool("TOR")["Ichorid"]
    game, me = _w1g4_ichorid_two_turns(set_pool, [ichorid])

    assert [p.card.name for p in game.controlled_by(0)] == ["Ichorid"]
    assert _w1g4_names(me.exile) == ["Ichorid"]
    assert me.graveyard == []


def test_w1g4_ichorid_asks_a_person_and_offers_only_black_creatures(set_pool):
    lea = set_pool("LEA")
    pile = [lea["Scathe Zombies"], lea["Grizzly Bears"], lea["Black Knight"]]
    game, me = _w1g4_ichorid_two_turns(set_pool, pile, interactive=(0,), pick=1)

    assert [p.card.name for p in game.controlled_by(0)] == ["Ichorid"]
    assert _w1g4_names(me.exile) == ["Black Knight"]
    assert _w1g4_names(me.graveyard) == ["Scathe Zombies", "Grizzly Bears"]


def test_w1g4_ichorid_declined_by_a_person_stays_in_the_graveyard(set_pool):
    zombies = set_pool("LEA")["Scathe Zombies"]
    game, me = _w1g4_ichorid_two_turns(set_pool, [zombies], interactive=(0,), accept=False)

    assert list(game.controlled_by(0)) == []
    assert _w1g4_names(me.graveyard) == ["Scathe Zombies", "Ichorid"]


# --- Carrion Rats / Carrion Wurm: any player may exile from their own pile --

def _w1g4_carrion_attack(set_pool, name, *, mine=(), theirs=(), interactive=(), answers=()):
    """*name* attacking an empty board; each seat's graveyard as given;
    *answers* is ``(seat, accept)`` in the order the prompts are answered."""
    game = _w1g4_table(set_pool, interactive=interactive)
    game.players[0].graveyard = list(mine)
    game.players[1].graveyard = list(theirs)
    attacker = _w1g4_put(game, 0, set_pool("TOR")[name])
    _w1g4_to_declare_attackers(game)
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why
    if interactive:
        game.resolve_top_of_stack()
        for seat, accept in answers:
            assert game.confirm_optional_pay(seat, accept=accept)
            chosen = next(
                (c for c in game.pending_choices if c.kind == "graveyard_exile_pick"),
                None,
            )
            if chosen is not None:
                assert chosen.player_index == seat
                live = game.live_graveyard_exile_candidates(chosen)
                assert game.confirm_graveyard_exile_pick(seat, live[: chosen.data["count"]])
    _w1g4_settle(game)
    for _ in range(4):
        if game.current_step in ("end_of_combat", "postcombat_main"):
            break
        game.advance_combat_phase()
    assert game.current_step in ("end_of_combat", "postcombat_main")
    assert any("Resolved combat damage" in line for line in game.log)
    return game, attacker


def test_w1g4_carrion_rats_an_opponent_exiles_from_their_graveyard(set_pool):
    """The defending player takes the offer out of *their own* pile, and the
    Rats assign no combat damage. Their controller, asked first, declines: an
    offer whose purchase is its own creature's drawback."""
    pile = _w1g4_four_cards(set_pool)
    game, _rats = _w1g4_carrion_attack(set_pool, "Carrion Rats", mine=pile, theirs=pile)

    assert game.players[1].life == 20
    # The least valuable card of the four (W2G3: an own-pile price is paid
    # with ``ai_prompt_readers.graveyard_price_order``); pile order gave up the
    # Giant Growth, the bottom card.
    assert _w1g4_names(game.players[1].exile) == ["Swamp"]
    assert game.players[0].exile == []
    assert any("declined Carrion Rats" in line for line in game.log)


def test_w1g4_carrion_rats_every_player_is_asked_in_turn(set_pool):
    """Both seats are put the offer, active player first (the Argothian Wurm
    ruling, 2007-02-01, for the same printed shape), and each takes it out of
    their own graveyard."""
    pile = _w1g4_four_cards(set_pool)
    game, _rats = _w1g4_carrion_attack(
        set_pool, "Carrion Rats", mine=pile, theirs=pile,
        interactive=(0, 1), answers=[(0, False), (1, True)],
    )

    assert game.players[1].life == 20
    assert game.players[0].exile == []
    assert len(game.players[1].exile) == 1


def test_w1g4_carrion_rats_with_no_graveyard_cards_deals_its_damage(set_pool):
    game, _rats = _w1g4_carrion_attack(set_pool, "Carrion Rats", interactive=(0, 1))

    assert game.pending_choices == []
    assert game.players[1].life == 18


def test_w1g4_carrion_wurm_owes_three_cards(set_pool):
    """"…exile three cards from their graveyard": a pile of two cannot take
    the offer, and a pile of four gives up exactly three."""
    pile = _w1g4_four_cards(set_pool)
    game, _wurm = _w1g4_carrion_attack(
        set_pool, "Carrion Wurm", theirs=pile[:2], interactive=(1,),
    )
    assert game.players[1].life == 14
    assert len(game.players[1].graveyard) == 2

    game, _wurm = _w1g4_carrion_attack(
        set_pool, "Carrion Wurm", theirs=pile, interactive=(1,), answers=[(1, True)],
    )
    assert game.players[1].life == 20
    assert len(game.players[1].exile) == 3 and len(game.players[1].graveyard) == 1


# --- Longhorn Firebeast: any opponent may take 5 to kill it -----------------

def _w1g4_firebeast(set_pool, *, interactive=(), accept=None):
    game = _w1g4_table(
        set_pool, hand=[set_pool("TOR")["Longhorn Firebeast"]], interactive=interactive,
    )
    game.current_step = "precombat_main"
    assert game.cast_from_hand(0, "Longhorn Firebeast").details == "resolved"
    if accept is not None:
        while game.stack and not game.pending_choices:
            game.resolve_top_of_stack()
        assert _w1g4_owed(game) == [("optional_pay", 1)]
        assert game.confirm_optional_pay(1, accept=accept)
    _w1g4_settle(game)
    return game


def test_w1g4_longhorn_firebeast_an_opponent_takes_five_to_sacrifice_it(set_pool):
    game = _w1g4_firebeast(set_pool, interactive=(1,), accept=True)

    assert game.players[1].life == 15
    assert list(game.controlled_by(0)) == []
    assert _w1g4_names(game.players[0].graveyard) == ["Longhorn Firebeast"]


def test_w1g4_longhorn_firebeast_declined_stays(set_pool):
    for game in (
        _w1g4_firebeast(set_pool, interactive=(1,), accept=False),
        # A seat nobody asks does not pay 5 life's worth of damage for a 3/2.
        _w1g4_firebeast(set_pool),
    ):
        assert game.players[1].life == 20
        assert [p.card.name for p in game.controlled_by(0)] == ["Longhorn Firebeast"]

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5_Game
from engine import PlayerState as _w1g5_PlayerState
from engine.models import Permanent as _w1g5_Permanent
from tests.helpers import _mk_card as _w1g5_mk_card
from tests.helpers import _nosick as _w1g5_nosick
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_duel(*, hand0=(), hand1=(), bf0=(), bf1=(), library0=None):
    filler = _w1g5_mk_card(name="W1G5 Filler", type_line="Land")
    game = _w1g5_Game(players=[
        _w1g5_PlayerState(
            "A", library=list(library0) if library0 is not None else [filler] * 10,
            hand=list(hand0),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf0],
        ),
        _w1g5_PlayerState(
            "B", library=[filler] * 10, hand=list(hand1),
            battlefield=[_w1g5_nosick(_w1g5_Permanent(card=c)) for c in bf1],
        ),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game


def test_w1g5_cephalid_vandal_mills_one_more_card_each_upkeep(set_pool):
    """A shred counter each upkeep, then a mill of one card per shred counter:
    1, then 2, then 3 — the count read off the source as the trigger resolves."""
    vandal = set_pool("TOR")["Cephalid Vandal"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Land") for i in range(10)]
    game = _w1g5_duel(bf0=[vandal], library0=library)

    milled = []
    for _turn in range(3):
        before = len(game.players[0].graveyard)
        game.start_turn(0)
        _w1g5_resolve_stack(game)
        milled.append(len(game.players[0].graveyard) - before)

    assert milled == [1, 2, 3]
    assert "Cephalid Vandal gets a shred counter (3 total)" in game.log
    assert "A milled 3 card(s)" in game.log


def test_w1g5_pitchstone_wall_returns_the_discarded_card_if_sacrificed(set_pool):
    """Two discards, two triggers. Taking the first offer sacrifices the Wall
    and returns that card; the second finds no Wall to sacrifice ("if you do")
    and returns nothing."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    wall, sludge = tor["Pitchstone Wall"], tor["Mind Sludge"]
    bolt, bears, forest = lea["Lightning Bolt"], lea["Grizzly Bears"], lea["Forest"]
    game = _w1g5_duel(
        hand0=[bolt, bears, forest], hand1=[sludge],
        bf0=[wall], bf1=[lea["Swamp"], lea["Swamp"]],
    )
    game.interactive_seats = {0}

    game.cast_from_hand(1, sludge.name, target_player_index=0)
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1], to_library=False,
    )
    assert [item.card.name for item in game.stack] == ["Pitchstone Wall"] * 2
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    _w1g5_resolve_stack(game)

    a = game.players[0]
    assert sorted(card.name for card in a.hand) == ["Forest", "Lightning Bolt"]
    assert sorted(card.name for card in a.graveyard) == ["Grizzly Bears", "Pitchstone Wall"]
    assert not list(game.controlled_by(0))


def test_w1g5_pitchstone_wall_declined_returns_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[lea["Lightning Bolt"]], hand1=[tor["Mind Sludge"]],
        bf0=[tor["Pitchstone Wall"]], bf1=[lea["Swamp"]],
    )

    game.cast_from_hand(1, "Mind Sludge", target_player_index=0)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]
    assert [p.card.name for p in game.controlled_by(0)] == ["Pitchstone Wall"]


def test_w1g5_pitchstone_wall_ignores_an_opponents_discard(set_pool):
    """"Whenever **you** discard a card": the Wall's controller only."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    game = _w1g5_duel(
        hand0=[tor["Mind Sludge"]], hand1=[lea["Lightning Bolt"]],
        bf0=[tor["Pitchstone Wall"], lea["Swamp"]],
    )

    game.cast_from_hand(0, "Mind Sludge", target_player_index=1)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[1].graveyard] == ["Lightning Bolt"]
    assert not game.stack


def test_w1g5_nantuko_cultivator_counts_and_draws_the_lands_discarded(set_pool):
    """Discard three lands: three +1/+1 counters and three cards. It placed
    none and drew none — the counters read Tetravus's ``trigger_count`` and
    the draw's handler never read ``amount_from`` — and with the counter
    step unreadable the offer could not fold its payoffs, so both ran before
    the discard was even answered."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    forest, island, bolt = lea["Forest"], lea["Island"], lea["Lightning Bolt"]
    library = [_w1g5_mk_card(name=f"W1G5 Card {i}", type_line="Instant") for i in range(10)]
    game = _w1g5_duel(hand0=[cultivator, forest, forest, island, bolt], library0=library)
    game.interactive_seats = {0}

    game.cast_from_hand(0, cultivator.name)
    game.resolve_top_of_stack()
    assert game.resolve_pending_choice("optional_pay", 0, accept=True)
    owed = game.pending_choice_of("discard", 0)
    assert owed is not None and owed.data.get("up_to")
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0, 1, 2], to_library=False,
    )
    _w1g5_resolve_stack(game)

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (5, 5)
    assert sorted(card.name for card in game.players[0].hand) == [
        "Lightning Bolt", "W1G5 Card 0", "W1G5 Card 1", "W1G5 Card 2",
    ]


def test_w1g5_nantuko_cultivator_declined_places_and_draws_nothing(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    cultivator = tor["Nantuko Cultivator"]
    game = _w1g5_duel(hand0=[cultivator, lea["Forest"]])

    game.cast_from_hand(0, cultivator.name)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()

    perm = next(p for p in game.controlled_by(0) if p.card.name == cultivator.name)
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)
    assert [card.name for card in game.players[0].hand] == ["Forest"]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState  # noqa: E402
from engine import ai_cast_gates as _w1g6_ai_cast_gates  # noqa: E402
from engine.cast_prohibitions import cast_prohibition as _w1g6_cast_prohibition  # noqa: E402
from engine.models import Permanent as _W1G6Permanent  # noqa: E402
from tests.helpers import _nosick as _w1g6_nosick, resolve_stack as _w1g6_resolve_stack  # noqa: E402


def _w1g6_llawan_table(set_pool, catalog_by_name):
    """Seat 0 holds Llawan; seat 1 has a blue creature, a green one and a
    blue-green one on the battlefield. Mana off."""
    llawan = set_pool("TOR")["Llawan, Cephalid Empress"]
    theirs = [
        _w1g6_nosick(_W1G6Permanent(card=catalog_by_name[name]))
        for name in ("Merfolk of the Pearl Trident", "Grizzly Bears", "Gaea's Skyfolk")
    ]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", hand=[llawan]),
        _W1G6PlayerState(name="P2", battlefield=theirs),
    ])
    game.enforce_mana_costs = False
    return game


def test_w1g6_llawan_bounces_the_blue_creatures_and_bans_the_blue_creature_spells(
    set_pool, catalog_by_name,
):
    """"When Llawan enters, return all blue creatures your opponents control to
    their owners' hands. Your opponents can't cast blue creature spells."

    The entry trigger takes the blue creatures and the gold one with blue in
    it (CR 105.2b), and leaves the green one. Then the ban: the opponent
    cannot cast the creatures it just got back — the engine refuses, the AI
    does not propose — but can cast a creature that is not blue, and Llawan's
    own controller casts blue creatures freely ("your opponents")."""
    game = _w1g6_llawan_table(set_pool, catalog_by_name)
    assert game.cast_from_hand(0, "Llawan, Cephalid Empress").supported
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert sorted(c.name for c in game.players[1].hand) == [
        "Gaea's Skyfolk", "Merfolk of the Pearl Trident",
    ]

    for name in ("Merfolk of the Pearl Trident", "Gaea's Skyfolk"):
        card = next(c for c in game.players[1].hand if c.name == name)
        found = _w1g6_cast_prohibition(game, 1, card)
        assert found is not None and found.source == "Llawan, Cephalid Empress", name
        assert not _w1g6_ai_cast_gates._can_cast_with_targets(game, 1, card)
        refused = game.cast_from_hand(1, name)
        assert not refused.supported and "Llawan" in refused.details
        assert name in [c.name for c in game.players[1].hand]

    # A creature that is not blue is not a blue creature spell.
    game.players[1].hand.append(catalog_by_name["Grizzly Bears"])
    assert game.cast_from_hand(1, "Grizzly Bears").supported
    _w1g6_resolve_stack(game)
    # A blue spell that is not a creature spell is not one either.
    game.players[1].hand.append(catalog_by_name["Ancestral Recall"])
    assert game.cast_from_hand(1, "Ancestral Recall", target_player_index=1).supported
    _w1g6_resolve_stack(game)

    # Llawan's controller is not its opponent.
    game.players[0].hand.append(catalog_by_name["Merfolk of the Pearl Trident"])
    assert game.cast_from_hand(0, "Merfolk of the Pearl Trident").supported
    _w1g6_resolve_stack(game)
    assert "Merfolk of the Pearl Trident" in [p.card.name for p in game.controlled_by(0)]

    # Gone, Llawan bans nothing.
    llawan = next(p for p in game.controlled_by(0) if p.card.name.startswith("Llawan"))
    game.remove_from_battlefield(llawan)
    assert game.cast_from_hand(1, "Merfolk of the Pearl Trident").supported


def test_w1g6_llawan_binds_whoever_is_her_controller_s_opponent(set_pool, catalog_by_name):
    """The ban is relative to Llawan's *controller* (CR 109.5, CR 102.3): an
    opponent who takes her is freed and her owner is bound."""
    game = _w1g6_llawan_table(set_pool, catalog_by_name)
    llawan = _w1g6_nosick(_W1G6Permanent(card=set_pool("TOR")["Llawan, Cephalid Empress"]))
    game.players[1].battlefield.append(llawan)
    merfolk = catalog_by_name["Merfolk of the Pearl Trident"]
    assert _w1g6_cast_prohibition(game, 0, merfolk) is not None
    assert _w1g6_cast_prohibition(game, 1, merfolk) is None

def test_w1g6_hydromorphs_counter_only_a_spell_that_targets_their_side(
    set_pool, catalog_by_name,
):
    """"{U}, Sacrifice this creature: Counter target spell that targets a
    creature you control." (Hydromorph Guardian, Hydromorph Gull.) A Bolt at
    its controller's face is not a legal target -- the activation is refused
    with nothing sacrificed -- and a Bolt at its controller's Grizzly Bears is
    countered."""
    for name in ("Hydromorph Guardian", "Hydromorph Gull"):
        hydromorph = _w1g6_nosick(_W1G6Permanent(card=set_pool("TOR")[name]))
        bears = _w1g6_nosick(_W1G6Permanent(card=catalog_by_name["Grizzly Bears"]))
        game = _W1G6Game(players=[
            _W1G6PlayerState(name="P1", battlefield=[hydromorph, bears]),
            _W1G6PlayerState(name="P2", hand=[catalog_by_name["Lightning Bolt"]] * 2),
        ])
        game.enforce_mana_costs = False
        assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
        assert not game.activate_permanent_ability(0, name, target_stack_index=0).supported
        assert hydromorph in list(game.controlled_by(0))
        _w1g6_resolve_stack(game)
        assert game.players[0].life == 17
        assert game.queue_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id], target_player_index=0,
        ).supported
        assert game.activate_permanent_ability(0, name, target_stack_index=0).supported
        _w1g6_resolve_stack(game)
        assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"], name
        assert bears.damage_marked == 0
        assert name in [c.name for c in game.players[0].graveyard]


def test_w1g6_cephalid_aristocrat_mills_two_when_targeted(set_pool, catalog_by_name):
    """"Whenever this creature becomes the target of a spell or ability, mill
    two cards." A Bolt aimed at it mills two before the Bolt resolves."""
    aristocrat = _w1g6_nosick(_W1G6Permanent(card=set_pool("TOR")["Cephalid Aristocrat"]))
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P1", battlefield=[aristocrat],
                         library=[catalog_by_name["Island"]] * 5),
        _W1G6PlayerState(name="P2", hand=[catalog_by_name["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[aristocrat.permanent_id], target_player_index=0,
    ).supported
    game.resolve_top_of_stack()
    assert len(game.players[0].library) == 3
    assert [c.name for c in game.players[0].graveyard] == ["Island", "Island"]
    _w1g6_resolve_stack(game)
    assert aristocrat.damage_marked == 3

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from tests.helpers import (
    _nosick as _w1g7_nosick, declare_attack as _w1g7_declare_attack,
    resolve_stack as _w1g7_resolve_stack,
)


def _w1g7_illusionist_board(set_pool):
    tor, lea = set_pool("TOR"), set_pool("LEA")
    illusionist = _w1g7_nosick(_w1g7_Permanent(card=tor["Cephalid Illusionist"]))
    ogre = _w1g7_nosick(_w1g7_Permanent(card=lea["Gray Ogre"]))
    giant = _w1g7_Permanent(card=lea["Hill Giant"])
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(
            name="P0", battlefield=[illusionist, ogre],
            library=[lea[n] for n in ("Forest", "Island", "Swamp", "Plains", "Mountain")],
        ),
        _w1g7_PlayerState(name="P1", battlefield=[giant]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    return game, illusionist, ogre, giant


def test_w1g7_cephalid_illusionist_targets_only_a_creature_you_control(set_pool):
    """"…target creature **you control**": the picker offers the caster's two
    creatures and not the opponent's, and naming the opponent's Giant is
    refused with nothing paid (CR 602.2b/601.2c)."""
    game, illusionist, ogre, giant = _w1g7_illusionist_board(set_pool)
    spec = game.activation_target_spec(0, 0, 0)
    assert {entry["name"] for entry in spec["valid_targets"]} == {
        "Cephalid Illusionist", "Gray Ogre",
    }
    refused = game.activate_permanent_ability(
        0, "Cephalid Illusionist", target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported
    assert not illusionist.tapped and not game.stack


def test_w1g7_cephalid_illusionist_targeting_itself_mills_three(set_pool):
    """Its own ability aimed at itself is "becomes the target of a spell or
    ability": three cards off its controller's library, and the shield is
    still armed when the ability resolves."""
    game, illusionist, _, _ = _w1g7_illusionist_board(set_pool)
    assert game.activate_permanent_ability(
        0, "Cephalid Illusionist", target_permanent_ids=[illusionist.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert [c.name for c in game.players[0].graveyard] == ["Forest", "Island", "Swamp"]
    assert len(game.players[0].library) == 2
    assert illusionist.tapped
    assert any(
        "dealt to and dealt by Cephalid Illusionist" in line for line in game.log
    )


def test_w1g7_cephalid_illusionist_shields_both_ends_of_a_fight(set_pool):
    """"Prevent all combat damage that would be dealt to **and dealt by**
    target creature you control this turn." The shielded Ogre is blocked by a
    Hill Giant: neither is dealt any damage."""
    game, illusionist, ogre, giant = _w1g7_illusionist_board(set_pool)
    assert game.activate_permanent_ability(
        0, "Cephalid Illusionist", target_permanent_ids=[ogre.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert game.players[0].graveyard == []   # the Ogre is not the Illusionist
    # The Illusionist is tapped; only the Ogre attacks, and the Giant blocks it.
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [1], defending_player_index=1)
    assert ok, why
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {0: 1})
    assert ok, why
    game.resolve_combat_damage(0)
    assert ogre.damage_marked == 0 and giant.damage_marked == 0
    assert ogre in game.players[0].battlefield and giant in game.players[1].battlefield


def _w1g7_snitch_board(set_pool):
    """Seat 0: Cephalid Snitch and two Terrors. Seat 1: a White Knight
    (protection from black)."""
    tor, lea = set_pool("TOR"), set_pool("LEA")
    snitch = _w1g7_nosick(_w1g7_Permanent(card=tor["Cephalid Snitch"]))
    knight = _w1g7_nosick(_w1g7_Permanent(card=lea["White Knight"]))
    game = _w1g7_Game(players=[
        _w1g7_PlayerState(name="P0", battlefield=[snitch], hand=[lea["Terror"]] * 2),
        _w1g7_PlayerState(name="P1", battlefield=[knight]),
    ])
    game.enforce_mana_costs = False
    return game, snitch, knight


def test_w1g7_cephalid_snitch_takes_protection_from_black_away(set_pool):
    """"Sacrifice this creature: Target creature loses protection from black
    until end of turn." The White Knight's printed protection was read off its
    line and the removal never asked, so the log said it lost the ability and
    a Terror still could not target it. Now it can."""
    game, snitch, knight = _w1g7_snitch_board(set_pool)
    refused = game.cast_from_hand(0, "Terror", target_permanent_ids=[knight.permanent_id])
    assert not refused.supported and "illegal target" in refused.details
    assert game.activate_permanent_ability(
        0, "Cephalid Snitch", target_permanent_ids=[knight.permanent_id],
    ).supported
    _w1g7_resolve_stack(game)
    assert snitch not in game.players[0].battlefield
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[knight.permanent_id]).supported
    _w1g7_resolve_stack(game)
    assert knight not in game.players[1].battlefield


def test_w1g7_cephalid_snitch_loss_ends_with_the_turn(set_pool):
    """Until end of turn: after cleanup the Knight has its protection back."""
    game, _, knight = _w1g7_snitch_board(set_pool)
    game.activate_permanent_ability(
        0, "Cephalid Snitch", target_permanent_ids=[knight.permanent_id],
    )
    _w1g7_resolve_stack(game)
    assert ("color", "B") not in game._protection_qualities(knight)
    game.resolve_cleanup_step(0)
    assert ("color", "B") in game._protection_qualities(knight)


def test_w1g7_a_protection_granted_after_the_loss_stays(set_pool):
    """CR 613.7: the later effect wins. Protection from black granted after
    the Snitch's removal (Floating Shield's sacrifice, black named) is kept;
    the printed one, older than the removal, is not."""
    from engine.keywords import grant_protection_flag

    game, _, knight = _w1g7_snitch_board(set_pool)
    game.activate_permanent_ability(
        0, "Cephalid Snitch", target_permanent_ids=[knight.permanent_id],
    )
    _w1g7_resolve_stack(game)
    assert ("color", "B") not in game._protection_qualities(knight)
    grant_protection_flag(knight, "black")
    assert ("color", "B") in game._protection_qualities(knight)


# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

from engine import Game as _W1G8Game, PlayerState as _W1G8Player
from engine.models import Permanent as _W1G8Permanent
from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_swarm_table(set_pool, *, humans=()):
    """Shambling Swarm and a Savannah Lions for seat 0, a Grizzly Bears and a
    Hill Giant for seat 1, and a Lightning Bolt in seat 1's hand to kill the
    Swarm with."""
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", library=[lea["Forest"]] * 10),
        _W1G8Player("B", library=[lea["Forest"]] * 10, hand=[lea["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(humans)
    placed = {}
    for seat, name, card in (
        (0, "swarm", set_pool("TOR")["Shambling Swarm"]),
        (0, "lions", lea["Savannah Lions"]),
        (1, "bears", lea["Grizzly Bears"]),
        (1, "giant", lea["Hill Giant"]),
    ):
        placed[name] = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(seat, placed[name], None)
    return game, placed


def _w1g8_bolt_the_swarm(game, swarm):
    result = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[swarm.permanent_id],
    )
    assert result.supported, result.details
    _w1g8_resolve_stack(game)


def _w1g8_body(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_w1g8_shambling_swarm_dies_and_a_seat_nobody_asks_spreads_its_counters(set_pool):
    """"When this creature dies, distribute three -1/-1 counters among one,
    two, or three target creatures." It compiled, reported supported and
    announced nothing: the handler found one creature on its own and put all
    three counters on it, and a person was never asked. A seat nobody asks
    now announces as a divided spell is proposed — the opponent's creatures,
    spread — and the shares come back at the next end step."""
    game, placed = _w1g8_swarm_table(set_pool)
    _w1g8_bolt_the_swarm(game, placed["swarm"])

    assert "Shambling Swarm: targets Grizzly Bears (2), Hill Giant (1)" in game.log
    game.check_state_based_actions()
    assert not game.is_on_battlefield(placed["bears"]), "2/2 with two -1/-1 counters"
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert _w1g8_body(placed["lions"]) == (2, 1), "its controller's own is spared"

    # One delayed removal per counter, each bound to its own creature; the
    # Bears' two find nothing (CR 400.7), the Giant's one finds the Giant.
    assert sorted(t.bound_permanent_id for t in game.delayed_triggers) == sorted([
        placed["bears"].permanent_id, placed["bears"].permanent_id,
        placed["giant"].permanent_id,
    ])
    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (3, 3)
    assert placed["giant"].metadata.get("minus_counters", 0) == 0
    assert not game.delayed_triggers


def test_w1g8_shambling_swarm_asks_its_controller_for_the_division(set_pool):
    """A person is asked which creatures **and** how the three counters are
    divided among them (CR 603.3d, CR 601.2d) — and the dying Swarm itself is
    not on offer, because the ability goes on the stack after it has died.
    Two targets are 2+1 or 1+2, which is the announcer's choice: an answer
    leaving it out is refused, and so is one that does not total three."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    assert bolt.supported
    game.resolve_top_of_stack()

    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert (asked.data["max_targets"], asked.data["division_total"]) == (3, 3)
    assert asked.data["division"] == "chosen"
    offered = {t["permanent_id"] for t in asked.data["targets"]}
    assert placed["swarm"].permanent_id not in offered
    assert offered == {
        placed[name].permanent_id for name in ("lions", "bears", "giant")
    }

    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert not game.confirm_trigger_target(0, permanent_ids=pair), "2+1 or 1+2?"
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 1])
    assert not game.confirm_trigger_target(0, permanent_ids=pair, amounts=[3, 0])
    assert not game.confirm_trigger_target(0, permanent_ids=[]), "one or more"
    assert game.pending_choices == [asked]

    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[1, 2])
    _w1g8_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g8_body(placed["bears"]) == (1, 1)
    assert _w1g8_body(placed["giant"]) == (1, 1)

    game.resolve_end_step(1)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["bears"]) == (2, 2)
    assert _w1g8_body(placed["giant"]) == (3, 3)


def test_w1g8_shambling_swarm_forced_divisions_need_no_amounts(set_pool):
    """One target takes all three and three targets take one apiece — no
    choice is left to make, so an answer naming either needs no division."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    assert game.confirm_trigger_target(0, permanent_id=placed["giant"].permanent_id)
    _w1g8_resolve_stack(game)
    assert _w1g8_body(placed["giant"]) == (0, 0)
    assert _w1g8_body(placed["bears"]) == (2, 2)


def test_w1g8_shambling_swarm_keeps_a_departed_targets_share_out(set_pool):
    """CR 608.2b: a target that has left is illegal and its share goes
    nowhere — the survivor keeps exactly what was announced for it, and the
    ability still resolves for it."""
    game, placed = _w1g8_swarm_table(set_pool, humans=(0,))
    game.players[0].hand.append(set_pool("LEA")["Unsummon"])
    game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[placed["swarm"].permanent_id],
    )
    game.resolve_top_of_stack()
    pair = [placed["bears"].permanent_id, placed["giant"].permanent_id]
    assert game.confirm_trigger_target(0, permanent_ids=pair, amounts=[2, 1])

    # In response, the Bears go back to their owner's hand.
    bounce = game.cast_from_hand(
        0, "Unsummon", target_player_index=1,
        target_permanent_ids=[placed["bears"].permanent_id],
    )
    assert bounce.supported, bounce.details
    _w1g8_resolve_stack(game)

    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert _w1g8_body(placed["giant"]) == (2, 2)
    assert placed["giant"].metadata.get("minus_counters") == 1


def _w1g8_cast_firecat(set_pool, monkeypatch, coins):
    """Crazed Firecat cast and resolved with the flips scripted, entry
    trigger and all."""
    script = iter(coins)
    monkeypatch.setattr(
        "engine.handlers.control_flow.flip_coin", lambda: next(script)
    )
    lea = set_pool("LEA")
    game = _W1G8Game(players=[
        _W1G8Player("A", hand=[set_pool("TOR")["Crazed Firecat"]]),
        _W1G8Player("B", library=[lea["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    result = game.cast_from_hand(0, "Crazed Firecat")
    assert result.supported, result.details
    _w1g8_resolve_stack(game)
    (firecat,) = game.controlled_by(0)
    return game, firecat


def test_w1g8_crazed_firecat_counts_the_flips_it_won(monkeypatch, set_pool):
    """"When this creature enters, flip a coin until you lose a flip. Put a
    +1/+1 counter on this creature for each flip you won." Won, won, lost:
    two counters, and the losing flip ends the run (the scripted coin has no
    fourth face to give)."""
    game, firecat = _w1g8_cast_firecat(set_pool, monkeypatch, [True, True, False])
    assert _w1g8_body(firecat) == (6, 6)
    assert firecat.metadata.get("plus_counters") == 2
    assert "Crazed Firecat: won 2 flip(s) before losing one" in game.log


def test_w1g8_crazed_firecat_that_loses_the_first_flip_gets_nothing(monkeypatch, set_pool):
    """The losing flip is not a flip won: lose the first and the Firecat is
    its printed 4/4."""
    game, firecat = _w1g8_cast_firecat(set_pool, monkeypatch, [False])
    assert _w1g8_body(firecat) == (4, 4)
    assert not firecat.metadata.get("plus_counters")


def test_w1g8_for_each_flip_you_won_names_a_run_or_nothing():
    """The count is the run's record, read through the producer gate every
    back-reference passes: with no run of flips in front of it the words name
    nothing, and the line refuses rather than placing zero counters."""
    from engine.grammar import compile_line

    lone = compile_line(
        "When this creature enters, put a +1/+1 counter on this creature for "
        "each flip you won."
    )
    assert not lone.usable and lone.lowering_error

# ==== end W1G8 ======================================================

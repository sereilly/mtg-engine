"""Onslaught artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# Dream Chisel — a cost reduction for face-down creature spells (CR 601.2f,
# CR 708.4: an object cast face down is turned face down before it is put on
# the stack, so the reduction sees the face-down 2/2).

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.card_loader import load_catalog as _w1g2_load_catalog
from engine.face_down import is_face_down as _w1g2_is_face_down
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack

_W1G2_CATALOG = {card.name: card for card in _w1g2_load_catalog()}


def _w1g2_table(mine=(), theirs=(), hand=()):
    p1 = _W1G2PlayerState(name="A", hand=list(hand), battlefield=list(mine),
                          library=[_W1G2_CATALOG["Island"]] * 10)
    p2 = _W1G2PlayerState(name="B", battlefield=list(theirs),
                          library=[_W1G2_CATALOG["Island"]] * 10)
    game = _W1G2Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game, p1, p2


def _w1g2_morph_price(game, seat, card):
    """What the picker, the AI and ``payable`` price a morph cast at."""
    (morph,) = game.applicable_alternative_costs(seat, card)
    owed = game.alternative_cost_mana(seat, card, morph)
    return sum(owed.values())


def test_w1g2_dream_chisel_makes_a_morph_cast_cost_two(set_pool):
    """"Face-down creature spells you cast cost {1} less to cast." Exalted
    Angel cast face down for {3} − {1}: two colourless mana pay for it, and
    every reader that prices the cast says {2}."""
    ons = set_pool("ONS")
    assert _w1g2_compile(ons["Dream Chisel"]).supported
    chisel = _W1G2Permanent(card=ons["Dream Chisel"])
    game, p1, _p2 = _w1g2_table([chisel], hand=[ons["Exalted Angel"]])
    assert _w1g2_morph_price(game, 0, ons["Exalted Angel"]) == 2
    p1.mana_pool.update({"C": 2})
    result = game.queue_from_hand(0, "Exalted Angel", alternative_cost=True)
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    assert sum(p1.mana_pool.values()) == 0
    (_chisel, angel) = p1.battlefield
    assert _w1g2_is_face_down(angel)
    assert any("costs less to cast (Dream Chisel)" in line for line in game.log)


def test_w1g2_two_dream_chisels_and_an_opponents(set_pool):
    """Two of yours reduce a morph cast to {1} (CR 601.2f adds every
    reduction); the opponent's does nothing for you ("you cast")."""
    ons = set_pool("ONS")
    mine = [_W1G2Permanent(card=ons["Dream Chisel"]) for _ in range(2)]
    theirs = [_W1G2Permanent(card=ons["Dream Chisel"])]
    game, p1, _p2 = _w1g2_table(mine, theirs, hand=[ons["Exalted Angel"]])
    assert _w1g2_morph_price(game, 0, ons["Exalted Angel"]) == 1
    p1.mana_pool.update({"C": 1})
    assert game.queue_from_hand(0, "Exalted Angel", alternative_cost=True).supported
    assert sum(p1.mana_pool.values()) == 0


def test_w1g2_dream_chisel_does_nothing_for_a_face_up_creature_spell(set_pool):
    """A creature spell cast face up is no face-down creature spell: a
    Grizzly Bears still costs {1}{G}, and the morph card cast for its mana cost
    pays all of it."""
    ons = set_pool("ONS")
    chisel = _W1G2Permanent(card=ons["Dream Chisel"])
    game, p1, _p2 = _w1g2_table([chisel], hand=[_W1G2_CATALOG["Grizzly Bears"]])
    p1.mana_pool.update({"G": 1})
    refused = game.queue_from_hand(0, "Grizzly Bears")
    assert not refused.supported and [c.name for c in p1.hand] == ["Grizzly Bears"]
    p1.mana_pool.update({"C": 1})
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert sum(p1.mana_pool.values()) == 0

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.layer_bridge import computed_types as _w1g4_computed_types
from engine.models import Permanent as _W1G4Permanent
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import _nosick as _w1g4_nosick
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(name, subtype):
    return _w1g4_mk_card(name, "{2}", f"Creature - {subtype}", "")


def _w1g4_enter(set_pool, name, *, x_value=None, library=()):
    """*name* cast by P1 over two Elves of P1's and three Goblins of P2's."""
    elves = [_w1g4_nosick(_W1G4Permanent(card=_w1g4_card(f"My Elf {n}", "Elf"))) for n in range(2)]
    goblins = [_W1G4Permanent(card=_w1g4_card(f"Their Goblin {n}", "Goblin")) for n in range(3)]
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", hand=[set_pool("ONS")[name]], battlefield=list(elves),
            library=list(library),
        ),
        _W1G4PlayerState(name="P2", battlefield=list(goblins)),
    ])
    game.enforce_mana_costs = False
    kwargs = {"x_value": x_value} if x_value is not None else {}
    assert game.cast_from_hand(0, name, **kwargs).supported
    _w1g4_resolve_stack(game)
    source = _w1g4_nosick(
        next(perm for perm in game.controlled_by(0) if perm.card.name == name)
    )
    return game, source, elves, goblins


def test_w1g4_doom_cannon_names_a_type_its_controller_can_sacrifice(set_pool):
    """"As this artifact enters, choose a creature type. {3}, {T}, Sacrifice a
    creature of the chosen type: This artifact deals 3 damage to any target."
    A cost is paid with its payer's own creatures (CR 701.21a), so the default
    names the controller's type; at ingest it named the opponents' and the
    Cannon could never be activated."""
    game, cannon, elves, _goblins = _w1g4_enter(set_pool, "Doom Cannon")
    assert cannon.metadata["chosen_creature_type"] == "elf"

    result = game.activate_permanent_ability(0, "Doom Cannon", target_player_index=1)
    assert result.supported, result.details
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 17
    assert sum(
        1 for perm in game.controlled_by(0) if any(perm is elf for elf in elves)
    ) == 1


def test_w1g4_riptide_replicator_makes_a_token_of_the_chosen_color_and_type(set_pool):
    """"As this artifact enters, choose a color and a creature type. This
    artifact enters with X charge counters on it. {4}, {T}: Create an X/X
    creature token of the chosen color and type, where X is the number of
    charge counters on this artifact." The token is the type its controller's
    own cards have most of, at X = 2."""
    game, replicator, _elves, _goblins = _w1g4_enter(
        set_pool, "Riptide Replicator", x_value=2,
        library=[_w1g4_card("Library Elf", "Elf")] * 3,
    )
    chosen = replicator.metadata["chosen_creature_type"]
    assert chosen == "elf"
    assert game.activate_permanent_ability(0, "Riptide Replicator").supported
    _w1g4_resolve_stack(game)

    (token,) = [perm for perm in game.controlled_by(0) if perm.metadata.get("is_token")]
    assert (token.effective_power, token.effective_toughness) == (2, 2)
    assert chosen in _w1g4_computed_types(token)[1]
    assert set(token.effective_colors) == {replicator.metadata["chosen_color"]}

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# "Share a creature type" (CR 205.3m) — Cryptic Gateway: "Tap two untapped
# creatures you control: You may put a creature card from your hand that shares
# a creature type with each creature tapped this way onto the battlefield."

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.targeting import derive_activation_spec as _w1g6_activation_spec
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    for code in ("ONS", "LEA", "LEG", "UDS"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


#: The ruling's own example (2022-12-08): an Elf Wizard and a Human Warrior
#: tapped, and an Elf Warrior put onto the battlefield.
_W1G6_TAPPED = ("Ivy Seer", "Barktooth Warbeard")
#: The hand: the Elf Warrior shares Elf with one and Warrior with the other;
#: the Elf Druid shares only Elf, the Human Soldier only Human, the Bear nothing.
_W1G6_HAND = ("Wirewood Elf", "Glory Seeker", "Elvish Warrior", "Grizzly Bears")


def _w1g6_gateway_table(set_pool, *, hand=_W1G6_HAND, interactive=(0,), sick=False):
    me = _W1G6PlayerState(
        name="Me", hand=[_w1g6_card(set_pool, n) for n in hand],
        library=[_w1g6_card(set_pool, "Forest")] * 6,
    )
    opp = _W1G6PlayerState(name="Opp", library=[_w1g6_card(set_pool, "Island")] * 6)
    game = _W1G6Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    gateway = _W1G6Permanent(card=_w1g6_card(set_pool, "Cryptic Gateway"))
    game._put_permanent_onto_battlefield(0, gateway, None)
    tapped = []
    for name in _W1G6_TAPPED:
        perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
        game._put_permanent_onto_battlefield(0, perm, None)
        if not sick:
            perm.metadata["summoning_sickness_turn"] = -99
        tapped.append(perm)
    game.stack.clear()
    game.start_turn(0)
    game._close_current_priority_step()
    return game, gateway, tapped


def _w1g6_activate(game, tapped):
    result = game.queue_permanent_ability(
        0, "Cryptic Gateway", cost_permanent_ids=[p.permanent_id for p in tapped],
    )
    assert result.supported, result
    assert all(perm.tapped for perm in tapped), "the cost tapped both"
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(0, accept=True)


def _w1g6_offered(game):
    (choice,) = game.pending_choices_of("put_from_hand_choice", 0)
    hand = game.players[0].hand
    return [hand[index].name for index in game.live_put_from_hand_choices(choice)]


def test_w1g6_cryptic_gateway_offers_only_a_card_sharing_a_type_with_each_tapped_creature(set_pool):
    """Cryptic Gateway (2022-12-08): "The two creatures you tap … don't
    necessarily have to share a creature type, but the creature card you put
    onto the battlefield must share a creature type with each of them. For
    example, you could tap an Elf Wizard and a Human Warrior to put an Elf
    Warrior card onto the battlefield." The Elf Druid shares only with the
    Wizard and the Human Soldier only with the Warrior, so the Elf Warrior is
    the one card offered — and it is put onto the battlefield."""
    game, _gateway, tapped = _w1g6_gateway_table(set_pool)
    _w1g6_activate(game, tapped)

    assert _w1g6_offered(game) == ["Elvish Warrior"], game.log
    hand = game.players[0].hand
    assert not game.confirm_put_from_hand_choice(0, [c.name for c in hand].index("Wirewood Elf"))
    assert game.confirm_put_from_hand_choice(0, [c.name for c in hand].index("Elvish Warrior"))
    _w1g6_resolve_stack(game)

    assert any(
        perm.card.name == "Elvish Warrior" for perm in game.controlled_by(0)
    ), game.log
    assert [card.name for card in game.players[0].hand] == [
        "Wirewood Elf", "Glory Seeker", "Grizzly Bears",
    ]


def test_w1g6_cryptic_gateway_with_no_card_that_shares_with_both_offers_nothing(set_pool):
    """No card in hand shares a type with **each** tapped creature — the Elf
    Druid and the Human Soldier each share with one of them — so nothing is
    put onto the battlefield and the hand is unchanged."""
    game, _gateway, tapped = _w1g6_gateway_table(
        set_pool, hand=("Wirewood Elf", "Glory Seeker"),
    )
    result = game.queue_permanent_ability(
        0, "Cryptic Gateway", cost_permanent_ids=[p.permanent_id for p in tapped],
    )
    assert result.supported
    game.auto_resolve_pending_choices()
    _w1g6_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [card.name for card in game.players[0].hand] == ["Wirewood Elf", "Glory Seeker"]
    assert not game.pending_choices_of("put_from_hand_choice", 0)
    assert len(list(game.controlled_by(0))) == 3


def test_w1g6_cryptic_gateway_may_tap_creatures_that_just_arrived(set_pool):
    """Cryptic Gateway (2022-12-08): "You can tap any untapped creatures you
    control to activate Cryptic Gateway's ability, even ones you haven't
    controlled continuously since the beginning of your most recent turn."
    CR 302.6 restricts a creature's *own* {T} abilities, and this is the
    artifact's ability: two creatures that arrived this turn pay it."""
    game, _gateway, tapped = _w1g6_gateway_table(set_pool, sick=True)
    assert all(not game._controlled_since_turn_start(p) for p in tapped)
    _w1g6_activate(game, tapped)

    assert _w1g6_offered(game) == ["Elvish Warrior"]


def test_w1g6_cryptic_gateway_names_no_target(set_pool):
    """The picker: the ability targets nothing (the creature card is chosen as
    it resolves, CR 608.2d), so no target spec is derived for the client to
    answer, and the cost's two creatures are what the activation names."""
    gateway = _w1g6_card(set_pool, "Cryptic Gateway")
    (ability,) = _w1g6_compile(gateway).activated_abilities
    assert ability.supported
    assert ability.cost.tap_count == 2
    spec = _w1g6_activation_spec(ability)
    assert spec is None or not spec.get("requires_target"), spec

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================

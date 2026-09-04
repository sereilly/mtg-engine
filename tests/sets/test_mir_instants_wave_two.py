"""Per-card tests for Mirage's instants — the wave-2 continuation.

The continuation of `test_mir_instants.py`, opened at wave 3 when that file
stood at 2,495 of the 2,600-line guard: near enough that two more groups'
blocks would sum past it at integration, which is the breach SET_PLAYBOOK.md
tells the integrator to expect and no single branch to be at fault for. Cut at
a **section boundary**, which is what `tests/sets/README.md` asks for past the
printed-type axis — every section here is self-contained and written up in
ROADMAP.md under the round or group that bought it.

The same block convention holds: append a delimited block headed
``# --- W<wave>G<n>: <topic> ---`` with **its own imports at the top of its own
block**, and do not edit this docstring or an earlier block.
"""

from __future__ import annotations


# --- W3G5: Shallow Grave's phantom graveyard picker ---

from engine import Game as _w3g5i_Game, PlayerState as _w3g5i_PlayerState  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g5i_compile  # noqa: E402
from engine.targeting import derive_cast_spec as _w3g5i_cast_spec  # noqa: E402


def _w3g5i_grave_game(set_pool, graveyard=()):
    """Shallow Grave in seat 0's hand, with the named cards in its graveyard."""
    pool = set_pool("MIR")
    game = _w3g5i_Game(players=[
        _w3g5i_PlayerState(
            name="P1",
            hand=[pool["Shallow Grave"]],
            library=[pool["Island"]] * 6,
            graveyard=[pool[name] for name in graveyard],
        ),
        _w3g5i_PlayerState(name="P2", library=[pool["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def test_shallow_grave_derives_no_picker_because_it_chooses_nothing(set_pool):
    """"Return **the top** creature card of your graveyard to the battlefield."

    The picker sweep's Cleanse class. The handler says outright that nobody
    chooses — it overwrites whatever index the wire carried and walks the pile
    from the back — and the derivation claimed a ``graveyard_creature`` picker
    anyway. That is the derivation disagreeing with the program it is derived
    from, which is the same failure `_reanimation_spec`'s own docstring already
    records one payload key over.
    """
    pool = set_pool("MIR")
    card = pool["Shallow Grave"]

    assert _w3g5i_cast_spec(card, _w3g5i_compile(card)) is None


def test_shallow_grave_on_an_empty_graveyard_offers_the_client_nothing(set_pool):
    """The consequence the sweep names: a picker the client must fill from an
    empty candidate list is a cast that cannot be made.

    The enumeration is the evidence rather than the spec — it is what the app
    puts in front of the player — so it is asserted here and not only above.
    """
    game = _w3g5i_grave_game(set_pool)
    pool = set_pool("MIR")

    assert game._enumerate_targets(
        0, pool["Shallow Grave"],
        {"kind": "graveyard_creature", "own_graveyard_only": True},
        for_cast=True,
    ) == []


def test_shallow_grave_with_an_empty_graveyard_resolves_to_nothing(set_pool):
    """And the reading that makes the picker wrong rather than merely absent:
    with no creature card the spell resolves having done nothing, which is a
    legal (if wasteful) cast — not a cast the rules refuse."""
    game = _w3g5i_grave_game(set_pool)

    assert game.cast_from_hand(0, "Shallow Grave").supported
    game.resolve_stack()

    assert list(game.controlled_by(0)) == []
    assert "no creature card in the graveyard" in " ".join(game.log)


def test_shallow_grave_takes_the_last_creature_card_added(set_pool):
    """"The top creature card" is CR 404.3's ordering: a graveyard is ordered
    and CR 400.4 appends, so the top card is the most recently added and "the
    top creature card" is the last one of those. Two creature cards with a
    noncreature card on top of them is the board that tells the two readings
    apart."""
    game = _w3g5i_grave_game(
        set_pool, graveyard=("Bay Falcon", "Barbed Foliage", "Mtenda Lion")
    )

    assert game.cast_from_hand(0, "Shallow Grave").supported
    game.resolve_stack()

    assert [p.card.name for p in game.controlled_by(0)] == ["Mtenda Lion"]
    assert [c.name for c in game.players[0].graveyard] == [
        "Bay Falcon", "Barbed Foliage", "Shallow Grave"
    ]
# --- W3G4: Delirium, a bound creature biting its own controller ---
#
# "Cast this spell only during an opponent's turn.
#  Tap target creature that player controls. That creature deals damage equal
#  to its power to the player. Prevent all combat damage that would be dealt to
#  and dealt by the creature this turn."
#
# Three sentences and three different questions. The tap chooses the target;
# the bite reads the creature the tap recorded, and deals *the creature's*
# damage (CR 119.3) rather than the spell's; the prevention is the shipped
# to-and-by shield Maze of Ith already prints.
#
# "That player" has its antecedent in the **timing clause**, which is a
# registry line producing no instruction at all — so the seat comes from
# `cast_restrictions.timing_fixed_seat`, the table that owns the phrase, and
# the picker and the resolution ask the same function.

from engine import Game as _w3g4i_Game, PlayerState as _w3g4i_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w3g4i_load,  # noqa: E402
                                manifest_set_path as _w3g4i_path)
from engine.models import Permanent as _w3g4i_Permanent  # noqa: E402
from engine.pt import add_pt_modifier as _w3g4i_pump  # noqa: E402


def _w3g4i_lea():
    return {card.name: card for card in _w3g4i_load(_w3g4i_path("LEA"))}


def _w3g4i_game(pool, *, mine=(), theirs=(), active=1):
    """P1 holds Delirium; it is P2's turn, which is the only window it has."""
    lea = _w3g4i_lea()
    game = _w3g4i_Game(players=[
        _w3g4i_PlayerState(name="P1", hand=[pool["Delirium"]],
                           battlefield=list(mine), library=[lea["Island"]] * 6),
        _w3g4i_PlayerState(name="P2", battlefield=list(theirs),
                           library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = active
    return game


def test_w3g4_delirium_bites_with_the_power_the_layers_computed(set_pool):
    """The damage is the creature's *effective* power (CR 613), not its printed
    one, and it lands on the creature's own controller."""
    pool = set_pool("MIR")
    bear = _w3g4i_Permanent(card=_w3g4i_lea()["Grizzly Bears"])   # printed 2/2
    game = _w3g4i_game(pool, theirs=[bear])
    _w3g4i_pump(bear, 3, 3)
    assert bear.effective_power == 5

    cast = game.cast_from_hand(
        0, "Delirium", target_player_index=1, target_permanent_index=0
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert bear.tapped, game.log
    assert game.players[1].life == 15, game.log      # 5, not the printed 2
    assert game.players[0].life == 20, "the caster is not the player it names"


def test_w3g4_delirium_offers_only_the_active_opponents_creatures(set_pool):
    """CR 601.2c: "target creature **that player** controls" has to know which
    player before it can offer one, and the antecedent is the timing clause.

    Without it the flag matched no seat at all and the picker offered nothing —
    a supported card no player could cast."""
    pool = set_pool("MIR")
    lea = _w3g4i_lea()
    mine = _w3g4i_Permanent(card=lea["Grizzly Bears"])
    theirs = _w3g4i_Permanent(card=lea["Hill Giant"])
    game = _w3g4i_game(pool, mine=[mine], theirs=[theirs])

    spec = game.cast_target_spec(0, pool["Delirium"])
    offered = {t["name"] for t in spec["valid_targets"]}

    assert offered == {"Hill Giant"}, spec["valid_targets"]


def test_w3g4_delirium_prevents_combat_damage_both_ways(set_pool):
    """The third sentence is the shield Maze of Ith prints, armed off the same
    record: combat damage to *and* by the creature, and noncombat damage
    untouched."""
    pool = set_pool("MIR")
    lea = _w3g4i_lea()
    bear = _w3g4i_Permanent(card=lea["Grizzly Bears"])
    blocker = _w3g4i_Permanent(card=lea["Hill Giant"])
    game = _w3g4i_game(pool, mine=[blocker], theirs=[bear])

    game.cast_from_hand(
        0, "Delirium", target_player_index=1, target_permanent_index=0
    )
    game.resolve_stack()
    game._settle()

    game._mark_damage_on_permanent(bear, 3, source=blocker, combat=True)
    assert bear.damage_marked == 0, game.log

    game._mark_damage_on_permanent(bear, 1, source=pool["Delirium"], combat=False)
    assert bear.damage_marked == 1, "only *combat* damage is prevented"


def test_w3g4_delirium_deals_no_damage_when_its_creature_has_left(set_pool):
    """The biter is read out of the scratchpad by id, so a permanent that is
    gone deals nothing — CR 608.2's last-known information is about reading a
    characteristic, not about acting from a graveyard."""
    pool = set_pool("MIR")
    bear = _w3g4i_Permanent(card=_w3g4i_lea()["Grizzly Bears"])
    game = _w3g4i_game(pool, theirs=[bear])

    from engine.oracle import compile_card_oracle as _compile
    from engine.game_types import OracleExecutionContext as _Ctx
    from engine.handlers.registry import EFFECT_HANDLERS as _HANDLERS

    program = _compile(pool["Delirium"])
    steps = program.instructions[0].payload["steps"]
    bite = next(s for s in steps if s.kind == "bound_bites_player")

    context = _Ctx(
        caster=game.players[0], target=game.players[1], card=pool["Delirium"],
        results={"tapped_permanents": [bear.permanent_id + 500]},
    )
    _HANDLERS[bite.kind](game, bite, context)

    assert game.players[1].life == 20, game.log


# --- W4G1: Aleatory's combat window (CR 506.7) ---

from engine import Game as _w4g1i_Game, PlayerState as _w4g1i_PlayerState  # noqa: E402
from engine.models import Permanent as _w4g1i_Permanent  # noqa: E402
from tests.helpers import _nosick as _w4g1i_nosick  # noqa: E402


def _w4g1i_combat_game(set_pool, spell: str):
    """Seat 0 holding *spell*, with a creature apiece and an attack to declare.

    Real combat rather than a poked phase where the window is being read: a
    timing clause is only worth having if the cast path meets it, and stepping
    the game through its own combat is what puts the card in front of it.
    """
    pool = set_pool("MIR")
    lea = set_pool("LEA")
    mine = _w4g1i_Permanent(card=lea["Grizzly Bears"])
    theirs = _w4g1i_Permanent(card=lea["Grizzly Bears"])
    _w4g1i_nosick(mine)
    _w4g1i_nosick(theirs)
    game = _w4g1i_Game(players=[
        _w4g1i_PlayerState(
            name="P1", hand=[pool[spell]], library=[pool["Mountain"]] * 6,
            battlefield=[mine],
        ),
        _w4g1i_PlayerState(
            name="P2", library=[pool["Mountain"]] * 6, battlefield=[theirs],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.start_turn(0)
    return game, mine, theirs


def test_w4g1_aleatory_is_refused_before_blockers_are_declared(set_pool):
    """"Cast this spell only during combat after blockers are declared."

    An unenforced timing clause has no symptom — the spell resolves, the card
    reports supported, and the game is wrong in its caster's favour — so this
    drives the cast path at four points the window is shut and checks the card
    is still in hand each time.
    """
    game, mine, _theirs = _w4g1i_combat_game(set_pool, "Aleatory")

    def _refused(where: str) -> None:
        result = game.cast_from_hand(
            0, "Aleatory", target_player_index=0, target_permanent_index=0,
        )
        assert result.supported is False, f"{where}: {result.details}"
        assert result.details == (
            "can only be cast during combat after blockers are declared"
        ), where
        assert any(card.name == "Aleatory" for card in game.players[0].hand), where

    _refused("precombat main")

    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    _refused("beginning of combat")

    game.advance_combat_phase()  # declare_attackers
    _refused("declare attackers")

    game.declare_attackers(0, [0])

    # The declare blockers step itself is *not* refused: CR 509.1 declares
    # blockers as a turn-based action when the step begins, so every moment of
    # it anybody could cast in is after the declaration. The two ends of the
    # turn are, though, and they are the ones a "combat" floor is for.
    game.current_turn_phase, game.current_step = "postcombat_main", "declare_blockers"
    _refused("postcombat main")

    game.current_turn_phase = "ending"
    _refused("ending phase")


def test_w4g1_aleatory_resolves_once_blockers_have_been_declared(set_pool):
    """The other end of the same window: a restriction that refuses everything
    passes a test that only checks it refuses."""
    game, mine, _theirs = _w4g1i_combat_game(set_pool, "Aleatory")
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    game.declare_attackers(0, [0])
    game.advance_combat_phase()  # declare_blockers
    game.declare_blockers(1, {})

    result = game.cast_from_hand(
        0, "Aleatory", target_player_index=0, target_permanent_index=0,
    )

    assert result.supported is True, result.details
    assert not any(card.name == "Aleatory" for card in game.players[0].hand)


def test_w4g1_rapid_fires_window_is_the_same_point_seen_from_the_other_side(
    set_pool,
):
    """Legends' Rapid Fire prints "only **before** blockers are declared", and
    the two clauses partition the turn: no moment may be legal for both or for
    neither. The pairing is what the complement in ``cast_restrictions`` buys,
    and it is asserted rather than assumed because the failure is silent — one
    predicate updated and not the other simply makes a card castable in a
    window it does not print."""
    from engine.cast_restrictions import check_cast_timing

    game, _mine, _theirs = _w4g1i_combat_game(set_pool, "Aleatory")
    after = "cast this spell only during combat after blockers are declared."
    before = "cast this spell only before blockers are declared."

    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat

    # Every step of the turn, both clauses, and exactly one of them open at a
    # time inside combat. The precombat main phase is the pair's asymmetry and
    # is checked too: it is before the declaration and *not* during combat, so
    # neither clause admits Aleatory there and Rapid Fire's does admit it.
    assert check_cast_timing(game, 0, before) is None
    assert check_cast_timing(game, 0, after) is not None

    for step in ("beginning_of_combat", "declare_attackers"):
        game.current_step = step
        assert check_cast_timing(game, 0, before) is None, step
        assert check_cast_timing(game, 0, after) is not None, step

    for step in ("declare_blockers", "combat_damage", "end_of_combat"):
        game.current_step = step
        assert check_cast_timing(game, 0, before) is not None, step
        assert check_cast_timing(game, 0, after) is None, step

    game.current_turn_phase = "precombat_main"
    assert check_cast_timing(game, 0, before) is None
    assert check_cast_timing(game, 0, after) is not None


# W4G1, continued: Lure of Prey's window on what an opponent has cast (CR 601.3)


def _w4g1i_prey_game(set_pool):
    """Lure of Prey in seat 0's hand, a green creature behind it, seat 1 armed
    with one creature spell and one instant."""
    pool = set_pool("MIR")
    lea = set_pool("LEA")
    game = _w4g1i_Game(players=[
        _w4g1i_PlayerState(
            name="P1",
            hand=[pool["Lure of Prey"], lea["Grizzly Bears"]],
            library=[pool["Forest"]] * 6,
        ),
        _w4g1i_PlayerState(
            name="P2",
            hand=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
            library=[pool["Forest"]] * 6,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _w4g1i_cast_prey(game):
    return game.cast_from_hand(0, "Lure of Prey")


def test_w4g1_lure_of_prey_is_refused_when_no_opponent_has_cast_a_creature(set_pool):
    """"Cast this spell only if an opponent cast a creature spell this turn."

    Three boards that all fail the condition for different reasons, because the
    near misses are what an unenforced restriction looks like: nobody has cast
    anything, an opponent cast something that is not a creature, and the caster
    cast the creature themselves ("an **opponent**").
    """
    game = _w4g1i_prey_game(set_pool)
    game.start_turn(1)
    denial = "can only be cast if an opponent cast a creature spell this turn"

    result = _w4g1i_cast_prey(game)
    assert result.supported is False and result.details == denial, result
    assert any(card.name == "Lure of Prey" for card in game.players[0].hand)

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = _w4g1i_cast_prey(game)
    assert result.supported is False and result.details == denial, result

    game.start_turn(0)
    game.cast_from_hand(0, "Grizzly Bears")
    result = _w4g1i_cast_prey(game)
    assert result.supported is False and result.details == denial, (
        "the caster's own creature spell is not an opponent's"
    )


def test_w4g1_lure_of_prey_is_castable_after_an_opponents_creature_spell(set_pool):
    """The other end of the window — a restriction that refuses everything
    passes a test that only checks it refuses."""
    game = _w4g1i_prey_game(set_pool)
    game.start_turn(1)
    game.cast_from_hand(1, "Grizzly Bears")

    result = _w4g1i_cast_prey(game)

    assert result.supported is True, result.details
    assert not any(card.name == "Lure of Prey" for card in game.players[0].hand)


def test_w4g1_lure_of_preys_window_closes_at_the_turn_boundary(set_pool):
    """"This turn" is the turn, and the record it reads is emptied with the rest
    of the turn's history. A record that outlived its turn would be a
    restriction that stopped applying — which is the direction that lets a card
    be cast when it may not be, and it fails no test that only casts it once."""
    game = _w4g1i_prey_game(set_pool)
    game.start_turn(1)
    game.cast_from_hand(1, "Grizzly Bears")
    assert _w4g1i_check_prey(game) is None

    game.start_turn(0)

    assert _w4g1i_check_prey(game) == (
        "can only be cast if an opponent cast a creature spell this turn"
    )


def _w4g1i_check_prey(game):
    from engine.cast_restrictions import check_cast_timing

    return check_cast_timing(
        game, 0, "cast this spell only if an opponent cast a creature spell this turn."
    )


def test_w4g1_the_opponent_cast_window_reads_its_noun_phrase(set_pool):
    """The phrase is payload, not part of the template: a card printed about an
    artifact spell or a black one is this restriction with one word changed.
    Read through the same noun parser and card matcher the damage-source row
    beside it uses, so what the phrase names is one answer."""
    from engine.cast_restrictions import cast_opponent_cast_line

    assert cast_opponent_cast_line(
        "cast this spell only if an opponent cast a creature spell this turn"
    ) == ({"type_filter": "creature"}, "a creature spell")
    assert cast_opponent_cast_line(
        "cast this spell only if an opponent cast a black artifact spell this turn"
    ) == ({"type_filter": "artifact", "color_filter": "B"}, "a black artifact spell")
    # A quantifier this row does not implement. "no creature spell" and "two or
    # more" are different conditions, and reading either as presence lifts the
    # restriction on a turn the card does not name.
    assert cast_opponent_cast_line(
        "cast this spell only if an opponent cast two creature spells this turn"
    ) is None

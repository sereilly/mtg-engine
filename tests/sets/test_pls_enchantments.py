"""Planeshift enchantments.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: damage and the odd ones ---
#
# Lashknife Barrier's second line — "If a source would deal damage to a creature
# you control, it deals that much damage minus 1 to that creature instead." —
# is Benevolent Unicorn's sentence with both ends changed, and it arrived
# *supported* with that line unclaimed: the card compiled on its draw trigger
# alone. The source class and the protected recipients are parameters of the
# one CR 614 interceptor (``replacements._read_damage_delta``), never a second
# one.

from engine import Game as _w1g8e_Game, PlayerState as _w1g8e_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8e_load,  # noqa: E402
                                manifest_set_path as _w1g8e_path)
from engine.control import change_control as _w1g8e_change_control  # noqa: E402
from engine.models import (CardDefinition as _w1g8e_Card,  # noqa: E402
                           Permanent as _w1g8e_Permanent)
from engine.oracle import compile_card_oracle as _w1g8e_compile  # noqa: E402
from engine.replacements import (  # noqa: E402
    damage_delta_recipients as _w1g8e_delta_recipients,
    replacement_claims_line as _w1g8e_claims,
    source_damage_delta as _w1g8e_delta,
)

from tests.helpers import (_damage_dealt as _w1g8e_dealt,  # noqa: E402
                           resolve_stack as _w1g8e_resolve_stack)


def _w1g8e_lea():
    return {card.name: card for card in _w1g8e_load(_w1g8e_path("LEA"))}


def _w1g8e_body(name, power, toughness, text="", keywords=()):
    """A bare creature for the other side of a damage event."""
    return _w1g8e_Card(
        name=name, mana_cost="{3}", cmc=3.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )  # W1G8 enchantments: a test body


def _w1g8e_duel(mine, theirs, *, hand0=(), hand1=(), active=0):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_w1g8e_Permanent(card=card) for card in mine]
    board1 = [_w1g8e_Permanent(card=card) for card in theirs]
    filler = _w1g8e_body("Filler", 0, 1)
    game = _w1g8e_Game(players=[
        _w1g8e_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10),
        _w1g8e_Player(name="P1", battlefield=board1, hand=list(hand1),
                      library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G8 enchantments: the duel


def _w1g8e_fight(game, attacker_slot, blocker_slot, *, defender):
    """The active seat attacks with one creature, *defender* blocks it, and
    combat runs through to the second main phase."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(game.active_player_index, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocked = game.declare_blockers(defender, {blocker_slot: attacker_slot})
    assert blocked[0], blocked
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g8e_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G8: fought


def test_w1g8_lashknife_barrier_claims_both_of_its_lines(set_pool):
    """The card was "supported" on the draw trigger with the replacement line
    read by nothing. Both readers of the sentence now answer for it, and the
    narrowing is read rather than dropped."""
    barrier = set_pool("PLS")["Lashknife Barrier"]
    line = barrier.oracle_text.splitlines()[1]

    assert _w1g8e_compile(barrier).supported
    assert _w1g8e_claims(line)
    assert _w1g8e_delta(line) == ("source", -1)
    assert _w1g8e_delta_recipients(line) == {
        "type_filter": "creature", "controller": "you",
    }
    # the unnarrowed printing names every recipient, so it carries no phrase
    assert _w1g8e_delta_recipients(
        "If a spell would deal damage to a permanent or player, it deals that "
        "much damage minus 1 to that permanent or player instead."
    ) is None
    # the two halves must name the same thing: a creature you control in front
    # and "that permanent or player" behind is not this sentence
    assert _w1g8e_delta(
        "If a source would deal damage to a creature you control, it deals "
        "that much damage minus 1 to that permanent or player instead."
    ) is None
    assert not _w1g8e_claims(
        "If a source would deal damage to a creature you control, it deals "
        "that much damage minus 1 to that permanent or player instead."
    )


def test_w1g8_lashknife_barrier_draws_on_entering(set_pool):
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, _, _ = _w1g8e_duel([], [], hand0=[barrier])

    cast = game.cast_from_hand(0, "Lashknife Barrier")
    assert cast.supported, cast.details
    _w1g8e_resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(0)] == ["Lashknife Barrier"]
    assert len(game.players[0].hand) == 1, "the entry trigger drew a card"


def test_w1g8_lashknife_barrier_shaves_a_burn_spell_aimed_at_its_creature(set_pool):
    """Three becomes two on the Barrier's controller's creature — and stays
    three on that player's face and on the other side's creature, because the
    sentence names "a creature you control" and nothing wider."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"]], [lea["Hill Giant"]],
        hand1=[lea["Lightning Bolt"]] * 2, hand0=[lea["Lightning Bolt"]],
        active=1,
    )
    giant = mine[1]

    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[giant.permanent_id]
    ).supported
    _w1g8e_resolve_stack(game)
    game._settle()
    assert giant.damage_marked == 2
    assert game.is_on_battlefield(giant), "3 minus 1 does not kill a 3/3"

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g8e_resolve_stack(game)
    assert game.players[0].life == 17, "a player is not a creature you control"

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[theirs[0].permanent_id]
    ).supported
    _w1g8e_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(theirs[0]), (
        "the opponent's creature takes the printed three"
    )


def test_w1g8_lashknife_barrier_shaves_combat_damage(set_pool):
    """"A source" is every source: a 3/3 blocked by the Barrier's 3/3 deals it
    two and dies to the three it takes back."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"]], [lea["Hill Giant"]], active=1,
    )

    _w1g8e_fight(game, 0, 1, defender=0)

    assert game.is_on_battlefield(mine[1])
    assert mine[1].damage_marked == 2
    assert not game.is_on_battlefield(theirs[0])


def test_w1g8_one_damage_reduced_to_none_is_not_dealt(set_pool):
    """CR 120.8: a source that would deal 0 damage deals none at all. The
    event's *dealt* number is 0, which is what lifelink gains from and what a
    "deals damage" trigger sees — a shield would have prevented 1 of 1 and
    still announced an event."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"], lea["Prodigal Sorcerer"]],
        [lea["Prodigal Sorcerer"]], active=1,
    )
    giant = mine[1]

    # the opponent's pinger, and then the Barrier's controller's own
    for seat in (1, 0):
        used = game.activate_permanent_ability(
            seat, "Prodigal Sorcerer",
            target_permanent_ids=[giant.permanent_id], ability_index=0,
        )
        assert used.supported, used.details
        _w1g8e_resolve_stack(game)
    assert giant.damage_marked == 0
    assert _w1g8e_dealt(game, giant, 1, source=theirs[0]) == 0
    assert _w1g8e_dealt(game, giant, 1, source=theirs[0], combat=True) == 0


def test_w1g8_two_lashknife_barriers_each_take_a_point(set_pool):
    """CR 616.1 applies them one at a time in an order the creature's
    controller picks; subtraction commutes and the floor is reached only from
    above, so either order is minus 2 and never less than nothing."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, _ = _w1g8e_duel([barrier, barrier, lea["Hill Giant"]], [])
    giant = mine[2]

    assert _w1g8e_dealt(game, giant, 3) == 1
    assert _w1g8e_dealt(game, giant, 2) == 0
    assert _w1g8e_dealt(game, giant, 1) == 0


def test_w1g8_lashknife_barrier_is_per_recipient_and_per_controller(set_pool):
    """A mass damage event is one event per recipient (Earthquake for 2): each
    of the Barrier's side's creatures takes 1, the other side's take 2 and
    both players take 2. And "you control" is the Barrier's controller *now*
    (CR 109.5) — a creature that changes hands changes cover with it."""
    lea = _w1g8e_lea()
    barrier = set_pool("PLS")["Lashknife Barrier"]
    game, mine, theirs = _w1g8e_duel(
        [barrier, lea["Hill Giant"], lea["Hill Giant"]], [lea["Hill Giant"]],
        hand0=[lea["Earthquake"]],
    )

    cast = game.cast_from_hand(0, "Earthquake", x_value=2)
    assert cast.supported, cast.details
    _w1g8e_resolve_stack(game)

    assert [perm.damage_marked for perm in mine[1:]] == [1, 1]
    assert theirs[0].damage_marked == 2
    assert [player.life for player in game.players] == [18, 18]

    stolen = theirs[0]
    assert _w1g8e_dealt(game, stolen, 3) == 3
    _w1g8e_change_control(stolen, 0, source="test")
    game._sync_control()
    assert _w1g8e_dealt(game, stolen, 3) == 2
    _w1g8e_change_control(mine[1], 1, source="test")
    game._sync_control()
    assert _w1g8e_dealt(game, mine[1], 3) == 3


# W1G8, supported on arrival and driven: Deadapult.


def test_w1g8_deadapult_needs_a_zombie_of_its_controllers(set_pool):
    """"{R}, Sacrifice a Zombie: This enchantment deals 2 damage to any
    target." The cost is a *Zombie* and the payer's own: with none, or with
    only the opponent's, the ability is refused and nothing is sacrificed —
    and a creature that is not a Zombie is never taken in its place."""
    lea = _w1g8e_lea()
    deadapult = set_pool("PLS")["Deadapult"]
    game, mine, theirs = _w1g8e_duel(
        [deadapult, lea["Grizzly Bears"]], [lea["Scathe Zombies"]],
    )

    for cost in ([mine[1].permanent_id], [theirs[0].permanent_id], None):
        refused = game.activate_permanent_ability(
            0, "Deadapult", ability_index=0, target_player_index=1,
            cost_permanent_ids=cost,
        )
        assert not refused.supported, cost
    assert game.is_on_battlefield(mine[1]) and game.is_on_battlefield(theirs[0])
    assert game.players[1].life == 20

    game, mine, theirs = _w1g8e_duel(
        [deadapult, lea["Grizzly Bears"], lea["Scathe Zombies"]],
        [lea["Hill Giant"]],
    )
    used = game.activate_permanent_ability(
        0, "Deadapult", ability_index=0,
        target_permanent_ids=[theirs[0].permanent_id],
        cost_permanent_ids=[mine[2].permanent_id],
    )
    assert used.supported, used.details
    _w1g8e_resolve_stack(game)
    assert theirs[0].damage_marked == 2
    assert [perm.card.name for perm in game.controlled_by(0)] == [
        "Deadapult", "Grizzly Bears",
    ]
    assert [card.name for card in game.players[0].graveyard] == ["Scathe Zombies"]


# --- W1G5: lands and mana ---
import pytest as _w1g5_pytest

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.ai_simulator import run_ai_simulation as _w1g5_run_ai_simulation
from engine.card_loader import manifest_set_path as _w1g5_manifest_set_path
from engine.land_animation import land_animation_for as _w1g5_land_animation_for
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import _mk_card as _w1g5_mk_card


def _w1g5_emergence_table(set_pool, *, mine=(), theirs=(), interactive=()):
    """Seat 0's main phase with *mine*/*theirs* already on the battlefield and
    Natural Emergence in seat 0's hand. Names resolve in Planeshift, then
    Alpha. Costs are off: what the enchantment does is the question."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[pls["Natural Emergence"]],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g5_emergence_table


def _w1g5_emergence_resolved(set_pool, returning: str, **board):
    """Cast Natural Emergence for an interactive seat 0 and return the
    enchantment named *returning* to its owner's hand; the game."""
    game = _w1g5_emergence_table(set_pool, interactive={0}, **board)
    assert game.cast_from_hand(0, "Natural Emergence").supported
    game.resolve_top_of_stack()
    (chosen,) = [p for p in game.controlled_by(0) if p.card.name == returning]
    assert game.confirm_permanent_set_choice(0, [chosen.permanent_id])
    assert not game.pending_choices
    return game  # _w1g5_emergence_resolved


def _w1g5_shape(game, seat: int) -> dict[str, tuple]:
    """Each of *seat*'s permanents as ``(is a creature, power, toughness,
    has first strike, is a land)``, by name."""
    return {
        p.card.name: (
            p.is_creature, p.effective_power, p.effective_toughness,
            game._has_keyword(p, "first strike"), p.has_type("land"),
        )
        for p in game.controlled_by(seat)
    }  # _w1g5_shape


def test_w1g5_natural_emergence_returns_a_red_or_green_enchantment(set_pool):
    """"When this enchantment enters, return a red or green enchantment you
    control to its owner's hand." The seat is asked, and the choices are its
    own red or green enchantments — Natural Emergence itself among them (it is
    both), a blue one and an opponent's green one not. Returning Fastbond
    leaves the Emergence in play; nothing is returned without an answer."""
    game = _w1g5_emergence_table(
        set_pool, mine=["Fastbond", "Flight"], theirs=["Fastbond"], interactive={0},
    )
    assert game.cast_from_hand(0, "Natural Emergence").supported
    game.resolve_top_of_stack()

    pick = game.pending_choice_of("permanent_set_choice", 0)
    assert pick is not None
    assert sorted(p.card.name for p in game.live_permanent_set_choices(pick)) == [
        "Fastbond", "Natural Emergence",
    ]
    (flight,) = [p for p in game.controlled_by(0) if p.card.name == "Flight"]
    (theirs,) = list(game.controlled_by(1))
    assert not game.confirm_permanent_set_choice(0, [flight.permanent_id])
    assert not game.confirm_permanent_set_choice(0, [theirs.permanent_id])
    assert not game.confirm_permanent_set_choice(0, [])
    (fastbond,) = [p for p in game.controlled_by(0) if p.card.name == "Fastbond"]
    assert game.confirm_permanent_set_choice(0, [fastbond.permanent_id])

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Flight", "Natural Emergence",
    ]
    assert [card.name for card in game.players[0].hand] == ["Fastbond"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Fastbond"]


def test_w1g5_natural_emergence_may_return_itself(set_pool):
    """With no other red or green enchantment it is its own only choice: it
    goes back to hand, and the lands it would have animated are plain lands."""
    game = _w1g5_emergence_table(set_pool, mine=["Forest"], interactive={0})
    game.cast_from_hand(0, "Natural Emergence")
    game.resolve_top_of_stack()
    (emergence,) = [p for p in game.controlled_by(0) if p.card.name == "Natural Emergence"]
    assert _w1g5_shape(game, 0)["Forest"][:2] == (True, 2), "animated while it is in play"
    assert game.confirm_permanent_set_choice(0, [emergence.permanent_id])

    assert [card.name for card in game.players[0].hand] == ["Natural Emergence"]
    assert _w1g5_shape(game, 0) == {"Forest": (False, 0, 0, False, True)}


def test_w1g5_natural_emergence_animates_your_lands_and_only_yours(set_pool):
    """"Lands you control are 2/2 creatures with first strike. They're still
    lands." Three things the animation table could not say before: whose
    lands (an opponent's Island is untouched), a keyword (first strike, layer
    6), and the two-sentence spelling. A land that enters later is animated
    too (CR 611.3a — a static ability is not locked in), a non-land is not,
    and everything reverts when the enchantment leaves (CR 611.3b)."""
    game = _w1g5_emergence_resolved(
        set_pool, "Fastbond",
        mine=["Forest", "Mountain", "Fastbond", "Sol Ring"], theirs=["Island"],
    )
    mine = _w1g5_shape(game, 0)
    assert mine["Forest"] == mine["Mountain"] == (True, 2, 2, True, True)
    assert mine["Sol Ring"] == mine["Natural Emergence"] == (False, 0, 0, False, False)
    assert _w1g5_shape(game, 1) == {"Island": (False, 0, 0, False, True)}

    game._put_permanent_onto_battlefield(
        0, _W1G5Permanent(card=set_pool("LEA")["Swamp"]), None
    )
    assert _w1g5_shape(game, 0)["Swamp"] == (True, 2, 2, True, True)

    (emergence,) = [p for p in game.controlled_by(0) if p.card.name == "Natural Emergence"]
    game.remove_from_battlefield(emergence)
    game._recompute_continuous_effects()
    assert set(_w1g5_shape(game, 0).values()) == {
        (False, 0, 0, False, True), (False, 0, 0, False, False),
    }


def test_w1g5_natural_emergence_follows_its_controller(set_pool):
    """"You control" is the controller of the *source*, through the control
    seam on both sides (CR 109.5): when an opponent takes the enchantment, the
    lands it animates are theirs and the first player's go back to being
    lands."""
    from engine.control import change_control

    game = _w1g5_emergence_resolved(
        set_pool, "Fastbond", mine=["Forest", "Fastbond"], theirs=["Island"],
    )
    (emergence,) = [p for p in game.controlled_by(0) if p.card.name == "Natural Emergence"]
    change_control(emergence, 1, source="w1g5-test")
    game._sync_control()
    game._recompute_continuous_effects()

    assert _w1g5_shape(game, 0) == {"Forest": (False, 0, 0, False, True)}
    assert _w1g5_shape(game, 1)["Island"] == (True, 2, 2, True, True)


def test_w1g5_an_animated_land_strikes_first(set_pool):
    """The keyword is real in combat: an animated Forest, 2/2 with first
    strike, attacks into a Grizzly Bears. The Bears die in the first-strike
    damage step and deal nothing back (CR 510.4), and the Forest is still a
    land that taps for {G} afterwards."""
    game = _w1g5_emergence_resolved(
        set_pool, "Fastbond", mine=["Forest", "Fastbond"], theirs=["Grizzly Bears"],
    )
    (forest,) = [p for p in game.controlled_by(0) if p.card.name == "Forest"]
    (bears,) = list(game.controlled_by(1))

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(forest)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    game.declare_blockers(
        1, {game.battlefield_index_of(bears): game.battlefield_index_of(forest)}
    )
    game.advance_combat_phase()

    assert [p.card.name for p in game.controlled_by(1)] == []
    assert forest in list(game.controlled_by(0))
    assert forest.damage_marked == 0, "the Bears never dealt their damage"


def test_w1g5_the_animation_table_reads_every_printed_word(set_pool):
    """The derivation table is anchored at both ends and each optional word is
    a field: the controller, the keyword list, either spelling of the "still
    lands" clause. A keyword the engine does not implement, or a tail the
    template does not print, refuses the line rather than animating the lands
    and dropping a word — and the four animators that shipped before
    Planeshift read exactly as they did."""
    emergence = _w1g5_land_animation_for(
        "lands you control are 2/2 creatures with first strike. they're still lands"
    )
    assert (emergence.controller, emergence.keywords) == ("you", ("first strike",))
    assert (emergence.land_type, emergence.power, emergence.toughness) == (None, 2, 2)

    typed = _w1g5_land_animation_for(
        "forests you control are 1/1 creatures with flying and trample that are still lands"
    )
    assert (typed.land_type, typed.controller) == ("forest", "you")
    assert typed.keywords == ("flying", "trample")

    plain = _w1g5_land_animation_for("all lands are 2/2 creatures that are still lands")
    assert (plain.controller, plain.keywords) == (None, ())

    for refused in (
        "lands you control are 2/2 creatures with gravestorm. they're still lands",
        "lands you control are 2/2 creatures with first strike",
        "lands you control are 2/2 creatures with first strike. they're still lands. draw a card",
        "lands an opponent controls are 2/2 creatures that are still lands",
    ):
        assert _w1g5_land_animation_for(refused) is None, refused

    invented = _w1g5_mk_card(
        name="Verdant Uprising", type_line="Enchantment",
        oracle_text="Forests you control are 1/1 creatures with trample that are still lands.",
    )
    (instruction,) = _w1g5_compile(invented).instructions
    assert instruction.kind == "animate_all_lands"
    assert instruction.payload == {
        "power": 1, "toughness": 1, "land_type": "forest",
        "controller": "you", "keywords": ["trample"],
    }
    game = _w1g5_emergence_table(set_pool, mine=["Forest", "Mountain"], theirs=["Forest"])
    game._put_permanent_onto_battlefield(0, _W1G5Permanent(card=invented), None)
    assert _w1g5_shape(game, 0)["Forest"][:3] == (True, 1, 1)
    assert game._has_keyword(
        next(p for p in game.controlled_by(0) if p.card.name == "Forest"), "trample"
    )
    assert _w1g5_shape(game, 0)["Mountain"][0] is False
    assert _w1g5_shape(game, 1)["Forest"][0] is False


def test_w1g5_multanis_harmony_gives_its_creature_a_mana_ability(set_pool):
    """'Enchanted creature has "{T}: Add one mana of any color."' Supported on
    arrival and never run. The creature — not the Aura — taps for the colour
    named, as a mana ability (no stack), and the ability is gone with the
    Aura (CR 611.3b)."""
    from engine.targeting import usable_activated_abilities

    pls, lea = set_pool("PLS"), set_pool("LEA")
    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=lea["Grizzly Bears"])],
        hand=[pls["Multani's Harmony"]],
    )
    game = _W1G5Game(players=[me, _W1G5PlayerState(name="W1G5-B")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    (bears,) = list(game.controlled_by(0))
    bears.metadata["summoning_sickness_turn"] = -99

    def granted():
        return [
            ability.source_line.lower() for ability in usable_activated_abilities(
                _w1g5_compile(game.playable_card_of(bears))
            )
        ]

    assert granted() == []
    assert game.cast_from_hand(
        0, "Multani's Harmony", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert granted() == ["{t}: add one mana of any color."]

    result = game.activate_permanent_ability(
        0, "Grizzly Bears",
        permanent_index=game.battlefield_index_of(bears), mana_color="U",
    )
    assert result.supported and bears.tapped and not game.stack
    assert {s: n for s, n in me.mana_pool.items() if n} == {"U": 1}

    (harmony,) = [p for p in game.controlled_by(0) if p.card.name == "Multani's Harmony"]
    game._remove_aura_effects(harmony)
    game.remove_from_battlefield(harmony)
    game._recompute_continuous_effects()
    assert granted() == []


@_w1g5_pytest.mark.slow
def test_w1g5_emergence_blessing_and_compass_in_simulated_games(set_pool):
    """Whole games with this group's three spells pinned into both decks —
    Natural Emergence, Skyshroud Blessing (an instant) and Star Compass (an
    artifact) — because a card can compile and do nothing in a turn structure.
    Each is cast and resolves, the Emergence's entry trigger is answered in
    the step that owes it (`steps_left_owing`), the Blessing's lands gain
    shroud, and nothing any of the three does is an issue or a refused cast.

    The floors are one apiece on purpose: the seed's trajectory moves whenever
    another card in the set changes, and this asks that the cards were *seen*,
    not how often. (Today: fifteen, four and seven casts.)
    """
    names = ["Natural Emergence", "Skyshroud Blessing", "Star Compass"]
    report = _w1g5_run_ai_simulation(
        _w1g5_manifest_set_path("PLS", include_measured=True),
        games=6, seed=11, max_turns=20, required_cards=names,
    )
    log = report.log_lines

    assert report.games_completed == 6
    assert report.steps_left_owing == {}, dict(report.steps_left_owing)
    for name in names:
        assert sum(f"cast {name} -> resolved" in line for line in log) >= 1, name
        assert not [i.message for i in report.issues if name in i.message], name
        assert not [why for why in report.refused_casts if name in why], name
    assert sum("Natural Emergence returned" in line for line in log) >= 1
    assert sum("gain shroud until end of turn" in line for line in log) >= 1


# --- W1G3: revealed cards ---
# "{3}{C}: Target opponent reveals a card at random from their hand. <something
# sized by that card's mana value>." The reveal shipped with Wand of Ith; what
# the Planeswalker's cycle adds is a later sentence *reading* what it showed —
# "that card's mana value" (a record the reveal step freezes, CR 608.2h) and
# "the revealed card's mana value" (the where-clause spelling of the same
# card). An empty hand reveals nothing and CR 107.2 makes the number 0.
import random as _w1g3_random

from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from engine.oracle import compile_card_oracle as _w1g3_compile
from engine.targeting import derive_activation_spec as _w1g3_activation_spec
from engine.targeting import spec_roles as _w1g3_spec_roles
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_cycle_board(set_pool, name, held, *, mine=(), theirs=(), seats=2, active=0):
    """Seat 0 controls the Planeswalker's enchantment *name*; seat 1 holds
    *held*. Names are read from PLS, then M21, then LEA. Every seat is
    interactive, so ``queue_permanent_ability`` leaves the ability on the
    stack. Returns ``(game, players, card lookup)``."""
    pools = [set_pool(code) for code in ("PLS", "M21", "LEA")]

    def w1g3_card(card_name):
        return next(pool[card_name] for pool in pools if card_name in pool)

    w1g3_players = [
        _W1G3PlayerState(
            name="A",
            battlefield=[_W1G3Permanent(card=w1g3_card(n)) for n in (name, *mine)],
        ),
        _W1G3PlayerState(
            name="B", hand=[w1g3_card(n) for n in held],
            battlefield=[_W1G3Permanent(card=w1g3_card(n)) for n in theirs],
        ),
    ]
    w1g3_players.extend(
        _W1G3PlayerState(name="CDE"[index - 2]) for index in range(2, seats)
    )
    for w1g3_player in w1g3_players:
        w1g3_player.library.extend([w1g3_card("Forest")] * 6)
    w1g3_game = _W1G3Game(players=w1g3_players)
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = set(range(seats))
    w1g3_game.start_turn(active)
    w1g3_game._sync_control()
    return w1g3_game, w1g3_players, w1g3_card  # _w1g3_cycle_board


def _w1g3_two_targets(game, seat, permanent):
    """The role refs Favor and Scorn announce: the opponent, then the creature."""
    return [{"seat": seat}, {"permanent_id": game.permanent_id_of(permanent)}]  # _w1g3_two_targets


def test_w1g3_planeswalkers_mirth_gains_the_revealed_cards_mana_value(set_pool):
    """"You gain life equal to that card's mana value." Shivan Dragon is the
    only card in the hand, so the reveal is of a six-drop and the gain is 6 —
    and the card stays in the hand it was revealed from (CR 701.20a: a reveal
    shows a card, it does not move one)."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", ["Shivan Dragon"]
    )

    result = game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert players[0].life == 26 and players[1].life == 20, game.log[-4:]
    assert [card.name for card in players[1].hand] == ["Shivan Dragon"]
    assert any("B reveals Shivan Dragon at random" in line for line in game.log)


def test_w1g3_planeswalkers_mirth_reveals_at_random(set_pool):
    """One card of the hand, chosen by nobody: over thirty seeds a hand of a
    six-drop, a two-drop and a land gains each of 6, 2 and 0 at least once,
    and never anything else."""
    gained = set()
    for seed in range(30):
        _w1g3_random.seed(seed)
        game, players, _card = _w1g3_cycle_board(
            set_pool, "Planeswalker's Mirth", ["Shivan Dragon", "Counterspell", "Forest"]
        )
        game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
        _w1g3_resolve_stack(game)
        gained.add(players[0].life - 20)

    assert gained == {0, 2, 6}


def test_w1g3_planeswalkers_mirth_gains_nothing_from_an_empty_hand(set_pool):
    """CR 107.2: a number that cannot be determined is 0. No life is gained —
    and no life-*gain event* happens, so Vito's "whenever you gain life" does
    not trigger. With a card to reveal, the same board drains for 6."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", [], mine=["Vito, Thorn of the Dusk Rose"]
    )
    game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert (players[0].life, players[1].life) == (20, 20), game.log[-4:]
    assert not any("gained" in line for line in game.log), game.log[-4:]

    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", ["Shivan Dragon"],
        mine=["Vito, Thorn of the Dusk Rose"],
    )
    game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert (players[0].life, players[1].life) == (26, 14), game.log[-5:]


def test_w1g3_planeswalkers_mirth_names_an_opponent_at_instant_speed(set_pool):
    """"Target **opponent**": the activator's own seat is refused with nothing
    resolved. And Mirth prints no "Activate only as a sorcery", so it is
    activated on the opponent's turn."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mirth", ["Shivan Dragon"], active=1
    )
    ability = _w1g3_compile(set_pool("PLS")["Planeswalker's Mirth"]).activated_abilities[0]
    assert _w1g3_activation_spec(ability) == {"kind": "player", "opponents_only": True}

    refused = game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=0)
    assert not refused.supported and not game.stack, refused.details

    allowed = game.queue_permanent_ability(0, "Planeswalker's Mirth", target_player_index=1)
    _w1g3_resolve_stack(game)
    assert allowed.supported and players[0].life == 26, game.log[-4:]


def test_w1g3_planeswalkers_fury_burns_the_opponent_who_revealed(set_pool):
    """"This enchantment deals damage equal to that card's mana value to that
    player." Three seats, the far one named: C reveals a Counterspell and C
    takes 2 — not B, the first opponent, whose hand holds a six-drop."""
    game, players, card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Fury", ["Shivan Dragon"], seats=3
    )
    players[2].hand.append(card("Counterspell"))

    result = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=2)
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert [player.life for player in players] == [20, 20, 18], game.log[-4:]
    assert any("Planeswalker's Fury dealt 2 damage to C" in line for line in game.log)


def test_w1g3_planeswalkers_fury_deals_nothing_for_an_empty_hand(set_pool):
    """CR 107.2 again: no card, no number, no damage — and no damage event in
    the log either."""
    game, players, _card = _w1g3_cycle_board(set_pool, "Planeswalker's Fury", [])

    result = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert players[1].life == 20
    assert not any("dealt" in line for line in game.log), game.log[-4:]


def test_w1g3_planeswalkers_fury_is_activated_only_as_a_sorcery(set_pool):
    """"Activate only as a sorcery." Refused on the opponent's turn, and
    refused on its controller's own main phase while the stack holds anything
    — here its own first activation."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Fury", ["Shivan Dragon"], active=1
    )
    refused = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    assert not refused.supported and "sorcery" in refused.details, refused.details
    assert players[1].life == 20 and not game.stack

    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Fury", ["Shivan Dragon"]
    )
    first = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    second = game.queue_permanent_ability(0, "Planeswalker's Fury", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert first.supported and not second.supported, second.details
    assert players[1].life == 14, "one activation, one six-drop"


def test_w1g3_planeswalkers_favor_pumps_by_the_revealed_cards_mana_value(set_pool):
    """"Target creature gets +X/+X until end of turn, where X is the revealed
    card's mana value." Two targets on one ability — the opponent who reveals
    and the creature that grows — and the picker is offered both, in the order
    the sentence prints them."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"], mine=["Grizzly Bears"]
    )
    bear = players[0].battlefield[1]
    ability = _w1g3_compile(set_pool("PLS")["Planeswalker's Favor"]).activated_abilities[0]
    roles = _w1g3_spec_roles(_w1g3_activation_spec(ability))
    assert [role["role"] for role in roles] == ["player", "creature"]
    assert roles[0]["opponents_only"] is True

    result = game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert (bear.effective_power, bear.effective_toughness) == (8, 8), game.log[-4:]


def test_w1g3_planeswalkers_favor_refuses_a_target_its_line_does_not_print(set_pool):
    """The announcement is held to both printed phrases: the activator is not
    their own opponent, and an enchantment is not a creature."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"], mine=["Grizzly Bears"]
    )
    favor, bear = players[0].battlefield

    own_seat = game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 0, bear)
    )
    not_a_creature = game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, favor)
    )

    assert not own_seat.supported and not not_a_creature.supported
    assert not game.stack


def test_w1g3_planeswalkers_favor_reads_each_activations_own_reveal(set_pool):
    """Two activations in one turn, at instant speed on the opponent's turn
    (Favor prints no sorcery clause): the second reads the card *it* revealed
    — a two-drop — rather than the six the first one froze. 2/2 + 6 + 2."""
    game, players, card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"],
        mine=["Grizzly Bears"], active=1,
    )
    bear = players[0].battlefield[1]

    game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)
    players[1].hand[:] = [card("Counterspell")]
    game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)

    assert (bear.effective_power, bear.effective_toughness) == (10, 10), game.log[-6:]


def test_w1g3_planeswalkers_favor_still_reveals_when_its_creature_has_gone(set_pool):
    """CR 608.2b, per target: the creature left in response, so that target is
    illegal and nothing is pumped — but the opponent is still a legal target,
    so the ability resolves and the card is still revealed."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Favor", ["Shivan Dragon"], mine=["Grizzly Bears"]
    )
    bear = players[0].battlefield[1]
    game.queue_permanent_ability(
        0, "Planeswalker's Favor", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )

    game.remove_from_battlefield(bear)
    _w1g3_resolve_stack(game)

    assert any("B reveals Shivan Dragon at random" in line for line in game.log)
    assert not any("gives Grizzly Bears" in line for line in game.log), game.log[-4:]


def test_w1g3_planeswalkers_scorn_shrinks_by_the_revealed_cards_mana_value(set_pool):
    """"Target creature gets -X/-X until end of turn": a six-drop revealed, so
    the 2/2 is a 2/2 with -6/-6 and dies to CR 704.5f."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Scorn", ["Shivan Dragon"], theirs=["Grizzly Bears"]
    )
    bear = players[1].battlefield[0]

    result = game.queue_permanent_ability(
        0, "Planeswalker's Scorn", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )
    _w1g3_resolve_stack(game)
    game._settle()

    assert result.supported, result.details
    assert not players[1].battlefield, game.log[-4:]
    assert [card.name for card in players[1].graveyard] == ["Grizzly Bears"]


def test_w1g3_planeswalkers_scorn_does_nothing_when_the_hand_is_emptied_in_response(set_pool):
    """The hand is read when the ability *resolves*: emptied in response, no
    card is revealed, X is 0 (CR 107.2) and the creature lives."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Scorn", ["Shivan Dragon"], theirs=["Grizzly Bears"]
    )
    bear = players[1].battlefield[0]
    game.queue_permanent_ability(
        0, "Planeswalker's Scorn", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )

    players[1].hand.clear()
    _w1g3_resolve_stack(game)
    game._settle()

    assert [perm.card.name for perm in players[1].battlefield] == ["Grizzly Bears"]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_w1g3_planeswalkers_scorn_is_activated_only_as_a_sorcery(set_pool):
    """Scorn prints the clause Favor does not: refused on the opponent's turn
    with the creature untouched."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Scorn", ["Shivan Dragon"],
        theirs=["Grizzly Bears"], active=1,
    )
    bear = players[1].battlefield[0]

    refused = game.queue_permanent_ability(
        0, "Planeswalker's Scorn", target_role_refs=_w1g3_two_targets(game, 1, bear)
    )

    assert not refused.supported and "sorcery" in refused.details, refused.details
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def _w1g3_activate_mischief(set_pool, held, **board):
    """Planeswalker's Mischief, activated at seat 1 and resolved. Returns the
    game and both players."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mischief", held, **board
    )
    result = game.queue_permanent_ability(
        0, "Planeswalker's Mischief", target_player_index=1
    )
    assert result.supported, result.details
    _w1g3_resolve_stack(game)
    return game, players[0], players[1]  # _w1g3_activate_mischief


def test_w1g3_planeswalkers_mischief_exiles_a_revealed_instant_and_lends_it(set_pool):
    """"If it's an instant or sorcery card, exile it. You may cast it without
    paying its mana cost for as long as it remains exiled." The card goes to
    its *owner's* exile (CR 400.3) and the permission to the enchantment's
    controller — never to the card's owner — and "it" is the revealed card:
    the enchantment itself stays where it is."""
    game, mine, theirs = _w1g3_activate_mischief(set_pool, ["Lightning Bolt"])

    assert not theirs.hand and not mine.exile
    assert [card.name for card in theirs.exile] == ["Lightning Bolt"]
    assert [perm.card.name for perm in mine.battlefield] == ["Planeswalker's Mischief"]
    (grant,) = game.cast_permissions
    assert (grant.player_index, grant.zone_seat) == (0, 1)
    assert (grant.mode, grant.free, grant.duration) == ("cast", True, "while_exiled")
    refused = game.queue_from_hand(1, "Lightning Bolt", from_zone="exile")
    assert not refused.supported, "the owner was given nothing"


def test_w1g3_planeswalkers_mischief_casts_the_card_for_free_into_its_owners_graveyard(set_pool):
    """CR 118.9: cast with costs enforced and not one land in play. The Bolt
    resolves, lands in its **owner's** graveyard, the one-card grant is spent,
    and the end step then has nothing to return."""
    game, mine, theirs = _w1g3_activate_mischief(set_pool, ["Lightning Bolt"])
    game.enforce_mana_costs = True

    cast = game.queue_from_hand(0, "Lightning Bolt", from_zone="exile", target_player_index=1)
    _w1g3_resolve_stack(game)

    assert cast.supported, cast.details
    assert theirs.life == 17
    assert [card.name for card in theirs.graveyard] == ["Lightning Bolt"]
    assert not theirs.exile and not mine.graveyard and not game.cast_permissions

    game.resolve_end_step(0)
    _w1g3_resolve_stack(game)
    assert not theirs.hand, "if you haven't cast it"
    assert [card.name for card in theirs.graveyard] == ["Lightning Bolt"]


def test_w1g3_planeswalkers_mischief_returns_an_uncast_card_at_the_end_step(set_pool):
    """"At the beginning of the next end step, if you haven't cast it, return
    it to its owner's hand." Back in the opponent's hand — and the permission
    ends with the card's stay in exile (CR 611.2b), so nothing is left that a
    later exile of the same card could wake up."""
    game, mine, theirs = _w1g3_activate_mischief(set_pool, ["Lightning Bolt"])
    assert [trigger.event for trigger in game.delayed_triggers] == ["next_end_step"]

    game.resolve_end_step(0)
    _w1g3_resolve_stack(game)

    assert [card.name for card in theirs.hand] == ["Lightning Bolt"]
    assert not theirs.exile and not mine.hand
    assert not game.cast_permissions and not game.delayed_triggers
    assert any(
        line == "Lightning Bolt returned to its owner's hand from exile"
        for line in game.log
    ), game.log[-4:]


def test_w1g3_planeswalkers_mischief_leaves_a_creature_card_in_the_hand(set_pool):
    """"**If it's an instant or sorcery card**": a creature card is revealed
    and nothing else happens — nothing exiled, nothing permitted, and the end
    step returns nothing. An empty hand reveals nothing at all."""
    game, mine, theirs = _w1g3_activate_mischief(set_pool, ["Grizzly Bears"])

    assert [card.name for card in theirs.hand] == ["Grizzly Bears"]
    assert not theirs.exile and not game.cast_permissions
    assert any("B reveals Grizzly Bears at random" in line for line in game.log)
    game.resolve_end_step(0)
    _w1g3_resolve_stack(game)
    assert [card.name for card in theirs.hand] == ["Grizzly Bears"]

    game, mine, theirs = _w1g3_activate_mischief(set_pool, [])
    assert not theirs.exile and not game.cast_permissions
    assert [perm.card.name for perm in mine.battlefield] == ["Planeswalker's Mischief"]


def test_w1g3_planeswalkers_mischief_lends_a_sorcery_and_fixes_x_at_zero(set_pool):
    """A sorcery is exiled like an instant and cast in the same main phase. And
    CR 107.3b: a spell cast without paying its mana cost has X = 0, whatever
    the caster announces — a Fireball lent this way deals nothing."""
    game, mine, theirs = _w1g3_activate_mischief(set_pool, ["Wrath of God"])
    cast = game.queue_from_hand(0, "Wrath of God", from_zone="exile")
    _w1g3_resolve_stack(game)
    assert cast.supported, cast.details
    assert [card.name for card in theirs.graveyard] == ["Wrath of God"]

    game, mine, theirs = _w1g3_activate_mischief(set_pool, ["Fireball"])
    game.enforce_mana_costs = True
    cast = game.queue_from_hand(
        0, "Fireball", from_zone="exile", target_player_index=1, x_value=5
    )
    assert cast.supported, cast.details
    assert [item.x_value for item in game.stack] == [0]
    _w1g3_resolve_stack(game)
    assert theirs.life == 20


def test_w1g3_planeswalkers_mischief_is_activated_only_as_a_sorcery(set_pool):
    """The clause the cycle's blue member prints: refused on the opponent's
    turn with the hand untouched."""
    game, players, _card = _w1g3_cycle_board(
        set_pool, "Planeswalker's Mischief", ["Lightning Bolt"], active=1
    )

    refused = game.queue_permanent_ability(
        0, "Planeswalker's Mischief", target_player_index=1
    )

    assert not refused.supported and "sorcery" in refused.details, refused.details
    assert [card.name for card in players[1].hand] == ["Lightning Bolt"]
    assert not players[1].exile and not game.cast_permissions


def _w1g3_suspicious_upkeeps(set_pool, mine, theirs):
    """Dark Suspicions for seat 0, with *mine* / *theirs* cards in each hand,
    run through seat 0's upkeep and then seat 1's. Returns both pairs of life
    totals, ``(after A's upkeep, after B's upkeep)``."""
    game, players, card = _w1g3_cycle_board(set_pool, "Dark Suspicions", [])
    players[0].hand.extend([card("Forest")] * mine)
    players[1].hand.extend([card("Forest")] * theirs)
    game.resolve_upkeep(0)
    _w1g3_resolve_stack(game)
    after_own = (players[0].life, players[1].life)
    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w1g3_resolve_stack(game)
    return after_own, (players[0].life, players[1].life)  # _w1g3_suspicious_upkeeps


def test_w1g3_dark_suspicions_charges_the_opponent_the_difference_in_hands(set_pool):
    """"At the beginning of each **opponent's** upkeep, that player loses X
    life, where X is the number of cards in that player's hand minus the number
    of cards in your hand." Five against two is 3 — on the opponent's upkeep,
    to the opponent, and nothing on its controller's own."""
    after_own, after_theirs = _w1g3_suspicious_upkeeps(set_pool, 2, 5)

    assert after_own == (20, 20)
    assert after_theirs == (20, 17)


def test_w1g3_dark_suspicions_takes_nothing_from_the_smaller_hand(set_pool):
    """The subtraction stops at 0 (CR 107.1b): an opponent holding fewer cards
    than you loses nothing and gains nothing, and equal hands are 0."""
    assert _w1g3_suspicious_upkeeps(set_pool, 5, 2) == ((20, 20), (20, 20))
    assert _w1g3_suspicious_upkeeps(set_pool, 3, 3) == ((20, 20), (20, 20))


# --- W1G6: colour ---
# Being a colour (CR 613 layer 5) and what an Aura says about the colour of the
# creature it is on. Colour is read through the layers everywhere below
# (`Game._effective_colors`), never off the printed card.
import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    """*name* from Planeshift, else Invasion, else Alpha."""
    for code in ("PLS", "INV", "LEA"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(f"not in PLS, INV or LEA: {name}")  # _w1g6_card (enchantments)


def _w1g6_table(set_pool, mine=(), theirs=(), *, hand=(), mana=False, interactive=(0,)):
    """Seat 0 holds *mine* (and *hand* in hand), seat 1 *theirs*, nothing
    summoning-sick, on seat 0's turn. Returns the game and both boards."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = mana
    w1g6_game.interactive_seats = set(interactive)
    w1g6_game.active_player_index = 0
    w1g6_tables = []
    for seat, names in ((0, mine), (1, theirs)):
        placed = []
        for name in names:
            perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            placed.append(perm)
        w1g6_tables.append(placed)
    w1g6_game.players[0].hand.extend(_w1g6_card(set_pool, name) for name in hand)
    return w1g6_game, w1g6_tables[0], w1g6_tables[1]  # _w1g6_table (enchantments)


def _w1g6_colors(game, perm):
    return sorted(game._effective_colors(perm))  # _w1g6_colors (enchantments)


def _w1g6_recolor(game, perm, colour):
    """Turn *perm* *colour* until end of turn, through layer 5's turn-long
    channel — what "becomes black until end of turn" writes."""
    perm.metadata["color_override_until_eot"] = colour
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, perm) == [colour]
    return perm  # _w1g6_recolor


def _w1g6_enchant(game, set_pool, name, host, *, seat=0):
    """*seat* casts the Aura *name* on *host* through the real cast path and
    the stack is drained. Returns the Aura permanent."""
    game.players[seat].hand.append(_w1g6_card(set_pool, name))
    cast = game.queue_from_hand(seat, name, target_permanent_ids=[host.permanent_id])
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)
    return next(
        perm for perm in game.controlled_by(seat) if perm.card.name == name
    )  # _w1g6_enchant


def _w1g6_cast_sky(set_pool, mine, theirs, colour, *, interactive=(0,)):
    """Seat 0 casts Shifting Sky and (when asked) answers *colour*."""
    game, my_side, their_side = _w1g6_table(
        set_pool, mine, theirs, hand=["Shifting Sky"], interactive=interactive,
    )
    assert game.queue_from_hand(0, "Shifting Sky").supported
    game.resolve_top_of_stack()
    sky = next(p for p in game.controlled_by(0) if p.card.name == "Shifting Sky")
    if interactive:
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", 0)]
        assert game.confirm_enter_choice(0, mana_color=colour)
    return game, sky, my_side, their_side  # _w1g6_cast_sky


def test_w1g6_shifting_sky_makes_every_nonland_permanent_the_chosen_colour(set_pool):
    """"As this enchantment enters, choose a color. / All nonland permanents
    are the chosen color." Black is answered: every player's creatures, the
    colourless artifact, the white enchantment and the Sky itself are black —
    black *instead of* what they were (CR 105.3) — and no land is. When the Sky
    leaves, each is its printed colour again with nothing to undo."""
    assert _w1g6_compile(_w1g6_card(set_pool, "Shifting Sky")).supported
    game, sky, mine, theirs = _w1g6_cast_sky(
        set_pool, ["Island", "Grizzly Bears", "Howling Mine"],
        ["Hill Giant", "Mountain", "Crusade", "Savannah Lions"], "B",
    )
    island, bears, mine_artifact = mine
    giant, mountain, crusade, lions = theirs

    for perm in (bears, mine_artifact, sky, giant, crusade, lions):
        assert _w1g6_colors(game, perm) == ["B"], perm.card.name
    for land in (island, mountain):
        assert _w1g6_colors(game, land) == [], land.card.name

    game.remove_from_battlefield(sky)
    game._recompute_continuous_effects()
    assert [_w1g6_colors(game, p) for p in (bears, mine_artifact, giant, crusade, lions)] == [
        ["G"], [], ["R"], ["W"], ["W"],
    ]


def test_w1g6_shifting_skys_colour_is_what_every_other_card_reads(set_pool):
    """The colour is layer 5's, so everything that asks about colour sees it:
    under a black Sky Crusade's "white creatures get +1/+1" stops applying to
    the Lions and Terror ("nonblack") has no creature it may name; under a
    white one the red Giant is a white creature Crusade pumps."""
    game, _sky, _mine, theirs = _w1g6_cast_sky(
        set_pool, [], ["Hill Giant", "Crusade", "Savannah Lions"], "B",
    )
    giant, _crusade, lions = theirs
    assert (lions.effective_power, lions.effective_toughness) == (2, 1)
    game.players[0].hand.append(_w1g6_card(set_pool, "Terror"))
    refused = game.queue_from_hand(0, "Terror", target_permanent_ids=[giant.permanent_id])
    assert not refused.supported, refused.details

    game, _sky, _mine, theirs = _w1g6_cast_sky(
        set_pool, [], ["Hill Giant", "Crusade", "Savannah Lions"], "W",
    )
    giant, _crusade, lions = theirs
    assert (lions.effective_power, lions.effective_toughness) == (3, 2)
    assert (giant.effective_power, giant.effective_toughness) == (4, 4)


def test_w1g6_shifting_sky_follows_its_record_and_a_headless_seat_is_never_asked(set_pool):
    """Derived from the Sky's entry record on every recompute: a seat nobody
    asks takes the default with no prompt left owing and the board is that
    colour at once; a later answer recolours the board; and a permanent that
    enters afterwards is the chosen colour as soon as it is there."""
    game, sky, mine, theirs = _w1g6_cast_sky(
        set_pool, ["Grizzly Bears"], ["Hill Giant"], None, interactive=(),
    )
    assert game.pending_choices == []
    default = sky.metadata["chosen_color"]
    assert default in ("W", "U", "B", "R", "G")
    assert _w1g6_colors(game, mine[0]) == [default] == _w1g6_colors(game, theirs[0])

    sky.metadata["chosen_color"] = "U"
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, mine[0]) == ["U"] == _w1g6_colors(game, theirs[0])

    late = _W1G6Permanent(card=_w1g6_card(set_pool, "Savannah Lions"))
    game._put_permanent_onto_battlefield(1, late, None)
    assert _w1g6_colors(game, late) == ["U"]


def _w1g6_shape(game, perm):
    """(colours, is a Goblin, is a Zombie, power, toughness) through the
    layers."""
    return (
        _w1g6_colors(game, perm), perm.has_type("goblin"), perm.has_type("zombie"),
        perm.effective_power, perm.effective_toughness,
    )  # _w1g6_shape


def test_w1g6_dralnus_crusade_makes_every_goblin_a_black_zombie_as_well(set_pool):
    """"All Goblins get +1/+1. / All Goblins are black and are Zombies in
    addition to their other creature types." Both players' Goblins are black —
    instead of red (CR 105.3, layer 5) — and Goblin **Zombies** (CR 205.1b,
    layer 4: the type is added, so they are still Goblins), and 2/2. The Bears
    and the Giant are neither, and when the Crusade leaves every Goblin is a
    red 1/1 Goblin again."""
    assert _w1g6_compile(_w1g6_card(set_pool, "Dralnu's Crusade")).supported
    game, mine, theirs = _w1g6_table(
        set_pool, ["Mons's Goblin Raiders", "Grizzly Bears"],
        ["Goblin Balloon Brigade", "Hill Giant"], hand=["Dralnu's Crusade"],
    )
    raiders, bears = mine
    brigade, giant = theirs
    assert _w1g6_shape(game, raiders) == (["R"], True, False, 1, 1)

    assert game.queue_from_hand(0, "Dralnu's Crusade").supported
    _w1g6_resolve_stack(game)
    crusade = next(p for p in game.controlled_by(0) if p.card.name == "Dralnu's Crusade")

    assert _w1g6_shape(game, raiders) == (["B"], True, True, 2, 2)
    assert _w1g6_shape(game, brigade) == (["B"], True, True, 2, 2)
    assert _w1g6_shape(game, bears) == (["G"], False, False, 2, 2)
    assert _w1g6_shape(game, giant) == (["R"], False, False, 3, 3)
    assert _w1g6_colors(game, crusade) == ["B", "R"], "the enchantment is no Goblin"

    game.remove_from_battlefield(crusade)
    game._recompute_continuous_effects()
    assert _w1g6_shape(game, raiders) == (["R"], True, False, 1, 1)
    assert _w1g6_shape(game, brigade) == (["R"], True, False, 1, 1)


def test_w1g6_dralnus_crusade_goblins_are_zombies_to_lord_of_the_undead_and_black_to_terror(set_pool):
    """What the two layers buy. "Other Zombie creatures get +1/+1" (Lord of the
    Undead) counts a Crusade Goblin: 1/1, +1/+1 from the Crusade, +1/+1 from
    the Lord. And the Goblin is a black creature, so a Terror ("nonblack") may
    not name it — the same Terror could a moment before the Crusade resolved."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Lord of the Undead"], ["Mons's Goblin Raiders"],
        hand=["Terror", "Dralnu's Crusade"],
    )
    lord, raiders = mine[0], theirs[0]
    assert (raiders.effective_power, raiders.effective_toughness) == (1, 1)
    assert game.queue_from_hand(0, "Terror", target_permanent_ids=[raiders.permanent_id]).supported
    game.stack.clear()
    game.players[0].hand.append(_w1g6_card(set_pool, "Terror"))

    assert game.queue_from_hand(0, "Dralnu's Crusade").supported
    _w1g6_resolve_stack(game)

    assert (raiders.effective_power, raiders.effective_toughness) == (3, 3)
    assert (lord.effective_power, lord.effective_toughness) == (2, 2), "other Zombies"
    refused = game.queue_from_hand(0, "Terror", target_permanent_ids=[raiders.permanent_id])
    assert not refused.supported, refused.details


def test_w1g6_dralnus_crusade_reads_goblin_through_the_layers(set_pool):
    """The scope is "Goblins" as the board currently is, not as cards are
    printed: Bears made Goblins by a Conspiracy naming Goblin are black Goblin
    Zombies under the Crusade, and stop being when the Conspiracy leaves."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Grizzly Bears", "Dralnu's Crusade"], [])
    bears = mine[0]
    assert _w1g6_shape(game, bears) == (["G"], False, False, 2, 2)

    conspiracy = _W1G6Permanent(card=set_pool("MMQ")["Conspiracy"])
    game._put_permanent_onto_battlefield(0, conspiracy, None)
    conspiracy.metadata["chosen_creature_type"] = "goblin"
    game._recompute_continuous_effects()
    assert _w1g6_shape(game, bears) == (["B"], True, True, 3, 3)

    game.remove_from_battlefield(conspiracy)
    game._recompute_continuous_effects()
    assert _w1g6_shape(game, bears) == (["G"], False, False, 2, 2)


def _w1g6_declare_block(game, attacker, blocker):
    """Seat 0 attacks with *attacker* and seat 1 offers *blocker*; returns the
    engine's answer to the block."""
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(attacker)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    return game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)],
    })  # _w1g6_declare_block


def test_w1g6_hobble_draws_a_card_and_stops_its_creature_attacking(set_pool):
    """"Enchant creature / When this Aura enters, draw a card. / Enchanted
    creature can't attack." Cast on the opponent's white Lions: its caster
    draws one card, and on the Lions' own turn the declaration naming them is
    refused while the Giant beside them attacks freely."""
    hobble = _w1g6_card(set_pool, "Hobble")
    assert _w1g6_compile(hobble).supported
    game, _mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Savannah Lions", "Hill Giant"])
    lions, giant = theirs
    game.players[0].library.extend([_w1g6_card(set_pool, "Forest")] * 3)

    _w1g6_enchant(game, set_pool, "Hobble", lions)
    assert [card.name for card in game.players[0].hand] == ["Forest"]

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    assert not game.declare_attackers(1, [game.battlefield_index_of(lions)])[0]
    assert game.declare_attackers(1, [game.battlefield_index_of(giant)])[0]


def test_w1g6_hobbles_block_ban_follows_the_creatures_colour_through_the_layers(set_pool):
    """"Enchanted creature can't block if it's black." A condition, re-read
    whenever combat asks (CR 613 layer 5): the white Lions under Hobble may
    block; the same Lions turned black for the turn may not; and once the turn
    is over and they are white again, they may. A printed-black creature under
    it can never block."""
    for blocker, may_block in (("Scathe Zombies", False), ("Savannah Lions", True)):
        game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], [blocker])
        _w1g6_enchant(game, set_pool, "Hobble", theirs[0])
        assert _w1g6_declare_block(game, mine[0], theirs[0])[0] is may_block, blocker

    game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Savannah Lions"])
    bears, lions = mine[0], theirs[0]
    _w1g6_enchant(game, set_pool, "Hobble", lions)
    _w1g6_recolor(game, lions, "B")
    refused = _w1g6_declare_block(game, bears, lions)
    assert not refused[0], refused

    game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Savannah Lions"])
    bears, lions = mine[0], theirs[0]
    _w1g6_enchant(game, set_pool, "Hobble", lions)
    _w1g6_recolor(game, lions, "B")
    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, lions) == ["W"]
    assert _w1g6_declare_block(game, bears, lions)[0]


def test_w1g6_a_black_creature_without_hobble_blocks_as_it_always_did(set_pool):
    """The ban is the Aura's: a black creature nothing enchants blocks, and so
    does a black creature wearing a different Aura."""
    game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Scathe Zombies"])
    assert _w1g6_declare_block(game, mine[0], theirs[0])[0]


def _w1g6_defiance(set_pool, mine, theirs):
    """Heroic Defiance cast on seat 0's first permanent. Returns the game and
    that creature."""
    game, my_side, their_side = _w1g6_table(set_pool, mine, theirs)
    host = my_side[0]
    _w1g6_enchant(game, set_pool, "Heroic Defiance", host)
    return game, host, their_side  # _w1g6_defiance


def test_w1g6_heroic_defiance_pumps_a_creature_that_is_not_the_most_common_colour(set_pool):
    """"Enchanted creature gets +3/+3 unless it shares a color with the most
    common color among all permanents or a color tied for most common." Two red
    permanents lead the census (the white Aura, the green Bears and a black
    creature are one each), so the green Bears are 5/5 — once, not twice."""
    assert _w1g6_compile(_w1g6_card(set_pool, "Heroic Defiance")).supported
    game, bears, _theirs = _w1g6_defiance(
        set_pool, ["Grizzly Bears"], ["Hill Giant", "Mons's Goblin Raiders", "Scathe Zombies"],
    )
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


def test_w1g6_heroic_defiance_follows_the_census_and_the_creatures_colour(set_pool):
    """Continuous, and both halves are layer-5 reads. The Bears turned red for
    the turn share the leading colour and are 2/2; at cleanup they are green
    and 5/5 again. With one red creature gone every colour is level, green is
    "a color tied for most common", and the bonus is off; and a creature made
    colourless shares no colour at all (CR 105.2) and has it."""
    game, bears, theirs = _w1g6_defiance(
        set_pool, ["Grizzly Bears"], ["Hill Giant", "Mons's Goblin Raiders", "Scathe Zombies"],
    )
    _w1g6_recolor(game, bears, "R")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, bears) == ["G"]
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)

    game.remove_from_battlefield(theirs[1])
    game._recompute_continuous_effects()
    assert (bears.effective_power, bears.effective_toughness) == (2, 2), "all tied"

    bears.metadata["color_override"] = ()
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, bears) == []
    assert (bears.effective_power, bears.effective_toughness) == (5, 5)


def test_w1g6_heroic_defiance_gives_nothing_to_a_creature_of_the_leading_colour(set_pool):
    """Cast on a red creature while red leads, it is +0/+0 — and the bonus
    arrives the moment red stops leading, with nothing re-cast."""
    game, giant, theirs = _w1g6_defiance(
        set_pool, ["Hill Giant", "Mons's Goblin Raiders"], ["Grizzly Bears", "Llanowar Elves"],
    )
    assert (giant.effective_power, giant.effective_toughness) == (3, 3), "red and green tie"

    extra = _W1G6Permanent(card=_w1g6_card(set_pool, "Giant Spider"))
    game._put_permanent_onto_battlefield(1, extra, None)
    game._recompute_continuous_effects()
    assert (giant.effective_power, giant.effective_toughness) == (6, 6), "green leads alone"


# -- arrival cards: supported on the day of the ingest, never run until now --


def test_w1g6_sinister_strength_makes_its_creature_black_for_as_long_as_it_is_attached(set_pool):
    """"Enchanted creature gets +3/+1 and is black." Layer 5 beside layer 7c,
    both derived from the Aura: the green Bears are a black 5/3 that a Terror
    ("nonblack") may not name, and green 2/2 Bears again the moment the Aura
    is gone."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Grizzly Bears"], [], hand=["Terror"])
    bears = mine[0]
    aura = _w1g6_enchant(game, set_pool, "Sinister Strength", bears)
    assert _w1g6_colors(game, bears) == ["B"]
    assert (bears.effective_power, bears.effective_toughness) == (5, 3)
    assert not game.queue_from_hand(0, "Terror", target_permanent_ids=[bears.permanent_id]).supported

    game.remove_from_battlefield(aura)
    game.check_state_based_actions()
    game._recompute_continuous_effects()
    assert _w1g6_colors(game, bears) == ["G"]
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g6_sisays_ingenuity_grants_a_recolour_whose_colour_is_asked_at_resolution(set_pool):
    """"When this Aura enters, draw a card. / Enchanted creature has "{2}{U}:
    Target creature becomes the color of your choice until end of turn.""
    The Aura's caster draws; the *creature* has the ability and it costs
    {2}{U}; the colour is asked of its activator as it resolves (CR 608.2d) —
    the white sent with the activation is not read — and wears off at
    cleanup."""
    game, mine, theirs = _w1g6_table(set_pool, ["Grizzly Bears"], ["Hill Giant"], mana=True)
    bears, giant = mine[0], theirs[0]
    game.players[0].library.extend([_w1g6_card(set_pool, "Forest")] * 3)
    game.players[0].mana_pool["U"] = 1
    _w1g6_enchant(game, set_pool, "Sisay's Ingenuity", bears)
    assert [card.name for card in game.players[0].hand] == ["Forest"]

    announced = {"ability_index": 0, "target_permanent_ids": [giant.permanent_id], "mana_color": "W"}
    assert not game.queue_permanent_ability(0, "Grizzly Bears", **announced).supported
    game.players[0].mana_pool.update({"U": 1, "G": 2})
    assert game.queue_permanent_ability(0, "Grizzly Bears", **announced).supported
    assert game.players[0].mana_pool["U"] + game.players[0].mana_pool["G"] == 0
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert _w1g6_colors(game, giant) == ["R"]
    assert game.confirm_color_choice(0, "G")
    _w1g6_resolve_stack(game)
    assert _w1g6_colors(game, giant) == ["G"]

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, giant) == ["R"]


def test_w1g6_escape_routes_returns_only_its_controllers_creature_that_is_white_or_black_now(set_pool):
    """"{2}{U}: Return target white or black creature you control to its
    owner's hand." The colour union is layer 5's and the seat is enforced:
    white Lions go home and green Bears may not be named; with the two swapped
    for the turn it is the Bears; and an opponent's white creature is never a
    legal target."""
    for swapped in (False, True):
        game, mine, theirs = _w1g6_table(
            set_pool, ["Escape Routes", "Savannah Lions", "Grizzly Bears"], ["Savannah Lions"],
        )
        _routes, lions, bears = mine
        if swapped:
            _w1g6_recolor(game, lions, "G")
            _w1g6_recolor(game, bears, "W")
        legal, illegal = (bears, lions) if swapped else (lions, bears)
        for refused in (illegal, theirs[0]):
            assert not game.queue_permanent_ability(
                0, "Escape Routes", ability_index=0, target_permanent_ids=[refused.permanent_id],
            ).supported
        assert game.queue_permanent_ability(
            0, "Escape Routes", ability_index=0, target_permanent_ids=[legal.permanent_id],
        ).supported
        _w1g6_resolve_stack(game)
        assert [card.name for card in game.players[0].hand] == [legal.card.name]
        assert game.is_on_battlefield(illegal) and game.is_on_battlefield(theirs[0])


# --- W1G7: triggers and cast rules ---
import pytest

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import CardDefinition as _W1G7Card
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_card(name, type_line, text="", *, cost="{1}", colors=(), pt=None):
    """A fixture card with exactly the printed text a test needs."""
    raw = {"name": name, "type_line": type_line}
    if pt is not None:
        raw["power"], raw["toughness"] = str(pt[0]), str(pt[1])
    made = _W1G7Card(
        name=name, mana_cost=cost, cmc=float(cost.count("{")),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(), raw=raw,
    )
    return made


def _w1g7_lands(set_pool, count, name="Swamp"):
    """*count* untapped basics — real ones, so they tap for real mana."""
    land = set_pool("LEA")[name]
    return [_W1G7Permanent(card=land) for _ in range(count)]


def _w1g7_board(mine=(), theirs=(), *, hands=((), ()), interactive=()):
    """Two seats, a library each, costs off — the enchantment under test on
    seat 0 unless the test says otherwise."""
    filler = _w1g7_card("W1G7 Filler", "Creature - Test", pt=(1, 1))
    table = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", battlefield=list(mine), hand=list(hands[0]),
            library=[filler] * 8,
        ),
        _W1G7PlayerState(
            name="P2", battlefield=list(theirs), hand=list(hands[1]),
            library=[filler] * 8,
        ),
    ])
    table.enforce_mana_costs = False
    table.interactive_seats = set(interactive)
    return table


# Phyrexian Tyranny — "Whenever a player draws a card, that player loses 2 life
# unless they pay {2}." CR 121.2 makes a draw a per-card event, so a draw-two is
# two triggers and two tolls; "a player" is the third value of the seat axis
# `draws_card` already carried for "you" and "an opponent".


def test_w1g7_phyrexian_tyranny_compiles_as_a_toll_on_any_seats_draw(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Phyrexian Tyranny"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "draws_card"
    assert trigger.condition.payload == {"drawer": "a player"}
    assert trigger.instruction.kind == "may"
    assert trigger.instruction.payload["actor"] == "event_subject_player"
    assert trigger.instruction.payload["cost"] == {"generic": 2}


def test_w1g7_phyrexian_tyranny_costs_the_drawing_opponent_two_life(set_pool):
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    # No land to pay with, so the offer is never made and the toll applies.
    assert [seat.life for seat in table.players] == [20, 18]


def test_w1g7_phyrexian_tyranny_binds_its_own_controller_too(set_pool):
    """"A player" is not "an opponent": the enchantment's controller drawing is
    the event happening to a seat the card names."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])

    table._draw_with_replacements(table.players[0], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    assert [seat.life for seat in table.players] == [18, 20]


def test_w1g7_phyrexian_tyranny_is_one_toll_per_card_drawn(set_pool):
    """CR 121.2: drawing two cards is two draws, so two triggers and two
    separate offers — three lands pay for exactly one of them."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 3)
    table = _w1g7_board([tyranny], lands, interactive={1})

    table._draw_with_replacements(table.players[1], 2)
    table.check_state_based_actions()
    assert [item.card.name for item in table.stack] == ["Phyrexian Tyranny"] * 2

    table.resolve_top_of_stack(pause_for_choices=True)
    (offer,) = table.pending_choices
    assert (offer.kind, offer.player_index) == ("optional_pay", 1), (
        "the drawing player is the payer, not the enchantment's controller"
    )
    assert table.confirm_optional_pay(1, accept=True)
    assert table.players[1].life == 20
    assert sum(land.tapped for land in lands) == 2

    # The second toll: one untapped land cannot cover {2}, so it is not offered.
    table.resolve_top_of_stack(pause_for_choices=True)
    assert table.pending_choices == []
    assert table.players[1].life == 18
    assert not table.stack


def test_w1g7_phyrexian_tyranny_a_declined_toll_loses_the_life(set_pool):
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 2)
    table = _w1g7_board([tyranny], lands, interactive={1})

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    table.resolve_top_of_stack(pause_for_choices=True)
    assert table.confirm_optional_pay(1, accept=False)

    assert table.players[1].life == 18
    assert not any(land.tapped for land in lands)


def test_w1g7_phyrexian_tyranny_fires_in_the_draw_step_that_drew(set_pool):
    """CR 504.2 with CR 603.3: the turn-based draw's trigger goes on the stack
    before the active player's draw-step priority, not a phase later. The
    headless turn resolves it inside the step, so the toll is already settled
    when the main phase begins."""
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    table = _w1g7_board([tyranny], [])
    table.turn = 2

    table.begin_turn_bookkeeping(1)
    table.resolve_untap_step(1)
    table.resolve_upkeep(1)
    table.resolve_draw_step(1)
    table.auto_resolve_pending_choices()

    assert table.current_step == "draw"
    assert table.players[1].life == 18


# Cloud Cover — "Whenever another permanent you control becomes the target of a
# spell or ability an opponent controls, you may return that permanent to its
# owner's hand." Cowardice's board-wide scope with three printed narrowings —
# "another", "you control", "an opponent controls" — and each has a test that
# fails if it is dropped.


def _w1g7_cloud_table(*, hands=((), ()), interactive=(0,)):
    cloud = _W1G7Permanent(card=_w1g7_cloud_table.pool["Cloud Cover"])
    mine = _W1G7Permanent(card=_w1g7_card("W1G7 Mine", "Creature - Test", pt=(2, 2)))
    theirs = _W1G7Permanent(
        card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(2, 2))
    )
    table = _w1g7_board(
        [cloud, mine], [theirs], hands=hands, interactive=interactive
    )
    return table, cloud, mine, theirs


def _w1g7_zap():
    return _w1g7_card(
        "W1G7 Zap", "Instant", "W1G7 Zap deals 2 damage to target creature.",
        cost="{R}", colors=("R",),
    )


def _w1g7_unmake():
    return _w1g7_card(
        "W1G7 Unmake", "Instant", "Destroy target enchantment.",
        cost="{W}", colors=("W",),
    )


@pytest.fixture
def _w1g7_cloud(set_pool):
    _w1g7_cloud_table.pool = set_pool("PLS")
    return _w1g7_cloud_table


def test_w1g7_cloud_cover_compiles_with_all_three_narrowings(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Cloud Cover"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "self_becomes_target"
    assert trigger.condition.payload == {
        "targeted_by": "a spell or ability",
        "targeting_controller": "an opponent controls",
        "targeted_filter": {"controller": "you", "exclude_self": True},
    }
    assert trigger.instruction.kind == "may"
    assert [step.kind for step in trigger.instruction.payload["action"]] == [
        "bounce_event_subject"
    ]


def test_w1g7_cloud_cover_saves_a_creature_an_opponent_targeted(_w1g7_cloud):
    table, _cloud, mine, _theirs = _w1g7_cloud(hands=((), (_w1g7_zap(),)))

    table.cast_from_hand(1, "W1G7 Zap", target_permanent_ids=[mine.permanent_id])
    (offer,) = table.pending_choices
    assert (offer.kind, offer.player_index) == ("optional_pay", 0)
    assert table.confirm_optional_pay(0, accept=True)
    _w1g7_resolve_stack(table)

    assert [card.name for card in table.players[0].hand] == ["W1G7 Mine"]
    assert not table.is_on_battlefield(mine)
    # CR 608.2b: the spell found its only target gone.
    assert any("every target is illegal" in line for line in table.log)


def test_w1g7_cloud_cover_is_a_may_and_declining_lets_the_spell_resolve(_w1g7_cloud):
    table, _cloud, mine, _theirs = _w1g7_cloud(hands=((), (_w1g7_zap(),)))

    table.cast_from_hand(1, "W1G7 Zap", target_permanent_ids=[mine.permanent_id])
    assert table.confirm_optional_pay(0, accept=False)
    _w1g7_resolve_stack(table)

    assert table.players[0].hand == []
    assert mine.damage_marked == 2 or not table.is_on_battlefield(mine)


def test_w1g7_cloud_cover_ignores_its_own_controllers_spells(_w1g7_cloud):
    """"…a spell or ability **an opponent controls**"."""
    table, _cloud, mine, _theirs = _w1g7_cloud(hands=((_w1g7_zap(),), ()))

    table.cast_from_hand(0, "W1G7 Zap", target_permanent_ids=[mine.permanent_id])

    assert table.pending_choices == []
    assert table.players[0].hand == []


def test_w1g7_cloud_cover_does_not_watch_itself(_w1g7_cloud):
    """"**Another** permanent you control": every permanent but the one
    printing the word. Dropped, an opponent's Disenchant aimed at Cloud Cover
    would let its controller pick the enchantment back up."""
    table, cloud, _mine, _theirs = _w1g7_cloud(hands=((), (_w1g7_unmake(),)))

    table.cast_from_hand(
        1, "W1G7 Unmake", target_permanent_ids=[cloud.permanent_id]
    )
    _w1g7_resolve_stack(table)

    assert table.pending_choices == []
    assert [card.name for card in table.players[0].graveyard] == ["Cloud Cover"]
    assert table.players[0].hand == []


def test_w1g7_cloud_cover_does_not_watch_an_opponents_permanents(_w1g7_cloud):
    """"…permanent **you control**"."""
    table, _cloud, _mine, theirs = _w1g7_cloud(hands=((), (_w1g7_zap(),)))

    table.cast_from_hand(1, "W1G7 Zap", target_permanent_ids=[theirs.permanent_id])

    assert table.pending_choices == []
    assert table.players[1].hand == []


def test_w1g7_cloud_cover_watches_an_opponents_ability_and_any_permanent(
    _w1g7_cloud, set_pool
):
    """"A spell **or ability**", and "**permanent**" rather than "creature":
    an opponent's activated ability aimed at a land fires it too."""
    table, _cloud, _mine, _theirs = _w1g7_cloud()
    forest = _W1G7Permanent(card=set_pool("LEA")["Forest"])
    table.players[0].battlefield.append(forest)
    table._initialize_permanent_state(forest, 0, 1)
    icy = _W1G7Permanent(card=_w1g7_card(
        "W1G7 Icy", "Artifact", "{T}: Tap target land.", cost="{4}",
    ))
    table.players[1].battlefield.append(icy)
    table._initialize_permanent_state(icy, 1, 0)

    assert table.activate_permanent_ability(
        1, "W1G7 Icy", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert [c.kind for c in table.pending_choices] == ["optional_pay"]
    assert table.confirm_optional_pay(0, accept=True)
    _w1g7_resolve_stack(table)

    assert [card.name for card in table.players[0].hand] == ["Forest"]


# Warped Devotion — "Whenever a permanent is returned to a player's hand, that
# player discards a card." A zone change with both ends named, announced from
# `Game.put_card_into_hand` — the one seam handed the hand it is going to and,
# as `from_battlefield`, the permanent it is the card of.


def _w1g7_devotion_table(set_pool, *, mine=(), theirs=(), hands=((), ())):
    devotion = _W1G7Permanent(card=set_pool("PLS")["Warped Devotion"])
    table = _w1g7_board([devotion, *mine], list(theirs), hands=hands)
    return table, devotion


def _w1g7_settle(table):
    """Drain the stack and take every default the drained objects armed."""
    for _ in range(8):
        _w1g7_resolve_stack(table)
        if not table.pending_choices:
            return
        table.auto_resolve_pending_choices()
    raise AssertionError("the table did not settle")


def _w1g7_names(cards):
    return sorted(getattr(card, "name", None) or card.card.name for card in cards)


def test_w1g7_warped_devotion_compiles_onto_the_zone_change(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Warped Devotion"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "permanent_returned_to_hand"
    assert trigger.condition.payload == {"returned_filter": {}}
    assert trigger.instruction.kind == "discard_target_cards"
    # "That player" is the seat the move froze, not a seat anybody targeted.
    assert trigger.instruction.payload == {
        "amount": 1, "who": "event_subject_player",
    }


def test_w1g7_warped_devotion_makes_the_bounced_permanents_owner_discard(set_pool):
    """Seat 1 bounces seat 0's creature: the hand it reaches is seat 0's, so
    seat 0 discards — not the player who cast the bounce, and not "the
    opponent of the enchantment's controller", which is the seat a targetless
    resolution defaults to and the one this card used to take the card from."""
    lea = set_pool("LEA")
    mine = _W1G7Permanent(card=_w1g7_card("W1G7 Mine", "Creature - Test", pt=(2, 2)))
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=[mine],
        hands=((lea["Forest"],), (lea["Unsummon"], lea["Swamp"])),
    )

    assert table.cast_from_hand(
        1, "Unsummon", target_permanent_ids=[mine.permanent_id]
    ).supported
    _w1g7_settle(table)

    assert len(table.players[0].hand) == 1, "one card arrived and one went"
    assert len(table.players[0].graveyard) == 1
    assert _w1g7_names(table.players[1].hand) == ["Swamp"]
    assert _w1g7_names(table.players[1].graveyard) == ["Unsummon"]


def test_w1g7_warped_devotion_follows_the_owner_whoever_did_the_bouncing(set_pool):
    lea = set_pool("LEA")
    theirs = _W1G7Permanent(
        card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(2, 2))
    )
    table, _devotion = _w1g7_devotion_table(
        set_pool, theirs=[theirs],
        hands=((lea["Unsummon"], lea["Forest"]), (lea["Swamp"],)),
    )

    table.cast_from_hand(0, "Unsummon", target_permanent_ids=[theirs.permanent_id])
    _w1g7_settle(table)

    assert _w1g7_names(table.players[0].hand) == ["Forest"]
    assert len(table.players[1].hand) == 1 and len(table.players[1].graveyard) == 1


def test_w1g7_warped_devotion_ignores_a_card_that_was_never_a_permanent(set_pool):
    """A draw and a return from a graveyard both put a card into a hand and
    return no *permanent* — the narrowing "a permanent is returned" is."""
    lea = set_pool("LEA")
    table, _devotion = _w1g7_devotion_table(
        set_pool, hands=((lea["Raise Dead"], lea["Forest"]), (lea["Swamp"],)),
    )
    table.players[0].graveyard.append(lea["Grizzly Bears"])

    assert table.cast_from_hand(0, "Raise Dead", target_permanent_index=0).supported
    _w1g7_settle(table)
    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    _w1g7_settle(table)

    assert _w1g7_names(table.players[0].hand) == ["Forest", "Grizzly Bears"]
    assert _w1g7_names(table.players[0].graveyard) == ["Raise Dead"]
    assert table.players[1].graveyard == []


def test_w1g7_warped_devotion_fires_for_a_token_that_is_bounced(set_pool):
    """CR 111.7: "if a token changes zones, applicable triggered abilities will
    trigger before the token ceases to exist." The token is returned to its
    owner's hand — and then is no card anywhere — so its owner discards."""
    from engine.tokens import make_token_card

    lea = set_pool("LEA")
    token = _W1G7Permanent(card=make_token_card(
        "Saproling", 1, 1, "Token Creature - Saproling", colors=("G",),
    ))
    table, _devotion = _w1g7_devotion_table(
        set_pool, theirs=[token], hands=((lea["Unsummon"],), (lea["Swamp"],)),
    )
    table._initialize_permanent_state(token, 1, 0)

    table.cast_from_hand(0, "Unsummon", target_permanent_ids=[token.permanent_id])
    _w1g7_settle(table)

    assert table.players[1].hand == [], "the token is not a card in a hand"
    assert _w1g7_names(table.players[1].graveyard) == ["Swamp"]
    assert not table.is_on_battlefield(token)


def test_w1g7_warped_devotion_sees_itself_returned(set_pool):
    """CR 603.10a: an ability that triggers when an object all players can see
    is put into a hand looks back in time, so the enchantment bounced by the
    effect is still there to see itself go."""
    lea = set_pool("LEA")
    table, devotion = _w1g7_devotion_table(
        set_pool, hands=((lea["Forest"],), (set_pool("LEG")["Boomerang"],)),
    )

    table.cast_from_hand(1, "Boomerang", target_permanent_ids=[devotion.permanent_id])
    _w1g7_settle(table)

    assert _w1g7_names(table.players[0].graveyard) == ["Forest"]
    assert _w1g7_names(table.players[0].hand) == ["Warped Devotion"]


def test_w1g7_warped_devotion_triggers_once_per_permanent_in_a_sweep(set_pool):
    """One trigger per permanent returned (CR 603.2c: an event containing
    several occurrences triggers once for each)."""
    lea, forest = set_pool("LEA"), set_pool("LEA")["Forest"]
    evacuation = next(
        set_pool(code)["Evacuation"]
        for code in ("STH", "5ED", "6ED", "TMP", "INV")
        if "Evacuation" in set_pool(code)
    )
    mine = [
        _W1G7Permanent(card=_w1g7_card(f"W1G7 Mine {n}", "Creature - Test", pt=(1, 1)))
        for n in (1, 2)
    ]
    theirs = [
        _W1G7Permanent(card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(1, 1)))
    ]
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=mine, theirs=theirs,
        hands=((evacuation, forest, forest, forest), (lea["Swamp"], lea["Swamp"])),
    )

    assert table.cast_from_hand(0, "Evacuation").supported
    _w1g7_settle(table)

    # Seat 0: three Forests and two returned creatures in, two discards out.
    assert len(table.players[0].hand) == 3
    assert len(table.players[0].graveyard) == 3  # Evacuation + two discards
    # Seat 1: two Swamps and one returned creature in, one discard out.
    assert len(table.players[1].hand) == 2
    assert len(table.players[1].graveyard) == 1


def test_w1g7_warped_devotion_costs_a_gating_creature_a_card(set_pool):
    """Gating ("When this creature enters, return a red or green creature you
    control to its owner's hand") under Warped Devotion: the return is a
    permanent returned to a hand, so the gater's controller discards."""
    lea, pls = set_pool("LEA"), set_pool("PLS")
    gater = pls["Horned Kavu"]
    assert _w1g7_compile(gater).supported
    host = _W1G7Permanent(card=_w1g7_card(
        "W1G7 Red Host", "Creature - Test", pt=(2, 2), colors=("R",), cost="{R}",
    ))
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=[host], hands=((gater, lea["Forest"]), ()),
    )

    assert table.cast_from_hand(0, "Horned Kavu").supported
    _w1g7_settle(table)

    hand = _w1g7_names(table.players[0].hand)
    # Gating returned one of the two red-or-green creatures (the Kavu may
    # return itself); either way exactly one card came back and one was
    # discarded, so the hand is still one card and the graveyard holds one.
    assert len(hand) == 1, hand
    assert len(table.players[0].graveyard) == 1
    assert any("must choose 1 card(s) to discard" in line for line in table.log)


def test_w1g7_warped_devotion_with_sunken_hope_is_a_discard_every_upkeep(set_pool):
    """Sunken Hope ("each player's upkeep, that player returns a creature they
    control to its owner's hand") beside Warped Devotion: the active player
    bounces a creature and then discards."""
    lea = set_pool("LEA")
    hope = _W1G7Permanent(card=set_pool("PLS")["Sunken Hope"])
    theirs = _W1G7Permanent(
        card=_w1g7_card("W1G7 Theirs", "Creature - Test", pt=(2, 2))
    )
    table, _devotion = _w1g7_devotion_table(
        set_pool, mine=[hope], theirs=[theirs],
        hands=((lea["Forest"],), (lea["Swamp"],)),
    )
    table.turn = 2

    table.begin_turn_bookkeeping(1)
    table.resolve_untap_step(1)
    table.resolve_upkeep(1)
    _w1g7_settle(table)

    assert not table.is_on_battlefield(theirs)
    assert len(table.players[1].hand) == 1 and len(table.players[1].graveyard) == 1
    assert _w1g7_names(table.players[0].hand) == ["Forest"]


def test_w1g7_a_narrower_returned_subject_is_enforced():
    """The noun phrase is data: "a **creature** is returned to a player's hand"
    is the same row with a filter, and the filter is tested — an enchantment
    bounced past it discards nothing."""
    watcher = _W1G7Permanent(card=_w1g7_card(
        "W1G7 Watcher", "Enchantment",
        "Whenever a creature is returned to a player's hand, that player "
        "discards a card.",
    ))
    rock = _W1G7Permanent(card=_w1g7_card("W1G7 Rock", "Artifact", cost="{2}"))
    bear = _W1G7Permanent(card=_w1g7_card("W1G7 Bear", "Creature - Test", pt=(2, 2)))
    filler = _w1g7_card("W1G7 Card", "Sorcery", "Draw a card.")
    table = _w1g7_board([watcher], [rock, bear], hands=((), (filler, filler)))
    program = _w1g7_compile(watcher.card)
    assert program.supported, program.reason

    table.put_card_into_hand(table.players[1], rock.card, from_battlefield=rock)
    table.remove_from_battlefield(rock)
    _w1g7_settle(table)
    assert table.players[1].graveyard == []

    table.put_card_into_hand(table.players[1], bear.card, from_battlefield=bear)
    table.remove_from_battlefield(bear)
    _w1g7_settle(table)
    assert len(table.players[1].graveyard) == 1


# Keldon Twilight — "At the beginning of each player's end step, if no
# creatures attacked this turn, that player sacrifices a creature of their
# choice that they controlled since the beginning of the turn." Three pieces
# that each already had a neighbour: the per-player end step (Monsoon), a
# turn-wide attack record read as CR 603.4's intervening-if, and CR 302.6's
# clock as a narrowing on the forced-sacrifice prompt.


def _w1g7_twilight_table(set_pool, *, mine=("W1G7 Mine",), theirs=("W1G7 Theirs",),
                         interactive=()):
    twilight = _W1G7Permanent(card=set_pool("PLS")["Keldon Twilight"])
    ours = [
        _W1G7Permanent(card=_w1g7_card(name, "Creature - Test", pt=(2, 2)))
        for name in mine
    ]
    others = [
        _W1G7Permanent(card=_w1g7_card(name, "Creature - Test", pt=(2, 2)))
        for name in theirs
    ]
    table = _w1g7_board([twilight, *ours], others, interactive=interactive)
    table.turn = 4
    return table, ours, others


def _w1g7_to_end_step(table, seat, *, begin=True):
    """Run *seat*'s turn to the beginning of its end step, attacking with
    nobody; the end-step triggers are on the stack when this returns."""
    if begin:
        table.start_turn(seat)
    table._close_current_priority_step()
    for _ in range(12):
        if table.current_turn_phase == "ending":
            return
        table.enter_next_turn_phase()
    raise AssertionError("the turn never reached its ending phase")


def test_w1g7_keldon_twilight_compiles_with_its_gate_and_its_narrowing(set_pool):
    program = _w1g7_compile(set_pool("PLS")["Keldon Twilight"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "end_step"
    assert trigger.instruction.kind == "sacrifice_matching_permanent"
    assert trigger.instruction.payload == {
        "filter": {"type_filter": "creature", "controlled_since_turn_start": True},
        "who": "event_subject_player",
        "intervening_if": {"kind": "creatures_attacked_this_turn", "negated": True},
    }


def test_w1g7_keldon_twilight_takes_a_creature_from_the_player_whose_end_step_it_is(
    set_pool,
):
    table, ours, others = _w1g7_twilight_table(set_pool)

    _w1g7_to_end_step(table, 1)
    assert [item.card.name for item in table.stack] == ["Keldon Twilight"]
    _w1g7_settle(table)

    # "That player" is the active one — the opponent here, not the
    # enchantment's controller.
    assert not table.is_on_battlefield(others[0])
    assert table.is_on_battlefield(ours[0])


def test_w1g7_keldon_twilight_binds_its_own_controller_on_their_turn(set_pool):
    table, ours, others = _w1g7_twilight_table(set_pool)

    _w1g7_to_end_step(table, 0)
    _w1g7_settle(table)

    assert not table.is_on_battlefield(ours[0])
    assert table.is_on_battlefield(others[0])


def test_w1g7_keldon_twilight_does_not_trigger_on_a_turn_a_creature_attacked(set_pool):
    """CR 603.4: an intervening-if that is false means the ability does not
    trigger at all — nothing goes on the stack. The record is the seat's, so an
    attacker that has since left the battlefield still attacked."""
    table, _ours, others = _w1g7_twilight_table(set_pool)
    table.start_turn(1)
    table._close_current_priority_step()
    table.advance_combat_phase()
    table.advance_combat_phase()
    assert table.declare_attackers(1, [0])[0]
    table.remove_from_battlefield(others[0])  # the attacker is gone …
    assert table.players[1].attacked_this_turn  # … and still attacked

    for _ in range(12):
        if table.current_turn_phase == "ending":
            break
        table.enter_next_turn_phase()

    assert table.current_turn_phase == "ending"
    assert table.stack == []


def test_w1g7_keldon_twilight_spares_a_creature_that_arrived_this_turn(set_pool):
    """"…that they controlled since the beginning of the turn". A creature cast
    this turn is not one, so a player holding only that one sacrifices
    nothing — and with an older creature beside it, only the older is offered."""
    fresh = _w1g7_card("W1G7 Fresh", "Creature - Test", pt=(2, 2))
    table, _ours, _others = _w1g7_twilight_table(set_pool, theirs=())
    table.players[1].hand.append(fresh)
    table.start_turn(1)
    assert table.cast_from_hand(1, "W1G7 Fresh").supported
    _w1g7_settle(table)

    _w1g7_to_end_step(table, 1, begin=False)
    _w1g7_settle(table)

    assert _w1g7_names(table.controlled_by(1)) == ["W1G7 Fresh"]
    assert table.players[1].graveyard == []


def test_w1g7_keldon_twilight_offers_only_the_creatures_it_names(set_pool):
    fresh = _w1g7_card("W1G7 Fresh", "Creature - Test", pt=(2, 2))
    table, _ours, others = _w1g7_twilight_table(
        set_pool, theirs=("W1G7 Old",), interactive={1},
    )
    table.players[1].hand.append(fresh)
    table.start_turn(1)
    table.cast_from_hand(1, "W1G7 Fresh")
    table.resolve_stack(pause_for_choices=True)

    _w1g7_to_end_step(table, 1, begin=False)
    table.resolve_top_of_stack(pause_for_choices=True)

    (owed,) = table.pending_choices
    assert (owed.kind, owed.player_index) == ("sacrifice", 1)
    offered = table._sacrifice_candidate_indices(
        table.players[1], owed.data["filter"]
    )
    assert [table.players[1].battlefield[i].card.name for i in offered] == [
        "W1G7 Old"
    ]
    assert others[0].card.name == "W1G7 Old"


# Phyrexian Tyranny and the seat nobody asks. "Pay tolls, always" answered this
# card by tapping two lands in every draw step for the rest of the game, so a
# toll whose whole penalty is a little life is priced against the lands on the
# seat's own turn (`ai_policy.optional_pay_may_tap_lands`).


def _w1g7_tyranny_draw_step(set_pool, *, life, hand):
    """Seat 1 (three Forests, *hand*, *life*) takes its draw step under seat
    0's Tyranny with mana costs enforced, and answers the toll by default."""
    lea = set_pool("LEA")
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 3, "Forest")
    table = _w1g7_board(
        [tyranny], lands, hands=((), tuple(lea[name] for name in hand)),
    )
    table.enforce_mana_costs = True
    table.players[1].life = life
    # The draw itself is a land, so what the seat could cast afterwards is
    # exactly the *hand* the test handed it.
    table.players[1].library = [lea["Forest"]] * 6
    table.turn = 2

    table.begin_turn_bookkeeping(1)
    table.resolve_untap_step(1)
    table.resolve_upkeep(1)
    table.resolve_draw_step(1)
    table.auto_resolve_pending_choices()
    return table, lands


def test_w1g7_a_healthy_seat_keeps_its_lands_for_the_spell_in_its_hand(set_pool):
    table, lands = _w1g7_tyranny_draw_step(
        set_pool, life=20, hand=("Grizzly Bears",)
    )

    assert table.players[1].life == 18
    assert not any(land.tapped for land in lands)


def test_w1g7_a_seat_with_nothing_to_cast_pays_the_toll(set_pool):
    """The mana would sit idle, so the life is the dearer price even at 20."""
    table, lands = _w1g7_tyranny_draw_step(set_pool, life=20, hand=())

    assert table.players[1].life == 20
    assert sum(land.tapped for land in lands) == 2


def test_w1g7_a_seat_low_on_life_pays_even_holding_a_spell(set_pool):
    """Declining would leave it under `LIFE_TOLL_FLOOR`."""
    from engine.ai_policy import LIFE_TOLL_FLOOR

    table, lands = _w1g7_tyranny_draw_step(
        set_pool, life=LIFE_TOLL_FLOOR + 1, hand=("Grizzly Bears",)
    )

    assert table.players[1].life == LIFE_TOLL_FLOOR + 1
    assert sum(land.tapped for land in lands) == 2


def test_w1g7_a_toll_off_its_own_turn_is_still_paid(set_pool):
    """On another seat's turn the lands are idle until the untap step, so the
    standing answer stands: pay."""
    lea = set_pool("LEA")
    tyranny = _W1G7Permanent(card=set_pool("PLS")["Phyrexian Tyranny"])
    lands = _w1g7_lands(set_pool, 3, "Forest")
    table = _w1g7_board([tyranny], lands, hands=((), (lea["Grizzly Bears"],)))
    table.enforce_mana_costs = True
    table.active_player_index = 0

    table._draw_with_replacements(table.players[1], 1)
    table.check_state_based_actions()
    _w1g7_resolve_stack(table)
    table.auto_resolve_pending_choices()

    assert table.players[1].life == 20
    assert sum(land.tapped for land in lands) == 2

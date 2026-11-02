"""The log says what happened, to what, and by what — Phase 5's wording, by class.

Phase 5 read the game log at a table and found lines that printed the engine's
record rather than the game: a token's name said twice ("Goblin Token token"),
a chosen colour as its mana symbol ("chose U") and a creature type in lower
case ("chose wizard"), Bane of the Living's -X/-X called a buff, a reanimation
naming neither card ("Reanimated creature to battlefield"), Toxin Sliver's
untargeted "that creature" judged as a target ("its target is gone (608.2b)"),
and a ping naming no recipient ("Goblin Dynamo dealt 1 damage"). Each is a
class, and these drive one board of each through the real entry points —
casting, activating, the special action, combat — and read the log.

The seeded census over whole games is ``test_kg3_logs_wording_census.py``.
"""
from __future__ import annotations

import re

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.face_down import face_down_card
from engine.models import Permanent
from engine.special_actions import take_permanent_special_action
from tests.helpers import declare_attack, resolve_stack

_C = {card.name: card for card in load_catalog()}


def _permanent(name: str, *, face_down: bool = False) -> Permanent:
    card = face_down_card(_C[name]) if face_down else _C[name]
    permanent = Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(hand=(), mine=(), theirs=(), *, graveyard=()) -> Game:
    game = Game(players=[
        PlayerState(
            name="P1", hand=[_C[name] for name in hand],
            graveyard=[_C[name] for name in graveyard],
            library=[_C["Forest"]] * 10,
        ),
        PlayerState(name="P2", library=[_C["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            face_down = name.startswith("fd:")
            permanent = _permanent(name[3:] if face_down else name, face_down=face_down)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_priority_window(0)
    return game


def _on(game: Game, seat: int, name: str) -> Permanent:
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _cast(game: Game, name: str, **kwargs) -> None:
    assert game.cast_from_hand(0, name, **kwargs).supported, game.log[-4:]
    resolve_stack(game)


# -- tokens: CR 111.4's name already ends in "Token" -------------------------


def test_a_token_named_for_its_type_is_not_called_a_token_twice():
    """"Create a 3/3 green Elephant creature token": CR 111.4 names it
    "Elephant Token", so the line reads "an Elephant Token" — the name and its
    article, never the noun again."""
    game = _table(hand=["Call of the Herd", "Grizzly Fate"])

    _cast(game, "Call of the Herd")
    _cast(game, "Grizzly Fate")

    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Bear Token", "Bear Token", "Elephant Token",
    ]
    assert "Call of the Herd created an Elephant Token" in game.log, game.log[-6:]
    assert "Grizzly Fate created 2 Bear Tokens" in game.log, game.log[-6:]
    assert not any(re.search(r"\btoken tokens?\b", line, re.I) for line in game.log)


# -- choices: a colour and a type said as a player says them -----------------


def test_a_chosen_colour_is_said_as_the_colour():
    """Distorting Lens names its colour as it resolves (CR 608.2d) and City of
    Brass is asked for one as it is tapped: each line says the colour or the
    mana symbol a card prints, never the record's bare letter."""
    game = _table(mine=["Distorting Lens", "City of Brass"], theirs=["Grizzly Bears"])
    bears = _on(game, 1, "Grizzly Bears")

    assert game.activate_permanent_ability(
        0, "Distorting Lens", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)
    assert game.tap_land_for_mana(0, "City of Brass", chosen_color="R")

    assert any(
        re.fullmatch(
            r"Grizzly Bears became (white|blue|black|red|green) until end of turn "
            r"\(Distorting Lens\)", line,
        ) for line in game.log
    ), game.log[-6:]
    assert "City of Brass produced {R}" in game.log, game.log[-6:]
    assert not any(re.search(r"\b(became|chose) [WUBRG]\b", line) for line in game.log)
    assert not any(re.search(r"\b\d+ [WUBRGC] mana\b", line) for line in game.log)


def test_a_chosen_creature_type_is_said_as_a_type_line_prints_it():
    """Defensive Maneuvers' seat nobody asks names the type of its own Goblins
    (CR 205.3m), and says it as a type line prints it."""
    game = _table(hand=["Defensive Maneuvers"], mine=["Goblin Sky Raider", "Goblin King"])

    _cast(game, "Defensive Maneuvers")

    assert "Defensive Maneuvers: chose Goblin" in game.log, game.log[-6:]
    raider = _on(game, 0, "Goblin Sky Raider")
    assert raider.effective_toughness == 2 + 1 + 4  # printed, the King, the spell


# -- P/T: a shrink is not a buff ---------------------------------------------


def test_bane_of_the_living_gives_everything_minus_x_and_says_so():
    """"All creatures get -X/-X until end of turn" (CR 702.37f's X, announced
    as the special action is taken): the line says how much, signed, and to
    how many — "buffed matching creatures" said neither and called it a buff."""
    game = _table(
        mine=["fd:Bane of the Living", "Swamp", "Swamp", "Swamp", "Swamp"],
        theirs=["Grizzly Bears", "Hill Giant"],
    )
    game.enforce_mana_costs = True
    bane = next(p for p in game.controlled_by(0) if p.is_creature)

    assert take_permanent_special_action(game, 0, bane, "turn_face_up", x_value=2) is None
    resolve_stack(game)
    game.check_state_based_actions()

    assert "Bane of the Living gives 3 creature(s) -2/-2 until end of turn" in game.log, (
        game.log[-8:]
    )
    assert not any("buffed" in line for line in game.log)
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_hell_swarm_is_a_minus_one_and_not_a_buff():
    game = _table(hand=["Hell Swarm"], theirs=["Grizzly Bears", "Hill Giant"])

    _cast(game, "Hell Swarm")

    # Signed by the format, as every pump line is: "-1/+0".
    assert "Hell Swarm gives 2 creature(s) -1/+0 until end of turn" in game.log, game.log[-4:]
    assert _on(game, 1, "Hill Giant").effective_power == 2


# -- what came back, and what brought it -------------------------------------


def test_a_reanimation_names_the_card_and_what_returned_it():
    game = _table(hand=["Resurrection"], graveyard=["Serra Angel"])

    _cast(game, "Resurrection")

    assert _on(game, 0, "Serra Angel")
    assert (
        "Resurrection returned Serra Angel from a graveyard to the battlefield" in game.log
    ), game.log[-6:]
    assert not any(line.startswith("Reanimated ") for line in game.log)


def test_a_bounce_names_the_creature_it_returned():
    game = _table(hand=["Unsummon"], theirs=["Grizzly Bears"])
    bears = _on(game, 1, "Grizzly Bears")

    _cast(game, "Unsummon", target_player_index=1, target_permanent_ids=[bears.permanent_id])

    assert [card.name for card in game.players[1].hand] == ["Grizzly Bears"]
    assert "Grizzly Bears returned to its owner's hand (Unsummon)" in game.log, game.log[-4:]
    assert "Returned creature to hand" not in game.log


# -- the object a trigger is about is not its target -------------------------


def test_toxin_slivers_creature_left_the_battlefield_it_was_not_a_target():
    """"Whenever a Sliver deals combat damage to a creature, destroy that
    creature." The Bears die of the 3 damage first (CR 704.5g); the trigger
    then finds them gone. Nothing was targeted (CR 115.10a), so CR 608.2b
    judged nothing: the creature left the battlefield (CR 400.7)."""
    game = _table(mine=["Toxin Sliver"], theirs=["Grizzly Bears"])
    sliver = _on(game, 0, "Toxin Sliver")
    bears_slot = next(
        slot for slot, p in enumerate(game.players[1].battlefield)
        if p.card.name == "Grizzly Bears"
    )
    attacker_slot = game.players[0].battlefield.index(sliver)

    declare_attack(game, 0, blocks={bears_slot: attacker_slot})
    game.advance_combat_phase()
    resolve_stack(game)

    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert "Grizzly Bears died (704.5g: lethal damage)" in game.log, game.log[-8:]
    assert (
        "Toxin Sliver: that permanent has left the battlefield (400.7)" in game.log
    ), game.log[-8:]
    assert not any("Toxin Sliver: its target is gone" in line for line in game.log)


def test_a_targeted_ability_whose_target_left_still_says_so():
    """The other half: Royal Assassin *targets*, so a target gone by
    resolution is CR 608.2b's, and the line says that."""
    game = _table(mine=["Royal Assassin"], theirs=["Grizzly Bears"])
    bears = _on(game, 1, "Grizzly Bears")
    bears.tapped = True

    assert game.queue_permanent_ability(
        0, "Royal Assassin", target_player_index=1, ability_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.stack
    game._destroy_swept_permanents(game.players[1], lambda perm: perm is bears)
    resolve_stack(game)

    assert (
        "Royal Assassin ability was removed from the stack: every target is illegal (608.2b)"
        in game.log
    ), game.log[-6:]
    assert not any("left the battlefield (400.7)" in line for line in game.log)


# -- damage names both ends ---------------------------------------------------


def test_damage_to_a_player_names_the_player_and_the_source():
    game = _table(hand=["Lightning Bolt"], mine=["Goblin Dynamo"])

    assert game.activate_permanent_ability(0, "Goblin Dynamo", target_player_index=1).supported
    resolve_stack(game)
    _cast(game, "Lightning Bolt", target_player_index=1)

    assert game.players[1].life == 16
    assert "Goblin Dynamo dealt 1 damage to P2" in game.log, game.log[-6:]
    assert "Lightning Bolt dealt 3 damage to P2" in game.log, game.log[-6:]
    assert not any(re.search(r"dealt \d+ damage$", line) for line in game.log)
    assert not any(re.search(r"^P\d took \d+ damage$", line) for line in game.log)


# -- "died" is a graveyard (CR 700.4) ----------------------------------------


def test_a_creature_exiled_instead_of_dying_is_not_said_to_have_died():
    """Disintegrate: "If the creature would die this turn, exile it instead."
    The lethal-damage sweep destroys it (CR 704.5g) and the replacement sends
    it to exile — so it did not die (CR 700.4), and the sweep's line says it
    was destroyed."""
    game = _table(hand=["Disintegrate"], theirs=["Birds of Paradise"])
    birds = _on(game, 1, "Birds of Paradise")

    _cast(
        game, "Disintegrate", target_player_index=1,
        target_permanent_ids=[birds.permanent_id], x_value=1,
    )

    assert [card.name for card in game.players[1].exile] == ["Birds of Paradise"]
    assert "Birds of Paradise was exiled instead of dying" in game.log, game.log[-6:]
    assert "Birds of Paradise was destroyed (704.5g: lethal damage)" in game.log, game.log[-6:]
    assert not any(line.startswith("Birds of Paradise died") for line in game.log)


# -- a step is complete when its window has drained (CR 500.2) ---------------


def test_declare_attackers_step_complete_follows_its_attack_trigger():
    """Vicious Kavu's attack trigger goes on the stack in the declare
    attackers step and resolves in its window; the step is complete only once
    that window has drained (CR 500.2), so its line comes after the trigger's
    resolution — it was written as the declaration locked, in every game."""
    game = _table(mine=["Vicious Kavu"])
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    kavu = _on(game, 0, "Vicious Kavu")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(kavu)], defending_player_index=1,
    )
    assert ok, why
    game.advance_combat_phase()

    assert game.current_step != "declare_attackers", game.log[-6:]
    gets = next(
        i for i, line in enumerate(game.log) if line.startswith("Vicious Kavu gets +2/+0")
    )
    complete = game.log.index("Declare attackers step complete: 1 creature(s) attacking")
    assert gets < complete, game.log[-8:]


def test_a_step_cr_508_8_skips_is_not_said_to_have_completed():
    """No creature attacked: CR 508.8 skips the declare blockers step, which
    is said once, with the attack's reason, and not then called complete."""
    game = _table(mine=["Plains"], theirs=["Grizzly Bears"])
    game._close_current_priority_step()
    for _ in range(4):
        if game.current_turn_phase == "combat" and game.current_step == "end_of_combat":
            break
        game.advance_combat_phase()

    assert "P1 has no valid attackers" in game.log, game.log[-6:]
    assert "No attackers; declare blockers step skipped (508.8)" in game.log, game.log[-6:]
    assert "Declare attackers step complete: 0 creature(s) attacking" in game.log
    assert not any(line.startswith("Declare blockers step complete") for line in game.log)
    assert not any("has no valid blockers" in line for line in game.log)

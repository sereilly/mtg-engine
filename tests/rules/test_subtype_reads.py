"""CR 613 layer 4 — a creature *type* is computed, not printed.

``Permanent.has_type`` resolves through the layer system, so a creature that
became a Wall is one and a printed Wall that stopped being one is not. Four
places in the engine asked the same question of ``card.type_line`` instead —
the text as printed, which no effect can change — and the two answers disagree
for anything whose type is granted.

The disagreement was in *one function*: ``_can_block_attacker`` tested
Juggernaut's "can't be blocked by Walls" against the printed line and
Invisibility's "can't be blocked except by Walls" against ``has_type``, three
lines apart. Primal Clay's third body is the creature that tells them apart.
"""

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent

_CATALOG = {c.name: c for c in load_catalog()}


def _wall_bodied_clay(game: Game, seat: int) -> Permanent:
    """A Primal Clay whose controller chose the 1/6 Wall body."""
    game.interactive_seats = {seat}
    game.players[seat].hand = [_CATALOG["Primal Clay"]]
    game.queue_from_hand(seat, "Primal Clay")
    game.resolve_top_of_stack()
    clay = game.players[seat].battlefield[-1]
    assert game.confirm_enter_body_choice(seat, 2)
    assert clay.has_type("wall")
    clay.metadata["summoning_sickness_turn"] = -99
    return clay


def _duel() -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


@pytest.mark.cr("613.1d", "509.1b")
def test_a_creature_that_became_a_wall_cannot_block_a_juggernaut():
    """"This creature can't be blocked by Walls." The restriction is about what
    the blocker *is* (CR 613 layer 4), not about what its card says."""
    game, p1, _p2 = _duel()
    juggernaut = Permanent(card=_CATALOG["Juggernaut"])
    juggernaut.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(juggernaut)
    clay = _wall_bodied_clay(game, 1)

    assert not game._can_block_attacker(clay, juggernaut)


@pytest.mark.cr("613.1d", "509.1b")
def test_the_same_creature_on_another_body_can_block_it():
    """The control: the 3/3 body is no Wall, so the restriction does not reach
    it. Without this the test above would pass for a Clay that simply could not
    block anything."""
    game, p1, p2 = _duel()
    juggernaut = Permanent(card=_CATALOG["Juggernaut"])
    juggernaut.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(juggernaut)
    game.interactive_seats = {1}
    p2.hand = [_CATALOG["Primal Clay"]]
    game.queue_from_hand(1, "Primal Clay")
    game.resolve_top_of_stack()
    clay = p2.battlefield[-1]
    assert game.confirm_enter_body_choice(1, 0)
    clay.metadata["summoning_sickness_turn"] = -99

    assert not clay.has_type("wall")
    assert game._can_block_attacker(clay, juggernaut)


@pytest.mark.cr("613.1d")
def test_a_granted_wall_is_a_legal_target_for_an_ability_that_wants_one():
    """Ali Baba: "{R}: Tap target Wall." The picker and the resolution both ask
    the layer system, so a granted Wall is offered and accepted."""
    game, p1, p2 = _duel()
    ali = Permanent(card=_CATALOG["Ali Baba"])
    ali.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(ali)
    clay = _wall_bodied_clay(game, 1)

    game.activate_permanent_ability(
        0, "Ali Baba", target_player_index=1, target_permanent_index=0
    )
    game._settle()

    assert clay.tapped


@pytest.mark.cr("613.1d")
def test_a_granted_wall_is_not_a_legal_non_wall_target():
    """The mirror question, and the one the printed read got backwards in the
    other direction: Nettling Imp's "target **non-Wall** creature" must decline
    a creature that became a Wall.
    """
    game, p1, p2 = _duel()
    imp = Permanent(card=_CATALOG["Nettling Imp"])
    imp.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(imp)
    clay = _wall_bodied_clay(game, 1)

    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(imp.card)
    instruction = next(
        ability.instruction
        for ability in program.activated_abilities
        if ability.instruction is not None
        and ability.instruction.kind == "mark_non_wall_target_to_attack"
    )

    assert not game._ability_target_legal(instruction, clay)


# ---------------------------------------------------------------------------
# Layer 5 — a colour is computed too
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.1e", "601.2c")
def test_a_laced_creature_is_offered_to_a_colour_targeted_ability():
    """Deathlace makes a Grizzly Bears black; Northern Paladin destroys target
    black permanent.

    The *resolution* asked layer 5 and accepted it. The **picker** — the
    enumerator the UI runs to decide what a player may click — asked the printed
    colours and offered nothing. So the engine had two answers to one question,
    and which one you got depended on whether you were a person or a script.
    """
    game, p1, p2 = _duel()
    paladin = Permanent(card=_CATALOG["Northern Paladin"])
    paladin.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(paladin)
    bears = Permanent(card=_CATALOG["Grizzly Bears"])
    p2.battlefield.append(bears)
    p1.hand = [_CATALOG["Deathlace"]]

    game.cast_from_hand(0, "Deathlace", target_player_index=1, target_permanent_index=0)
    game._settle()
    assert bears.effective_colors == {"B"}

    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    spec = dict(derive_activation_spec(
        compile_card_oracle(paladin.card).activated_abilities[0]
    ))
    kind = spec.pop("kind")
    offered = game.enumerate_targets_for_kind(0, paladin.card, kind, **spec)

    assert [entry["name"] for entry in offered] == ["Grizzly Bears"]


@pytest.mark.cr("613.1e")
def test_an_unlaced_creature_is_not_offered():
    """The control: without the lace the Bears are green and the picker is
    empty, so the test above is about layer 5 and not about the enumerator
    offering everything."""
    game, p1, p2 = _duel()
    paladin = Permanent(card=_CATALOG["Northern Paladin"])
    paladin.metadata["summoning_sickness_turn"] = -99
    p1.battlefield.append(paladin)
    p2.battlefield.append(Permanent(card=_CATALOG["Grizzly Bears"]))

    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    spec = dict(derive_activation_spec(
        compile_card_oracle(paladin.card).activated_abilities[0]
    ))
    kind = spec.pop("kind")

    assert game.enumerate_targets_for_kind(0, paladin.card, kind, **spec) == []


@pytest.mark.cr("613.1d", "702.3")
def test_animate_wall_may_enchant_a_creature_that_became_a_wall():
    """"Enchant Wall" is a question about the permanent. Primal Clay's third
    body is a Wall, so Animate Wall attaches to it — the Aura's own target
    search asked the printed line and refused."""
    game, p1, _p2 = _duel()
    clay = _wall_bodied_clay(game, 0)
    p1.hand = [_CATALOG["Animate Wall"]]

    game.cast_from_hand(0, "Animate Wall", target_player_index=0, target_permanent_index=0)
    game._settle()

    attached = [
        perm for perm in game.controlled_by(0)
        if perm.metadata.get("attached_to") is clay
    ]
    assert [perm.card.name for perm in attached] == ["Animate Wall"]

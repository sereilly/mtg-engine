"""CR 613 — the continuous-effect layer system.

Tested against the rule text and its worked examples rather than against
particular cards, because the point of the layer system is that it settles
interactions the cards were never designed together for.
"""

from __future__ import annotations

import pytest

from engine.continuous import (
    Characteristics,
    ContinuousEffect,
    LAYER_ABILITY,
    LAYER_PT,
    add_types,
    apply_layers,
    change_control,
    grant_abilities,
    modify_pt,
    remove_abilities,
    scope_only,
    set_colors,
    set_pt,
    switch_pt,
)


def _state(**objects: Characteristics) -> dict[int, Characteristics]:
    """A board keyed by small integer ids, so tests can name their objects."""
    return {int(name.lstrip("o")): char for name, char in objects.items()}


def _creature(power: int, toughness: int, **kwargs) -> Characteristics:
    return Characteristics(
        card_types={"creature"}, power=power, toughness=toughness, **kwargs
    )


def _everything(oid, state):
    return True


def _creatures(oid, state):
    return "creature" in state[oid].card_types


# ---------------------------------------------------------------------------
# 613.4 — layer 7 sublayer order
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.4b", "613.4c")
def test_a_set_effect_applies_before_a_modification_whatever_the_timestamp():
    """7b before 7c, even when the modification is older. Applying them in
    timestamp order would let the set effect wipe out the +1/+1."""
    state = _state(o1=_creature(2, 2))
    effects = [
        modify_pt(scope_only(1), 1, 1, timestamp=1, label="+1/+1"),
        set_pt(scope_only(1), 0, 2, timestamp=5, label="base 0/2"),
    ]
    apply_layers(effects, state)
    assert (state[1].power, state[1].toughness) == (1, 3)


@pytest.mark.cr("613.4a", "613.4b")
def test_a_characteristic_defining_ability_applies_before_a_set_effect():
    state = _state(o1=_creature(None, None))
    effects = [
        set_pt(scope_only(1), 7, 7, timestamp=9, label="base 7/7"),
        set_pt(scope_only(1), 3, 3, timestamp=1, from_cda=True, label="CDA */*"),
    ]
    apply_layers(effects, state)
    assert (state[1].power, state[1].toughness) == (7, 7)


@pytest.mark.cr("613.4d")
def test_a_switch_applies_last_and_two_switches_cancel():
    state = _state(o1=_creature(1, 4))
    apply_layers([switch_pt(scope_only(1), timestamp=1)], state)
    assert (state[1].power, state[1].toughness) == (4, 1)

    state = _state(o1=_creature(1, 4))
    apply_layers(
        [switch_pt(scope_only(1), timestamp=1), switch_pt(scope_only(1), timestamp=2)],
        state,
    )
    assert (state[1].power, state[1].toughness) == (1, 4)


@pytest.mark.cr("613.4c", "613.4d")
def test_a_switch_uses_the_values_after_modifications():
    """613.4d: the switch takes the values as they stand in 7d, so a +3/+0 in
    7c is included in what gets swapped."""
    state = _state(o1=_creature(1, 4))
    effects = [
        switch_pt(scope_only(1), timestamp=1),
        modify_pt(scope_only(1), 3, 0, timestamp=2),
    ]
    apply_layers(effects, state)
    assert (state[1].power, state[1].toughness) == (4, 4)


@pytest.mark.cr("613.4c")
def test_modifications_are_commutative_and_all_apply():
    state = _state(o1=_creature(1, 1))
    effects = [
        modify_pt(scope_only(1), 1, 1, timestamp=1),
        modify_pt(scope_only(1), 2, 0, timestamp=2),
        modify_pt(scope_only(1), 0, 3, timestamp=3),
    ]
    apply_layers(effects, state)
    assert (state[1].power, state[1].toughness) == (4, 5)


# ---------------------------------------------------------------------------
# 613.7 — timestamp order
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.7", "613.9")
def test_gaining_and_losing_an_ability_resolves_by_timestamp():
    """CR 613.9's worked example: an Aura granting flying and one removing it
    do not depend on each other, so the later timestamp wins — in either
    direction."""
    state = _state(o1=_creature(2, 2))
    apply_layers(
        [
            grant_abilities(scope_only(1), ["flying"], timestamp=1),
            remove_abilities(scope_only(1), ["flying"], timestamp=2),
        ],
        state,
    )
    assert "flying" not in state[1].abilities

    state = _state(o1=_creature(2, 2))
    apply_layers(
        [
            remove_abilities(scope_only(1), ["flying"], timestamp=1),
            grant_abilities(scope_only(1), ["flying"], timestamp=2),
        ],
        state,
    )
    assert "flying" in state[1].abilities


@pytest.mark.cr("613.7b")
def test_later_set_effects_win_within_a_sublayer():
    state = _state(o1=_creature(2, 2))
    apply_layers(
        [
            set_pt(scope_only(1), 0, 2, timestamp=1),
            set_pt(scope_only(1), 5, 5, timestamp=2),
        ],
        state,
    )
    assert (state[1].power, state[1].toughness) == (5, 5)


# ---------------------------------------------------------------------------
# 613.1 — cross-layer ordering
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.1e", "613.9")
def test_a_colour_change_feeds_an_anthem_that_keys_on_colour():
    """CR 613.9's second worked example: "White creatures get +1/+1" and
    "Enchanted creature is white" — the creature gets the bonus regardless of
    its previous colour, because layer 5 runs before layer 7."""
    state = _state(o1=_creature(2, 2, colors={"B"}))

    def white_creatures(oid, board):
        return "creature" in board[oid].card_types and "W" in board[oid].colors

    apply_layers(
        [
            modify_pt(white_creatures, 1, 1, timestamp=1, label="white anthem"),
            set_colors(scope_only(1), ["W"], timestamp=2, label="is white"),
        ],
        state,
    )
    assert state[1].colors == {"W"}
    assert (state[1].power, state[1].toughness) == (3, 3)


@pytest.mark.cr("613.1d", "613.1g")
def test_animating_a_land_lets_a_creature_anthem_reach_it():
    """Layer 4 makes the land a creature; layer 7 then sees a creature. The
    old flag-based order could only get this right by being written in the
    right sequence by hand."""
    state = _state(
        o1=Characteristics(card_types={"land"}, subtypes={"swamp"}),
        o2=_creature(2, 2),
    )
    apply_layers(
        [
            modify_pt(_creatures, 1, 1, timestamp=5, label="anthem"),
            add_types(scope_only(1), card_types=["creature"], timestamp=1, label="animate"),
            set_pt(scope_only(1), 1, 1, timestamp=1, label="1/1"),
        ],
        state,
    )
    assert "creature" in state[1].card_types
    assert (state[1].power, state[1].toughness) == (2, 2)
    assert (state[2].power, state[2].toughness) == (3, 3)


@pytest.mark.cr("613.1b")
def test_control_change_applies_before_effects_that_key_on_controller():
    state = _state(o1=_creature(1, 1, controller_index=1), o2=_creature(1, 1, controller_index=0))

    def mine(oid, board):
        return board[oid].controller_index == 0

    apply_layers(
        [
            modify_pt(mine, 2, 2, timestamp=9, label="creatures you control"),
            change_control(scope_only(1), 0, timestamp=1, label="gain control"),
        ],
        state,
    )
    assert (state[1].power, state[1].toughness) == (3, 3)
    assert (state[2].power, state[2].toughness) == (3, 3)


# ---------------------------------------------------------------------------
# 613.8 — dependency
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.8a", "613.8b")
def test_a_dependent_effect_waits_even_though_its_timestamp_is_earlier():
    """The classic shape: one effect changes what the other applies to, inside
    the same layer. Timestamp says the anthem goes first; dependency says it
    must wait until the type change has happened.
    """
    state = _state(o1=Characteristics(card_types={"land"}, subtypes={"swamp"}))

    def creatures(oid, board):
        return "creature" in board[oid].card_types

    def modify(char):
        char.subtypes.add("zombie")

    anthem = ContinuousEffect(
        layer=4, modify=modify, applies_to=creatures, timestamp=1, label="creatures are Zombies",
    )
    animate = add_types(
        scope_only(1), card_types=["creature"], timestamp=2, label="lands are creatures"
    )
    apply_layers([anthem, animate], state)
    assert "zombie" in state[1].subtypes, "the dependent effect must apply after the type change"


@pytest.mark.cr("613.8a")
def test_an_effect_never_depends_on_a_characteristic_defining_ability():
    """613.8a(c): unless both are CDAs. Here only one is, so timestamp order
    stands and the CDA's earlier sublayer decides."""
    state = _state(o1=_creature(None, None))
    cda = set_pt(scope_only(1), 4, 4, timestamp=9, from_cda=True)
    setter = set_pt(scope_only(1), 1, 1, timestamp=1)
    apply_layers([cda, setter], state)
    # 7a applies first, then 7b overwrites — the CDA does not "win" by being
    # newer, because sublayers outrank timestamps.
    assert (state[1].power, state[1].toughness) == (1, 1)


@pytest.mark.cr("613.8b")
def test_a_dependency_loop_falls_back_to_timestamp_order():
    """Two effects that each change what the other applies to. The rule says
    stop trying and use timestamps, which must terminate rather than spin."""
    state = _state(
        o1=Characteristics(card_types={"land"}, subtypes={"swamp"}),
        o2=Characteristics(card_types={"land"}, subtypes={"forest"}),
    )

    def swamps_become_forests(char):
        char.subtypes = {"forest"}

    def forests_become_swamps(char):
        char.subtypes = {"swamp"}

    first = ContinuousEffect(
        layer=4, modify=swamps_become_forests,
        applies_to=lambda oid, b: "swamp" in b[oid].subtypes, timestamp=1, label="swamps->forests",
    )
    second = ContinuousEffect(
        layer=4, modify=forests_become_swamps,
        applies_to=lambda oid, b: "forest" in b[oid].subtypes, timestamp=2, label="forests->swamps",
    )
    apply_layers([first, second], state)
    # Both lands end up Swamps: the earlier effect turns the Swamp into a
    # Forest, then the later turns every Forest into a Swamp.
    assert state[1].subtypes == {"swamp"}
    assert state[2].subtypes == {"swamp"}


@pytest.mark.cr("613.8c")
def test_ordering_is_reevaluated_after_each_application():
    """An effect's scope is re-evaluated as the state changes, so an object
    that only becomes eligible partway through the layer is still caught.

    Asserted on the resulting state rather than by counting calls: ``modify``
    is applied speculatively while probing dependency, so call counts are not
    observable behavior.
    """
    state = _state(o1=Characteristics(card_types={"land"}), o2=_creature(1, 1))

    def brand(char):
        char.subtypes.add("branded")

    animate = add_types(scope_only(1), card_types=["creature"], timestamp=3, label="animate")
    watcher = ContinuousEffect(
        layer=4, modify=brand, applies_to=_creatures, timestamp=1, label="brand creatures",
    )
    apply_layers([watcher, animate], state)

    # The land only becomes a creature during this layer; the branding still
    # reaches it because it waited on the effect it depends on.
    assert "branded" in state[1].subtypes
    assert "branded" in state[2].subtypes


# ---------------------------------------------------------------------------
# 613.1b — layer 2 (control) is live: control is a recorded contribution
# ---------------------------------------------------------------------------


def _bear_board():
    from engine import Game, PlayerState
    from engine.models import CardDefinition, Permanent

    def _card(name: str) -> CardDefinition:
        return CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line="Creature — Bear", oracle_text="",
            colors=(), color_identity=(), keywords=(), produced_mana=(),
            raw={"name": name, "type_line": "Creature — Bear", "power": "2", "toughness": "2"},
            power="2", toughness="2",
        )

    bear = Permanent(card=_card("Bear"))
    thief_a = Permanent(card=_card("Thief A"))
    thief_b = Permanent(card=_card("Thief B"))
    mine = PlayerState(name="P1", battlefield=[bear], life=20)
    theirs = PlayerState(name="P2", battlefield=[thief_a, thief_b], life=20)
    return Game(players=[mine, theirs]), bear, thief_a, thief_b


@pytest.mark.cr("613.1b")
def test_a_control_change_is_a_recorded_effect_not_a_move():
    """Layer 2 is collected into the system like every other layer: the effect
    is recorded on the permanent with its source, and the battlefield lists are
    the *projection* of what the layer says — not the storage for it."""
    from engine.control import control_changes, has_control_change

    game, bear, thief, _ = _bear_board()
    assert game.controller_index_of(bear) == 0
    assert not has_control_change(bear)

    assert game.take_control(bear, 1, source=thief)

    assert game.controller_index_of(bear) == 1
    assert [entry["source"] for entry in control_changes(bear)] == [thief]
    # The projection agrees, so every reader behind the seam sees it too.
    assert [p for p in game.controlled_by(1) if p is bear]
    assert not [p for p in game.controlled_by(0) if p is bear]


@pytest.mark.cr("613.7")
def test_the_later_control_effect_wins():
    """Two effects in the same layer are ordered by timestamp, so the newer
    theft decides — not whichever code path happened to run last."""
    game, bear, thief_a, thief_b = _bear_board()

    assert game.take_control(bear, 1, source=thief_a)
    assert game.take_control(bear, 0, source=thief_b)
    assert game.controller_index_of(bear) == 0

    # Re-recording from the older source takes a *fresh* timestamp, which is
    # what makes it the later effect and hands control back.
    assert game.take_control(bear, 1, source=thief_a)
    assert game.controller_index_of(bear) == 1


@pytest.mark.cr("613.7", "611.3")
def test_ending_one_control_effect_leaves_the_other_applying():
    """The bug that motivated wiring the layer. With two thefts recorded and
    the *older* one ended first, remember-and-undo handed the permanent to the
    seat the newer thief had stored as "previous controller" — a seat that by
    then controlled nothing giving it. A contribution ending is an absence:
    whatever is left decides."""
    game, bear, thief_a, thief_b = _bear_board()

    game.take_control(bear, 1, source=thief_a)   # older: P2 takes the bear
    game.take_control(bear, 0, source=thief_b)   # newer: P1 takes it back
    assert game.controller_index_of(bear) == 0

    # The *newer* effect ends first. The older one has not gone anywhere, so
    # P2 controls the bear again — this is the case remember-and-undo could
    # not express, because thief_b's remembered "previous controller" was P2
    # only by coincidence and thief_a's was the seat it had already left.
    game.end_control_changes_from(thief_b)
    assert game.controller_index_of(bear) == 1

    # And ending the last one returns it to the base controller, not to
    # whichever seat happened to hold it before the most recent theft.
    game.end_control_changes_from(thief_a)
    assert game.controller_index_of(bear) == 0


@pytest.mark.cr("613.1b", "108.3")
def test_the_base_controller_survives_every_theft():
    """CR 613 applies layers to *copiable* values; for control that is the seat
    the permanent entered under. Keeping it separate from the current
    controller is what lets an ended effect revert correctly — and it is the
    same value CR 108.3 ownership reads when a stolen permanent dies."""
    from engine.control import base_controller

    game, bear, thief_a, thief_b = _bear_board()
    game.take_control(bear, 1, source=thief_a)
    game.take_control(bear, 1, source=thief_b)

    assert base_controller(bear) == 0
    assert game.owner_index_of(bear) == 0
    assert game.controller_index_of(bear) == 1


@pytest.mark.cr("613.1b")
def test_the_battlefield_lists_never_disagree_with_the_layer():
    """The projection invariant. Every reader migrated onto the seam reads the
    zone lists (``controlled_by``, the web payload's per-seat battlefield), so
    a permanent whose list disagreed with layer 2 would give two answers to the
    same question — the failure mode layer 4's audit found seven of."""
    game, bear, thief_a, thief_b = _bear_board()
    for step in (
        lambda: game.take_control(bear, 1, source=thief_a),
        lambda: game.take_control(bear, 0, source=thief_b),
        lambda: game.end_control_changes_from(thief_b),
        lambda: game.end_control_changes_from(thief_a),
    ):
        step()
        for seat, permanent in game.permanents_with_controller():
            assert game.controller_index_of(permanent) == seat, (
                f"{permanent.card.name} is on seat {seat}'s battlefield but layer 2 "
                f"says {game.controller_index_of(permanent)}"
            )


@pytest.mark.cr("613.1b")
def test_all_permanents_spans_every_battlefield():
    from engine import Game, PlayerState
    from engine.models import CardDefinition, Permanent

    def _card(name: str) -> CardDefinition:
        return CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line="Creature — Bear", oracle_text="",
            colors=(), color_identity=(), keywords=(), produced_mana=(),
            raw={"name": name, "type_line": "Creature — Bear", "power": "2", "toughness": "2"},
            power="2", toughness="2",
        )

    mine = PlayerState(name="P1", battlefield=[Permanent(card=_card("A"))], life=20)
    theirs = PlayerState(name="P2", battlefield=[Permanent(card=_card("B"))], life=20)
    game = Game(players=[mine, theirs])

    assert {perm.card.name for perm in game.all_permanents()} == {"A", "B"}
    assert {index for index, _ in game.permanents_with_controller()} == {0, 1}
    assert [p.card.name for p in game.permanents_matching(lambda p: p.card.name == "B")] == ["B"]


@pytest.mark.cr("613.2a", "613.2c")
def test_a_layer_one_effect_is_refused_rather_than_silently_dropped():
    """613.2c: after layer 1 the object's characteristics *are* its copiable
    values, so layer 1 produces the state this function is handed — it is not
    something applied over it. ``apply_layers`` starts at layer 2, so a layer-1
    effect passed in would be dropped without a word, which is the one way a
    copy could go back to being invisible. Copy effects are recorded in
    ``engine/copies.py`` and folded into the seed."""
    stray = ContinuousEffect(
        layer=1, modify=lambda char: None, applies_to=_everything, label="copy of X",
    )
    with pytest.raises(ValueError, match="engine/copies.py"):
        apply_layers([stray], _state(o1=_creature(2, 2)))

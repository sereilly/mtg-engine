"""Per-card tests for Antiquities' sorceries.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


# ---------------------------------------------------------------------------
# Detonate (round 23) — a target bound to the cast's X
# ---------------------------------------------------------------------------


def _detonate(set_pool, target_name):
    """Detonate in P1's hand, *target_name* on P2's battlefield."""
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", hand=[pool["Detonate"]])
    victim = Permanent(card=pool[target_name])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, victim


def test_detonate_destroys_the_artifact_and_burns_its_controller(set_pool):
    """Su-Chi's mana value is 4, so X is 4 and so is the damage."""
    game, p1, p2, victim = _detonate(set_pool, "Su-Chi")
    life = p2.life

    result = game.cast_from_hand(
        0, "Detonate", target_player_index=1, target_permanent_index=0
    )

    assert result.supported, result.details
    assert "Su-Chi" not in {perm.card.name for perm in p2.battlefield}
    assert p2.life == life - 4, game.log


def test_the_damage_scales_with_the_target_rather_than_being_printed(set_pool):
    """The control on the test above: nothing about Detonate is a fixed 4. An
    Ornithopter costs nothing, so X is 0 and the artifact dies for free."""
    game, p1, p2, victim = _detonate(set_pool, "Ornithopter")
    life = p2.life

    game.cast_from_hand(0, "Detonate", target_player_index=1, target_permanent_index=0)

    assert "Ornithopter" not in {perm.card.name for perm in p2.battlefield}
    assert p2.life == life, "X is 0, and CR 120.8 makes 0 damage no damage at all"


def test_an_x_that_does_not_match_the_target_cannot_be_cast(set_pool):
    """CR 601.2c: "target artifact with mana value X" is one restriction over
    two announcements, and an X naming a value the chosen artifact does not have
    makes the choice illegal — not a spell that resolves and fizzles."""
    game, p1, p2, victim = _detonate(set_pool, "Su-Chi")

    result = game.cast_from_hand(
        0, "Detonate", target_player_index=1, target_permanent_index=0, x_value=1,
    )

    assert not result.supported
    assert "Su-Chi" in {perm.card.name for perm in p2.battlefield}


def test_the_damage_goes_to_the_player_not_the_destroyed_artifact(set_pool):
    """The sentence names a player, and the destroy in front of it leaves a
    permanent index on the resolution context. A damage clause that inferred
    "player" from the *absence* of that index aimed this one at the artifact it
    had just destroyed, and the spell dealt no damage at all."""
    game, p1, p2, victim = _detonate(set_pool, "Su-Chi")

    game.cast_from_hand(0, "Detonate", target_player_index=1, target_permanent_index=0)

    assert any("dealt 4 damage to P2" in entry for entry in game.log), game.log


# ---------------------------------------------------------------------------
# Drafna's Restoration (round 27) — any number of targets, in someone else's
# graveyard
# ---------------------------------------------------------------------------


def _drafna(set_pool, graveyard=("Ornithopter", "Citanul Druid", "Su-Chi")):
    pool = set_pool("ATQ")
    p1 = PlayerState(name="P1", hand=[pool["Drafna's Restoration"]])
    p2 = PlayerState(
        name="P2",
        graveyard=[pool[name] for name in graveyard],
        library=[pool["Ornithopter"]] * 3,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, pool, p1, p2


def test_the_picker_offers_only_artifact_cards_in_the_targets_graveyard(set_pool):
    game, pool, p1, p2 = _drafna(set_pool)

    spec = game.cast_target_spec(0, pool["Drafna's Restoration"])

    assert [t["name"] for t in spec["valid_targets"]] == ["Ornithopter", "Su-Chi"]
    assert {t["seat"] for t in spec["valid_targets"]} == {1}


def test_any_number_caps_at_the_targets_the_picker_found(set_pool):
    """"Any number" prints no maximum, so the only cap is how many legal
    targets there are — a number the lowering cannot know and the enumerator
    can."""
    game, pool, p1, p2 = _drafna(set_pool)

    spec = game.cast_target_spec(0, pool["Drafna's Restoration"])

    assert spec["max_targets"] == 2


def test_the_chosen_cards_go_on_top_in_the_order_they_were_named(set_pool):
    """"…in any order." The targets are chosen in sequence (CR 601.2c) and
    nothing else on the wire could carry an ordering, so the order they were
    named in is the controller's choice of order — first named, top of the
    library."""
    game, pool, p1, p2 = _drafna(set_pool)

    result = game.cast_from_hand(
        0, "Drafna's Restoration",
        target_player_index=1, target_permanent_index=[2, 0],
    )

    assert result.supported, result.details
    assert [card.name for card in p2.graveyard] == ["Citanul Druid"]
    assert [card.name for card in p2.library[:2]] == ["Su-Chi", "Ornithopter"]


def test_a_nonartifact_slot_is_an_illegal_announcement(set_pool):
    """CR 601.2c: naming the Citanul Druid for "target artifact card" is an
    illegal announcement, so the cast is refused with nothing spent and
    nothing moved. This used to be accepted and cleaned up at resolution —
    the graveyard target reached no announcement gate at all — which is the
    laxity the GyRes round in tests/rules/test_targets_and_costs.py closed."""
    game, pool, p1, p2 = _drafna(set_pool)

    result = game.cast_from_hand(
        0, "Drafna's Restoration",
        target_player_index=1, target_permanent_index=[1, 0],
    )

    assert not result.supported
    assert [card.name for card in p1.hand] == ["Drafna's Restoration"]
    assert [card.name for card in p2.graveyard] == [
        "Ornithopter", "Citanul Druid", "Su-Chi",
    ]


def test_a_slot_whose_card_left_in_response_is_dropped_rather_than_moved(set_pool):
    """CR 608.2b's last sentence: a chosen card that left the pile with the
    spell on the stack is simply not moved, and the surviving target still
    goes on top — never the card that slid into the vacated slot."""
    game, pool, p1, p2 = _drafna(set_pool)
    game.queue_from_hand(
        0, "Drafna's Restoration",
        target_player_index=1, target_permanent_index=[2, 0],
    )

    p2.graveyard.pop(2)  # the Su-Chi is exiled in response

    game.resolve_top_of_stack()

    assert [card.name for card in p2.graveyard] == ["Citanul Druid"]
    assert p2.library[0].name == "Ornithopter"


def test_it_reads_the_targets_graveyard_not_the_casters(set_pool):
    """The whole difference from every other graveyard effect in the engine:
    those pop the *caster's* pile, and this one names a player."""
    game, pool, p1, p2 = _drafna(set_pool)
    p1.graveyard = [pool["Su-Chi"]]

    game.cast_from_hand(
        0, "Drafna's Restoration",
        target_player_index=1, target_permanent_index=[0],
    )

    # The spell itself lands in the caster's graveyard on resolution; the Su-Chi
    # that was already there is the one this test is about.
    assert "Su-Chi" in [card.name for card in p1.graveyard]
    assert p1.graveyard[0].name == "Su-Chi", "the caster's pile is not the one read"
    assert p2.library[0].name == "Ornithopter"


# ---------------------------------------------------------------------------
# Transmute Artifact (round 29) — three decisions, each shaping the next
# ---------------------------------------------------------------------------


def _transmute(set_pool, given, library):
    pool = set_pool("ATQ")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Transmute Artifact"]],
        battlefield=[Permanent(card=pool[given])],
        library=[pool[name] for name in library],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1, pool


def _resolve(game):
    game.cast_from_hand(0, "Transmute Artifact")
    game.auto_resolve_pending_choices()


def test_a_cheaper_find_goes_straight_onto_the_battlefield(set_pool):
    """Su-Chi's mana value is 4 and Ornithopter's is 0, so no payment is
    offered at all."""
    game, p1, pool = _transmute(set_pool, "Su-Chi", ["Ornithopter"])

    _resolve(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Ornithopter"]
    assert "Su-Chi" in [card.name for card in p1.graveyard]


def test_a_dearer_find_needs_the_difference_paid(set_pool):
    """The other way round: Ornithopter pays for nothing, Su-Chi costs 4, and a
    seat that cannot pay the difference watches it go to the graveyard."""
    game, p1, pool = _transmute(set_pool, "Ornithopter", ["Su-Chi"])

    _resolve(game)

    assert p1.battlefield == []
    assert "Su-Chi" in [card.name for card in p1.graveyard]


def test_the_search_finds_an_artifact_creature(set_pool):
    """CR 205.2: a card has every type its line names, so Ornithopter is an
    artifact card. `primary_type` picks one type by the order of a list and
    picked "creature", which made this search — and Goblin Artisans' counter —
    blind to every artifact creature in the set."""
    from engine.search_filters import search_matches

    pool = set_pool("ATQ")
    assert search_matches(pool["Ornithopter"], {"card_type": "artifact"})
    assert not search_matches(pool["Ornithopter"], {"card_type": "land"})


def test_nothing_happens_without_an_artifact_to_give_up(set_pool):
    """"Sacrifice an artifact. **If you do**, …" — no artifact, no search."""
    pool = set_pool("ATQ")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Transmute Artifact"]],
        library=[pool["Su-Chi"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False

    _resolve(game)

    assert p1.battlefield == []
    assert [card.name for card in p1.library] == ["Su-Chi"]


def test_the_declined_payment_still_moves_the_card(set_pool):
    """A decline is an answer, and this one has a consequence: "If you don't,
    put it into its owner's graveyard." The non-interactive default read the
    legacy damage field alone and dropped the branch, so the found card
    vanished out of the game instead."""
    game, p1, pool = _transmute(set_pool, "Ornithopter", ["Su-Chi"])

    _resolve(game)

    assert "Su-Chi" not in [card.name for card in p1.library]
    assert "Su-Chi" in [card.name for card in p1.graveyard]

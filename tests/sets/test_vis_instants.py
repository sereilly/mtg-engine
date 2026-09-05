"""Per-card tests for Visions' instants.

See tests/sets/README.md for the convention: get cards through
``set_pool("VIS")`` / ``set_cards("VIS")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. A branch that added an import to a shared header loses it in the
mechanical "take ours, append the branch's block" merge — a ``NameError`` at
collection, found only after the merge is committed. A self-contained block
cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block.
"""

from __future__ import annotations


# --- W1G2: phasing as an effect, and the land-play prohibition ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g2_game(*battlefields):
    game = Game(players=[
        PlayerState(name=f"P{i + 1}", battlefield=list(bf))
        for i, bf in enumerate(battlefields)
    ])
    game.enforce_mana_costs = False
    return game


def _w1g2_creature(name: str, keywords=()) -> CardDefinition:
    text = "\n".join(k.title() for k in keywords)
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=tuple(
            k.title() for k in keywords
        ),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": "1", "toughness": "1"},
    )


def _w1g2_tide_board(set_pool):
    """A phaser and a plain creature out; a third creature already phased out."""
    phaser = Permanent(card=_w1g2_creature("Phaser", keywords=("phasing",)))
    plain = Permanent(card=_w1g2_creature("Plain"))
    away = Permanent(card=_w1g2_creature("Away"))
    game = _w1g2_game([phaser, plain], [])
    game.players[0].phased_out.append(away)
    away.metadata["phased_out"] = True
    game.players[0].hand = [set_pool("VIS")["Time and Tide"]]
    game._recompute_continuous_effects()
    return game, phaser, plain, away


def test_time_and_tide_swaps_both_sets_of_creatures(set_pool):
    """"Simultaneously, all phased-out creatures phase in and all creatures
    with phasing phase out." (CR 702.26.)"""
    game, phaser, plain, away = _w1g2_tide_board(set_pool)

    result = game.cast_from_hand(0, "Time and Tide")
    assert result.supported, result.details
    game.resolve_stack()

    assert game.is_on_battlefield(away), "the phased-out creature came back"
    assert not game.is_on_battlefield(phaser), "the phaser went away"
    assert game.is_on_battlefield(plain), "no phasing, so it stayed"


def test_time_and_tide_reads_both_sets_before_it_applies_either(set_pool):
    """The printed adverb, and the only thing it buys.

    A creature with phasing that is *already* phased out comes back — and must
    not be swept straight out again by the sentence's other half, which read the
    board before it arrived. Applying the two halves in order gets this wrong in
    a way nothing else would notice: the creature simply never returns.
    """
    game, phaser, _plain, _away = _w1g2_tide_board(set_pool)
    # Send the phaser away first, so the incoming half is what brings it back.
    game.phase_out_permanent(phaser)
    assert phaser in game.players[0].phased_out

    game.cast_from_hand(0, "Time and Tide")
    game.resolve_stack()

    assert game.is_on_battlefield(phaser), (
        "it was phased out when the sets were read, so it phases in and stays"
    )


def test_solfatara_stops_its_target_playing_a_land_this_turn(set_pool):
    """"Target player can't play lands this turn." (CR 305.1.)

    The card reported **supported** before this round on its second line alone
    ("Draw a card at the beginning of the next turn's upkeep"), which is what
    made it invisible to the census: a card is supported when any of its lines
    is. Its first line produced no instruction at all, so it also had no cast
    picker — the client sent a bare cast and the engine refused it.
    """
    game = _w1g2_game([], [])
    game.players[0].hand = [set_pool("VIS")["Solfatara"]]
    game.players[1].hand = [set_pool("LEA")["Forest"]]
    assert game._may_play_another_land(1)

    result = game.cast_from_hand(0, "Solfatara", target_player_index=1)
    assert result.supported, result.details
    game.resolve_stack()

    assert not game._may_play_another_land(1)
    assert game._may_play_another_land(0), "only the target"


def test_solfatara_s_prohibition_ends_with_the_turn(set_pool):
    """"…**this turn**." The record is cleared at the turn boundary, beside the
    land-drop count it modifies."""
    game = _w1g2_game([], [])
    game.players[0].hand = [set_pool("VIS")["Solfatara"]]
    game.cast_from_hand(0, "Solfatara", target_player_index=1)
    game.resolve_stack()
    assert not game._may_play_another_land(1)

    game.start_turn(1)

    assert game._may_play_another_land(1)


def test_solfatara_offers_a_player_picker(set_pool):
    """The other half of the Roots class. ``derive_cast_spec`` reads the
    *compiled program*, so a line that lowered to nothing left the card with no
    picker — which is the exact value the client tests before asking for a
    target."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = set_pool("VIS")["Solfatara"]
    spec = derive_cast_spec(card, compile_card_oracle(card))
    assert spec is not None
    assert spec.get("kind") == "player"


def _w1g2_charm_board(set_pool, *, interactive=frozenset()):
    """A Forest for the caster, an Island and a Mountain for the opponent."""
    lea = set_pool("LEA")
    forest = Permanent(card=lea["Forest"])
    island = Permanent(card=lea["Island"])
    mountain = Permanent(card=lea["Mountain"])
    game = _w1g2_game([forest], [island, mountain])
    game.players[0].hand = [set_pool("VIS")["Vision Charm"]]
    game.interactive_seats = set(interactive)
    game._recompute_continuous_effects()
    return game, forest, island, mountain


def test_vision_charm_swaps_every_land_of_the_chosen_type(set_pool):
    """"Choose a land type and a basic land type. Each land of the first chosen
    type becomes the second chosen type until end of turn." (CR 305.7,
    CR 609.3.)

    Two printed sentences and one decision: the second names its parameters by
    ordinal, so neither half is a sentence on its own. The mode was the card's
    only unsupported one — its mill and its "target artifact phases out" already
    worked, which is what the brief's `expected 'card'` refusal was hiding.
    """
    game, forest, island, mountain = _w1g2_charm_board(set_pool, interactive={0})

    result = game.cast_from_hand(0, "Vision Charm", mode_index=1)
    assert result.supported, result.details
    game.resolve_stack()

    assert game.confirm_land_type_swap(0, "island", "forest") is True
    game._settle()

    assert island.basic_land_types == ("forest",), "CR 305.7 replaces, not adds"
    assert forest.basic_land_types == ("forest",)
    assert mountain.basic_land_types == ("mountain",), "only the chosen type"


def test_vision_charm_s_swap_wears_off_in_the_cleanup_step(set_pool):
    """"…**until end of turn**." The duration is read rather than defaulted:
    without the words the change would last as long as the game does
    (CR 611.2), which is a different card."""
    game, _forest, island, _mountain = _w1g2_charm_board(set_pool, interactive={0})
    game.cast_from_hand(0, "Vision Charm", mode_index=1)
    game.resolve_stack()
    game.confirm_land_type_swap(0, "island", "forest")
    assert island.basic_land_types == ("forest",)

    game.resolve_cleanup_step(0)

    assert island.basic_land_types == ("island",)


def test_vision_charm_refuses_a_nonbasic_second_type(set_pool):
    """The two halves draw from different catalogs, and the printed adjective
    says which: "a land type" is all of CR 205.3i's and "a basic land type" is
    the five. An answer outside either is refused rather than repaired."""
    game, _forest, _island, _mountain = _w1g2_charm_board(set_pool, interactive={0})
    game.cast_from_hand(0, "Vision Charm", mode_index=1)
    game.resolve_stack()

    assert game.confirm_land_type_swap(0, "island", "desert") is False, (
        "Desert is a land type but not a basic one"
    )
    assert game.confirm_land_type_swap(0, "wizard", "forest") is False
    assert game.confirm_land_type_swap(0, "island", "forest") is True


def test_vision_charm_takes_a_real_default_for_a_seat_that_is_not_asked(set_pool):
    """A headless or AI seat is never blocked, and never gets "the first word in
    the catalog": the default is the pair that changes the most colours of mana
    on the other side of the table, computed off the board and deterministic so
    a seeded run reproduces."""
    game, forest, island, mountain = _w1g2_charm_board(set_pool)

    game.cast_from_hand(0, "Vision Charm", mode_index=1)
    game.resolve_stack()
    game.auto_resolve_pending_choices()
    game._settle()

    assert island.basic_land_types == ("forest",)
    assert mountain.basic_land_types == ("mountain",)
    assert forest.basic_land_types == ("forest",)


def test_vision_charm_s_other_two_modes_still_do_what_they_did(set_pool):
    """The mode this round added is the third of three, and the differential's
    reason for existing: a card whose modes are compiled together is a card
    whose other modes a new production can quietly move."""
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("VIS")["Vision Charm"])
    kinds = [mode.instruction.kind for mode in program.modes]
    assert kinds == [
        "mill_target_player",
        "swap_land_types_until_eot",
        "phase_out_target",
    ]

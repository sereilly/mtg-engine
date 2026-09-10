"""Rules tests earned by Classic Sixth Edition wave 1, group 3 — the colour of
an object that is not a permanent.

CR 613.1 applies the layers to an **object**, and CR 109.1's objects include a
spell on the stack and a card in a hand or a graveyard. This engine had a
correct reader for a permanent's colour (``Permanent.effective_colors``, layer
5) and a correct reader for a card's (``object_colors.card_colors``, which
knows Celestial Dawn's second sentence) — and in between them, half a dozen
rules asked ``card.colors`` instead, which is the mana cost as printed.

The family's failure mode is the one this repo keeps finding: nothing crashes,
no ability is missing, and the rule simply reads a characteristic the board has
already changed. So every test here puts a colour-defining static on the
battlefield and watches a *different* rule's answer move — and its twin watches
the answer stay put for the seat the static does not reach, because a colour
override applied to the wrong seat's cards is the card backwards.

Celestial Dawn is the pool's only static whose sentence reaches off the
battlefield; Thran Lens and Darkest Hour are the two that recolour the
battlefield alone, and they are here for the on-battlefield half.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cost_modifiers import ability_cost_tax, spell_cost_tax
from engine.models import Permanent


def _catalog():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _game(*battlefields, hands=None):
    players = [
        PlayerState(
            name=f"P{index + 1}",
            battlefield=list(pile),
            hand=list((hands or {}).get(index, [])),
            life=20,
        )
        for index, pile in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    game.start_turn(0)
    for player in players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    game._recompute_continuous_effects()
    return game


# ---------------------------------------------------------------------------
# CR 601.2f — a cost increase narrowed by colour
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2f", "613.1e", "105.3")
def test_601_2f_a_colour_tax_reads_the_spell_the_board_made_it():
    """"White spells cost {3} more to cast." (Gloom.) CR 601.2f asks about the
    **spell**, and Celestial Dawn's second sentence makes its controller's
    spells white — so a Dark Ritual in hand under the Dawn is a white spell and
    is taxed exactly as a printed white one is. Reading the printed colours
    charged nothing at all."""
    catalog = _catalog()
    ritual, salve = catalog["Dark Ritual"], catalog["Healing Salve"]

    bare = _game([Permanent(card=catalog["Gloom"])], [], hands={0: [ritual]})
    assert spell_cost_tax(bare, 0, ritual) == (0, [])
    assert spell_cost_tax(bare, 0, salve) == (3, ["Gloom"])

    dawned = _game(
        [Permanent(card=catalog["Gloom"]), Permanent(card=catalog["Celestial Dawn"])],
        [],
        hands={0: [ritual]},
    )
    assert spell_cost_tax(dawned, 0, ritual) == (3, ["Gloom"])


@pytest.mark.cr("109.5", "601.2f")
def test_109_5_the_tax_follows_the_seat_the_static_names():
    """"…nonland cards **you own** that aren't on the battlefield." The Dawn
    recolours one player's cards, and CR 601.2f charges the player casting the
    spell — so the same Dark Ritual is a white spell in its controller's hand
    and a black one in the opponent's. A tax that answered the same both ways
    would be the card backwards for one of them."""
    catalog = _catalog()
    ritual = catalog["Dark Ritual"]
    game = _game(
        [Permanent(card=catalog["Gloom"]), Permanent(card=catalog["Celestial Dawn"])],
        [],
        hands={0: [ritual], 1: [ritual]},
    )

    assert spell_cost_tax(game, 0, ritual) == (3, ["Gloom"])
    assert spell_cost_tax(game, 1, ritual) == (0, [])


@pytest.mark.cr("613.1e", "601.2f")
def test_613_1e_an_activation_tax_reads_the_permanent_s_layer_5_colour():
    """"Activated abilities of white enchantments cost {3} more to activate."
    (Gloom's second line.) The taxed object is a *permanent*, so its colour is
    layer 5's answer — not the printed field on its effective card, which folds
    in layers 1 and 3 and stops. Greed is a black enchantment the Dawn makes
    white, and Absolute Grace a white one the Lens makes colourless."""
    catalog = _catalog()
    greed = Permanent(card=catalog["Greed"])
    grace = Permanent(card=catalog["Absolute Grace"])
    gloom = Permanent(card=catalog["Gloom"])

    bare = _game([gloom, greed, grace], [])
    assert ability_cost_tax(bare, 0, greed) == (0, [])
    assert ability_cost_tax(bare, 0, grace) == (3, ["Gloom"])

    greed, grace = Permanent(card=catalog["Greed"]), Permanent(card=catalog["Absolute Grace"])
    dawned = _game(
        [Permanent(card=catalog["Gloom"]), greed, grace,
         Permanent(card=catalog["Celestial Dawn"])],
        [],
    )
    assert ability_cost_tax(dawned, 0, greed) == (3, ["Gloom"])

    greed, grace = Permanent(card=catalog["Greed"]), Permanent(card=catalog["Absolute Grace"])
    lensed = _game(
        [Permanent(card=catalog["Gloom"]), greed, grace,
         Permanent(card=catalog["Thran Lens"])],
        [],
    )
    assert ability_cost_tax(lensed, 0, grace) == (0, [])


# ---------------------------------------------------------------------------
# CR 702.16 — protection
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.16b", "613.1e")
def test_702_16b_protection_reads_the_spell_s_current_colour():
    """"…can't be targeted by spells **with the stated quality**." The quality
    is a characteristic of the spell, and a spell's colour is layer 5's answer
    like anything else's. A Terror its controller's Celestial Dawn has made
    white is not a black spell, so a White Knight is a legal target for it —
    and a Black Knight, protected from white, is not."""
    catalog = _catalog()
    terror = catalog["Terror"]
    white_knight = Permanent(card=catalog["White Knight"])
    black_knight = Permanent(card=catalog["Black Knight"])

    bare = _game([], [white_knight, black_knight], hands={0: [terror]})
    assert bare._can_be_targeted(white_knight, terror, caster_index=0) is False
    assert bare._can_be_targeted(black_knight, terror, caster_index=0) is True

    white_knight = Permanent(card=catalog["White Knight"])
    black_knight = Permanent(card=catalog["Black Knight"])
    dawned = _game(
        [Permanent(card=catalog["Celestial Dawn"])],
        [white_knight, black_knight],
        hands={0: [terror]},
    )
    assert dawned._can_be_targeted(white_knight, terror, caster_index=0) is True
    assert dawned._can_be_targeted(black_knight, terror, caster_index=0) is False


@pytest.mark.cr("702.16b", "109.5")
def test_702_16b_the_other_seat_s_spell_keeps_its_printed_colour():
    """The same Terror cast by the player who does *not* control the Dawn is
    still black, and the White Knight is still no target for it. This is the
    half a seat-blind reader cannot get right in both directions at once."""
    catalog = _catalog()
    terror = catalog["Terror"]
    white_knight = Permanent(card=catalog["White Knight"])
    game = _game(
        [Permanent(card=catalog["Celestial Dawn"]), white_knight],
        [],
        hands={1: [terror]},
    )

    assert game._can_be_targeted(white_knight, terror, caster_index=1) is False


@pytest.mark.cr("702.16e", "613.1e")
def test_702_16e_the_damage_half_reads_the_same_colour():
    """"Any damage that would be dealt by sources that have the stated quality
    … is prevented." A spell is a source (CR 109.5), and the seat it is
    controlled by rides on the damage event as ``source_seat`` — so a
    Lightning Bolt the Dawn has made white is stopped by protection from white
    and no longer by protection from red."""
    catalog = _catalog()
    bolt = catalog["Lightning Bolt"]
    black_knight = Permanent(card=catalog["Black Knight"])  # protection from white
    falcon = Permanent(card=catalog["Freewind Falcon"])  # protection from red

    bare = _game([], [black_knight, falcon], hands={0: [bolt]})
    assert bare._is_protected_from(
        black_knight, bolt, as_damage_source=True, seat=0
    ) is False
    assert bare._is_protected_from(
        falcon, bolt, as_damage_source=True, seat=0
    ) is True

    black_knight = Permanent(card=catalog["Black Knight"])
    falcon = Permanent(card=catalog["Freewind Falcon"])
    dawned = _game(
        [Permanent(card=catalog["Celestial Dawn"])],
        [black_knight, falcon],
        hands={0: [bolt]},
    )
    assert dawned._is_protected_from(
        black_knight, bolt, as_damage_source=True, seat=0
    ) is True
    assert dawned._is_protected_from(
        falcon, bolt, as_damage_source=True, seat=0
    ) is False


# ---------------------------------------------------------------------------
# CR 603.2 — a trigger whose condition names a colour
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.2", "613.1e")
def test_603_2_a_cast_trigger_s_colour_narrowing_reads_the_spell():
    """"Whenever a player casts a **white** spell, you may pay {1}. If you do,
    you gain 1 life." (Ivory Cup.) The trigger event is about the spell, so a
    Dark Ritual cast under its controller's Celestial Dawn matches it. Driven
    through a real cast rather than through the filter, because a trigger that
    is admitted and never announced is the other half of this failure mode."""
    catalog = _catalog()
    cup = Permanent(card=catalog["Ivory Cup"])
    game = _game(
        [cup, Permanent(card=catalog["Celestial Dawn"])],
        [],
        hands={0: [catalog["Dark Ritual"]]},
    )
    game.players[0].mana_pool["C"] = 1

    game.cast_from_hand(0, "Dark Ritual")
    game.resolve_stack()
    game.auto_resolve_pending_optional_pays()

    assert game.players[0].life == 21

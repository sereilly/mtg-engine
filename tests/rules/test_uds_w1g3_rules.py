"""Rules tests earned by Urza's Destiny wave 1, group 3 — being enchanted, and
enchantments that become creatures.

Two families, and each is a *word* the engine had the machinery for and no
vocabulary entry against.

**"Enchanted" is a state of the host, not of the Aura.** CR 303.4 puts an Aura
onto the battlefield attached to something; CR 303.4m gives the Aura's own
abilities the word "enchanted [object]" for whatever that something is, and
CR 301.5f gives an Equipment's abilities "equipped" for the identical relation.
Three of this group's cards read the state from the *other* end — "as long as
it's enchanted", asked of the creature — and this engine keeps both attachments
in one record on the host, so the interesting half of every test here is the
Equipment that must *not* answer yes.

**An enchantment that becomes a creature is two layers, not one.** Opalescence
adds a card type (CR 613.1d, layer 4) and sets a base power and toughness
(CR 613.4b, layer 7b). Reading them as one effect is what makes a card either
lose its enchantment-ness or stop being reachable by an anthem, and both halves
are visible on one board: Crusade animated by Opalescence is a 2/2 white
creature that its own anthem then makes 3/3 (CR 613.4c is after 613.4b).

The state trigger is here for the third reason this file exists: CR 603.8's
"doesn't trigger again until the ability has left the stack" and CR 603.4's
intervening "if" are two separate brakes on one sentence, and a card can look
correct with either one missing.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura, auras_attached_to, detach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.equipment import attach_equipment
from engine.models import CardDefinition, Permanent

from tests.helpers import resolve_stack


def _uds_g3_catalog():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _uds_g3_creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _uds_g3_game(*battlefields, lives=(20, 20), hands=None):
    players = [
        PlayerState(
            name=f"P{index + 1}",
            battlefield=list(pile),
            hand=list((hands or {}).get(index, [])),
            life=lives[index] if index < len(lives) else 20,
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
# CR 303.4 / CR 301.5f — which attachment the word "enchanted" names
# ---------------------------------------------------------------------------


@pytest.mark.cr("303.4", "613.1f")
def test_303_4_an_attached_aura_is_what_makes_a_permanent_enchanted():
    """CR 303.4 attaches an Aura to an object, and that is the whole of what
    "as long as it's enchanted" asks about. Layer 6 (CR 613.1f) is where the
    grant lands, so the answer is read through ``has_keyword`` rather than off
    the printed keyword list."""
    catalog = _uds_g3_catalog()
    osprey = Permanent(card=catalog["Fledgling Osprey"])
    game = _uds_g3_game([osprey])

    assert osprey.has_keyword("flying") is False

    aura = Permanent(card=catalog["Holy Strength"])
    game.players[0].battlefield.append(aura)
    attach_aura(aura, osprey)
    game._recompute_continuous_effects()

    assert osprey.has_keyword("flying") is True


@pytest.mark.cr("301.5f", "303.4m")
def test_301_5f_an_equipment_makes_its_host_equipped_and_not_enchanted():
    """The two words name two attachments: CR 301.5f gives an Equipment's
    abilities "equipped [object]" and CR 303.4m gives an Aura's "enchanted
    [object]". This engine records both on one ``attached_auras`` list — which
    is what makes the distinction a *test* rather than a definition, because a
    truthiness read of that list is right for every Aura in the pool and hands
    Fledgling Osprey flying for a Short Sword."""
    catalog = _uds_g3_catalog()
    osprey = Permanent(card=catalog["Fledgling Osprey"])
    sword = Permanent(card=catalog["Short Sword"])
    game = _uds_g3_game([osprey, sword])
    attach_equipment(game, sword, osprey)
    game._recompute_continuous_effects()

    assert auras_attached_to(osprey) == [sword]
    assert osprey.has_keyword("flying") is False


@pytest.mark.cr("611.3b", "613.1f")
def test_611_3b_the_grant_ends_when_the_aura_stops_being_attached():
    """"The effect applies at all times that the permanent generating it is on
    the battlefield." A conditional static is re-derived on every recompute, so
    detaching the Aura is the whole removal — there is no remembered grant that
    a missed cleanup could leave behind."""
    catalog = _uds_g3_catalog()
    golem = Permanent(card=catalog["Thran Golem"])
    aura = Permanent(card=catalog["Holy Strength"])
    game = _uds_g3_game([golem, aura])
    attach_aura(aura, golem)
    game._recompute_continuous_effects()
    assert (golem.effective_power, golem.effective_toughness) == (6, 7)

    detach_aura(aura, golem)
    game._recompute_continuous_effects()

    assert (golem.effective_power, golem.effective_toughness) == (3, 3)
    assert golem.has_keyword("trample") is False


# ---------------------------------------------------------------------------
# CR 613.1d / CR 613.4b — an enchantment that becomes a creature
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.1d")
def test_613_1d_opalescence_adds_the_creature_type_without_replacing_anything():
    """"…is a creature **in addition to its other types**." Layer 4 adds; it
    never replaces. An animated Crusade that stopped being an enchantment would
    fall out of the very set Opalescence describes, so the effect would switch
    itself off on the next recompute."""
    catalog = _uds_g3_catalog()
    crusade = Permanent(card=catalog["Crusade"])
    game = _uds_g3_game([Permanent(card=catalog["Opalescence"]), crusade])
    game._recompute_continuous_effects()

    assert crusade.is_creature is True
    assert crusade.has_type("enchantment") is True


@pytest.mark.cr("613.4b")
def test_613_4b_opalescence_sets_base_power_and_toughness_from_mana_value():
    """"…has **base** power and **base** toughness each equal to its mana
    value." CR 613.4b is the sublayer an effect naming a base P/T applies in,
    and the number is CR 202.3's mana value: Pestilence costs {2}{B}{B} and is
    a 4/4. The artifact beside it is the control — the sentence names
    enchantments, and a scope that answered for every permanent would read
    exactly the same on a board with only enchantments on it."""
    catalog = _uds_g3_catalog()
    disk = Permanent(card=catalog["Nevinyrral's Disk"])   # an artifact, untouched
    pestilence = Permanent(card=catalog["Pestilence"])    # {2}{B}{B}
    game = _uds_g3_game([Permanent(card=catalog["Opalescence"]), disk, pestilence])
    game._recompute_continuous_effects()

    assert (pestilence.effective_power, pestilence.effective_toughness) == (4, 4)
    assert disk.is_creature is False


@pytest.mark.cr("613.4c", "613.4b")
def test_613_4c_a_modifier_still_applies_over_the_base_pt_opalescence_sets():
    """7c is applied after 7b, so an anthem is not overwritten by the setting —
    it is added to it. Crusade under Opalescence is the worked example that
    needs no second card: a 2/2 white creature whose own "White creatures get
    +1/+1" now reaches it."""
    catalog = _uds_g3_catalog()
    crusade = Permanent(card=catalog["Crusade"])
    game = _uds_g3_game([Permanent(card=catalog["Opalescence"]), crusade])
    game._recompute_continuous_effects()

    assert (crusade.effective_power, crusade.effective_toughness) == (3, 3)


@pytest.mark.cr("109.5", "613.1d")
def test_109_5_opalescence_excludes_itself_and_reaches_every_battlefield():
    """"Each **other** …" is CR 109.5's exclusion of the ability's own source,
    and the sentence names no seat — so it is every other non-Aura enchantment
    on the table, an opponent's included."""
    catalog = _uds_g3_catalog()
    opalescence = Permanent(card=catalog["Opalescence"])
    theirs = Permanent(card=catalog["Crusade"])
    game = _uds_g3_game([opalescence], [theirs])
    game._recompute_continuous_effects()

    assert opalescence.is_creature is False
    assert theirs.is_creature is True


# ---------------------------------------------------------------------------
# CR 603.8 / CR 603.4 — a state trigger and its intervening "if"
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.8")
def test_603_8_a_state_trigger_does_not_announce_twice_for_one_state():
    """"A state-triggered ability doesn't trigger again until the ability has
    resolved, has been countered, or has otherwise left the stack." The sweep
    runs on every state-based check, so without the latch a low opponent would
    put a copy on the stack every time anything happened."""
    catalog = _uds_g3_catalog()
    jackals = Permanent(card=catalog["Lurking Jackals"])
    # Built with the state *false* and made true afterwards, because
    # ``start_turn`` runs the sweep itself: a board that already matched would
    # have announced and resolved before the test could look.
    game = _uds_g3_game([jackals], [], lives=(20, 20))
    game.players[1].life = 10

    game.check_state_based_actions()
    game.check_state_based_actions()
    game.check_state_based_actions()

    assert len(game.stack) == 1


@pytest.mark.cr("603.8")
def test_603_8_the_state_trigger_waits_for_the_state_to_become_true():
    """"These abilities trigger as soon as the game state matches the
    condition" — and not before. The opponent at 11 is a board the card does
    not name, and nothing is announced for it."""
    catalog = _uds_g3_catalog()
    jackals = Permanent(card=catalog["Lurking Jackals"])
    game = _uds_g3_game([jackals], [], lives=(20, 11))

    game.check_state_based_actions()
    assert game.stack == []

    game.players[1].life = 10
    game.check_state_based_actions()

    assert len(game.stack) == 1


@pytest.mark.cr("603.4")
def test_603_4_the_intervening_if_stops_the_second_animation():
    """"…if [condition], [effect]" is checked when the trigger event occurs and
    **again as it resolves**. Lurking Jackals stops being an enchantment the
    moment it animates, so a second announcement — which CR 603.8 permits once
    the state has stopped and started again — resolves into nothing.

    The re-announcement is the half that makes this a test rather than a
    restatement: with the latch cleared and re-armed, the only thing standing
    between the board and a second resolution is the "if"."""
    catalog = _uds_g3_catalog()
    jackals = Permanent(card=catalog["Lurking Jackals"])
    game = _uds_g3_game([jackals], [], lives=(20, 20))
    game.players[1].life = 10
    game.check_state_based_actions()
    resolve_stack(game)
    assert jackals.is_creature is True
    assert jackals.has_type("enchantment") is False

    # The state stops matching and matches again, which is exactly what
    # CR 603.8 says re-arms the trigger.
    game.players[1].life = 20
    game.check_state_based_actions()
    game.players[1].life = 10
    game.check_state_based_actions()
    resolve_stack(game)

    assert game.stack == []
    assert (jackals.effective_power, jackals.effective_toughness) == (3, 2)
    assert jackals.has_type("enchantment") is False


# ---------------------------------------------------------------------------
# CR 702.16g — "protection from A and from B" is two abilities
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.16g", "702.16e")
def test_702_16g_an_aura_granting_two_qualities_grants_both_of_them():
    """""Protection from [A] and from [B]" … behaves as two separate protection
    abilities." Asked through the damage half (CR 702.16e) rather than off the
    quality set, because the failure this guards is a *reader* that stops after
    the first colour: the set would then look plausible and the second colour
    would simply never stop anything."""
    catalog = _uds_g3_catalog()
    host = Permanent(card=_uds_g3_creature("Host", 2, 2))
    mask = Permanent(card=catalog["Mask of Law and Grace"])
    bolt = catalog["Lightning Bolt"]          # red
    ritual = catalog["Dark Ritual"]           # black
    growth = catalog["Giant Growth"]          # green
    game = _uds_g3_game([host, mask], hands={0: [bolt, ritual, growth]})
    attach_aura(mask, host)
    game._recompute_continuous_effects()

    assert game._is_protected_from(host, bolt, as_damage_source=True, seat=0) is True
    assert game._is_protected_from(host, ritual, as_damage_source=True, seat=0) is True
    assert game._is_protected_from(host, growth, as_damage_source=True, seat=0) is False


# ---------------------------------------------------------------------------
# CR 303.4g — an Aura with nothing legal to enchant
# ---------------------------------------------------------------------------


@pytest.mark.cr("303.4g")
def test_303_4g_an_aura_with_no_legal_object_remains_in_the_graveyard():
    """"If an Aura is entering the battlefield and there is no legal object or
    player for it to enchant, the Aura remains in its current zone." Iridescent
    Drake names the host itself, so the question is asked of *that* creature —
    and an "Enchant land" Aura has no answer, which leaves it in the pile
    rather than on the battlefield for CR 704.5m to bin a moment later."""
    catalog = _uds_g3_catalog()
    game = _uds_g3_game([], [])
    game.players[0].graveyard.append(catalog["Evil Presence"])
    drake = Permanent(card=catalog["Iridescent Drake"])
    game._put_permanent_onto_battlefield(0, drake, None)

    resolve_stack(game)

    assert auras_attached_to(drake) == []
    assert [card.name for card in game.players[0].graveyard] == ["Evil Presence"]


@pytest.mark.cr("303.4")
def test_303_4_an_aura_returned_this_way_arrives_already_attached():
    """CR 303.4: an Aura enters the battlefield **attached**. It is never on the
    battlefield unattached, which is what keeps CR 704.5m from putting it
    straight back into the graveyard between the arrival and the attachment."""
    catalog = _uds_g3_catalog()
    game = _uds_g3_game([], [])
    game.players[0].graveyard.append(catalog["Holy Strength"])
    drake = Permanent(card=catalog["Iridescent Drake"])
    game._put_permanent_onto_battlefield(0, drake, None)

    resolve_stack(game)

    assert [aura.card.name for aura in auras_attached_to(drake)] == ["Holy Strength"]
    assert game.players[0].graveyard == []
    assert (drake.effective_power, drake.effective_toughness) == (3, 4)

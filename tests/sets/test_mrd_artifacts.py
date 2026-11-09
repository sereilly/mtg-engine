"""Mirrodin artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
#
# Imprint (an ability word, CR 207.2c) over CR 607.2a's linked abilities:
# "the exiled card" is the card this permanent's own entry trigger exiled and
# still in exile (``linked_exile.cards_still_exiled_with``). Each card is
# driven through the real entry points — cast, the entry trigger on the stack,
# the "may" answered by an interactive seat and by a seat nobody asks, then the
# linked ability.

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from engine.mana_could_produce import (
    ability_colors_on_offer as _w1g5_colors_on_offer,
)
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_table(set_pool, hand=(), *, interactive=False, bob_hand=()):
    lea = set_pool("LEA")
    alice = _W1G5PlayerState(
        name="Alice", hand=list(hand), library=[lea["Plains"]] * 8,
    )
    bob = _W1G5PlayerState(
        name="Bob", hand=list(bob_hand), library=[lea["Island"]] * 8,
    )
    game = _W1G5Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.priority_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game, alice, bob


def _w1g5_put(game, seat, card):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g5_named(game, name):
    return next(p for p in game.all_permanents() if p.card.name == name)


def _w1g5_imprint_from_hand(game, alice, source_name, card_name):
    """Cast *source_name* for an interactive seat 0, take its imprint offer
    and pick *card_name* out of the hand."""
    assert game.cast_from_hand(0, source_name).supported
    assert game.resolve_top_of_stack() is False, "the imprint offer holds the trigger"
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    (pick,) = game.pending_choices
    assert pick.kind == "exile_from_hand_choice"
    slot = next(i for i, c in enumerate(alice.hand) if c.name == card_name)
    assert slot in game.live_exile_from_hand_choices(pick)
    assert game.confirm_exile_from_hand_choice(0, slot)
    _w1g5_resolve_stack(game)
    return _w1g5_named(game, source_name)


def _w1g5_tap_for(game, permanent, color):
    for symbol in list(game.players[0].mana_pool):
        game.players[0].mana_pool[symbol] = 0
    permanent.tapped = False
    result = game.activate_permanent_ability(
        0, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent),
        ability_index=0, mana_color=color,
    )
    assert result.supported, result.details
    return {k: v for k, v in game.players[0].mana_pool.items() if v}


def test_w1g5_chrome_mox_taps_only_for_the_imprinted_cards_colors(set_pool):
    """"{T}: Add one mana of any of the exiled card's colors." A red card
    imprinted makes {R}, and a colour named outside the set is re-checked to
    one inside it (the colour fan offers only {R})."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"], lea["Wheel of Fortune"]],
        interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    (ability,) = _w1g5_compile(mox.card).activated_abilities
    assert ability.supported
    assert _w1g5_colors_on_offer(game, mox, ability.instruction) == ("R",)
    assert _w1g5_tap_for(game, mox, "R") == {"R": 1}
    assert _w1g5_tap_for(game, mox, "G") == {"R": 1}


def test_w1g5_chrome_mox_offers_each_color_of_a_multicolored_card(set_pool):
    """Ruling 2025-02-07: "If the exiled card is multicolored, you choose one
    of that card's colors each time you tap this artifact for mana.\""""
    mrd, inv = set_pool("MRD"), set_pool("INV")
    gold = next(
        c for c in sorted(inv.values(), key=lambda c: c.name)
        if set(c.colors) == {"W", "U"} and "Land" not in c.type_line
        and "Artifact" not in c.type_line
    )
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], gold], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", gold.name)
    (ability,) = _w1g5_compile(mox.card).activated_abilities
    assert _w1g5_colors_on_offer(game, mox, ability.instruction) == ("W", "U")
    assert _w1g5_tap_for(game, mox, "U") == {"U": 1}
    assert _w1g5_tap_for(game, mox, "W") == {"W": 1}


def test_w1g5_chrome_mox_adds_nothing_with_no_card_or_once_the_card_leaves(set_pool):
    """Ruling 2025-02-07: "If no card is exiled with this artifact, it can't
    add mana." A declined imprint links nothing; a card that leaves exile is no
    longer "the exiled card"; and the Mox returning is a new object with no
    exiled card at all (CR 400.7)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    assert game.cast_from_hand(0, "Chrome Mox").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    mox = _w1g5_named(game, "Chrome Mox")
    assert alice.exile == [] and [c.name for c in alice.hand] == ["Lightning Bolt"]
    assert _w1g5_tap_for(game, mox, "R") == {}
    assert "it adds no mana" in game.log[-1]

    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    assert _w1g5_tap_for(game, mox, "R") == {"R": 1}
    game.remove_from_battlefield(mox)
    returned = _w1g5_put(game, 0, mrd["Chrome Mox"])
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]
    assert _w1g5_tap_for(game, returned, "R") == {}

    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Chrome Mox"], lea["Lightning Bolt"]], interactive=True,
    )
    mox = _w1g5_imprint_from_hand(game, alice, "Chrome Mox", "Lightning Bolt")
    (bolt,) = alice.exile
    assert game.take_card_from_exile(0, bolt)
    assert _w1g5_tap_for(game, mox, "R") == {}


def _w1g5_golem_imprints(set_pool, graveyard_index, *, interactive=True):
    """Mirror Golem cast with Terror and Grizzly Bears in Bob's graveyard; the
    imprint's target is the card at *graveyard_index* (an interactive seat
    names it on the trigger's target prompt, CR 603.3d)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Mirror Golem"]], interactive=interactive,
        bob_hand=[lea["Lightning Bolt"], lea["Terror"]],
    )
    game.enforce_mana_costs = False
    bob.graveyard.extend([lea["Terror"], lea["Grizzly Bears"]])
    assert game.cast_from_hand(0, "Mirror Golem").supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert [c.kind for c in game.pending_choices] == ["trigger_target"]
        assert game.confirm_trigger_target(0, seat=1, graveyard_index=graveyard_index)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, alice, bob, _w1g5_named(game, "Mirror Golem")


def test_w1g5_mirror_golem_is_protected_from_the_exiled_instants_type(set_pool):
    """"This creature has protection from each of the exiled card's card
    types." Terror imprinted: an instant cannot target the Golem (CR 702.16b)
    — Bob's Terror and Lightning Bolt are both refused — and its damage would
    be prevented (CR 702.16e)."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 0)
    assert [c.name for c in bob.exile] == ["Terror"]
    assert game._protection_qualities(golem) == {("card_type", "instant")}
    bolt = set_pool("LEA")["Lightning Bolt"]
    assert not game._can_be_targeted(golem, bolt, caster_index=1)
    assert game._is_protected_from(golem, bolt, as_damage_source=True, seat=1)
    refused = game.cast_from_hand(1, "Lightning Bolt", target_permanent_ids=[golem.permanent_id])
    assert not refused.supported
    assert game.is_on_battlefield(golem)


def test_w1g5_mirror_golem_with_a_creature_imprinted_answers_creatures_only(set_pool):
    """Grizzly Bears imprinted: protection from creatures (a creature cannot
    block it or damage it, CR 702.16e/f) and nothing else — an instant
    targets it as usual."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 1)
    assert [c.name for c in bob.exile] == ["Grizzly Bears"]
    assert game._protection_qualities(golem) == {("card_type", "creature")}
    bears = _w1g5_put(game, 1, set_pool("LEA")["Grizzly Bears"])
    assert game._is_protected_from(golem, bears)
    bolt = set_pool("LEA")["Lightning Bolt"]
    assert game._can_be_targeted(golem, bolt, caster_index=1)


def test_w1g5_mirror_golem_loses_the_protection_with_the_card(set_pool):
    """The exiled card leaving exile takes the protection with it, and a
    Golem that never imprinted (the seat nobody asks takes the first legal
    target) has the one quality its card gives."""
    game, _alice, bob, golem = _w1g5_golem_imprints(set_pool, 0, interactive=False)
    assert game._protection_qualities(golem) == {("card_type", "instant")}
    (terror,) = bob.exile
    assert game.take_card_from_exile(1, terror)
    assert game._protection_qualities(golem) == set()


def _w1g5_duplicant_exiles(set_pool, victim_name, *, interactive=True, bob_lands=()):
    """Duplicant cast at Bob's *victim_name* — named on the trigger's target
    prompt and the imprint taken, for an interactive seat 0."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g5_table(set_pool, [mrd["Duplicant"]], interactive=interactive)
    game.enforce_mana_costs = False
    for land in bob_lands:
        _w1g5_put(game, 1, lea[land])
    victim = _w1g5_put(game, 1, lea[victim_name])
    assert game.cast_from_hand(0, "Duplicant").supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert [c.kind for c in game.pending_choices] == ["trigger_target"]
        assert game.confirm_trigger_target(0, permanent_id=victim.permanent_id)
        game.resolve_top_of_stack()
        assert [c.kind for c in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, bob, _w1g5_named(game, "Duplicant")


def test_w1g5_duplicant_takes_the_exiled_creatures_body_and_types(set_pool):
    """"…this creature has the power, toughness, and creature types of the
    last creature card exiled with it. It's still a Shapeshifter." Hill Giant
    exiled: a 3/3 Giant Shapeshifter, and a +1/+1 modification still applies on
    top of the new base (the 2020-08-07 ruling)."""
    from engine.pt import add_pt_modifier as _w1g5_add_pt

    game, bob, duplicant = _w1g5_duplicant_exiles(set_pool, "Hill Giant")
    assert [c.name for c in bob.exile] == ["Hill Giant"]
    assert list(game.controlled_by(1)) == []
    assert (duplicant.effective_power, duplicant.effective_toughness) == (3, 3)
    assert duplicant.has_type("giant") and duplicant.has_type("shapeshifter")
    _w1g5_add_pt(duplicant, 1, 1)
    game._recompute_continuous_effects()
    assert (duplicant.effective_power, duplicant.effective_toughness) == (4, 4)


def test_w1g5_duplicant_is_its_printed_self_once_the_card_leaves_exile(set_pool):
    """CR 607.2a: only a card still in exile is "a card exiled with this
    creature". The seat nobody asks takes the opposing creature too."""
    game, bob, duplicant = _w1g5_duplicant_exiles(set_pool, "Hill Giant", interactive=False)
    assert (duplicant.effective_power, duplicant.effective_toughness) == (3, 3)
    (giant,) = bob.exile
    assert game.take_card_from_exile(1, giant)
    game._recompute_continuous_effects()
    assert (duplicant.effective_power, duplicant.effective_toughness) == (2, 4)
    assert not duplicant.has_type("giant") and duplicant.has_type("shapeshifter")


def test_w1g5_duplicant_follows_an_exiled_cards_characteristic_defining_pt(set_pool):
    """Ruling 2020-08-07: a */* defined by the card's own ability applies in
    exile, and Duplicant's P/T "are constantly updated". Nightmare counts the
    Swamps its owner controls: two, then three."""
    game, _bob, duplicant = _w1g5_duplicant_exiles(
        set_pool, "Nightmare", bob_lands=("Swamp", "Swamp"),
    )
    assert (duplicant.effective_power, duplicant.effective_toughness) == (2, 2)
    assert duplicant.has_type("nightmare")
    _w1g5_put(game, 1, set_pool("LEA")["Swamp"])
    game._recompute_continuous_effects()
    assert (duplicant.effective_power, duplicant.effective_toughness) == (3, 3)

def test_w1g5_soul_foundry_makes_a_copy_of_the_imprinted_creature_for_its_mana_value(set_pool):
    """"{X}, {T}: Create a token that's a copy of the exiled card. X is the mana
    value of that card." Hill Giant imprinted: X is 4 — two mana is refused —
    and the token is a Hill Giant with the card's mana cost and mana value
    (the 2004-12-01 rulings)."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Soul Foundry"], lea["Hill Giant"], lea["Grizzly Bears"]],
        interactive=True,
    )
    alice.mana_pool["C"] = 4
    foundry = _w1g5_imprint_from_hand(game, alice, "Soul Foundry", "Hill Giant")
    foundry.metadata["summoning_sickness_turn"] = -99
    assert [c.name for c in alice.exile] == ["Hill Giant"]

    alice.mana_pool.update({"C": 0, "R": 2})
    refused = game.activate_permanent_ability(
        0, "Soul Foundry", permanent_index=game.battlefield_index_of(foundry),
        ability_index=0,
    )
    assert not refused.supported and foundry.tapped is False
    alice.mana_pool["R"] = 4
    assert game.activate_permanent_ability(
        0, "Soul Foundry", permanent_index=game.battlefield_index_of(foundry),
        ability_index=0,
    ).supported
    assert alice.mana_pool["R"] == 0
    _w1g5_resolve_stack(game)
    (token,) = [p for p in game.controlled_by(0) if p.metadata.get("is_token")]
    assert token.effective_card.name == "Hill Giant"
    assert (token.effective_power, token.effective_toughness) == (3, 3)
    assert token.effective_card.mana_cost == "{3}{R}" and token.effective_card.cmc == 4
    assert [c.name for c in alice.exile] == ["Hill Giant"], "the card stays imprinted"


def test_w1g5_soul_foundry_with_nothing_imprinted_makes_nothing(set_pool):
    """A declined imprint: X is 0 (CR 107.2) and the token copies nothing."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, _bob = _w1g5_table(
        set_pool, [mrd["Soul Foundry"], lea["Hill Giant"]], interactive=True,
    )
    alice.mana_pool["C"] = 4
    assert game.cast_from_hand(0, "Soul Foundry").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    foundry = _w1g5_named(game, "Soul Foundry")
    foundry.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(
        0, "Soul Foundry", permanent_index=game.battlefield_index_of(foundry),
        ability_index=0,
    ).supported
    _w1g5_resolve_stack(game)
    assert [p for p in game.controlled_by(0) if p.metadata.get("is_token")] == []
    assert any("no card is exiled with it" in line for line in game.log)

def _w1g5_shield_imprints(set_pool, graveyard_index):
    """Mourner's Shield cast for an interactive seat 0, its imprint aimed at
    Bob's graveyard card at *graveyard_index* (Shatter, then Grizzly Bears)
    and taken; Bob controls Mons's Goblin Raiders and Grizzly Bears."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g5_table(set_pool, [mrd["Mourner's Shield"]], interactive=True)
    game.enforce_mana_costs = False
    bob.graveyard.extend([lea["Shatter"], lea["Grizzly Bears"]])
    goblin = _w1g5_put(game, 1, lea["Mons's Goblin Raiders"])
    bears = _w1g5_put(game, 1, lea["Grizzly Bears"])
    assert game.cast_from_hand(0, "Mourner's Shield").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=graveyard_index)
    game.resolve_top_of_stack()
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    shield = _w1g5_named(game, "Mourner's Shield")
    shield.metadata["summoning_sickness_turn"] = -99
    return game, bob, shield, goblin, bears


def _w1g5_shield_against(game, shield, source):
    result = game.activate_permanent_ability(
        0, "Mourner's Shield", permanent_index=game.battlefield_index_of(shield),
        ability_index=0, source_seat=game.controller_index_of(source),
        source_permanent_index=game.battlefield_index_of(source),
    )
    assert result.supported, result.details
    _w1g5_resolve_stack(game)


def test_w1g5_mourners_shield_stops_a_source_sharing_the_imprinted_cards_color(set_pool):
    """"{2}, {T}: Prevent all damage that would be dealt this turn by a source
    of your choice that shares a color with the exiled card." Shatter (red)
    imprinted, a red Goblin chosen: none of its damage this turn is dealt, to
    a player or to a creature; a green source's damage still is."""
    from tests.helpers import _damage_dealt as _w1g5_damage_dealt

    game, bob, shield, goblin, bears = _w1g5_shield_imprints(set_pool, 0)
    assert [c.name for c in bob.exile] == ["Shatter"]
    _w1g5_shield_against(game, shield, goblin)
    alice = game.players[0]
    assert _w1g5_damage_dealt(game, alice, 2, source=goblin, combat=True) == 0
    assert _w1g5_damage_dealt(game, bears, 1, source=goblin) == 0
    assert _w1g5_damage_dealt(game, alice, 2, source=bears, combat=True) == 2


def test_w1g5_mourners_shield_chosen_source_must_share_the_color(set_pool):
    """A green source chosen against a red imprint shares nothing: the shield
    is rechecked as the damage would be dealt (CR 609.7b) and prevents none."""
    from tests.helpers import _damage_dealt as _w1g5_damage_dealt

    game, _bob, shield, _goblin, bears = _w1g5_shield_imprints(set_pool, 0)
    _w1g5_shield_against(game, shield, bears)
    assert _w1g5_damage_dealt(game, game.players[0], 2, source=bears) == 2


def test_w1g5_mourners_shield_arms_nothing_once_the_imprinted_card_leaves(set_pool):
    """Grizzly Bears imprinted, then taken out of exile: no card is "the exiled
    card" any more (CR 607.2a), no colour is left to share, and the shield is
    not armed at all — the green Bears' damage is dealt."""
    from tests.helpers import _damage_dealt as _w1g5_damage_dealt

    game, bob, shield, goblin, bears = _w1g5_shield_imprints(set_pool, 1)
    assert [c.name for c in bob.exile] == ["Grizzly Bears"]
    (exiled,) = bob.exile
    assert game.take_card_from_exile(1, exiled)
    _w1g5_shield_against(game, shield, bears)
    assert "no colored card is exiled with it" in " ".join(game.log[-3:])
    assert _w1g5_damage_dealt(game, game.players[0], 2, source=bears) == 2

def _w1g5_tapped_for(game, seat, land):
    pool = game.players[seat].mana_pool
    before = dict(pool)
    assert game.tap_land_for_mana_or_refusal(
        seat, land.card.name, permanent_id=land.permanent_id,
    ) is None
    return {k: pool[k] - before.get(k, 0) for k in pool if pool[k] != before.get(k, 0)}


def test_w1g5_extraplanar_lens_doubles_every_land_sharing_the_imprinted_name(set_pool):
    """"Whenever a land with the same name as the exiled card is tapped for
    mana, its controller adds one mana of any type that land produced." A
    Forest imprinted: each Forest — Alice's and Bob's, each to its own
    controller — makes {G}{G}; a Mountain makes its one {R}."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(set_pool, [mrd["Extraplanar Lens"]], interactive=True)
    game.enforce_mana_costs = False
    imprinted = _w1g5_put(game, 0, lea["Forest"])
    forest = _w1g5_put(game, 0, lea["Forest"])
    mountain = _w1g5_put(game, 0, lea["Mountain"])
    theirs = _w1g5_put(game, 1, lea["Forest"])
    assert game.cast_from_hand(0, "Extraplanar Lens").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_trigger_target(0, permanent_id=imprinted.permanent_id)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    assert [c.name for c in alice.exile] == ["Forest"]
    assert not game.is_on_battlefield(imprinted)
    assert _w1g5_tapped_for(game, 0, forest) == {"G": 2}
    assert _w1g5_tapped_for(game, 0, mountain) == {"R": 1}
    assert _w1g5_tapped_for(game, 1, theirs) == {"G": 2}
    assert bob.mana_pool["G"] == 2 and alice.mana_pool["G"] == 2


def test_w1g5_extraplanar_lens_without_its_card_adds_nothing(set_pool):
    """A declined imprint is a Lens with no exiled card: a Forest is one {G}."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, _bob = _w1g5_table(set_pool, [mrd["Extraplanar Lens"]], interactive=True)
    game.enforce_mana_costs = False
    target = _w1g5_put(game, 0, lea["Forest"])
    forest = _w1g5_put(game, 0, lea["Forest"])
    assert game.cast_from_hand(0, "Extraplanar Lens").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_trigger_target(0, permanent_id=target.permanent_id)
    game.resolve_top_of_stack()
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    assert game.is_on_battlefield(target)
    assert _w1g5_tapped_for(game, 0, forest) == {"G": 1}

def _w1g5_prison_imprints(set_pool, pick_name, *, interactive=True):
    """Thought Prison cast at Bob for an interactive seat 0: the offer taken
    and *pick_name* chosen out of Bob's revealed hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Thought Prison"], lea["Lightning Bolt"]],
        interactive=interactive,
        bob_hand=[
            lea["Lightning Bolt"], lea["Mountain"], lea["Grizzly Bears"],
            lea["Shatter"], lea["Giant Growth"],
        ],
    )
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Thought Prison", target_player_index=1).supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert [c.kind for c in game.pending_choices] == ["optional_pay"]
        assert game.confirm_optional_pay(0, accept=True)
        (pick,) = game.pending_choices
        assert pick.kind == "revealed_hand_pick" and pick.player_index == 0
        legal = pick.data["legal_indices"]
        assert all(bob.hand[i].name != "Mountain" for i in legal), "a nonland card"
        slot = next(i for i in legal if bob.hand[i].name == pick_name)
        assert game.confirm_revealed_hand_pick(0, slot)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, alice, bob, _w1g5_named(game, "Thought Prison")


def test_w1g5_thought_prison_burns_a_caster_sharing_a_color_or_mana_value(set_pool):
    """"Whenever a player casts a spell that shares a color or mana value with
    the exiled card, this artifact deals 2 damage to that player." Lightning
    Bolt (red, 1) imprinted out of Bob's hand: Giant Growth (green, 1) and
    Shatter (red, 2) each cost their caster 2; Grizzly Bears (green, 2) does
    not; and Alice's own red spell burns Alice ("that player")."""
    game, alice, bob, prison = _w1g5_prison_imprints(set_pool, "Lightning Bolt")
    assert [c.name for c in bob.exile] == ["Lightning Bolt"]
    assert "Lightning Bolt" not in [c.name for c in bob.hand]
    game.active_player_index = game.priority_player_index = 1

    assert game.cast_from_hand(1, "Grizzly Bears").supported
    _w1g5_resolve_stack(game)
    assert bob.life == 20
    bears = _w1g5_named(game, "Grizzly Bears")
    assert game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 18
    assert game.cast_from_hand(
        1, "Shatter", target_permanent_ids=[prison.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 16
    assert not game.is_on_battlefield(prison)

    game, alice, bob, _prison = _w1g5_prison_imprints(set_pool, "Lightning Bolt")
    game.active_player_index = game.priority_player_index = 0
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (18, 17)


def test_w1g5_thought_prison_declined_or_emptied_burns_nobody(set_pool):
    """A declined offer exiles nothing, and a card that leaves exile shares
    nothing: no spell burns anyone."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, _alice, bob = _w1g5_table(
        set_pool, [mrd["Thought Prison"]], interactive=True,
        bob_hand=[lea["Lightning Bolt"], lea["Shatter"]],
    )
    game.enforce_mana_costs = False
    assert game.cast_from_hand(0, "Thought Prison", target_player_index=1).supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=False)
    _w1g5_resolve_stack(game)
    assert bob.exile == [] and len(bob.hand) == 2
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 20

    game, _alice, bob, _prison = _w1g5_prison_imprints(set_pool, "Shatter")
    (shatter,) = bob.exile
    assert game.take_card_from_exile(1, shatter)
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert bob.life == 20

def _w1g5_scepter_with(set_pool, imprint="Lightning Bolt", *, interactive=True):
    """Isochron Scepter on the battlefield with *imprint* exiled with it — by
    the imprint's own offer and pick — and ready to activate."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Isochron Scepter"], lea[imprint]], interactive=True,
    )
    alice.mana_pool["C"] = 2
    scepter = _w1g5_imprint_from_hand(game, alice, "Isochron Scepter", imprint)
    scepter.metadata["summoning_sickness_turn"] = -99
    game.interactive_seats = {0} if interactive else set()
    alice.mana_pool["C"] = 2
    return game, alice, bob, scepter


def _w1g5_activate_scepter(game, scepter):
    result = game.activate_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    )
    assert result.supported, result.details


def test_w1g5_isochron_scepter_casts_a_copy_of_the_imprinted_instant(set_pool):
    """"{2}, {T}: You may copy the exiled card. If you do, you may cast the
    copy without paying its mana cost." Lightning Bolt imprinted: the ability
    resolving offers the cast (CR 707.12, made during the resolution — the
    2020-08-07 ruling); the copy is cast free, aimed at Bob, resolves for 3
    and ceases to exist (CR 707.10a) while the imprinted Bolt stays in exile.
    Twice, on two turns' worth of activations."""
    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    for expected in (17, 14):
        _w1g5_activate_scepter(game, scepter)
        assert game.resolve_top_of_stack() is False
        (offer,) = game.pending_choices
        assert offer.kind == "copy_cast" and offer.data["card_name"] == "Lightning Bolt"
        outcome = []
        assert game.confirm_copy_cast(0, True, outcome=outcome, target_player_index=1)
        (copy,) = [item for item in game.stack if item.card.name == "Lightning Bolt"]
        assert copy.is_copy, "the spell is the copy, not the card"
        _w1g5_resolve_stack(game)
        assert bob.life == expected
        assert [c.name for c in alice.exile] == ["Lightning Bolt"]
        assert alice.graveyard == [] and bob.graveyard == []
        assert alice.mana_pool["C"] == 0, "{2} paid; the copy's own cost waived"
        scepter.tapped = False
        alice.mana_pool["C"] = 2


def test_w1g5_isochron_scepter_declined_or_emptied_casts_nothing(set_pool):
    """A declined offer makes no copy; and once the imprinted card has left
    exile the ability resolves with nothing to copy (the ruling's "the copy
    can't be made")."""
    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    _w1g5_activate_scepter(game, scepter)
    assert game.resolve_top_of_stack() is False
    assert game.confirm_copy_cast(0, False)
    _w1g5_resolve_stack(game)
    assert bob.life == 20 and [c.name for c in alice.exile] == ["Lightning Bolt"]
    assert game.pending_choices == []

    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    # Queued, not settled: the ability waits on the stack for a response.
    assert game.queue_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    ).supported
    assert [item.card.name for item in game.stack] == ["Isochron Scepter"]
    assert game.pending_choices == [], "not yet resolving"
    (bolt,) = alice.exile
    assert game.take_card_from_exile(0, bolt), "removed in response"
    _w1g5_resolve_stack(game)
    assert game.pending_choices == [] and bob.life == 20
    assert "no card is exiled with it to copy" in " ".join(game.log[-3:])


def test_w1g5_isochron_scepter_still_copies_after_it_leaves(set_pool):
    """Ruling 2020-08-07: "If Isochron Scepter leaves the battlefield while
    the activated ability is on the stack, the ability can still make a
    copy." A seat nobody asks takes the offer with its rehearsed chooser."""
    game, alice, bob, scepter = _w1g5_scepter_with(set_pool, interactive=False)
    assert game.queue_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    ).supported
    assert bob.life == 20 and len(game.stack) == 1
    game.remove_from_battlefield(scepter)
    assert not game.is_on_battlefield(scepter)
    _w1g5_resolve_stack(game)
    assert bob.life == 17
    assert [c.name for c in alice.exile] == ["Lightning Bolt"]


def test_w1g5_isochron_scepter_offer_is_answered_on_the_wire(set_pool):
    """The ``copy_cast`` prompt renders with the exiled card's place (the
    client's cast dialog opens on it), and the ``copy_cast_confirm`` action
    casts the copy with the ordinary cast fields."""
    from types import SimpleNamespace as _W1G5Namespace

    from web.action_prompt_board import _action_copy_cast_confirm
    from web.prompts import PromptContext, render_prompts
    from web.schemas import GameActionRequest

    game, alice, bob, scepter = _w1g5_scepter_with(set_pool)
    _w1g5_activate_scepter(game, scepter)
    assert game.resolve_top_of_stack() is False
    offered = render_prompts(PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": getattr(card, "name", str(card))},
        seat_type=lambda index: "human" if index in game.interactive_seats else "ai",
    ))["copy_cast"]
    assert offered["card_name"] == "Lightning Bolt"
    assert (offered["exile_seat"], offered["exile_index"]) == (0, 0)
    assert alice.exile[offered["exile_index"]].name == "Lightning Bolt"

    _action_copy_cast_confirm(
        _W1G5Namespace(game=game),
        GameActionRequest(
            seat=0, action="copy_cast_confirm", accept=True, target_player_index=1,
        ),
        None,
    )
    _w1g5_resolve_stack(game)
    assert bob.life == 17 and game.pending_choices == []

def _w1g5_helix_imprints(set_pool, buried, *, interactive=True):
    """Spellweaver Helix with the two sorceries *buried* in Bob's graveyard
    exiled by its imprint (named on the trigger's target prompt), Bad Moon and
    a Swamp on Bob's side, and a Stone Rain in Alice's hand."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    game, alice, bob = _w1g5_table(
        set_pool, [mrd["Spellweaver Helix"], lea["Stone Rain"]], interactive=interactive,
    )
    game.enforce_mana_costs = False
    bob.graveyard.extend(lea[name] for name in buried)
    moon = _w1g5_put(game, 1, lea["Bad Moon"])
    swamp = _w1g5_put(game, 1, lea["Swamp"])
    assert game.cast_from_hand(0, "Spellweaver Helix").supported
    if interactive:
        assert game.resolve_top_of_stack() is False
        assert game.confirm_trigger_target(0, seat=1, graveyard_indices=[0, 1])
        game.resolve_top_of_stack()
        assert game.confirm_optional_pay(0, accept=True)
    _w1g5_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game, alice, bob, moon, swamp


def _w1g5_cast_stone_rain(game, swamp, *, accept=True):
    assert game.cast_from_hand(0, "Stone Rain", target_permanent_ids=[swamp.permanent_id]).supported
    while game.stack and not game.pending_choices:
        if game.resolve_top_of_stack():
            continue
        break
    offers = [c for c in game.pending_choices if c.kind == "copy_cast"]
    for offer in offers:
        assert game.confirm_copy_cast(0, accept)
    _w1g5_resolve_stack(game)
    return [offer.data["card_name"] for offer in offers]


def test_w1g5_spellweaver_helix_casts_a_copy_of_the_other_imprinted_sorcery(set_pool):
    """"Whenever a player casts a card, if it has the same name as one of the
    cards exiled with this artifact, you may copy the other. If you do, you
    may cast the copy without paying its mana cost." Stone Rain and
    Tranquility imprinted: Alice's Stone Rain offers a copy of Tranquility,
    cast above it, which destroys Bad Moon before the Stone Rain resolves; the
    copy is not a card, so it does not trigger the Helix again (CR 707.10)."""
    game, alice, bob, moon, swamp = _w1g5_helix_imprints(set_pool, ("Stone Rain", "Tranquility"))
    assert [c.name for c in bob.exile] == ["Stone Rain", "Tranquility"]
    assert _w1g5_cast_stone_rain(game, swamp) == ["Tranquility"]
    assert not game.is_on_battlefield(moon) and not game.is_on_battlefield(swamp)
    assert [c.name for c in bob.exile] == ["Stone Rain", "Tranquility"]
    assert [c.name for c in alice.graveyard] == ["Stone Rain"], "the copy ceased to exist"
    assert sum("cast a copy of" in line for line in game.log) == 1


def test_w1g5_spellweaver_helix_two_of_one_name_make_one_copy(set_pool):
    """Ruling 2004-12-01: "If the two imprinted sorcery cards have the same
    name and a card with that name is cast, only one copy is created." And a
    seat nobody asks takes the offer."""
    game, _alice, _bob, _moon, swamp = _w1g5_helix_imprints(
        set_pool, ("Stone Rain", "Stone Rain"), interactive=False,
    )
    _w1g5_put(game, 1, set_pool("LEA")["Swamp"])
    assert game.cast_from_hand(0, "Stone Rain", target_permanent_ids=[swamp.permanent_id]).supported
    _w1g5_resolve_stack(game)
    assert sum("cast a copy of Stone Rain" in line for line in game.log) == 1
    assert not game.is_on_battlefield(swamp)


def test_w1g5_spellweaver_helix_with_one_card_left_does_nothing(set_pool):
    """Ruling 2004-12-01: "If there's only one imprinted sorcery card, nothing
    happens." With Tranquility gone from exile, Stone Rain names one card and
    there is no other; with Stone Rain gone, the cast names none and the Helix
    does not trigger (CR 603.4)."""
    game, _alice, bob, moon, swamp = _w1g5_helix_imprints(set_pool, ("Stone Rain", "Tranquility"))
    tranquility = next(c for c in bob.exile if c.name == "Tranquility")
    assert game.take_card_from_exile(1, tranquility)
    assert _w1g5_cast_stone_rain(game, swamp) == []
    assert game.is_on_battlefield(moon) and not game.is_on_battlefield(swamp)

    game, _alice, bob, moon, swamp = _w1g5_helix_imprints(set_pool, ("Stone Rain", "Tranquility"))
    rain = next(c for c in bob.exile if c.name == "Stone Rain")
    assert game.take_card_from_exile(1, rain)
    before = len(game.log)
    assert _w1g5_cast_stone_rain(game, swamp) == []
    assert game.is_on_battlefield(moon)
    assert not any("Spellweaver Helix" in line for line in game.log[before:])

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================

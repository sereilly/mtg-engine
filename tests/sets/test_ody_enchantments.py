"""Odyssey enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
import pytest as _w1g5_pytest  # noqa: E402

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState  # noqa: E402
from engine.damage_events import deal_damage as _w1g5_deal_damage  # noqa: E402
from engine.models import Permanent as _W1G5Permanent  # noqa: E402
from tests.helpers import resolve_stack as _w1g5_resolve_stack  # noqa: E402


def _w1g5_table(catalog_by_name, set_pool, hand0=(), hand1=(), interactive=()):
    """Two seats, mana off, a library each so a draw is a draw. Cards are
    looked up in Odyssey first and the shipped pool second."""
    ody = set_pool("ODY")

    def card(name):
        return ody[name] if name in ody else catalog_by_name[name]

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20),
        _W1G5PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.players[0].hand = [card(name) for name in hand0]
    game.players[1].hand = [card(name) for name in hand1]
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g5_card = card
    return game  # _w1g5_table (enchantments)


def _w1g5_put(game, seat, name):
    """*name* onto *seat*'s battlefield through the one entry path, awake."""
    permanent = _W1G5Permanent(card=game._w1g5_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g5_put (enchantments)


def _w1g5_dealt(game, recipient, amount, source, source_seat=None):
    """One damage event through CR 120.4, reporting what was dealt."""
    event = {"recipient": recipient, "amount": amount, "source": source,
             "combat": False}
    if source_seat is not None:
        event["source_seat"] = source_seat
    return _w1g5_deal_damage(game, event).dealt  # _w1g5_dealt (enchantments)


# The five Spheres -------------------------------------------------------------

_W1G5_SPHERES = [
    ("Sphere of Duty", "Grizzly Bears", "Hill Giant"),      # green
    ("Sphere of Grace", "Scathe Zombies", "Hill Giant"),    # black
    ("Sphere of Law", "Hill Giant", "Grizzly Bears"),       # red
    ("Sphere of Reason", "Merfolk of the Pearl Trident", "Hill Giant"),  # blue
    ("Sphere of Truth", "Savannah Lions", "Hill Giant"),    # white
]


@_w1g5_pytest.mark.parametrize("sphere, answered, ignored", _W1G5_SPHERES)
def test_w1g5_a_sphere_shaves_two_points_off_its_colours_sources_only(
    catalog_by_name, set_pool, sphere, answered, ignored,
):
    """"If a <colour> source would deal damage to you, prevent 2 of that
    damage." Urza's Armor's sentence with two payload words changed: a static
    prevention (CR 615.1), never used up, narrowed by the source's colour and
    by "you" — the Sphere's controller. A source of another colour, and the
    opponent's face, are untouched; a 1-damage source of the colour deals
    nothing at all."""
    game = _w1g5_table(catalog_by_name, set_pool)
    _w1g5_put(game, 0, sphere)
    hit = _w1g5_put(game, 1, answered)
    miss = _w1g5_put(game, 1, ignored)
    alice, bob = game.players

    assert _w1g5_dealt(game, alice, 5, hit) == 3
    assert _w1g5_dealt(game, alice, 5, hit) == 3, "a static prevention is never used up"
    assert _w1g5_dealt(game, alice, 1, hit) == 0
    assert _w1g5_dealt(game, alice, 5, miss) == 5, "another colour's source is not this Sphere's"
    assert _w1g5_dealt(game, bob, 5, hit) == 5, "'to you' is the Sphere's controller"
    assert _w1g5_dealt(game, alice, 5, None) == 5, "no source has no colour"


def test_w1g5_sphere_of_law_reads_a_spells_colour_and_stacks_with_a_second(
    catalog_by_name, set_pool,
):
    """A Lightning Bolt cast at the Sphere's controller lands 1; a second
    Sphere takes the other point (two effects, summed — subtraction commutes,
    so CR 616.1's order cannot matter). And the colour is the source's colour
    *as a source of damage* (CR 609.7b): under Ghostly Flame a red spell is a
    colourless source, so no Sphere of Law answers to it."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Lightning Bolt"] * 3)
    _w1g5_put(game, 0, "Sphere of Law")
    game.active_player_index = 1

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 19

    _w1g5_put(game, 0, "Sphere of Law")
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 19, "two Spheres prevent 4 of a 3-damage event, clamped"

    _w1g5_put(game, 1, "Ghostly Flame")
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 16


def test_w1g5_a_sphere_recolours_with_its_source_and_an_invented_card_reads_the_same(
    catalog_by_name, set_pool,
):
    """The colour is read when the damage would be dealt, through the layers:
    a green creature turned red is a red source. And the sentence is a
    template, not a card — an invented permanent printing "prevent 3" against
    blue sources works with no registration."""
    from engine.color_changes import change_color
    from engine.oracle import compile_card_oracle
    from tests.helpers import _mk_card

    game = _w1g5_table(catalog_by_name, set_pool)
    _w1g5_put(game, 0, "Sphere of Law")
    bears = _w1g5_put(game, 1, "Grizzly Bears")
    assert _w1g5_dealt(game, game.players[0], 4, bears) == 4
    change_color(bears, "R")
    assert _w1g5_dealt(game, game.players[0], 4, bears) == 2

    invented = _mk_card(
        "W1G5 Blue Ward", "{1}", "Enchantment",
        "If a blue source would deal damage to you, prevent 3 of that damage.",
    )
    assert compile_card_oracle(invented).supported
    game._put_permanent_onto_battlefield(0, _W1G5Permanent(card=invented), None)
    merfolk = _w1g5_put(game, 1, "Merfolk of the Pearl Trident")
    assert _w1g5_dealt(game, game.players[0], 4, merfolk) == 1


def _w1g5_slot(game, seat, permanent) -> int:
    return next(
        index for index, perm in enumerate(game.controlled_by(seat))
        if perm is permanent
    )  # _w1g5_slot (enchantments)


def _w1g5_to_declare_attackers(game, seat=0):
    """*seat*'s turn, at the declare-attackers step, nobody summoning sick."""
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step  # _w1g5_to_declare_attackers


def _w1g5_finish_combat(game):
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # _w1g5_finish_combat


def _w1g5_attached(game, host):
    return sorted(
        perm.card.name for perm in game.all_permanents()
        if perm.metadata.get("attached_to") is host
    )  # _w1g5_attached (enchantments)


# Earnest Fellowship -----------------------------------------------------------


def test_w1g5_earnest_fellowship_gives_each_creature_protection_from_its_own_colours(
    catalog_by_name, set_pool,
):
    """"Each creature has protection from each of its colors." CR 702.16i: one
    protection ability per colour the creature has — both players' creatures,
    a gold one from both its colours, and (the card's ruling) a colourless one
    from nothing. Read through layer 5 when asked: a Bears turned red has
    protection from red and no longer from green."""
    from engine.color_changes import change_color

    game = _w1g5_table(
        catalog_by_name, set_pool,
        hand0=["Giant Growth", "Lightning Bolt"],
        hand1=["Lightning Bolt", "Terror", "Giant Growth"],
    )
    _w1g5_put(game, 0, "Earnest Fellowship")
    giant = _w1g5_put(game, 0, "Hill Giant")
    bears = _w1g5_put(game, 1, "Grizzly Bears")
    thopter = _w1g5_put(game, 1, "Ornithopter")
    gold = _w1g5_put(game, 0, "Nicol Bolas")

    assert game._protection_qualities(giant) == {("color", "R")}
    assert game._protection_qualities(bears) == {("color", "G")}
    assert game._protection_qualities(thopter) == set()
    assert game._protection_qualities(gold) == {
        ("color", "U"), ("color", "B"), ("color", "R"),
    }

    assert not game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[giant.permanent_id],
    ).supported, "a red spell at a red creature"
    assert not game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    ).supported, "the opponent's green creature is protected from green too"
    assert _w1g5_dealt(game, giant, 3, catalog_by_name["Lightning Bolt"], 1) == 0
    assert _w1g5_dealt(game, giant, 3, bears) == 3

    change_color(bears, "R")
    assert game._protection_qualities(bears) == {("color", "R")}
    grown = game.cast_from_hand(
        1, "Giant Growth", target_permanent_ids=[bears.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert grown.supported and bears.effective_power == 5

    killed = game.cast_from_hand(
        1, "Terror", target_permanent_ids=[giant.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert killed.supported and not game.is_on_battlefield(giant)


def test_w1g5_earnest_fellowship_drops_an_aura_of_the_creatures_colour_and_stops_its_blockers(
    catalog_by_name, set_pool,
):
    """The rest of protection follows from the qualities with no code of the
    card's own. CR 702.16c: a white Aura on a white creature is put into its
    owner's graveyard when the Fellowship arrives; a green Aura on it stays.
    CR 702.16f: a red attacker can't be blocked by a red creature and can be
    by a green one."""
    game = _w1g5_table(
        catalog_by_name, set_pool, hand0=["Holy Strength", "Regeneration"],
    )
    lions = _w1g5_put(game, 0, "Savannah Lions")
    for aura in ("Holy Strength", "Regeneration"):
        assert game.cast_from_hand(
            0, aura, target_permanent_ids=[lions.permanent_id],
        ).supported
        _w1g5_resolve_stack(game)
    assert _w1g5_attached(game, lions) == ["Holy Strength", "Regeneration"]

    _w1g5_put(game, 1, "Earnest Fellowship")
    game.check_state_based_actions()
    assert _w1g5_attached(game, lions) == ["Regeneration"]
    assert "Holy Strength" in [card.name for card in game.players[0].graveyard]

    attacker = _w1g5_put(game, 0, "Hill Giant")
    red = _w1g5_put(game, 1, "Gray Ogre")
    green = _w1g5_put(game, 1, "Grizzly Bears")
    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, attacker)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g5_slot(game, 1, red): slot})[0]
    assert game.declare_blockers(1, {_w1g5_slot(game, 1, green): slot})[0]
    _w1g5_finish_combat(game)
    assert "Grizzly Bears" in [card.name for card in game.players[1].graveyard]


# Tattoo Ward ------------------------------------------------------------------


def test_w1g5_tattoo_ward_protects_from_enchantments_and_stays_on(
    catalog_by_name, set_pool,
):
    """"Enchanted creature gets +1/+1 and has protection from enchantments.
    This effect doesn't remove this Aura." The quality is a card type, so
    every other Aura comes off (CR 702.16c), no Aura spell may target the
    creature afterwards — a second Tattoo Ward included (CR 702.16b) — and the
    Ward itself stays (CR 702.16n). A Lightning Bolt is not an enchantment."""
    game = _w1g5_table(
        catalog_by_name, set_pool,
        hand0=["Holy Strength", "Tattoo Ward", "Tattoo Ward"],
        hand1=["Pacifism", "Lightning Bolt"],
    )
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Holy Strength", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 4)

    assert game.cast_from_hand(
        0, "Tattoo Ward", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g5_attached(game, bears) == ["Tattoo Ward"]
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert game._protection_qualities(bears) == {("card_type", "enchantment")}
    assert [card.name for card in game.players[0].graveyard] == ["Holy Strength"]

    for seat, name in ((1, "Pacifism"), (0, "Tattoo Ward")):
        refused = game.cast_from_hand(
            seat, name, target_permanent_ids=[bears.permanent_id],
        )
        assert not refused.supported, (name, refused.details)

    crusade = _w1g5_put(game, 1, "Crusade")
    assert _w1g5_dealt(game, bears, 2, crusade) == 0, "an enchantment source"
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert bolt.supported and not game.is_on_battlefield(bears)


def test_w1g5_tattoo_ward_is_sacrificed_to_destroy_an_enchantment(
    catalog_by_name, set_pool,
):
    """"Sacrifice this Aura: Destroy target enchantment." The cost is the
    Ward, so its +1/+1 and its protection leave with it."""
    game = _w1g5_table(catalog_by_name, set_pool, hand0=["Tattoo Ward"])
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    crusade = _w1g5_put(game, 1, "Crusade")
    assert game.cast_from_hand(
        0, "Tattoo Ward", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    ward = next(p for p in game.all_permanents() if p.card.name == "Tattoo Ward")

    spec = game.activation_target_spec(
        0, _w1g5_slot(game, 0, ward), ability_index=0,
    )
    assert sorted(t["name"] for t in spec["valid_targets"]) == [
        "Crusade", "Tattoo Ward",
    ]
    assert not game.activate_permanent_ability(
        0, "Tattoo Ward", target_permanent_ids=[bears.permanent_id],
    ).supported, "a creature is not an enchantment"
    assert game.is_on_battlefield(ward), "a refused activation pays nothing"

    fired = game.activate_permanent_ability(
        0, "Tattoo Ward", target_permanent_ids=[crusade.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert fired.supported, fired.details
    assert not game.is_on_battlefield(crusade)
    assert not game.is_on_battlefield(ward)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert game._protection_qualities(bears) == set()


@_w1g5_pytest.mark.parametrize("aura, creature, other_instance", [
    ("Tattoo Ward", "Grizzly Bears", "protection_from_enchantments"),
    ("White Ward", "Grizzly Bears", "protection_from_white"),
])
def test_w1g5_this_effect_doesnt_remove_this_aura_exempts_only_its_own_grant(
    catalog_by_name, set_pool, aura, creature, other_instance,
):
    """CR 702.16n, both sentences. The Aura is not removed by the protection
    **it** grants — and "if the creature has other instances of protection
    from the same quality, those instances affect Auras as normal". The
    exemption was the bare printed phrase, so a White Ward stayed on a
    creature that came by protection from white some other way; the sweep now
    asks what the creature is protected from with that one Aura's grant left
    out. Scryfall has no ruling for either card, so the CR is the authority."""
    game = _w1g5_table(catalog_by_name, set_pool, hand0=[aura])
    host = _w1g5_put(game, 0, creature)
    assert game.cast_from_hand(
        0, aura, target_permanent_ids=[host.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g5_attached(game, host) == [aura], "its own grant does not remove it"

    # A second instance of the same protection, through the grant channel a
    # one-shot "gains protection from … until end of turn" writes.
    host.metadata[other_instance] = True
    game.check_state_based_actions()
    assert _w1g5_attached(game, host) == []
    assert aura in [card.name for card in game.players[0].graveyard]


# Ground Seal ------------------------------------------------------------------


def test_w1g5_ground_seal_draws_and_stops_every_way_of_targeting_a_graveyard_card(
    catalog_by_name, set_pool,
):
    """"When this enchantment enters, draw a card. Cards in graveyards can't be
    the targets of spells or abilities." It compiled supported on the first
    sentence alone. The second is asked in the one enumeration of graveyard
    targets, so both players' spells and abilities are refused with nothing
    spent, and a trigger that must target a card there is removed from the
    stack (CR 603.3d). The pool-wide census is
    ``tests/regressions/test_ody_w1g5_ground_seal.py``."""
    game = _w1g5_table(
        catalog_by_name, set_pool,
        hand0=["Ground Seal", "Raise Dead", "Animate Dead", "Karmic Guide"],
        hand1=["Regrowth"],
    )
    bears = catalog_by_name["Grizzly Bears"]
    game.players[0].graveyard = [bears, catalog_by_name["Hill Giant"]]
    game.players[1].graveyard = [catalog_by_name["Lightning Bolt"]]
    adun = _w1g5_put(game, 0, "Adun Oakenshield")

    assert [t["name"] for t in game.cast_target_spec(
        0, catalog_by_name["Raise Dead"])["valid_targets"]] == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert game.cast_from_hand(0, "Ground Seal").supported
    _w1g5_resolve_stack(game)
    assert [card.name for card in game.players[0].hand].count("Island") == 1, (
        "the entry trigger drew a card"
    )

    assert game.cast_target_spec(0, catalog_by_name["Raise Dead"])["valid_targets"] == []
    for seat, name in ((0, "Raise Dead"), (0, "Animate Dead"), (1, "Regrowth")):
        refused = game.cast_from_hand(
            seat, name, target_player_index=seat, target_permanent_index=0,
        )
        assert not refused.supported, (name, refused.details)
        assert game._w1g5_card(name) in game.players[seat].hand
    refused = game.activate_permanent_ability(
        0, "Adun Oakenshield", target_player_index=0, target_permanent_index=0,
    )
    assert not refused.supported and not adun.tapped, refused.details

    # A permanent spell targets nothing, so Karmic Guide is cast; its entry
    # trigger ("return target creature card from your graveyard to the
    # battlefield") has no legal target and never resolves.
    assert game.cast_from_hand(0, "Karmic Guide").supported
    _w1g5_resolve_stack(game)
    assert [card.name for card in game.players[0].graveyard] == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert any("Karmic Guide's triggered ability was removed from the stack"
               in line for line in game.log)

    # And it ends with the permanent (the card's ruling: "only works when
    # Ground Seal is on the battlefield").
    seal = next(p for p in game.all_permanents() if p.card.name == "Ground Seal")
    game.remove_from_battlefield(seal)
    returned = game.cast_from_hand(
        0, "Raise Dead", target_player_index=0, target_permanent_index=0,
    )
    _w1g5_resolve_stack(game)
    assert returned.supported and bears in game.players[0].hand

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================

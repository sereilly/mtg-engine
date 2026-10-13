"""Odyssey enchantments, continued: whole group sections moved out of `test_ody_enchantments.py`.

`test_ody_enchantments.py` reached the per-set size cap at wave 1's integration, on no
group's branch - nine groups each wrote a test per driven card, which is what
the briefs asked for. The sections below were moved **whole**, byte for byte,
under the marker pairs they had; a section carries its own imports and its
own `_w<wave>g<n>_` prefix, so nothing here depends on its old neighbours.
Their empty marker pairs stay behind in `test_ody_enchantments.py` so a branch still in
flight merges against unchanged context.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` (`tests/sets/README.md`).
"""


# ==== W1G5 ==========================================================
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


# Nefarious Lich ---------------------------------------------------------------


def _w1g5_lich_table(catalog_by_name, set_pool, interactive=()):
    game = _w1g5_table(
        catalog_by_name, set_pool, hand1=["Lightning Bolt"] * 3,
        interactive=interactive,
    )
    lich = _w1g5_put(game, 0, "Nefarious Lich")
    game.players[0].graveyard = [
        catalog_by_name[name]
        for name in ("Grizzly Bears", "Hill Giant", "Forest", "Sol Ring", "Island")
    ]
    game.active_player_index = 1
    return game, lich  # _w1g5_lich_table


def test_w1g5_nefarious_lich_turns_damage_into_cards_exiled_from_its_controllers_graveyard(
    catalog_by_name, set_pool,
):
    """"If damage would be dealt to you, exile that many cards from your
    graveyard instead. If you can't, you lose the game." Implemented by
    nothing at the ingest — the card compiled supported and its controller
    simply took the damage. A CR 614 substitution: no life is lost and three
    cards go; with two cards left against three damage the player loses on the
    spot (CR 104.3e). "To **you**" is the Lich's controller, so the opponent's
    face is an ordinary face."""
    game, _lich = _w1g5_lich_table(catalog_by_name, set_pool)
    alice, bob = game.players

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert alice.life == 20
    assert sorted(card.name for card in alice.exile) == [
        "Forest", "Grizzly Bears", "Hill Giant",
    ], "a seat nobody asks gives up the first three in pile order"
    assert [card.name for card in alice.graveyard] == ["Sol Ring", "Island"]
    assert not alice.lost

    assert _w1g5_dealt(game, bob, 3, catalog_by_name["Lightning Bolt"], 1) == 3

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert alice.lost and alice.life == 20
    assert any("could not exile 3 card(s)" in line and "104.3e" in line
               for line in game.log)


def test_w1g5_nefarious_lich_asks_which_cards_and_holds_the_spell_until_answered(
    catalog_by_name, set_pool,
):
    """Which cards go is the player's choice, and in this block it matters. An
    interactive seat is asked through the existing "exile N cards from that
    graveyard" pick; the Lightning Bolt stays on the stack until it is
    answered (CR 608.2), a short answer is refused, and the chosen three are
    the three exiled."""
    game, _lich = _w1g5_lich_table(catalog_by_name, set_pool, interactive={0})
    alice = game.players[0]

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [(c.kind, c.player_index, c.data["count"]) for c in game.pending_choices] == [
        ("graveyard_exile_pick", 0, 3),
    ]
    assert len(game.stack) == 1 and game.waiting_prompt() is not None
    assert alice.life == 20 and len(alice.graveyard) == 5

    assert not game.confirm_graveyard_exile_pick(0, [0, 1]), "three are owed"
    assert game.confirm_graveyard_exile_pick(0, [4, 2, 0])
    assert [card.name for card in alice.graveyard] == ["Hill Giant", "Sol Ring"]
    assert sorted(card.name for card in alice.exile) == [
        "Forest", "Grizzly Bears", "Island",
    ]
    _w1g5_resolve_stack(game)
    assert game.stack == [] and game.pending_choices == []


def test_w1g5_nefarious_lich_pays_only_for_what_a_shield_let_through_and_counts_what_it_owes(
    catalog_by_name, set_pool,
):
    """CR 616.1: prevention and the Lich contend for one event, and the
    default order is the one its controller would choose — the shield first,
    so the graveyard pays only for the remainder. And two events before an
    answer must not both count the same cards: with five cards in the pile and
    a pick of three already owed, three more damage cannot be paid."""
    from engine.shields import END_OF_TURN, PREVENT_NEXT_N, Shield, shields_on

    game, _lich = _w1g5_lich_table(catalog_by_name, set_pool)
    alice = game.players[0]
    shields_on(alice).append(
        Shield(kind=PREVENT_NEXT_N, amount=2, lifetime=END_OF_TURN)
    )
    assert _w1g5_dealt(game, alice, 3, catalog_by_name["Lightning Bolt"], 1) == 0
    assert len(alice.exile) == 1 and len(alice.graveyard) == 4

    game, _lich = _w1g5_lich_table(catalog_by_name, set_pool, interactive={0})
    alice = game.players[0]
    bolt = catalog_by_name["Lightning Bolt"]
    assert _w1g5_dealt(game, alice, 3, bolt, 1) == 0
    assert not alice.lost and len(game.pending_choices) == 1
    assert _w1g5_dealt(game, alice, 3, bolt, 1) == 0
    assert alice.lost, "three of the five cards were already spoken for"


def test_w1g5_nefarious_lich_draws_for_life_and_loses_when_it_leaves(
    catalog_by_name, set_pool,
):
    """The two lines that already worked, driven: "If you would gain life,
    draw that many cards instead." and "When this enchantment leaves the
    battlefield, you lose the game." — leaves, not dies, so a bounce is
    enough."""
    game, lich = _w1g5_lich_table(catalog_by_name, set_pool)
    game.players[1].hand = [game._w1g5_card("Boomerang")]
    alice = game.players[0]

    game._gain_life(alice, 3, source_name="a test")
    assert alice.life == 20 and len(alice.hand) == 3

    assert game.cast_from_hand(
        1, "Boomerang", target_permanent_ids=[lich.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert alice.lost
    assert game._w1g5_card("Nefarious Lich") in alice.hand


# Delaying Shield --------------------------------------------------------------


def _w1g5_delay_counters(permanent) -> int:
    from engine.named_counters import counters_on

    return counters_on(permanent, "delay")  # _w1g5_delay_counters


def test_w1g5_delaying_shield_stores_damage_as_counters_even_when_it_cant_be_prevented(
    catalog_by_name, set_pool,
):
    """"If damage would be dealt to you, put that many delay counters on this
    enchantment instead." A replacement, not a prevention — the card's ruling:
    "the damage is replaced and is not 'prevented'. This means it can replace
    damage that 'can't be prevented'." So an event locked against prevention
    still becomes counters, and an opponent's damage to *their own* face is
    not this Shield's business."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Lightning Bolt"])
    shield = _w1g5_put(game, 0, "Delaying Shield")
    alice, bob = game.players
    game.active_player_index = 1

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert alice.life == 20 and _w1g5_delay_counters(shield) == 3

    dealt = game._deal_damage_to_player(
        alice, 4, catalog_by_name["Lightning Bolt"], cant_be_prevented=True,
    )
    assert dealt == 0 and alice.life == 20 and _w1g5_delay_counters(shield) == 7
    assert _w1g5_dealt(game, bob, 2, catalog_by_name["Lightning Bolt"], 1) == 2


def test_w1g5_three_damage_effects_contend_and_the_prompt_names_what_is_on_the_table(
    catalog_by_name, set_pool,
):
    """CR 616.1: a Sphere of Law, a Delaying Shield and a Nefarious Lich all
    want one Lightning Bolt, and the affected player chooses which applies
    first. A seat nobody asks takes them in registration order — the Sphere's
    two points, then the Shield's one counter, and the Lich is owed nothing.
    A person is asked, and the options name what is on the table: the Sphere's
    reads as what the effect is, where it used to read "Urza's Armor", the
    first card to print the sentence and a card that was not there. Choosing
    the Lich first sends all three points to the graveyard and leaves the
    other two nothing to modify (CR 616.1f re-asks over an event that is no
    longer damage)."""
    def table(interactive):
        game = _w1g5_table(
            catalog_by_name, set_pool, hand1=["Lightning Bolt"],
            interactive=interactive,
        )
        shield = _w1g5_put(game, 0, "Delaying Shield")
        _w1g5_put(game, 0, "Nefarious Lich")
        _w1g5_put(game, 0, "Sphere of Law")
        game.players[0].graveyard = [catalog_by_name["Forest"]] * 5
        game.active_player_index = 1
        assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
        return game, shield

    game, shield = table(())
    _w1g5_resolve_stack(game)
    alice = game.players[0]
    assert (alice.life, _w1g5_delay_counters(shield), len(alice.exile)) == (20, 1, 0)

    game, shield = table({0})
    alice = game.players[0]
    [prompt] = game.pending_choices
    assert (prompt.kind, prompt.player_index) == ("effect_order", 0)
    options = list(prompt.data["options"])
    assert options == ["A static prevention", "Delaying Shield", "Nefarious Lich"]
    assert len(game.stack) == 1, "the Bolt waits for the answer (CR 608.2)"

    assert game.resolve_pending_choice(
        "effect_order", 0, option_index=options.index("Nefarious Lich"),
    )
    assert [(c.kind, c.data["count"]) for c in game.pending_choices] == [
        ("graveyard_exile_pick", 3),
    ]
    assert game.confirm_graveyard_exile_pick(0, [0, 1, 2])
    _w1g5_resolve_stack(game)
    assert (alice.life, _w1g5_delay_counters(shield), len(alice.exile)) == (20, 0, 3)
    assert game.stack == [] and game.pending_choices == []


@_w1g5_pytest.mark.parametrize("plains, answers, life, untapped", [
    (0, (), 17, 0),                       # nothing to pay with: three life
    (4, (True, False, True), 19, 0),      # pay, decline, pay
    (6, (True, True, True), 20, 0),       # pay for all three
    (6, (False, False, False), 17, 6),    # decline all three
])
def test_w1g5_delaying_shield_asks_once_per_counter_at_upkeep(
    catalog_by_name, set_pool, plains, answers, life, untapped,
):
    """"At the beginning of your upkeep, remove all delay counters from this
    enchantment. For each delay counter removed this way, you lose 1 life
    unless you pay {1}{W}." One offer per counter — each its own payment,
    tapped out of the board — and a counter nobody can pay for is a life with
    no question asked."""
    game = _w1g5_table(catalog_by_name, set_pool, interactive={0})
    shield = _w1g5_put(game, 0, "Delaying Shield")
    for _ in range(plains):
        _w1g5_put(game, 0, "Plains")
    alice = game.players[0]
    assert _w1g5_dealt(game, alice, 3, catalog_by_name["Lightning Bolt"], 1) == 0
    assert _w1g5_delay_counters(shield) == 3

    game.enforce_mana_costs = True
    game.turn = 3
    game.resolve_upkeep(0)
    game.resolve_top_of_stack()
    assert _w1g5_delay_counters(shield) == 0
    assert [c.kind for c in game.pending_choices] == ["optional_pay"] * len(answers)
    for accept in answers:
        assert game.resolve_pending_choice(
            "optional_pay", 0, accept=accept, card_name="Delaying Shield",
        )
    _w1g5_resolve_stack(game)

    assert alice.life == life
    assert sum(
        1 for p in game.controlled_by(0)
        if p.card.name == "Plains" and not p.tapped
    ) == untapped
    assert game.pending_choices == [] and game.stack == []


# Aegis of Honor ---------------------------------------------------------------


def test_w1g5_aegis_of_honor_turns_the_next_instant_or_sorcery_back_on_its_controller(
    catalog_by_name, set_pool,
):
    """"{1}: The next time an instant or sorcery spell would deal damage to you
    this turn, that spell deals that damage to its controller instead." A
    one-shot CR 614.9 redirect keyed on a class of **spells**: a creature's
    ability is not one, the first Lightning Bolt is — its caster takes the 3 —
    and the second finds the record spent."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Lightning Bolt"] * 2)
    _w1g5_put(game, 0, "Aegis of Honor")
    _w1g5_put(game, 1, "Prodigal Sorcerer")
    alice, bob = game.players

    assert game.activate_permanent_ability(0, "Aegis of Honor").supported
    _w1g5_resolve_stack(game)
    game.active_player_index = 1

    assert game.activate_permanent_ability(
        1, "Prodigal Sorcerer", target_player_index=0,
    ).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (19, 20), "an ability is not a spell"

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (19, 17)
    assert any("3 damage to Alice is dealt to Bob instead (Aegis of Honor)" in line
               for line in game.log)

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (16, 17), "one instance, and it is spent"


def test_w1g5_aegis_of_honor_covers_a_sorcery_ignores_its_controllers_own_spell_and_ends_with_the_turn(
    catalog_by_name, set_pool,
):
    """The other printed type, the degenerate recipient and the duration. An
    opponent's Earthquake deals its damage to "each player": the Aegis'
    controller's share moves to the Earthquake's controller, who takes both.
    The controller's own Bolt at their own face would be redirected to the
    player it is already headed for, which moves nothing and spends nothing
    (CR 614.9). And a record nobody used is gone at cleanup."""
    game = _w1g5_table(
        catalog_by_name, set_pool,
        hand0=["Lightning Bolt"], hand1=["Earthquake", "Lightning Bolt"],
    )
    _w1g5_put(game, 0, "Aegis of Honor")
    alice, bob = game.players

    assert game.activate_permanent_ability(0, "Aegis of Honor").supported
    _w1g5_resolve_stack(game)
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (17, 20)

    game.active_player_index = 1
    assert game.cast_from_hand(1, "Earthquake", x_value=2).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (17, 16), "the record was still there to spend"

    assert game.activate_permanent_ability(0, "Aegis of Honor").supported
    _w1g5_resolve_stack(game)
    game.resolve_cleanup_step(1)
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert (alice.life, bob.life) == (14, 16)


# Impulsive Maneuvers and Chance Encounter -------------------------------------


def _w1g5_rig_coin(monkeypatch, won: bool) -> None:
    """Every coin lands as *won* says. Each handler module flips the
    ``flip_coin`` it imported — the name every coin test in this repo rigs —
    and hands it to the seam that announces a win, so the two modules these
    cards flip in are the two patched: ``control_flow`` (the ordinary "flip a
    coin") and ``damage`` (Mana Clash's pair)."""
    from engine.handlers import control_flow, damage

    for module in (control_flow, damage):
        monkeypatch.setattr(module, "flip_coin", lambda win_probability=0.5: won)


def _w1g5_attack(game, attacker, blocker=None):
    """Seat 0 attacks seat 1 with *attacker*, blocked or not, through to the
    second main phase — draining the stack after the declaration, which is
    where an attack trigger resolves."""
    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, attacker)
    assert game.declare_attackers(0, [slot])[0]
    _w1g5_resolve_stack(game)
    game.advance_combat_phase()
    blocks = {} if blocker is None else {_w1g5_slot(game, 1, blocker): slot}
    assert game.declare_blockers(1, blocks)[0]
    _w1g5_finish_combat(game)  # _w1g5_attack


@_w1g5_pytest.mark.parametrize("won, life", [(True, 14), (False, 20)])
def test_w1g5_impulsive_maneuvers_doubles_or_prevents_the_attackers_combat_damage(
    catalog_by_name, set_pool, monkeypatch, won, life,
):
    """"Whenever a creature attacks, flip a coin. If you win the flip, the
    next time that creature would deal combat damage this turn, it deals
    double that damage instead. If you lose the flip, the next time that
    creature would deal combat damage this turn, prevent that damage."
    Desperate Gambit's two riders on the creature the attack trigger was
    about, narrowed to combat damage. A Hill Giant deals 6 or nothing."""
    _w1g5_rig_coin(monkeypatch, won)
    game = _w1g5_table(catalog_by_name, set_pool)
    _w1g5_put(game, 0, "Impulsive Maneuvers")
    giant = _w1g5_put(game, 0, "Hill Giant")

    _w1g5_attack(game, giant)

    assert game.players[1].life == life
    assert not any("next_" in key for key in giant.metadata), "the rider was spent"


def test_w1g5_impulsive_maneuvers_rider_answers_to_combat_damage_only_and_dies_with_the_turn(
    catalog_by_name, set_pool, monkeypatch,
):
    """"…would deal **combat** damage": the rider on an attacker is not spent
    by — and does not double — that creature's noncombat damage. And it is
    "this turn": an attacker whose combat damage never happened carries
    nothing into the next one."""
    from engine.next_damage import COMBAT_DAMAGE_DOUBLED_NEXT, armed

    _w1g5_rig_coin(monkeypatch, True)
    game = _w1g5_table(catalog_by_name, set_pool)
    _w1g5_put(game, 0, "Impulsive Maneuvers")
    sorcerer = _w1g5_put(game, 0, "Prodigal Sorcerer")
    bob = game.players[1]

    _w1g5_to_declare_attackers(game)
    assert game.declare_attackers(0, [_w1g5_slot(game, 0, sorcerer)])[0]
    _w1g5_resolve_stack(game)
    assert armed(sorcerer, COMBAT_DAMAGE_DOUBLED_NEXT) == 1

    # A ping from the same creature, outside combat damage: 1, not 2.
    assert _w1g5_dealt(game, bob, 1, sorcerer) == 1
    assert armed(sorcerer, COMBAT_DAMAGE_DOUBLED_NEXT) == 1

    game.resolve_cleanup_step(0)
    assert armed(sorcerer, COMBAT_DAMAGE_DOUBLED_NEXT) == 0


def test_w1g5_impulsive_maneuvers_flips_once_per_attacker_and_its_controller_flips(
    catalog_by_name, set_pool, monkeypatch,
):
    """The card's ruling: "You flip a coin for each creature that attacks, not
    once per attack." And "you" is the enchantment's controller, whoever is
    attacking — the defending player's Maneuvers flips for the attackers
    coming at them, and a win doubles the damage they take."""
    _w1g5_rig_coin(monkeypatch, True)
    game = _w1g5_table(catalog_by_name, set_pool)
    _w1g5_put(game, 1, "Impulsive Maneuvers")
    giant = _w1g5_put(game, 0, "Hill Giant")
    bears = _w1g5_put(game, 0, "Grizzly Bears")

    _w1g5_to_declare_attackers(game)
    assert game.declare_attackers(
        0, [_w1g5_slot(game, 0, giant), _w1g5_slot(game, 0, bears)],
    )[0]
    _w1g5_resolve_stack(game)
    assert sum("Impulsive Maneuvers: won the coin flip" in line for line in game.log) == 2
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    _w1g5_finish_combat(game)

    assert game.players[1].life == 20 - 6 - 4


def test_w1g5_chance_encounter_counts_only_flips_its_controller_won(
    catalog_by_name, set_pool, monkeypatch,
):
    """"Whenever you win a coin flip, put a luck counter on this enchantment."
    Implemented by nothing at the ingest. CR 705.2: only the player who flips
    the coin wins or loses it — the card's ruling says the same. So its
    controller's won flip is a counter; a lost one, an opponent's win, and a
    flip nobody can win (Mana Clash's heads-or-tails) are not."""
    from engine.named_counters import counters_on

    game = _w1g5_table(
        catalog_by_name, set_pool,
        hand0=["Mana Clash"],
    )
    encounter = _w1g5_put(game, 0, "Chance Encounter")
    mine = _w1g5_put(game, 0, "Impulsive Maneuvers")
    giant = _w1g5_put(game, 0, "Hill Giant")

    _w1g5_rig_coin(monkeypatch, True)
    _w1g5_attack(game, giant)
    assert counters_on(encounter, "luck") == 1

    _w1g5_rig_coin(monkeypatch, False)
    game.turn += 2
    _w1g5_attack(game, giant)
    assert counters_on(encounter, "luck") == 1, "a lost flip"

    # The opponent's Maneuvers: they flip, they win, nobody else did.
    game.remove_from_battlefield(mine)
    _w1g5_put(game, 1, "Impulsive Maneuvers")
    _w1g5_rig_coin(monkeypatch, True)
    game.turn += 2
    _w1g5_attack(game, giant)
    assert counters_on(encounter, "luck") == 1, "an opponent's win"

    # Mana Clash: both coins heads on the first round. No player wins a flip
    # that only cares which side came up.
    game.current_turn_phase = "main1"
    assert game.cast_from_hand(0, "Mana Clash", target_player_index=1).supported
    _w1g5_resolve_stack(game)
    assert counters_on(encounter, "luck") == 1, "heads is not a win"


def test_w1g5_chance_encounter_wins_the_game_at_ten_luck_counters_in_upkeep(
    catalog_by_name, set_pool,
):
    """"At the beginning of your upkeep, if this enchantment has ten or more
    luck counters on it, you win the game." An intervening "if" (CR 603.4):
    nine counters do not trigger it, ten do, and its controller's opponent has
    then lost."""
    from engine.named_counters import add_counters

    game = _w1g5_table(catalog_by_name, set_pool)
    encounter = _w1g5_put(game, 0, "Chance Encounter")
    add_counters(encounter, "luck", 9)
    game.turn = 3
    game.resolve_upkeep(0)
    _w1g5_resolve_stack(game)
    assert not game.players[1].lost and game.get_winner() is None

    add_counters(encounter, "luck", 1)
    game.resolve_upkeep(0)
    _w1g5_resolve_stack(game)
    assert game.get_winner() is game.players[0]

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), their_library=(),
    hand=(), their_hand=(),
):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; the returned game has not started a turn."""
    def board(cards):
        permanents = [_W1G6Permanent(card=card) for card in cards]
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
        return permanents

    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", battlefield=board(mine), graveyard=list(yard),
            library=list(library), hand=list(hand), life=20,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=board(theirs), graveyard=list(their_yard),
            library=list(their_library), hand=list(their_hand), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    return game  # _w1g6_game


def _w1g6_named(game, seat, name):
    return next(
        permanent for permanent in game.controlled_by(seat)
        if permanent.card.name == name
    )  # _w1g6_named


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


# --- Bearscape, Screams of the Damned ---------------------------------------
# Driven: the Atog-style graveyard exile costs on two enchantments.

def test_w1g6_bearscape_makes_a_bear_for_two_cards_and_nothing_for_one(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(mine=[ody["Bearscape"]], yard=[lea["Forest"]] * 3)
    game.start_turn(0)

    made = game.activate_permanent_ability(0, "Bearscape")

    assert made.supported, made.details
    assert len(game.players[0].graveyard) == 1 and len(game.players[0].exile) == 2
    bear = next(p for p in game.controlled_by(0) if p.card.name != "Bearscape")
    assert "Bear" in bear.card.type_line and "Creature" in bear.card.type_line
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert tuple(bear.card.colors) == ("G",)

    refused = game.activate_permanent_ability(0, "Bearscape")
    assert not refused.supported
    assert len(game.players[0].graveyard) == 1
    assert len(list(game.controlled_by(0))) == 2


def test_w1g6_screams_of_the_damned_pings_everything_for_one_card(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Screams of the Damned"], lea["Grizzly Bears"]],
        theirs=[lea["Birds of Paradise"], lea["Hill Giant"]],
        yard=[lea["Forest"]],
    )
    game.start_turn(0)

    used = game.activate_permanent_ability(0, "Screams of the Damned")
    game.check_state_based_actions()

    assert used.supported, used.details
    assert _w1g6_pile(game.players[0], "exile") == ["Forest"]
    assert (game.players[0].life, game.players[1].life) == (19, 19)
    assert _w1g6_names(game, 1) == ["Hill Giant"]  # the 0/1 Birds died
    assert _w1g6_named(game, 0, "Grizzly Bears").damage_marked == 1

    # An empty graveyard cannot pay, and nothing is dealt.
    refused = game.activate_permanent_ability(0, "Screams of the Damned")
    assert not refused.supported
    assert (game.players[0].life, game.players[1].life) == (19, 19)


# --- Holistic Wisdom --------------------------------------------------------
# "{2}, Exile a card from your hand: Return target card from your graveyard to
# your hand if it shares a card type with the card exiled this way." The
# target is any card (CR 601.2c precedes the cost, CR 601.2h); the comparison
# is made as the ability resolves, between two cards' printed types.

def _w1g6_wisdom(set_pool, hand, yard):
    ody = set_pool("ODY")
    game = _w1g6_game(mine=[ody["Holistic Wisdom"]], hand=hand, yard=yard)
    game.start_turn(0)
    return game  # _w1g6_wisdom


@_w1g6_pytest.mark.parametrize(
    "exiled, wanted, returned",
    [
        ("Grizzly Bears", "Craw Wurm", True),        # creature / creature
        ("Grizzly Bears", "Lightning Bolt", False),  # creature / instant
        ("Forest", "Island", True),                  # land / land
        ("Ornithopter", "Sol Ring", True),           # artifact creature / artifact
        ("Ornithopter", "Craw Wurm", True),          # artifact creature / creature
        ("Sol Ring", "Craw Wurm", False),            # artifact / creature
    ],
)
def test_w1g6_holistic_wisdom_returns_a_card_that_shares_a_type(
    set_pool, exiled, wanted, returned
):
    lea = set_pool("LEA")
    cards = {**lea, "Ornithopter": set_pool("ATQ")["Ornithopter"]}
    game = _w1g6_wisdom(
        set_pool, hand=[cards[exiled]], yard=[lea["Mountain"], cards[wanted]],
    )

    used = game.activate_permanent_ability(
        0, "Holistic Wisdom", target_player_index=0, target_permanent_index=1,
        cost_hand_index=0,
    )

    # The cost is paid either way: the card from hand is exiled.
    assert used.supported, used.details
    assert _w1g6_pile(game.players[0], "exile") == [exiled]
    assert _w1g6_pile(game.players[0], "hand") == ([wanted] if returned else [])
    assert _w1g6_pile(game.players[0]) == (
        ["Mountain"] if returned else ["Mountain", wanted]
    )


def test_w1g6_holistic_wisdom_refusals_pay_nothing(set_pool):
    lea = set_pool("LEA")
    # An empty hand cannot pay.
    game = _w1g6_wisdom(set_pool, hand=[], yard=[lea["Craw Wurm"]])
    refused = game.activate_permanent_ability(
        0, "Holistic Wisdom", target_player_index=0, target_permanent_index=0
    )
    assert not refused.supported and _w1g6_pile(game.players[0]) == ["Craw Wurm"]

    # No card in your graveyard: nothing to target, and the hand is not eaten.
    game = _w1g6_wisdom(set_pool, hand=[lea["Grizzly Bears"]], yard=[])
    refused = game.activate_permanent_ability(0, "Holistic Wisdom", cost_hand_index=0)
    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Grizzly Bears"]

    # An opponent's graveyard is not yours.
    game = _w1g6_game(
        mine=[set_pool("ODY")["Holistic Wisdom"]], hand=[lea["Grizzly Bears"]],
        their_yard=[lea["Craw Wurm"]],
    )
    game.start_turn(0)
    refused = game.activate_permanent_ability(
        0, "Holistic Wisdom", target_player_index=1, target_permanent_index=0,
        cost_hand_index=0,
    )
    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Grizzly Bears"]


def test_w1g6_holistic_wisdom_does_nothing_once_its_target_has_left(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_wisdom(
        set_pool, hand=[lea["Grizzly Bears"]],
        yard=[lea["Craw Wurm"], lea["Hill Giant"]],
    )
    queued = game.queue_permanent_ability(
        0, "Holistic Wisdom", target_player_index=0, target_permanent_index=0,
        cost_hand_index=0,
    )
    assert queued.details == "queued"
    game.players[0].graveyard.pop(0)   # the Wurm leaves in response
    _w1g6_resolve_stack(game)

    # CR 608.2b: no other creature card is taken in its place.
    assert _w1g6_pile(game.players[0]) == ["Hill Giant"]
    assert not game.players[0].hand


# --- Gravestorm -------------------------------------------------------------
# "At the beginning of your upkeep, target opponent may exile a card from
# their graveyard. If that player doesn't, you may draw a card." The offer is
# the opponent's, the pile is the opponent's, and the pick is the opponent's.

def _w1g6_gravestorm(set_pool, their_yard):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Gravestorm"]], their_yard=their_yard, yard=[lea["Mountain"]],
        library=[lea["Island"]] * 5,
    )
    game.interactive_seats = {0, 1}
    game.start_turn(0)
    choice = game.pending_choices[0]
    assert choice.kind == "trigger_target" and choice.player_index == 0
    assert game.confirm_trigger_target(0, seat=1)
    game.resolve_top_of_stack()
    return game  # _w1g6_gravestorm


def test_w1g6_gravestorm_the_opponent_exiles_a_card_of_their_choice(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_gravestorm(set_pool, [lea["Forest"], lea["Hill Giant"]])

    offer = game.pending_choices[0]
    assert (offer.kind, offer.player_index) == ("optional_pay", 1)
    assert game.confirm_optional_pay(1, accept=True)
    pick = game.pending_choices[0]
    assert (pick.kind, pick.player_index, pick.data["owner_index"]) == (
        "graveyard_exile_pick", 1, 1,
    )
    # The pick is the opponent's: the Gravestorm's controller cannot answer it.
    assert not game.confirm_graveyard_exile_pick(0, [1])
    assert game.confirm_graveyard_exile_pick(1, [1])
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Forest"]
    assert _w1g6_pile(game.players[1], "exile") == ["Hill Giant"]
    # The opponent did: no draw is offered, and your own graveyard is untouched.
    assert not game.pending_choices and not game.players[0].hand
    assert _w1g6_pile(game.players[0]) == ["Mountain"]


def test_w1g6_gravestorm_a_declining_opponent_lets_you_draw(set_pool):
    lea = set_pool("LEA")
    game = _w1g6_gravestorm(set_pool, [lea["Forest"]])

    assert game.confirm_optional_pay(1, accept=False)
    draw = game.pending_choices[0]
    assert (draw.kind, draw.player_index) == ("optional_pay", 0)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[1]) == ["Forest"] and not game.players[1].exile
    assert _w1g6_pile(game.players[0], "hand") == ["Island"]


def test_w1g6_gravestorm_an_opponent_with_no_graveyard_is_not_asked(set_pool):
    game = _w1g6_gravestorm(set_pool, [])

    # Nothing to exile is not an offer: it goes straight to "you may draw".
    draw = game.pending_choices[0]
    assert (draw.kind, draw.player_index) == ("optional_pay", 0)
    assert game.confirm_optional_pay(0, accept=False)
    _w1g6_resolve_stack(game)
    assert not game.players[0].hand and len(game.players[0].library) == 5


# --- Pedantic Learning ------------------------------------------------------
# "Whenever a land card is put into your graveyard from your library, you may
# pay {1}. If you do, draw a card." The graveyard seam's one arrival event,
# narrowed three ways as data: what the card is, whose pile, and where from.

def _w1g6_learning(set_pool, library, **extra):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Pedantic Learning"], *extra.pop("mine", ())],
        library=[lea[name] for name in library], **extra,
    )
    game.enforce_mana_costs = True
    game.start_turn(0)
    game.players[0].mana_pool["U"] = 1
    return game  # _w1g6_learning


def _w1g6_learning_triggers(game):
    return [item for item in game.stack if item.card.name == "Pedantic Learning"]


def test_w1g6_pedantic_learning_draws_for_a_land_milled_from_your_library(set_pool):
    from engine.replacements import _mill_cards as _w1g6_mill

    game = _w1g6_learning(set_pool, ["Forest", "Island", "Island"])
    _w1g6_mill(game, game.players[0], 1)

    assert len(_w1g6_learning_triggers(game)) == 1
    _w1g6_resolve_stack(game)
    offer = game.pending_choices_of("optional_pay", 0)[0]
    assert offer.data["cost"] == {"generic": 1}
    assert game.confirm_optional_pay(0, accept=True)
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[0], "hand") == ["Island"]
    assert game.players[0].mana_pool["U"] == 0


def test_w1g6_pedantic_learning_triggers_once_per_land_and_pays_each_separately(
    set_pool,
):
    from engine.replacements import _mill_cards as _w1g6_mill

    game = _w1g6_learning(set_pool, ["Forest", "Forest", "Island", "Island"])
    _w1g6_mill(game, game.players[0], 2)
    assert len(_w1g6_learning_triggers(game)) == 2

    for _ in range(4):
        _w1g6_resolve_stack(game)
        offers = game.pending_choices_of("optional_pay", 0)
        if not offers:
            break
        assert game.confirm_optional_pay(0, accept=True)

    # One mana in the pool buys one card, not two.
    assert len(game.players[0].hand) == 1


def test_w1g6_pedantic_learning_ignores_every_other_arrival(set_pool):
    from engine.replacements import _mill_cards as _w1g6_mill

    lea = set_pool("LEA")
    # A nonland card milled.
    game = _w1g6_learning(set_pool, ["Lightning Bolt", "Island"])
    _w1g6_mill(game, game.players[0], 1)
    assert not _w1g6_learning_triggers(game)

    # A land discarded: put into your graveyard, not from your library.
    game = _w1g6_learning(set_pool, ["Island"], hand=[lea["Forest"]])
    game.take_card_from_hand(game.players[0], lea["Forest"])
    game._discard_card(game.players[0], lea["Forest"])
    assert _w1g6_pile(game.players[0]) == ["Forest"]
    assert not _w1g6_learning_triggers(game)

    # A land sacrificed from the battlefield.
    game = _w1g6_learning(set_pool, ["Island"], mine=[lea["Forest"]])
    game.sacrifice_permanent(_w1g6_named(game, 0, "Forest"))
    assert not _w1g6_learning_triggers(game)

    # An opponent's land milled into the opponent's graveyard.
    game = _w1g6_learning(set_pool, ["Island"], their_library=[lea["Forest"]])
    _w1g6_mill(game, game.players[1], 1)
    assert _w1g6_pile(game.players[1]) == ["Forest"]
    assert not _w1g6_learning_triggers(game)


# --- Traveling Plague -------------------------------------------------------
# "At the beginning of each upkeep, put a plague counter on this Aura. /
# Enchanted creature gets -1/-1 for each plague counter on this Aura. / When
# enchanted creature leaves the battlefield, that creature's controller
# returns this Aura from its owner's graveyard to the battlefield."
# Rulings (Scryfall): "A counter is placed on every player's upkeep" (2004-10-
# 04); "The controller of the dead creature chooses the new creature" (2004-
# 10-04); "The triggered ability returns this card to the battlefield with no
# counters on it" (2005-08-01).

def _w1g6_plague(set_pool, theirs=("Hill Giant", "Grizzly Bears"), mine=("Craw Wurm",)):
    from engine.auras import attach_aura as _w1g6_attach

    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Traveling Plague"], *(lea[name] for name in mine)],
        theirs=[lea[name] for name in theirs],
    )
    game.interactive_seats = {0, 1}
    plague = _w1g6_named(game, 0, "Traveling Plague")
    giant = _w1g6_named(game, 1, "Hill Giant")
    _w1g6_attach(plague, giant)
    return game, plague, giant  # _w1g6_plague


def test_w1g6_traveling_plague_grows_at_every_upkeep_and_shrinks_its_host(set_pool):
    from engine.named_counters import counters_on as _w1g6_counters

    game, plague, giant = _w1g6_plague(set_pool)

    game.start_turn(0)
    _w1g6_resolve_stack(game)
    assert _w1g6_counters(plague, "plague") == 1
    assert (giant.effective_power, giant.effective_toughness) == (2, 2)

    # The opponent's upkeep counts too.
    game.start_turn(1)
    _w1g6_resolve_stack(game)
    assert _w1g6_counters(plague, "plague") == 2
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)


def _w1g6_plague_kills_its_host(set_pool, **board):
    game, plague, giant = _w1g6_plague(set_pool, **board)
    for seat in (0, 1):
        game.start_turn(seat)
        _w1g6_resolve_stack(game)
    # The third counter is lethal, and everything it sets off belongs to the
    # upkeep that placed it (CR 500.2, CR 117.5): the Giant dies at the check
    # the players' passes make, the Aura follows it (CR 704.5m), and the
    # return resolves in that same step — held on the stack where it has a
    # seat to ask. It used to wait for a state check made by hand after the
    # turn had moved on to its draw.
    game.start_turn(0)
    assert "Hill Giant" in _w1g6_pile(game.players[1])
    assert _w1g6_pile(game.players[0]) == ["Traveling Plague"]
    return game  # _w1g6_plague_kills_its_host


def test_w1g6_traveling_plague_is_returned_by_the_dead_creatures_controller(set_pool):
    from engine.named_counters import counters_on as _w1g6_counters

    game = _w1g6_plague_kills_its_host(set_pool)

    # The dead creature's controller chooses, not the Aura's.
    choice = game.pending_choices[0]
    assert (choice.kind, choice.player_index) == ("permanent_choice", 1)
    wurm = _w1g6_named(game, 0, "Craw Wurm")
    assert not game.confirm_permanent_choice(0, wurm.permanent_id)
    assert game.confirm_permanent_choice(1, wurm.permanent_id)
    _w1g6_resolve_stack(game)

    # It enters under the control of the player who put it there (CR 110.2a),
    # attached to the creature they chose, as a new object with no counters.
    returned = _w1g6_named(game, 1, "Traveling Plague")
    assert returned.metadata.get("attached_to") is wurm
    assert _w1g6_counters(returned, "plague") == 0
    assert (wurm.effective_power, wurm.effective_toughness) == (6, 4)
    assert not game.players[0].graveyard


def test_w1g6_traveling_plague_stays_in_the_graveyard_with_nothing_to_enchant(
    set_pool,
):
    game = _w1g6_plague_kills_its_host(set_pool, theirs=("Hill Giant",), mine=())

    # CR 303.4g: no legal object to enchant, so the Aura stays where it is.
    _w1g6_resolve_stack(game)
    assert not game.pending_choices
    assert _w1g6_pile(game.players[0]) == ["Traveling Plague"]
    assert _w1g6_names(game, 0) == [] and _w1g6_names(game, 1) == []


def test_w1g6_traveling_plague_follows_a_host_that_left_without_dying(set_pool):
    game, plague, giant = _w1g6_plague(set_pool)
    game.start_turn(0)
    _w1g6_resolve_stack(game)

    # Bounced: "leaves the battlefield" is wider than "dies".
    game.remove_from_battlefield(giant)
    game.put_card_into_hand(game.players[1], giant.card, from_battlefield=giant)
    game.check_state_based_actions()
    assert [item.card.name for item in game.stack] == ["Traveling Plague"]
    game.resolve_top_of_stack()
    bears = _w1g6_named(game, 1, "Grizzly Bears")
    assert game.confirm_permanent_choice(1, bears.permanent_id)
    _w1g6_resolve_stack(game)

    assert _w1g6_named(game, 1, "Traveling Plague").metadata.get("attached_to") is bears


# --- Malevolent Awakening ---------------------------------------------------
# "{1}{B}{B}, Sacrifice a creature: Return target creature card from your
# graveyard to your hand." Driven. One of the four activations the ingest's
# stack-target guard named: the creature its cost sacrifices is a legal
# re-aim its own picker could not have listed.

def test_w1g6_malevolent_awakening_trades_a_creature_for_a_creature_card(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Malevolent Awakening"], lea["Grizzly Bears"], lea["Hill Giant"]],
        yard=[lea["Craw Wurm"], lea["Forest"]], their_yard=[lea["Shivan Dragon"]],
    )
    game.start_turn(0)
    giant = _w1g6_named(game, 0, "Hill Giant")

    used = game.activate_permanent_ability(
        0, "Malevolent Awakening", target_player_index=0, target_permanent_index=0,
        cost_permanent_ids=[giant.permanent_id],
    )
    assert used.supported, used.details
    assert _w1g6_pile(game.players[0], "hand") == ["Craw Wurm"]
    assert _w1g6_pile(game.players[0]) == ["Forest", "Hill Giant"]
    assert _w1g6_names(game, 0) == ["Grizzly Bears", "Malevolent Awakening"]

    # A land card, and an opponent's creature card, are not legal targets —
    # and a refused activation sacrifices nothing.
    for seat, slot in ((0, 0), (1, 0)):
        refused = game.activate_permanent_ability(
            0, "Malevolent Awakening", target_player_index=seat,
            target_permanent_index=slot,
        )
        assert not refused.supported
    assert _w1g6_names(game, 0) == ["Grizzly Bears", "Malevolent Awakening"]

# ==== end W1G6 ======================================================

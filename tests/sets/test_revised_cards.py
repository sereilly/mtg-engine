"""Per-card tests for Revised Edition (3ED) additions.

Revised is mostly a reprint set, but it introduced a handful of cards the
engine had never seen. These use invented cards carrying the printed text
rather than the catalog, because the set is not in the manifest yet — the point
is that the *templates* work, which is what makes ingesting it cheap.
"""

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle


@pytest.fixture(scope="module")
def catalog():
    return {c.name: c for c in load_catalog()}


def _spell(catalog, name, text, cost="{2}", cmc=2.0):
    return dataclasses.replace(
        catalog["Shatter"], name=name, mana_cost=cost, cmc=cmc, oracle_text=text
    )


# ---------------------------------------------------------------------------
# Millstone — mill, which every set after this one uses
# ---------------------------------------------------------------------------

def test_millstone_mills_the_named_number(catalog):
    card = dataclasses.replace(
        catalog["Jayemdae Tome"], name="Millstone", mana_cost="{2}", cmc=2.0,
        oracle_text="{2}, {T}: Target player mills two cards.",
    )
    program = compile_card_oracle(card)
    assert program.supported
    ability = program.activated_abilities[0]
    assert ability.instruction.kind == "mill_target_player"
    assert ability.instruction.payload["amount"] == 2

    stone = Permanent(card=card)
    stone.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[stone])
    p2 = PlayerState(name="P2", library=[catalog["Forest"]] * 5)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Millstone", target_player_index=1)

    assert len(p2.library) == 3
    assert len(p2.graveyard) == 2


def test_mill_count_is_a_parameter_not_a_rule_per_number(catalog):
    """The number is read from the text, spelled out or numeric."""
    from engine.parsing import parse_primary_instruction

    for text, expected in (
        ("target player mills two cards", 2),
        ("target player mills 5 cards", 5),
        ("target player mills ten cards", 10),
    ):
        instruction, _ = parse_primary_instruction(text, activated=True)
        assert instruction.payload["amount"] == expected, text


def test_mill_stops_at_an_empty_library_without_losing_the_game(catalog):
    """CR 704.5b fires on an attempted *draw* from an empty library, not on
    milling more cards than remain."""
    card = dataclasses.replace(
        catalog["Jayemdae Tome"], name="Millstone", mana_cost="{2}", cmc=2.0,
        oracle_text="{2}, {T}: Target player mills two cards.",
    )
    stone = Permanent(card=card)
    stone.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=[stone])
    p2 = PlayerState(name="P2", library=[catalog["Forest"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Millstone", target_player_index=1)
    game.check_state_based_actions()

    assert p2.library == []
    assert len(p2.graveyard) == 1
    assert not p2.lost


# ---------------------------------------------------------------------------
# Hurkyl's Recall — ownership, not control
# ---------------------------------------------------------------------------

def test_hurkyls_recall_returns_artifacts_to_their_owners_hand(catalog):
    card = _spell(
        catalog, "Hurkyl's Recall",
        "Return all artifacts target player owns to their hand.", "{1}{U}", 2.0,
    )
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=catalog["Sol Ring"]), Permanent(card=catalog["Grizzly Bears"])],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Hurkyl's Recall", target_player_index=1)

    assert [p.card.name for p in p2.battlefield] == ["Grizzly Bears"]
    assert [c.name for c in p2.hand] == ["Sol Ring"]


def test_hurkyls_recall_leaves_another_players_artifacts_alone(catalog):
    card = _spell(
        catalog, "Hurkyl's Recall",
        "Return all artifacts target player owns to their hand.", "{1}{U}", 2.0,
    )
    p1 = PlayerState(name="P1", hand=[card], battlefield=[Permanent(card=catalog["Sol Ring"])])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Jayemdae Tome"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.cast_from_hand(0, "Hurkyl's Recall", target_player_index=1)

    assert [p.card.name for p in p1.battlefield] == ["Sol Ring"]
    assert p2.battlefield == []


# ---------------------------------------------------------------------------
# Crumble
# ---------------------------------------------------------------------------

def test_crumble_destroys_and_gives_the_controller_its_mana_value(catalog):
    card = _spell(
        catalog, "Crumble",
        "Destroy target artifact. It can't be regenerated. That artifact's "
        "controller gains life equal to its mana value.",
        "{G}", 1.0,
    )
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Jayemdae Tome"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    before = p2.life

    game.cast_from_hand(0, "Crumble", target_player_index=1, target_permanent_index=0)

    assert p2.battlefield == []
    assert p2.life == before + 4          # Jayemdae Tome's mana value


def test_crumble_reads_the_mana_value_before_destroying(catalog):
    """The life clause is about the object the first clause destroyed, so both
    its controller and its mana value have to be read while it is still on the
    battlefield (CR 603.10 last-known information)."""
    card = _spell(
        catalog, "Crumble",
        "Destroy target artifact. It can't be regenerated. That artifact's "
        "controller gains life equal to its mana value.",
        "{G}", 1.0,
    )
    p1 = PlayerState(name="P1", hand=[card])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Black Lotus"])])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    before = p2.life

    game.cast_from_hand(0, "Crumble", target_player_index=1, target_permanent_index=0)

    assert p2.battlefield == []
    assert p2.life == before              # Black Lotus's mana value is 0


# ---------------------------------------------------------------------------
# Titania's Song — a static that changes objects its source does not own
# ---------------------------------------------------------------------------

def _song(catalog):
    return dataclasses.replace(
        catalog["Bad Moon"], name="Titania's Song", mana_cost="{3}{G}", cmc=4.0,
        oracle_text=(
            "Each noncreature artifact loses all abilities and becomes an "
            "artifact creature with power and toughness each equal to its mana value."
        ),
    )


@pytest.mark.cr("613.1d", "613.1f")
def test_titanias_song_animates_noncreature_artifacts_at_their_mana_value(catalog):
    tome = Permanent(card=catalog["Jayemdae Tome"])       # mana value 4
    bears = Permanent(card=catalog["Grizzly Bears"])
    player = PlayerState(name="P1", battlefield=[tome, bears])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert tome.is_creature is False

    player.battlefield.append(Permanent(card=_song(catalog)))
    game._refresh_dynamic_creatures()

    assert tome.is_creature is True
    assert (tome.effective_power, tome.effective_toughness) == (4, 4)
    # A creature is not a *noncreature* artifact, and Grizzly Bears is neither.
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


@pytest.mark.cr("611.3")
def test_titanias_song_effect_ends_when_the_source_leaves(catalog):
    """The affected permanent holds a reference to the *source*, not a copy of
    the effect, so removal is the source dropping out of that list — the same
    shape attached Auras use, and the reason there is no flag to clear."""
    tome = Permanent(card=catalog["Jayemdae Tome"])
    song = Permanent(card=_song(catalog))
    player = PlayerState(name="P1", battlefield=[tome, song])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert tome.is_creature is True

    player.battlefield.remove(song)
    game._refresh_dynamic_creatures()

    assert tome.is_creature is False


@pytest.mark.cr("613.1f")
def test_titanias_song_removes_activated_abilities_too(catalog):
    """"Loses all abilities" means the activated ones. Layer 6 removes keyword
    abilities, but an activated ability is read from the compiled program, so
    the loss has to be enforced where activation is authorised — otherwise the
    card is half-implemented and a Tome keeps drawing cards."""
    tome = Permanent(card=catalog["Jayemdae Tome"])
    tome.metadata["summoning_sickness_turn"] = -99
    song = Permanent(card=_song(catalog))
    player = PlayerState(
        name="P1", battlefield=[tome, song], library=[catalog["Forest"]] * 5
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()

    result = game.activate_permanent_ability(0, "Jayemdae Tome")
    assert result.supported is False
    assert player.hand == []

    player.battlefield.remove(song)
    game._refresh_dynamic_creatures()

    assert game.activate_permanent_ability(0, "Jayemdae Tome").supported is True
    assert len(player.hand) == 1


# ---------------------------------------------------------------------------
# Energy Flux — a static that *grants* an ability board-wide
# ---------------------------------------------------------------------------

@pytest.mark.cr("613.1f")
def test_energy_flux_grants_the_upkeep_cost_to_every_artifact(catalog):
    """The granted ability is appended to each artifact's effective card, so the
    compiler produces it like a printed one and the upkeep step finds it without
    knowing a static granted it."""
    flux = dataclasses.replace(
        catalog["Bad Moon"], name="Energy Flux", mana_cost="{2}{U}", cmc=3.0,
        oracle_text=(
            'All artifacts have "At the beginning of your upkeep, sacrifice '
            'this artifact unless you pay {2}."'
        ),
    )
    assert compile_card_oracle(flux).supported

    ring = Permanent(card=catalog["Sol Ring"])
    bears = Permanent(card=catalog["Grizzly Bears"])
    player = PlayerState(name="P1", battlefield=[ring, bears])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert game.get_upkeep_pay_triggers(0) == []

    player.battlefield.append(Permanent(card=flux))
    game._refresh_dynamic_creatures()

    triggers = game.get_upkeep_pay_triggers(0)
    assert [t["card_name"] for t in triggers] == ["Sol Ring"]
    assert triggers[0]["mana"]["generic"] == 2


@pytest.mark.cr("611.3")
def test_energy_flux_grant_ends_when_it_leaves(catalog):
    flux = dataclasses.replace(
        catalog["Bad Moon"], name="Energy Flux", mana_cost="{2}{U}", cmc=3.0,
        oracle_text=(
            'All artifacts have "At the beginning of your upkeep, sacrifice '
            'this artifact unless you pay {2}."'
        ),
    )
    ring = Permanent(card=catalog["Sol Ring"])
    flux_perm = Permanent(card=flux)
    player = PlayerState(name="P1", battlefield=[ring, flux_perm])
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    assert len(game.get_upkeep_pay_triggers(0)) == 1

    player.battlefield.remove(flux_perm)
    game._refresh_dynamic_creatures()

    assert game.get_upkeep_pay_triggers(0) == []

"""Tests for Magic: The Gathering Comprehensive Rules Sections 115 (Targets)
and 118 (Costs).

Targeting during casting (601.2c) and activation-cost mechanics (602.x) are
covered in test_casting_spells.py / test_abilities.py — the tests here verify
the rule-115/118 statements themselves: what may legally be targeted, and what
it takes to pay a cost.
"""

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent

from ..helpers import _mk_card, _nosick


def _perm(card: CardDefinition, tapped: bool = False) -> Permanent:
    return _nosick(Permanent(card=card, tapped=tapped))


def _two_player_game(p1: PlayerState, p2: PlayerState, enforce: bool = False) -> Game:
    return Game(players=[p1, p2], enforce_mana_costs=enforce)


# ---------------------------------------------------------------------------
# Rule 115.1 — Some spells and abilities require targets; targets are declared
# as part of putting the spell on the stack and can't be changed.
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.1")
def test_115_1_spell_requiring_target_cannot_be_cast_without_legal_target(cards):
    """A spell that requires a target can't be cast when no legal target exists (115.1)."""
    p1 = PlayerState(name="P1", hand=[cards["Shatter"]])  # Destroy target artifact.
    p2 = PlayerState(name="P2")  # no artifacts anywhere
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Shatter", target_player_index=1)

    assert not result.supported
    assert len(p1.hand) == 1  # the cast never happened
    assert len(game.stack) == 0


@pytest.mark.cr("115.1")
def test_115_1_target_declared_on_stack_is_the_one_affected(cards):
    """The target is declared when the spell is put on the stack; resolution
    affects that declared target, not objects that appear later (115.1)."""
    mine = cards["Howling Mine"]
    sol_ring = cards["Sol Ring"]
    p1 = PlayerState(name="P1", hand=[cards["Shatter"]])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=mine)])
    game = _two_player_game(p1, p2)

    game.queue_from_hand(0, "Shatter", target_player_index=1, target_permanent_index=0)
    # A second artifact appears after the target was declared.
    p2.battlefield.append(Permanent(card=sol_ring))

    game.resolve_top_of_stack()

    names = [perm.card.name for perm in p2.battlefield]
    assert "Howling Mine" not in names  # the declared target was destroyed
    assert "Sol Ring" in names  # the later arrival was untouched


# ---------------------------------------------------------------------------
# Rule 115.1b — Aura spells are always targeted.
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.1b")
def test_115_1b_aura_spell_requires_a_target_when_cast(cards):
    """An Aura spell is always targeted: casting one without choosing an
    enchant target is illegal (115.1b)."""
    p1 = PlayerState(name="P1", hand=[cards["Weakness"]])  # Enchant creature
    p2 = PlayerState(name="P2", battlefield=[_perm(cards["Gray Ogre"])])
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Weakness", target_player_index=1)

    assert not result.supported
    assert "requires a target" in result.details
    assert len(p1.hand) == 1


# ---------------------------------------------------------------------------
# Rule 115.1c — Activated abilities are targeted; targets are chosen as the
# ability is activated.
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.1c")
def test_115_1c_activated_ability_target_validated_at_activation(cards):
    """Royal Assassin's "Destroy target tapped creature" chooses its target at
    activation; an untapped creature is not a legal choice, and a tapped one
    is (115.1c)."""
    assassin = _perm(cards["Royal Assassin"])
    p1 = PlayerState(name="P1", battlefield=[assassin])
    p2 = PlayerState(name="P2", battlefield=[_perm(cards["Gray Ogre"], tapped=False)])
    game = _two_player_game(p1, p2)

    denied = game.activate_permanent_ability(
        0, "Royal Assassin", target_player_index=1, target_permanent_index=0
    )
    assert not denied.supported
    assert not assassin.tapped  # rejected before the {T} cost was paid

    p2.battlefield[0].tapped = True
    allowed = game.activate_permanent_ability(
        0, "Royal Assassin", target_player_index=1, target_permanent_index=0
    )
    assert allowed.supported
    assert all(perm.card.name != "Gray Ogre" for perm in p2.battlefield)


# ---------------------------------------------------------------------------
# Rule 115.2 — Only objects matching the target description are legal targets.
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.2")
def test_115_2_target_must_match_the_spells_type_description(cards):
    """Shatter destroys "target artifact" — a creature is not a legal target (115.2)."""
    p1 = PlayerState(name="P1", hand=[cards["Shatter"]])
    p2 = PlayerState(name="P2", battlefield=[_perm(cards["Gray Ogre"])])
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Shatter", target_player_index=1, target_permanent_index=0)

    assert not result.supported
    assert p2.battlefield[0].card.name == "Gray Ogre"  # untouched


@pytest.mark.cr("115.2")
def test_115_2_target_must_match_the_spells_color_description(cards):
    """Terror destroys "target nonartifact, nonblack creature" — a black
    creature is not a legal target (115.2)."""
    p1 = PlayerState(name="P1", hand=[cards["Terror"]])
    p2 = PlayerState(name="P2", battlefield=[_perm(cards["Black Knight"])])
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

    assert not result.supported
    assert p2.battlefield[0].card.name == "Black Knight"


# ---------------------------------------------------------------------------
# Rule 115.4 — "Any target" means creatures, players, planeswalkers, battles;
# other objects such as noncreature artifacts can't be chosen.
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.4")
def test_115_4_any_target_does_not_include_noncreature_artifacts(cards):
    """Lightning Bolt ("deals 3 damage to any target") does nothing to a
    noncreature artifact — it isn't a valid 'any target' choice (115.4)."""
    p1 = PlayerState(name="P1", hand=[cards["Lightning Bolt"]])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Howling Mine"])], life=20)
    game = _two_player_game(p1, p2)

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

    assert len(p2.battlefield) == 1  # the artifact is untouched
    assert p2.battlefield[0].card.name == "Howling Mine"
    assert p2.life == 20  # and the damage was not redirected to the player


# ---------------------------------------------------------------------------
# Rule 115.10 — Spells can affect objects they don't target; those objects
# aren't chosen until resolution (115.10 / 115.10a).
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.10")
def test_115_10_destroy_all_requires_no_targets_and_affects_everything(cards):
    """Wrath of God targets nothing, yet destroys every creature on each
    battlefield when it resolves (115.10)."""
    p1 = PlayerState(name="P1", hand=[cards["Wrath of God"]], battlefield=[_perm(cards["Gray Ogre"])])
    p2 = PlayerState(name="P2", battlefield=[_perm(cards["Scathe Zombies"])])
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Wrath of God")  # no target chosen at all

    assert result.supported
    assert all(not perm.is_creature for perm in p1.battlefield)
    assert all(not perm.is_creature for perm in p2.battlefield)
    assert any(c.name == "Gray Ogre" for c in p1.graveyard)
    assert any(c.name == "Scathe Zombies" for c in p2.graveyard)


@pytest.mark.cr("115.10a")
def test_115_10a_untargeted_effect_affects_creature_that_cannot_be_targeted(cards):
    """Black Knight (protection from white) can't be targeted by white spells,
    but Wrath of God doesn't target — the Knight is still destroyed (115.10a)."""
    p1 = PlayerState(name="P1", hand=[cards["Wrath of God"]])
    p2 = PlayerState(name="P2", battlefield=[_perm(cards["Black Knight"])])
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Wrath of God")

    assert result.supported
    assert all(perm.card.name != "Black Knight" for perm in p2.battlefield)
    assert any(c.name == "Black Knight" for c in p2.graveyard)


# ---------------------------------------------------------------------------
# Rule 118.1 — A cost is an action or payment necessary to take another action.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.1")
def test_118_1_tap_cost_is_carried_out_to_take_the_action(cards):
    """Activating Prodigal Sorcerer's "{T}: deals 1 damage" pays the cost
    (the permanent becomes tapped) and only then produces the effect (118.1)."""
    sorcerer = _perm(cards["Prodigal Sorcerer"])
    p1 = PlayerState(name="P1", battlefield=[sorcerer])
    p2 = PlayerState(name="P2", life=20)
    game = _two_player_game(p1, p2)

    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)

    assert result.supported
    assert sorcerer.tapped  # the cost was actually carried out
    assert p2.life == 19  # enabling the other action


# ---------------------------------------------------------------------------
# Rule 118.2 — A cost with a mana payment gives a chance to activate mana
# abilities first; payment follows 601.2f–h.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.2")
def test_118_2_mana_abilities_pay_for_an_activation_cost(cards):
    """The controller activates mana abilities (tapping Plains) to pay Northern
    Paladin's {W}{W} activation cost (118.2)."""
    zombie = _mk_card("Gravebound Zombie", "Creature — Zombie", colors=("B",))
    paladin = _perm(cards["Northern Paladin"])
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=cards["Plains"]), Permanent(card=cards["Plains"]), paladin],
    )
    p2 = PlayerState(name="P2", battlefield=[_perm(zombie)])
    game = _two_player_game(p1, p2, enforce=True)

    game.tap_land_for_mana(0, "Plains", chosen_color="W", permanent_index=0)
    game.tap_land_for_mana(0, "Plains", chosen_color="W", permanent_index=1)
    result = game.activate_permanent_ability(
        0, "Northern Paladin", target_player_index=1, target_permanent_index=0
    )

    assert result.supported
    assert all(perm.card.name != "Gravebound Zombie" for perm in p2.battlefield)


# ---------------------------------------------------------------------------
# Rule 118.3 — A player can't pay a cost without the necessary resources.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.3")
def test_118_3_already_tapped_permanent_cannot_be_tapped_to_pay(cards):
    """A permanent that's already tapped can't be tapped to pay a cost (118.3)."""
    sorcerer = _perm(cards["Prodigal Sorcerer"])
    sorcerer.tapped = True
    p1 = PlayerState(name="P1", battlefield=[sorcerer])
    p2 = PlayerState(name="P2", life=20)
    game = _two_player_game(p1, p2)

    result = game.activate_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)

    assert not result.supported
    assert "already tapped" in result.details
    assert p2.life == 20  # the effect never happened


@pytest.mark.cr("118.3")
def test_118_3_ability_cannot_be_activated_without_the_mana(cards):
    """Rod of Ruin's {3}, {T} ability can't be activated with an empty mana
    pool — the cost can't be paid partially or at all (118.3)."""
    rod = Permanent(card=cards["Rod of Ruin"])
    p1 = PlayerState(name="P1", battlefield=[rod])
    p2 = PlayerState(name="P2", life=20)
    game = _two_player_game(p1, p2, enforce=True)

    result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)

    assert not result.supported
    assert "insufficient mana" in result.details
    assert not rod.tapped  # no part of the cost was paid
    assert p2.life == 20


@pytest.mark.cr("118.3")
def test_118_3_cannot_pay_more_life_than_the_life_total(cards):
    """A player with 20 life can't pay 25 life (Channel) — the payment is
    refused outright rather than partially applied (118.3)."""
    p1 = PlayerState(name="P1", hand=[cards["Channel"]], life=20)
    p2 = PlayerState(name="P2")
    game = _two_player_game(p1, p2)
    game.cast_from_hand(0, "Channel", target_player_index=0)

    result = game.use_channel_mana(0, 25)

    assert not result.supported
    assert p1.life == 20
    assert p1.mana_pool.get("C", 0) == 0


# ---------------------------------------------------------------------------
# Rule 118.3a — Paying mana removes the indicated mana from the mana pool.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.3a")
def test_118_3a_paying_mana_removes_it_from_the_pool(cards):
    """Paying Rod of Ruin's {3} removes exactly that mana from the pool (118.3a)."""
    rod = Permanent(card=cards["Rod of Ruin"])
    p1 = PlayerState(name="P1", battlefield=[rod], mana_pool={"C": 3})
    p2 = PlayerState(name="P2", life=20)
    game = _two_player_game(p1, p2, enforce=True)

    result = game.activate_permanent_ability(0, "Rod of Ruin", target_player_index=1)

    assert result.supported
    assert p1.mana_pool.get("C", 0) == 0
    assert p2.life == 19


# ---------------------------------------------------------------------------
# Rule 118.3b — Paying life subtracts that much from the life total.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.3b")
def test_118_3b_paying_life_subtracts_from_the_life_total(cards):
    """Paying 4 life through Channel subtracts 4 from the life total (118.3b)."""
    p1 = PlayerState(name="P1", hand=[cards["Channel"]], life=20)
    p2 = PlayerState(name="P2")
    game = _two_player_game(p1, p2)
    game.cast_from_hand(0, "Channel", target_player_index=0)

    result = game.use_channel_mana(0, 4)

    assert result.supported
    assert p1.life == 16
    assert p1.mana_pool.get("C", 0) == 4


# ---------------------------------------------------------------------------
# Rule 118.4 — Some costs include an {X}; the chosen value must be paid.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.4")
def test_118_4_announced_x_value_is_part_of_the_cost_paid():
    """Casting an {X}{R} spell with X=4 pays 4 generic plus {R} — the whole
    pool of 5 red is consumed (118.4)."""
    blaze = _mk_card(
        "Test Blaze",
        "Sorcery",
        "Test Blaze deals X damage to any target.",
        mana_cost="{X}{R}",
        colors=("R",),
    )
    p1 = PlayerState(name="P1", hand=[blaze], mana_pool={"R": 5})
    p2 = PlayerState(name="P2", life=20)
    game = _two_player_game(p1, p2, enforce=True)

    result = game.cast_from_hand(0, "Test Blaze", target_player_index=1, x_value=4)

    assert result.supported
    assert p2.life == 16  # X=4 damage
    assert sum(p1.mana_pool.values()) == 0  # {R} plus 4 generic all paid


# ---------------------------------------------------------------------------
# Rule 118.5 — A {0} cost requires no resources but the spell is cast normally.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.5", "118.5a")
def test_118_5_zero_mana_cost_spell_castable_with_empty_pool():
    """A spell whose mana cost is {0} is cast the same way as any other, and
    paying {0} needs no mana at all (118.5, 118.5a)."""
    freebie = _mk_card(
        "Zero Cost Trick",
        "Instant",
        "Target player loses 1 life.",
        mana_cost="{0}",
    )
    p1 = PlayerState(name="P1", hand=[freebie])  # empty mana pool
    p2 = PlayerState(name="P2", life=20)
    game = _two_player_game(p1, p2, enforce=True)

    result = game.cast_from_hand(0, "Zero Cost Trick", target_player_index=1)

    assert result.supported
    assert p2.life == 19


# ---------------------------------------------------------------------------
# Rule 118.7 — What a player actually needs to pay may be changed by effects.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.7")
def test_118_7_cost_changing_effect_alters_what_must_be_paid(cards):
    """Gloom makes activated abilities of white enchantments cost {3} more:
    the printed {1} is no longer enough, and {1} plus {3} succeeds (118.7)."""
    shrine = _mk_card(
        "Test Shrine",
        "Enchantment",
        "{1}: Test Shrine deals 1 damage to any target.",
        mana_cost="{W}",
        colors=("W",),
    )
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=shrine)], mana_pool={"C": 1})
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=cards["Gloom"])], life=20)
    game = _two_player_game(p1, p2, enforce=True)

    denied = game.activate_permanent_ability(0, "Test Shrine", target_player_index=1)
    assert not denied.supported
    assert "insufficient mana" in denied.details
    assert p2.life == 20

    p1.mana_pool["C"] = 4  # printed {1} + Gloom's {3}
    allowed = game.activate_permanent_ability(0, "Test Shrine", target_player_index=1)
    assert allowed.supported
    assert p2.life == 19
    assert p1.mana_pool.get("C", 0) == 0


# ---------------------------------------------------------------------------
# Rule 118.8 — Additional costs are paid alongside the spell's mana cost.
# ---------------------------------------------------------------------------


@pytest.mark.cr("118.8")
def test_118_8_additional_cost_sacrifice_is_paid_when_casting(cards):
    """Sacrifice ("As an additional cost to cast this spell, sacrifice a
    creature") sacrifices the chosen creature as part of casting (118.8)."""
    p1 = PlayerState(
        name="P1",
        hand=[cards["Sacrifice"]],
        battlefield=[_perm(cards["Gray Ogre"])],  # mana value 3
    )
    p2 = PlayerState(name="P2")
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Sacrifice", target_player_index=0, target_permanent_index=0)

    assert result.supported
    assert all(perm.card.name != "Gray Ogre" for perm in p1.battlefield)
    assert any(c.name == "Gray Ogre" for c in p1.graveyard)
    assert p1.mana_pool.get("B", 0) == 3  # {B} equal to the sacrificed mana value


@pytest.mark.cr("118.6")
def test_118_6_spell_with_no_mana_cost_cannot_be_cast():
    """An object with no mana cost has an unpayable cost — attempting to cast
    it is illegal (118.6). This differs from {0}, which casts for free (118.5)."""
    costless = _mk_card(
        name="Costless Spell",
        mana_cost="",
        type_line="Instant",
        oracle_text="Target player loses 1 life.",
    )
    p1 = PlayerState(name="P1", hand=[costless], mana_pool={"W": 5})
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2], enforce_mana_costs=True)

    result = game.cast_from_hand(0, "Costless Spell", target_player_index=1)

    assert not result.supported
    assert p2.life == 20
    assert costless in p1.hand  # never left the hand

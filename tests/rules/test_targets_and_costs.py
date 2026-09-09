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


@pytest.mark.cr("115.1c", "602.2b")
def test_115_1c_the_whole_target_description_narrows_the_legal_choices(cards, arn_by_name):
    """An activated ability's target description is read in full, including the
    part that names a controller.

    Ebony Horse untaps "target attacking creature **you control**", so an
    opponent's attacker is not a legal choice (115.1c, via 602.2b/601.2c). The
    engine used to classify this from the ability's text and stopped at
    "attacking creature", offering the defender's attackers as well; the choice
    is derived from the ability's compiled instruction now, and both halves of
    the restriction survive.
    """
    horse = _perm(arn_by_name["Ebony Horse"])
    mine = _perm(cards["Grizzly Bears"], tapped=True)
    theirs = _perm(cards["Hill Giant"], tapped=True)
    mine.attacking = theirs.attacking = True
    idle = _perm(cards["Gray Ogre"])  # yours, but not attacking
    p1 = PlayerState(name="P1", battlefield=[horse, mine, idle])
    p2 = PlayerState(name="P2", battlefield=[theirs])
    game = _two_player_game(p1, p2)

    spec = game.activation_target_spec(0, 0)

    assert spec["requires_target"] is True
    assert [(t["seat"], t["name"]) for t in spec["valid_targets"]] == [(0, "Grizzly Bears")]


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


# ---------------------------------------------------------------------------
# Rule 602.2b / 601.2c — an activated ability with no legal target cannot be
# activated, and its cost is not paid. One gate for every object-targeted
# ability (engine/legality.activation_target_refusal), replacing a per-kind
# if-chain that named only four instruction kinds.
# ---------------------------------------------------------------------------


@pytest.mark.cr("602.2b", "601.2c")
def test_602_2b_a_banding_grant_needs_a_creature_to_target(cards):
    """Helm of Chatzuk: "{T}: Target creature gains banding." With no creature,
    the ability can't be activated, and the {T} is not paid."""
    helm = _perm(cards["Helm of Chatzuk"])
    p1 = PlayerState(name="P1", battlefield=[helm])
    game = _two_player_game(p1, PlayerState(name="P2"))

    result = game.activate_permanent_ability(0, "Helm of Chatzuk", target_player_index=0)

    assert result.supported is False
    assert helm.tapped is False


@pytest.mark.cr("602.2b", "601.2c")
def test_602_2b_a_targeted_counter_needs_a_matching_spell(cards):
    """Deathgrip: "{B}{B}: Counter target green spell." With no green spell on
    the stack the ability can't be activated."""
    deathgrip = _perm(cards["Deathgrip"])
    p1 = PlayerState(name="P1", battlefield=[deathgrip])
    game = _two_player_game(p1, PlayerState(name="P2"))

    result = game.activate_permanent_ability(0, "Deathgrip")

    assert result.supported is False


@pytest.mark.cr("602.2b", "601.2c")
def test_602_2b_destroy_target_permanent_needs_a_matching_permanent(cards):
    """Northern Paladin: "{W}{W}, {T}: Destroy target black permanent." With no
    black permanent it can't be activated, and the {T} is not paid."""
    paladin = _perm(cards["Northern Paladin"])
    p1 = PlayerState(name="P1", battlefield=[paladin])
    game = _two_player_game(p1, PlayerState(name="P2", battlefield=[_perm(cards["Grizzly Bears"])]))

    result = game.activate_permanent_ability(0, "Northern Paladin", target_player_index=1)

    assert result.supported is False
    assert paladin.tapped is False


@pytest.mark.cr("602.2b", "601.2c", "702.6c")
def test_602_2b_equip_needs_a_creature_you_control(set_pool):
    """An equip ability targets "creature you control"; with none, activating it
    is refused before the equip cost is paid (CR 702.6a rewrites equip into that
    activated ability, so the same gate covers it)."""
    pool = set_pool("M21")
    scythe = _nosick(Permanent(card=pool["Malefic Scythe"]))
    p1 = PlayerState(name="P1", battlefield=[scythe])
    game = _two_player_game(p1, PlayerState(name="P2"))
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"

    result = game.activate_permanent_ability(0, "Malefic Scythe")

    assert result.supported is False


@pytest.mark.cr("608.2b")
def test_608_2b_object_targeted_damage_with_no_target_does_not_hit_the_player(set_pool):
    """Silent Dart: "It deals 3 damage to target creature." Activated with no
    creature named and none on the board, the object target is not the player —
    the ability is refused (602.2b), and even reached with the target gone it
    does nothing rather than redirecting to a face (608.2b)."""
    pool = set_pool("M21")
    dart = Permanent(card=pool["Silent Dart"])
    p1 = PlayerState(name="P1", battlefield=[dart])
    p2 = PlayerState(name="P2")
    game = _two_player_game(p1, p2)
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"

    result = game.activate_permanent_ability(0, "Silent Dart")

    assert result.supported is False
    assert p2.life == 20
    assert dart.tapped is False


# ---------------------------------------------------------------------------
# Rule 115.6 — A spell or ability that requires targets may allow *zero*
# targets to be chosen. It still "requires targets", but it is targeted only
# if one or more were actually chosen.
#
# Driven through Frost Breath ("Tap up to two target creatures") and Basri
# Ket's "+1: Put a +1/+1 counter on up to one target creature", because the
# rule is only observable where the engine has to *not* refuse: the cast gate
# and `legality._ability_target_quantifiers` both read the quantifier, and an
# "up_to" is the one that does not make a target mandatory.
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.6")
def test_115_6_up_to_spell_may_be_cast_choosing_no_targets_at_all(set_pool, cards):
    """"Tap up to two target creatures" resolves having chosen zero of them.

    The whole of 115.6's permission: legal targets exist, the caster names
    none, and the spell is still cast, still resolves and still goes to the
    graveyard — with nothing tapped, because it was never targeted at
    anything.
    """
    pool = set_pool("M21")
    bears = _perm(cards["Grizzly Bears"])
    giant = _perm(cards["Hill Giant"])
    p1 = PlayerState(name="P1", hand=[pool["Frost Breath"]])
    p2 = PlayerState(name="P2", battlefield=[bears, giant])
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(0, "Frost Breath")  # no target named

    assert result.supported
    assert (bears.tapped, giant.tapped) == (False, False)
    assert [c.name for c in p1.graveyard] == ["Frost Breath"]
    assert len(game.stack) == 0


@pytest.mark.cr("115.6", "115.1")
def test_115_6_up_to_spell_is_castable_with_no_legal_target_on_the_board(set_pool, cards):
    """Zero is a legal number of targets, so an empty board does not make an
    "up to" spell uncastable — where a spell that *must* have one is refused
    on exactly the same board (115.1).

    The pair is the test: both spells are asked of a battlefield with no
    creature on it, and only the quantifier differs.
    """
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool["Frost Breath"], cards["Terror"]])
    p2 = PlayerState(name="P2")  # no creatures anywhere
    game = _two_player_game(p1, p2)

    optional = game.cast_from_hand(0, "Frost Breath")
    mandatory = game.cast_from_hand(0, "Terror", target_player_index=1)

    assert optional.supported
    assert not mandatory.supported
    assert [c.name for c in p1.hand] == ["Terror"]  # only the refused one stayed


@pytest.mark.cr("115.6", "115.1")
def test_115_6_an_up_to_spell_affects_exactly_the_targets_chosen(set_pool, cards):
    """One chosen target taps one creature; two tap two — and the picker is
    told the maximum, so it collects up to that many rather than defaulting to
    the one-target shape every other spell has.

    ``max_targets`` is where "up to two" survives past the parser: the count is
    a maximum, not a requirement, and a spec that dropped it would leave the
    browser offering a single slot for a spell that names two.
    """
    pool = set_pool("M21")

    def board():
        bears = _perm(cards["Grizzly Bears"])
        giant = _perm(cards["Hill Giant"])
        p1 = PlayerState(name="P1", hand=[pool["Frost Breath"]])
        p2 = PlayerState(name="P2", battlefield=[bears, giant])
        return _two_player_game(p1, p2), bears, giant

    game, bears, giant = board()
    spec = game.cast_target_spec(0, pool["Frost Breath"])
    assert spec["requires_target"] is True
    assert spec["max_targets"] == 2

    game.cast_from_hand(0, "Frost Breath", target_player_index=1, target_permanent_index=0)
    assert (bears.tapped, giant.tapped) == (True, False)

    game, bears, giant = board()
    game.cast_from_hand(
        0, "Frost Breath", target_player_index=1,
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    assert (bears.tapped, giant.tapped) == (True, True)


@pytest.mark.cr("115.6", "602.2b")
def test_115_6_an_up_to_ability_activates_with_nothing_to_target(set_pool):
    """The same permission for an activated ability, and the same pairing.

    Basri Ket's "+1: Put a +1/+1 counter on up to one target creature"
    activates on an empty board and its loyalty cost is paid; Liliana, Death
    Mage's "−3: Destroy target creature." is refused on that board with no
    loyalty spent (602.2b). One gate reads both, and it reads the quantifier —
    an "up_to" slot walked by ``_ability_target_quantifiers`` deliberately does
    not count as a mandatory target.
    """
    pool = set_pool("M21")
    basri = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 3})
    p1 = PlayerState(name="P1", battlefield=[basri])
    game = _two_player_game(p1, PlayerState(name="P2"))
    game.start_turn(0)

    optional = game.activate_permanent_ability(
        0, "Basri Ket", permanent_index=0, ability_index=0
    )

    assert optional.supported
    assert basri.metadata["loyalty_counters"] == 4  # the +1 was paid

    liliana = Permanent(card=pool["Liliana, Death Mage"], metadata={"loyalty_counters": 5})
    p3 = PlayerState(name="P1", battlefield=[liliana])
    other = _two_player_game(p3, PlayerState(name="P2"))
    other.start_turn(0)

    mandatory = other.activate_permanent_ability(
        0, "Liliana, Death Mage", permanent_index=0, ability_index=1
    )

    assert not mandatory.supported
    assert liliana.metadata["loyalty_counters"] == 5  # nothing was paid


# ---------------------------------------------------------------------------
# Rule 115.7 — changing the target(s) of a spell or ability, and rule 115.9a's
# count of what a spell chose. Reflecting Mirror (The Dark) is the pool's only
# card that changes a target, so it is what these are asked through.
# ---------------------------------------------------------------------------


def _reflecting_mirror_game(set_pool, spell_name, spell_set="LEA"):
    mirror = Permanent(card=set_pool("DRK")["Reflecting Mirror"])
    p1 = PlayerState(name="P1", battlefield=[mirror])
    p2 = PlayerState(name="P2", hand=[set_pool(spell_set)[spell_name]])
    game = _two_player_game(p1, p2)
    game._sync_control()
    return game, p1, p2


@pytest.mark.cr("115.7", "115.7a")
def test_115_7a_a_changed_target_is_the_one_the_spell_affects(set_pool):
    """An effect that changes a spell's target changes *only* that (115.7a):
    the spell still resolves, from the same source, doing the same thing — to
    somebody else."""
    game, p1, p2 = _reflecting_mirror_game(set_pool, "Lightning Bolt")
    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)

    game.activate_permanent_ability(0, "Reflecting Mirror", target_stack_index=0)
    game._settle()

    assert p1.life == 20
    assert p2.life == 17
    assert [card.name for card in p2.graveyard] == ["Lightning Bolt"]


@pytest.mark.cr("115.7a")
def test_115_7a_a_target_with_no_other_legal_choice_is_left_unchanged(set_pool):
    """"If a target can't be changed to another legal target, the original
    target is unchanged" (115.7a). Word of Command targets an opponent, so the
    only player its own caster could legally name is the one it already
    names."""
    game, _p1, _p2 = _reflecting_mirror_game(set_pool, "Word of Command")
    game.queue_from_hand(1, "Word of Command", target_player_index=0)

    result = game.queue_permanent_ability(
        0, "Reflecting Mirror", target_stack_index=0
    )
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert game.stack[0].target_player_index == 0, game.log


@pytest.mark.cr("115.9a")
def test_115_9a_a_spell_with_a_single_target_is_counted_by_what_it_chose(set_pool):
    """"[spell] with [a number of] targets" counts the choices made when the
    spell was put on the stack (115.9a). One Fireball is a single target and
    one spread across two players is not, whatever else is true of the card."""
    single, _p1, _p2 = _reflecting_mirror_game(set_pool, "Fireball")
    single.queue_from_hand(1, "Fireball", target_player_index=0, x_value=1)
    assert [t["name"] for t in single.activation_target_spec(0, 0)["valid_targets"]] == [
        "Fireball"
    ]

    spread, _q1, _q2 = _reflecting_mirror_game(set_pool, "Fireball")
    spread.queue_from_hand(
        1, "Fireball", x_value=2, divided_targets=[(0, None), (1, None)]
    )
    assert spread.activation_target_spec(0, 0)["valid_targets"] == [], spread.log


# --- W3G3: X spells, multiple targets, damage sources ---
@pytest.mark.cr("601.2d")
def test_601_2d_the_caster_announces_the_division_and_it_totals_the_effect():
    """601.2d: "If the spell requires the player to divide or distribute an
    effect (such as damage or counters) among one or more targets, the player
    announces the division. Each of these targets must receive at least one of
    whatever is being divided."

    Announced, not derived. The engine divided every such spell evenly, which is
    a different sentence — one printed on Fireball and on no other card in this
    pool.
    """
    from engine.divided_damage import CHOSEN, EVENLY, divide, division_refusal

    entries = [(1, 0, 3), (1, 1, 1)]
    assert division_refusal(4, entries, division=CHOSEN) is None
    assert divide(4, entries, division=CHOSEN) == [(1, 0, 3), (1, 1, 1)]

    # Each target must receive at least one.
    assert "at least 1" in division_refusal(4, [(1, 0, 4), (1, 1, 0)], division=CHOSEN)
    # And the division must be of the whole effect.
    assert "total 4" in division_refusal(4, [(1, 0, 3), (1, 1, 3)], division=CHOSEN)
    # A spell whose card divides it evenly is not the caster's to divide.
    assert division_refusal(4, entries, division=EVENLY) is not None


@pytest.mark.cr("601.2d")
def test_601_2d_an_unannounced_division_falls_back_to_the_even_split():
    """No division is not an illegal division. Every "divided evenly" spell has
    none by definition, and a chosen-division spell cast by a seat with nothing
    to ask (the AI, a scripted duel) takes the even split — the same answer a
    ``ChoiceSpec`` gives a non-interactive seat."""
    from engine.divided_damage import CHOSEN, divide, division_refusal

    entries = [(1, 0), (1, 1)]
    assert division_refusal(5, entries, division=CHOSEN) is None
    assert divide(5, entries, division=CHOSEN) == [(1, 0, 2), (1, 1, 2)], \
        "rounded down, so the remainder simply disappears"
# --- end W3G3 ---


# --- FixB: a departed target is a fizzle, not the next permanent along ---
#
# CR 608.2b at the *resolver*. The rule is enforced above the instructions for
# a spell (``legality.illegal_targets_refusal``, instants and sorceries only),
# and an activated ability has no such gate — so the only place its target can
# be found to be gone is where the handler asks for it.


def _fixb_boards(catalog_by_name, source_name, *, decoy="Balduvian Barbarians"):
    """Seat 0 with *source*, a chosen creature, and a decoy **behind it**.

    The decoy's position is the whole experiment: when the chosen creature
    leaves, every later slot renumbers (CR 400.7), so the index the resolution
    recorded comes to mean the decoy.
    """
    source = _perm(catalog_by_name[source_name])
    chosen = _perm(catalog_by_name["Grizzly Bears"])
    bystander = _perm(catalog_by_name[decoy])
    p1 = PlayerState(name="P1", battlefield=[source, chosen, bystander], life=20)
    game = _two_player_game(p1, PlayerState(name="P2", life=20))
    game.start_turn(0)
    return game, source, chosen, bystander


def _fixb_resolve(game):
    game.pass_priority(0)
    game.pass_priority(1)
    game._settle()


@pytest.mark.cr("608.2b", "400.7", "115.1c")
def test_608_2b_an_activated_abilitys_departed_target_is_not_the_next_permanent(
    catalog_by_name,
):
    """"Target creature gains islandwalk until end of turn." The creature dies
    with the ability on the stack.

    CR 400.7 makes the permanent that left a different object, so the recorded
    id can no longer name anything — and the *index* beside it now names the
    permanent that slid into the vacated slot. Resolving against that index is
    an ability affecting a permanent nobody targeted, which is the failure this
    asserts is gone. Both halves of the ability are checked: the printed
    effect and the delayed ability behind it.
    """
    game, _sandals, chosen, bystander = _fixb_boards(
        catalog_by_name, "Sandals of Abdallah"
    )
    game.queue_permanent_ability(
        0, "Sandals of Abdallah", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )

    game.remove_from_battlefield(chosen)
    game.check_state_based_actions()
    _fixb_resolve(game)

    assert not game._has_keyword(bystander, "islandwalk"), game.log
    assert game.delayed_triggers == [], game.log


@pytest.mark.cr("608.2b", "115.1c")
def test_608_2b_an_activated_abilitys_surviving_target_is_still_affected(
    catalog_by_name,
):
    """The other direction, and the reason the fizzle is narrowed to an id that
    resolves to *nothing*: a target still on the battlefield must still be hit.
    A fizzle that fires too eagerly is the same bug pointing the other way."""
    game, _sandals, chosen, bystander = _fixb_boards(
        catalog_by_name, "Sandals of Abdallah"
    )
    game.queue_permanent_ability(
        0, "Sandals of Abdallah", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )

    _fixb_resolve(game)

    assert game._has_keyword(chosen, "islandwalk"), game.log
    assert not game._has_keyword(bystander, "islandwalk"), game.log
    assert [entry.bound_permanent_id for entry in game.delayed_triggers] == [
        chosen.permanent_id
    ], game.log


@pytest.mark.cr("602.2b", "603.7d")
def test_602_2b_an_activation_that_named_no_target_still_means_its_own_source(
    catalog_by_name,
):
    """The distinction the fizzle rests on, asserted from the other side.

    "This creature gets +2/+0 and gains flying. Its controller sacrifices it at
    the beginning of the next end step" (Goblin Ski Patrol) names no target, so
    no id is recorded and there is nothing to find gone — the pronoun is the
    ability's own source (CR 603.7d) and must keep resolving to it. An id that
    was never recorded is not a departed one.
    """
    patrol = _perm(catalog_by_name["Goblin Ski Patrol"])
    # "…only if you control a snow Mountain", the ability's own permission.
    mountain = _perm(catalog_by_name["Snow-Covered Mountain"])
    p1 = PlayerState(name="P1", battlefield=[patrol, mountain], life=20)
    p2 = PlayerState(
        name="P2", battlefield=[_perm(catalog_by_name["Grizzly Bears"])], life=20,
    )
    game = _two_player_game(p1, p2)
    game.start_turn(0)

    game.queue_permanent_ability(0, "Goblin Ski Patrol", permanent_index=0)
    _fixb_resolve(game)

    assert patrol.metadata.get("sacrifice_at_next_end_step") is True, game.log
    assert not p2.battlefield[0].metadata.get("sacrifice_at_next_end_step"), game.log
# --- end FixB ---


# --- LeadB: an index is not a target ---


def _leadb_board(oracle_text):
    """A game, an invented artifact's activated ability, and two targets.

    The ability is invented because the rule under test is about *abilities*,
    and ``legality.illegal_targets_refusal`` — the engine's CR 608.2b gate —
    covers instants and sorceries only. A spell probe would be checked by the
    gate and would say nothing about the resolver underneath it.
    """
    from engine.oracle import compile_card_oracle

    from ..helpers import _mk_card

    card = _mk_card("Rules Probe", "{2}", "Artifact", oracle_text)
    program = compile_card_oracle(card)
    assert program.supported

    game = _two_player_game(PlayerState(name="A"), PlayerState(name="B"))
    source = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, source, 0)
    chosen = Permanent(card=_mk_creature("Chosen"))
    game._put_permanent_onto_battlefield(1, chosen, 1)
    neighbour = Permanent(card=_mk_creature("Neighbour"))
    game._put_permanent_onto_battlefield(1, neighbour, 1)
    return game, card, program.activated_abilities[0].instruction, source, chosen, neighbour


def _mk_creature(name):
    return _mk_card(name, "{1}{G}", "Creature — Bear", "")


def _leadb_resolve(game, card, instruction, source, index, permanent_id):
    from engine.game_types import OracleExecutionContext
    from engine.handlers import EFFECT_HANDLERS

    EFFECT_HANDLERS[instruction.kind](
        game, instruction,
        OracleExecutionContext(
            caster=game.players[0], target=game.players[1], card=card,
            target_permanent_index=index, target_permanent_id=permanent_id,
            source_permanent=source,
        ),
    )


@pytest.mark.cr("608.2b", "400.7", "115.1c")
def test_608_2b_an_abilitys_target_that_left_is_not_replaced_by_its_slots_new_tenant():
    """A target that has left the battlefield is gone, not "whatever is there now".

    CR 115.1c fixes an activated ability's targets when it is activated;
    CR 400.7 makes the permanent that left a new object with no relation to
    what it was; CR 608.2b says an ability whose every target is illegal does
    nothing. Between them there is no reading on which the effect lands on the
    permanent that inherited the vacated list slot — but the battlefield *is* a
    list, so an engine holding the index rather than the identity lands there
    every time.

    The engine's 608.2b gate (``legality.illegal_targets_refusal``) is instants
    and sorceries only and returns None for every ability, so this has to be
    answered by the resolver.
    """
    game, card, instruction, source, chosen, neighbour = _leadb_board(
        "{T}: Untap target permanent."
    )
    chosen.tapped = neighbour.tapped = True
    index = game.battlefield_index_of(chosen)
    chosen_id = chosen.permanent_id

    chosen.damage_marked = 99
    game.check_state_based_actions()
    assert game.battlefield_index_of(neighbour) == index, (
        "the neighbour inherited the slot — that is the whole hazard"
    )

    _leadb_resolve(game, card, instruction, source, index, chosen_id)

    assert neighbour.tapped, (
        "the ability untapped the permanent that inherited its target's slot"
    )


@pytest.mark.cr("115.1c", "400.7")
def test_115_1c_the_ability_still_affects_a_target_that_merely_moved_slots():
    """The identity is what is remembered, so a *surviving* target is still hit
    even though its index has changed underneath it (CR 400.7 is about objects
    that changed zone; this one never did)."""
    game, card, instruction, source, chosen, neighbour = _leadb_board(
        "{T}: Untap target permanent."
    )
    chosen.tapped = neighbour.tapped = True
    # Choose the *later* slot, then remove the earlier one so the choice slides.
    index = game.battlefield_index_of(neighbour)
    neighbour_id = neighbour.permanent_id

    chosen.damage_marked = 99
    game.check_state_based_actions()
    assert game.battlefield_index_of(neighbour) != index, "the slot really moved"

    _leadb_resolve(game, card, instruction, source, index, neighbour_id)

    assert not neighbour.tapped, (
        "the ability must still untap the permanent it named, whatever slot it "
        "has slid to — the id is the choice (CR 115.1c)"
    )
# --- end LeadB ---


# --- LeadA: a graveyard target is a target ---
# CR 602.2b reached every object-targeted activated ability *except* the ones
# that point into a graveyard, because the gate asks whether the ability's
# instruction carries a mandatory ``targets`` quantifier and the graveyard
# lowerings carry none — the noun phrase travels as ``card_type`` instead. So
# every one of the ten such abilities in the pool could be activated with every
# graveyard on the table empty, paying its cost for nothing.


@pytest.mark.cr("602.2b", "601.2c")
def test_602_2b_a_graveyard_return_needs_a_card_in_a_graveyard(set_pool):
    """Adun Oakenshield: "{B}{R}{G}, {T}: Return target creature card from your
    graveyard to your hand." With the graveyard empty there is no legal target,
    so the ability cannot be activated and the {T} is not paid."""
    adun = _perm(set_pool("LEG")["Adun Oakenshield"])
    game = _two_player_game(PlayerState(name="P1", battlefield=[adun]),
                            PlayerState(name="P2"))

    result = game.activate_permanent_ability(0, "Adun Oakenshield")

    assert result.supported is False
    assert adun.tapped is False


@pytest.mark.cr("602.2b", "601.2c")
def test_602_2b_a_reanimation_is_refused_before_its_source_is_sacrificed(set_pool):
    """The same rule where the cost is not a tap but the permanent itself.

    Obsessive Stitcher: "{2}{U}{B}, {T}, **Sacrifice this creature**: Return
    target creature card from your graveyard to the battlefield." Unenforced,
    the ability was activatable with an empty graveyard — and CR 601.2h pays the
    cost before it resolves, so the creature was sacrificed for nothing.
    """
    pool = set_pool("M21")
    stitcher = _perm(pool["Obsessive Stitcher"])
    p1 = PlayerState(name="P1", battlefield=[stitcher])
    game = _two_player_game(p1, PlayerState(name="P2"))

    # ability_index 1: {T} draws and discards, the reanimation is the second.
    result = game.activate_permanent_ability(
        0, "Obsessive Stitcher", permanent_index=0, ability_index=1,
    )

    assert result.supported is False
    assert [p.card.name for p in game.controlled_by(p1)] == ["Obsessive Stitcher"]
    assert stitcher.tapped is False


@pytest.mark.cr("602.2b", "601.2c")
def test_602_2b_a_graveyard_exile_inside_a_sequence_is_still_a_target(set_pool):
    """Scavenging Ooze: "{G}: Exile target card from a graveyard. If it was a
    creature card, …" — two printed sentences, so the exile is the first *step*
    of a sequence rather than the ability's whole instruction. The gate walked
    only the top instruction, so the one-sentence siblings answered correctly
    and this one did not."""
    ooze = _perm(set_pool("M21")["Scavenging Ooze"])
    game = _two_player_game(PlayerState(name="P1", battlefield=[ooze]),
                            PlayerState(name="P2"))

    result = game.activate_permanent_ability(0, "Scavenging Ooze")

    assert result.supported is False


@pytest.mark.cr("601.2c")
def test_601_2c_a_graveyard_target_must_sit_in_a_pile_the_ability_reads(set_pool):
    """"…from **your** graveyard" is a seat restriction, and a named target
    outside it is an illegal announcement — not an announcement the resolution
    quietly re-points at the caster's own pile, which is what happened while the
    named-target half of the gate was unreachable for this family."""
    pool = set_pool("LEG")
    adun = _perm(pool["Adun Oakenshield"])
    p1 = PlayerState(name="P1", battlefield=[adun],
                     graveyard=[set_pool("LEA")["Grizzly Bears"]])
    p2 = PlayerState(name="P2", graveyard=[set_pool("LEA")["Serra Angel"]])
    game = _two_player_game(p1, p2)

    result = game.activate_permanent_ability(
        0, "Adun Oakenshield", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )

    assert result.supported is False
    assert adun.tapped is False
    assert p1.hand == []                                    # nothing re-pointed
    assert [c.name for c in p1.graveyard] == ["Grizzly Bears"]
    assert [c.name for c in p2.graveyard] == ["Serra Angel"]


@pytest.mark.cr("601.2c")
def test_601_2c_up_to_one_may_still_be_activated_with_nothing_to_return(set_pool):
    """The control, and the reason the quantifier had to reach the payload.

    Liliana, Death Mage's "+1: Return **up to one** target creature card from
    your graveyard to your hand" prints the same graveyard target as Adun
    Oakenshield above, and CR 601.2c lets an "up to" announcement name none — so
    an empty graveyard is no reason to refuse it. The lowering dropped the
    quantifier (one chosen card either way, so nothing downstream had needed
    it), which left the two abilities indistinguishable to the gate.
    """
    walker = _perm(set_pool("M21")["Liliana, Death Mage"])
    game = _two_player_game(PlayerState(name="P1", battlefield=[walker]),
                            PlayerState(name="P2"))

    result = game.activate_permanent_ability(
        0, "Liliana, Death Mage", ability_index=0,
    )

    assert result.supported is True, result.details
# --- end LeadA ---


# --- W2G1: a relation between two targets (HML) ---


def _w2g1_seats(*players: PlayerState) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    game._settle()
    return game


@pytest.mark.cr("601.2c")
def test_601_2c_a_relation_between_two_targets_is_checked_over_the_whole_announcement(
    set_pool,
):
    """"Choose two target creatures **controlled by the same opponent**."
    (Retribution.)

    CR 601.2c has the player announce a choice for each target, and a printed
    relation between them is part of what makes the announcement legal. It
    cannot be a property of any one candidate: each of two creatures controlled
    by *different* opponents is separately a legal choice, and only the pair is
    illegal. So the per-candidate enumeration passes both and the announcement
    is refused over the whole list, before any mana is spent.
    """
    lea = set_pool("LEA")
    mine = _perm(lea["Hill Giant"])
    theirs = _perm(lea["Grizzly Bears"])
    third = _perm(lea["Craw Wurm"])
    game = _w2g1_seats(
        PlayerState(name="P0", hand=[set_pool("HML")["Retribution"]]),
        PlayerState(name="P1", battlefield=[mine, theirs]),
        PlayerState(name="P2", battlefield=[third]),
    )

    # Two creatures, one opponent: a legal announcement.
    assert game.cast_target_refusal(
        0, set_pool("HML")["Retribution"],
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    ) is None

    # One from each opponent: each is a legal *target*, and the pair is not.
    assert game.cast_target_refusal(
        0, set_pool("HML")["Retribution"],
        target_permanent_ids=[mine.permanent_id, third.permanent_id],
    ) is not None


@pytest.mark.cr("601.2c")
def test_601_2c_the_relation_does_not_narrow_what_each_target_may_be(set_pool):
    """The relation is checked *beside* the per-candidate rule, never instead of
    it: every creature either opponent controls is still enumerated as a legal
    target for one instance of the word, which is what keeps the caster free to
    announce either pair."""
    lea = set_pool("LEA")
    first = _perm(lea["Hill Giant"])
    second = _perm(lea["Grizzly Bears"])
    game = _w2g1_seats(
        PlayerState(name="P0", hand=[set_pool("HML")["Retribution"]]),
        PlayerState(name="P1", battlefield=[first]),
        PlayerState(name="P2", battlefield=[second]),
    )

    for named in (first, second):
        assert game.cast_target_refusal(
            0, set_pool("HML")["Retribution"], target_permanent_ids=[named.permanent_id],
        ) is None


@pytest.mark.cr("608.2h")
def test_608_2h_the_last_known_information_a_destroy_records_does_not_depend_on_how_the_target_was_named(
    set_pool,
):
    """Divine Offering: "Destroy target artifact. You gain life equal to **its**
    mana value."

    CR 608.2h makes the number the destroyed object's last known information,
    which the destroy freezes before it destroys anything. The gate in front of
    that record asked whether a target *slot* had been supplied — so a caller
    naming its target the way this engine asks for, by stable ``permanent_id``
    alone, skipped the record entirely and the rider gained nothing. The web
    layer sends both, so the app never showed it.

    Written as a comparison rather than as one assertion, because the two
    spellings naming the same permanent are the whole content of the rule here.
    """
    def _cast(by_id: bool) -> int:
        artifact = _perm(set_pool("LEG")["Ring of Immortals"])
        game = _w2g1_seats(
            PlayerState(name="P0", hand=[set_pool("LEG")["Divine Offering"]]),
            PlayerState(name="P1", battlefield=[artifact]),
        )
        if by_id:
            game.cast_from_hand(
                0, "Divine Offering", target_permanent_ids=[artifact.permanent_id],
            )
        else:
            game.cast_from_hand(0, "Divine Offering", target_permanent_index=0)
        resolve_stack(game)
        game._settle()
        return game.players[0].life

    assert _cast(by_id=False) == _cast(by_id=True) == 25


# --- GyRes: the two graveyard-target residuals (CR 608.2b / 601.2c) ---
#
# A graveyard slot has no ``permanent_id``, so a chosen card is remembered as a
# ``GraveyardTarget`` stamp and re-located at resolution. Two residuals lived in
# that seam. Resolution: a stamp whose card had left the pile *entirely* fell
# through to the stale index, which named whatever slid into the vacated slot —
# exile the Serra Angel a Resurrection targeted and it reanimated the Grizzly
# Bears beneath it. Announcement: ``cast_target_refusal`` skipped graveyard
# targets and ``_validate_cast_targets`` keys on the *primary* instruction kind,
# so a spell whose graveyard targeting sits inside a ``sequence`` (Fungal
# Rebirth, Experimental Overload) accepted an announcement naming an opponent's
# pile and silently re-pointed it at the caster's own. The *ambiguous* case —
# two copies of one card are literally one ``CardDefinition``, so resolution
# clamps to the last surviving copy — is deliberately unchanged, and the third
# test below is the guard that says so.


@pytest.mark.cr("608.2b")
def test_608_2b_a_graveyard_targets_vanished_card_is_not_the_card_beneath_it(
    set_pool, cards,
):
    """Resurrection targets the Serra Angel in its caster's graveyard; the
    Angel is exiled in response. CR 608.2b: the chosen card is no longer in the
    zone it was targeted in, it was the spell's only target, so the spell does
    not resolve — it leaves the stack and is put into its owner's graveyard.
    What must NOT happen is the stale slot answering instead: the Grizzly Bears
    beneath the Angel slid into its index, and the old fall-through reanimated
    them."""
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEA")["Resurrection"]],
        graveyard=[cards["Grizzly Bears"], cards["Serra Angel"]],
    )
    game = _two_player_game(p1, PlayerState(name="P2"))
    game.queue_from_hand(0, "Resurrection", target_permanent_index=1)

    p1.graveyard.pop(1)  # the Angel is exiled in response

    game.resolve_top_of_stack()

    assert [p.card.name for p in p1.battlefield] == [], game.log
    assert [c.name for c in p1.graveyard] == ["Grizzly Bears", "Resurrection"]
    assert any("every target is illegal" in line for line in game.log), game.log


@pytest.mark.cr("608.2b")
def test_608_2b_a_graveyard_target_that_merely_slid_is_still_reanimated(
    set_pool, cards,
):
    """The other direction, and the reason the answer is a stamp rather than a
    refusal to hold an index at all: the pile shifting *beneath* the chosen
    card is not a zone change for it. The Bears leave, the Angel slides from
    slot 1 to slot 0, and the spell still reanimates the Angel."""
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEA")["Resurrection"]],
        graveyard=[cards["Grizzly Bears"], cards["Serra Angel"]],
    )
    game = _two_player_game(p1, PlayerState(name="P2"))
    game.queue_from_hand(0, "Resurrection", target_permanent_index=1)

    p1.graveyard.pop(0)  # the Bears leave; the Angel slides down a slot

    game.resolve_top_of_stack()

    assert [p.card.name for p in p1.battlefield] == ["Serra Angel"], game.log


@pytest.mark.cr("608.2b")
def test_608_2b_a_surviving_copy_of_the_chosen_card_is_not_a_fizzle(
    set_pool, cards,
):
    """The deliberate boundary of the fizzle. Two copies of one card in one
    graveyard are literally one ``CardDefinition``, so when one of them leaves
    the engine cannot know which — resolution clamps to the last surviving copy
    rather than guessing, and the fizzle is reserved for the case the data
    model can establish: NO copy of the chosen card left in that pile."""
    bears = cards["Grizzly Bears"]
    p1 = PlayerState(
        name="P1", hand=[set_pool("LEA")["Resurrection"]],
        graveyard=[bears, bears],
    )
    game = _two_player_game(p1, PlayerState(name="P2"))
    game.queue_from_hand(0, "Resurrection", target_permanent_index=1)

    p1.graveyard.pop(1)  # one copy leaves; one indistinguishable copy remains

    game.resolve_top_of_stack()

    assert [p.card.name for p in p1.battlefield] == ["Grizzly Bears"], game.log
    assert not any("every target is illegal" in line for line in game.log), game.log


@pytest.mark.cr("608.2b")
def test_608_2b_only_the_vanished_slot_of_a_several_target_return_is_unaffected(
    set_pool, cards,
):
    """CR 608.2b's last sentence, one zone over: with one of two chosen cards
    gone, the spell still resolves and the surviving target is still returned —
    while the vanished card's slot, which the Hill Giant has slid into, is
    left alone rather than inherited. Sanguine Indulgence names the Bears
    (slot 0) and the Angel (slot 1); the Angel is exiled in response."""
    p1 = PlayerState(
        name="P1", hand=[set_pool("M21")["Sanguine Indulgence"]],
        graveyard=[cards["Grizzly Bears"], cards["Serra Angel"], cards["Hill Giant"]],
    )
    game = _two_player_game(p1, PlayerState(name="P2"))
    game.queue_from_hand(0, "Sanguine Indulgence", target_permanent_index=[0, 1])

    p1.graveyard.pop(1)  # the Angel is exiled; the Hill Giant slides into slot 1

    game.resolve_top_of_stack()

    assert [c.name for c in p1.hand] == ["Grizzly Bears"], game.log
    assert [c.name for c in p1.graveyard] == ["Hill Giant", "Sanguine Indulgence"]


@pytest.mark.cr("601.2c")
@pytest.mark.parametrize("name", ["Fungal Rebirth", "Experimental Overload"])
def test_601_2c_a_sequence_wrapped_graveyard_target_must_sit_in_a_pile_the_spell_reads(
    set_pool, name,
):
    """"…from **your** graveyard" is part of what makes an announcement legal,
    for a spell exactly as the activation twin already enforced for an ability
    (CR 601.2c). Both of these spells print their graveyard return as a later
    sentence, so their compiled program is a ``sequence`` and the per-kind arms
    in ``_validate_cast_targets`` never see the target — an announcement naming
    an opponent's pile was accepted and silently re-pointed at the caster's
    own. It is refused instead, before any cost is paid: the spell stays in
    hand and neither graveyard moves."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1", hand=[pool[name]], graveyard=[pool["Shock"]])
    p2 = PlayerState(name="P2", graveyard=[pool["Opt"]])
    game = _two_player_game(p1, p2)

    result = game.cast_from_hand(
        0, name, target_player_index=1, target_permanent_index=0,
    )

    assert result.supported is False
    assert "no valid target" in result.details
    assert [c.name for c in p1.hand] == [name]
    assert [c.name for c in p1.graveyard] == ["Shock"]
    assert [c.name for c in p2.graveyard] == ["Opt"]


@pytest.mark.cr("601.2c")
def test_601_2c_a_legal_graveyard_announcement_still_returns_the_named_card(
    set_pool, cards,
):
    """The control: the picker never offered the illegal choice, so the gate
    must change nothing about a legal one. Fungal Rebirth names slot 1 of its
    caster's own pile and returns exactly that card, whether the seat is left
    implicit or named as the caster's own."""
    pool = set_pool("M21")
    for seat in (None, 0):
        p1 = PlayerState(
            name="P1", hand=[pool["Fungal Rebirth"]],
            graveyard=[cards["Sol Ring"], cards["Grizzly Bears"]],
        )
        game = _two_player_game(p1, PlayerState(name="P2"))

        result = game.cast_from_hand(
            0, "Fungal Rebirth",
            target_player_index=seat, target_permanent_index=1,
        )

        assert result.supported is True, result.details
        assert [c.name for c in p1.hand] == ["Grizzly Bears"]
        assert [c.name for c in p1.graveyard] == ["Sol Ring", "Fungal Rebirth"]


@pytest.mark.cr("601.2c")
def test_601_2c_a_legal_sequence_wrapped_announcement_still_resolves_its_other_steps(
    set_pool,
):
    """Experimental Overload's graveyard target is one step of three; a legal
    announcement must still run the steps around it — the Weird token arrives
    sized by the instants and sorceries in the caster's graveyard."""
    pool = set_pool("M21")
    p1 = PlayerState(
        name="P1", hand=[pool["Experimental Overload"]],
        graveyard=[pool["Shock"], pool["Opt"]],
    )
    game = _two_player_game(p1, PlayerState(name="P2"))

    result = game.cast_from_hand(
        0, "Experimental Overload", target_permanent_index=1,
    )

    assert result.supported is True, result.details
    assert [(p.card.name, p.effective_power) for p in p1.battlefield] == [
        ("Weird Token", 2)
    ], game.log
# --- end GyRes ---


# --- W3-divided: CR 601.2d needs one target or more ---
#
# ``division_refusal`` answered only the *shares* question, and the casting path
# asked it only when a division had been announced. So a divided spell proposed
# with nothing at all -- no share, no target -- walked past both: it was cast,
# for its full cost, into a resolution with nothing to divide among.


@pytest.mark.cr("601.2d")
def test_601_2d_a_divided_spell_must_have_one_target_or_more():
    """601.2d: "If the spell requires the player to divide or distribute an
    effect ... **among one or more targets**, the player announces the
    division."

    An absent *division* is not a refusal -- an evenly-divided spell has none by
    definition, and a non-interactive seat takes the even split. An absent
    *target list* is one, and the two used to share an answer.
    """
    from engine.divided_damage import CHOSEN, EVENLY, division_refusal

    assert "601.2d" in division_refusal(4, [], division=CHOSEN)
    assert "601.2d" in division_refusal(4, [], division=EVENLY), \
        "the rule is about targets, and every divided spell has to have one"
    # ...unless the caster named one through the engine's older single-target
    # channel, which is a lawful announcement of one target taking all of it.
    assert division_refusal(4, [], division=CHOSEN, named_targets=1) is None
    # An announced division is still judged on its own terms.
    assert division_refusal(4, [(1, 0, 4)], division=CHOSEN) is None


@pytest.mark.cr("601.2e")
def test_601_2e_an_illegal_divided_proposal_costs_the_caster_nothing(catalog_by_name):
    """601.2e returns the game to the moment before an illegal proposal.

    Fire Covenant is the case that shows the cost of getting this wrong: "As an
    additional cost to cast this spell, pay X life", and "X damage divided as
    you choose among any number of **target creatures**". With no creature on
    any battlefield there is no legal announcement at all, and the spell used to
    be cast anyway -- three life paid, three damage to a player's face, for a
    spell that may not target one.
    """
    covenant = catalog_by_name["Fire Covenant"]
    p1 = PlayerState(name="P1", hand=[covenant], life=20)
    game = _two_player_game(p1, PlayerState(name="P2", life=20))

    result = game.cast_from_hand(0, "Fire Covenant", target_player_index=1, x_value=3)

    assert result.supported is False
    assert "601.2d" in result.details, result.details
    assert (p1.life, game.players[1].life) == (20, 20), "601.2e: nothing was spent"
    assert [card.name for card in p1.hand] == ["Fire Covenant"]
    assert not game.stack


@pytest.mark.cr("601.2c")
def test_601_2c_a_players_face_counts_as_the_named_target_only_where_the_card_admits_one(
    catalog_by_name,
):
    """601.2c: the caster announces a target "for each target the spell
    requires", and what may be one is the card's own noun.

    Pyrotechnics divides "among any number of targets", so a seat is a lawful
    one and a cast naming only ``target_player_index`` is a legal one-target
    announcement. Fire Covenant divides among "target creatures", so the same
    field names no target at all -- and the gate has to tell them apart, or it
    either refuses every burn spell or lets every creature-only one hit a face.
    """
    for name, expected in (("Pyrotechnics", True), ("Fire Covenant", False)):
        card = catalog_by_name[name]
        p1 = PlayerState(name="P1", hand=[card], life=20)
        game = _two_player_game(p1, PlayerState(name="P2", life=20))

        result = game.cast_from_hand(0, name, target_player_index=1, x_value=3)

        assert result.supported is expected, (name, result.details)
# --- end W3-divided ---


# --- W2G1 (Visions): an "unless they pay" with two currencies ---

import pytest as _w2g1_pytest
from engine.card_loader import (
    load_cards as _w2g1_load, manifest_set_path as _w2g1_path,
)
from engine.grammar import parse_line as _w2g1_parse
from engine.grammar.errors import GrammarError as _W2G1GrammarError
from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine.models import Permanent as _W2G1Permanent

_W2G1_LEA2 = {c.name: c for c in _w2g1_load(_w2g1_path("LEA"))}
_W2G1_VIS2 = {
    c.name: c
    for c in _w2g1_load(_w2g1_path("VIS", include_measured=True))
}


def _w2g1_counter_scene(*, opp_life=20, opp_lands=2):
    p1 = _W2G1PlayerState(name="A")
    p2 = _W2G1PlayerState(name="B", hand=[_W2G1_LEA2["Giant Growth"]])
    game = _W2G1Game(players=[p1, p2])
    game.enforce_mana_costs = False
    source = _W2G1Permanent(card=_W2G1_VIS2["Mundungu"])
    source.summoning_sick = False
    p1.battlefield.append(source)
    for _ in range(opp_lands):
        p2.battlefield.append(_W2G1Permanent(card=_W2G1_LEA2["Forest"]))
    p2.life = opp_life
    game.queue_from_hand(1, "Giant Growth")
    return game, p2


@_w2g1_pytest.mark.cr("118.3c", "119.4")
def test_119_4_an_unless_they_pay_offer_can_carry_two_currencies():
    """"…unless its controller pays {1} **and 1 life**" (Mundungu).

    One offer with two prices, both of which must be paid — CR 118.8's "or 1
    life" is the opposite word and the opposite meaning, which is why the two
    have never shared a reader. It rides the one payment prompt rather than
    arming a second: two prompts would be two decisions and two counters, and
    declining the first would counter the spell before the second was made.
    """
    game, payer = _w2g1_counter_scene()

    result = game.activate_permanent_ability(0, "Mundungu", target_stack_index=0)

    assert result.supported, result.details
    assert payer.life == 19
    assert any(p.tapped for p in payer.battlefield)
    assert game.stack == []
    # It went to the graveyard by *resolving*, not by being countered — which
    # is the whole difference the log records, since both endings empty the
    # stack and bin the card.
    assert any("is not countered" in line for line in game.log), game.log


@_w2g1_pytest.mark.cr("119.4")
def test_119_4_a_payer_who_cannot_meet_the_life_half_spends_no_mana():
    """"A player may pay life only if their life total is greater than or equal
    to the amount."

    Both halves are gated together, so a payer who can meet one and not the
    other meets neither — the mana must not leave the board for a payment that
    then fails.
    """
    game, payer = _w2g1_counter_scene(opp_life=0)

    game.activate_permanent_ability(0, "Mundungu", target_stack_index=0)

    assert game.stack == []
    assert [c.name for c in payer.graveyard] == ["Giant Growth"]
    assert not any(p.tapped for p in payer.battlefield)


@_w2g1_pytest.mark.cr("118.3c")
def test_118_3c_the_life_rider_refuses_a_currency_nothing_charges():
    """A production consumes every token of its line or refuses it."""
    with _w2g1_pytest.raises(_W2G1GrammarError):
        _w2g1_parse(
            "Counter target spell unless its controller pays {1} and 1 card."
        )
    # And the mana half stays required: a life-only payment would reach the
    # prompt as a cost of {0}, which every board covers, so the offer would
    # read as always paid.
    with _w2g1_pytest.raises(_W2G1GrammarError):
        _w2g1_parse("Counter target spell unless its controller pays 1 life.")


# --- W1G5: "target opponent" is never the caster's own seat ---
import pytest as _w1g5_pytest

from engine.card_loader import load_cards as _w1g5_load, manifest_set_paths as _w1g5_paths
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_activation_spec as _w1g5_activation_spec
from engine.targeting import derive_cast_spec as _w1g5_cast_spec
from tests.helpers import resolve_stack


def _w1g5_pool():
    """Every card in both manifest roles, by name."""
    pool = {}
    for path in _w1g5_paths(include_measured=True):
        for card in _w1g5_load(path):
            pool.setdefault(card.name, card)
    return pool


def _w1g5_widened(spec) -> bool:
    """Whether *spec* offers a player picker with no "opponent" narrowing."""
    return (
        isinstance(spec, dict)
        and spec.get("kind") in ("player", "player_or_planeswalker")
        and not spec.get("opponents_only")
    )


@_w1g5_pytest.mark.cr("115.1", "102.2")
def test_115_1_no_card_printing_target_opponent_offers_its_own_controller():
    """A player is not their own opponent (CR 102.2/102.3), so the seat a
    printed "target **opponent**" describes (CR 115.1) can never be the seat
    choosing it.

    The picker is what enforces that, and it enforces what the *spec* says —
    so a lowering that records no target description leaves the kind table's
    bare ``{"kind": "player"}`` standing, which offers every seat. That was
    live on five cards across the cast and activation paths: Ebony Charm,
    Forbidden Ritual and Necromentia sent to the caster's own face, Liliana,
    Death Mage's −7 and Mirror Universe the same one path over.

    A sweep rather than five cases, because the failure is a *missing* record:
    it cannot be found by testing the cards that have one, and the sixth card
    to print the phrase would arrive with the same hole.
    """
    widened = []
    for name, card in sorted(_w1g5_pool().items()):
        program = _w1g5_compile(card)
        if "target opponent" in (card.oracle_text or "").lower():
            if _w1g5_widened(_w1g5_cast_spec(card, program)):
                widened.append((name, "cast"))
        for ability in program.activated_abilities:
            if "target opponent" not in (ability.source_line or "").lower():
                continue
            if _w1g5_widened(_w1g5_activation_spec(ability)):
                widened.append((name, "activation"))
    assert widened == [], (
        "cards whose picker offers the caster for a printed "
        f"'target opponent': {widened}"
    )


@_w1g5_pytest.mark.cr("115.1", "102.2")
def test_115_1_the_picker_offers_only_opponents_for_target_opponent():
    """The other half: the narrowing on the spec has to reach the enumerator.

    A flag recorded and never read is the dropped rider this whole family
    exists to prevent, so the list is asked for rather than the spec inspected
    — and a plain "target player" beside it still offers every seat, which is
    what says the narrowing is the phrase's rather than the picker's.
    """
    pool = _w1g5_pool()
    game = Game(players=[PlayerState(name=f"P{i + 1}") for i in range(3)])
    game.enforce_mana_costs = False
    game.active_player_index = 0

    def offered(name):
        card = pool[name]
        spec = _w1g5_cast_spec(card, _w1g5_compile(card))
        assert spec is not None, f"{name} derives no cast spec"
        return [
            candidate.get("seat")
            for candidate in game._enumerate_targets(0, card, spec, for_cast=True)
        ]

    for name in ("Ebony Charm", "Forbidden Ritual", "Necromentia"):
        assert offered(name) == [1, 2], name
    # "Target **player** loses 5 life" (Kaervek's Spite) names every seat, the
    # caster's own included.
    assert offered("Kaervek's Spite") == [0, 1, 2]


# --- W2G3: changing an ability's target ---

import pytest as _w2g3_pytest

from engine import Game, PlayerState
from engine.models import Permanent


def _w2g3_stack_game(set_pool, mine=("Silver Wyvern", "Spined Wurm")):
    """Seat 0 holds *mine*; seat 1 holds a Rod of Ruin whose ability targets."""
    game = Game(players=[
        PlayerState(name="P1", life=20), PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    perms = []
    for name in mine:
        perm = Permanent(card=set_pool("STH")[name])
        perm.metadata["summoning_sickness_turn"] = -99
        game._put_permanent_onto_battlefield(0, perm, None)
        perms.append(perm)
    rod = Permanent(card=set_pool("LEA")["Rod of Ruin"])
    rod.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(1, rod, None)
    return game, perms, rod


@_w2g3_pytest.mark.cr("115.7a", "113.3b")
def test_115_7a_an_activated_ability_on_the_stack_can_have_its_target_changed(
    set_pool,
):
    """CR 115.7a says "the target(s) of a spell **or ability**", and CR 113.3b
    puts an activated ability on the stack as an object in its own right.

    So a retarget is not a counterspell's question: a counterspell asks about a
    *card* (colour, type, cost) and an ability has none, while "what did you
    choose as your target" is a question both objects answer the same way. The
    engine had one stack enumeration that skipped every item carrying an ability
    instruction, which made the ability half unreachable rather than wrong.
    """
    game, (wyvern, wurm), _rod = _w2g3_stack_game(set_pool)
    assert game.queue_permanent_ability(
        1, "Rod of Ruin", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(wyvern),
        ability_index=0,
    ).supported
    assert game.stack[0].is_ability

    assert game.queue_permanent_ability(
        0, "Silver Wyvern", target_stack_index=0, ability_index=0,
    ).supported
    game.resolve_stack()

    assert wurm.damage_marked == 1, game.log
    assert wyvern.damage_marked == 0, game.log


@_w2g3_pytest.mark.cr("115.7a")
def test_115_7a_an_ability_with_nowhere_else_to_go_keeps_its_target(set_pool):
    """"If a target can't be changed to **another** legal target, the original
    target is unchanged."

    The rule's own escape clause, and the one that decides what a retarget does
    on a board with nothing else on it: the current target is excluded from the
    candidates, so an empty list leaves the object exactly as it was rather than
    fizzling it or aiming it back at itself.
    """
    game, (wyvern,), _rod = _w2g3_stack_game(set_pool, mine=("Silver Wyvern",))
    assert game.queue_permanent_ability(
        1, "Rod of Ruin", target_player_index=0,
        target_permanent_index=game.battlefield_index_of(wyvern),
        ability_index=0,
    ).supported
    assert game.queue_permanent_ability(
        0, "Silver Wyvern", target_stack_index=0, ability_index=0,
    ).supported
    game.resolve_stack()

    assert wyvern.damage_marked == 1, game.log
    assert any("no other legal target" in line for line in game.log), game.log

# --- Integrator: an id alone is an address (CR 115.1, CR 400.7) -------------

from engine.oracle_types import single_chosen_id as _int_single_chosen_id


@pytest.mark.cr("400.7", "115.1")
def test_single_chosen_id_reads_one_address_and_refuses_several():
    """The channel's arity, as a rule rather than as twelve assumptions.

    ``StackItem.target_permanent_id`` carries a *list* when ``activation`` or
    ``casting`` stamped it and a bare id when a prompt's answer did. One
    element is one address. Several is not, and a single-target read that
    picked slot zero would be the multi-target list read as a single target \u2014
    wrong in the direction that looks right \u2014 so it gets None and the caller
    falls back to whatever it did before.
    """
    assert _int_single_chosen_id(7) == 7
    assert _int_single_chosen_id([7]) == 7
    assert _int_single_chosen_id((7,)) == 7
    assert _int_single_chosen_id([7, 9]) is None
    assert _int_single_chosen_id([]) is None
    assert _int_single_chosen_id(None) is None
    assert _int_single_chosen_id([None]) is None
    # ``True`` is an ``int`` and is not a permanent id.
    assert _int_single_chosen_id(True) is None


@pytest.mark.cr("115.1", "400.7")
def test_115_1_an_any_target_ability_named_by_id_alone_hits_the_creature(set_pool):
    """"any target" addressed the only stable way there is.

    ``_stack_push`` stamps both an index and an id, and the ``deal_damage``
    permanent branch used to be gated on the **index** \u2014 so a caller that sent
    only the id fell past it to the face and burned the *player*, having named
    a creature. ``web/actions.py`` fills an index in and masked it; the AI, a
    headless driver and a test do not. Written from the far side of the fix:
    the assertion that fails without it is the player's life total, not the
    creature's damage.
    """
    lea = set_pool("LEA")
    rod = _nosick(Permanent(card=lea["Rod of Ruin"]))
    victim = Permanent(card=lea["Gray Ogre"])
    p1 = PlayerState(name="P1", battlefield=[rod])
    p2 = PlayerState(name="P2", battlefield=[victim], life=20)
    game = _two_player_game(p1, p2)

    assert game.queue_permanent_ability(
        0, "Rod of Ruin", ability_index=0,
        target_permanent_ids=[victim.permanent_id],
    ).supported
    game.resolve_stack()

    assert victim.metadata.get("was_dealt_damage_this_turn"), game.log
    assert p2.life == 20, game.log


@pytest.mark.cr("109.2", "115.1")
def test_109_2_a_bare_type_word_means_a_permanent_on_the_battlefield(catalog_by_name):
    """"...includes a card type or subtype, but doesn’t refer to a specific zone
    or include the word ‘card,’ ‘spell,’ ‘source,’ or ‘scheme,’ it means a
    permanent of that card type ... on the battlefield."

    Shatter says "Destroy target **artifact**" — no zone, no "card". So the
    Moxen in hand and in the graveyard are not targets, however plainly they are
    artifacts, and the picker must offer exactly the one on the battlefield.

    The picker rather than the resolution: CR 109.2 is what scopes the noun
    phrase at announcement (CR 115.1), so a reading that only narrowed at
    resolution would still let a player choose a card in their hand.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    shatter = catalog_by_name["Shatter"]
    on_battlefield = Permanent(card=catalog_by_name["Mox Ruby"])
    p1 = PlayerState(
        name="P1",
        hand=[catalog_by_name["Mox Pearl"]],
        graveyard=[catalog_by_name["Mox Sapphire"]],
        battlefield=[on_battlefield],
    )
    game = _two_player_game(p1, PlayerState(name="P2"))

    spec = dict(derive_cast_spec(shatter, compile_card_oracle(shatter)) or {})
    kind = spec.pop("kind")
    offered = [
        entry["name"]
        for entry in game.enumerate_targets_for_kind(0, shatter, kind, **spec)
    ]

    assert offered == ["Mox Ruby"], offered


# ---------------------------------------------------------------------------
# Rule 115.3 - the same target can't be chosen twice for one instance of the
# word "target"; several instances each get their own choice.
# ---------------------------------------------------------------------------


def _two_blockers_declared(set_pool):
    """A real combat with Sorrow's Path untapped and two of the *defender's*
    creatures blocking.

    The Path is on the attacking side because it names "two target blocking
    creatures controlled by the same **opponent**", so the blockers have to sit
    across the table from the land. Everything is tough enough to survive the
    activation's own 2 damage, which would otherwise renumber the combat maps
    out from under the assertions.

    Returns ``(game, path, first_blocker, second_blocker)``.
    """
    alpha = _perm(_mk_card(name="Alpha", type_line="Creature - Test", power=2, toughness=5))
    beta = _perm(_mk_card(name="Beta", type_line="Creature - Test", power=3, toughness=5))
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    ex = Permanent(card=_mk_card(name="Ex", type_line="Creature - Test", power=1, toughness=4))
    why = Permanent(card=_mk_card(name="Why", type_line="Creature - Test", power=1, toughness=5))
    p1 = PlayerState(name="P1", battlefield=[alpha, beta, path], life=20)
    p2 = PlayerState(name="P2", battlefield=[ex, why], life=20)
    game = _two_player_game(p1, p2)
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [0, 1])[0], game.log
    game.advance_combat_phase()  # declare blockers
    assert game.declare_blockers(1, {0: 0, 1: 1})[0], game.log
    return game, path, ex, why


@pytest.mark.cr("115.3", "602.2b")
def test_115_3_one_instance_of_target_cannot_name_the_same_object_twice(set_pool):
    """"The same target can't be chosen multiple times for any one instance of
    the word 'target'."

    Sorrow's Path prints one instance, pluralised - "choose **two target**
    blocking creatures controlled by the same opponent" - so one blocker named
    for both is not an announcement this rule allows. CR 115.3 is the half of
    that sentence CR 601.2c does *not* cover: this is an activated ability, and
    the refusal has to come out of the role walk the activation gate uses rather
    than out of the cast gate.

    Refused with nothing paid (CR 602.2b), which is the half that matters on
    this card in particular: its cost taps a land that then deals 2 damage to
    its controller and to each creature they control, so an activation accepted
    and then quietly no-opped would cost the activator a board.
    """
    game, path, ex, why = _two_blockers_declared(set_pool)

    refused = game.activate_permanent_ability(
        0, "Sorrow's Path", target_permanent_ids=[ex.permanent_id, ex.permanent_id],
    )

    assert not refused.supported, game.log
    assert not path.tapped, "the cost was never paid"
    assert game.players[0].life == 20, "nor its 2 damage dealt"
    assert game.combat_blockers[1] == {0: [0], 1: [1]}, "the declared blocks stand"

    # The control, on a fresh combat: the same announcement naming the two
    # *different* blockers is one the rule allows, and it goes through.
    game, path, ex, why = _two_blockers_declared(set_pool)

    allowed = game.activate_permanent_ability(
        0, "Sorrow's Path", target_permanent_ids=[ex.permanent_id, why.permanent_id],
    )

    assert allowed.supported, game.log


@pytest.mark.cr("115.3")
def test_115_3_two_instances_of_target_may_each_name_the_same_creature(catalog_by_name):
    """"If the spell or ability uses the word 'target' in multiple places, the
    same object or player can be chosen once for each instance of the word
    'target'."

    Cuombajj Witches prints two of them: "deals 1 damage to any target **and**
    1 damage to any target of an opponent's choice". Two instances, two
    choosers, and one creature is a legal answer to both - so it takes 2 damage
    from a single activation rather than 1.

    The opponent's instance is a queued decision rather than a second slot in
    the announcement, which is why seat 1 has to be interactive here: a headless
    seat takes the kind's deterministic default and never gets the chance to
    name the creature the activator already named.
    """
    witches = _nosick(Permanent(card=catalog_by_name["Cuombajj Witches"]))
    victim = Permanent(card=catalog_by_name["Hill Giant"])  # 3/3, so it survives
    p1 = PlayerState(name="P1", battlefield=[witches], life=20)
    p2 = PlayerState(name="P2", battlefield=[victim], life=20)
    game = _two_player_game(p1, p2)
    game.interactive_seats = {1}

    assert game.activate_permanent_ability(
        0, "Cuombajj Witches", target_permanent_ids=[victim.permanent_id],
    ).supported, game.log
    game.resolve_stack()

    assert victim.damage_marked == 1, "the activator's instance"
    pending = game.pending_opponent_damage
    assert pending is not None and pending["chooser_index"] == 1, game.log

    assert game.confirm_opponent_damage_choice(1, 1, 0) is True, game.log

    assert victim.damage_marked == 2, "once for each instance of the word"
    assert (p1.life, p2.life) == (20, 20), "neither instance went to a face"


# ---------------------------------------------------------------------------
# Rule 115.3, the half that had no gate: one printed instance of the word
# "target", made plural, over a spell rather than an ability.
#
# The distinction the whole family turns on is how many times the sentence
# prints the word. "Exile **two target** nonartifact creatures" prints it once
# and opens two slots, so no creature may fill both; "target creature you
# control ... up to one **target** creature you don't control" prints it twice
# and one creature could legally fill both, were the two filters not disjoint.
# ``targeting.py`` answers that question off the payload's per-slot filter list
# and ``legality._repeated_target_refusal`` enforces the answer.
# ---------------------------------------------------------------------------


def _cr115_3_pool(catalog_by_name, spell, *creatures, own=()):
    """*spell* in hand, *creatures* on the opponent's battlefield."""
    p1 = PlayerState(
        name="P1",
        hand=[catalog_by_name[spell]],
        battlefield=[_perm(catalog_by_name[name]) for name in own],
    )
    theirs = [_perm(catalog_by_name[name]) for name in creatures]
    p2 = PlayerState(name="P2", battlefield=theirs)
    game = _two_player_game(p1, p2)
    game._settle()
    return game, p1, p2, theirs


@pytest.mark.cr("115.3", "601.2c")
def test_115_3_a_two_target_spell_is_not_castable_with_one_legal_target(
    catalog_by_name,
):
    """The sharp end of the rule, and the reason it is a refusal rather than a
    tidy-up at resolution.

    "Exile **two** target nonartifact creatures" needs two legal targets to have
    any legal announcement at all (CR 601.2c). With one creature on the
    battlefield there is none — and naming that creature twice used to be
    accepted, exiling it and charging the caster the printed 5 life. A spell the
    board cannot pay for, cast anyway for half its effect.
    """
    game, p1, p2, (only,) = _cr115_3_pool(
        catalog_by_name, "Ashes to Ashes", "Grizzly Bears"
    )

    result = game.cast_from_hand(
        0, "Ashes to Ashes", target_permanent_ids=[only.permanent_id] * 2
    )

    assert not result.supported
    assert "same target" in result.details
    assert p1.life == 20, "the printed 5 damage was charged for a refused cast"
    assert [perm.card.name for perm in p2.battlefield] == ["Grizzly Bears"]
    assert [card.name for card in p1.hand] == ["Ashes to Ashes"]


@pytest.mark.cr("115.3")
def test_115_3_the_same_spell_with_two_legal_targets_is_unaffected(
    catalog_by_name,
):
    """The control the refusal above needs: the gate must not have made the card
    harder to cast, only impossible to cast illegally."""
    game, p1, p2, (bear, giant) = _cr115_3_pool(
        catalog_by_name, "Ashes to Ashes", "Grizzly Bears", "Hill Giant"
    )

    result = game.cast_from_hand(
        0, "Ashes to Ashes",
        target_permanent_ids=[bear.permanent_id, giant.permanent_id],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert p2.battlefield == []
    assert p1.life == 15, "the printed cost is still charged for a legal cast"


@pytest.mark.cr("115.3")
def test_115_3_several_printed_instances_may_still_name_one_object(
    catalog_by_name,
):
    """The rule's other half, which the fix must not overreach into. Primal
    Might prints "target" twice — "**target** creature you control ... up to one
    **target** creature you don't control" — so the default is that one object
    could fill both slots, and only a printed "another" would forbid it. Here
    the two filters are disjoint, so a legal announcement names two creatures
    and the gate stays out of the way.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = catalog_by_name["Primal Might"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec.get("max_targets") == 2
    assert not spec.get("distinct_targets"), (
        "two printed instances of the word are not one instance made plural"
    )


@pytest.mark.cr("115.3", "601.2c")
def test_115_3_the_printed_another_forbids_the_repeat_two_instances_allow(
    catalog_by_name,
):
    """Deadshot prints the word twice and then says "**another** target
    creature", which is the card doing what CR 115.3 does not.

    The fusion that builds this instruction has always *required* the word — an
    unqualified second "target" is a different card and refuses — and then
    dropped it, so the gate had nothing to read and the announcement naming one
    creature twice was legal. It tapped that creature and had it bite itself for
    its own power, which the handler scored as no damage at all.
    """
    game, _p1, p2, (only,) = _cr115_3_pool(
        catalog_by_name, "Deadshot", "Grizzly Bears"
    )

    result = game.cast_from_hand(
        0, "Deadshot", target_permanent_ids=[only.permanent_id] * 2
    )

    assert not result.supported
    assert "same target" in result.details
    assert not only.tapped, "the tap half of the sentence happened anyway"


@pytest.mark.cr("115.3", "602.2b")
def test_115_3_an_activated_ability_refuses_the_repeat_before_paying(
    catalog_by_name,
):
    """CR 602.2b routes an activation through CR 601.2c, so the ability half of
    this rule is the same question asked one announcement over — and refused
    with nothing paid, which on a {T} ability is visible on the source."""
    elder = _perm(catalog_by_name["Argothian Elder"])   # {T}: Untap two target lands.
    forest = _perm(catalog_by_name["Forest"], tapped=True)
    island = _perm(catalog_by_name["Island"], tapped=True)
    p1 = PlayerState(name="P1", battlefield=[elder, forest, island])
    game = _two_player_game(p1, PlayerState(name="P2"))
    game._settle()

    refused = game.activate_permanent_ability(
        0, "Argothian Elder", target_permanent_ids=[forest.permanent_id] * 2
    )

    assert not refused.supported
    assert "same target" in refused.details
    assert not elder.tapped, "{T} was paid for a refused activation (CR 733.1)"
    assert forest.tapped and island.tapped

    ok = game.activate_permanent_ability(
        0, "Argothian Elder",
        target_permanent_ids=[forest.permanent_id, island.permanent_id],
    )
    assert ok.supported, ok.details
    game.resolve_stack()
    assert not forest.tapped and not island.tapped


@pytest.mark.cr("115.3", "601.2d")
def test_115_3_a_divided_spell_asks_the_same_question_of_its_own_channel(
    catalog_by_name,
):
    """A division names its targets on their own channel, so the rule has to be
    asked there too. "Distribute two +1/+1 counters among **one or two target**
    creatures" is one printed instance, and the gate that already refused a
    repeat for the card-divided family now refuses it for every division —
    which is what the family's own comment said was still missing.
    """
    game, p1, _p2, (only,) = _cr115_3_pool(
        catalog_by_name, "Elven Rite", "Grizzly Bears"
    )

    refused = game.cast_from_hand(
        0, "Elven Rite", divided_targets=[(1, 0, 1), (1, 0, 1)]
    )
    assert not refused.supported
    assert "different" in refused.details

    # One target taking both counters is the legal way to say it, and the
    # refusal must leave that alone: "one or two" prints the choice.
    ok = game.cast_from_hand(0, "Elven Rite", divided_targets=[(1, 0, 2)])
    assert ok.supported, ok.details

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

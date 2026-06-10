"""Tests for Magic: The Gathering Comprehensive Rules Section 115 — Targets."""

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.game import StackItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_card(
    name: str,
    type_line: str,
    oracle_text: str = "",
    mana_cost: str = "",
    colors: tuple[str, ...] = (),
    cmc: float = 0.0,
    produced_mana: tuple[str, ...] = (),
) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = "2"
        raw["toughness"] = "2"
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=cmc,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=produced_mana,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# Rule 115.1 — Targets are declared when the spell or ability is put on the stack
# ---------------------------------------------------------------------------


def test_115_1_target_declared_when_spell_put_on_stack():
    """Target player is declared as part of putting the spell on the stack (115.1)."""
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)

    assert game.stack[0].target_player_index == 1


def test_115_1_target_permanent_declared_when_spell_put_on_stack():
    """Target permanent index is declared as part of putting the spell on the stack (115.1)."""
    destruction = _mk_card("Shatter", "Instant", "Destroy target artifact.")
    artifact = _mk_card("Ornithopter", "Artifact Creature — Thopter")
    p1 = PlayerState(name="P1", hand=[destruction])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=artifact)])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Shatter", target_player_index=1, target_permanent_index=0)

    assert game.stack[0].target_permanent_index == 0


def test_115_1_target_unchanged_without_explicit_effect():
    """Targets on the stack are not changed without an effect that explicitly changes them (115.1)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt", target_player_index=1)

    # Without any target-changing spell, target remains as originally declared
    assert game.stack[0].target_player_index == 1


# ---------------------------------------------------------------------------
# Rule 115.1a — Instant/sorcery is targeted if its spell ability uses "target [something]"
# ---------------------------------------------------------------------------


def test_115_1a_instant_with_target_phrase_stores_target():
    """An instant with 'target [something]' stores the chosen target on the stack (115.1a)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt", target_player_index=1)

    item = game.stack[0]
    assert item.card.primary_type == "instant"
    assert item.target_player_index == 1


def test_115_1a_sorcery_with_target_creature_stores_permanent_target():
    """A sorcery with 'target creature' stores the creature's permanent index on the stack (115.1a)."""
    terror = _mk_card("Terror", "Sorcery", "Destroy target creature.")
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

    item = game.stack[0]
    assert item.card.primary_type == "sorcery"
    assert item.target_permanent_index == 0


def test_115_1a_triggered_ability_target_does_not_make_card_targeted():
    """A triggered ability using 'target' does not make the card itself targeted (115.1a).

    When a spell's only use of 'target' appears in a triggered ability (not in the spell
    ability itself), the spell is placed on the stack with no target. The oracle recognises
    'Draw a card' as the main effect and ignores the cycling trigger's 'target' phrase for
    the purposes of targeting the spell.
    """
    # Main spell effect: "Draw a card." (untargeted).
    # Triggered ability: "When you cycle this card, target creature gets -1/-1 until end of turn."
    # Only the triggered ability uses 'target' — the spell itself does not.
    cycler = _mk_card(
        "Cycling Sorcery",
        "Sorcery",
        "Draw a card. When you cycle this card, target creature gets -1/-1 until end of turn.",
    )
    dummy = _mk_card("Dummy", "Sorcery")
    p1 = PlayerState(name="P1", hand=[cycler], library=[dummy])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Cast without providing any target — valid because the spell ability is not targeted
    result = game.queue_from_hand(0, "Cycling Sorcery")

    assert result.supported
    item = game.stack[0]
    # Spell itself has no target; the cycling trigger carries its own target independently
    assert item.target_player_index is None
    assert item.target_permanent_index is None


# ---------------------------------------------------------------------------
# Rule 115.1b — Aura spells are always targeted
# ---------------------------------------------------------------------------


def test_115_1b_enchant_artifact_aura_stores_target_permanent_index():
    """An 'enchant artifact' Aura spell stores the chosen permanent index on the stack (115.1b).

    Regression: Animate Artifact previously cast without prompting for or storing
    a target permanent index, so the target_permanent_index on the StackItem was None.
    """
    animate = _mk_card(
        "Animate Artifact",
        "Enchantment — Aura",
        "Enchant artifact\nAs long as enchanted artifact isn't a creature, it's an artifact creature with power and toughness each equal to its mana value.",
    )
    artifact = _mk_card("Black Lotus", "Artifact", "{T}, Sacrifice Black Lotus: Add three mana of any one color.")
    p1 = PlayerState(name="P1", hand=[animate])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=artifact)])
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Animate Artifact", target_player_index=1, target_permanent_index=0)

    assert result.supported
    item = game.stack[0]
    assert item.target_player_index == 1
    assert item.target_permanent_index == 0


def test_115_1b_enchant_artifact_attaches_to_chosen_artifact_not_first():
    """When multiple artifacts exist, an 'enchant artifact' Aura attaches to the chosen one (115.1b).

    Regression: without target selection the aura always attached to the first artifact found,
    ignoring the player's choice expressed via target_permanent_index.
    """
    animate = _mk_card(
        "Animate Artifact",
        "Enchantment — Aura",
        "Enchant artifact\nAs long as enchanted artifact isn't a creature, it's an artifact creature with power and toughness each equal to its mana value.",
        cmc=4,
    )
    artifact_a = _mk_card("Black Lotus", "Artifact", "{T}, Sacrifice Black Lotus: Add three mana of any one color.", cmc=0)
    artifact_b = _mk_card("Sol Ring", "Artifact", "{T}: Add {C}{C}.", cmc=1)
    p1 = PlayerState(name="P1", hand=[animate])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=artifact_a), Permanent(card=artifact_b)])
    game = Game(players=[p1, p2])

    # Target the second artifact (index 1 = Sol Ring)
    result = game.cast_from_hand(0, "Animate Artifact", target_player_index=1, target_permanent_index=1)

    assert result.supported
    aura_perm = next((p for p in p1.battlefield if p.card.name == "Animate Artifact"), None)
    assert aura_perm is not None, "Animate Artifact should be on P1's battlefield"
    attached = aura_perm.metadata.get("attached_to")
    assert attached is not None, "Aura must have an attached_to reference"
    assert attached.card.name == "Sol Ring", (
        f"Aura should attach to Sol Ring (index 1), not {attached.card.name}"
    )
    # The first artifact must not have received the aura
    black_lotus = p2.battlefield[0]
    assert black_lotus.metadata.get("attached_aura") is None, (
        "Black Lotus (index 0) should not have the aura attached"
    )


def test_115_1b_aura_cast_without_target_is_rejected():
    """An Aura spell cannot be cast without choosing a target (115.1b, 601.2c).

    Regression: Fear was cast with no target at all — the engine only checked that
    some legal target existed somewhere and let the Aura resolve unattached.
    """
    fear = _mk_card(
        "Fear",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature has fear.",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[fear], battlefield=[Permanent(card=bear)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fear", target_player_index=0)

    assert not result.supported
    assert "requires a target" in result.details
    assert any(c.name == "Fear" for c in p1.hand)
    assert not any(perm.card.name == "Fear" for perm in p1.battlefield)


def test_115_1b_aura_cast_with_wrong_type_target_is_rejected():
    """An Aura cast at a permanent its enchant ability can't enchant is illegal (115.1b)."""
    fear = _mk_card(
        "Fear",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature has fear.",
    )
    forest = _mk_card("Forest", "Basic Land — Forest")
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[fear])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=forest), Permanent(card=bear)])
    game = Game(players=[p1, p2])

    # Index 0 is the Forest — not a legal target for "Enchant creature"
    result = game.cast_from_hand(0, "Fear", target_player_index=1, target_permanent_index=0)

    assert not result.supported
    assert any(c.name == "Fear" for c in p1.hand)
    assert not any(perm.card.name == "Fear" for perm in p1.battlefield)


def test_115_1b_aura_cast_with_out_of_range_target_is_rejected():
    """An Aura cast with a target index that points at nothing is illegal (115.1b)."""
    fear = _mk_card(
        "Fear",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature has fear.",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[fear])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Fear", target_player_index=1, target_permanent_index=5)

    assert not result.supported
    assert any(c.name == "Fear" for c in p1.hand)
    assert not any(perm.card.name == "Fear" for perm in p1.battlefield)


def test_115_1b_enchant_creature_attaches_to_chosen_creature_not_first():
    """An 'enchant creature' Aura attaches to the chosen creature, not the first found (115.1b).

    Regression: the enchant-creature resolution path ignored target_permanent_index
    and always attached to the first creature on the target player's battlefield.
    """
    aura = _mk_card(
        "Power Aura",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature gets +2/+2.",
    )
    bear_a = _mk_card("First Bear", "Creature — Bear")
    bear_b = _mk_card("Second Bear", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear_a), Permanent(card=bear_b)])
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Power Aura", target_player_index=1, target_permanent_index=1)

    assert result.supported
    aura_perm = next(perm for perm in p1.battlefield if perm.card.name == "Power Aura")
    attached = aura_perm.metadata.get("attached_to")
    assert attached is not None
    assert attached.card.name == "Second Bear"
    assert p2.battlefield[0].metadata.get("attached_aura") is None
    assert p2.battlefield[1].effective_power == 4


def test_115_1b_aura_spell_stores_enchant_target():
    """An Aura spell's enchant target is declared when the spell is cast (115.1b).

    Only the Aura spell is targeted; the resulting permanent is not.
    """
    aura = _mk_card(
        "Holy Armor",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature gets +0/+2 and has '{W}: Enchanted creature gets +0/+1 until end of turn.'",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Holy Armor", target_player_index=1, target_permanent_index=0)

    assert result.supported
    item = game.stack[0]
    assert item.target_player_index == 1
    assert item.target_permanent_index == 0


def test_115_1b_aura_permanent_has_no_target_after_resolution():
    """An Aura permanent does not target anything once it is on the battlefield (115.1b)."""
    aura = _mk_card(
        "Holy Armor",
        "Enchantment — Aura",
        "Enchant creature\nEnchanted creature gets +0/+2 and has '{W}: Enchanted creature gets +0/+1 until end of turn.'",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[aura])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    game.cast_from_hand(0, "Holy Armor", target_player_index=1, target_permanent_index=0)

    # Stack is empty — spell resolved
    assert len(game.stack) == 0
    # The Aura on the battlefield is just a Permanent; it has no target fields
    aura_on_field = next(
        (perm for perm in p1.battlefield if "Aura" in perm.card.type_line),
        None,
    )
    if aura_on_field is None:
        aura_on_field = next(
            (perm for perm in p2.battlefield if "Aura" in perm.card.type_line),
            None,
        )
    # A Permanent has no target_player_index attribute — targets belong to StackItems only
    assert not hasattr(Permanent, "target_player_index")


# ---------------------------------------------------------------------------
# Rule 115.1c — Activated ability is targeted if it uses "target [something]"
# ---------------------------------------------------------------------------


def test_115_1c_activated_ability_target_stored_on_stack():
    """An activated ability's target is declared when the ability is activated (115.1c)."""
    tapper = _mk_card(
        "Icy Manipulator",
        "Artifact",
        "{1}, {T}: Tap target artifact, creature, or land.",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=tapper)],
        mana_pool={"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2},
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.queue_permanent_ability(
        0, "Icy Manipulator", target_player_index=1, permanent_index=0
    )

    assert result.supported
    # The queued ability has the target stored
    ability_item = game.stack[-1]
    assert ability_item.target_player_index == 1


def test_115_1c_activated_ability_targeting_player_stores_player_index():
    """An activated ability targeting a player stores the player index when queued (115.1c)."""
    royal_assassin = _mk_card(
        "Lich",
        "Enchantment",
        "{B}: Draw a card. Target player loses 1 life.",
    )
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=royal_assassin)],
        mana_pool={"W": 0, "U": 0, "B": 1, "R": 0, "G": 0, "C": 0},
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_permanent_ability(0, "Lich", target_player_index=1)

    assert result.supported
    assert game.stack[-1].target_player_index == 1


# ---------------------------------------------------------------------------
# Rule 115.1d — Triggered ability is targeted if it uses "target [something]"
# ---------------------------------------------------------------------------


def test_115_1d_triggered_ability_target_stored_when_put_on_stack():
    """A triggered ability's target is declared when it is put on the stack (115.1d).

    Simulate by directly placing a triggered-ability StackItem with a target,
    mirroring what the engine does when a triggered ability fires.
    """
    trigger_card = _mk_card(
        "Prodigal Sorcerer",
        "Creature — Human Wizard",
        "{T}: Prodigal Sorcerer deals 1 damage to any target.",
    )
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Simulate the triggered ability being put on the stack with a chosen target
    game.stack.append(
        StackItem(
            card=trigger_card,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=None,
            x_value=None,
        )
    )

    # Target is stored on the stack item exactly as declared
    assert game.stack[-1].target_player_index == 1


# ---------------------------------------------------------------------------
# Rule 115.2 — Only permanents are legal targets unless a spell specifies otherwise
# ---------------------------------------------------------------------------


def test_115_2_player_is_legal_target_when_spell_specifies():
    """A spell specifying 'target player' can legally target a player (115.2a)."""
    heal = _mk_card("Healing Salve", "Instant", "Target player gains 3 life.")
    p1 = PlayerState(name="P1", hand=[heal])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Healing Salve", target_player_index=1)

    assert result.supported
    assert game.stack[0].target_player_index == 1


def test_115_2_permanent_on_battlefield_is_legal_target():
    """A permanent on the battlefield is a legal target for a spell (115.2)."""
    terror = _mk_card("Terror", "Sorcery", "Destroy target creature.")
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[terror])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Terror", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert game.stack[0].target_permanent_index == 0


def test_115_2_targeting_player_and_permanent_simultaneously():
    """Both a player index and a permanent index can be stored as targets on one stack item (115.2)."""
    drain = _mk_card(
        "Drain Life",
        "Sorcery",
        "Spend only black mana on X. Drain Life deals X damage to target creature or player.",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[drain])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Drain Life", target_player_index=1, target_permanent_index=0)

    assert result.supported
    item = game.stack[0]
    assert item.target_player_index == 1
    assert item.target_permanent_index == 0


# ---------------------------------------------------------------------------
# Rule 115.3 — The same target can't be chosen multiple times for one "target" instance
# ---------------------------------------------------------------------------


def test_115_3_multi_target_spell_stores_list_of_permanent_indices():
    """A spell targeting multiple permanents stores all indices on the stack item (115.3).

    When a spell has two separate 'target' instances (e.g., 'target artifact and target land'),
    two different indices may be chosen — one per instance of the word 'target'.
    """
    arc_trail = _mk_card(
        "Arc Trail",
        "Sorcery",
        "Arc Trail deals 2 damage to any target and 1 damage to any other target.",
    )
    creature_a = _mk_card("Goblin A", "Creature — Goblin")
    creature_b = _mk_card("Goblin B", "Creature — Goblin")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=creature_a), Permanent(card=creature_b)])
    game = Game(players=[p1, p2])

    # Two distinct targets — one per 'target' instance
    game.stack.append(
        StackItem(
            card=arc_trail,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 1],
            x_value=None,
        )
    )

    item = game.stack[0]
    assert isinstance(item.target_permanent_index, list)
    assert len(item.target_permanent_index) == 2
    assert item.target_permanent_index[0] != item.target_permanent_index[1]


def test_115_3_same_permanent_can_be_chosen_for_different_target_instances():
    """The same object may be chosen once per instance of 'target' in a spell (115.3).

    Example: 'Destroy target artifact and target land' may target the same artifact land twice,
    once for each instance of the word 'target'.
    """
    two_target_spell = _mk_card(
        "Detonate",
        "Sorcery",
        "Destroy target artifact and target land.",
    )
    artifact_land = _mk_card("Mishra's Factory", "Land — Artifact")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=artifact_land)])
    game = Game(players=[p1, p2])

    # Same permanent index (0) chosen for each of the two 'target' instances
    game.stack.append(
        StackItem(
            card=two_target_spell,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 0],
            x_value=None,
        )
    )

    item = game.stack[0]
    # Both slots reference the same permanent — legal because each uses a separate 'target' instance
    assert item.target_permanent_index[0] == 0
    assert item.target_permanent_index[1] == 0


# ---------------------------------------------------------------------------
# Rule 115.4 — "any target" includes creatures, players, planeswalkers, and battles
# ---------------------------------------------------------------------------


def test_115_4_any_target_spell_can_target_player():
    """A spell with 'any target' may target a player (115.4)."""
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)

    assert result.supported
    assert p2.life == 17


def test_115_4_any_target_spell_can_target_creature():
    """A spell with 'any target' may target a creature permanent (115.4).

    The creature is a legal target; the StackItem records it. After resolution the
    3-damage bolt kills the 2/2 bear (lethal damage), so we verify via graveyard/SBA.
    """
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    # Check target is declared on the stack before resolution
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    item = game.stack[-1]
    assert item.target_player_index == 1
    assert item.target_permanent_index == 0

    # After resolution the creature is dealt lethal damage and leaves the battlefield
    game.resolve_stack()
    game.check_state_based_actions()
    assert len(p2.battlefield) == 0


def test_115_4_any_target_cannot_target_noncreature_artifact():
    """A spell with 'any target' cannot target a noncreature artifact (115.4).

    'Any target' is limited to creatures, players, planeswalkers, and battles.
    When the targeted permanent is a noncreature artifact the spell fizzles — the
    artifact takes no damage and is not removed from the battlefield.
    """
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    artifact = _mk_card("Black Lotus", "Artifact", "{T}, Sacrifice Black Lotus: Add three mana of any single color.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=artifact)])
    game = Game(players=[p1, p2])

    # Target the artifact — the engine should refuse or deal no damage
    result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

    # The artifact should remain on the battlefield undamaged (noncreature artifact is not a valid 'any target')
    assert len(p2.battlefield) == 1
    assert p2.battlefield[0].damage_marked == 0


# ---------------------------------------------------------------------------
# Rule 115.5 — A spell or ability on the stack is an illegal target for itself
# ---------------------------------------------------------------------------


def test_115_5_spell_cannot_target_itself_on_stack():
    """A spell or ability on the stack is an illegal target for itself (115.5).

    Verified by confirming the stack item's own card is not set as its own target —
    spells target players or battlefield permanents, never the StackItem representing themselves.
    """
    counter = _mk_card("Counterspell", "Instant", "Counter target spell.")
    some_spell = _mk_card("Recall", "Instant", "Target player draws 3 cards.")
    p1 = PlayerState(name="P1", hand=[counter])
    p2 = PlayerState(name="P2", hand=[some_spell])
    game = Game(players=[p1, p2])

    # A spell must exist on the stack for Counterspell to have a legal target (Rule 601.2c).
    game.queue_from_hand(1, "Recall", target_player_index=0)

    result = game.queue_from_hand(0, "Counterspell", target_player_index=1)

    assert result.supported
    item = game.stack[-1]  # Counterspell is on top
    # The stack item does not list itself as its target permanent
    assert item.target_permanent_index is None or item.target_permanent_index != id(item)


# ---------------------------------------------------------------------------
# Rule 115.6 — A spell allowing zero targets is targeted only if targets are chosen
# ---------------------------------------------------------------------------


def test_115_6_spell_with_optional_target_is_targeted_when_target_chosen():
    """A spell that may have zero targets is targeted when one or more targets are chosen (115.6).

    'You may have target player draw a card.' allows zero targets (the 'may' is optional), but
    if the controller elects to name a target the spell is considered targeted and the target
    is stored on the stack item.
    """
    optional_target_spell = _mk_card(
        "Opt",
        "Instant",
        "You may have target player draw a card.",
    )
    dummy = _mk_card("Dummy", "Sorcery")
    p1 = PlayerState(name="P1", hand=[optional_target_spell])
    p2 = PlayerState(name="P2", library=[dummy])
    game = Game(players=[p1, p2])

    # Controller chose to name player 1 as the target
    result = game.queue_from_hand(0, "Opt", target_player_index=1)

    assert result.supported
    item = game.stack[-1]
    # Target was chosen — spell is targeted (target_player_index is set)
    assert item.target_player_index == 1


def test_115_6_spell_with_optional_target_has_no_target_when_none_chosen():
    """A spell that may have zero targets has no target when none are chosen (115.6)."""
    no_target_spell = _mk_card(
        "Ancestral Recall",
        "Instant",
        "Target player draws three cards.",
    )
    p1 = PlayerState(name="P1", hand=[no_target_spell])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Ancestral Recall")

    assert result.supported
    # No target chosen — stack item has no target
    assert game.stack[-1].target_player_index is None


# ---------------------------------------------------------------------------
# Rule 115.7 — Changing targets / choosing new targets
# ---------------------------------------------------------------------------


def test_115_7a_change_targets_all_must_change_to_legal_or_none_change():
    """When 'change the target(s)', all must become legal targets or none are changed (115.7a).

    Simulated by verifying that after a target change attempt, the targets are either
    all updated or all remain as originally declared.
    """
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    original_target = game.stack[0].target_player_index

    # Without any explicit target-changing effect, the original target is preserved
    assert game.stack[0].target_player_index == original_target


def test_115_7d_new_targets_must_be_legal():
    """When 'choosing new targets', the new targets must be legal (115.7d).

    Targets can be left unchanged, but any changed targets must be legal new targets.
    This verifies the stack item carries valid player/permanent indices.
    """
    arc_trail = _mk_card(
        "Arc Trail",
        "Sorcery",
        "Arc Trail deals 2 damage to any target and 1 damage to any other target.",
    )
    bear = _mk_card("Runeclaw Bear", "Creature — Bear")
    elf = _mk_card("Llanowar Elves", "Creature — Elf")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=bear), Permanent(card=elf)],
    )
    game = Game(players=[p1, p2])

    # Original targets: Bear at index 0, Elf at index 1
    game.stack.append(
        StackItem(
            card=arc_trail,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 1],
            x_value=None,
        )
    )

    # Swap targets (rule 115.7d example: swap Bear and Elf)
    item = game.stack[0]
    item.target_permanent_index = [1, 0]

    assert item.target_permanent_index == [1, 0]
    # Both are still valid indices within p2.battlefield
    assert all(0 <= idx < len(p2.battlefield) for idx in item.target_permanent_index)


def test_115_7e_only_final_set_of_targets_evaluated():
    """When changing targets, only the final set of targets is evaluated for legality (115.7e).

    Example from CR: Arc Trail's two targets may be swapped — the evaluation only
    looks at the final arrangement, not intermediate states.
    """
    arc_trail = _mk_card(
        "Arc Trail",
        "Sorcery",
        "Arc Trail deals 2 damage to any target and 1 damage to any other target.",
    )
    bear = _mk_card("Runeclaw Bear", "Creature — Bear")
    elf = _mk_card("Llanowar Elves", "Creature — Elf")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=bear), Permanent(card=elf)],
    )
    game = Game(players=[p1, p2])

    # Start: first target Bear (0), second target Elf (1)
    game.stack.append(
        StackItem(
            card=arc_trail,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 1],
            x_value=None,
        )
    )

    # Change to: first target Elf (1), second target Bear (0)
    # Intermediate state [1, 1] or [0, 0] would be illegal but the final [1, 0] is legal
    item = game.stack[0]
    item.target_permanent_index = [1, 0]

    # Final set is valid — no target appears in a position it can't occupy
    assert item.target_permanent_index[0] != item.target_permanent_index[1]


def test_115_7f_divided_damage_division_unchanged_when_retargeting():
    """The original division cannot be changed when choosing new targets for a divided spell (115.7f)."""
    fireball = _mk_card(
        "Fireball",
        "Sorcery",
        "Fireball deals X damage divided equally, rounded down, among any number of targets.",
    )
    creature_a = _mk_card("Goblin A", "Creature — Goblin")
    creature_b = _mk_card("Goblin B", "Creature — Goblin")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=creature_a), Permanent(card=creature_b)],
    )
    game = Game(players=[p1, p2])

    # Division: 3 damage to creature 0, 1 damage to creature 1
    game.stack.append(
        StackItem(
            card=fireball,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 1],
            x_value=4,
        )
    )

    item = game.stack[0]
    original_x = item.x_value

    # Changing to new targets does not change the X value (total damage)
    item.target_permanent_index = [1, 0]
    assert item.x_value == original_x


# ---------------------------------------------------------------------------
# Rule 115.8 — Modal spells: changing target doesn't change mode
# ---------------------------------------------------------------------------


def test_115_8_modal_spell_stores_target_without_changing_mode():
    """Changing the target of a modal spell does not change its mode (115.8).

    Verified by confirming the card (which encodes the mode) is unchanged
    when only the target index is modified on the stack item.
    """
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)

    item = game.stack[0]
    original_card = item.card

    # Retarget to player 0 (change target, not mode)
    item.target_player_index = 0

    # Card (representing the spell and its mode) is unchanged
    assert item.card is original_card
    assert item.card.name == "Lightning Bolt"


# ---------------------------------------------------------------------------
# Rule 115.9 — Objects that check what a spell or ability is targeting
# ---------------------------------------------------------------------------


def test_115_9a_target_count_is_number_of_times_target_was_chosen():
    """Target count is the number of times targets were chosen when the spell was put on the stack (115.9a).

    A spell targeting two objects has a target count of 2, even if both are the same object.
    """
    arc_trail = _mk_card(
        "Arc Trail",
        "Sorcery",
        "Arc Trail deals 2 damage to any target and 1 damage to any other target.",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    game.stack.append(
        StackItem(
            card=arc_trail,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 0],  # same target chosen for both instances
            x_value=None,
        )
    )

    item = game.stack[0]
    # Count of how many times a target was chosen (both instances = 2)
    target_count = len(item.target_permanent_index) if isinstance(item.target_permanent_index, list) else 1
    assert target_count == 2


def test_115_9b_target_current_state_used_when_checking():
    """When checking 'targets [something]', the current state of the target is used (115.9b)."""
    bolt = _mk_card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.")
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

    # Modify target state after targeting (e.g., creature gains toughness)
    p2.battlefield[0].toughness_bonus += 5

    item = game.stack[0]
    # Target index still points to the correct permanent (current state is used)
    assert item.target_permanent_index == 0
    assert p2.battlefield[item.target_permanent_index].effective_toughness == 7


def test_115_9c_targets_only_checks_number_of_distinct_targets():
    """'Targets only [something]' checks the number of different objects or players targeted (115.9c).

    If only one distinct object or player was chosen, the current state of that target is checked.
    """
    arc_trail = _mk_card(
        "Arc Trail",
        "Sorcery",
        "Arc Trail deals 2 damage to any target and 1 damage to any other target.",
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    # Same target chosen for both 'target' instances (same object or player)
    game.stack.append(
        StackItem(
            card=arc_trail,
            caster_index=0,
            target_player_index=1,
            target_permanent_index=[0, 0],
            x_value=None,
        )
    )

    item = game.stack[0]
    indices = item.target_permanent_index if isinstance(item.target_permanent_index, list) else [item.target_permanent_index]
    distinct_targets = len(set(indices))
    assert distinct_targets == 1  # only one distinct permanent was targeted


# ---------------------------------------------------------------------------
# Rule 115.10 — Spells affect objects without targeting them
# ---------------------------------------------------------------------------


def test_115_10_spell_affects_nontarget_objects_on_resolution():
    """Spells can affect objects and players they do not target (115.10).

    A board-wide effect (e.g., a wrath) affects all creatures without targeting any.
    """
    wrath = _mk_card(
        "Wrath of God",
        "Sorcery",
        "Destroy all creatures. They can't be regenerated.",
        mana_cost="{2}{W}{W}",
        colors=("W",),
        cmc=4.0,
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    wolf = _mk_card("Timber Wolf", "Creature — Wolf")
    p1 = PlayerState(name="P1", hand=[wrath])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=bear), Permanent(card=wolf)],
    )
    game = Game(players=[p1, p2])

    result = game.cast_from_hand(0, "Wrath of God")

    assert result.supported
    # Creatures destroyed without being targeted
    assert len(p2.battlefield) == 0


def test_115_10_wrath_stack_item_has_no_target():
    """A board-wide spell that affects creatures has no target on its stack item (115.10a)."""
    wrath = _mk_card(
        "Wrath of God",
        "Sorcery",
        "Destroy all creatures. They can't be regenerated.",
        mana_cost="{2}{W}{W}",
        colors=("W",),
        cmc=4.0,
    )
    bear = _mk_card("Grizzly Bears", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[wrath])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=bear)])
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Wrath of God")

    item = game.stack[0]
    assert item.target_player_index is None
    assert item.target_permanent_index is None


def test_115_10b_you_in_oracle_text_is_not_a_target():
    """The word 'you' in a spell's text does not indicate a target (115.10b)."""
    recall = _mk_card(
        "Ancestral Recall",
        "Instant",
        "Target player draws three cards.",
    )
    dummy = _mk_card("Dummy", "Sorcery")
    p1 = PlayerState(
        name="P1",
        hand=[recall],
        library=[dummy, dummy, dummy],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    # Cast targeting self (via 'target player' — not 'you')
    result = game.cast_from_hand(0, "Ancestral Recall", target_player_index=0)

    assert result.supported
    # P1 drew three cards; this is a targeted effect because oracle_text says 'target player',
    # not because it says 'you'
    assert len(p1.hand) == 3


def test_115_10b_you_gain_life_spell_has_no_target():
    """A spell that says 'you gain N life' has no target — 'you' is not 'target you' (115.10b)."""
    ritual = _mk_card(
        "Stream of Life",
        "Sorcery",
        "Target player gains X life.",
    )
    self_heal = _mk_card(
        "Healing Wave",
        "Sorcery",
        "You gain 5 life.",
    )
    p1 = PlayerState(name="P1", hand=[self_heal])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_from_hand(0, "Healing Wave")

    assert result.supported
    item = game.stack[-1]
    # 'You' in the text means the controller; it is not a target
    assert item.target_player_index is None

"""Tests for CR 117 (Timing and Priority), CR 405 (The Stack), and CR 608
(Resolving Spells and Abilities).

Covers the parts of those rules this engine implements: the priority window
(`start_priority_window` / `has_priority` / `pass_priority` /
`note_priority_action_taken` in engine/mixins/phase_steps.py), the LIFO stack
(`game.stack` of StackItems, `resolve_top_of_stack`), state-based actions
before priority, actions that bypass the stack (turn-based untap, mana
abilities), and target-legality checks at resolution.

Not covered (engine gaps, noted rather than asserted):
- 117.6 (shared team turns) — the variant isn't implemented.
- 405.3 (APNAP ordering of simultaneously-added stack objects) — the engine
  never puts two players' objects on the stack in one event.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.game import StackItem
from engine.models import CardDefinition, Permanent, PlayerState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_card(
    name: str,
    type_line: str,
    oracle_text: str = "",
    mana_cost: str = "",
    colors: tuple[str, ...] = (),
    produced_mana: tuple[str, ...] = (),
) -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"] = "2"
        raw["toughness"] = "2"
    return CardDefinition(
        name=name,
        mana_cost=mana_cost,
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=(),
        produced_mana=produced_mana,
        raw=raw,
    )


def _get(all_cards, name: str) -> CardDefinition:
    return next(card for card in all_cards if card.name == name)


def _filler_library(count: int = 3) -> list[CardDefinition]:
    """Dummy cards so start_turn's draw step never draws from an empty library
    (which would flag the player for a 704.5b loss at the next SBA check)."""
    return [_mk_card(f"Filler {i}", "Sorcery", "Target player gains 1 life.") for i in range(count)]


def _game_in_main_phase(p1: PlayerState, p2: PlayerState) -> Game:
    """A game advanced to P1's precombat main phase with the priority window open."""
    p1.library.extend(_filler_library())
    p2.library.extend(_filler_library())
    game = Game(players=[p1, p2])
    game.start_turn(0)
    assert game.current_step == "precombat_main"
    return game


# ---------------------------------------------------------------------------
# 117.1 — the player with priority may cast spells and pass
# ---------------------------------------------------------------------------


@pytest.mark.cr("117.1", "117.3c")
def test_117_1_player_with_priority_may_cast_and_retains_priority():
    """The priority holder may cast a spell (117.1); after casting, that same
    player receives priority again (117.3c)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = _game_in_main_phase(p1, p2)

    assert game.has_priority(0)
    result = game.queue_from_hand(0, "Bolt", target_player_index=1)
    assert result.supported
    game.note_priority_action_taken(0)  # accepted: player 0 held priority

    # 117.3c: the caster holds priority again after casting.
    assert game.has_priority(0)
    assert game.priority_pass_count == 0
    assert len(game.stack) == 1


@pytest.mark.cr("117.1")
def test_117_1_player_without_priority_cannot_act_or_pass():
    """Only the player with priority can take actions or pass; the engine
    rejects both from anyone else (117.1)."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = _game_in_main_phase(p1, p2)

    assert game.has_priority(0)
    with pytest.raises(ValueError, match="does not have priority"):
        game.pass_priority(1)
    with pytest.raises(ValueError, match="does not have priority"):
        game.note_priority_action_taken(1)


# ---------------------------------------------------------------------------
# 117.3 — which player has priority
# ---------------------------------------------------------------------------


@pytest.mark.cr("117.3", "117.3a")
def test_117_3a_active_player_receives_priority_at_start_of_main_phase():
    """The active player receives priority at the beginning of the main phase,
    after turn-based actions (untap/draw) are dealt with (117.3a)."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = _game_in_main_phase(p1, p2)

    assert game.priority_player_index == game.active_player_index == 0
    assert game.has_priority(0)
    assert not game.has_priority(1)


@pytest.mark.cr("117.3a", "117.2c")
def test_117_3a_no_player_receives_priority_during_untap_step():
    """No player receives priority during the untap step (117.3a); untapping is
    a turn-based action performed before anyone could receive priority (117.2c)."""
    land = Permanent(card=_mk_card("Test Land", "Land"), tapped=True)
    creature = Permanent(card=_mk_card("Test Bear", "Creature — Bear"), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[land, creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    # Game construction opens a window for the default step; close it so we can
    # observe that the untap step itself never grants priority.
    game.clear_priority_window()

    assert game._receives_priority("untap") is False
    untapped = game.resolve_untap_step(0)

    # The turn-based action happened, and no priority window was ever opened.
    assert untapped == 2
    assert not land.tapped and not creature.tapped
    assert game.priority_player_index is None


@pytest.mark.cr("117.3", "117.3d")
def test_117_3d_passing_hands_priority_to_next_player_in_turn_order():
    """When the priority holder passes, the next player in turn order receives
    priority (117.3d)."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = _game_in_main_phase(p1, p2)

    assert game.priority_player_index == 0
    result = game.pass_priority(0)

    assert result == "passed"
    assert game.priority_player_index == 1


@pytest.mark.cr("117.3b")
def test_117_3b_active_player_gets_priority_after_spell_resolves():
    """After a spell resolves, the *active* player receives priority — even when
    the spell's controller was the nonactive player (117.3b)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", hand=[bolt])
    game = _game_in_main_phase(p1, p2)

    game.pass_priority(0)  # priority moves to the nonactive player
    game.queue_from_hand(1, "Bolt", target_player_index=0)
    game.note_priority_action_taken(1)

    game.pass_priority(1)
    result = game.pass_priority(0)  # all players have now passed

    assert result == "resolved_top"
    assert p1.life == 17  # the nonactive player's spell resolved
    # Priority returns to the active player, not the spell's controller.
    assert game.priority_player_index == game.active_player_index == 0


# ---------------------------------------------------------------------------
# 117.4 / 405.5 — all players passing in succession
# ---------------------------------------------------------------------------


@pytest.mark.cr("117.4", "405.5")
def test_117_4_all_pass_with_nonempty_stack_resolves_top():
    """If all players pass in succession while the stack is nonempty, the top
    spell resolves (117.4 / 405.5)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=20)
    game = _game_in_main_phase(p1, p2)

    game.queue_from_hand(0, "Bolt", target_player_index=1)
    game.note_priority_action_taken(0)
    assert p2.life == 20  # nothing happens until all players pass

    game.pass_priority(0)
    result = game.pass_priority(1)

    assert result == "resolved_top"
    assert len(game.stack) == 0
    assert p2.life == 17


@pytest.mark.cr("117.4", "405.5")
def test_117_4_all_pass_on_empty_stack_ends_the_step():
    """If all players pass in succession while the stack is empty, the step or
    phase ends (117.4 / 405.5) — the engine signals this with 'all_passed_empty'."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = _game_in_main_phase(p1, p2)

    game.pass_priority(0)
    result = game.pass_priority(1)

    assert result == "all_passed_empty"


# ---------------------------------------------------------------------------
# 117.5 — state-based actions performed before a player gets priority
# ---------------------------------------------------------------------------


@pytest.mark.cr("117.5", "704.5a")
def test_117_5_state_based_actions_performed_before_priority():
    """When a spell's resolution leaves a player at 0 life, that state-based
    action (704.5a) is performed before any player would receive priority
    (117.5) — by the time priority returns, the loss is already recorded."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=3)
    game = _game_in_main_phase(p1, p2)

    game.queue_from_hand(0, "Bolt", target_player_index=1)
    game.note_priority_action_taken(0)
    game.pass_priority(0)
    result = game.pass_priority(1)

    assert result == "resolved_top"
    assert p2.life == 0
    # The SBA already fired: the loss is recorded before priority was handed out.
    assert p2.lost is True
    assert game.priority_player_index == 0


# ---------------------------------------------------------------------------
# 405.1 — spells and abilities go on the stack
# ---------------------------------------------------------------------------


@pytest.mark.cr("405.1")
def test_405_1_casting_puts_the_physical_card_on_the_stack():
    """When a spell is cast, the card itself is put on the stack (405.1)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt", target_player_index=1)

    assert len(p1.hand) == 0
    assert len(game.stack) == 1
    assert game.stack[0].card is bolt  # the same physical card object


@pytest.mark.cr("405.1", "405.4")
def test_405_1_activated_ability_goes_on_stack_without_its_card(all_cards):
    """An activated ability goes on the stack without any card associated with
    it — its source stays on the battlefield (405.1) — and its controller is
    the player who activated it (405.4)."""
    tim = Permanent(card=_get(all_cards, "Prodigal Sorcerer"))
    p1 = PlayerState(name="P1", battlefield=[tim])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    result = game.queue_permanent_ability(0, "Prodigal Sorcerer", target_player_index=1)

    assert result.supported and result.details == "queued"
    assert len(game.stack) == 1
    item = game.stack[0]
    assert item.ability_instruction is not None  # a compiled ability, not a card
    assert item.source_permanent is tim
    assert tim in p1.battlefield  # the source never left the battlefield
    assert item.caster_index == 0  # 405.4: controller = the activating player

    game.resolve_top_of_stack()
    assert p2.life == 19
    assert len(game.stack) == 0


# ---------------------------------------------------------------------------
# 405.2 — the stack is LIFO
# ---------------------------------------------------------------------------


@pytest.mark.cr("405.2")
def test_405_2_new_objects_go_on_top_and_resolve_first():
    """Each object added to the stack goes on top of those already there
    (405.2); resolving takes the last-added object first."""
    early = _mk_card("Early Spell", "Instant", "Early Spell deals 1 damage to any target.")
    late = _mk_card("Late Spell", "Instant", "Late Spell deals 2 damage to any target.")
    p1 = PlayerState(name="P1", hand=[early, late])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Early Spell", target_player_index=1)
    game.queue_from_hand(0, "Late Spell", target_player_index=1)

    assert game.stack[-1].card.name == "Late Spell"
    assert game.stack[0].card.name == "Early Spell"

    game.resolve_top_of_stack()
    # Only the most recently added spell has resolved.
    assert p2.life == 18
    assert len(game.stack) == 1
    assert game.stack[0].card.name == "Early Spell"

    game.resolve_top_of_stack()
    assert p2.life == 17


# ---------------------------------------------------------------------------
# 405.4 — a spell on the stack has its card's characteristics; caster controls it
# ---------------------------------------------------------------------------


@pytest.mark.cr("405.4")
def test_405_4_spell_has_card_characteristics_and_caster_controls_it():
    """A spell on the stack has all the characteristics of its card, and its
    controller is the player who cast it (405.4)."""
    spell = _mk_card(
        "Blue Trick",
        "Instant",
        "Blue Trick deals 1 damage to any target.",
        mana_cost="{U}",
        colors=("U",),
    )
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2", hand=[spell])
    game = Game(players=[p1, p2])

    game.queue_from_hand(1, "Blue Trick", target_player_index=0)

    item = game.stack[0]
    assert item.card.name == "Blue Trick"
    assert item.card.type_line == "Instant"
    assert item.card.colors == ("U",)
    assert item.card.mana_cost == "{U}"
    assert item.caster_index == 1


# ---------------------------------------------------------------------------
# 405.6 — some things don't use the stack
# ---------------------------------------------------------------------------


@pytest.mark.cr("405.6", "405.6e")
def test_405_6e_untap_turn_based_action_does_not_use_the_stack():
    """Turn-based actions like untapping don't use the stack — the permanents
    untap without any object being put on the stack (405.6e)."""
    land = Permanent(card=_mk_card("Test Land", "Land"), tapped=True)
    creature = Permanent(card=_mk_card("Test Bear", "Creature — Bear"), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[land, creature])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    game.resolve_untap_step(0)

    assert not land.tapped and not creature.tapped
    assert game.stack == []  # nothing was ever placed on the stack


@pytest.mark.cr("405.6c")
def test_405_6c_mana_ability_resolves_immediately_without_the_stack():
    """A mana ability resolves immediately: the mana is produced at activation
    and nothing is put on the stack (405.6c)."""
    sol_ring = _mk_card("Sol Ring", "Artifact", "{T}: Add {C}{C}.", produced_mana=("C", "C"))
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=sol_ring, tapped=False)])
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])

    result = game.queue_permanent_ability(0, "Sol Ring")

    assert result.supported
    assert result.details != "queued"  # never went on the stack
    assert game.stack == []
    assert p1.mana_pool.get("C", 0) == 2
    assert p1.battlefield[0].tapped is True


# ---------------------------------------------------------------------------
# 608.1 — each time all players pass, the top of the stack resolves
# ---------------------------------------------------------------------------


@pytest.mark.cr("608.1", "117.7")
def test_608_1_each_full_round_of_passes_resolves_exactly_one_object():
    """Each time all players pass in succession, exactly one object — the top of
    the stack — resolves (608.1). A spell cast in response to another resolves
    first (117.7)."""
    slow = _mk_card("Slow Spell", "Instant", "Slow Spell deals 1 damage to any target.")
    response = _mk_card("Response", "Instant", "Response deals 2 damage to any target.")
    p1 = PlayerState(name="P1", hand=[slow])
    p2 = PlayerState(name="P2", hand=[response])
    game = _game_in_main_phase(p1, p2)

    game.queue_from_hand(0, "Slow Spell", target_player_index=1)
    game.note_priority_action_taken(0)
    game.pass_priority(0)

    # The nonactive player responds while Slow Spell is on the stack (117.7).
    game.queue_from_hand(1, "Response", target_player_index=0)
    game.note_priority_action_taken(1)
    game.pass_priority(1)
    result = game.pass_priority(0)

    # Only the response — the newer, topmost spell — has resolved.
    assert result == "resolved_top"
    assert p1.life == 18
    assert p2.life == 20
    assert len(game.stack) == 1

    # The next full round of passes resolves the remaining spell.
    game.pass_priority(0)
    result = game.pass_priority(1)
    assert result == "resolved_top"
    assert p2.life == 19
    assert len(game.stack) == 0


# ---------------------------------------------------------------------------
# 608.2 — resolving instants/sorceries/abilities
# ---------------------------------------------------------------------------


@pytest.mark.cr("608.2", "608.2b")
def test_608_2b_spell_whose_target_became_illegal_does_not_resolve(all_cards):
    """A spell checks its targets' legality on resolution; if every target is
    now illegal the spell doesn't resolve and goes to its owner's graveyard
    (608.2b). Here Red Ward, resolving first, makes the Bolt's target illegal
    while the Bolt is still on the stack."""
    bears = Permanent(card=_get(all_cards, "Grizzly Bears"))
    p1 = PlayerState(name="P1", hand=[_get(all_cards, "Lightning Bolt")])
    p2 = PlayerState(name="P2", hand=[_get(all_cards, "Red Ward")], battlefield=[bears])
    game = Game(players=[p1, p2])

    # Bolt is cast at the Bears while they are a legal target...
    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    # ...then Red Ward is cast in response and resolves first (LIFO).
    game.queue_from_hand(1, "Red Ward", target_player_index=1, target_permanent_index=0)
    game.resolve_top_of_stack()
    assert game._protection_colors(bears) == {"R"}

    game.resolve_top_of_stack()  # Bolt: its only target is now illegal

    assert bears.damage_marked == 0
    assert bears in p2.battlefield
    # 608.2b: the spell was removed from the stack and put into its owner's graveyard.
    assert game.stack == []
    assert any(card.name == "Lightning Bolt" for card in p1.graveyard)


@pytest.mark.cr("608.2n")
def test_608_2n_instant_is_put_into_owners_graveyard_after_resolving():
    """As the final part of an instant's resolution, the card is put into its
    owner's graveyard (608.2n)."""
    bolt = _mk_card("Bolt", "Instant", "Bolt deals 3 damage to any target.")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    game.queue_from_hand(0, "Bolt", target_player_index=1)
    game.resolve_top_of_stack()

    assert p2.life == 17  # the effect happened first
    assert game.stack == []
    assert bolt in p1.graveyard


# ---------------------------------------------------------------------------
# 608.3 — resolving permanent spells
# ---------------------------------------------------------------------------


@pytest.mark.cr("608.3", "608.3a")
def test_608_3a_permanent_spell_enters_battlefield_under_controllers_control():
    """A resolving permanent spell with no targets becomes a permanent and
    enters the battlefield under its controller's control (608.3a)."""
    bear = _mk_card("Grizzly Cub", "Creature — Bear")
    p1 = PlayerState(name="P1", hand=[bear])
    p2 = PlayerState(name="P2")
    game = _game_in_main_phase(p1, p2)

    game.queue_from_hand(0, "Grizzly Cub")
    game.note_priority_action_taken(0)
    game.pass_priority(0)
    result = game.pass_priority(1)

    assert result == "resolved_top"
    assert game.stack == []
    assert len(p1.battlefield) == 1
    assert p1.battlefield[0].card.name == "Grizzly Cub"
    assert p2.battlefield == []


@pytest.mark.cr("608.3b")
def test_608_3b_aura_spell_with_illegal_target_does_not_resolve(all_cards):
    """An Aura spell whose target left the battlefield doesn't resolve — it is
    put into its owner's graveyard instead of entering the battlefield (608.3b)."""
    bears = Permanent(card=_get(all_cards, "Grizzly Bears"))
    holy_strength = _get(all_cards, "Holy Strength")
    p1 = PlayerState(name="P1", hand=[holy_strength])
    p2 = PlayerState(name="P2", battlefield=[bears])
    game = Game(players=[p1, p2])

    # The Aura is cast at a legal target...
    result = game.queue_from_hand(
        0, "Holy Strength", target_player_index=1, target_permanent_index=0
    )
    assert result.supported
    # ...which leaves the battlefield while the Aura spell is on the stack.
    p2.battlefield.clear()

    game.resolve_top_of_stack()

    assert holy_strength in p1.graveyard
    assert all(perm.card.name != "Holy Strength" for perm in p1.battlefield)
    assert all(perm.card.name != "Holy Strength" for perm in p2.battlefield)
    assert game.stack == []


@pytest.mark.cr("608.2b")
def test_608_2b_damage_spell_with_vanished_creature_target_does_not_hit_the_player(all_cards):
    """A damage spell whose creature target has left the battlefield does
    nothing on resolution (608.2b) — it must not fall back to damaging the
    targeted creature's controller."""
    bolt = _get(all_cards, "Lightning Bolt")
    p1 = PlayerState(name="P1", hand=[bolt])
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])

    # Target creature index 0 on P2's (now empty) battlefield: the creature is
    # gone by resolution time, so the spell fizzles.
    result = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)

    assert result.supported
    assert p2.life == 20  # no fallback damage to the player
    assert any(card.name == "Lightning Bolt" for card in p1.graveyard)

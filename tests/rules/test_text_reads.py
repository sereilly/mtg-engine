"""CR 613 layers 1, 3 and 6 — what a permanent *says* is computed, not printed.

``Permanent.effective_card`` is that answer: layer 1 folds in what the permanent
copies (CR 707.2), layer 3 folds in a text change (CR 612.1), and the abilities a
board-wide static grants are appended after both. Reading ``perm.card.oracle_text``
instead asks the card as it left the printer, which no effect can change.

This is the sibling of ``tests/rules/test_subtype_reads.py``. Round 48 gave
``has_type`` and ``effective_colors`` a ratchet and wrote down that the text had
none; the census that followed found the reads below, every one of them a rule
the engine implements correctly and then declines to notice:

  * a Clone of a Wall could attack, and so could a Primal Clay that entered on
    its 1/6 Wall body — one site, two different layers reaching it;
  * a Clone of Veteran Bodyguard let its controller take the damage;
  * a Copy Artifact of Time Vault untapped every turn;
  * Sleight of Mind on a Ward, and Magical Hack on Burrowing or Aspect of Wolf,
    changed the printed word and nothing else.

The guard that fails when a new one appears is
``tests/engine/test_layer_reads.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_catalog
from engine.copies import become_copy
from engine.damage_events import deal_damage
from engine.models import Permanent
from engine.text_changes import change_color_word, change_land_word

_CATALOG = {c.name: c for c in load_catalog()}


def _board(
    *names: str, copies: dict[int, int] | None = None
) -> tuple[Game, PlayerState, list[Permanent]]:
    """A two-seat game with *names* on seat 0's battlefield.

    ``copies`` maps a permanent's index to the index of the one it copies, and
    it is applied **before** the ``Game`` exists. That ordering is a parameter
    rather than a note because getting it wrong is silent: a Clone that has
    copied nothing is a 0/0, so the first state-based-action pass bins it
    (CR 704.5f) and every later assertion is made about a permanent that is no
    longer on the battlefield.
    """
    perms = [Permanent(card=_CATALOG[name]) for name in names]
    for copier, original in (copies or {}).items():
        become_copy(perms[copier], perms[original])
    for perm in perms:
        perm.metadata["summoning_sickness_turn"] = -99
    p1 = PlayerState(name="P1", battlefield=perms)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    assert len(p1.battlefield) == len(names), "the fixture lost a permanent"
    return game, p1, perms


# ---------------------------------------------------------------------------
# Layer 1 — a copy says what it copied
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.2a", "707.2", "702.3b")
def test_702_3b_a_clone_of_a_wall_cannot_attack():
    """Defender is one of the copiable values (CR 707.2 lists rules text), so a
    Clone of Wall of Stone has it. The attack gate asked ``card.keywords`` — the
    Clone's own printed list, which is empty — and let it through."""
    game, _p1, (clone, wall) = _board("Clone", "Wall of Stone", copies={0: 1})

    assert game._has_keyword(clone, "defender")
    assert not game.can_attack(clone, 1)
    assert not game.can_attack(wall, 1), "the control: the Wall itself never could"


@pytest.mark.cr("613.2a", "707.2")
def test_a_clone_of_a_creature_without_defender_still_attacks():
    """The control. Without it the test above would pass for a Clone that simply
    could not attack at all."""
    game, _p1, (clone, _bears) = _board("Clone", "Grizzly Bears", copies={0: 1})

    assert game.can_attack(clone, 1)


@pytest.mark.cr("613.1f", "702.3b")
def test_702_3b_a_primal_clay_on_its_wall_body_cannot_attack():
    """The same site reached by the other layer. Primal Clay's third body grants
    defender in layer 6, so it is not in the printed keyword list *or* in the
    effective card — only ``_has_keyword`` knows. Round 47 made this body a real
    Wall; it could still attack."""
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0}
    p1.hand = [_CATALOG["Primal Clay"]]
    game.queue_from_hand(0, "Primal Clay")
    game.resolve_top_of_stack()
    clay = p1.battlefield[-1]
    assert game.confirm_enter_body_choice(0, 2)
    clay.metadata["summoning_sickness_turn"] = -99

    assert clay.has_type("wall") and game._has_keyword(clay, "defender")
    assert not clay.effective_card.keywords, "the grant is layer 6, not layer 1 or 3"
    assert not game.can_attack(clay, 1)


@pytest.mark.cr("613.2a", "707.2")
def test_a_primal_clay_on_a_body_without_defender_still_attacks():
    """The control for the body, not for the card."""
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0}
    p1.hand = [_CATALOG["Primal Clay"]]
    game.queue_from_hand(0, "Primal Clay")
    game.resolve_top_of_stack()
    clay = p1.battlefield[-1]
    assert game.confirm_enter_body_choice(0, 0)
    clay.metadata["summoning_sickness_turn"] = -99

    assert not game._has_keyword(clay, "defender")
    assert game.can_attack(clay, 1)


@pytest.mark.cr("613.2a", "707.2", "509.1h")
def test_a_clone_of_veteran_bodyguard_takes_the_damage_instead():
    """"As long as this creature is untapped, all damage that would be dealt to
    you by unblocked creatures is dealt to this creature instead." The
    replacement finds its bodyguard by scanning the defender's board for that
    sentence, and a Clone prints none of it."""
    game, p1, (clone, bodyguard) = _board("Clone", "Veteran Bodyguard", copies={0: 1})
    # Remove the real one: the Clone alone has to answer for the effect.
    game.remove_from_battlefield(bodyguard)

    attacker = Permanent(card=_CATALOG["Grizzly Bears"])
    attacker.attacking, attacker.blocked = True, False
    outcome = deal_damage(
        game, {"recipient": p1, "amount": 2, "source": attacker, "combat": True}
    )

    assert outcome.consumed and outcome.dealt == 0
    assert clone.damage_marked == 2


@pytest.mark.cr("613.2a", "707.2", "502.3")
def test_502_3_a_copy_of_time_vault_does_not_untap():
    """Copy Artifact copying Time Vault is the copy this pool is most likely to
    see. "This artifact doesn't untap during your untap step" is rules text, so
    the copy has it — and the untap step read the copier's own card."""
    game, p1, (copier, vault) = _board("Copy Artifact", "Time Vault", copies={0: 1})
    copier.tapped = vault.tapped = True

    assert sorted(game.get_begin_turn_untap_options(0)) == ["Copy Artifact", "Time Vault"]
    game.resolve_untap_step(0)
    assert copier.tapped, "the copy is a Time Vault and stays tapped"


@pytest.mark.cr("613.2a", "707.2", "509.1a")
def test_509_1a_a_clone_of_two_headed_giant_blocks_two_attackers():
    """How many creatures a blocker may block is read off "can block an
    additional creature", which the Clone acquires with the rest of the text."""
    game, _p1, (clone, giant) = _board("Clone", "Two-Headed Giant of Foriys", copies={0: 1})

    assert game._max_blocks_for(clone) == 2
    assert game._max_blocks_for(giant) == 2


# ---------------------------------------------------------------------------
# Layer 3 — a text change rewrites what the permanent says
# ---------------------------------------------------------------------------


@pytest.mark.cr("612.1", "613.1c", "702.16b")
def test_612_1_a_sleight_of_mind_on_a_ward_moves_the_protection():
    """Black Ward grants "protection from black". Sleight of Mind replacing
    "black" with "blue" moves the shield — the Aura's grant was derived from the
    printed sentence, so the enchanted creature kept the old colour and never
    gained the new one."""
    game, _p1, (ward, bears) = _board("Black Ward", "Grizzly Bears")
    attach_aura(ward, bears)
    assert game._protection_qualities(bears) == {("color", "B")}

    change_color_word(ward, "B", "U", label="Sleight of Mind")

    assert game._protection_qualities(bears) == {("color", "U")}


@pytest.mark.cr("612.1", "613.1c", "702.14a")
def test_612_1_a_magical_hack_on_burrowing_moves_the_landwalk_it_grants():
    """"Enchanted creature has mountainwalk." The land word is inside the
    keyword, which ``engine/text_changes.py`` rewrites on purpose — and the Aura
    keyword grant then read the printed sentence and granted mountainwalk
    anyway."""
    game, _p1, (burrowing, bears) = _board("Burrowing", "Grizzly Bears")
    attach_aura(burrowing, bears)
    assert game._has_keyword(bears, "mountainwalk")

    change_land_word(burrowing, "mountain", "swamp", label="Magical Hack")

    assert game._has_keyword(bears, "swampwalk")
    assert not game._has_keyword(bears, "mountainwalk")


@pytest.mark.cr("612.1", "613.1c")
def test_612_1_a_magical_hack_on_aspect_of_wolf_counts_the_new_land_type():
    """"+X/+Y, where X is half the number of Forests you control." The count is
    the one place a text change is *arithmetic* rather than a keyword, and the
    bonus went on counting Forests after the card said Islands."""
    game, p1, (aspect, bears) = _board("Aspect of Wolf", "Grizzly Bears")
    for name in ("Forest", "Forest", "Forest", "Island"):
        p1.battlefield.append(Permanent(card=_CATALOG[name]))
    attach_aura(aspect, bears)

    game._refresh_dynamic_creatures()
    assert (bears.effective_power, bears.effective_toughness) == (2 + 1, 2 + 2)

    change_land_word(aspect, "forest", "island", label="Magical Hack")
    game._refresh_dynamic_creatures()

    assert (bears.effective_power, bears.effective_toughness) == (2 + 0, 2 + 1)

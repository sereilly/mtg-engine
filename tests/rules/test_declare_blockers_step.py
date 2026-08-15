"""Tests for the Declare Blockers Step (Comprehensive Rules 509).

Each test cites the specific subrule it exercises. Where Limited Edition Alpha
has no card for a corner of the rule (e.g. menace, costs to block, creatures put
onto the battlefield blocking), that is noted in the test or its docstring rather
than asserted against absent functionality.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent, PlayerState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_creature(
    name: str,
    power: int,
    toughness: int,
    *,
    oracle_text: str = "",
    keywords: tuple[str, ...] = (),
    colors: tuple[str, ...] = (),
    type_line: str = "Creature - Test",
) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=keywords,
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": str(power), "toughness": str(toughness)},
    )


def _lure_card() -> CardDefinition:
    """Lure's printed text. The block requirement is read off this, so the test
    exercises the same derivation the game does."""
    return CardDefinition(
        name="Lure", mana_cost="{1}{G}{G}", cmc=3.0,
        type_line="Enchantment — Aura",
        oracle_text=(
            "Enchant creature\n"
            "All creatures able to block enchanted creature do so."
        ),
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Lure", "type_line": "Enchantment — Aura"},
    )


def _to_declare_blockers(game: Game, attacker_indices: list[int]) -> None:
    """Advance a freshly built game to the declare_blockers step with attacks made."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"


def _get(all_cards, name: str) -> CardDefinition:
    return next(card for card in all_cards if card.name == name)


def _block_triggers_on_stack(game: Game) -> list:
    return [item for item in game.stack if item.ability_effect_kind == "triggered_delayed_destroy"]


# ---------------------------------------------------------------------------
# 509.1 — the declaration is atomic; an illegal declaration is undone
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.1")
def test_509_1_illegal_declaration_leaves_state_unchanged():
    """509.1: if the defender can't comply, the game returns to before the declaration."""
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    # Assigning the blocker to a non-attacker index is illegal.
    ok, _ = game.declare_blockers(1, {0: 99})
    assert not ok
    assert game.combat_blockers == {}
    assert game.combat_blockers_locked is False
    assert blocker.blocking_attacker_index is None


# ---------------------------------------------------------------------------
# 509.1a — chosen creatures must be untapped; each blocks an attacker of that player
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.1a")
def test_509_1a_tapped_creature_cannot_block():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Tapped Blocker", 2, 2), tapped=True)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok
    assert game.combat_blockers == {}


@pytest.mark.cr("509.1a")
def test_509_1a_blocker_must_be_assigned_to_a_real_attacker():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    other = Permanent(card=_mk_creature("Not Attacking", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker, other])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])  # only index 0 attacks

    ok, _ = game.declare_blockers(1, {0: 1})  # index 1 is not an attacker
    assert not ok


@pytest.mark.cr("509.1a")
def test_509_1a_only_defending_player_may_declare_blockers():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    # The active (attacking) player can't declare blocks.
    ok, _ = game.declare_blockers(0, {0: 0})
    assert not ok


# ---------------------------------------------------------------------------
# 509.1b — restrictions / evasion abilities
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.1b", "702.9b")
def test_509_1b_flying_attacker_cannot_be_blocked_by_ground_creature():
    flier = Permanent(card=_mk_creature("Flier", 2, 2, keywords=("Flying",)))
    grounder = Permanent(card=_mk_creature("Grounder", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[flier])
    p2 = PlayerState(name="P2", battlefield=[grounder])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok


@pytest.mark.cr("509.1b", "702.9b", "702.17b")
def test_509_1b_flying_attacker_can_be_blocked_by_flier_or_reach():
    flier = Permanent(card=_mk_creature("Flier", 2, 2, keywords=("Flying",)))
    reacher = Permanent(card=_mk_creature("Reacher", 2, 2, keywords=("Reach",)))
    p1 = PlayerState(name="P1", battlefield=[flier])
    p2 = PlayerState(name="P2", battlefield=[reacher])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    # combat_blockers is nested by defender index -> {blocker index -> list of
    # blocked attacker indices} (CR 802: 2+ defenders may declare blocks in the
    # same combat; a creature may block several attackers, CR 509.1b / _max_blocks_for).
    assert game.combat_blockers == {1: {0: [0]}}


@pytest.mark.cr("509.1b", "702.9b", "702.36b")
def test_509_1b_evasion_abilities_are_cumulative():
    """509.1b: an attacker with flying + fear needs a blocker that beats both."""
    sneaker = Permanent(card=_mk_creature("Sneaker", 2, 2, keywords=("Flying", "Fear")))
    # Flier alone defeats flying but not fear.
    plain_flier = Permanent(card=_mk_creature("Plain Flier", 2, 2, keywords=("Flying",)))
    # Black flier beats both restrictions.
    black_flier = Permanent(
        card=_mk_creature("Black Flier", 2, 2, keywords=("Flying",), colors=("B",))
    )
    p1 = PlayerState(name="P1", battlefield=[sneaker])
    p2 = PlayerState(name="P2", battlefield=[plain_flier, black_flier])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})  # plain flier
    assert not ok

    ok, _ = game.declare_blockers(1, {1: 0})  # black flier
    assert ok


# ---------------------------------------------------------------------------
# 509.1c — requirements (a creature that must block if able)
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.1c")
def test_509_1c_lure_requires_all_able_creatures_to_block():
    """509.1c: a creature able to block a 'must be blocked' attacker must do so.

    Lure makes every creature that can block the attacker required to block it;
    omitting one is an illegal declaration.
    """
    lure_attacker = Permanent(card=_mk_creature("Lured", 3, 3))
    # Attach a real Lure. The requirement is derived from the Auras attached to
    # the creature (engine/auras.py), so it ends when the Aura does — there is
    # no flag to set, and setting one describes a board that cannot occur.
    lure = Permanent(card=_lure_card())
    attach_aura(lure, lure_attacker)
    b1 = Permanent(card=_mk_creature("Blocker A", 2, 2))
    b2 = Permanent(card=_mk_creature("Blocker B", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[lure_attacker, lure])
    p2 = PlayerState(name="P2", battlefield=[b1, b2])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    # Only one of two able blockers assigned -> illegal.
    ok, _ = game.declare_blockers(1, {0: 0})
    assert not ok

    # Both able blockers assigned -> legal.
    ok, _ = game.declare_blockers(1, {0: 0, 1: 0})
    assert ok


# ---------------------------------------------------------------------------
# 509.1g — chosen creatures become blocking creatures
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.1g")
def test_509_1g_chosen_creature_becomes_a_blocking_creature():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    assert blocker.blocking_attacker_index == 0
    assert blocker.blocking_attacker_controller == 0


# ---------------------------------------------------------------------------
# 509.1h — attackers become blocked / unblocked; blocked stays blocked
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.1h")
def test_509_1h_attacker_with_blocker_becomes_blocked_and_without_stays_unblocked():
    a_blocked = Permanent(card=_mk_creature("Blocked Attacker", 2, 2))
    a_free = Permanent(card=_mk_creature("Free Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[a_blocked, a_free])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0, 1])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    assert a_blocked.blocked is True
    assert a_free.blocked is False


@pytest.mark.cr("509.1h")
def test_509_1h_creature_remains_blocked_after_its_blocker_leaves_combat():
    """509.1h: a creature stays blocked even if all its blockers leave combat."""
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    assert attacker.blocked is True

    # Blocker leaves the battlefield (e.g. bounced/destroyed in response).
    p2.battlefield.remove(blocker)
    game._prune_combat_state()

    assert attacker.blocked is True
    assert game.combat_blockers == {}


@pytest.mark.cr("509.1h", "510.1c")
def test_509_1h_blocked_attacker_deals_no_damage_to_player_when_blocker_dies():
    """509.1h corollary: a blocked attacker without trample deals no player damage
    even after its only blocker is gone."""
    attacker = Permanent(card=_mk_creature("Attacker", 4, 4))
    blocker = Permanent(card=_mk_creature("Blocker", 1, 1))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker], life=20)
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})

    # Remove the blocker before damage; attacker remains blocked, no trample.
    p2.battlefield.remove(blocker)
    game._prune_combat_state()
    game.advance_combat_phase()  # combat_damage

    assert p2.life == 20


# ---------------------------------------------------------------------------
# 509.2 — the active player gets priority after blockers are declared
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.2")
def test_509_2_active_player_gets_priority_after_blockers_declared():
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    # Active (attacking) player is index 0 and holds priority in declare_blockers.
    assert game.active_player_index == 0
    assert game.priority_player_index == 0
    assert game.has_priority(0)
    assert not game.has_priority(1)


@pytest.mark.cr("509.2", "117.4")
def test_509_2_priority_passing_advances_from_active_to_nonactive_player():
    """The priority window is real: passing hands priority to the defender, and a
    second pass on an empty stack ends the round back with the active player."""
    attacker = Permanent(card=_mk_creature("Attacker", 2, 2))
    blocker = Permanent(card=_mk_creature("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})

    assert game.priority_player_index == 0
    game.pass_priority(0)
    assert game.priority_player_index == 1  # defender gets priority next
    result = game.pass_priority(1)
    assert result == "all_passed_empty"
    assert game.priority_player_index == 0


# ---------------------------------------------------------------------------
# 509.1i / 509.2a / 509.3 — abilities trigger on blockers being declared
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.2a", "509.1i")
def test_509_2a_block_trigger_goes_on_stack_before_active_player_priority(all_cards):
    """509.2a: a triggered ability is put on the stack when blockers are declared,
    and the active player has priority while it sits there (it has not resolved)."""
    basilisk = Permanent(card=_get(all_cards, "Thicket Basilisk"))
    attacker = Permanent(card=_mk_creature("Victim", 1, 1))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[basilisk])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    # Trigger is on the stack, not yet resolved.
    assert len(_block_triggers_on_stack(game)) == 1
    assert attacker.metadata.get("destroy_at_end_of_combat") is None
    # 509.2: the active player holds priority with the trigger on the stack.
    assert game.priority_player_index == game.active_player_index == 0

    # It resolves only once both players pass priority.
    game.pass_priority(0)
    game.pass_priority(1)
    assert _block_triggers_on_stack(game) == []
    assert attacker.metadata.get("destroy_at_end_of_combat") is True


@pytest.mark.cr("509.3a")
def test_509_3a_creature_that_blocks_destroys_what_it_blocks(all_cards):
    """509.3a: Thicket Basilisk blocks -> destroys the blocked creature at EOC."""
    basilisk = Permanent(card=_get(all_cards, "Thicket Basilisk"))
    attacker = Permanent(card=_mk_creature("Victim", 1, 1))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[basilisk])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    # 509.1i / 509.2a: the trigger is queued on the stack, not resolved yet.
    assert len(_block_triggers_on_stack(game)) == 1

    game.advance_combat_phase()  # resolves stack on step end, then combat_damage
    assert attacker.metadata.get("destroy_at_end_of_combat") is True
    game.advance_combat_phase()  # end_of_combat
    assert all(perm.card.name != "Victim" for perm in p1.battlefield)


@pytest.mark.cr("509.3c")
def test_509_3c_attacker_that_becomes_blocked_destroys_its_blocker(all_cards):
    """509.3c: Thicket Basilisk attacks and becomes blocked -> destroys blocker."""
    basilisk = Permanent(card=_get(all_cards, "Thicket Basilisk"))
    blocker = Permanent(card=_mk_creature("Chump", 1, 1))
    p1 = PlayerState(name="P1", battlefield=[basilisk])
    p2 = PlayerState(name="P2", battlefield=[blocker])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    assert len(_block_triggers_on_stack(game)) == 1

    game.advance_combat_phase()  # combat_damage
    assert blocker.metadata.get("destroy_at_end_of_combat") is True
    game.advance_combat_phase()  # end_of_combat
    assert all(perm.card.name != "Chump" for perm in p2.battlefield)


@pytest.mark.cr("509.3")
def test_509_3_block_trigger_excludes_walls(all_cards):
    """The "non-Wall creature" clause: a Wall blocker triggers nothing."""
    basilisk = Permanent(card=_get(all_cards, "Thicket Basilisk"))
    wall = Permanent(card=_mk_creature("Stone Wall", 0, 4, type_line="Creature - Wall"))
    p1 = PlayerState(name="P1", battlefield=[basilisk])
    p2 = PlayerState(name="P2", battlefield=[wall])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {0: 0})
    assert ok
    assert _block_triggers_on_stack(game) == []

    game.advance_combat_phase()  # combat_damage
    game.advance_combat_phase()  # end_of_combat
    assert any(perm.card.name == "Stone Wall" for perm in p2.battlefield)


@pytest.mark.cr("509.3g")
def test_509_3_block_trigger_does_not_fire_for_unblocked_attacker(all_cards):
    """509.3g spirit: no block trigger when the Basilisk is never blocked."""
    basilisk = Permanent(card=_get(all_cards, "Thicket Basilisk"))
    bystander = Permanent(card=_mk_creature("Bystander", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[basilisk])
    p2 = PlayerState(name="P2", battlefield=[bystander])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])

    ok, _ = game.declare_blockers(1, {})  # no blocks
    assert ok
    assert _block_triggers_on_stack(game) == []
    assert bystander.metadata.get("destroy_at_end_of_combat") is None


@pytest.mark.cr("509.3a", "701.19a")
def test_509_3a_blocking_basilisk_regeneration_saves_the_blocked_creature(all_cards):
    """End-of-combat destruction honors regeneration shields like any destroy.

    The attacker is a 1/3 so the Basilisk's 2 combat damage is not lethal —
    otherwise the single shield would be consumed replacing the lethal-damage
    destruction (CR 701.19a: one shield replaces one destruction event) and the
    end-of-combat destroy would still kill it."""
    basilisk = Permanent(card=_get(all_cards, "Thicket Basilisk"))
    attacker = Permanent(card=_mk_creature("Tough Guy", 1, 3), regeneration_shield=1)
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[basilisk])
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])
    game.declare_blockers(1, {0: 0})

    game.advance_combat_phase()  # combat_damage
    game.advance_combat_phase()  # end_of_combat
    # Survived via regeneration.
    assert any(perm.card.name == "Tough Guy" for perm in p1.battlefield)
    assert attacker.regeneration_shield == 0


# ---------------------------------------------------------------------------
# 509.4 — creatures put onto the battlefield blocking
# ---------------------------------------------------------------------------

@pytest.mark.cr("509.4")
def test_509_4_no_alpha_card_puts_creatures_onto_battlefield_blocking(all_cards):
    """509.4 governs creatures put onto the battlefield blocking. Limited Edition
    Alpha has no such effect, so this documents the absence rather than asserting
    unimplemented behavior."""
    texts = [
        (card.oracle_text or "").lower()
        for card in all_cards
    ]
    assert not any("onto the battlefield blocking" in text for text in texts)


# ---------------------------------------------------------------------------
# 509.3c / 509.3d — how often a becomes-blocked trigger fires
# ---------------------------------------------------------------------------

_BARE = "Whenever this creature becomes blocked, you gain 1 life."
_PER_BLOCKER = "Whenever this creature becomes blocked by a creature, you gain 1 life."


def _blocked_by_two(oracle_text: str) -> tuple[Game, PlayerState]:
    attacker = Permanent(card=_mk_creature("Watched", 1, 4, oracle_text=oracle_text))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=_mk_creature("First", 1, 1)),
            Permanent(card=_mk_creature("Second", 1, 1)),
        ],
    )
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])
    ok, msg = game.declare_blockers(1, {0: 0, 1: 0})
    assert ok, msg
    game._settle()
    return game, p1


@pytest.mark.cr("509.3c")
def test_509_3c_a_bare_becomes_blocked_trigger_fires_once_however_many_blockers():
    """"…generally triggers only once each combat for that creature, even if
    it's blocked by multiple creatures.\""""
    _, p1 = _blocked_by_two(_BARE)
    assert p1.life == 21


@pytest.mark.cr("509.3d")
def test_509_3d_becomes_blocked_by_a_creature_fires_once_per_blocker():
    """"…triggers once for each creature that blocks the specified creature."

    The only difference on the card is the words "by a creature", which the
    condition carries as a subject filter — so the count is read off the
    trigger rather than off a list of card names."""
    _, p1 = _blocked_by_two(_PER_BLOCKER)
    assert p1.life == 22


@pytest.mark.cr("509.3d")
def test_509_3d_a_narrowed_becomes_blocked_trigger_counts_only_what_it_names():
    """"…by a creature with flying" admits one of the two blockers."""
    attacker = Permanent(card=_mk_creature(
        "Watched", 1, 4,
        oracle_text="Whenever this creature becomes blocked by a creature with flying, you gain 1 life.",
    ))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(
        name="P2",
        battlefield=[
            Permanent(card=_mk_creature("Grounded", 1, 1)),
            Permanent(card=_mk_creature("Winged", 1, 1, keywords=("Flying",))),
        ],
    )
    game = Game(players=[p1, p2])
    _to_declare_blockers(game, [0])
    ok, msg = game.declare_blockers(1, {0: 0, 1: 0})
    assert ok, msg
    game._settle()

    assert p1.life == 21


@pytest.mark.cr("509.3a")
def test_509_3a_a_narrowed_blocks_trigger_reads_what_was_blocked():
    """The blocker's own side of the same distinction: "whenever this creature
    blocks **a creature with flying**" is answered by the attacker, not by the
    blocker. Two games rather than one, because a creature without an ability
    saying otherwise blocks only one attacker (CR 509.1b)."""
    def gained(attacker_keywords: tuple[str, ...]) -> int:
        attacker = Permanent(card=_mk_creature(
            "Attacker", 1, 1, keywords=attacker_keywords
        ))
        blocker = Permanent(card=_mk_creature(
            "Watcher", 0, 6,
            keywords=("Reach",),   # or it could not block the flier at all
            oracle_text=(
                "Whenever this creature blocks a creature with flying, "
                "you gain 1 life."
            ),
        ))
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", battlefield=[blocker])
        game = Game(players=[p1, p2])
        _to_declare_blockers(game, [0])
        ok, msg = game.declare_blockers(1, {0: 0})
        assert ok, msg
        game._settle()
        return p2.life - 20

    assert gained(("Flying",)) == 1
    assert gained(()) == 0, "the rider is enforced, not consumed and dropped"

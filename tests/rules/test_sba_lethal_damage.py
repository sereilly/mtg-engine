"""CR 704.5g/h — lethal damage and deathtouch damage as state-based actions.

Before this was a state-based action, destruction from lethal damage happened
only when an effect explicitly called ``_destroy_marked_creatures()``. Nine
call sites did; any new damage-dealing effect that forgot would leave a
lethally damaged creature alive. Composed damage sequences make that easy to
hit, since a damage step no longer necessarily sits inside a handler that knows
to run the sweep — so the check belongs in the SBA loop where CR puts it.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature — Test",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=(),
        raw={
            "name": name,
            "type_line": "Creature — Test",
            "power": str(power),
            "toughness": str(toughness),
        },
    )


def _game_with(perm: Permanent) -> tuple[Game, PlayerState]:
    owner = PlayerState(name="P1", battlefield=[perm], life=20)
    opponent = PlayerState(name="P2", life=20)
    game = Game(players=[owner, opponent])
    game.enforce_mana_costs = False
    return game, owner


@pytest.mark.cr("704.5g")
def test_creature_with_lethal_damage_dies_at_the_next_sba_check():
    perm = Permanent(card=_creature("Grizzly Bears", 2, 2))
    game, owner = _game_with(perm)

    perm.damage_marked = 2
    game.check_state_based_actions()

    assert owner.battlefield == []
    assert [c.name for c in owner.graveyard] == ["Grizzly Bears"]


@pytest.mark.cr("704.5g")
def test_creature_with_non_lethal_damage_survives():
    perm = Permanent(card=_creature("Grizzly Bears", 2, 2))
    game, owner = _game_with(perm)

    perm.damage_marked = 1
    game.check_state_based_actions()

    assert owner.battlefield == [perm]
    assert perm.damage_marked == 1


@pytest.mark.cr("704.5g", "701.19")
def test_regeneration_replaces_the_destruction_and_clears_the_damage():
    perm = Permanent(card=_creature("Drudge Skeletons", 1, 1))
    game, owner = _game_with(perm)

    perm.regeneration_shield = 1
    perm.damage_marked = 5
    game.check_state_based_actions()

    assert owner.battlefield == [perm]
    assert perm.regeneration_shield == 0
    # The shield is spent, the creature taps, and — critically — the marked
    # damage clears. Leaving it marked would re-destroy the creature on the
    # very next pass of the SBA fixpoint loop.
    assert perm.tapped is True
    assert perm.damage_marked == 0


@pytest.mark.cr("704.5g", "701.19")
def test_regeneration_does_not_save_a_creature_that_cant_be_regenerated():
    perm = Permanent(card=_creature("Drudge Skeletons", 1, 1))
    game, owner = _game_with(perm)

    perm.regeneration_shield = 1
    perm.metadata["cant_be_regenerated_this_turn"] = True
    perm.damage_marked = 5
    game.check_state_based_actions()

    assert owner.battlefield == []


@pytest.mark.cr("704.5h")
def test_deathtouch_damage_is_lethal_regardless_of_amount():
    perm = Permanent(card=_creature("Serra Angel", 4, 4))
    game, owner = _game_with(perm)

    perm.damage_marked = 1
    perm.metadata["received_deathtouch"] = True
    game.check_state_based_actions()

    assert owner.battlefield == []


@pytest.mark.cr("704.5f", "704.5g")
def test_zero_toughness_is_handled_by_704_5f_not_the_lethal_damage_rule():
    """A creature at 0 toughness dies even with no damage marked, and
    regeneration cannot save it — that is 704.5f's job, and the lethal-damage
    sweep must not shadow it."""
    perm = Permanent(card=_creature("Shrunken Thing", 1, 1))
    game, owner = _game_with(perm)

    perm.toughness_bonus = -1
    perm.regeneration_shield = 1
    game.check_state_based_actions()

    assert owner.battlefield == []


@pytest.mark.cr("704.5g", "704.3")
def test_a_resolved_damage_spell_kills_without_any_manual_sweep(all_cards):
    """End-to-end through the real stack.

    The damage handlers no longer call the destruction sweep themselves — they
    mark damage and stop. This is the test that the state-based-action check
    which replaced those nine call sites actually runs on the resolution path,
    rather than the handlers having quietly been the only thing killing
    anything.
    """
    from tests.helpers import _game, _nosick

    bolt = next(card for card in all_cards if card.name == "Lightning Bolt")
    bear = next(card for card in all_cards if card.name == "Grizzly Bears")

    caster = PlayerState(name="P1", hand=[bolt], life=20)
    victim = PlayerState(name="P2", battlefield=[_nosick(Permanent(card=bear))], life=20)
    game = _game(caster, victim)

    game.cast_from_hand(0, "Lightning Bolt", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert victim.battlefield == [], "a 2/2 dealt 3 damage must die"
    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]


@pytest.mark.cr("704.5g")
def test_damage_dealt_by_a_composed_sequence_still_kills():
    """The end-to-end reason this rule moved into the SBA loop: a damage
    instruction that is one step of a sequence must still destroy its target,
    without the sequence handler knowing anything about destruction."""
    from engine.game_types import OracleExecutionContext
    from engine.handlers import EFFECT_HANDLERS
    from engine.oracle import OracleInstruction

    perm = Permanent(card=_creature("Grizzly Bears", 2, 2))
    owner = PlayerState(name="P1", battlefield=[perm], life=20)
    caster = PlayerState(name="P2", life=20)
    game = Game(players=[caster, owner])
    game.enforce_mana_costs = False

    bolt = CardDefinition(
        name="Test Bolt", mana_cost="", cmc=0.0, type_line="Instant",
        oracle_text="Test Bolt deals 2 damage to any target.",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Test Bolt", "type_line": "Instant"},
    )
    context = OracleExecutionContext(
        caster=caster, target=owner, card=bolt, target_permanent_index=0
    )
    sequence = OracleInstruction(
        "sequence", "", {"steps": (OracleInstruction("deal_damage", "", {"amount": 2}),)}
    )
    EFFECT_HANDLERS["sequence"](game, sequence, context)
    game.check_state_based_actions()

    assert owner.battlefield == []


# --- VIS w1g3: a printed narrowing of 704.5g, and 616.1e's default order ----
#
# Imports live inside the block by the per-set convention.

from engine.lethal_damage import lethal_damage_destroys
from engine.pt import add_pt_counters
from engine.shields import PREVENT_NEXT_N, Shield, add_shield, shields_of_kind
from tests.helpers import _damage_dealt


def _w1g3r_creature(name, power=2, toughness=2, oracle_text=""):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={
            "name": name, "type_line": "Creature - Test",
            "power": str(power), "toughness": str(toughness),
        },
    )


_SINGLE_SOURCE = (
    "This creature can't be destroyed by lethal damage unless lethal damage "
    "dealt by a single source is marked on it."
)


@pytest.mark.cr("704.5g")
def test_704_5g_reads_the_permanent_s_own_text_before_burying_it():
    """The rule is one sentence and a printed card may narrow it. The sweep
    therefore asks the permanent rather than only its numbers - and asks it
    through ``effective_card``, so a permanent that *copies* the clause is
    covered and one whose text was changed is not (CR 707.2, CR 612.1).

    The rule-level claim, separate from the card: nothing about this depends on
    Ogre Enforcer existing, and a second card printing the sentence needs no
    code.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    narrowed = Permanent(
        card=_w1g3r_creature("Stubborn", toughness=4, oracle_text=_SINGLE_SOURCE)
    )
    ordinary = Permanent(card=_w1g3r_creature("Plain", toughness=4))
    game.players[0].battlefield.extend([narrowed, ordinary])
    for perm in (narrowed, ordinary):
        perm.damage_marked = 4

    # No ledger entries at all: nobody has dealt this creature anything, so no
    # single source dealt it lethal damage.
    assert lethal_damage_destroys(game, narrowed) is False
    assert lethal_damage_destroys(game, ordinary) is True


@pytest.mark.cr("616.1e")
def test_616_1e_a_replacement_that_consumes_the_event_runs_before_a_shield():
    """CR 616.1e gives the affected player the choice of which effect applies
    first, and the registered ``order`` is the default a non-interactive seat
    takes. A replacement that turns damage into counters *consumes* the event,
    so applying it first leaves the shield unspent — and applying the shield
    first would spend its points on damage that was never going to be marked.

    The rule permits either; this pins which one the engine picks, because that
    choice is worth points of shield to the affected player.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    perm = Permanent(
        card=_w1g3r_creature(
            "Fungus", toughness=5,
            oracle_text=(
                "If damage would be dealt to this creature, put that many "
                "-1/-1 counters on it instead."
            ),
        )
    )
    game.players[0].battlefield.append(perm)
    add_shield(perm, Shield(kind=PREVENT_NEXT_N, amount=3, uses=None))

    assert _damage_dealt(game, perm, 2) == 0
    assert perm.damage_marked == 0
    assert shields_of_kind(perm, PREVENT_NEXT_N)[0].amount == 3, (
        "the shield was not spent on an event the replacement consumed"
    )
    assert perm.effective_toughness == 3, "and the counters arrived instead"


@pytest.mark.cr("122.1a")
def test_122_1a_the_substituted_counters_are_real_counters():
    """"Put that many -1/-1 counters on it instead" places CR 122.1a counters,
    not a P/T bonus wearing their name: the 704.5q sweep cancels them against
    +1/+1, the card face renders them, and the card's own upkeep trigger takes
    one off. A version writing the bonus alone would look identical until any
    of those three asked.
    """
    from engine.named_counters import counters_on

    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    perm = Permanent(
        card=_w1g3r_creature(
            "Fungus", toughness=5,
            oracle_text=(
                "If damage would be dealt to this creature, put that many "
                "-1/-1 counters on it instead."
            ),
        )
    )
    game.players[0].battlefield.append(perm)

    _damage_dealt(game, perm, 2)

    # Whichever store the kind lives in, the count is readable as counters.
    recorded = counters_on(perm, "-1/-1") or perm.metadata.get("minus_counters", 0)
    assert recorded == 2

    # And CR 704.5q cancels them against their opposite.
    add_pt_counters(perm, "+1/+1", 2)
    game.check_state_based_actions()
    assert perm.effective_toughness == 5
# --- end VIS w1g3 ---

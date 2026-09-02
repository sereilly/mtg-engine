"""Which of a toll's two losses is smaller — the valuation behind the middle
word of **take gifts, pay tolls, make no trades**.

A *toll* is an offer with a printed decline consequence, so both answers cost
something, and the default used to pay whenever it could however the two costs
compared. The magnitudes are `ai_valuation.toll_branch_loss`, derived from the
compiled program with the permanents resolved to the engine's own default
sacrifice picks; the prices and the comparison are
`ai_policy.toll_decline_is_smaller_loss`. A side the program cannot price
answers False and the standing policy — pay tolls — is what happens, which is
why every card here is a real pool card and no card is named in the code.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.ai_policy import toll_decline_is_smaller_loss
from engine.ai_valuation import TollLoss, toll_branch_loss
from engine.auras import attach_aura
from engine.models import Permanent
from engine.oracle import OracleInstruction


def _run_upkeep(game: Game, seat: int) -> None:
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    while game.stack:
        game.resolve_top_of_stack()


# --- paying is the smaller loss ----------------------------------------------


def test_the_ai_pays_two_life_rather_than_lose_the_enchantment(set_pool):
    """Season of the Witch: "…sacrifice this enchantment unless you pay 2
    life." Two life against a permanent: the AI pays, exactly as the old
    affordability default did — the valuation agrees with it here, and the
    point of the test is that it does so for the *comparison's* reason."""
    season = Permanent(card=set_pool("DRK")["Season of the Witch"])
    game = Game(players=[
        PlayerState(name="AI", battlefield=[season]), PlayerState(name="B"),
    ])
    game._sync_control()

    _run_upkeep(game, 0)
    game.auto_resolve_pending_optional_pays()

    assert game.is_on_battlefield(season), game.log
    assert game.players[0].life == 18


def test_the_ai_gives_an_island_rather_than_lose_elder_spawn_and_six_life(set_pool):
    """Elder Spawn: "…sacrifice an Island. If you don't, sacrifice this
    creature and it deals 6 damage to you." One land against a fat creature
    plus six damage: the deed is the smaller loss and the AI performs it."""
    spawn = Permanent(card=set_pool("LEG")["Elder Spawn"])
    island = Permanent(card=set_pool("LEA")["Island"])
    game = Game(players=[
        PlayerState(name="AI", battlefield=[spawn, island]), PlayerState(name="B"),
    ])
    game._sync_control()

    _run_upkeep(game, 0)
    game.auto_resolve_pending_optional_pays()
    game.auto_resolve_pending_choices()

    assert game.is_on_battlefield(spawn), game.log
    assert not game.is_on_battlefield(island), game.log
    assert game.players[0].life == 20


# --- taking the penalty is the smaller loss ----------------------------------


def test_the_ai_takes_curse_artifacts_damage_rather_than_sacrifice(set_pool):
    """Curse Artifact: "…this Aura deals 2 damage to that player unless they
    sacrifice that artifact." Two damage at a healthy life total is less than
    a permanent, and the old default could not see that — it performed the
    sacrifice every upkeep because the offer was takeable."""
    enchanted = Permanent(card=set_pool("LEA")["Mox Pearl"])
    aura = Permanent(card=set_pool("DRK")["Curse Artifact"])
    game = Game(players=[
        PlayerState(name="Caster", battlefield=[aura]),
        PlayerState(name="AI", battlefield=[enchanted]),
    ])
    game._sync_control()
    attach_aura(aura, enchanted)

    _run_upkeep(game, 1)
    game.auto_resolve_pending_optional_pays()

    assert game.is_on_battlefield(enchanted), game.log
    assert game.players[1].life == 18


def test_a_lethal_penalty_is_never_the_smaller_loss(set_pool):
    """The same Curse Artifact offer at 2 life: declining would be lethal, so
    the artifact goes — the comparison prices a lethal side above any
    survivable one."""
    enchanted = Permanent(card=set_pool("LEA")["Mox Pearl"])
    aura = Permanent(card=set_pool("DRK")["Curse Artifact"])
    game = Game(players=[
        PlayerState(name="Caster", battlefield=[aura]),
        PlayerState(name="AI", battlefield=[enchanted], life=2),
    ])
    game._sync_control()
    attach_aura(aura, enchanted)

    _run_upkeep(game, 1)
    game.auto_resolve_pending_optional_pays()
    game.auto_resolve_pending_choices()

    assert not game.is_on_battlefield(enchanted), game.log
    assert game.players[1].life == 2


# --- the derivation's refusals -----------------------------------------------


def test_a_branch_with_an_unpriceable_step_is_not_priced(set_pool):
    """"…counter that spell" (Mana Vortex's decline) is not a loss this
    derivation can size. None — not zero — so the caller keeps the standing
    policy instead of comparing a number to a guess."""
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])

    steps = (OracleInstruction("counter_top_stack_spell", "", {}),)
    assert toll_branch_loss(game, 0, steps) is None


def test_an_unpriceable_side_keeps_the_pay_tolls_policy(set_pool):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    entry = {
        "card_name": "probe",
        "_on_accept": (OracleInstruction("pay_life", "", {"amount": 2}),),
        "_on_decline": (OracleInstruction("counter_top_stack_spell", "", {}),),
    }
    assert toll_decline_is_smaller_loss(game, 0, entry, frozenset()) is False


def test_a_mana_priced_toll_is_left_to_the_floating_mana_policy(set_pool):
    """A toll paid in mana is not this comparison's to improve: the default
    spends only what is floating, and floating mana would otherwise empty at
    the end of the step."""
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    entry = {
        "card_name": "probe",
        "cost": {"generic": 1},
        "_on_accept": (),
        "_on_decline": (OracleInstruction("pay_life", "", {"amount": 20}),),
    }
    assert toll_decline_is_smaller_loss(game, 0, entry, frozenset()) is False


def test_toll_branch_loss_resolves_the_engines_own_sacrifice_pick(set_pool):
    """"Sacrifice an Island": the permanent handed back is the one the engine's
    deterministic default would give up, so the valuation and the execution
    cannot disagree about what is lost."""
    lea = set_pool("LEA")
    island = Permanent(card=lea["Island"])
    other = Permanent(card=lea["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="A", battlefield=[island, other]), PlayerState(name="B"),
    ])
    game._sync_control()

    steps = (
        OracleInstruction(
            "sacrifice_matching_permanent", "", {"filter": {"subtype_filter": "island"}}
        ),
    )
    loss = toll_branch_loss(game, 0, steps)

    assert loss == TollLoss(permanents=(island,))


def test_toll_branch_loss_reads_damage_only_when_it_lands_on_the_offered_seat(set_pool):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    steps = (OracleInstruction("deal_damage", "", {"amount": 2, "recipient": "caster"}),)

    assert toll_branch_loss(game, 0, steps, frozenset({"caster"})) == TollLoss(life=2)
    assert toll_branch_loss(game, 0, steps, frozenset()) is None

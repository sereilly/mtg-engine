"""A second copy of an Aura goes on a host that wears none (kg4 aivalue).

SCG Phase 5's re-check saw an AI seat put all five Pemmin's Auras it cast on
one Prodigal Sorcerer: legal, and worth little past the first — a second
"Enchanted creature has flying", a second Pacifism, a second set of one
Aura's activated abilities on one creature add little or nothing. The host
chooser (``ai_targets._choose_aura_target``) took the first legal creature on
the side the Aura helps, every time; it now ranks the legal hosts by how many
copies of this Aura each already wears (``ai_targets.copies_worn``).

Driven through the real cast: ``choose_cast_action`` proposes, the
announcement is cast (``cast_from_hand``) and the board is read. Validated
backwards: with ``copies_worn`` answering 0 (the base), every Aura of the
census lands on the first creature.
"""

from __future__ import annotations

from unittest import mock

from engine import ai_targets
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.aura_attachment import auras_attached_to
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.mixins.stack import aura_enchant_noun
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack, stable_sample


def _pool() -> dict:
    cards = load_cards(manifest_set_paths(include_measured=True))
    return {card.name: card for card in compilation_units(cards)}


def _table(pool, aura, hosts) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for name in hosts:
        game.players[0].battlefield.append(_nosick(Permanent(card=pool[name])))
    game.players[1].battlefield.append(_nosick(Permanent(card=pool["Grizzly Bears"])))
    for player in game.players:
        player.library = [pool["Island"]] * 10
    game.players[0].hand = [aura, aura]
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    game.start_priority_window(0)
    return game


def _cast_both(game, aura) -> list:
    """Cast the two copies the policy proposes, one after the other; the host
    each landed on, by permanent id."""
    hosts = []
    for _ in range(2):
        action = choose_cast_action(game, 0)
        if action is None or action.card_name != aura.name:
            return hosts
        action = tap_planned_lands(game, 0, action)
        result = game.cast_from_hand(0, aura.name, **cast_announcement(action))
        assert result.supported, result.details
        resolve_stack(game)
        hosts = [
            permanent.permanent_id for permanent in game.controlled_by(0)
            for _aura in auras_attached_to(permanent)
        ]
    return hosts


def test_two_pemmins_auras_go_on_two_creatures():
    pool = _pool()
    aura = pool["Pemmin's Aura"]
    game = _table(pool, aura, ["Prodigal Sorcerer", "Grizzly Bears"])
    hosts = _cast_both(game, aura)
    assert len(hosts) == 2, game.log[-6:]
    assert len(set(hosts)) == 2, game.log[-6:]
    sorcerer, bears = game.players[0].battlefield[:2]
    assert len(auras_attached_to(sorcerer)) == 1
    assert len(auras_attached_to(bears)) == 1


def test_with_one_creature_the_second_copy_still_has_a_host():
    """A preference, not a refusal: with one legal host the second copy
    goes on it as it always did."""
    pool = _pool()
    aura = pool["Pemmin's Aura"]
    game = _table(pool, aura, ["Prodigal Sorcerer"])
    hosts = _cast_both(game, aura)
    assert len(hosts) == 2 and len(set(hosts)) == 1, game.log[-6:]


def _own_side_auras(pool) -> list:
    """Every supported "Enchant creature" Aura the cast chooser puts on its
    caster's own creature (both manifest roles)."""
    found = []
    for name, card in sorted(pool.items()):
        if "Aura" not in (card.type_line or "") or aura_enchant_noun(card) != "creature":
            continue
        if not compile_card_oracle(card).supported or ai_targets._aura_harms_its_host(card):
            continue
        found.append(card)
    return found


def _census(pool, every: int = 6) -> dict:
    found = {"examined": [], "stacked": [], "spread": []}
    for aura in _own_side_auras(pool):
        if not stable_sample(aura.name, every):
            continue
        game = _table(pool, aura, ["Grizzly Bears", "Grizzly Bears"])
        hosts = _cast_both(game, aura)
        if len(hosts) != 2:
            continue
        found["examined"].append(aura.name)
        found["spread" if len(set(hosts)) == 2 else "stacked"].append(aura.name)
    return found


def test_no_beneficial_aura_is_stacked_while_a_bare_host_is_legal():
    found = _census(_pool())
    assert found["stacked"] == [], found
    assert len(found["examined"]) >= 8, found


def test_without_the_ranking_every_copy_goes_on_the_first_creature():
    """Backwards: ``copies_worn`` answering 0, as on 313bd09d — every copy on
    the first creature, unless the first copy made it a creature the second
    cannot target ("Enchanted creature has shroud", Robe of Mirrors)."""
    with mock.patch.object(ai_targets, "copies_worn", lambda host, card: 0):
        found = _census(_pool())
    assert len(found["stacked"]) >= 8, found
    assert len(found["spread"]) <= 2, found


def test_an_aura_returned_without_a_cast_takes_the_bare_host_too():
    """CR 303.4f's host choice (Replenish, Cleansing Meditation) asks the same
    ranking after the side: ``choose_returning_aura_host``."""
    from engine.aura_attachment import attach_aura

    pool = _pool()
    aura = pool["Pemmin's Aura"]
    game = _table(pool, aura, ["Prodigal Sorcerer", "Grizzly Bears"])
    sorcerer, bears = game.players[0].battlefield[:2]
    worn = Permanent(card=aura)
    game.players[0].battlefield.append(worn)
    attach_aura(worn, sorcerer)
    game._sync_control()
    assert ai_targets.choose_returning_aura_host(game, 0, aura, [sorcerer, bears]) is bears
    assert ai_targets.choose_returning_aura_host(game, 0, aura, [sorcerer]) is sorcerer

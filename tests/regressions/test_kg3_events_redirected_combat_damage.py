"""Combat damage a CR 614.9 redirect moves is still combat damage.

Wall of Souls' ruling (2004-10-04): "Redirected damage is still combat damage";
Pariah's (2024-04-12): "If you would be dealt combat damage, the damage dealt to
the enchanted creature instead is still combat damage." Every redirect hands
its moved damage to ``replacements.redirects.deal_redirected_damage``; the
player half called ``Game._deal_damage_to_player``, which hard-coded
``combat=False``, and three of the six hand-offs passed no flag at all. So a
redirected attacker's damage reaching a player woke no "whenever … deals
combat damage to a player" trigger and passed through "prevent all combat
damage". And the creature half skipped lifelink for combat damage — the combat
damage step tallies its own, and never saw a chunk a redirect had moved — so
an unblocked lifelinker whose damage a Veteran Bodyguard took gained nothing.

Validated backwards: on 753c241a the Specter's controller discards nothing,
the Fog lets the 2 through, the lifelinker gains 0, and three hand-offs pass
no ``combat``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}
_ENGINE = Path(__file__).resolve().parents[2] / "engine"


def _put(game: Game, seat: int, card) -> Permanent:
    permanent = Permanent(card=_POOL[card] if isinstance(card, str) else card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table() -> Game:
    game = Game(players=[
        PlayerState(f"P{seat}", library=[_POOL["Island"]] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


def _attack_unblocked(game: Game, attacker: Permanent) -> None:
    game._sync_control()
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(attacker)], defending_player_index=1,
    )[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {})[0]


def _deal(game: Game) -> None:
    game._set_phase_and_step("combat", "combat_damage")
    assert game.resolve_all_combat_damage(0)[0]


def _mirror_strike(game: Game, attacker: Permanent) -> None:
    """"All combat damage that would be dealt to you this turn by target
    unblocked creature is dealt to its controller instead." """
    game.players[1].hand.append(_POOL["Mirror Strike"])
    assert game.cast_from_hand(
        1, "Mirror Strike", target_permanent_ids=[attacker.permanent_id],
    ).supported
    resolve_stack(game)


def test_a_redirected_attackers_damage_to_a_player_is_combat_damage():
    """Mirror Strike sends Blazing Specter's damage to its own controller:
    "whenever this creature deals combat damage to a player, that player
    discards a card" — the player is its controller."""
    game = _table()
    specter = _put(game, 0, "Blazing Specter")
    game.players[0].hand.extend([_POOL["Island"], _POOL["Island"]])
    _attack_unblocked(game, specter)
    _mirror_strike(game, specter)
    _deal(game)
    assert game.players[0].life == 18 and game.players[1].life == 20
    assert any(item.source_permanent is specter for item in game.stack), game.log
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert len(game.players[0].hand) == 1, game.log


def test_prevent_all_combat_damage_stops_a_redirected_chunk():
    """Fog ("Prevent all combat damage that would be dealt this turn") and
    Mirror Strike: the redirect moves the chunk first (the default order),
    and the moved chunk — still combat damage — is Fog's to prevent."""
    game = _table()
    attacker = _put(game, 0, CardDefinition(
        name="Raider", mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Raider", "type_line": "Creature — Test",
             "power": "2", "toughness": "2"},
    ))
    _attack_unblocked(game, attacker)
    _mirror_strike(game, attacker)
    game.players[1].hand.append(_POOL["Fog"])
    assert game.cast_from_hand(1, "Fog").supported
    resolve_stack(game)
    _deal(game)
    assert game.players[0].life == 20, game.log
    assert game.players[1].life == 20, game.log


def test_a_lifelinker_whose_damage_a_bodyguard_takes_still_gains():
    """Veteran Bodyguard: "As long as this creature is untapped, all damage
    that would be dealt to you by unblocked creatures is dealt to this
    creature instead." An unblocked 2/2 with lifelink: the Bodyguard takes 2
    and the lifelinker's controller gains 2, once (CR 702.15b)."""
    game = _table()
    lifelinker = _put(game, 0, CardDefinition(
        name="Lifelinker", mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="Lifelink", colors=(), color_identity=(), keywords=("Lifelink",),
        produced_mana=(),
        raw={"name": "Lifelinker", "type_line": "Creature — Test",
             "power": "2", "toughness": "2"},
    ))
    bodyguard = _put(game, 1, "Veteran Bodyguard")
    _attack_unblocked(game, lifelinker)
    _deal(game)
    assert bodyguard.damage_marked == 2
    assert game.players[1].life == 20
    assert game.players[0].life == 22, game.log
    assert sum("gained 2 life from lifelink" in line for line in game.log) == 1


def test_every_redirect_hand_off_says_whether_it_is_combat_damage():
    """The static half: each call of the one hand-off passes ``combat=`` — a
    required keyword now, so a call that forgets it fails as soon as it runs;
    this finds it before any card does."""
    calls, silent = [], []
    for path in sorted(_ENGINE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name != "deal_redirected_damage":
                continue
            where = f"{path.relative_to(_ENGINE).as_posix()}:{node.lineno}"
            calls.append(where)
            if "combat" not in {keyword.arg for keyword in node.keywords}:
                silent.append(where)
    assert len(calls) >= 6, calls
    assert silent == [], silent

"""An Aura whose abilities its controller pays to use goes on that player's own
creature, and is used only for that player (SCG Phase 5, smoke game 1).

Seen, the AI playing blue-white against a person playing red-green:

1. The AI cast Pemmin's Aura ("Enchant creature / {U}: Untap enchanted
   creature. / {U}: Enchanted creature gains flying until end of turn. / {U}:
   … gains shroud … / {1}: … gets +1/-1 or -1/+1 until end of turn.") on the
   **person's** Krosan Warchief.
2. It then paid {U} in its main phase to untap the person's creature — the
   person's attacker, which then blocked — and again in its declare-attackers
   step.

Two readings were wrong. The cast's: ``ai_targets._aura_harms_its_host``
matched its marker "tap enchanted" inside "Untap enchanted creature", so the
Aura read as one that works against its host. The activation's: the own-board
chooser scored "Untap enchanted creature" flat wherever the Aura was, with no
question about whose creature it lands on (``ai_target_sides.host_effect_side``
now answers that, and ``ai_abilities._host_refusal`` asks it).
"""
from __future__ import annotations

from engine.ai_abilities import choose_activation_action
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.aura_attachment import attach_aura
from engine.game import Game
from engine.handlers._targets import attached_host
from engine.models import Permanent, PlayerState
from tests.helpers import _nosick, client, resolve_stack


def _table(cards, own, other=(), hand=()) -> Game:
    game = Game(players=[PlayerState(name="AI"), PlayerState(name="Opp")])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, names in ((0, own), (1, other)):
        for name in names:
            game.players[seat].battlefield.append(_nosick(Permanent(card=cards[name])))
        game.players[seat].library = [cards["Island"]] * 10
    game.players[0].hand = [cards[name] for name in hand]
    game._recompute_continuous_effects()
    return game


def _main_phase(game: Game) -> Game:
    game.start_turn(0)
    for _ in range(6):
        if game.current_turn_phase == "precombat_main":
            break
        game._close_current_priority_step()
    return game


def _on(game: Game, seat: int, name: str) -> Permanent:
    return next(p for p in game.players[seat].battlefield if p.card.name == name)


def _cards(set_pool) -> dict:
    cards = dict(set_pool("LEA"))
    cards.update(set_pool("SCG"))
    cards["Grizzly Bears"] = set_pool("LEA")["Grizzly Bears"]
    return cards


def test_pemmins_aura_is_cast_on_the_ais_own_creature(set_pool):
    """A creature on each board: the Aura goes on the AI's own, through the
    cast the simulator and the web AI make (paid from Islands), and resolves
    onto it."""
    cards = _cards(set_pool)
    game = _main_phase(_table(
        cards, ["Grizzly Bears", "Island", "Island", "Island"], ["Krosan Warchief"],
        hand=["Pemmin's Aura"],
    ))
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Pemmin's Aura"
    assert action.target_player_index == 0, action

    action = tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(0, "Pemmin's Aura", **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    host = attached_host(game, _on(game, 0, "Pemmin's Aura"))
    assert host is not None and host.card.name == "Grizzly Bears"
    assert game.controller_index_of(host) == 0


def test_the_ai_never_untaps_a_persons_creature_with_its_own_aura(set_pool):
    """The board smoke game 1 reached: the AI's Pemmin's Aura on the person's
    tapped Krosan Warchief, two Islands open. Not proposed in the main phase,
    nor in the declare-attackers step the web AI is asked in again."""
    cards = _cards(set_pool)
    game = _table(cards, ["Pemmin's Aura", "Grizzly Bears", "Island", "Island"],
                  ["Krosan Warchief"])
    attach_aura(_on(game, 0, "Pemmin's Aura"), _on(game, 1, "Krosan Warchief"))
    game._recompute_continuous_effects()
    _main_phase(game)
    _on(game, 1, "Krosan Warchief").tapped = True
    assert choose_activation_action(game, 0) is None

    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    ok, why = game.declare_attackers(0, [1], defending_player_index=1)
    assert ok, why
    assert game.current_step == "declare_attackers"
    assert choose_activation_action(game, 0) is None


def test_the_untap_is_spent_on_the_ais_own_tapped_creature_only(set_pool):
    """The same Aura on the AI's own creature: untapping it when it is tapped
    is the card working; untapping it when it is untapped moves nothing, and
    is not proposed."""
    cards = _cards(set_pool)
    game = _table(cards, ["Pemmin's Aura", "Grizzly Bears", "Island", "Island"],
                  ["Krosan Warchief"])
    attach_aura(_on(game, 0, "Pemmin's Aura"), _on(game, 0, "Grizzly Bears"))
    game._recompute_continuous_effects()
    _main_phase(game)
    assert choose_activation_action(game, 0) is None

    _on(game, 0, "Grizzly Bears").tapped = True
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Pemmin's Aura"
    action = tap_planned_lands(game, 0, action)
    result = game.activate_permanent_ability(
        0, action.permanent_name, permanent_index=action.permanent_index,
        target_player_index=action.target_player_index,
    )
    assert result.supported, result.details
    assert not _on(game, 0, "Grizzly Bears").tapped


def test_a_shrink_on_the_host_is_used_on_a_persons_creature_and_not_the_ais(set_pool):
    """The side by the effect's sign, not its family: Manacles of Decay's
    "{B}: Enchanted creature gets -1/-1 until end of turn." is the AI's to use
    on a person's creature, and never on its own (the ``pump`` category read
    every host pump as a gift)."""
    cards = dict(set_pool("APC"))
    cards.update({"Grizzly Bears": set_pool("LEA")["Grizzly Bears"],
                  "Island": set_pool("LEA")["Island"], "Swamp": set_pool("LEA")["Swamp"]})
    for host_seat, proposed in ((1, True), (0, False)):
        game = _table(cards, ["Manacles of Decay", "Swamp", "Swamp", "Grizzly Bears"],
                      ["Grizzly Bears"])
        game.enforce_mana_costs = False
        attach_aura(_on(game, 0, "Manacles of Decay"), _on(game, host_seat, "Grizzly Bears"))
        game._recompute_continuous_effects()
        _main_phase(game)
        action = choose_activation_action(game, 0)
        found = action is not None and action.permanent_name == "Manacles of Decay"
        assert found is proposed, (host_seat, action)


# --- the web AI seat, driven as the browser drives it -------------------------

_LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body) -> int:
    return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body}).status_code


def _put(game, cards, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=cards[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _to_the_humans_turn(sid: str) -> None:
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0:
            return
        assert _act(sid, action="pass_priority" if state["priority_player"] == 0 else "ai_step") == 200
    raise AssertionError("never reached the human's turn")


def _end_the_humans_turn(sid: str) -> None:
    for _ in range(60):
        state = _state(sid)
        if state["current_turn"] != 0:
            return
        if state["current_step"] == "declare_attackers" and state["priority_player"] is None:
            code = _act(sid, action="declare_attackers", attacker_ids=[], target_seat=1)
        else:
            code = _act(sid, action="pass_priority")
            if code != 200:
                code = _act(sid, action="next_phase")
        assert code == 200
    raise AssertionError("the human's turn never ended")


def _play_the_ais_turn(sid: str) -> None:
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0 or state["status"] == "finished":
            return
        assert _act(sid, action="pass_priority" if state["priority_player"] == 0 else "ai_step") == 200
    raise AssertionError("the AI's turn never ended")


def test_the_web_ai_does_not_untap_a_persons_creature_for_them(set_pool):
    """Human vs AI through the API: the AI's Pemmin's Aura on the person's
    Krosan Warchief, tapped from its attack, and three Islands open. The AI's
    whole turn goes by with the Warchief left tapped."""
    from web.app import store

    cards = _cards(set_pool)
    created = client.post("/api/sessions", json={
        "mode": "human_vs_ai", "host_deck_cards": _LANDS, "guest_deck_cards": _LANDS, "seed": 11,
    }).json()
    sid = created["session_id"]
    game = store.get(sid).game
    game.enforce_mana_costs = True
    _to_the_humans_turn(sid)
    human, ai = game.players
    human.battlefield, ai.battlefield, human.hand, ai.hand = [], [], [], []
    (warchief,) = _put(game, cards, 0, ["Krosan Warchief"])
    aura, *_ = _put(game, cards, 1, ["Pemmin's Aura", "Island", "Island", "Island"])
    attach_aura(aura, warchief)
    game._recompute_continuous_effects()
    human.library = [cards["Island"]] * 10
    ai.library = [cards["Island"]] * 10

    _end_the_humans_turn(sid)
    warchief.tapped = True
    _play_the_ais_turn(sid)

    assert not any("via Pemmin's Aura" in line for line in game.log), game.log[-30:]

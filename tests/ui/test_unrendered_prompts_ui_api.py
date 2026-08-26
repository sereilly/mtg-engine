"""Web-API round trips for the five prompts the browser client used to lack.

Each one arms the prompt the way the card does, reads it back through the
state payload the client renders from (checking the fields the new renderers
read), answers it through the action the client sends, and checks the effect
landed. The renderers themselves are exercised in the running app; these pin
the wire they depend on.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick
from web.app import app, store

client = TestClient(app)


def _session():
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human",
            "host_name": "Host",
            "guest_name": "Guest",
            "host_colors": 2,
            "guest_colors": 2,
            "seed": 777,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = False
    session.current_turn = 0
    game.active_player_index = 0
    game.current_phase = "main"
    # What the action preamble (web/actions.py) sets before every action: these
    # tests arm prompts on the engine directly, before any action has run, and
    # a ``default_at_arm`` kind (mode_choice) would otherwise answer itself.
    game.interactive_seats = {0, 1}
    # The session's opening-hand draws are still unannounced on the per-turn
    # record; a turn boundary clears them in play, so clear them here before a
    # "whenever you draw" permanent is put onto the battlefield.
    for player in game.players:
        player.cards_drawn_this_turn = []
    game.draws_announced_this_turn = {}
    return sid, session, game


def _state(sid: str, seat: int = 0) -> dict:
    return client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()


def _act(sid: str, **body):
    return client.post(f"/api/sessions/{sid}/action", json=body)


# --- mode_choice: Trufflesnout ----------------------------------------------

def test_mode_choice_round_trip(set_pool):
    pool = set_pool("M21")
    sid, session, game = _session()
    p1 = game.players[0]
    p1.hand = [pool["Trufflesnout"]]
    life_before = p1.life

    result = game.cast_from_hand(0, "Trufflesnout")
    assert result.supported, result.details
    game._settle()

    prompt = _state(sid)["mode_choice"]
    assert prompt is not None
    assert prompt["player_seat"] == 0
    assert prompt["card_name"] == "Trufflesnout"
    assert [m["label"] for m in prompt["modes"]] == [
        "Put a +1/+1 counter on this creature", "You gain 4 life",
    ]
    assert _state(sid, seat=1)["mode_choice"] is None

    refused = _act(sid, seat=0, action="pass_priority")
    assert refused.status_code == 400

    answered = _act(sid, seat=0, action="mode_choice_confirm", hand_index=1)
    assert answered.status_code == 200, answered.json()
    assert p1.life == life_before + 4
    assert _state(sid)["mode_choice"] is None


# --- name_and_strip: Necromentia ---------------------------------------------

def test_name_and_strip_round_trip(set_pool):
    pool = set_pool("M21")
    sid, session, game = _session()
    p1, p2 = game.players
    p1.hand = [pool["Necromentia"]]
    p2.hand = [pool["Shock"], pool["Island"], pool["Volcanic Salvo"]]
    p2.graveyard = [pool["Shock"]]
    p2.library = [pool["Shock"], pool["Forest"], pool["Baneslayer Angel"]]

    result = game.cast_from_hand(0, "Necromentia", target_player_index=1)
    assert result.supported, result.details
    game._settle()

    prompt = _state(sid)["name_and_strip"]
    assert prompt is not None
    assert prompt["caster_seat"] == 0
    assert prompt["card_name"] == "Necromentia"
    assert prompt["target_seat"] == 1
    assert prompt["suggestions"] == ["Shock"], "the graveyard is public"
    assert "Island" not in prompt["suggestions"], "a basic land can't be named"
    # The card searches the hand and the library too, but the chooser may not
    # look at either: nothing seen only there is offered, and the AI's default
    # (the commonest card over every searched zone) is not forwarded.
    assert "Volcanic Salvo" not in prompt["suggestions"]
    assert "Baneslayer Angel" not in prompt["suggestions"]
    assert "default_name" not in prompt

    basic = _act(sid, seat=0, action="name_and_strip_confirm", card_name="Island")
    assert basic.status_code == 400

    answered = _act(sid, seat=0, action="name_and_strip_confirm", card_name="Shock")
    assert answered.status_code == 200, answered.json()
    assert not any(c.name == "Shock" for c in p2.hand + p2.graveyard + p2.library)
    assert _state(sid)["name_and_strip"] is None


# --- reflexive_target: Tolarian Kraken --------------------------------------

def test_reflexive_target_round_trip(set_pool):
    pool = set_pool("M21")
    sid, session, game = _session()
    p1, p2 = game.players
    kraken = Permanent(card=pool["Tolarian Kraken"])
    victim = Permanent(card=pool["Gale Swooper"])
    p1.battlefield = [kraken]
    p1.library = [pool["Island"], pool["Shock"]]
    p2.battlefield = [victim]
    game._sync_control()
    game.enforce_mana_costs = True
    p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 2, "generic": 0}

    game._draw_with_replacements(p1, 1)
    game._settle()
    assert _state(sid)["optional_pay"] is not None, "the 'you may pay {1}' comes first"
    paid = _act(sid, seat=0, action="resolve_optional_pay", accept=True)
    assert paid.status_code == 200, paid.json()

    prompt = _state(sid)["reflexive_target"]
    assert prompt is not None
    assert prompt["player_seat"] == 0
    assert prompt["card_name"] == "Tolarian Kraken"
    names = {c["name"] for c in prompt["candidates"]}
    assert names == {"Tolarian Kraken", "Gale Swooper"}
    for candidate in prompt["candidates"]:
        assert candidate["id"] is not None
        assert candidate["seat"] in (0, 1)
        assert isinstance(candidate["index"], int)
    assert _state(sid, seat=1)["reflexive_target"] is None

    victim_id = next(c["id"] for c in prompt["candidates"] if c["name"] == "Gale Swooper")
    answered = _act(sid, seat=0, action="reflexive_target_confirm", target_permanent_id=victim_id)
    assert answered.status_code == 200, answered.json()
    # "you may tap or untap": the tap-or-untap is its own optional prompt.
    if _state(sid)["optional_pay"] is not None:
        _act(sid, seat=0, action="resolve_optional_pay", accept=True)
    assert victim.tapped
    assert _state(sid)["reflexive_target"] is None


# --- tap_any_number: Siege Striker -------------------------------------------

def test_tap_any_number_round_trip(set_pool):
    pool = set_pool("M21")
    sid, session, game = _session()
    p1 = game.players[0]
    striker = _nosick(Permanent(card=pool["Siege Striker"]))
    striker.attacking = True
    idle = Permanent(card=pool["Alpine Watchdog"])
    already = Permanent(card=pool["Alpine Watchdog"])
    already.tapped = True
    p1.battlefield = [striker, idle, already]
    game._sync_control()

    trigger = compile_card_oracle(pool["Siege Striker"]).triggered_abilities[0]
    game._execute_oracle_instruction(
        trigger.instruction,
        OracleExecutionContext(caster=p1, target=p1, card=pool["Siege Striker"], source_permanent=striker),
    )

    prompt = _state(sid)["tap_any_number"]
    assert prompt is not None
    assert prompt["player_seat"] == 0
    assert prompt["card_name"] == "Siege Striker"
    assert prompt["power"] == 1 and prompt["toughness"] == 1
    offered = {c["name"]: c for c in prompt["candidates"]}
    assert set(offered) == {"Siege Striker", "Alpine Watchdog"}
    assert len(prompt["candidates"]) == 2, "the already-tapped Watchdog is not offered"
    for candidate in prompt["candidates"]:
        assert candidate["seat"] == 0 and candidate["id"] is not None

    # A stale id is a 404 at the top of web/actions.py, never a fall back.
    stale = _act(sid, seat=0, action="tap_any_number_confirm", target_permanent_ids=[999999])
    assert stale.status_code == 404

    idle_id = game.permanent_id_of(idle)
    answered = _act(sid, seat=0, action="tap_any_number_confirm", target_permanent_ids=[idle_id])
    assert answered.status_code == 200, answered.json()
    assert idle.tapped
    assert striker.effective_power == 2, "1/1 base, +1/+1 for the one creature tapped"
    assert _state(sid)["tap_any_number"] is None


def test_tap_any_number_accepts_none(set_pool):
    """"You **may** tap any number": the client's "Tap None" sends an empty list."""
    pool = set_pool("M21")
    sid, session, game = _session()
    p1 = game.players[0]
    striker = _nosick(Permanent(card=pool["Siege Striker"]))
    p1.battlefield = [striker, Permanent(card=pool["Alpine Watchdog"])]
    game._sync_control()
    trigger = compile_card_oracle(pool["Siege Striker"]).triggered_abilities[0]
    game._execute_oracle_instruction(
        trigger.instruction,
        OracleExecutionContext(caster=p1, target=p1, card=pool["Siege Striker"], source_permanent=striker),
    )
    assert _state(sid)["tap_any_number"] is not None

    answered = _act(sid, seat=0, action="tap_any_number_confirm", target_permanent_ids=[])
    assert answered.status_code == 200, answered.json()
    assert not any(p.tapped for p in p1.battlefield)
    assert _state(sid)["tap_any_number"] is None


# --- revealed_hand_pick: Duress ----------------------------------------------

def test_revealed_hand_pick_round_trip(set_pool):
    pool = set_pool("M21")
    sid, session, game = _session()
    p1, p2 = game.players
    p1.hand = [pool["Duress"]]
    p1.library = [pool["Swamp"]] * 4
    p2.hand = [pool["Alpine Watchdog"], pool["Shock"], pool["Island"], pool["Volcanic Salvo"]]

    result = game.cast_from_hand(0, "Duress", target_player_index=1)
    assert result.supported, result.details
    game._settle()

    prompt = _state(sid)["revealed_hand_pick"]
    assert prompt is not None
    assert prompt["player_seat"] == 0, "the caster chooses"
    assert prompt["card_name"] == "Duress"
    assert prompt["victim_seat"] == 1
    assert prompt["victim_name"] == p2.name
    assert [c["name"] for c in prompt["cards"]] == [
        "Alpine Watchdog", "Shock", "Island", "Volcanic Salvo",
    ], "the whole revealed hand is shown"
    assert prompt["legal_indices"] == [1, 3], "only the noncreature, nonland cards are pickable"
    assert _state(sid, seat=1)["revealed_hand_pick"] is None

    illegal = _act(sid, seat=0, action="revealed_hand_pick_confirm", hand_index=0)
    assert illegal.status_code == 400

    answered = _act(sid, seat=0, action="revealed_hand_pick_confirm", hand_index=3)
    assert answered.status_code == 200, answered.json()
    assert [c.name for c in p2.hand] == ["Alpine Watchdog", "Shock", "Island"]
    assert any(c.name == "Volcanic Salvo" for c in p2.graveyard)
    assert _state(sid)["revealed_hand_pick"] is None


# --- name_then_reveal_top: Petra Sphinx --------------------------------------

def test_name_then_reveal_top_round_trip(set_pool):
    """The prompt belongs to the **targeted** player, not the activating one —
    the card asks them to guess at their own library. So the seat that sees it
    and the seat that answers it are seat 1 while seat 0 activated."""
    leg = set_pool("LEG")
    m21 = set_pool("M21")
    sid, session, game = _session()
    p1, p2 = game.players
    sphinx = Permanent(card=leg["Petra Sphinx"])
    p1.battlefield = [_nosick(sphinx)]
    p2.hand = []
    p2.graveyard = []
    p2.library = [m21["Shock"], m21["Island"]]
    game._sync_control()

    result = game.activate_permanent_ability(0, "Petra Sphinx", target_player_index=1)
    assert result.supported, result.details
    game._settle()

    prompt = _state(sid, seat=1)["name_then_reveal_top"]
    assert prompt is not None
    assert prompt["player_seat"] == 1
    assert prompt["card_name"] == "Petra Sphinx"
    assert prompt["match_zone"] == "hand"
    assert prompt["miss_zone"] == "graveyard"
    assert _state(sid, seat=0)["name_then_reveal_top"] is None

    wrong_seat = _act(sid, seat=0, action="name_then_reveal_top_confirm", card_name="Shock")
    assert wrong_seat.status_code == 400

    answered = _act(sid, seat=1, action="name_then_reveal_top_confirm", card_name="Shock")
    assert answered.status_code == 200, answered.json()
    assert [c.name for c in p2.hand] == ["Shock"]
    assert p2.graveyard == []
    assert _state(sid, seat=1)["name_then_reveal_top"] is None


# --- choose_cards_in_hand: Sylvan Library (round 34) ------------------------

def test_choose_cards_in_hand_round_trip(set_pool):
    """The whole of Sylvan Library over the wire: the offer, the hand pick the
    browser renders as a toggle list, and one mode per chosen card.

    The pick is what the round-trip is for — it is the one prompt this round
    added, and it is answered with a *set* in a single action.
    """
    pool = set_pool("LEG")
    lea = set_pool("LEA")
    sid, session, game = _session()
    p1 = game.players[0]
    p1.library = [lea[name] for name in ("Forest", "Mountain", "Island", "Swamp")]
    p1.hand = []
    p1.life = 20
    library = Permanent(card=pool["Sylvan Library"])
    p1.battlefield.append(library)

    game.turn = 3
    game.resolve_draw_step(0)
    assert _act(sid, seat=0, action="resolve_optional_pay",
                card_name="Sylvan Library", accept=True).status_code == 200

    prompt = _state(sid, 0)["choose_cards_in_hand"]
    assert prompt["count"] == 2
    assert [c["name"] for c in prompt["choices"]] == ["Forest", "Mountain", "Island"]

    assert _act(sid, seat=0, action="choose_cards_in_hand_confirm",
                hand_indices=[1, 2]).status_code == 200
    # The prompt is answered and the ability has moved on to its per-card
    # decision — the shape the client's dispatch relies on.
    assert _state(sid, 0).get("choose_cards_in_hand") is None
    assert [m["label"] for m in _state(sid, 0)["mode_choice"]["modes"]] == [
        "pay 4 life", "put the card on top of your library",
    ]

    for _ in range(2):
        assert _act(sid, seat=0, action="mode_choice_confirm",
                    hand_index=0).status_code == 200

    assert p1.life == 12
    assert [c.name for c in p1.hand] == ["Forest", "Mountain", "Island"]


def test_choose_cards_in_hand_refuses_a_pick_it_never_offered(set_pool):
    """A client sending a hand slot outside the candidate rule is refused, not
    obeyed: the list offered and the list an answer is checked against are one
    rule, so a wider answer has nowhere to land."""
    pool = set_pool("LEG")
    lea = set_pool("LEA")
    sid, session, game = _session()
    p1 = game.players[0]
    p1.library = [lea[name] for name in ("Forest", "Mountain", "Island", "Swamp")]
    # A card that was in hand before the turn began: eligible by type, and
    # ineligible because the phrase says "drawn this turn".
    p1.hand = [lea["Black Lotus"]]
    p1.battlefield.append(Permanent(card=pool["Sylvan Library"]))

    game.turn = 3
    game.resolve_draw_step(0)
    _act(sid, seat=0, action="resolve_optional_pay",
         card_name="Sylvan Library", accept=True)

    prompt = _state(sid, 0)["choose_cards_in_hand"]
    assert 0 not in [c["hand_index"] for c in prompt["choices"]], "not drawn this turn"

    refused = _act(sid, seat=0, action="choose_cards_in_hand_confirm",
                   hand_indices=[0, 1])
    assert refused.status_code == 400
    assert _state(sid, 0)["choose_cards_in_hand"] is not None, "still owed"

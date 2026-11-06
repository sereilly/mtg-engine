"""Who holds priority in the combat steps of a web AI's turn (kg4 `webprio`).

CR 508.1 / 509.1 make each declaration the step's turn-based action, taken
before anybody receives priority (CR 117.3a); CR 508.2 / 509.2 then give the
**active** player priority first, and it passes round from there (CR 117.3d).
A ``human_vs_ai`` game on the web broke all three halves on the AI's turn:

* **The AI's own CR 508.2 priority was never answered.** After the web AI
  declared attackers, ``game_flow._advance_phase`` left the step straight
  through the engine's window, and the phase rail's hold
  (``seats._hold_priority_for_human``) passed the AI's priority on unasked —
  so an attacker's ability that pays only before the blocks (shedding its
  own flying so a Lure makes the Bears block it) was never used, with or
  without the person holding the step. It was answered only when an attack
  trigger happened to go round the table first.
* **The person was handed priority before declaring blocks.** With the rail
  flagging ``declare_blockers``, the hold made the AI pass in a step whose
  declaration was still owed, and once the person passed too, the AI held
  priority with the blocks still to come.
* **The AI's CR 509.2 priority was never answered when the person had no
  legal block**: the engine declares that defender's nothing and leaves the
  step in one call.

**The census is every combination of the rail's two combat stops, an attack
trigger or none, and a person with a legal block or none**, driven as the
browser drives the game (the person passes when served priority, declares no
blocks when the blocks are theirs, and otherwise asks for an ``ai_step``),
with a spy on the web AI's one answer to priority
(``game_flow.act_at_priority``). Each row asks the four questions above of
the states the person was served and of the moments the AI was asked.
"""

from __future__ import annotations

import itertools

import pytest

import web.game_flow as game_flow
from engine.aura_attachment import attach_aura
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import client, seat_plays_first
from web.app import store

_CARDS = {card.name: card for card in load_catalog()}
_LANDS = [{"name": name, "count": 8} for name in ("Plains", "Island", "Swamp", "Mountain", "Forest")]


def _session(*, force_attack: bool = True):
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_deck_cards": _LANDS, "guest_deck_cards": _LANDS, "seed": 11},
    ).json()
    sid = created["session_id"]
    session = seat_plays_first(sid, 1)
    session.game.enforce_mana_costs = True
    session.force_ai_attack_all = force_attack
    for player in session.game.players:
        player.battlefield = []
        player.hand = []
        player.graveyard = []
        player.library = [_CARDS["Plains"]] * 12
    return sid, session


def _put(game, seat: int, names) -> list:
    placed = []
    for name in names:
        permanent = Permanent(card=_CARDS[name])
        game._put_permanent_onto_battlefield(seat, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    return placed


def _state(sid: str) -> dict:
    return client.get(f"/api/sessions/{sid}/state?seat=0").json()


def _act(sid: str, **body) -> dict:
    response = client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})
    assert response.status_code == 200, (body, response.json())
    return response.json()


@pytest.fixture
def asked(monkeypatch):
    """Every moment the web AI was asked for its answer to priority:
    ``(step, seat, attackers locked, blockers locked, stack empty)``."""
    moments: list[tuple] = []
    answer = game_flow.act_at_priority

    def spy(game, seat, **kwargs):
        moments.append((
            game.current_step, seat, game.combat_attackers_locked,
            game.combat_blockers_locked, not game.stack,
        ))
        return answer(game, seat, **kwargs)

    monkeypatch.setattr(game_flow, "act_at_priority", spy)
    return moments


def _play_the_ais_turn(sid: str, stops: list[str], *, on_combat=None, blocks=None) -> list[tuple]:
    """The AI's turn as the browser plays it, every action carrying the
    person's rail (``stop_steps``). Returns each state served in combat:
    ``(step, priority player, attackers locked, blockers locked, stack size)``.
    *on_combat* runs once, as combat begins; *blocks* names the person's
    declaration (``blocker_pairs_by_id``, or a function of the game that
    returns it), none by default."""
    game = store.get(sid).game
    served = []
    combat_seen = False
    for _ in range(80):
        state = _state(sid)
        if state["current_turn"] == 0 or state["status"] == "finished":
            return served
        combat = state.get("combat") or {}
        if state["current_turn_phase"] == "combat":
            if not combat_seen and on_combat is not None:
                on_combat(game)
            combat_seen = True
            served.append((
                state["current_step"], state["priority_player"],
                bool(combat.get("attackers_locked")), bool(combat.get("blockers_locked")),
                len(state["stack"]),
            ))
        if state["priority_player"] == 0:
            _act(sid, action="pass_priority", stop_steps=stops)
        elif (
            state["current_step"] == "declare_blockers"
            and combat.get("attackers")
            and not combat.get("blockers_locked")
            and combat.get("defending_player_index") == 0
        ):
            pairs = blocks(game) if callable(blocks) else blocks
            _act(
                sid, action="declare_blockers", target_seat=0,
                blocker_pairs_by_id=pairs or {}, stop_steps=stops,
            )
        else:
            _act(sid, action="ai_step", stop_steps=stops)
    raise AssertionError(f"the AI's turn never ended: {game.log[-20:]}")


_STOPS = (
    [], ["declare_attackers"], ["declare_blockers"], ["declare_attackers", "declare_blockers"],
    # The attack is then declared by the `ai_step` that follows the person's
    # pass, rather than inside the request that left the AI's main phase.
    ["beginning_of_combat"],
)
_ROWS = list(itertools.product(_STOPS, (False, True), (False, True)))


@pytest.mark.cr("508.1", "508.2", "509.1", "509.2", "117.3a")
@pytest.mark.parametrize(("stops", "attack_trigger", "person_can_block"), _ROWS)
def test_each_combat_step_gives_priority_after_its_declaration_and_to_the_active_ai_first(
    asked, stops, attack_trigger, person_can_block,
):
    """The AI attacks (the Debug Menu's attack-everything, so the attack is
    certain) with Grizzly Bears, and with Charging Paladin where the row has
    an attack trigger; the person has a Wall of Wood to block with, or no
    creature. Four questions of every row."""
    sid, session = _session()
    game = session.game
    _put(game, 1, ["Grizzly Bears"] + (["Charging Paladin"] if attack_trigger else []))
    if person_can_block:
        _put(game, 0, ["Wall of Wood"])
    served = _play_the_ais_turn(sid, stops)

    declared = [line for line in game.log if line.startswith("AI declared")]
    assert declared and declared[0] != "AI declared 0 attacker(s)", game.log[-20:]

    # CR 117.3a, 508.1, 509.1: nobody holds priority in a declaration step
    # before its declaration — the person was never served priority there,
    # and neither was the AI.
    early = [
        row for row in served
        if row[1] is not None and (
            (row[0] == "declare_attackers" and not row[2])
            or (row[0] == "declare_blockers" and not row[3])
        )
    ]
    assert not early, f"priority before the declaration: {early}; log: {game.log[-25:]}"

    # CR 508.2: the active AI was asked, with the attack declared, the
    # blocks to come and nothing on the stack.
    assert any(
        step == "declare_attackers" and seat == 1 and attackers_locked
        and not blockers_locked and empty
        for step, seat, attackers_locked, blockers_locked, empty in asked
    ), f"the AI never answered its declare-attackers priority: {asked}; log: {game.log[-25:]}"

    # CR 509.2: …and again once the blocks were declared.
    assert any(
        step == "declare_blockers" and seat == 1 and blockers_locked and empty
        for step, seat, _attackers_locked, blockers_locked, empty in asked
    ), f"the AI never answered its declare-blockers priority: {asked}; log: {game.log[-25:]}"

    # CR 117.4: the AI's attack trigger resolved only once the person had
    # passed over it.
    if attack_trigger:
        assert any(
            row[0] == "declare_attackers" and row[1] == 0 and row[4] == 1 for row in served
        ), f"the attack trigger never waited for the person: {served}; log: {game.log[-25:]}"

    # The rail: a step the person flagged gave them priority once its
    # declaration was made, and with nothing on the stack.
    for step in (s for s in stops if s in ("declare_attackers", "declare_blockers")):
        locked_index = 2 if step == "declare_attackers" else 3
        assert any(
            row[0] == step and row[1] == 0 and row[locked_index] and row[4] == 0
            for row in served
        ), f"the person's {step} stop never gave them priority: {served}; log: {game.log[-25:]}"


@pytest.mark.cr("508.2", "117.3a")
@pytest.mark.parametrize("held", ([], ["declare_attackers"]))
def test_the_attacking_ai_sheds_its_flying_before_the_blocks_so_lure_makes_the_bears_block(held):
    """The AI's Ribbon Snake (a 2/3 flier, "{2}: This creature loses flying
    until end of turn") wears Lure; the person has Grizzly Bears. Shed in the
    declare attackers step, the flying is gone when blocks are declared, Lure
    makes the Bears block, and the Snake kills them and lives — whether or
    not the person's rail holds that step.

    The Islands arrive at beginning of combat (the person's rail stops there
    so they can), so the main phase cannot have spent them: the main-phase
    chooser sheds the flying itself when it can pay, and the step this is
    about would never be reached with mana open."""
    sid, session = _session(force_attack=False)
    game = session.game
    (snake,) = _put(game, 1, ["Ribbon Snake"])
    (lure,) = _put(game, 1, ["Lure"])
    attach_aura(lure, snake)
    (bears,) = _put(game, 0, ["Grizzly Bears"])
    game._recompute_continuous_effects()

    def lands(g):
        _put(g, 1, ["Island", "Island"])

    def owed_block(g):
        # Lure's requirement, once the Bears can block the Snake at all.
        if g._can_block_attacker(bears, snake):
            return {str(bears.permanent_id): [snake.permanent_id]}
        return {}

    served = _play_the_ais_turn(
        sid, ["beginning_of_combat"] + held, on_combat=lands, blocks=owed_block,
    )

    assert "Ribbon Snake loses flying until end of turn" in game.log, game.log[-25:]
    shed_at = game.log.index("Ribbon Snake loses flying until end of turn")
    declared_at = game.log.index("AI declared 1 attacker(s)")
    assert declared_at < shed_at, game.log[declared_at - 5:]
    assert "Player 1 declared 1 blocker(s)" in game.log[shed_at:], game.log[shed_at:]
    assert any(card.name == "Grizzly Bears" for card in game.players[0].graveyard), game.log[-25:]
    assert any(p.card.name == "Ribbon Snake" for p in game.controlled_by(1))
    assert game.players[0].life == 20
    # The person was asked over the ability before it resolved (CR 117.4).
    assert any(row[0] == "declare_attackers" and row[1] == 0 and row[4] == 1 for row in served), served


@pytest.mark.cr("509.1", "509.2")
@pytest.mark.parametrize("held", ([], ["declare_blockers"]))
def test_the_attacking_ai_pumps_its_unblocked_attacker_when_the_person_had_no_block(held):
    """The AI attacks with Grizzly Bears into a person with no creature, and
    holds Giant Growth over a Forest (both arriving at beginning of combat,
    where the person's rail stops, so its main phase cannot have spent
    them). The person's declaration is the empty one; CR 509.2 gives the AI
    priority, Giant Growth goes on the stack, the person is asked over it,
    and the Bears deal 5. The engine's leaving pass declared this person's
    nothing and left the step in one call, so the AI was never asked."""
    sid, session = _session()
    game = session.game
    _put(game, 1, ["Grizzly Bears"])

    def trick(g):
        _put(g, 1, ["Forest"])
        g.players[1].hand = [_CARDS["Giant Growth"]]

    served = _play_the_ais_turn(sid, ["beginning_of_combat"] + held, on_combat=trick)

    assert any(card.name == "Giant Growth" for card in game.players[1].graveyard), game.log[-25:]
    assert game.players[0].life == 15, game.log[-25:]
    # Cast once the blocks were in, and answered by the person before it resolved.
    assert any(
        row[0] == "declare_blockers" and row[1] == 0 and row[3] and row[4] == 1 for row in served
    ), served
    if held:
        assert any(
            row[0] == "declare_blockers" and row[1] == 0 and row[3] and row[4] == 0 for row in served
        ), served


@pytest.mark.cr("117.3a", "503.1")
def test_the_ais_upkeep_answer_comes_before_the_persons_flagged_upkeep():
    """Hammer of Bogardan in the AI's graveyard over five Mountains ("Return
    this card from your graveyard to your hand. Activate only during your
    upkeep"), and the person's rail flagging the AI's upkeep. The active
    player receives priority first (CR 117.3a): the AI answers it — the
    ability goes on the stack and the person is asked over it — and only then
    holds the person's flagged window. The hold passed the AI's priority on
    unasked, so the Hammer stayed in the graveyard."""
    sid, session = _session()
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game.start_priority_window(0)
    _put(game, 1, ["Mountain"] * 5)
    game.players[1].graveyard = [_CARDS["Hammer of Bogardan"]]
    stops = ["upkeep"]
    _act(sid, action="end_turn", stop_steps=stops)
    served = []
    for _ in range(40):
        state = _state(sid)
        if state["current_turn"] != 1 or state["current_step"] != "upkeep":
            break
        served.append((state["priority_player"], [item["label"] for item in state["stack"]]))
        if state["priority_player"] == 0:
            _act(sid, action="pass_priority", stop_steps=stops)
        else:
            _act(sid, action="ai_step", stop_steps=stops)
    assert any(card.name == "Hammer of Bogardan" for card in game.players[1].hand), game.log[-20:]
    assert any(
        holder == 0 and any("Hammer of Bogardan" in label for label in labels)
        for holder, labels in served
    ), served
    # …and the person's flagged upkeep window, with nothing on the stack.
    assert any(holder == 0 and not labels for holder, labels in served), served

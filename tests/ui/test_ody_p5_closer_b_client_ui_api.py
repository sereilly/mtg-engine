"""The client half of the engine closer's fixes for Odyssey's Phase 5.

The engine closer changed what the server says in four places a person meets,
and each needed the client to read the new field rather than keep an older
habit. The server halves have their own wire tests beside this file; these
hold that ``app.js`` still **reads** what they send (as text — ``app.js`` is
DOM-coupled and bare ``node`` cannot load it; see
``tests.helpers.app_js_function_body``), and one wire test of the body the
client now sends for a Fork.

* **"Pay" follows ``payable``.** A payment the board cannot make is refused now
  instead of being read as a decline, so the button says so before the click:
  disabled, with the refusal's own advice beside it, until tapping makes the
  server answer ``payable: true`` (``test_pay_prompt_refusal_ui_api.py``).
* **"Fail to Find" follows ``min_picks``.** The floor rides every search, and a
  search for "a card" has a floor of 1 (CR 701.23d), so the decline is not
  offered beside it (``test_unqualified_search_ui_api.py``).
* **Cards put on top say "top".** ``reorder_library`` with ``position: "top"``
  is a pile going onto the library in its owner's order, not a look at what is
  already there (``test_bauble_owner_draws_ui_api.py``).
* **Fork is asked once, by the server.** The client's own second step — a new
  permanent chosen before the cast went out — is gone; the ``copy_spell_target``
  prompt asks as the copy is made (``test_fork_new_target_prompt_ui_api.py``).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from engine.models import Permanent
from tests.helpers import _pass_priority, app_js_function_body
from web.app import app, store
from web.runtime import CARD_BY_NAME

client = TestClient(app)

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"


def _app_js() -> str:
    return (STATIC / "app.js").read_text(encoding="utf-8")


# --- "Pay" follows `payable` ------------------------------------------------


def test_the_toll_prompts_pay_button_follows_payable():
    body = app_js_function_body("applyManaPaymentPrompt")

    # Strictly false: an absent field (an older server) leaves the button as it
    # was, and a falsy test would lock it there for good.
    assert "const cannotPayYet = info.payable === false;" in body
    assert "!info.payable" not in body

    pay_button = body[body.index('id="manaPayBtn"'):body.index('id="manaDeclineBtn"')]
    assert "cannotPayYet ? ` disabled title=" in pay_button
    # Declining is always an answer; only "Pay" is ever locked.
    decline_button = body[body.index('id="manaDeclineBtn"'):body.index("steps.innerHTML")]
    assert "disabled" not in decline_button
    # …and the reason is on the panel, not only in a hover.
    assert 'cannotPayYet ? `<div class="prompt-subnote prompt-pay-note">${PAY_NOT_YET_HINT}</div>`' in body


def test_the_optional_offers_pay_buttons_follow_payable():
    body = app_js_function_body("applyOptionalPayPrompt")

    assert "const cannotPayYet = current?.payable === false;" in body
    assert 'const payLock = cannotPayYet ? ` disabled title="${PAY_NOT_YET_HINT}"` : "";' in body
    # Both shapes of "yes" carry it — a graded price (Pay {1} / Pay {2}) and the
    # single accept — and the "no" beside them never does.
    assert body.count("${payLock}") == 2
    graded, single, decline = _optional_pay_button_lines(body)
    assert "${payLock}" in graded and "${payLock}" in single
    assert "${payLock}" not in decline and "disabled" not in decline
    assert 'cannotPayYet ? `<div class="prompt-subnote prompt-pay-note">${PAY_NOT_YET_HINT}</div>`' in body


def _optional_pay_button_lines(body: str) -> tuple[str, str, str]:
    """The three lines that build the offer's buttons: the graded "yes" (its
    ``data-pay-option`` half), the single "yes", and the "no"."""
    graded = next(line for line in body.splitlines() if "data-pay-option=" in line)
    single = next(
        line for line in body.splitlines()
        if 'data-optional-pay="yes"' in line and "acceptLabel" in line
    )
    decline = next(line for line in body.splitlines() if 'data-optional-pay="no"' in line)
    return graded, single, decline


def test_the_note_gives_the_refusals_own_advice():
    """What the panel says before the click is what the server would say after
    it: tap first, or decline. Read off a live refusal so the two cannot drift
    into saying different things."""
    from engine.game_types import StackItem

    created = client.post(
        "/api/sessions", json={"mode": "human_vs_human", "seed": 2213},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "main")
    game.interactive_seats = {0, 1}
    me = game.players[0]
    me.battlefield = [Permanent(card=CARD_BY_NAME["island"])]
    me.mana_pool = {symbol: 0 for symbol in me.mana_pool}
    game._settle()
    bolt = StackItem(
        card=CARD_BY_NAME["lightning bolt"], caster_index=0,
        target_player_index=1, target_permanent_index=None, x_value=None,
    )
    game.stack.append(bolt)
    game.arm_pending_choice(
        "mana_payment", 0, amount=3, card_name="Mana Leak",
        counter_card=CARD_BY_NAME["mana leak"], stack_item=bolt,
    )

    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    assert state["mana_payment"]["payable"] is False
    refused = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "confirm_mana_payment", "accept": True},
    )
    assert refused.status_code == 400
    detail = refused.json()["detail"].lower()

    source = _app_js()
    hint = source[source.index("const PAY_NOT_YET_HINT = "):].split("\n", 1)[0].lower()
    for advice in ("tap for the mana first", "or decline"):
        assert advice in detail, detail
        assert advice in hint, hint


# --- "Fail to Find" follows `min_picks` -------------------------------------


def test_fail_to_find_is_withheld_from_every_search_with_a_floor():
    body = app_js_function_body("renderSearchLibraryModal")

    # Every search's floor, not only a counted one's: it read
    # `multi && Number.isInteger(info.min_picks)`, so Demonic Tutor's 1 was
    # dropped and its modal went on offering a decline the engine refuses.
    assert "const minPicks = Number.isInteger(info.min_picks) ? info.min_picks : 0;" in body
    assert "multi && Number.isInteger(info.min_picks)" not in body
    # One switch, read by the single-pick and the counted modal alike — it sits
    # after the `if (multi) … else …`, not inside either arm. A floor of 0 (a
    # stated quality, CR 701.23b; "up to") keeps the button.
    update = body[body.index("function updateConfirmButton() {"):]
    update = update[:update.index("\n  }\n")]
    toggle = 'if (declineBtn) declineBtn.classList.toggle("hidden", minPicks > 0);'
    assert toggle in update
    assert update.index(toggle) > update.rindex("} else {")
    assert 'document.getElementById("searchLibraryDeclineBtn")' in body


# --- cards put on top say "top" ---------------------------------------------


def test_cards_put_on_top_are_not_called_a_reorder_of_the_top():
    body = app_js_function_body("renderReorderLibraryModal")

    assert 'const ontoTop = info.position === "top";' in body
    assert ': ontoTop ? "Order the Top of Library" : "Reorder Top of Library";' in body
    # Whose library, how many, and which end of the row is the top card — the
    # owner chooses the order (CR 401.4) and may be ordering somebody else's
    # pile's worth of their own cards.
    assert "`These ${cards.length} cards go on top of ${whose} library. Drag cards to rearrange. `" in body
    assert '"The leftmost card will be the top card — the next one drawn."' in body
    # The bottom's wording is its own, and a plain look keeps the old one.
    assert 'atBottom ? "Order the Bottom of Library"' in body
    assert "go on the bottom of ${whose} library" in body
    assert '"Drag cards to rearrange. The leftmost card will be on top of the library."' in body


# --- Fork is asked once, by the server --------------------------------------


def test_the_client_has_no_cast_time_step_for_a_copys_new_target():
    """One way of asking, not two. The client's second step ran before the
    cast went out, only for a copied spell whose picker was a creature, a
    permanent, an artifact or a land, and could not name a player; the server
    asks every copy now, as it is made."""
    source = _app_js()
    for gone in (
        "startForkCopyRetarget", "sendForkCopyCast", "forkStackIndex",
        "copiesSpell", "_FORK_RETARGET_KINDS", "copies_spell",
    ):
        assert gone not in source, f"{gone} is back in app.js"

    # Choosing the spell to copy sends the cast: nothing between the pick and
    # the body but the X prompt, and the body names the spell and nothing else.
    select = app_js_function_body("selectStackSpellTarget")
    cast = select[select.index("const actionBody = {"):]
    cast = cast[:cast.index("};")]
    assert [line.strip() for line in cast.splitlines()[1:] if line.strip()] == [
        "seat,",
        'action: pending.castAction || "cast",',
        "card_name: pending.cardName,",
        "target_stack_index: arrayIndex,",
    ]


def test_the_copys_prompt_is_answered_on_the_board_with_a_permanent_or_a_player():
    info = app_js_function_body("getCopySpellTargetInfo")
    assert "state.copy_spell_target" in info and "info.player_seat !== seat" in info

    board = app_js_function_body("getPromptBoardTargeting")
    start = board.index("copySpellTargetInfo.candidates")
    branch = board[start:board.index("return promptTargeting({", start) + 900]
    # A permanent is named by id (never by slot), a player by seat — the two
    # bodies the server documents — and the players are offered at all, which
    # is what the removed step could not do.
    assert 'action: "copy_spell_target_confirm",\n          target_permanent_id: byKey.get(`${targetSeat}-${idx}`),' in branch.replace("\r\n", "\n")
    assert 'action: "copy_spell_target_confirm",\n          target_seat: targetSeat,' in branch.replace("\r\n", "\n")
    assert 'candidates.filter((c) => c.kind === "player").map((c) => c.seat)' in branch
    assert "playerSeats: seats," in branch


def test_fork_cast_as_the_client_now_sends_it_asks_for_a_permanent_targets_copy():
    """Giant Growth on one creature, then Fork with the only body the client
    sends any more — the spell to copy and no target. The copy's new target is
    asked as Fork resolves and answered by id; both creatures end up grown."""
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_colors": 2, "guest_colors": 2, "seed": 708},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    game = store.get(sid).game
    game.enforce_mana_costs = False
    me, _you = game.players
    first = Permanent(card=CARD_BY_NAME["grizzly bears"])
    second = Permanent(card=CARD_BY_NAME["grizzly bears"])
    me.battlefield = [first, second]
    me.hand = [CARD_BY_NAME["giant growth"], CARD_BY_NAME["fork"]]
    game._settle()

    def act(**body):
        return client.post(f"/api/sessions/{sid}/action", json={"seat": 0, **body})

    def state() -> dict:
        return client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()

    growth = act(
        action="cast", card_name="Giant Growth",
        target_seat=0, target_permanent_id=first.permanent_id,
    )
    assert growth.status_code == 200, growth.text
    fork = act(action="cast", card_name="Fork", target_stack_index=0)
    assert fork.status_code == 200, fork.text
    assert state()["copy_spell_target"] is None, "not until Fork resolves"

    _pass_priority(sid, 0)
    _pass_priority(sid, 1)

    prompt = state()["copy_spell_target"]
    assert prompt is not None, game.log[-6:]
    assert prompt["player_seat"] == 0 and prompt["card_name"] == "Giant Growth"
    offered = {c["id"] for c in prompt["candidates"] if c["kind"] == "permanent"}
    assert offered == {first.permanent_id, second.permanent_id}
    assert not [c for c in prompt["candidates"] if c["kind"] == "player"]

    aimed = act(action="copy_spell_target_confirm", target_permanent_id=second.permanent_id)
    assert aimed.status_code == 200, aimed.text
    assert state()["copy_spell_target"] is None

    for _ in range(8):
        if not game.stack:
            break
        _pass_priority(sid, 0)
        _pass_priority(sid, 1)

    assert (first.effective_power, second.effective_power) == (5, 5), game.log[-8:]

"""Two gates the castable highlight did not ask (``web/state_view.py``).

The board glows a card it believes can be cast right now. Two families were
wrong in opposite directions, both found by putting Planeshift's kicked spells
on a board and looking at what lit up:

* **A spell naming several roles never glowed.** "Return target creature to
  its owner's hand. Then return another target creature…" (Withdraw). The
  highlight asked ``_validate_cast_targets`` with no target named, and that
  gate counts the named targets against the roles — so the answer was
  "requires 2 targets" on every board. Ten shipped spells, dark with a full
  chain of legal targets in play. The Aura branch beside it had met the same
  gate and answered it the same way this now does: ask the picker.
* **A spell whose printed cost could not be paid glowed.** "As an additional
  cost to cast this spell, sacrifice a creature." (Village Rites.) Nothing
  asked CR 601.2h, so 27 shipped spells lit up with nothing to pay with and
  the click was refused.

Both are asked pool-wide, with a floor on how many cards each sweep reaches —
a census that reads no cards passes for the wrong reason.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from engine.card_loader import load_catalog
from engine.cast_costs import additional_costs
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec, spec_roles
from web.app import app, store

client = TestClient(app)
_CARDS = {card.name: card for card in load_catalog()}

_MINE = (
    ["Forest"] * 3 + ["Island"] * 3 + ["Mountain"] * 3 + ["Plains"] * 3
    + ["Swamp"] * 3 + ["Grizzly Bears", "Sol Ring", "Wall of Wood", "Castle"]
)
_THEIRS = [
    "Grizzly Bears", "Hill Giant", "Sol Ring", "Mox Pearl", "Forest", "Island",
    "Wall of Wood", "Castle", "Serra Angel", "Royal Assassin",
]


def _session(name: str, mine):
    created = client.post(
        "/api/sessions",
        json={
            "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
            "host_colors": 2, "guest_colors": 2, "seed": 4243,
        },
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    game = session.game
    game.enforce_mana_costs = True
    game.players[0].battlefield = [Permanent(card=_CARDS[n]) for n in mine]
    game.players[1].battlefield = [Permanent(card=_CARDS[n]) for n in _THEIRS]
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.players[0].hand = [_CARDS[name]]
    game.players[0].mana_pool.update({"W": 9, "U": 9, "B": 9, "R": 9, "G": 9})
    session.current_turn = 0
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game


def _glows(sid) -> bool:
    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    return bool(state["players"][0]["playable_hand_indices"])


def _spells():
    """Every shipped single-face instant or sorcery that compiles, with its
    program. Through ``compilation_units`` so a split card's halves are not
    read as one empty card; a half is left out because the hand holds the
    whole card and the highlight asks about that."""
    for card in compilation_units(load_catalog()):
        if card.face_of is not None:
            continue
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if program.supported and not program.modes:
            yield card, program


def _roles_spells() -> list[str]:
    return sorted(
        card.name for card, program in _spells()
        if spec_roles(derive_cast_spec(card, program, optional_cost_payments={}))
    )


def _mandatory_cost_spells() -> list[str]:
    """Spells whose printed additional cost is a price in permanents or cards
    — the ones an empty board cannot pay."""
    found = []
    for card, _program in _spells():
        for cost in additional_costs(card):
            if cost.optional_key is not None or cost.from_zone is not None:
                continue
            if (
                cost.sacrifice_filter is not None
                or cost.exile_filter is not None
                or (cost.return_filter is not None and not cost.return_count_x)
                or (cost.discard_cards and not cost.discard_count_x)
            ):
                found.append(card.name)
                break
    return sorted(found)


def test_the_sweeps_reach_the_cards_they_are_about():
    roles, costs = _roles_spells(), _mandatory_cost_spells()
    assert len(roles) >= 9, roles
    assert {"Withdraw", "Lunge", "Donate"} <= set(roles)
    assert len(costs) >= 24, costs
    assert {"Village Rites", "Natural Order", "Thrill of Possibility"} <= set(costs)


@pytest.mark.parametrize("name", _roles_spells())
def test_a_roles_spell_glows_exactly_when_the_picker_offers_a_chain(name):
    """The highlight and the picker agree: a full chain of legal targets is a
    castable spell, and no chain is not."""
    sid, game = _session(name, _MINE)
    chain = game.cast_target_spec(0, _CARDS[name]).get("valid_targets")
    assert _glows(sid) is bool(chain), name


def test_withdraw_glows_with_two_creatures_and_not_with_one():
    """The named case: two targets must be two different creatures."""
    sid, game = _session("Withdraw", _MINE)
    assert _glows(sid)
    game.players[1].battlefield = [Permanent(card=_CARDS["Hill Giant"])]
    game.players[0].battlefield = [
        Permanent(card=_CARDS["Island"]) for _ in range(3)
    ]
    assert not _glows(sid)


@pytest.mark.parametrize("name", _mandatory_cost_spells())
def test_a_spell_does_not_glow_while_its_printed_cost_cannot_be_paid(name):
    """CR 601.2h, through the gate the cast path refuses with: on a board with
    nothing of the caster's own (and a hand holding only the spell) the cost is
    unpayable wherever that gate says so, and the card is then dark."""
    sid, game = _session(name, [])
    card = _CARDS[name]
    refusal = game._unpayable_additional_cost(
        0, card, additional_costs(card), spell_hand_index=0, from_zone="hand",
        taken={},
    )
    if refusal is None:
        pytest.skip(f"{name}'s cost is payable off an empty board")
    assert not _glows(sid)


def test_the_highlight_asks_about_the_cast_with_every_offer_declined(set_pool):
    """CR 702.33g: "Prevent all combat damage target creature would deal this
    turn. If this spell was kicked, prevent all combat damage another target
    creature would deal this turn." (Falling Timber.) Castable *now* is the
    cheapest cast, the unkicked one, which names one creature — so one
    creature on the table is enough, and none is not. Read as the card's every
    arm the spell named two and was dark on every board."""
    timber = set_pool("PLS")["Falling Timber"]

    def table(theirs):
        sid, game = _session("Withdraw", ["Forest"] * 3)
        game.players[0].hand = [timber]
        game.players[1].battlefield = [Permanent(card=_CARDS[n]) for n in theirs]
        return sid

    assert _glows(table(["Grizzly Bears"]))
    assert _glows(table(["Grizzly Bears", "Hill Giant"]))
    assert not _glows(table([]))


def test_village_rites_glows_once_there_is_a_creature_to_sacrifice():
    """…and the gate is a gate, not a blanket: the same spell with its cost
    payable is castable."""
    sid, _game = _session("Village Rites", [])
    assert not _glows(sid)
    sid, _game = _session("Village Rites", ["Grizzly Bears"])
    assert _glows(sid)

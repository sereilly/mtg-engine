"""What a mana ability adds is stated for every shape, the board's included.

``ability_mana`` (``web/offers``) said what each ability adds and whether its
activation asks a colour — but only where the ability's own payload said it.
Every shape whose symbols the board, a record or the cost decides was None, and
the client fell back to the card's text (``cardRequiresManaColorChoice``: "one
mana of any color" — all five) or to the permanent's ``produced_mana`` summary:

* Fellwar Stone, Quirion Explorer, Harvester Druid, Star Compass ("…of any
  color that a land … could produce") offered five colours whatever the board,
  which the resolution then narrowed;
* Sol Grail and Quirion Elves ("…of the chosen color"), Jeweled Amulet ("…of
  this artifact's last noted type") and Charmed Pendant (the milled card's
  symbols) opened a five-colour fan whose answer the engine never read — and
  so did abilities that add no mana at all beside one that does (Jeweled
  Amulet's charge, Diamond Kaleidoscope's token, Soldevi Excavations' scry);
* Benthic Explorers and Squandered Resources ("…any type that land could
  produce") offered five colours for a land that makes one, or (Squandered,
  whose sacrifice is picked on the board) asked nothing and took the first type
  alphabetically;
* Adarkar Unicorn and Cadaverous Bloom ("Add {U} or {C}{U}", "{B}{B} or
  {G}{G}") opened a fan of colours; the engine read an index nothing wrote, so
  the Bloom's {G} made {B}{B}, and the Unicorn's {C} could not be clicked.

The server now states each (``offers._decided_ability_mana``): the board's set
through ``mana_could_produce.ability_colors_on_offer``, the records, the land
the cost names (``symbols_by_cost``), and the alternatives (``alternatives``,
answered on ``mana_combination``, which ``mana_combination.split_refusal``
holds to one of them). An entry is None only for an ability that adds no mana.

Backwards on the base: the census finds 17 add-mana abilities with no entry,
the Bloom's {"G": 2} is refused ("makes no mana in any combination"), and the
client asks Fellwar Stone for five colours.
"""
from __future__ import annotations

import re
import shutil

import pytest

from engine import faces
from engine.card_loader import load_catalog
from engine.mana_abilities import _every_nested_step
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import app_js_function_body, client, resolve_stack, run_app_js
from web.app import store

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not on PATH; the client half cannot run",
)

_PRELUDE = (
    'const MANA_COLOR_OPTIONS = [{symbol: "W", label: "White"}, {symbol: "U", label: "Blue"},'
    ' {symbol: "B", label: "Black"}, {symbol: "R", label: "Red"}, {symbol: "G", label: "Green"}];'
    " let pendingActivationCost = null;"
)


def _session(mine=(), theirs=(), *, tapped_theirs=False):
    created = client.post("/api/sessions", json={
        "mode": "human_vs_human", "host_name": "Host", "guest_name": "Guest",
        "host_colors": 2, "guest_colors": 2, "seed": 4471,
    }).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "Joiner"})
    session = store.get(sid)
    session.pregame_phase = None
    game = session.game
    session.current_turn = 0
    game.active_player_index = 0
    for player in game.players:
        player.hand.clear()
        player.graveyard.clear()
    game.remove_all_from_battlefield(list(game.all_permanents()))
    # Entered at a table nobody answers, so an "as it enters" colour is the
    # default and stamped (Sol Grail); then the table is the people's again.
    seats = set(game.interactive_seats)
    game.interactive_seats = set()
    placed = {}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            permanent.tapped = bool(seat == 1 and tapped_theirs)
            placed.setdefault(name, permanent)
    resolve_stack(game)
    game.interactive_seats = seats
    game.pending_choices.clear()
    game._recompute_continuous_effects()
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    game.start_priority_window(0)
    return sid, game, placed


def _payload(sid, permanent, seat=0):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": seat}).json()
    return next(
        entry for player in state["players"] for entry in player["battlefield"]
        if entry.get("id") == permanent.permanent_id
    )


def _activate(sid, permanent, **fields):
    return client.post(f"/api/sessions/{sid}/action", json={
        "seat": 0, "action": "activate", "permanent_id": permanent.permanent_id, **fields,
    })


# -- the census --------------------------------------------------------------

def _adds_mana(ability) -> bool:
    instruction = ability.instruction
    return instruction is not None and any(
        step.kind == "add_mana_from_text" for step in (instruction, *_every_nested_step(instruction))
    )


def test_every_ability_that_adds_mana_is_stated():
    """Pool-wide: each usable activated ability with an add-mana step, put on a
    board, has an ``ability_mana`` entry — and the ones the payload alone
    cannot read are answered by the board's reader, not by the summary."""
    from web import offers
    from web.offers import _ability_mana, _ability_mana_payload

    # Read by name so the census runs, and names what it finds, on a tree
    # without the board's reader.
    decided_reader = getattr(offers, "_decided_ability_mana", None)

    sid, game, _placed = _session()
    # Nobody answers, so an "as it enters" choice is stamped and the permanent
    # is on the battlefield to be asked (Sol Grail's colour).
    game.interactive_seats = set()
    examined, decided, unstated = 0, set(), []
    for unit in faces.compilation_units(_CATALOG):
        program = compile_card_oracle(unit)
        if not program.supported or unit.primary_type in ("instant", "sorcery"):
            continue
        usable = usable_activated_abilities(program)
        if not any(_adds_mana(ability) for ability in usable):
            continue
        permanent = Permanent(card=unit)
        game._put_permanent_onto_battlefield(0, permanent, None)
        game.stack.clear()
        game.pending_choices.clear()
        if not game.is_on_battlefield(permanent):
            # An entry its own replacement stopped (Balduvian Trading Post
            # with no Mountain to sacrifice).
            continue
        on_board = game.usable_abilities_of(permanent, card=permanent.effective_card)
        entries = _ability_mana_payload(game, permanent, on_board)
        # A land whose tap the board changed is answered by its summary
        # (``_ability_mana_payload``'s guard); every other permanent states.
        guarded = permanent.has_type("land") and set(offers._offered_mana(game, permanent)) != set(
            permanent.effective_produced_mana
        )
        for index, ability in enumerate(on_board):
            if not _adds_mana(ability):
                if entries is not None:
                    assert entries[index] is None, (unit.name, index)
                continue
            examined += 1
            if entries is None or entries[index] is None:
                if not guarded:
                    unstated.append((unit.name, ability.source_line))
                continue
            if _ability_mana(ability.instruction) is None and decided_reader is not None:
                if decided_reader(game, permanent, ability.instruction) is not None:
                    decided.add(unit.name)
        game.remove_from_battlefield(permanent)
    assert examined >= 300, examined
    assert unstated == [], unstated
    # The shapes the board, a record or the cost decides — a floor, not a count.
    assert len(decided) >= 10, sorted(decided)
    assert {"Fellwar Stone", "Benthic Explorers", "Cadaverous Bloom", "Sol Grail"} <= decided


# -- the board decides: "…that a land … could produce" ------------------------

_OPPONENT_READERS = ("Fellwar Stone", "Quirion Explorer")


@pytest.mark.parametrize("name", _OPPONENT_READERS)
def test_an_opponent_s_lands_are_the_question_on_two_boards(name):
    sid, game, placed = _session([name], ["Mountain", "Swamp"])
    payload = _payload(sid, placed[name])
    (entry,) = payload["ability_mana"]
    assert entry == {"symbols": ["B", "R"], "choice": True}
    # …and the summary a player reads off its badges says the same.
    assert payload["produced_mana"] == ["B", "R"]
    response = _activate(sid, placed[name], mana_color="R")
    assert response.status_code == 200, response.text
    assert game.players[0].mana_pool["R"] == 1

    # The other board: an opponent with no land offers nothing (CR 106.7).
    sid, game, placed = _session([name, "Forest"], [])
    payload = _payload(sid, placed[name])
    (entry,) = payload["ability_mana"]
    assert entry == {"symbols": [], "choice": False}
    assert payload["produced_mana"] == []
    response = _activate(sid, placed[name])
    assert response.status_code == 200, response.text
    assert sum(game.players[0].mana_pool.values()) == 0
    assert any("produces colored mana" in line for line in game.log[-4:]), game.log[-4:]


def test_your_own_lands_and_your_basic_lands_are_two_questions():
    sid, game, placed = _session(
        ["Harvester Druid", "Star Compass", "Forest", "Underground River"], ["Mountain"],
    )
    (druid,) = _payload(sid, placed["Harvester Druid"])["ability_mana"]
    (compass,) = _payload(sid, placed["Star Compass"])["ability_mana"]
    # The painland's colours are the Druid's too; only the Forest is basic.
    assert druid == {"symbols": ["U", "B", "G"], "choice": True}
    assert compass == {"symbols": ["G"], "choice": False}
    placed["Star Compass"].tapped = False
    response = _activate(sid, placed["Star Compass"])
    assert response.status_code == 200, response.text
    assert game.players[0].mana_pool["G"] == 1


# -- a record decides ---------------------------------------------------------

def test_a_chosen_colour_and_a_noted_type_are_not_asked():
    sid, game, placed = _session(["Sol Grail", "Quirion Elves", "Jeweled Amulet", "Charmed Pendant"])
    grail = placed["Sol Grail"]
    chosen = grail.metadata["chosen_color"]
    assert _payload(sid, grail)["ability_mana"] == [{"symbols": [chosen], "choice": False}]
    # Its badges say the colour it chose, not the five it could have.
    assert _payload(sid, grail)["produced_mana"] == [chosen]
    elves = _payload(sid, placed["Quirion Elves"])["ability_mana"]
    assert elves == [
        {"symbols": ["G"], "choice": False},
        {"symbols": [placed["Quirion Elves"].metadata["chosen_color"]], "choice": False},
    ]
    # The charge ability adds no mana; the adding one has noted nothing yet.
    assert _payload(sid, placed["Jeweled Amulet"])["ability_mana"] == [
        None, {"symbols": [], "choice": False},
    ]
    # The milled card decides, after the cost: nothing to ask — and its
    # summary, every colour it could make, stands.
    pendant = _payload(sid, placed["Charmed Pendant"])
    assert pendant["ability_mana"] == [{"symbols": [], "choice": False}]
    assert len(pendant["produced_mana"]) == 5

    response = _activate(sid, grail)
    assert response.status_code == 200, response.text
    assert game.players[0].mana_pool[chosen] == 1


# -- the cost decides: "…any type that land could produce" --------------------

def test_the_land_a_cost_names_is_the_question():
    sid, game, placed = _session(
        ["Benthic Explorers", "Squandered Resources", "Underground River", "Forest"],
        ["Mountain", "Volcanic Island"], tapped_theirs=True,
    )
    river, mountain = placed["Underground River"], placed["Mountain"]
    volcanic = placed["Volcanic Island"]
    (benthic,) = _payload(sid, placed["Benthic Explorers"])["ability_mana"]
    by_cost = benthic["symbols_by_cost"]
    assert by_cost[str(mountain.permanent_id)] == ["R"]
    assert sorted(by_cost[str(volcanic.permanent_id)]) == ["R", "U"]
    assert sorted(by_cost[str(river.permanent_id)]) == ["B", "C", "U"]

    # Squandered Resources sacrificing the painland for {C}: one of its types.
    response = _activate(
        sid, placed["Squandered Resources"],
        cost_permanent_id=river.permanent_id, mana_color="C",
    )
    assert response.status_code == 200, response.text
    assert game.players[0].mana_pool["C"] == 1
    assert not game.is_on_battlefield(river)

    # Benthic Explorers untapping the opponent's Volcanic Island, for {U}.
    response = _activate(
        sid, placed["Benthic Explorers"],
        cost_permanent_ids=[volcanic.permanent_id], mana_color="U",
    )
    assert response.status_code == 200, response.text
    assert game.players[0].mana_pool["U"] == 1
    assert not volcanic.tapped


# -- an "or" of written-out quantities ----------------------------------------

def test_an_or_of_quantities_is_answered_as_the_mana_taken():
    sid, game, placed = _session(["Cadaverous Bloom", "Adarkar Unicorn"])
    game.players[0].hand = [_CARDS["Forest"], _CARDS["Island"]]
    (bloom,) = _payload(sid, placed["Cadaverous Bloom"])["ability_mana"]
    assert bloom["alternatives"] == [{"B": 2}, {"G": 2}]
    response = _activate(
        sid, placed["Cadaverous Bloom"], cost_hand_index=0, mana_combination={"G": 2},
    )
    assert response.status_code == 200, response.text
    pool = game.players[0].mana_pool
    assert (pool["G"], pool["B"]) == (2, 0)

    (unicorn,) = _payload(sid, placed["Adarkar Unicorn"])["ability_mana"]
    assert unicorn["alternatives"] == [{"U": 1}, {"C": 1, "U": 1}]
    response = _activate(sid, placed["Adarkar Unicorn"], mana_combination={"U": 1})
    assert response.status_code == 200, response.text
    restricted = game.players[0].restricted_mana
    assert sum(sum(bucket.values()) for bucket in restricted.values()) == 1, restricted


def test_a_quantity_that_is_not_printed_is_refused_with_nothing_paid():
    sid, game, placed = _session(["Adarkar Unicorn"])
    response = _activate(sid, placed["Adarkar Unicorn"], mana_combination={"C": 1})
    assert response.status_code == 400
    assert "{U} or {C}{U}" in response.json()["detail"]
    assert not placed["Adarkar Unicorn"].tapped


# -- the client asks what the server states -----------------------------------

_CLIENT_FUNCTIONS = [
    "chosenAbilityMana", "abilityAddsNoMana", "manaForChosenCost", "manaOptionsFor",
    "abilityManaColors", "getDualLandColors", "chosenAbilityCombination",
]


def _asked(card, cost_id=None):
    return run_app_js(
        _CLIENT_FUNCTIONS,
        "const stated = manaForChosenCost(chosenAbilityMana(INPUT.card), INPUT.cost);"
        " const fan = abilityManaColors(INPUT.card, stated);"
        " const split = chosenAbilityCombination(INPUT.card);"
        " return { modal: !!(stated && stated.choice && stated.symbols.length >= 5),"
        " fan: fan ? manaOptionsFor(fan).map((o) => o.symbol) : null,"
        " splits: split && split.splits ? split.splits : null };",
        {"card": card, "cost": cost_id},
        prelude=_PRELUDE,
    )


@needs_node
def test_the_client_offers_the_board_s_colours_and_asks_nothing_fixed():
    sid, game, placed = _session(
        ["Fellwar Stone", "Sol Grail", "Jeweled Amulet", "Diamond Kaleidoscope", "Cadaverous Bloom"],
        ["Mountain", "Swamp"],
    )
    stone = _payload(sid, placed["Fellwar Stone"])
    assert _asked(stone) == {"modal": False, "fan": ["B", "R"], "splits": None}
    assert _asked(_payload(sid, placed["Sol Grail"]))["fan"] is None
    amulet = _payload(sid, placed["Jeweled Amulet"])
    for index in (0, 1):
        assert _asked({**amulet, "__abilityIndex": index})["fan"] is None, index
    kaleidoscope = _payload(sid, placed["Diamond Kaleidoscope"])
    assert _asked({**kaleidoscope, "__abilityIndex": 0})["fan"] is None
    bloom = _payload(sid, placed["Cadaverous Bloom"])
    assert _asked(bloom)["splits"] == [{"B": 2}, {"G": 2}]


@needs_node
def test_the_client_asks_the_type_of_the_land_the_cost_named():
    sid, game, placed = _session(
        ["Benthic Explorers"], ["Mountain", "Underground River"], tapped_theirs=True,
    )
    benthic = _payload(sid, placed["Benthic Explorers"])
    river, mountain = placed["Underground River"], placed["Mountain"]
    assert _asked(benthic, river.permanent_id)["fan"] == ["U", "B", "C"]
    assert _asked(benthic, mountain.permanent_id)["fan"] is None


def test_the_card_s_text_is_no_longer_read_for_a_colour():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[2] / "web" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    assert "function cardRequiresManaColorChoice" not in source
    start = app_js_function_body("startActivationPrompt")
    assert "answeredCostPermanentId(permanentIndex, abilityIndex)" in start
    # The land Squandered Resources sacrifices is picked on the board, and its
    # type is asked after it.
    cast_target = app_js_function_body("resolvePendingCastTarget")
    assert re.search(r"manaForChosenCost\(\s*chosenAbilityMana\(", cast_target)
    assert "...(pending.extraFields || {})" in app_js_function_body("resolvePendingManaColor")

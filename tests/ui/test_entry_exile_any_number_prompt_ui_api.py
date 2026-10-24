"""The "exile any number of cards from your graveyard as it enters" prompt on
the wire (Sutured Ghoul, Judgment).

The engine arms the same ``entry_exile`` prompt Frankenstein's Monster does,
with no count owed (``any_number``). The renderer's ``count`` is then 0, and a
client gating its Confirm on ``count`` alone offers exactly one answer — exile
nothing, which enters the Ghoul as a 0/0 that dies. So the payload says
``any_number`` outright, and this holds the server half: the flag is sent, the
legal positions are the creature cards only, and an answer of any size up to
them is accepted by the action the client sends. The browser half — a Confirm
ready at every selection size when ``any_number`` is set — is ``app.js``'s
``entryExileConfirmState``, run in ``tests/ui/test_jud_w2g1_client_ui_api.py``.
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from web.prompt_cards import _entry_exile
from web.prompts import PromptContext

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)


def _ghoul_entering(graveyard):
    p0 = PlayerState(
        name="P0", hand=[_POOL["Sutured Ghoul"]],
        graveyard=[_POOL[name] for name in graveyard],
        library=[_POOL["Swamp"]] * 3,
    )
    p1 = PlayerState(name="P1", library=[_POOL["Forest"]] * 3)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.queue_from_hand(0, "Sutured Ghoul")
    game.resolve_top_of_stack()
    return game


def _rendered(game) -> dict:
    queued = [c for c in game.pending_choices if c.kind == "entry_exile"]
    assert queued, game.log[-4:]
    ctx = PromptContext(
        game=game, viewer_seat=0,
        serialize_card=lambda card: {"name": card.name},
        seat_type=lambda _seat: "human",
    )
    return _entry_exile(ctx, queued)


def test_the_any_number_entry_exile_says_so_on_the_wire():
    game = _ghoul_entering(["Grizzly Bears", "Lightning Bolt", "Hill Giant"])
    payload = _rendered(game)

    assert payload["any_number"] is True
    assert payload["count"] == 0
    assert payload["counters"] == []
    assert payload["legal_indices"] == [0, 2]
    assert [card["name"] for card in payload["cards"]] == [
        "Grizzly Bears", "Lightning Bolt", "Hill Giant",
    ]


def test_frankensteins_monster_s_exact_count_is_not_any_number():
    p0 = PlayerState(
        name="P0", hand=[_POOL["Frankenstein's Monster"]],
        graveyard=[_POOL["Grizzly Bears"], _POOL["Hill Giant"]],
        library=[_POOL["Swamp"]] * 3,
    )
    game = Game(players=[p0, PlayerState(name="P1")])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.queue_from_hand(0, "Frankenstein's Monster", x_value=1)
    game.resolve_top_of_stack()

    assert _rendered(game)["any_number"] is False


def test_an_any_number_answer_of_any_size_is_accepted_through_the_action():
    from types import SimpleNamespace

    from web.action_prompt_answers import _action_entry_exile_confirm

    for picks in ([], [0], [0, 2]):
        game = _ghoul_entering(["Grizzly Bears", "Lightning Bolt", "Hill Giant"])
        request = SimpleNamespace(
            seat=0,
            entry_exile_picks=[
                SimpleNamespace(index=index, counter=None) for index in picks
            ],
        )
        _action_entry_exile_confirm(SimpleNamespace(game=game), request, "human")
        assert not [c for c in game.pending_choices if c.kind == "entry_exile"]
        assert len(game.players[0].exile) == len(picks)

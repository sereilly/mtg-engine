"""The "as this enters, choose …" prompt, rendered in every shape it is armed in.

Found by W2G5 while adding the sixth shape (Shimmer's land type). The renderer
subscripted ``data["needs_color"]`` and Runed Halo's arming passes no such key —
so an interactive seat that resolved Runed Halo got a ``KeyError`` out of the
whole state payload. Not a card that does the wrong thing: a game that cannot be
read, so the choice cannot be shown, so it cannot be answered, so the game stops.

The engine cannot see this. `_resolve_enter_choice` is happy, the choice queues
correctly, and every engine-side test of Runed Halo passes — the defect lives
entirely in the *presentation* of a prompt one arming shapes differently from
the others. So the guard renders the payload each arming really produces, rather
than a payload written here to look like one.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import _mk_card
from web.prompts import PromptContext, _enter_choice


@pytest.fixture(scope="module")
def pool():
    found: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            found.setdefault(card.name, card)
    return found


#: One card per shape the arming takes, by the key it passes. Named cards rather
#: than invented ones: what is being checked is that a real arming's data
#: renders, and an invented payload would be this file writing the bug out of
#: existence.
_SHAPES = [
    ("Black Vise", "an opponent"),
    ("Jihad", "an opponent and a colour"),
    ("Psychic Allergy", "a colour"),
    ("Runed Halo", "a card name"),
    ("An-Zerrin Ruins", "a creature type"),
    ("Illusionary Terrain", "two basic land types"),
    ("Shimmer", "a land type"),
    # The two shapes whose *offer* the sentence prints rather than a catalog
    # (W4G4). They reuse the colour and land-type armings with an options list,
    # so what this guard is checking is that the narrowed arming still renders
    # — a list on one arming and not the others is exactly the shape that broke
    # Runed Halo.
    ("Mangara's Equity", "one of two printed colours"),
    ("Roots of Life", "one of two printed land types"),
]


@pytest.mark.parametrize("name,shape", _SHAPES)
def test_every_enter_choice_arming_renders(pool, name, shape):
    card = pool.get(name)
    assert card is not None, f"{name} is not in the pool"
    entering = Permanent(card=card)
    bystander = Permanent(card=_mk_card("Bear", "Creature - Bear", ""))
    forest = Permanent(card=_mk_card("Forest", "Basic Land - Forest", ""))
    # Three seats, because Black Vise only asks when there is more than one
    # opponent to ask about — with two players its choice is forced and never
    # queued, and the shape would go untested while looking covered.
    game = Game(players=[
        PlayerState(name="P1", battlefield=[entering]),
        PlayerState(name="P2", battlefield=[bystander, forest]),
        PlayerState(name="P3"),
    ])
    game.enforce_mana_costs = False
    # Interactive, so the prompt is *queued* rather than defaulted at arm — the
    # queued prompt is the only one anybody ever renders.
    game.interactive_seats = {0}
    game._initialize_permanent_state(entering, 0, 1)

    queued = [c for c in game.pending_choices if c.kind == "enter_choice"]
    assert queued, f"{name} armed no enter choice ({shape})"

    ctx = PromptContext(
        game=game,
        viewer_seat=0,
        serialize_card=lambda card: {"name": card.name},
        seat_type=lambda seat: "human",
    )
    payload = _enter_choice(ctx, queued)

    assert payload["card_name"] == name

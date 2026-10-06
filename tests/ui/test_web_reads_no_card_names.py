"""The web layer decides nothing by what a card is called.

``tests/engine/test_card_name_reads.py`` holds ``engine/`` to "card names live
only in ``card_hooks.py``". It does not walk ``web/`` — and it would not have
seen the worst of what was there if it had, because it looks for a comparison
against ``<something>.name`` and the web's first offender compared a bare
``card_name`` string. Three name-keyed decisions sat in this package:

* ``action_helpers._default_target`` — the seat a cast that named none is aimed
  at was the caster's for **Ancestral Recall, Healing Salve and Stream of
  Life** and the opponent's for every other card, including every other
  printing of their sentences (Inspiration, Stroke of Genius).
* ``serialization._gloom_white_tax`` — the cost shown in a hand added three for
  a white spell while a permanent **named Gloom** was on the battlefield. Chill
  ("Red spells cost {2} more to cast") showed the printed cost and charged the
  taxed one.
* ``turn_steps._has_island_sanctuary`` — whether to ask a human seat about
  skipping its draw was a comparison against **Island Sanctuary**'s name, a
  second copy of the hook registry the engine reads.

(The last two were known: ``tests/engine/test_printed_name_reads.py`` does walk
``web/`` for ``.card.name`` reads, and held each at a ratchet of one as a fix
"nothing can exercise" — true of an enchantment being *copied*, which is the
question that guard asks, and not of the sentence being printed on a second
card, which is this one's. The first was visible to neither guard.)

Each is derived now from the compiled program, the engine's cost-tax table and
the engine's own reader of its hook. This file is the guard — a scan of every
comparison under ``web/`` — and the behavioural halves, each given an invented
card with the same printed text, because a fix that only works for the named
card is a hook in disguise.
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import CardDefinition, Permanent
from web import action_helpers, turn_steps
from web.app import app, store

client = TestClient(app)

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"
#: A basic land's name is also its subtype — the engine guard's exemption, for
#: the engine guard's reason.
BASIC_LANDS = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest"})


def _literals(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return [
            item.value for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    return []


def test_no_comparison_under_web_names_a_card(catalog):
    """Every ``ast.Compare`` in ``web/*.py``, whatever its other operand looks
    like: a card's name on either side is a card deciding behaviour.

    Wider than the engine's scan on purpose. That one requires a ``.name``
    read beside the literal, because ``engine/`` is full of words that are also
    card names ("Sacrifice", "Channel"); this package compares far fewer
    strings, and its first offender — ``card_name in {…}`` — had no ``.name``
    in it at all. Three on the tree this was written against.
    """
    names = frozenset(card.name for card in catalog) - BASIC_LANDS
    files = sorted(WEB.rglob("*.py"))
    compared = 0
    offenders = []
    for path in files:
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Compare):
                continue
            compared += 1
            for operand in (node.left, *node.comparators):
                for literal in _literals(operand):
                    if literal in names:
                        offenders.append(
                            f"{path.relative_to(WEB.parent).as_posix()}:{node.lineno} "
                            f"{literal!r} — {lines[node.lineno - 1].strip()}"
                        )
    # The floors: a scan that found no files, or no comparisons, passes blind.
    assert len(files) >= 15, len(files)
    assert compared >= 500, compared
    assert not offenders, "\n".join(offenders)


# -- the default seat of a cast that named none ----------------------------------


def _card(name: str, type_line: str, text: str, *, colors=(), mana_cost="") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(len(mana_cost) // 3),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _default_seat(card, *, mode_index=None, caster=0) -> int:
    players = [PlayerState(name="P1"), PlayerState(name="P2")]
    players[caster].hand.append(card)
    game = Game(players=players)
    request = SimpleNamespace(from_zone=None, mode_index=mode_index)
    return action_helpers._default_target(game, caster, card.name, request)


@pytest.mark.parametrize("name, mode", [
    # The three the set named…
    ("Ancestral Recall", None), ("Healing Salve", 0), ("Healing Salve", 1),
    ("Stream of Life", None),
    # …and four it did not, printing the same sentences.
    ("Inspiration", None), ("Stroke of Genius", None), ("Natural Spring", None),
    ("Braingeyser", None),
])
def test_a_gift_to_a_player_defaults_to_the_caster(catalog_by_name, name, mode):
    for caster in (0, 1):
        assert _default_seat(
            catalog_by_name[name], mode_index=mode, caster=caster
        ) == caster, name


@pytest.mark.parametrize("name", [
    "Lightning Bolt", "Mind Twist", "Kaervek's Spite", "Duress", "Terror",
])
def test_anything_else_keeps_the_opposing_default(catalog_by_name, name):
    for caster in (0, 1):
        assert _default_seat(catalog_by_name[name], caster=caster) == 1 - caster, name


def test_an_invented_card_with_ancestral_recalls_text_defaults_the_same_way():
    """Not in the set, not in the pool, and aimed where the sentence says."""
    gift = _card("Borrowed Insight", "Instant", "Target player draws three cards.")
    assert _default_seat(gift) == 0
    assert _default_seat(gift, caster=1) == 1

    # "Target **opponent** draws": the caster is not a seat the phrase admits.
    curse = _card("Unwanted Insight", "Instant", "Target opponent draws three cards.")
    assert _default_seat(curse) == 1

    # A card this cannot find in the zone it is cast from keeps the default.
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    request = SimpleNamespace(from_zone=None, mode_index=None)
    assert action_helpers._default_target(game, 0, "Borrowed Insight", request) == 1


# -- the cost a hand shows --------------------------------------------------------


def _session():
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_ai", "host_name": "H", "host_colors": 2,
              "guest_colors": 2, "seed": 5},
    ).json()
    session = store.get(created["session_id"])
    session.current_turn = 0
    return created["session_id"], session.game


def _shown(sid, name):
    state = client.get(f"/api/sessions/{sid}/state", params={"seat": 0}).json()
    return next(c for c in state["players"][0]["hand"] if c["name"] == name)


def test_the_hand_shows_what_chill_charges(set_pool):
    """"Red spells cost {2} more to cast." (Chill.) Gloom's sentence with
    another colour and another number — shown at its printed cost, before."""
    lea = set_pool("LEA")
    sid, game = _session()
    game.players[1].battlefield = [Permanent(card=set_pool("TMP")["Chill"])]
    game.players[0].battlefield = []
    game.players[0].hand = [lea["Lightning Bolt"], lea["Holy Strength"], lea["Mountain"]]
    game._sync_control()

    bolt = _shown(sid, "Lightning Bolt")
    assert (bolt["printed_mana_cost"], bolt["mana_cost"], bolt["cost_increased"]) == (
        "{R}", "{2}{R}", True,
    )
    assert _shown(sid, "Holy Strength")["cost_increased"] is False
    # A land is played, not cast (CR 305.1): no tax can be owed on it.
    assert _shown(sid, "Mountain")["cost_increased"] is False


def test_an_invented_card_with_glooms_text_taxes_the_hand_too(set_pool):
    """The sentence under a name the old comparison never matched."""
    lea = set_pool("LEA")
    pall = _card(
        "Pall of Night", "Enchantment", "White spells cost {3} more to cast.",
        colors=("B",),
    )
    sid, game = _session()
    game.players[0].battlefield = [Permanent(card=pall)]
    game.players[0].hand = [lea["Holy Strength"], lea["Lightning Bolt"]]
    game._sync_control()

    strength = _shown(sid, "Holy Strength")
    assert (strength["mana_cost"], strength["cost_increased"]) == ("{3}{W}", True)
    assert _shown(sid, "Lightning Bolt")["cost_increased"] is False


# -- the draw-step question -------------------------------------------------------


def test_the_draw_skip_question_is_the_engines_to_answer(set_pool):
    """The web asks the engine's reader of its own hook, and the two cannot
    disagree: the seat controlling Island Sanctuary is asked, the other is
    not, and a board without one asks nobody."""
    lea = set_pool("LEA")
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    assert not turn_steps._has_island_sanctuary(game, 0)

    game._put_permanent_onto_battlefield(0, Permanent(card=lea["Island Sanctuary"]), None)
    for seat in (0, 1):
        assert turn_steps._has_island_sanctuary(game, seat) is (seat == 0)
        assert game.may_skip_draw_for_protection(seat) is (seat == 0)

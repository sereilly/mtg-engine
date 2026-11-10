"""What a seat nobody asks discards: what a card costs to lose, and what the
discard pays the seat that caused it (``ai_prompt_picks.discard_order``,
``discard_worth``, ``graveyard_keeps``; ``ai_prompt_readers.
discard_pays_its_cause``).

* **A graveyard road back** — flashback (CR 702.34a), or an ability of the
  card's own that returns it from the graveyard (Eternal Dragon) — keeps a
  share of the card: a Firebolt discarded is a Firebolt cast later for
  {4}{R}. The worth order alone kept the Firebolt and discarded a Grizzly
  Bears beside it.
* **A payoff to the cause** — "You gain 3 life for each land card discarded
  this way" (Gerrard's Verdict) — is part of what each matching card costs
  an opponent of the caster to discard, priced on the standing's scale: a
  spare land still goes at twenty life, and is held back when three life is
  worth more than the spell beside it.
"""

from __future__ import annotations

from functools import lru_cache

from engine import faces
from engine.ai_prompt_picks import discard_worth, graveyard_keeps, held_worth
from engine.ai_prompt_readers import discard_pays_its_cause
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState

from tests.helpers import _nosick, settle


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _table(*, hand=(), opponent_hand=(), mine=(), theirs=(), library=()):
    catalog = _catalog()
    island = catalog["Island"]
    game = Game(players=[
        PlayerState(name="A", hand=[catalog[n] for n in hand],
                    library=[catalog[n] for n in library] + [island] * 10),
        PlayerState(name="B", hand=[catalog[n] for n in opponent_hand], library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=catalog[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game.start_turn(0)
    settle(game)
    return game


def test_every_graveyard_road_back_is_read_off_the_program():
    """The census: every shipped card with flashback, and every card whose own
    ability returns it from the graveyard, keeps a share of its worth when
    discarded — and a card with neither keeps none."""
    game = _table()
    cards = sorted(_catalog().values(), key=lambda card: card.name)
    kept = [unit.name for unit in faces.compilation_units(cards) if graveyard_keeps(game, 0, unit)]
    assert len(kept) >= 50, len(kept)
    assert {"Firebolt", "Engulfing Flames", "Eternal Dragon", "Ashen Ghoul"} <= set(kept)
    assert "Lightning Bolt" not in kept and "Grizzly Bears" not in kept
    firebolt = _catalog()["Firebolt"]
    assert discard_worth(game, 0, firebolt) < held_worth(game, 0, firebolt)


def test_careful_study_discards_its_firebolt_before_a_creature_that_is_simply_gone():
    """Careful Study draws a Raging Goblin and a Mons's Goblin Raiders beside
    a Firebolt and a Grizzly Bears: the seat discards the Firebolt — still a
    Firebolt cast later for its flashback cost — and one goblin, keeping the
    Bears and the other. Validated backwards: on 59f133e63 it discarded both
    goblins, the cards worth least to hold, and kept the Firebolt it could
    have had from the graveyard."""
    game = _table(
        hand=["Careful Study", "Firebolt", "Grizzly Bears"],
        mine=["Mountain", "Mountain", "Island"], theirs=["Grizzly Bears"],
        library=["Raging Goblin", "Mons's Goblin Raiders"],
    )
    assert game.queue_from_hand(0, "Careful Study").supported
    settle(game)
    graveyard = [card.name for card in game.players[0].graveyard]
    assert "Firebolt" in graveyard
    hand = sorted(card.name for card in game.players[0].hand)
    assert "Grizzly Bears" in hand and len(hand) == 2 and "Firebolt" not in hand


def _verdict(caster_life: int):
    game = _table(
        hand=["Gerrard's Verdict"],
        opponent_hand=["Giant Growth", "Mountain", "Holy Strength", "Shivan Dragon"],
        mine=["Plains", "Swamp"], theirs=["Mountain", "Mountain", "Forest"],
    )
    game.players[0].life = caster_life
    assert game.queue_from_hand(0, "Gerrard's Verdict", target_player_index=1).supported
    settle(game)
    return game


def test_gerrards_verdict_is_answered_by_what_three_life_is_worth_to_the_caster():
    """The reader: Gerrard's Verdict pays its caster for each land card
    discarded, three life a land on the standing's scale. Driven: B holds a
    Giant Growth it cannot use, a Mountain, a Holy Strength and a Shivan Dragon.
    Against a caster at twenty B lets the spare Mountain go (three life is
    little there); against a caster at one, three life is worth more than the
    Holy Strength and B keeps the land. Validated backwards: on 59f133e63 the
    Mountain went both times — the discard prompt carried no source card and
    no reader asked what the discard paid."""
    verdict = _catalog()["Gerrard's Verdict"]
    pays = discard_pays_its_cause(verdict)
    assert pays is not None
    game = _table()
    assert pays.matches(_catalog()["Mountain"], game, game.players[1])
    assert not pays.matches(_catalog()["Holy Strength"], game, game.players[1])
    assert pays.worth(game, 0) > 0
    rich = _verdict(20)
    assert sorted(c.name for c in rich.players[1].graveyard) == ["Giant Growth", "Mountain"]
    assert rich.players[0].life == 23
    poor = _verdict(1)
    assert sorted(c.name for c in poor.players[1].graveyard) == ["Giant Growth", "Holy Strength"]
    assert poor.players[0].life == 1

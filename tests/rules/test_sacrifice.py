"""CR 701.21 — Sacrifice, and what follows from it being a zone change.

"To sacrifice a permanent, its controller moves it from the battlefield
directly to its owner's graveyard" (CR 701.21a). Every clause of that sentence
has a consequence somewhere else in the rules, and the engine used to satisfy
them unevenly: thirteen sites performed a sacrifice, seven of them by appending
a card to some player's graveyard list instead of going through the
leaves-the-battlefield transition. What those seven skipped is what this file
tests — the owner lookup (CR 400.3), token cessation (CR 704.5d), and above all
CR 700.4, which says a permanent put into a graveyard from the battlefield
*dies*, so everything counting deaths must count a sacrifice.

They are rules tests rather than card tests because none of them is about a
card: they are about what the word "sacrifice" means, and the cards below are
only the shortest way to reach it.
"""

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.tokens import make_token_card

_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _duel(*names: str) -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


def _put(game: Game, player: PlayerState, name: str) -> Permanent:
    perm = Permanent(card=_LEA[name])
    player.battlefield.append(perm)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# ---------------------------------------------------------------------------
# A sacrifice is a death
# ---------------------------------------------------------------------------


@pytest.mark.cr("700.4", "701.21a")
def test_a_creature_sacrificed_to_pay_a_cost_has_died():
    """CR 700.4: *dies* means "is put into a graveyard from the battlefield",
    and CR 701.21a's sacrifice does exactly that — so the two counters that
    answer "how many creatures died this turn" must both move.

    Sacrifice's own additional cost is the shortest path to a cost-paid
    sacrifice in the shipped pool. Scavenging Ghoul is the card that can tell
    the difference: its corpse counters come from the game-wide count.
    """
    game, p1, _p2 = _duel()
    _put(game, p1, "Grizzly Bears")
    p1.hand = [_LEA["Sacrifice"]]

    game.cast_from_hand(0, "Sacrifice")

    assert [p.card.name for p in p1.battlefield] == []
    assert game.creatures_died_this_turn == 1
    assert p1.creatures_died_under_your_control_this_turn == 1


@pytest.mark.cr("700.4", "701.21a")
def test_a_creature_sacrificed_on_upkeep_has_died():
    """The same rule reached down the other path that skipped it. Phantasmal
    Forces sacrifices *itself* for an unpaid upkeep, which is still a permanent
    moving from the battlefield to a graveyard."""
    game, p1, _p2 = _duel()
    _put(game, p1, "Phantasmal Forces")

    game.resolve_upkeep(0)

    assert [p.card.name for p in p1.battlefield] == []
    assert game.creatures_died_this_turn == 1


# ---------------------------------------------------------------------------
# Whose graveyard, and whether there is a card to put in it
# ---------------------------------------------------------------------------


@pytest.mark.cr("400.3", "701.21a", "108.3")
def test_a_stolen_permanent_is_sacrificed_into_its_owners_graveyard():
    """"…directly to its **owner's** graveyard" (CR 701.21a), which is a
    different player from the one doing the sacrificing whenever the permanent
    was stolen (CR 400.3 / 108.3).

    Control Magic steals the Forces; the thief then owes its upkeep and cannot
    pay, so the thief sacrifices a card they do not own. The card belongs in the
    owner's graveyard, and the thief's stays empty.
    """
    game, thief, owner = _duel()
    forces = _put(game, owner, "Phantasmal Forces")
    magic = _put(game, thief, "Control Magic")
    assert game.take_control(forces, 0, source=magic)
    assert game.controller_index_of(forces) == 0
    assert game.owner_index_of(forces) == 1

    game.resolve_upkeep(0)

    assert [c.name for c in owner.graveyard] == ["Phantasmal Forces"]
    assert [c.name for c in thief.graveyard] == []


@pytest.mark.cr("704.5d", "701.21a", "111.7")
def test_a_sacrificed_token_ceases_to_exist():
    """A token that leaves the battlefield ceases to exist (CR 111.7) and the
    state-based action then removes it from the graveyard (CR 704.5d) — the net
    effect being that no card arrives there, because a token was never a card.

    Reached through the same cost-paid sacrifice as the death test above: the
    site that skipped the transition also skipped this, and appended the token's
    stand-in card into the graveyard as though it were one.
    """
    game, p1, _p2 = _duel()
    token = Permanent(card=make_token_card("Bear Token", 2, 2, "Creature — Bear"))
    token.metadata["is_token"] = True
    p1.battlefield.append(token)
    p1.hand = [_LEA["Sacrifice"]]

    game.cast_from_hand(0, "Sacrifice")

    assert [p.card.name for p in p1.battlefield] == []
    assert [c.name for c in p1.graveyard] == ["Sacrifice"], (
        "the token is not a card and leaves nothing behind"
    )


# ---------------------------------------------------------------------------
# What a sacrifice is *not*
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.21a", "701.19a")
def test_regeneration_does_not_save_a_sacrificed_creature():
    """"Sacrificing a permanent doesn't destroy it, so regeneration or other
    effects that replace destruction can't affect this action" (CR 701.21a).

    The shield is armed the way a regeneration effect arms it and then simply
    never consulted: the sacrifice does not go through the destruction sweeps
    that offer it. Pinned here rather than asserted in a comment, because the
    seam that made every sacrifice one function is exactly the place a future
    "let it regenerate" convenience would be added by mistake.
    """
    game, p1, _p2 = _duel()
    bears = _put(game, p1, "Grizzly Bears")
    bears.regeneration_shield = 1
    p1.hand = [_LEA["Sacrifice"]]

    game.cast_from_hand(0, "Sacrifice")

    assert [p.card.name for p in p1.battlefield] == []
    assert [c.name for c in p1.graveyard] == ["Grizzly Bears", "Sacrifice"]
    assert bears.regeneration_shield == 1, "the shield was never spent"

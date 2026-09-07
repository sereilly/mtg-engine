"""Stronghold sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G4: library, graveyard and unusual costs ---

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path

_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g4_duel(hand: list) -> tuple[Game, PlayerState, PlayerState]:
    caster, victim = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, caster, victim


def test_g4_mulch_sorts_the_revealed_four_by_card_type(set_pool):
    """"Reveal the top four cards of your library. Put all land cards revealed
    this way into your hand and the rest into your graveyard."

    Wood Sage's sorted reveal with the predicate printed on the card instead of
    read out of an earlier step's chosen name — so the sentence needs no
    producer and cannot be silently emptied by one going missing. The fifth
    card is never seen: the pile is the printed number, not the library.
    """
    game, caster, _ = _g4_duel([set_pool("STH")["Mulch"]])
    caster.library = [
        _G4_LEA[name] for name in
        ("Forest", "Black Lotus", "Mountain", "Healing Salve", "Mox Pearl")
    ]

    result = game.cast_from_hand(0, "Mulch")
    game.resolve_top_of_stack()

    assert result.supported, result.details
    assert [c.name for c in caster.hand] == ["Forest", "Mountain"]
    assert [c.name for c in caster.graveyard] == [
        "Black Lotus", "Healing Salve", "Mulch",
    ]
    assert [c.name for c in caster.library] == ["Mox Pearl"]


def test_g4_mulch_over_a_short_library_reveals_what_is_there(set_pool):
    """CR 701.20 shows what the library holds; fewer cards than the printed
    number is an ordinary board and never a draw from an empty library."""
    game, caster, _ = _g4_duel([set_pool("STH")["Mulch"]])
    caster.library = [_G4_LEA["Plains"], _G4_LEA["Black Lotus"]]

    game.cast_from_hand(0, "Mulch")
    game.resolve_top_of_stack()

    assert [c.name for c in caster.hand] == ["Plains"]
    assert [c.name for c in caster.graveyard] == ["Black Lotus", "Mulch"]
    assert caster.library == []


@pytest.mark.cr("701.18a", "115.1")
def test_g4_ransack_scries_five_on_the_targeted_player_s_library(set_pool):
    """"Look at the top five cards of target player's library. Put any number
    of them on the bottom of that library in any order and the rest on top of
    the library in any order."

    Coral Fighters' offer at a size where the printed words have to change —
    with one card there is nothing to count and nothing to order. One decision
    either way, so both reach the same prompt: which of the looked-at cards go
    to the bottom, and in what order the rest go back.
    """
    game, caster, victim = _g4_duel([set_pool("STH")["Ransack"]])
    victim.library = [
        _G4_LEA[name] for name in
        ("Black Lotus", "Healing Salve", "Forest", "Mox Pearl", "Mountain",
         "Island")
    ]

    spec = game.cast_target_spec(0, set_pool("STH")["Ransack"])
    assert spec["kind"] == "player"

    result = game.cast_from_hand(0, "Ransack", target_player_index=1)
    game.resolve_top_of_stack()
    assert result.supported, result.details

    pending = game.pending_scry
    assert pending is not None
    assert pending["top_count"] == 5
    assert pending["library_index"] == 1, "the victim's library, not the caster's"
    assert pending["caster_index"] == 0, "and the caster makes the choices"

    # The first two looked-at cards to the bottom, the rest back on top
    # reversed: one permutation plus a bottom count, exactly as a scry is.
    assert game.confirm_scry(0, [4, 3, 2, 1, 0], 2)
    assert [c.name for c in victim.library] == [
        "Mountain", "Mox Pearl", "Forest", "Island", "Healing Salve",
        "Black Lotus",
    ]
    assert caster.library == [], "nothing was done to the caster's own deck"


@pytest.mark.cr("601.2c", "701.13a")
def test_g4_cannibalize_exiles_one_of_two_and_grows_the_other(set_pool):
    """"Choose two target creatures controlled by the same player. Exile one of
    those creatures and put two +1/+1 counters on the other."

    Retribution's decomposition one verb over: the pick among the chosen set is
    an ordinary ``choose_permanent`` prompt and the exile acts on the recorded
    id. Two differences, and both are printed. "The same **player**" narrows no
    controller at all, so the caster may aim it at their own board — the
    relation is between the targets, not a restriction on either. And nothing
    names a chooser, so CR 608.2c makes it the spell's controller rather than
    Retribution's "that player".
    """
    from engine.models import Permanent
    from engine.named_counters import counters_on

    game, caster, victim = _g4_duel([set_pool("STH")["Cannibalize"]])
    first = Permanent(card=_G4_LEA["Hurloon Minotaur"])
    second = Permanent(card=_G4_LEA["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, first, None)
    game._put_permanent_onto_battlefield(1, second, None)

    result = game.cast_from_hand(
        0, "Cannibalize", target_player_index=1,
        target_permanent_ids=[first.permanent_id, second.permanent_id],
    )
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert [c.name for c in victim.exile] == ["Hurloon Minotaur"]
    survivors = [(p.card.name, counters_on(p, "+1/+1")) for p in victim.battlefield]
    assert survivors == [("Grizzly Bears", 2)]


@pytest.mark.cr("601.2c")
def test_g4_cannibalize_needs_both_targets_under_one_seat(set_pool):
    """"…**the same** player". The relation is what the word buys, so an
    announcement naming one creature on each side is illegal (CR 601.2c) — and
    the caster's *own* pair is legal, which is the half a reading borrowed from
    Retribution's "the same opponent" would have got wrong."""
    from engine.models import Permanent

    def _board():
        game, caster, victim = _g4_duel([set_pool("STH")["Cannibalize"]])
        mine = Permanent(card=_G4_LEA["Mons's Goblin Raiders"])
        also_mine = Permanent(card=_G4_LEA["Grizzly Bears"])
        theirs = Permanent(card=_G4_LEA["Hurloon Minotaur"])
        game._put_permanent_onto_battlefield(0, mine, None)
        game._put_permanent_onto_battlefield(0, also_mine, None)
        game._put_permanent_onto_battlefield(1, theirs, None)
        return game, caster, mine, also_mine, theirs

    game, _caster, mine, _also, theirs = _board()
    assert not game.cast_from_hand(
        0, "Cannibalize", target_player_index=1,
        target_permanent_ids=[theirs.permanent_id, mine.permanent_id],
    ).supported, "one from each seat is not 'the same player'"

    game, caster, mine, also_mine, _theirs = _board()
    assert game.cast_from_hand(
        0, "Cannibalize", target_player_index=0,
        target_permanent_ids=[mine.permanent_id, also_mine.permanent_id],
    ).supported, "'the same player' includes the caster"
    game.resolve_top_of_stack()
    assert len(caster.exile) == 1

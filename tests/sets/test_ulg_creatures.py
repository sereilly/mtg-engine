"""Urza's Legacy creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: a keyword chosen from a printed list, on the removal side ---
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g2_removal_pool():
    """Every shipped card by name, for the creature the Sponge points at.

    Memoized on the function, and read through the manifest rather than a
    spelled-out filename — `set_pool("ULG")` cannot supply a card from another
    set and the victim has to have the keywords the Sponge takes away.
    """
    cached = getattr(_g2_removal_pool, "_g2_victims", None)
    if cached is None:
        cached = {}
        for path in manifest_set_paths():
            for card in load_cards(path):
                cached.setdefault(card.name, card)
        _g2_removal_pool._g2_victims = cached
    return cached


def _g2_sponge_board(set_pool, victim_name, *, interactive=False):
    """The Sponge on Alice's board and *victim_name* on Bob's."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    sponge = Permanent(card=set_pool("ULG")["Walking Sponge"])
    game._put_permanent_onto_battlefield(0, sponge, None)
    sponge.metadata["summoning_sickness_turn"] = -99
    victim = Permanent(card=_g2_removal_pool()[victim_name])
    game._put_permanent_onto_battlefield(1, victim, None)
    return game, sponge, victim


def test_walking_sponge_takes_away_one_keyword_not_three(set_pool):
    """"{T}: Target creature loses **your choice of** flying, first strike, or
    trample until end of turn."

    CR 608.2d: the pick is announced while the effect is applied, so the card
    removes *one* of the three. The four printed words were unread on this side
    of the layer — the grant reads them (Alchemist's Gift) and the removal did
    not — and the connective went with them, so the tuple the lowering received
    could not tell "or" from "and".
    """
    game, _, angel = _g2_sponge_board(set_pool, "Serra Angel")
    assert angel.has_keyword("flying") and angel.has_keyword("vigilance")

    result = game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert not angel.has_keyword("flying")
    assert angel.has_keyword("vigilance"), "a keyword the card never named"


def test_walking_sponge_offers_all_three_to_an_interactive_seat(set_pool):
    """The choice reaches its player as the mode prompt every nested "or"
    already uses, so no new pending-choice kind and no new renderer were needed
    — and the ability stays on the stack while the prompt is owed (CR 608.2,
    CR 117.3b)."""
    game, _, knight = _g2_sponge_board(
        set_pool, "White Knight", interactive=True
    )
    game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )

    game.resolve_top_of_stack()

    (prompt,) = game.pending_choices
    assert prompt.kind == "mode_choice"
    assert prompt.data["labels"] == ["flying", "first strike", "trample"]
    assert len(game.stack) == 1, "the ability waits for the answer"


def test_walking_sponge_removes_the_keyword_its_player_named(set_pool):
    """The answer is honoured rather than defaulted: an interactive seat that
    names "first strike" takes first strike, where the headless default takes
    the first printed option."""
    game, _, knight = _g2_sponge_board(
        set_pool, "White Knight", interactive=True
    )
    assert knight.has_keyword("first strike")
    game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game.resolve_top_of_stack()

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    resolve_stack(game)

    assert not knight.has_keyword("first strike")


def test_walking_sponge_leaves_a_creature_with_none_of_the_three_alone(set_pool):
    """The control. A removal that wrote the word regardless would pass every
    test above; this one asserts the Sponge changes nothing it did not name."""
    game, _, bears = _g2_sponge_board(set_pool, "Grizzly Bears")

    game.activate_permanent_ability(
        0, "Walking Sponge", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)

    assert not bears.has_keyword("flying")
    assert not bears.has_keyword("first strike")
    assert not bears.has_keyword("trample")
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

"""Urza's Legacy instants.

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


# --- W1G5: zones — hands, graveyards, libraries ---
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec

from tests.helpers import resolve_stack


def _g5_two_seats(p1: PlayerState, p2: PlayerState) -> Game:
    """Two seats with mana enforcement off and nobody interactive.

    Kept apart from the sorcery file's twin so a mechanical union cannot splice
    one body onto the other's signature.
    """
    board = Game(players=[p1, p2])
    board.enforce_mana_costs = False
    board.interactive_seats = set()
    return board


def test_w1g5_harmonic_convergence_tucks_every_enchantment_under_its_own_owner(
    set_pool,
):
    """"Put all enchantments on top of **their owners' libraries**." A sweep, so
    nothing is chosen and no picker is raised — and each permanent follows its
    own owner (CR 400.3) rather than the caster.

    The refusal that stood before this named counters the sentence never
    mentions, which is the probe order above the zone-move production rather
    than a diagnosis. Two real gaps sat behind it: the plural destination had no
    spelling, and the tuck lowering read only a chosen target.
    """
    pool = set_pool("ULG")
    lea = set_pool("LEA")
    p1 = PlayerState(
        name="P1", hand=[pool["Harmonic Convergence"]], library=[lea["Island"]] * 3,
    )
    p2 = PlayerState(name="P2", library=[lea["Forest"]] * 3)
    game = _g5_two_seats(p1, p2)
    mine = Permanent(card=lea["Black Ward"])
    theirs = Permanent(card=lea["Instill Energy"])
    bear = Permanent(card=lea["Grizzly Bears"])
    game.players[0].battlefield.extend([mine, bear])
    game.players[1].battlefield.append(theirs)
    game._sync_control()

    result = game.cast_from_hand(0, "Harmonic Convergence")
    resolve_stack(game)

    assert result.supported is True
    # The creature is untouched; each enchantment is on **its own** owner's pile.
    assert [p.card.name for p in game.players[0].battlefield] == ["Grizzly Bears"]
    assert game.players[1].battlefield == []
    assert game.players[0].library[0].name == "Black Ward"
    assert game.players[1].library[0].name == "Instill Energy"


def test_w1g5_harmonic_convergence_announces_nothing(set_pool):
    """A sweep chooses no target (CR 115.1), so no picker is derived — the
    opposite direction from the Roots class and just as load-bearing: a spec
    here would raise a picker the client must fill for a spell that names
    nothing."""
    card = set_pool("ULG")["Harmonic Convergence"]

    assert derive_cast_spec(card, compile_card_oracle(card)) is None


def test_w1g5_repopulate_shuffles_only_the_creature_cards_of_the_named_seat(
    set_pool,
):
    """"…from **target player's** graveyard into **that player's** library." Two
    possessives naming one seat, and the seat is the whole of what this spell
    announces — which is why it was in the Roots class with a picker of None."""
    pool = set_pool("ULG")
    lea = set_pool("LEA")
    p1 = PlayerState(name="P1", hand=[pool["Repopulate"]], library=[lea["Island"]] * 5)
    p2 = PlayerState(
        name="P2",
        graveyard=[lea["Grizzly Bears"], lea["Lightning Bolt"], lea["Serra Angel"]],
        library=[lea["Forest"]] * 5,
    )
    game = _g5_two_seats(p1, p2)

    result = game.cast_from_hand(0, "Repopulate", target_player_index=1)
    resolve_stack(game)

    assert result.supported is True
    assert [c.name for c in game.players[1].graveyard] == ["Lightning Bolt"]
    assert len(game.players[1].library) == 7
    # The caster's own library is untouched: the sentence names one seat twice.
    assert len(game.players[0].library) == 5


def test_w1g5_repopulate_offers_a_seat_picker(set_pool):
    """The finding this card was on the picker sweep for: the cards are
    *described* and nobody picks one, but the seat whose two zones they move
    between is chosen, and without a spec the client sent a bare cast."""
    card = set_pool("ULG")["Repopulate"]

    assert derive_cast_spec(card, compile_card_oracle(card)) == {"kind": "player"}

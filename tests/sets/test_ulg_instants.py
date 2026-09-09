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


# --- W1G2: "each of them" — a pronoun for the sentence before's two targets ---
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g2_pump_pool():
    """Every shipped card by name, for the creatures Hope and Glory untaps.

    Memoized on the function and read through the manifest, never a spelled-out
    filename: the two creatures come from another set, so `set_pool("ULG")`
    cannot supply them.
    """
    cached = getattr(_g2_pump_pool, "_g2_targets", None)
    if cached is None:
        cached = {}
        for path in manifest_set_paths():
            for card in load_cards(path):
                cached.setdefault(card.name, card)
        _g2_pump_pool._g2_targets = cached
    return cached


def _g2_two_tapped_creatures(set_pool, *, tapped=True):
    """Alice with two tapped creatures and Hope and Glory in hand."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    pool = _g2_pump_pool()
    first = Permanent(card=pool["Grizzly Bears"])
    second = Permanent(card=pool["Hill Giant"])
    game._put_permanent_onto_battlefield(0, first, None)
    game._put_permanent_onto_battlefield(0, second, None)
    first.tapped = second.tapped = tapped
    alice.hand.append(set_pool("ULG")["Hope and Glory"])
    return game, first, second


def test_hope_and_glory_untaps_two_and_pumps_both(set_pool):
    """"Untap two target creatures. **Each of them** gets +1/+1 until end of
    turn."

    Two sentences, and the second names what the first chose. A line's sentences
    are parsed independently, so nothing inside "each of them gets +1/+1" can
    see back that far — and the phrase is not a subject this grammar reads at
    all, so the whole card refused at "expected a subject".
    """
    game, bears, giant = _g2_two_tapped_creatures(set_pool)

    result = game.cast_from_hand(
        0, "Hope and Glory",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    resolve_stack(game)

    assert result.supported, result.details
    assert not bears.tapped and not giant.tapped
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert (giant.effective_power, giant.effective_toughness) == (4, 4)


def test_hope_and_glory_pumps_the_creatures_it_untapped(set_pool):
    """The binding, asserted against the alternative it replaced: a bare
    re-parse of the second sentence would announce targets of its own, and a
    pronoun read as the source would pump the spell — which is nothing at all.
    Both steps carry the *same* chosen targets, so a third creature standing
    beside them is untouched."""
    game, bears, giant = _g2_two_tapped_creatures(set_pool)
    bystander = Permanent(card=_g2_pump_pool()["Hill Giant"])
    game._put_permanent_onto_battlefield(0, bystander, None)
    bystander.tapped = True

    game.cast_from_hand(
        0, "Hope and Glory",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    resolve_stack(game)

    assert bystander.tapped
    assert (bystander.effective_power, bystander.effective_toughness) == (3, 3)


def test_hope_and_glory_asks_for_its_two_targets_once(set_pool):
    """CR 601.2c chooses the targets once, when the spell is announced. Both
    instructions carry the identical `targets` payload, so the picker offers one
    two-creature choice rather than one per sentence."""
    game, bears, giant = _g2_two_tapped_creatures(set_pool)

    spec = game.cast_target_spec(0, set_pool("ULG")["Hope and Glory"])

    assert spec["max_targets"] == 2
    assert {target["name"] for target in spec["valid_targets"]} == {
        "Grizzly Bears", "Hill Giant"
    }


# --- W1G1: a quantity the sentence that spends it produced ---
#
# Last-Ditch Effort — "Sacrifice any number of creatures. Last-Ditch Effort
# deals that much damage to any target." "Any number" prints no count, so the
# number the damage reads exists nowhere until the seat has answered — and by
# then the creatures are cards in a graveyard (CR 400.7).

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack as _g1i_resolve


def _g1i_board(set_pool, creatures=3, *, interactive=()):
    """Seat 0 holding Last-Ditch Effort behind *creatures* bodies.

    ``_g1i_`` prefixed and ending on ``return game, game.players[0], game.players[1]``
    — SET_PLAYBOOK.md's note about a union splicing one helper onto another.
    """
    bear = set_pool("LEA")["Grizzly Bears"]
    seat0 = PlayerState(
        name="G1I-A",
        hand=[set_pool("ULG")["Last-Ditch Effort"]],
        battlefield=[Permanent(card=bear) for _ in range(creatures)],
    )
    seat1 = PlayerState(name="G1I-B")
    game = Game(players=[seat0, seat1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, game.players[0], game.players[1]


def test_g1_last_ditch_effort_deals_one_per_creature_given_up(set_pool):
    """"That much" names the sacrifice in front of it, and what it counts is
    what the seat actually gave up rather than what it was offered — two of the
    three go, and two damage lands."""
    game, mine, theirs = _g1i_board(set_pool, interactive=(0,))

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    offer = game.pending_sacrifice_state()
    assert offer["up_to"] is True and offer["count"] == 3, (
        '"any number" is a ceiling the whole board answers, not an amount'
    )
    assert game.confirm_sacrifice(0, [0, 1])
    _g1i_resolve(game)

    assert len(list(game.controlled_by(0))) == 1, "two went"
    assert theirs.life == 18


def test_g1_last_ditch_effort_gives_up_the_whole_board(set_pool):
    """The control on the count: three creatures is three damage, so nothing
    about the number is the printed one — the card prints none."""
    game, mine, theirs = _g1i_board(set_pool, interactive=(0,))

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    assert game.confirm_sacrifice(0, [0, 1, 2])
    _g1i_resolve(game)

    assert list(game.controlled_by(0)) == []
    assert theirs.life == 17


def test_g1_last_ditch_effort_declined_by_a_headless_seat_deals_none(set_pool):
    """"Any number" includes none, which is the stated ``up_to`` policy — a
    seat merely offered the chance gives up nothing, and the count behind it is
    zero rather than the board's size."""
    game, mine, theirs = _g1i_board(set_pool)

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    _g1i_resolve(game)

    assert len(list(game.controlled_by(0))) == 3, "nothing was given up"
    assert theirs.life == 20


def test_g1_last_ditch_effort_over_an_empty_board_deals_none(set_pool):
    """Nothing to offer, nothing asked, and a count off a record nothing wrote
    is zero rather than a number the card never named."""
    game, mine, theirs = _g1i_board(set_pool, creatures=0, interactive=(0,))

    game.cast_from_hand(0, "Last-Ditch Effort", target_player_index=1)
    _g1i_resolve(game)

    assert game.pending_sacrifice_state() is None
    assert theirs.life == 20

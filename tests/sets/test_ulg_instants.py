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

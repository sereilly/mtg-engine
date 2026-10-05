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


# --- INV W1G6: a count of "each creature attacking you" ---
# Found by Invasion's colour-choice round: a count whose noun phrase names no
# controller was scoped to the caster's own battlefield.
from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent


def test_w1g6_blessed_reversal_counts_the_creatures_attacking_its_caster(set_pool):
    """A shipped card this round's count fix found (Urza's Legacy): "You gain 3
    life for each creature attacking you." The count was scoped to the
    caster's own battlefield, where nothing attacking the caster ever is, so
    it gained nothing. Two attackers and one creature that stayed home: 6."""
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    game.enforce_mana_costs = False
    for seat, names in ((0, ["Grizzly Bears", "Hill Giant", "Llanowar Elves"]), (1, ["Grizzly Bears"])):
        for name in names:
            perm = _W1G6Permanent(card=lea[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0, 1])[0]
    game.players[1].hand.append(set_pool("ULG")["Blessed Reversal"])
    from tests.helpers import resolve_stack

    assert game.queue_from_hand(1, "Blessed Reversal").supported
    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (20, 26)

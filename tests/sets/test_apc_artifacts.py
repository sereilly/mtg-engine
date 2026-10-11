"""Apocalypse artifacts (artifact creatures included).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

import pytest as _w1g8_pytest

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.replacements import discard_to_battlefield as _w1g8_discard_to_battlefield
from engine.replacements import replacement_claims_line as _w1g8_claims_line
from tests.helpers import _mk_card as _w1g8_mk_card
from tests.helpers import resolve_stack as _w1g8_resolve_stack

# Where the cards these tests borrow from other sets were first printed. Every
# other name is Apocalypse's.
_W1G8_HOMES = {
    "Forest": "LEA", "Island": "LEA", "Grizzly Bears": "LEA",
    "Library of Leng": "LEA", "Wheel of Fortune": "LEA", "Mind Rot": "7ED",
    "Hymn to Tourach": "FEM", "Coercion": "TMP", "Megrim": "STH",
    "Thrill of Possibility": "M21",
}
_W1G8_RICH = {"W": 9, "U": 9, "B": 9, "R": 9, "G": 9}
_W1G8_DODECAPOD_LINE = (
    "If a spell or ability an opponent controls causes you to discard this "
    "card, put it onto the battlefield with two +1/+1 counters on it instead "
    "of putting it into your graveyard."
)


def _w1g8_card(set_pool, name: str):
    return set_pool(_W1G8_HOMES.get(name, "APC"))[name]


def _w1g8_duel(set_pool, *, hand=(), opp_hand=(), interactive=()) -> _w1g8_Game:
    forest = _w1g8_card(set_pool, "Forest")
    me = _w1g8_PlayerState(
        name="Me", hand=[_w1g8_card(set_pool, n) for n in hand], library=[forest] * 12,
    )
    opp = _w1g8_PlayerState(
        name="Opp", hand=[_w1g8_card(set_pool, n) for n in opp_hand],
        library=[forest] * 12,
    )
    game = _w1g8_Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    me.mana_pool.update(_W1G8_RICH)
    opp.mana_pool.update(_W1G8_RICH)
    return game


def _w1g8_put(game, set_pool, seat: int, name: str) -> _w1g8_Permanent:
    perm = _w1g8_Permanent(card=_w1g8_card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, perm, None)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g8_names(cards) -> list[str]:
    return [getattr(entry, "card", entry).name for entry in cards]


def _w1g8_settle(game) -> None:
    """Resolve the stack and take every owed default, as a headless seat's
    loop does between actions."""
    _w1g8_resolve_stack(game)
    game.auto_resolve_pending_choices()
    game.auto_resolve_pending_replacement_choices()
    _w1g8_resolve_stack(game)


def _w1g8_dodecapods(game, seat: int) -> list[tuple[int, int]]:
    return [
        (perm.effective_power, perm.effective_toughness)
        for perm in game.controlled_by(seat) if perm.card.name == "Dodecapod"
    ]


# --- Dodecapod -------------------------------------------------------------------


def test_w1g8_dodecapod_is_supported_by_the_replacement_table_and_nothing_else(set_pool):
    """Its whole text is one CR 614 replacement, so no instruction compiles:
    the line is claimed by ``replacement_claims_line`` through the reader the
    interceptor itself asks, and the card is an artifact creature with that
    static line."""
    program = _w1g8_compile(_w1g8_card(set_pool, "Dodecapod"))
    assert program.supported
    assert [i.kind for i in program.instructions] == ["static_line"]
    assert _w1g8_claims_line(_W1G8_DODECAPOD_LINE)
    assert _w1g8_discard_to_battlefield(_W1G8_DODECAPOD_LINE) == {
        "counters": {"+1/+1": 2},
    }


def test_w1g8_dodecapod_chosen_as_an_opponents_discard_enters_as_a_five_five(set_pool):
    """"If a spell or ability an opponent controls causes you to choose a card
    to discard and you discard Dodecapod, you'll put it onto the battlefield."
    Mind Rot is the opponent's; I pick the Dodecapod and a Forest. One enters
    with its two counters, the other is in the graveyard — and both were
    discarded."""
    game = _w1g8_duel(
        set_pool, hand=["Dodecapod", "Forest", "Island"], opp_hand=["Mind Rot"],
        interactive=(0, 1),
    )
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_discard(0, [0, 1])

    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert _w1g8_names(game.players[0].graveyard) == ["Forest"]
    assert _w1g8_names(game.players[0].hand) == ["Island"]
    assert any(
        "discarded Dodecapod, which was put onto the battlefield" in line
        for line in game.log
    )


def test_w1g8_dodecapod_taken_at_random_or_by_the_opponents_pick_still_enters(set_pool):
    """Nobody on my side chose: Hymn to Tourach takes it at random and
    Coercion's caster picks it out of my revealed hand. Two different discard
    paths in the engine, one printed condition."""
    game = _w1g8_duel(set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Hymn to Tourach"])
    assert game.queue_from_hand(1, "Hymn to Tourach", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert _w1g8_names(game.players[0].graveyard) == ["Forest"]

    game = _w1g8_duel(
        set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Coercion"], interactive=(0, 1),
    )
    assert game.queue_from_hand(1, "Coercion", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_revealed_hand_pick(1, 0)
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert game.players[0].graveyard == []
    assert _w1g8_names(game.players[0].hand) == ["Forest"]


def test_w1g8_dodecapod_discarded_by_its_owners_own_doing_goes_to_the_graveyard(set_pool):
    """The restriction is the card: "a spell or ability **an opponent**
    controls". My own Mind Rot, my own Wheel of Fortune, a cost I chose to pay
    and the cleanup step's hand size are none of them that, and each puts it
    in the graveyard like any other card."""
    # My own spell, aimed at me.
    game = _w1g8_duel(set_pool, hand=["Mind Rot", "Dodecapod", "Forest"])
    assert game.queue_from_hand(0, "Mind Rot", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == []
    assert "Dodecapod" in _w1g8_names(game.players[0].graveyard)

    # My own spell that makes *each* player discard.
    game = _w1g8_duel(set_pool, hand=["Wheel of Fortune", "Dodecapod"])
    assert game.queue_from_hand(0, "Wheel of Fortune").supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == []
    assert "Dodecapod" in _w1g8_names(game.players[0].graveyard)

    # A cost (CR 601.2h): nothing caused it but the player paying.
    game = _w1g8_duel(set_pool, hand=["Thrill of Possibility", "Dodecapod"])
    assert game.queue_from_hand(0, "Thrill of Possibility", cost_hand_index=1).supported
    assert _w1g8_dodecapods(game, 0) == []
    assert _w1g8_names(game.players[0].graveyard) == ["Dodecapod"]

    # CR 514.1: the cleanup step's discard is a turn-based action.
    forest = _w1g8_card(set_pool, "Forest")
    game = _w1g8_duel(set_pool, hand=["Dodecapod"])
    game.players[0].hand.extend([forest] * 7)
    game.resolve_cleanup_step(0, discard_hand_indices=[0])
    assert _w1g8_dodecapods(game, 0) == []
    assert _w1g8_names(game.players[0].graveyard) == ["Dodecapod"]


def test_w1g8_the_opponents_wheel_puts_dodecapod_onto_the_battlefield(set_pool):
    """The mirror of the case above: the same spell, cast by the other seat,
    and now an opponent's spell is what discards my hand."""
    game = _w1g8_duel(set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Wheel of Fortune"])
    assert game.queue_from_hand(1, "Wheel of Fortune").supported
    _w1g8_settle(game)

    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert _w1g8_names(game.players[0].graveyard) == ["Forest"]
    assert len(game.players[0].hand) == 7


def test_w1g8_a_dodecapod_put_onto_the_battlefield_was_still_discarded(set_pool):
    """"If you discard Dodecapod and put it onto the battlefield, you've still
    discarded it. Abilities that trigger whenever you discard a card will
    trigger." Megrim deals its 2; and a sentence counting what was discarded
    counts it — Gerrard's Verdict sees two cards go, one of them a land."""
    game = _w1g8_duel(set_pool, hand=["Dodecapod"], opp_hand=["Mind Rot"])
    _w1g8_put(game, set_pool, 1, "Megrim")
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)]
    assert game.players[0].life == 18, game.log

    game = _w1g8_duel(
        set_pool, hand=["Dodecapod", "Forest"], opp_hand=["Gerrard's Verdict"],
    )
    assert game.queue_from_hand(1, "Gerrard's Verdict", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)]
    assert game.players[0].hand == []
    assert game.players[1].life == 23, "one land card among the two discarded"


def test_w1g8_library_of_leng_and_dodecapod_contend_for_one_discard(set_pool):
    """Both replace where the discarded card goes (CR 616.1): a seat that is
    asked may take the Library's offer instead, and a seat nobody asks gets the
    creature."""
    game = _w1g8_duel(
        set_pool, hand=["Dodecapod"], opp_hand=["Mind Rot"], interactive=(0, 1),
    )
    _w1g8_put(game, set_pool, 0, "Library of Leng")
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_discard(0, [0], to_library=True)
    assert _w1g8_dodecapods(game, 0) == []
    assert game.players[0].library[0].name == "Dodecapod"

    game = _w1g8_duel(set_pool, hand=["Dodecapod"], opp_hand=["Hymn to Tourach"])
    _w1g8_put(game, set_pool, 0, "Library of Leng")
    assert game.queue_from_hand(1, "Hymn to Tourach", target_player_index=0).supported
    _w1g8_settle(game)
    assert _w1g8_dodecapods(game, 0) == [(5, 5)], game.log
    assert game.players[0].library[0].name == "Forest"


def test_w1g8_the_sentence_without_counters_is_the_same_replacement(set_pool):
    """The counters are payload: the sentence is printed without them too
    (Loxodon Smiter's wording), and an invented card carrying it enters as
    printed — no name is read anywhere."""
    text = (
        "If a spell or ability an opponent controls causes you to discard this "
        "card, put it onto the battlefield instead of putting it into your "
        "graveyard."
    )
    assert _w1g8_discard_to_battlefield(text) == {"counters": {}}
    smiter = _w1g8_mk_card(
        name="Probe Smiter", mana_cost="{1}{G}{W}", type_line="Creature — Elephant",
        oracle_text=text, power=4, toughness=4,
    )
    assert _w1g8_compile(smiter).supported

    game = _w1g8_duel(set_pool, opp_hand=["Mind Rot"])
    game.players[0].hand.append(smiter)
    assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
    _w1g8_settle(game)

    assert [
        (perm.card.name, perm.effective_power, perm.effective_toughness)
        for perm in game.controlled_by(0)
    ] == [("Probe Smiter", 4, 4)], game.log


@_w1g8_pytest.mark.parametrize("text", [
    # A number word the entry reader does not know: claiming the line would
    # put the creature in play with no counters, or with a guessed number.
    "If a spell or ability an opponent controls causes you to discard this card, "
    "put it onto the battlefield with umpteen +1/+1 counters on it instead of "
    "putting it into your graveyard.",
    # Another destination is another effect.
    "If a spell or ability an opponent controls causes you to discard this card, "
    "put it onto the battlefield instead of putting it into your library.",
    # "You" discarding for any reason is a wider condition than the card's.
    "If you discard this card, put it onto the battlefield instead of putting "
    "it into your graveyard.",
])
def test_w1g8_a_discard_replacement_the_interceptor_cannot_perform_is_not_claimed(text):
    assert _w1g8_discard_to_battlefield(text) is None
    assert not _w1g8_claims_line(text)
    probe = _w1g8_mk_card(
        name="Probe", mana_cost="{4}", type_line="Artifact Creature — Golem",
        oracle_text=text, power=3, toughness=3,
    )
    assert not _w1g8_compile(probe).supported

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

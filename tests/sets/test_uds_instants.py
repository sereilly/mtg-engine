"""Urza's Destiny instants.

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

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: name-matched search, graveyards and libraries ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


@pytest.fixture
def _g2i_lea(set_pool):
    """One Alpha card by name — the piles these instants read need several
    copies of one card, which the UDS pool can supply but not readably."""
    return lambda name: set_pool("LEA")[name]


def _g2i_seats(*players):
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


def test_scour_strips_every_copy_of_the_enchantment_it_exiles(set_pool, _g2i_lea):
    """Eradicate's sentence over enchantments — one production, one word
    apart, so the test that matters is that the *noun* did not leak."""
    aura = _g2i_lea("Animate Dead")
    salve = _g2i_lea("Healing Salve")
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Scour"]]),
        PlayerState(
            name="G2i-B", battlefield=[Permanent(card=aura)],
            hand=[aura, salve], graveyard=[aura], library=[aura, salve],
        ),
    )
    assert game.queue_from_hand(
        0, "Scour", target_player_index=1, target_permanent_index=0,
    ).details == "queued"
    resolve_stack(game)
    victim = game.players[1]
    assert [p.card.name for p in victim.battlefield] == []
    assert sorted(c.name for c in victim.exile) == ["Animate Dead"] * 4
    assert sorted(c.name for c in victim.hand) == ["Healing Salve"]
    assert sorted(c.name for c in victim.library) == ["Healing Salve"]


def test_quash_exiles_the_countered_card_and_its_copies(set_pool, _g2i_lea):
    """"Counter target instant or sorcery spell. Search its controller's
    graveyard, hand, and library for all cards with the same name as that
    spell and exile them."

    The countered card is in the graveyard by the time the search runs
    (CR 701.6a), so it is one of the copies the strip takes — which is the
    thing a test written from the printed sentence alone would get wrong.
    """
    bolt = _g2i_lea("Lightning Bolt")
    salve = _g2i_lea("Healing Salve")
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Quash"]]),
        PlayerState(
            name="G2i-B", hand=[bolt, salve], graveyard=[bolt, salve],
            library=[bolt, salve],
        ),
    )
    assert game.queue_from_hand(1, "Lightning Bolt").details == "queued"
    assert game.queue_from_hand(0, "Quash", target_stack_index=0).details == "queued"
    resolve_stack(game)
    victim = game.players[1]
    # The one in the graveyard, the one in the library, and the one it
    # countered — which is in the graveyard by then. The hand's copy is the one
    # that was cast, so three is every copy that existed when the search ran.
    assert sorted(c.name for c in victim.exile) == ["Lightning Bolt"] * 3
    assert sorted(c.name for c in victim.hand) == ["Healing Salve"]
    assert sorted(c.name for c in victim.graveyard) == ["Healing Salve"]
    assert sorted(c.name for c in victim.library) == ["Healing Salve"]


def test_rapid_decay_exiles_cards_of_any_type_from_one_pile(set_pool, _g2i_lea):
    """"Exile up to three target cards from a single graveyard."

    "Cards", with no type named — and that is the whole test. The pile the
    engine offers is read by ``graveyard_card_matches``, whose *unnarrowed*
    default is "creature card", so a lowering that simply left the type key off
    narrowed a sentence that narrows nothing: against a graveyard of lands and
    spells this reported that no graveyard held a card it could exile.
    """
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Rapid Decay"]]),
        PlayerState(
            name="G2i-B",
            graveyard=[
                _g2i_lea("Mountain"), _g2i_lea("Lightning Bolt"),
                _g2i_lea("Black Lotus"), _g2i_lea("Island"),
            ],
        ),
    )
    assert game.queue_from_hand(0, "Rapid Decay").details == "queued"
    resolve_stack(game)
    victim = game.players[1]
    assert len(victim.exile) == 3, [c.name for c in victim.exile]
    assert len(victim.graveyard) == 1
    # One pile only: the caster's own graveyard is untouched.
    assert game.players[0].exile == []


def test_rapid_decay_still_reads_a_graveyard_with_no_creature_in_it(set_pool, _g2i_lea):
    """The regression above stated as the case that used to fail outright.

    Every card in the pile is a land; the sentence names cards, so all of them
    are legal choices and the spell has a pile to open.
    """
    game = _g2i_seats(
        PlayerState(name="G2i-A", hand=[set_pool("UDS")["Rapid Decay"]]),
        PlayerState(
            name="G2i-B",
            graveyard=[_g2i_lea("Mountain"), _g2i_lea("Island")],
        ),
    )
    assert game.queue_from_hand(0, "Rapid Decay").details == "queued"
    resolve_stack(game)
    assert sorted(c.name for c in game.players[1].exile) == ["Island", "Mountain"]

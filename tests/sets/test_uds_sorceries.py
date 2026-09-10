"""Urza's Destiny sorceries.

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
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


@pytest.fixture
def _g2_lea(set_pool):
    """One Alpha card by name, for a pile that is not an Urza's Destiny card.

    The strip these five sorceries perform is about *names*, so the fixture has
    to hold several copies of one card and a few of another — which the UDS pool
    can supply but not readably.
    """
    return lambda name: set_pool("LEA")[name]


def _g2_board(set_pool, spell, victim, copies, spare):
    """Seat 0 holds *spell*; seat 1 has *victim* out, plus *copies* of it spread
    across hand, graveyard and library, and one *spare* in each zone.

    Returns the game with the spell already announced at the victim.
    """
    game = Game(players=[
        PlayerState(name="G2-A", hand=[set_pool("UDS")[spell]]),
        PlayerState(
            name="G2-B",
            battlefield=[Permanent(card=copies)],
            hand=[copies, spare],
            graveyard=[copies, spare],
            library=[copies, spare],
        ),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    result = game.queue_from_hand(
        0, spell, target_player_index=1, target_permanent_index=0,
    )
    assert result.details == "queued", result
    return game


def _g2_zones(game, seat=1):
    player = game.players[seat]
    return (
        [p.card.name for p in player.battlefield],
        sorted(c.name for c in player.hand),
        sorted(c.name for c in player.graveyard),
        sorted(c.name for c in player.library),
        sorted(c.name for c in player.exile),
    )


def test_eradicate_exiles_every_copy_of_the_creature_it_names(set_pool, _g2_lea):
    """"Exile target nonblack creature. Search its controller's graveyard,
    hand, and library for all cards with the same name as that creature and
    exile them."

    Four zones emptied of one name and nothing else touched — the spare in each
    pile is what says the search read the name rather than the zone.
    """
    bears = _g2_lea("Grizzly Bears")
    salve = _g2_lea("Healing Salve")
    game = _g2_board(set_pool, "Eradicate", bears, bears, salve)
    resolve_stack(game)
    battlefield, hand, graveyard, library, exile = _g2_zones(game)
    assert battlefield == []
    assert hand == ["Healing Salve"]
    assert graveyard == ["Healing Salve"]
    assert library == ["Healing Salve"]
    assert exile == ["Grizzly Bears"] * 4


def test_splinter_reads_the_artifact_it_exiled_not_the_creature_beside_it(set_pool, _g2_lea):
    """Splinter names an artifact, and the strip is keyed to *that* object.

    A creature copy in the same piles is the control: a strip that had read the
    zone rather than the recorded name would take it too.
    """
    lotus = _g2_lea("Black Lotus")
    bears = _g2_lea("Grizzly Bears")
    game = _g2_board(set_pool, "Splinter", lotus, lotus, bears)
    resolve_stack(game)
    _battlefield, hand, graveyard, library, exile = _g2_zones(game)
    assert hand == graveyard == library == ["Grizzly Bears"]
    assert exile == ["Black Lotus"] * 4


def test_sowing_salt_declines_a_basic_land(set_pool, _g2_lea):
    """"Exile target **nonbasic** land." The printed narrowing is enforced at
    announcement (CR 601.2c), so a board of basics leaves nothing to name."""
    mountain = _g2_lea("Mountain")
    game = Game(players=[
        PlayerState(name="G2-A", hand=[set_pool("UDS")["Sowing Salt"]]),
        PlayerState(name="G2-B", battlefield=[Permanent(card=mountain)]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    result = game.queue_from_hand(
        0, "Sowing Salt", target_player_index=1, target_permanent_index=0,
    )
    assert result.details != "queued", result
    assert game.players[1].battlefield


def test_wake_of_destruction_takes_every_land_sharing_the_targets_name(set_pool, _g2_lea):
    """"Destroy target land and all other lands with the same name as that
    land."

    Both battlefields, because "all other lands" names no seat — and the
    Islands beside them are what says the sweep read the destroyed land's name
    rather than its type.
    """
    mountain, island = _g2_lea("Mountain"), _g2_lea("Island")
    game = Game(players=[
        PlayerState(
            name="G2-A", hand=[set_pool("UDS")["Wake of Destruction"]],
            battlefield=[Permanent(card=mountain), Permanent(card=island)],
        ),
        PlayerState(
            name="G2-B",
            battlefield=[
                Permanent(card=mountain), Permanent(card=mountain),
                Permanent(card=island),
            ],
        ),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    assert game.queue_from_hand(
        0, "Wake of Destruction", target_player_index=1, target_permanent_index=0,
    ).details == "queued"
    resolve_stack(game)
    assert [p.card.name for p in game.players[0].battlefield] == ["Island"]
    assert [p.card.name for p in game.players[1].battlefield] == ["Island"]


def test_the_five_name_matched_sorceries_carry_no_card_hook(set_pool):
    """The shape is one production, not five entries.

    Each of these prints one sentence with one word changed, which is the case
    ``card_hooks`` exists *not* to take: a name-keyed entry would buy one card
    where the grammar buys every card printed the same way. Asserted rather than
    assumed, because a hook is invisible from the outside — the card reports
    supported either way.
    """
    from engine.card_hooks import CARD_LINE_INSTRUCTIONS

    hooked = set(CARD_LINE_INSTRUCTIONS)
    for name in ("Eradicate", "Scour", "Splinter", "Sowing Salt", "Quash"):
        assert compile_card_oracle(set_pool("UDS")[name]).supported, name
        assert name not in hooked, f"{name} is supported by its name"

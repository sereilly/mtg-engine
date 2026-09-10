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


# --- W1G5: player-directed effects, and a cost reduction nothing implemented ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import resolve_stack


def _g5_sorcery_game(*players: PlayerState) -> Game:
    """A duel with mana enforcement off, for this block's sorceries."""
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    return game


def _g5_onto_battlefield(game: Game, seat: int, card):
    """*card* onto *seat*'s battlefield, and the Permanent that arrived."""
    permanent = Permanent(card=card)
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return game.players[seat].battlefield[-1]


def test_fatigue_skips_the_targeted_players_draw_step_and_nobody_elses(set_pool):
    """"Target player skips their next draw step."

    The seat is a CR 115.1 *target*, not CR 109.5's controller — which is the
    whole of what the lowering could not say before: it refused every player
    reference but "you", so the card that names one was unsupported while
    ``Game.skip_next_step`` had taken a seat since Ivory Gargoyle.

    Both halves in one game, because the record is keyed by seat: the victim
    misses a draw and the caster does not.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Fatigue"])
    assert program.supported, program.reason
    # The picker has to offer a seat, or the target is unfillable in the app.
    assert derive_cast_spec(pool["Fatigue"], program) == {"kind": "player"}

    library = [set_pool("LEA")["Grizzly Bears"]] * 8
    game = _g5_sorcery_game(
        PlayerState(name="P1", hand=[pool["Fatigue"]], library=list(library), life=20),
        PlayerState(name="P2", library=list(library), life=20),
    )
    # Past CR 103.8a's skipped first draw step, so what the card takes away is
    # a step the seat would otherwise have had.
    game.turn = 2
    game.start_turn(0)
    assert game.cast_from_hand(0, "Fatigue", target_player_index=1).supported
    resolve_stack(game)
    assert game.skip_step_counts.get((1, "draw")) == 1, game.skip_step_counts

    victim_before = len(game.players[1].hand)
    caster_before = len(game.players[0].hand)
    game.start_turn(1)
    assert len(game.players[1].hand) == victim_before, game.log
    # The record is spent, not permanent: the seat's *next* draw step happens.
    game.start_turn(1)
    assert len(game.players[1].hand) == victim_before + 1, game.log
    # And it was keyed to the seat the spell named, so the caster kept theirs.
    game.start_turn(0)
    assert len(game.players[0].hand) == caster_before + 1, game.log


def test_plow_under_tucks_both_named_lands(set_pool):
    """"Put two target lands on top of their owners' libraries."

    A chosen *list*, on the several-target description a handler opts into. The
    failure it replaces is the quiet one this repo keeps naming: without the
    opt-in no target description is emitted at all, so the picker reads nothing
    and the card tucks one land of the two it prints.

    Each land goes to **its own** owner's library (CR 400.3), which is why the
    two here are on two battlefields.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Plow Under"])
    assert program.supported, program.reason

    forest = set_pool("LEA")["Forest"]
    game = _g5_sorcery_game(
        PlayerState(name="P1", hand=[pool["Plow Under"]], library=[], life=20),
        PlayerState(name="P2", library=[], life=20),
    )
    game.start_turn(0)
    mine = _g5_onto_battlefield(game, 0, forest)
    theirs = _g5_onto_battlefield(game, 1, forest)
    assert game.cast_from_hand(
        0, "Plow Under",
        target_permanent_ids=[mine.permanent_id, theirs.permanent_id],
    ).supported
    resolve_stack(game)

    assert game.players[0].battlefield == [], game.log
    assert game.players[1].battlefield == [], game.log
    assert [c.name for c in game.players[0].library] == ["Forest"], game.log
    assert [c.name for c in game.players[1].library] == ["Forest"], game.log


def test_multanis_decree_gains_two_life_per_enchantment_it_destroyed(set_pool):
    """"Destroy all enchantments. You gain 2 life for each enchantment
    destroyed this way."

    The rate is the point. The record and the loop spelling of it existed
    ("for each creature that **died** this way"); what did not was a printed
    *multiplier* on a life gain — the reader refused a printed 2 outright,
    while the counter family one file over had been minting ``ast.Times`` for
    the identical clause since Mind Maggots.

    Two enchantments and 4 life, so a dropped factor is visible: gaining 2
    would be the count read once instead of twice.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Multani's Decree"])
    assert program.supported, program.reason

    lea = set_pool("LEA")
    game = _g5_sorcery_game(
        PlayerState(name="P1", hand=[pool["Multani's Decree"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    _g5_onto_battlefield(game, 0, lea["Black Vise"])
    _g5_onto_battlefield(game, 0, lea["Crusade"])
    _g5_onto_battlefield(game, 1, lea["Fastbond"])
    assert game.cast_from_hand(0, "Multani's Decree").supported
    resolve_stack(game)

    survivors = [p.card.name for p in game.all_permanents()]
    assert survivors == ["Black Vise"], survivors
    assert game.players[0].life == 24, game.log


def test_multanis_decree_gains_nothing_when_no_enchantment_is_out(set_pool):
    """The rate over an empty record is zero, not the printed 2.

    The direction that fails silently: a multiplier applied to a base of 2
    rather than to the count would heal the caster for destroying nothing.
    """
    pool = set_pool("UDS")
    game = _g5_sorcery_game(
        PlayerState(name="P1", hand=[pool["Multani's Decree"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    assert game.cast_from_hand(0, "Multani's Decree").supported
    resolve_stack(game)
    assert game.players[0].life == 20, game.log


def test_encroach_offers_only_nonbasic_lands_from_the_revealed_hand(set_pool):
    """"Target player reveals their hand. You choose a **nonbasic land card**
    from it. That player discards that card."

    The narrowing is a printed *supertype* exclusion, which the revealed-hand
    picker could not test — and a picker that cannot test a narrowing refuses
    the line rather than offering the whole hand, which is why the card was
    unsupported rather than wrong.

    The hand holds all three kinds on purpose: a basic land, a nonbasic land
    and a creature. Only the middle one is a legal answer.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Encroach"])
    assert program.supported, program.reason

    lea = set_pool("LEA")
    victim_hand = [lea["Plains"], set_pool("ARN")["Bazaar of Baghdad"], lea["Grizzly Bears"]]
    game = _g5_sorcery_game(
        PlayerState(name="P1", hand=[pool["Encroach"]], life=20),
        PlayerState(name="P2", hand=list(victim_hand), life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    assert game.cast_from_hand(0, "Encroach", target_player_index=1).supported
    resolve_stack(game)

    choice = game.pending_choices[0]
    offered = {victim_hand[index].name for index in choice.data["legal_indices"]}
    assert offered == {"Bazaar of Baghdad"}, offered

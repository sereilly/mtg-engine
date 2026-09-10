"""Mercadian Masques artifacts.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: prevention shields and damage redirection ---
from engine import Game as _G3aGame
from engine import PlayerState as _G3aPlayerState
from engine.damage_redirects import redirects_on as _g3a_redirects_on
from engine.models import CardDefinition as _G3aCard
from engine.models import Permanent as _G3aPermanent
from tests.helpers import _damage_dealt as _g3a_dealt
from tests.helpers import resolve_stack as _g3a_resolve


def _g3a_creature(name, power=2, toughness=2):
    """A vanilla creature to take redirected damage, or to deal it."""
    line = "Creature - Test"
    return _G3aCard(
        name=name, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _g3a_board(seat0=(), seat1=()):
    """A two-seat game with the permanents already on the battlefield."""
    made = _G3aGame(players=[
        _G3aPlayerState(name="P0", battlefield=list(seat0)),
        _G3aPlayerState(name="P1", battlefield=list(seat1)),
    ])
    made.enforce_mana_costs = False
    made.interactive_seats = set()
    return made


def test_generals_regalia_moves_a_chosen_sources_damage_onto_a_named_creature(
    set_pool,
):
    """"{3}: The next time a source of your choice would deal damage to you this
    turn, that damage is dealt to target creature you control instead."

    CR 614.9's redirection, not a shield: the damage is still dealt, in full, by
    the same source, and only its recipient changes. Two announcements again —
    CR 609.7's chosen source and CR 601.2c's target — so an unnamed source is
    checked as well as the named one, because a record that answered to every
    source would move a whole turn's damage onto one creature.
    """
    regalia = _G3aPermanent(card=set_pool("MMQ")["General's Regalia"])
    taker = _G3aPermanent(card=_g3a_creature("Taker", 1, 9))
    named = _G3aPermanent(card=_g3a_creature("Named Source", 3, 3))
    other = _G3aPermanent(card=_g3a_creature("Other Source", 3, 3))
    game = _g3a_board((regalia, taker), (named, other))
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update({"generic": 3})

    result = game.activate_permanent_ability(
        0, "General's Regalia",
        target_player_index=0,
        target_permanent_ids=[taker.permanent_id],
        source_seat=1, source_permanent_index=0,
    )
    assert result.supported, result
    _g3a_resolve(game)
    assert [r.uses for r in _g3a_redirects_on(game.players[0])] == [1]

    before = game.players[0].life
    game._deal_damage_to_player(game.players[0], 2, source=other)
    assert game.players[0].life == before - 2, "an unnamed source is untouched"
    assert taker.damage_marked == 0

    game._deal_damage_to_player(game.players[0], 3, source=named)
    assert game.players[0].life == before - 2, "the named source's damage moved"
    assert taker.damage_marked == 3, "and was dealt in full to the creature"


def test_generals_regalia_will_not_move_its_damage_onto_an_opponents_creature(
    set_pool,
):
    """The printed "you control" is re-checked at resolution (CR 608.2b).

    Dropped, the ability would hand an opponent's creature the damage its
    controller was about to take, which is a strictly better card — and the
    activation, the log and the board all look the same at the moment it is
    announced.
    """
    regalia = _G3aPermanent(card=set_pool("MMQ")["General's Regalia"])
    mine = _G3aPermanent(card=_g3a_creature("Mine", 1, 9))
    theirs = _G3aPermanent(card=_g3a_creature("Theirs", 1, 9))
    game = _g3a_board((regalia, mine), (theirs,))
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update({"generic": 3})

    game.activate_permanent_ability(
        0, "General's Regalia",
        target_player_index=1,
        target_permanent_ids=[theirs.permanent_id],
        source_seat=1, source_permanent_index=0,
    )
    _g3a_resolve(game)

    assert _g3a_redirects_on(game.players[0]) == []


def test_crumbling_sanctuary_exiles_a_library_instead_of_dealing_damage(
    set_pool,
):
    """"If damage would be dealt to a player, that player exiles that many cards
    from the top of their library instead."

    CR 614's substitution: the damage never happens, so no life is lost and
    nothing that watches damage to a player fires. The sentence narrows neither
    end, so it is symmetric — both seats pay — which is the half a reader keyed
    to the artifact's controller would drop while the card still looked right
    from one side of the table.
    """
    sanctuary = _G3aPermanent(card=set_pool("MMQ")["Crumbling Sanctuary"])
    bear = _G3aPermanent(card=_g3a_creature("Bear"))
    game = _g3a_board((sanctuary,), (bear,))
    for seat in game.players:
        seat.library = [_g3a_creature(f"Card{n}") for n in range(10)]

    assert _g3a_dealt(game, game.players[0], 4, source=bear) == 0
    assert len(game.players[0].library) == 6
    assert len(game.players[0].exile) == 4

    assert _g3a_dealt(game, game.players[1], 3, source=bear) == 0, "symmetric"
    assert len(game.players[1].exile) == 3

    assert _g3a_dealt(game, bear, 4, source=bear) == 4, (
        "the sentence names a player, not a permanent"
    )


def test_crumbling_sanctuary_exiles_what_is_there_and_replaces_the_rest(
    set_pool,
):
    """CR 609.3: an effect that cannot do all of something does as much as it
    can — and "as much as it can" is a statement about the *cards*.

    A library shorter than the damage exiles its whole self and the player still
    takes nothing, which is what makes this artifact a way to lose by decking
    rather than a way to survive one more turn. Running out is not a loss until
    a draw is attempted (CR 104.3c), and this is not a draw.
    """
    sanctuary = _G3aPermanent(card=set_pool("MMQ")["Crumbling Sanctuary"])
    bear = _G3aPermanent(card=_g3a_creature("Bear"))
    game = _g3a_board((sanctuary,), (bear,))
    game.players[0].library = [_g3a_creature("Last")]

    before = game.players[0].life
    assert _g3a_dealt(game, game.players[0], 6, source=bear) == 0
    assert game.players[0].life == before, "the whole event was replaced"
    assert game.players[0].library == []
    assert len(game.players[0].exile) == 1
# --- end W1G3 ---


# --- W1G4: upkeep and end-step triggers ---
#
# Two artifacts, both of which parsed cleanly on `main` and were refused one
# layer down: the mill on a phrase the *draw* one family over already read, and
# the Atlas on a CR 603.4 condition nothing had a node for.

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack


def _g4a_card(name, type_line="Basic Land - Forest"):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name},
    )


def _g4a_duel(set_pool):
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, set_pool("MMQ")


def _g4a_run(game):
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()


def test_worry_beads_mills_the_seat_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, **that player** mills a
    card." The seat is the one the upkeep announcement froze - the same record
    the damage recipient and the draw's own reader already take of the same two
    words, and the reading the mill's comment claimed it took and did not."""
    game, p1, p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Worry Beads"]))
    p1.library = [_g4a_card("a0"), _g4a_card("a1")]
    p2.library = [_g4a_card("b0"), _g4a_card("b1")]
    game._sync_control()

    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4a_run(game)
    assert [card.name for card in p1.graveyard] == ["a0"]
    assert p2.graveyard == []

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4a_run(game)
    assert [card.name for card in p1.graveyard] == ["a0"]
    assert [card.name for card in p2.graveyard] == ["b0"]


def test_mercadian_atlas_draws_only_on_a_landless_turn(set_pool):
    """"At the beginning of your end step, **if you didn't play a land this
    turn**, you may draw a card." CR 603.4 checks the condition when the
    trigger would fire, so a turn with a land drop puts nothing on the stack at
    all."""
    game, p1, _p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Mercadian Atlas"]))
    p1.library = [_g4a_card("top"), _g4a_card("next")]
    game._sync_control()
    game.active_player_index = 0
    game.lands_played_this_turn[0] = 0
    game.resolve_end_step(0)
    _g4a_run(game)

    assert [card.name for card in p1.hand] == ["top"]


def test_a_land_drop_silences_mercadian_atlas(set_pool):
    """The other half of the same gate, read off the per-seat per-turn tally
    the land-play path writes - never off the board, because by the end step a
    land played this turn is an ordinary permanent."""
    game, p1, _p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Mercadian Atlas"]))
    p1.library = [_g4a_card("top"), _g4a_card("next")]
    game._sync_control()
    game.active_player_index = 0
    game.lands_played_this_turn[0] = 1
    game.resolve_end_step(0)
    _g4a_run(game)

    assert p1.hand == []
    assert [card.name for card in p1.library] == ["top", "next"]

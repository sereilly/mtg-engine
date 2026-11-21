"""Betrayers of Kamigawa creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

from engine import Game as _w1g1_Game, PlayerState as _w1g1_PlayerState
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import (_mk_creature_card as _w1g1_creature,
                           _nosick as _w1g1_nosick,
                           declare_attack as _w1g1_declare_attack,
                           drive_combat as _w1g1_drive_combat,
                           settle as _w1g1_settle)


def _w1g1_ninjutsu_table(
    set_pool, ninja, *, runners=1, theirs=(), their_hand=(), their_graveyard=(),
    my_graveyard=(), library=(), blocks=None,
):
    """*ninja* in P1's hand and *runners* vanilla 2/2s attacking P2, with
    *blocks* declared (none by default): the declare blockers step, blocks
    locked, the damage still to come — the window ninjutsu is printed for
    (CR 702.49a; "after blockers have been declared", 2021-03-19)."""
    pool = set_pool("BOK")
    mine = [
        _w1g1_nosick(_w1g1_Permanent(card=_w1g1_creature(f"Runner {i}", 2, 2)))
        for i in range(runners)
    ]
    defenders = [_w1g1_nosick(_w1g1_Permanent(card=c)) for c in theirs]
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P1", hand=[pool[ninja]], battlefield=mine,
            graveyard=list(my_graveyard), library=list(library), life=20,
        ),
        _w1g1_PlayerState(
            name="P2", hand=list(their_hand), battlefield=defenders,
            graveyard=list(their_graveyard),
            library=[_w1g1_creature("Filler", 1, 1)] * 5, life=20,
        ),
    ])
    game.enforce_mana_costs = False
    game._settle()
    _w1g1_declare_attack(game, 0, blocks=blocks)
    return game, mine, defenders


def _w1g1_ninjutsu(game, ninja, runner):
    """Activate *ninja*'s ninjutsu returning *runner*, and resolve it."""
    result = game.activate_from_hand(
        0, ninja, cost_permanent_ids=[runner.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_settle(game)
    entered = next(p for p in game.controlled_by(0) if p.card.name == ninja)
    return entered


def test_w1g1_ninja_of_the_deep_hours_swaps_in_and_draws_on_combat_damage(set_pool):
    """Ninjutsu {1}{U}: the unblocked Runner goes home, the Ninja enters tapped
    and attacking P2 (CR 702.49c) and deals its 2 — and "Whenever this
    creature deals combat damage to a player, you may draw a card"."""
    library = [set_pool("BOK")["Ninja of the Deep Hours"]]
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Ninja of the Deep Hours", library=[_w1g1_creature("Drawn", 1, 1)],
    )
    ninja = _w1g1_ninjutsu(game, "Ninja of the Deep Hours", mine[0])
    assert ninja.tapped and ninja.attacking and not ninja.blocked
    assert [c.name for c in game.players[0].hand] == ["Runner 0"]
    _w1g1_drive_combat(game)
    assert game.players[1].life == 18
    assert sorted(c.name for c in game.players[0].hand) == ["Drawn", "Runner 0"]
    assert library  # the pool lookup above is the card under test


def test_w1g1_mistblade_shinobi_returns_a_creature_that_player_controls(set_pool):
    """"…you may return target creature **that player** controls to its
    owner's hand." The damaged player's creature goes home; P1's own second
    attacker — a creature the sentence does not name — stays."""
    elves = _w1g1_creature("Defender", 1, 1)
    game, mine, defenders = _w1g1_ninjutsu_table(
        set_pool, "Mistblade Shinobi", runners=2, theirs=[elves],
    )
    _w1g1_ninjutsu(game, "Mistblade Shinobi", mine[0])
    _w1g1_drive_combat(game)
    assert [c.name for c in game.players[1].hand] == ["Defender"]
    assert not list(game.controlled_by(1))
    assert any(p is mine[1] for p in game.controlled_by(0))
    assert game.players[1].life == 20 - 1 - 2


def test_w1g1_walker_of_secret_ways_looks_at_that_players_hand(set_pool):
    """"Whenever this creature deals combat damage to a player, look at that
    player's hand." The damaged seat's hand, shown to P1 (a ``hand_reveal``
    prompt), never P1's own."""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Walker of Secret Ways",
        their_hand=[_w1g1_creature("Secret A", 1, 1), _w1g1_creature("Secret B", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Walker of Secret Ways", mine[0])
    shown = []
    _w1g1_drive_combat(game, answers={
        "hand_reveal": lambda g, choice: (
            shown.append((
                choice.player_index, choice.data.get("target_index"),
                list(choice.data.get("card_names") or ()),
            )),
            g.discard_pending_choice(choice),
        ),
    })
    assert shown == [(0, 1, ["Secret A", "Secret B"])]
    assert any("looked at P2's hand (2 cards)" in line for line in game.log)


def test_w1g1_walker_of_secret_ways_returns_a_ninja_only_during_your_turn(set_pool):
    """"{1}{U}: Return target Ninja you control to its owner's hand. Activate
    only during your turn." Its own body is a Ninja it controls; on P2's turn
    the clause refuses it."""
    walker_card = set_pool("BOK")["Walker of Secret Ways"]
    walker = _w1g1_nosick(_w1g1_Permanent(card=walker_card))
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(name="P1", battlefield=[walker], life=20),
        _w1g1_PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game._settle()
    game.active_player_index = 1
    game._set_phase_and_step("precombat_main", None)
    refused = game.activate_permanent_ability(
        0, "Walker of Secret Ways", target_permanent_ids=[walker.permanent_id],
    )
    assert not refused.supported
    assert any(walker is p for p in game.controlled_by(0))
    game.active_player_index = 0
    result = game.activate_permanent_ability(
        0, "Walker of Secret Ways", target_permanent_ids=[walker.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_settle(game)
    assert [c.name for c in game.players[0].hand] == ["Walker of Secret Ways"]


def test_w1g1_okiba_gang_shinobi_makes_that_player_discard_two(set_pool):
    """"…that player discards two cards." (Of three, one is left.)"""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Okiba-Gang Shinobi",
        their_hand=[_w1g1_creature(f"Card {i}", 1, 1) for i in range(3)],
    )
    _w1g1_ninjutsu(game, "Okiba-Gang Shinobi", mine[0])
    _w1g1_drive_combat(game)
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 2
    assert game.players[1].life == 17


def test_w1g1_skullsnatcher_exiles_up_to_two_from_that_players_graveyard(set_pool):
    """"…exile up to two target cards from that player's graveyard." Two of
    P2's three go to exile; P1's own graveyard is not the pile named."""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Skullsnatcher",
        their_graveyard=[_w1g1_creature(f"Dead {i}", 1, 1) for i in range(3)],
        my_graveyard=[_w1g1_creature("Mine", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Skullsnatcher", mine[0])
    _w1g1_drive_combat(game)
    assert len(game.players[1].exile) == 2
    assert len(game.players[1].graveyard) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Mine"]


def test_w1g1_throat_slitter_destroys_a_nonblack_creature_that_player_controls(set_pool):
    """"…destroy target nonblack creature that player controls." P2's
    colourless Defender dies, P2's black creature survives (nonblack), and so
    does P1's own nonblack attacker (that player)."""
    black = set_pool("BOK")["Skullsnatcher"]
    game, mine, defenders = _w1g1_ninjutsu_table(
        set_pool, "Throat Slitter", runners=2,
        theirs=[_w1g1_creature("Defender", 1, 1), black],
    )
    _w1g1_ninjutsu(game, "Throat Slitter", mine[0])
    _w1g1_drive_combat(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Skullsnatcher"]
    assert [c.name for c in game.players[1].graveyard] == ["Defender"]
    assert any(p is mine[1] for p in game.controlled_by(0))


def test_w1g1_higure_searches_for_a_ninja_card(set_pool):
    """"Whenever Higure deals combat damage to a player, you may search your
    library for a Ninja card, reveal it, put it into your hand, then
    shuffle." The Ninja comes out of a library of vanillas."""
    pool = set_pool("BOK")
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Higure, the Still Wind",
        library=[_w1g1_creature("Not A", 1, 1), pool["Skullsnatcher"],
                 _w1g1_creature("Not B", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Higure, the Still Wind", mine[0])
    _w1g1_drive_combat(game)
    assert sorted(c.name for c in game.players[0].hand) == ["Runner 0", "Skullsnatcher"]
    assert game.players[1].life == 17


def test_w1g1_higure_makes_only_a_ninja_unblockable(set_pool):
    """"{2}: Target Ninja creature can't be blocked this turn." A creature
    that is no Ninja is refused as the target; Higure, a Ninja, takes it, and
    P2's declared block on it is then refused."""
    pool = set_pool("BOK")
    higure = _w1g1_nosick(_w1g1_Permanent(card=pool["Higure, the Still Wind"]))
    other = _w1g1_nosick(_w1g1_Permanent(card=_w1g1_creature("Plain", 2, 2)))
    wall = _w1g1_nosick(_w1g1_Permanent(card=_w1g1_creature("Wall", 0, 5)))
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(name="P1", battlefield=[higure, other], life=20),
        _w1g1_PlayerState(name="P2", battlefield=[wall], life=20),
    ])
    game.enforce_mana_costs = False
    game._settle()
    refused = game.activate_permanent_ability(
        0, "Higure, the Still Wind", target_permanent_ids=[other.permanent_id],
    )
    assert not refused.supported
    result = game.activate_permanent_ability(
        0, "Higure, the Still Wind", target_permanent_ids=[higure.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_settle(game)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok
    ok, why = game.declare_blockers(1, {0: 1})
    assert ok, why


def test_w1g1_ink_eyes_reanimates_from_that_players_graveyard(set_pool):
    """"…you may put target creature card from that player's graveyard onto
    the battlefield under your control." P2's creature card comes back under
    P1."""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Ink-Eyes, Servant of Oni",
        their_graveyard=[_w1g1_creature("Fallen", 3, 3)],
        my_graveyard=[_w1g1_creature("Mine", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Ink-Eyes, Servant of Oni", mine[0])
    _w1g1_drive_combat(game)
    assert "Fallen" in [p.card.name for p in game.controlled_by(0)]
    assert not game.players[1].graveyard
    assert [c.name for c in game.players[0].graveyard] == ["Mine"]
    assert game.players[1].life == 15

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================

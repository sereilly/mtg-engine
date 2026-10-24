"""Judgment creatures (legendary ones too), for the groups whose creature
tests no longer fit beside wave 1's in ``test_jud_creatures.py`` (2,600-line
cap for a per-set file).

The same shape as that file: one marked section per group. **A group writes
only between its own markers and puts its imports at the top of its own
section**, never at the top of the file, and every module-level helper,
constant and import alias in a section carries that group's ``_w<wave>g<n>_``
prefix — the sections share one module namespace.

Cards come from ``set_pool("JUD")`` / ``set_cards("JUD")`` — never a new
``conftest.py`` fixture and never a spelled-out ``cards/*.json`` path
(``tests/sets/README.md``). Drain the stack with
``tests.helpers.resolve_stack``, never a bare ``while game.stack:`` loop. A
test asserts what a game showed (boards, zones, life, the log), not
instruction kinds alone.
"""


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

from engine import Game as _W1G10Game, PlayerState as _W1G10PlayerState
from engine.models import Permanent as _W1G10Permanent
from tests.helpers import resolve_stack as _w1g10_resolve_stack


def _w1g10_table(set_pool, *, interactive=(), libraries=None):
    """Two seats on seat 0's first main phase, mana costs not enforced."""
    island = set_pool("LEA")["Island"]
    libraries = libraries or ([island] * 10, [island] * 10)
    game = _W1G10Game(players=[
        _W1G10PlayerState(name=f"P{seat}", life=20, library=list(libraries[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g10_put(game, card, seat):
    """*card* onto *seat*'s battlefield through the entry seam, not sick."""
    permanent = _W1G10Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g10_balthor_returns_every_black_and_every_red_creature_card(set_pool):
    """"{B}{B}{B}, Exile Balthor: Each player returns all black and all red
    creature cards from their graveyard to the battlefield." The printed union
    is one set — a card that is black *or* red — so each player's black and red
    creature cards come back under their own control, while a green creature
    card and a black instant stay where they are. The cost exiles Balthor
    itself (CR 113.6m ruling, 2013-07-01: it can only be activated from the
    battlefield), so Balthor is not among the black creature cards returned."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g10_table(set_pool)
    balthor = _w1g10_put(game, jud["Balthor the Defiled"], 0)
    game.players[0].graveyard.extend(
        [lea["Black Knight"], lea["Hill Giant"], lea["Grizzly Bears"], lea["Dark Ritual"]]
    )
    game.players[1].graveyard.extend([lea["Scathe Zombies"], lea["Llanowar Elves"]])

    result = game.activate_permanent_ability(0, "Balthor the Defiled")
    assert result.supported, result.details
    # The cost is paid as the ability is activated: Balthor is in exile before
    # the ability resolves.
    assert not game.is_on_battlefield(balthor)
    assert "Balthor the Defiled" in [card.name for card in game.players[0].exile]
    _w1g10_resolve_stack(game)

    def names(seat):
        return sorted(perm.card.name for perm in game.controlled_by(seat))

    assert names(0) == ["Black Knight", "Hill Giant"]
    assert names(1) == ["Scathe Zombies"]
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Dark Ritual", "Grizzly Bears",
    ]
    assert [card.name for card in game.players[1].graveyard] == ["Llanowar Elves"]


def test_w1g10_balthor_pumps_every_minion_on_the_table(set_pool):
    """"Minion creatures get +1/+1." — every Minion, whoever controls it, and
    not Balthor (a Zombie Dwarf) or a creature of another type."""
    jud, lea = set_pool("JUD"), set_pool("LEA")
    game = _w1g10_table(set_pool)
    balthor = _w1g10_put(game, jud["Balthor the Defiled"], 0)
    mine = _w1g10_put(game, jud["Cabal Trainee"], 0)
    theirs = _w1g10_put(game, jud["Cabal Trainee"], 1)
    bears = _w1g10_put(game, lea["Grizzly Bears"], 1)
    game._settle()

    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)
    assert (balthor.effective_power, balthor.effective_toughness) == (2, 2)


def _w1g10_scalpelexis_hits(set_pool, library):
    """Scalpelexis attacks unblocked into a seat whose library is *library*
    (card names); combat damage is dealt and the trigger resolved."""
    from tests.helpers import declare_attack

    pool = {**set_pool("LEA"), **set_pool("JUD")}
    game = _w1g10_table(
        set_pool,
        libraries=([pool["Island"]] * 5, [pool[name] for name in library]),
    )
    game.interactive_seats = set()
    _w1g10_put(game, pool["Scalpelexis"], 0)
    declare_attack(game, 0)
    for _ in range(6):
        game.advance_combat_phase()
        _w1g10_resolve_stack(game)
        if game.players[1].life < 20:
            break
    _w1g10_resolve_stack(game)
    return game


def test_w1g10_scalpelexis_repeats_until_four_cards_share_no_name(set_pool):
    """"…that player exiles the top four cards of their library. If two or more
    of those cards have the same name, repeat this process." The ruling
    (2004-10-04): "repeat as often as it takes to not get a matching pair". Two
    Islands in the first four repeat it; the second four hold one Forest of
    their own — the first round's Forest is not "those cards" — so it stops
    there, with two cards left."""
    game = _w1g10_scalpelexis_hits(set_pool, [
        "Island", "Island", "Forest", "Mountain",
        "Plains", "Swamp", "Forest", "Grizzly Bears",
        "Lightning Bolt", "Hill Giant",
    ])

    assert game.players[1].life == 19
    assert [card.name for card in game.players[1].exile] == [
        "Island", "Island", "Forest", "Mountain",
        "Plains", "Swamp", "Forest", "Grizzly Bears",
    ]
    assert [card.name for card in game.players[1].library] == [
        "Lightning Bolt", "Hill Giant",
    ]
    assert game.players[0].exile == []
    assert sum("Scalpelexis: repeating" in line for line in game.log) == 1


def test_w1g10_scalpelexis_exiles_four_once_without_a_pair(set_pool):
    game = _w1g10_scalpelexis_hits(set_pool, [
        "Island", "Forest", "Mountain", "Plains", "Island", "Island",
    ])
    assert [card.name for card in game.players[1].exile] == [
        "Island", "Forest", "Mountain", "Plains",
    ]
    assert [card.name for card in game.players[1].library] == ["Island", "Island"]


def test_w1g10_scalpelexis_stops_on_an_empty_library(set_pool):
    """A pair in every round until the library runs out: the round that finds
    no card exiles nothing, has no pair, and ends the loop."""
    game = _w1g10_scalpelexis_hits(set_pool, [
        "Island", "Island", "Forest", "Mountain", "Plains", "Plains",
    ])
    assert len(game.players[1].exile) == 6
    assert game.players[1].library == []


def _w1g10_constable_hits(set_pool, *, bonus=0, interactive=()):
    """Cephalid Constable (+*bonus* power) attacks unblocked into a seat that
    controls a tapped Grizzly Bears, a Forest and a tapped Hill Giant; returns
    the game paused with the trigger on the stack, and those three."""
    from engine.pt import add_pt_modifier
    from tests.helpers import declare_attack

    pool = {**set_pool("LEA"), **set_pool("JUD")}
    game = _w1g10_table(set_pool, interactive=interactive)
    constable = _w1g10_put(game, pool["Cephalid Constable"], 0)
    theirs = []
    for name in ("Grizzly Bears", "Forest", "Hill Giant"):
        permanent = _w1g10_put(game, pool[name], 1)
        permanent.tapped = name != "Forest"
        theirs.append(permanent)
    if bonus:
        add_pt_modifier(constable, bonus, 0)
    declare_attack(game, 0)
    for _ in range(4):
        game.advance_combat_phase()
        if game.stack:
            break
    return game, theirs


def test_w1g10_cephalid_constable_returns_as_many_as_the_damage_dealt(set_pool):
    """"Whenever this creature deals combat damage to a player, return up to
    that many target permanents that player controls to their owner's hand."
    Pumped to 3 power it deals 3, and its controller is asked to name up to
    three of the **damaged player's** permanents as the trigger goes on the
    stack (CR 603.3d) — and the ones named go home.
    It returned nothing at all before: the several-target bounce asked the
    matcher about "that player" with no seat, and the matcher fails closed."""
    game, theirs = _w1g10_constable_hits(set_pool, bonus=2, interactive=(0,))
    assert game.players[1].life == 17
    prompts = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert len(prompts) == 1
    data = prompts[0].data
    assert data["max_targets"] == 3 and data["up_to"]
    assert {entry["permanent_id"] for entry in data["targets"]} == {
        permanent.permanent_id for permanent in theirs
    }
    assert game.confirm_trigger_target(
        0, permanent_ids=[theirs[0].permanent_id, theirs[2].permanent_id]
    )
    _w1g10_resolve_stack(game)

    assert sorted(card.name for card in game.players[1].hand) == [
        "Grizzly Bears", "Hill Giant",
    ]
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Forest"]


def test_w1g10_cephalid_constable_unpumped_returns_one(set_pool):
    """A 1/1 deals 1, so "that many" is one — the default answer names one of
    the damaged player's permanents and returns it."""
    game, theirs = _w1g10_constable_hits(set_pool)
    _w1g10_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g10_resolve_stack(game)
    assert game.players[1].life == 19
    assert len(game.players[1].hand) == 1
    assert len(list(game.controlled_by(1))) == 2

# ==== end W1G10 ======================================================

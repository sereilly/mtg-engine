"""Planeshift creatures.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour ---
# Becoming a colour, being one, sharing one, and protection from one. Colour is
# read through CR 613's layer 5 everywhere below (`Game._effective_colors`),
# never off the printed card: half of these tests change a colour mid-game and
# ask the card again.
import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine import targeting as _w1g6_targeting
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    """*name* from Planeshift, else Invasion, else Alpha."""
    for code in ("PLS", "INV", "LEA"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)  # _w1g6_card (creatures)


def _w1g6_table(set_pool, mine=(), theirs=(), *, mana=False, interactive=(0,)):
    """Seat 0 holds *mine* and seat 1 *theirs*, nothing summoning-sick, on
    seat 0's turn. Returns the game and the two lists of permanents."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = mana
    w1g6_game.interactive_seats = set(interactive)
    w1g6_game.active_player_index = 0
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            side.append(perm)
        w1g6_sides.append(side)
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_table (creatures)


def _w1g6_colors(game, perm):
    return sorted(game._effective_colors(perm))  # _w1g6_colors (creatures)


def _w1g6_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g6_names (creatures)


def _w1g6_ability(card, index=0):
    """The *index*-th activated ability of *card* and the picker spec the
    compiled program derives for it."""
    w1g6_ability = _w1g6_compile(card).activated_abilities[index]
    return w1g6_ability, _w1g6_targeting.derive_activation_spec(w1g6_ability)  # _w1g6_ability


def test_w1g6_disciple_of_kangee_gives_one_target_flying_and_blue_for_a_turn(set_pool):
    """"{U}, {T}: Target creature gains flying and becomes blue until end of
    turn." One target, two things said about it, one window: the red Giant
    flies and is blue (CR 105.3 — blue *instead of* red), the Bears beside it
    are untouched, the Disciple is tapped and {U} is spent, and at cleanup the
    Giant is a red ground creature again."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Disciple of Kangee", "Grizzly Bears"], ["Hill Giant"], mana=True,
    )
    disciple, bears = mine
    giant = theirs[0]
    _ability, spec = _w1g6_ability(disciple.card)
    assert spec == {"kind": "creature"}

    assert not game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
    ).supported, "no {U}, no ability"
    game.players[0].mana_pool["U"] = 1
    assert game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    assert disciple.tapped and game.players[0].mana_pool["U"] == 0
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")
    _w1g6_resolve_stack(game)

    assert _w1g6_colors(game, giant) == ["U"] and game._has_keyword(giant, "flying")
    assert _w1g6_colors(game, bears) == ["G"] and not game._has_keyword(bears, "flying")

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")


def test_w1g6_disciple_of_kangee_may_be_aimed_at_its_controllers_own_creature(set_pool):
    """The id names a battlefield as well as an object: aimed at the Bears on
    its own side, the Bears — not the opponent's Giant — fly and turn blue."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Disciple of Kangee", "Grizzly Bears"], ["Hill Giant"],
    )
    bears, giant = mine[1], theirs[0]

    assert game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)

    assert _w1g6_colors(game, bears) == ["U"] and game._has_keyword(bears, "flying")
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")


def _w1g6_libraries(game, set_pool):
    """Five Forests under seat 0 and five Islands under seat 1, so a card drawn
    names the library it left."""
    game.players[0].library.extend([_w1g6_card(set_pool, "Forest")] * 5)
    game.players[1].library.extend([_w1g6_card(set_pool, "Island")] * 5)
    return game  # _w1g6_libraries


def test_w1g6_questing_phelddagrif_gains_both_protections_and_the_opponent_gains_life(set_pool):
    """"{W}: This creature gains protection from black and from red until end
    of turn. Target opponent gains 2 life." CR 702.16g: two protection
    abilities from one list. Both colours are protected against — a red Bolt
    and a black Terror are illegal announcements — green is not, the *opponent*
    is the one two life up, and both protections are gone at cleanup."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Questing Phelddagrif"], ["Black Knight"], mana=True)
    phelddagrif = mine[0]
    game.players[1].hand.extend(
        _w1g6_card(set_pool, name) for name in ("Lightning Bolt", "Terror", "Giant Growth")
    )
    game.players[0].mana_pool["W"] = 1
    assert game._protection_colors(phelddagrif) == set()

    assert game.queue_permanent_ability(
        0, "Questing Phelddagrif", ability_index=1, target_player_index=1,
    ).supported
    assert game.players[0].mana_pool["W"] == 0
    _w1g6_resolve_stack(game)

    assert game._protection_colors(phelddagrif) == {"B", "R"}
    assert (game.players[0].life, game.players[1].life) == (20, 22)
    for name in ("Lightning Bolt", "Terror"):
        refused = game.queue_from_hand(1, name, target_permanent_ids=[phelddagrif.permanent_id])
        assert not refused.supported and "illegal target" in refused.details, (name, refused.details)
    game.players[1].mana_pool["G"] = 1
    assert game.queue_from_hand(
        1, "Giant Growth", target_permanent_ids=[phelddagrif.permanent_id],
    ).supported, "green is neither black nor red"
    _w1g6_resolve_stack(game)

    game.resolve_cleanup_step(0)
    assert game._protection_colors(phelddagrif) == set()


def test_w1g6_questing_phelddagrifs_other_two_abilities_pay_the_opponent(set_pool):
    """"{G}: … gets +1/+1 until end of turn. Target opponent creates a 1/1 green
    Hippo creature token." and "{U}: … gains flying until end of turn. Target
    opponent may draw a card." The Hippo lands on the opponent's battlefield,
    and the card is drawn **by the opponent, from the opponent's library** —
    the offered seat is the one that draws (the bare "draw a card" used to be
    read as the ability's controller's)."""
    game, mine, _theirs = _w1g6_table(set_pool, ["Questing Phelddagrif"], [], interactive=(0, 1))
    _w1g6_libraries(game, set_pool)
    phelddagrif = mine[0]

    assert game.queue_permanent_ability(
        0, "Questing Phelddagrif", ability_index=0, target_player_index=1,
    ).supported
    _w1g6_resolve_stack(game)
    assert (phelddagrif.effective_power, phelddagrif.effective_toughness) == (5, 5)
    (hippo,) = game.controlled_by(1)
    assert hippo.card.name == "Hippo Token" and _w1g6_colors(game, hippo) == ["G"]
    assert (hippo.effective_power, hippo.effective_toughness) == (1, 1)

    assert game.queue_permanent_ability(
        0, "Questing Phelddagrif", ability_index=2, target_player_index=1,
    ).supported
    game.resolve_top_of_stack()
    assert game._has_keyword(phelddagrif, "flying")
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("optional_pay", 1)]
    assert game.confirm_optional_pay(1, accept=True)
    assert [card.name for card in game.players[1].hand] == ["Island"]
    assert game.players[0].hand == [] and len(game.players[0].library) == 5


def test_w1g6_questing_phelddagrif_offers_and_requires_an_opponent_for_every_ability(set_pool):
    """Each ability's second sentence targets an opponent, so each derives the
    opponent picker and none may be aimed at its own controller. The {W} one
    derived no picker at all — its first step's positive "this targets
    nothing" ended the walk before the sentence behind it was read — and was
    activatable naming its own controller as the "opponent"."""
    card = _w1g6_card(set_pool, "Questing Phelddagrif")
    for index in range(3):
        _ability, spec = _w1g6_ability(card, index)
        assert spec == {"kind": "player", "opponents_only": True}, index

    game, _mine, _theirs = _w1g6_table(set_pool, ["Questing Phelddagrif"], [])
    for index in range(3):
        refused = game.queue_permanent_ability(
            0, "Questing Phelddagrif", ability_index=index, target_player_index=0,
        )
        assert not refused.supported, index
    assert game.stack == [] and game.players[0].life == 20


@_w1g6_pytest.mark.parametrize("name, index, announcement", [
    ("Phelddagrif", 2, {"target_player_index": 1}),
    ("Soldevi Heretic", 0, None),
])
def test_w1g6_a_shipped_target_opponent_may_draw_a_card_draws_for_the_opponent(
    set_pool, name, index, announcement,
):
    """Alliances prints the same sentence twice ("Target opponent may draw a
    card." — Phelddagrif's {U}, Soldevi Heretic's rider) and both handed the
    card to the ability's own controller. Accepted, the opponent draws from
    their own library; declined, nobody draws."""
    for accept in (True, False):
        game = _W1G6Game(players=[
            _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0, 1}
        game.active_player_index = 0
        _w1g6_libraries(game, set_pool)
        source = _W1G6Permanent(card=set_pool("ALL")[name])
        bears = _W1G6Permanent(card=_w1g6_card(set_pool, "Grizzly Bears"))
        for perm in (source, bears):
            game._put_permanent_onto_battlefield(0, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
        chosen = announcement or {"target_role_refs": [
            {"permanent_id": bears.permanent_id}, {"seat": 1},
        ]}

        assert game.queue_permanent_ability(0, name, ability_index=index, **chosen).supported
        game.resolve_top_of_stack()
        assert [(c.kind, c.player_index) for c in game.pending_choices] == [("optional_pay", 1)]
        assert game.confirm_optional_pay(1, accept=accept)

        assert [card.name for card in game.players[1].hand] == (["Island"] if accept else [])
        assert "Forest" not in [card.name for card in game.players[0].hand]
        assert len(game.players[0].library) == 5


def test_w1g6_phelddagrifs_trample_ability_now_offers_its_opponent(set_pool):
    """"{G}: Phelddagrif gains trample until end of turn. Target opponent
    creates a 1/1 green Hippo creature token." (Alliances.) The same shadowed
    picker Questing Phelddagrif's {W} had: the grant in front answered "nothing
    to point at" and the token's target was never derived."""
    ability, spec = _w1g6_ability(set_pool("ALL")["Phelddagrif"], 0)
    assert spec == {"kind": "player", "opponents_only": True}

    game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._put_permanent_onto_battlefield(
        0, _W1G6Permanent(card=set_pool("ALL")["Phelddagrif"]), None,
    )
    assert not game.queue_permanent_ability(
        0, "Phelddagrif", ability_index=0, target_player_index=0,
    ).supported
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Phelddagrif"]

"""Planeshift sorceries.

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


# --- W1G8: damage and the odd ones ---
#
# March of Souls: "Destroy all creatures. They can't be regenerated. For each
# creature destroyed this way, its controller creates a 1/1 white Spirit
# creature token with flying." The sweep and the loop were both built (Martyr's
# Cry prints the same loop over an exile with a draw inside it); what refused
# was the *token's* seat — "its controller" under a loop was read only off a
# firing event, and a sorcery has none.

from engine import Game as _w1g8s_Game, PlayerState as _w1g8s_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8s_load,  # noqa: E402
                                manifest_set_path as _w1g8s_path)
from engine.control import change_control as _w1g8s_change_control  # noqa: E402
from engine.grammar import compile_line as _w1g8s_compile_line  # noqa: E402
from engine.models import (CardDefinition as _w1g8s_Card,  # noqa: E402
                           Permanent as _w1g8s_Permanent)
from engine.oracle import compile_card_oracle as _w1g8s_compile  # noqa: E402

from tests.helpers import resolve_stack as _w1g8s_resolve_stack  # noqa: E402


def _w1g8s_lea():
    return {card.name: card for card in _w1g8s_load(_w1g8s_path("LEA"))}


def _w1g8s_body(name, power, toughness, text="", keywords=()):
    """A bare creature for a sweep to find."""
    return _w1g8s_Card(
        name=name, mana_cost="{3}", cmc=3.0, type_line="Creature - Test",
        oracle_text=text, colors=(), color_identity=(), keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )  # W1G8 sorceries: a test body


def _w1g8s_duel(mine, theirs, *, hand0=(), hand1=(), active=0, interactive=()):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_w1g8s_Permanent(card=card) for card in mine]
    board1 = [_w1g8s_Permanent(card=card) for card in theirs]
    filler = _w1g8s_body("Filler", 0, 1)
    game = _w1g8s_Game(players=[
        _w1g8s_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10),
        _w1g8s_Player(name="P1", battlefield=board1, hand=list(hand1),
                      library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G8 sorceries: the duel


def _w1g8s_spirits(game, seat):
    return [
        perm for perm in game.controlled_by(seat)
        if perm.card.name == "Spirit Token"
    ]  # W1G8 sorceries: the tokens a seat holds


def test_w1g8_march_of_souls_pays_each_controller_a_spirit_per_creature(set_pool):
    """Two of the caster's and three of the opponent's: two Spirits and three,
    each a 1/1 white flier — and created after the destruction, so they are
    there when the spell has finished."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    assert _w1g8s_compile(march).supported
    game, _, _ = _w1g8s_duel(
        [lea["Hill Giant"], lea["Grizzly Bears"]],
        [lea["Hill Giant"], lea["Grizzly Bears"], lea["Drudge Skeletons"]],
        hand0=[march],
    )

    cast = game.cast_from_hand(0, "March of Souls")
    assert cast.supported, cast.details
    _w1g8s_resolve_stack(game)
    game._settle()

    assert len(_w1g8s_spirits(game, 0)) == 2
    assert len(_w1g8s_spirits(game, 1)) == 3
    assert all(
        perm.card.name == "Spirit Token" for perm in game.all_permanents()
    ), "every creature was destroyed, the Skeletons included"
    token = _w1g8s_spirits(game, 1)[0]
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.has_keyword("flying")
    assert token.effective_colors == {"W"}
    assert token.has_type("spirit") and token.is_creature
    assert [card.name for card in game.players[1].graveyard] == [
        "Hill Giant", "Grizzly Bears", "Drudge Skeletons",
    ]


def test_w1g8_march_of_souls_cannot_be_regenerated_through(set_pool):
    """"They can't be regenerated." A regeneration shield already on a creature
    does not save it — and it is replaced by a Spirit like the rest."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    game, _, theirs = _w1g8s_duel([], [lea["Drudge Skeletons"]], hand0=[march])
    skeletons = theirs[0]

    shielded = game.activate_permanent_ability(1, "Drudge Skeletons", ability_index=0)
    assert shielded.supported, shielded.details
    _w1g8s_resolve_stack(game)

    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(skeletons)
    assert len(_w1g8s_spirits(game, 1)) == 1


def test_w1g8_march_of_souls_reads_who_controlled_it_as_it_left(set_pool):
    """"Its controller" is last known information (CR 608.2h): a creature the
    caster had taken pays the *caster* its Spirit, though the card goes to its
    owner's graveyard."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    game, _, theirs = _w1g8s_duel(
        [lea["Hill Giant"]], [lea["Grizzly Bears"]], hand0=[march],
    )
    # the two calls every control-changing handler makes, in that order: the
    # contribution, then the projection that also records who owns it
    _w1g8s_change_control(theirs[0], 0, source="test")
    game._sync_control()
    assert game.controller_index_of(theirs[0]) == 0

    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()

    assert len(_w1g8s_spirits(game, 0)) == 2
    assert _w1g8s_spirits(game, 1) == []
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_w1g8_march_of_souls_pays_only_for_what_was_destroyed(set_pool):
    """"Destroyed this way": an indestructible creature is still there and
    earns nothing, a token that is destroyed earns its controller a token, and
    an empty board resolves and makes none."""
    lea = _w1g8s_lea()
    march = set_pool("PLS")["March of Souls"]
    idol = _w1g8s_body("Stone Idol", 3, 3, "Indestructible", ("Indestructible",))
    game, mine, _ = _w1g8s_duel(
        [idol], [lea["Grizzly Bears"]], hand0=[march, march, march],
    )

    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()
    assert game.is_on_battlefield(mine[0])
    assert _w1g8s_spirits(game, 0) == []
    first = _w1g8s_spirits(game, 1)
    assert len(first) == 1

    # the Spirit is a creature too: the second March destroys it and replaces it
    assert game.cast_from_hand(0, "March of Souls").supported
    _w1g8s_resolve_stack(game)
    game._settle()
    second = _w1g8s_spirits(game, 1)
    assert len(second) == 1 and second[0] is not first[0]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"], (
        "a destroyed token ceases to exist rather than reaching the graveyard"
    )


def test_w1g8_its_controller_needs_the_loop_to_name_anybody():
    """The refusal half. Outside a "for each … this way" loop the sweep's
    per-object record is still written, and "its controller creates a token"
    would compile to a per-iteration read with no iteration round it — so the
    loop marker is what admits the words, not the record."""
    looped = _w1g8s_compile_line(
        "Destroy all creatures. For each creature destroyed this way, its "
        "controller creates a 1/1 white Spirit creature token with flying.",
        card_name="Probe",
    )
    assert not looped.parse_error and not looped.lowering_error
    bare = _w1g8s_compile_line(
        "Destroy all creatures. Its controller creates a 1/1 white Spirit "
        "creature token with flying.",
        card_name="Probe",
    )
    assert bare.parse_error or bare.lowering_error
    assert not bare.instructions

"""Invasion instants.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: colour relations ---
from engine import Game as _W1G5IGame, PlayerState as _W1G5IPlayer
from engine.models import CardDefinition as _W1G5ICard, Permanent as _W1G5IPermanent
from engine.oracle import compile_card_oracle as _w1g5i_compile
from tests.helpers import _damage_dealt as _w1g5i_damage_dealt
from tests.helpers import resolve_stack as _w1g5i_resolve_stack


def _w1g5_attacker(name, power, colors):
    """A vanilla creature of the given colours, for a shield to be aimed at."""
    return _W1G5ICard(
        name=name, mana_cost="".join("{%s}" % symbol for symbol in colors) or "{3}",
        cmc=3.0, type_line="Creature - Test", oracle_text="", colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(power)},
    )  # W1G5 instants: a source of damage


def _w1g5_ministration_table(set_pool, theirs):
    """Seat 1's turn, seat 0 holding Samite Ministration; *theirs* on seat 1's
    battlefield and unsick."""
    board = [_W1G5IPermanent(card=card) for card in theirs]
    filler = _w1g5_attacker("Filler", 1, ())
    game = _W1G5IGame(players=[
        _W1G5IPlayer(name="P0", hand=[set_pool("INV")["Samite Ministration"]],
                     library=[filler] * 10),
        _W1G5IPlayer(name="P1", battlefield=board, library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(1)
    game._close_current_priority_step()
    return game, board  # W1G5 instants: the Ministration's table


def _w1g5_minister(game, source=None):
    """Cast Samite Ministration naming *source* (or no source at all)."""
    aimed = {} if source is None else {
        "target_player_index": game.controller_index_of(source),
        "target_permanent_index": game.battlefield_index_of(source),
    }
    result = game.cast_from_hand(0, "Samite Ministration", **aimed)
    assert result.supported, result.details
    _w1g5i_resolve_stack(game)  # W1G5: the Ministration has resolved


# --- Samite Ministration ---------------------------------------------------
# "Prevent all damage that would be dealt to you this turn by a source of your
# choice. Whenever damage from a black or red source is prevented this way this
# turn, you gain that much life."


def test_w1g5_samite_ministration_stops_every_hit_from_the_chosen_red_source(set_pool):
    """The red Giant is named: its first hit, its second hit and its combat
    damage are all prevented — "all", where the one-shot shields stop at the
    first — and each prevention pays that much life, because the source is red
    (CR 615.5). Another source's damage is untouched."""
    card = set_pool("INV")["Samite Ministration"]
    program = _w1g5i_compile(card)
    assert program.supported
    from engine.targeting import derive_cast_spec

    assert derive_cast_spec(card, program)["source_of_choice"] is True

    game, (giant, bears) = _w1g5_ministration_table(
        set_pool, [_w1g5_attacker("Giant", 3, ("R",)), _w1g5_attacker("Bears", 2, ("G",))]
    )
    me = game.players[0]
    _w1g5_minister(game, giant)

    game._deal_damage_to_player(me, 3, source=giant)
    assert me.life == 23
    game._deal_damage_to_player(me, 2, source=giant)
    assert me.life == 25
    game._deal_damage_to_player(me, 2, source=bears)
    assert me.life == 23
    assert _w1g5i_damage_dealt(game, me, 3, source=giant, combat=True) == 0


def test_w1g5_samite_ministration_through_a_real_attack(set_pool):
    """The whole card in one combat: the named black 4/4 attacks unblocked, the
    damage is prevented in the combat damage step and its four points come
    back as life."""
    game, (specter,) = _w1g5_ministration_table(
        set_pool, [_w1g5_attacker("Specter", 4, ("B",))]
    )
    _w1g5_minister(game, specter)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {})[0]
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5i_resolve_stack(game)
    assert game.players[0].life == 24


def test_w1g5_samite_ministration_prevents_but_does_not_pay_for_other_colours(set_pool):
    """The rider is conditional and the prevention is not: a green source's
    damage is prevented just the same, and no life is gained. A gold
    black-green source pays — it is a black source (CR 105.2b)."""
    game, (bears,) = _w1g5_ministration_table(set_pool, [_w1g5_attacker("Bears", 2, ("G",))])
    me = game.players[0]
    _w1g5_minister(game, bears)
    game._deal_damage_to_player(me, 2, source=bears)
    assert me.life == 20

    game, (rot,) = _w1g5_ministration_table(set_pool, [_w1g5_attacker("Rot", 2, ("B", "G"))])
    me = game.players[0]
    _w1g5_minister(game, rot)
    game._deal_damage_to_player(me, 2, source=rot)
    assert me.life == 22


def test_w1g5_samite_ministration_protects_only_its_caster_and_only_this_turn(set_pool):
    """"To you": the caster's own creature is not shielded from the named
    source, and neither is the opponent. "This turn": the cleanup step ends
    it."""
    game, (giant,) = _w1g5_ministration_table(set_pool, [_w1g5_attacker("Giant", 3, ("R",))])
    me = game.players[0]
    mine = _W1G5IPermanent(card=_w1g5_attacker("Squire", 5, ("W",)))
    game._put_permanent_onto_battlefield(0, mine, None)
    _w1g5_minister(game, giant)

    assert _w1g5i_damage_dealt(game, mine, 3, source=giant) == 3
    assert _w1g5i_damage_dealt(game, game.players[1], 3, source=giant) == 3
    assert _w1g5i_damage_dealt(game, me, 3, source=giant) == 0
    game.resolve_cleanup_step(1)
    assert _w1g5i_damage_dealt(game, me, 3, source=giant) == 3


def test_w1g5_samite_ministration_with_no_source_named_chooses_one(set_pool):
    """A shield that lasts all turn has no sourceless form: left unnamed it
    would be "prevent all damage dealt to you this turn". So a seat that names
    nothing takes the stated default — the opponent's biggest creature — and
    every other source still deals its damage."""
    game, (giant, bears) = _w1g5_ministration_table(
        set_pool, [_w1g5_attacker("Giant", 3, ("R",)), _w1g5_attacker("Bears", 2, ("G",))]
    )
    me = game.players[0]
    _w1g5_minister(game)

    assert _w1g5i_damage_dealt(game, me, 3, source=giant) == 0
    assert _w1g5i_damage_dealt(game, me, 2, source=bears) == 2
    assert _w1g5i_damage_dealt(game, me, 5) == 5


def test_w1g5_samite_ministration_with_nothing_to_choose_does_nothing(set_pool):
    """No source on the table at all: the spell resolves, arms nothing and says
    so (CR 609.7a) — and a later, unrelated damage event is dealt in full."""
    game, _board = _w1g5_ministration_table(set_pool, [])
    me = game.players[0]
    _w1g5_minister(game)
    assert any("no source of damage to choose" in line for line in game.log)
    assert _w1g5i_damage_dealt(game, me, 4) == 4


def test_w1g5_the_blanket_and_the_one_shot_keep_their_own_rider_spelling():
    """"Whenever … this turn" belongs to the shield that lasts the turn and
    "if …" to the one-shot. Each printed on the other's shield refuses, so the
    two sentences cannot drift into arming each other's interceptor."""
    from engine.grammar import compile_line

    blanket = (
        "Prevent all damage that would be dealt to you this turn by a source "
        "of your choice."
    )
    one_shot = (
        "The next time a source of your choice would deal damage to you and/or "
        "creatures you control this turn, prevent that damage."
    )
    whenever = (
        " Whenever damage from a black source is prevented this way this turn, "
        "you gain that much life."
    )
    if_once = " If damage from a black source is prevented this way, you gain that much life."

    assert compile_line(blanket + whenever).usable
    assert compile_line(one_shot + if_once).usable
    assert not compile_line(blanket + if_once).usable
    assert not compile_line(one_shot + whenever).usable
    # …and neither narrowing the blanket does not carry is dropped
    assert not compile_line(blanket.replace("all damage", "all combat damage")).usable
    assert not compile_line(blanket.replace("to you", "to target creature")).usable

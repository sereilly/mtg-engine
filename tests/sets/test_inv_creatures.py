"""Invasion creatures.

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
from engine import Game as _W1G5CGame, PlayerState as _W1G5CPlayer
from engine.models import CardDefinition as _W1G5CCard, Permanent as _W1G5CPermanent
from engine.oracle import compile_card_oracle as _w1g5c_compile
from tests.helpers import _damage_dealt as _w1g5c_damage_dealt
from tests.helpers import resolve_stack as _w1g5c_resolve_stack


def _w1g5_body(name, power, toughness, colors=(), type_line="Creature - Test", text=""):
    """A bare creature for the other side of a fight."""
    return _W1G5CCard(
        name=name, mana_cost="".join("{%s}" % symbol for symbol in colors) or "{3}",
        cmc=3.0, type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )  # W1G5 creatures: a test body


def _w1g5_duel(mine, theirs, *, active=0):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_W1G5CPermanent(card=card) for card in mine]
    board1 = [_W1G5CPermanent(card=card) for card in theirs]
    filler = _w1g5_body("Filler", 0, 1)
    game = _W1G5CGame(players=[
        _W1G5CPlayer(name="P0", battlefield=board0, library=[filler] * 10),
        _W1G5CPlayer(name="P1", battlefield=board1, library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G5 creatures: the duel


def _w1g5_attack(game, attacker_slot, blocker_slot=None, *, defender=1):
    """The active seat attacks with *attacker_slot*; *defender* blocks it with
    *blocker_slot* or not at all; combat runs to the second main phase."""
    attacker_seat = game.active_player_index
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(attacker_seat, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocks = {} if blocker_slot is None else {blocker_slot: attacker_slot}
    blocked = game.declare_blockers(defender, blocks)
    assert blocked[0], blocked
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5c_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G5: fought


# --- Callous Giant ---------------------------------------------------------
# "If a source would deal 3 or less damage to this creature, prevent that
# damage." A static shield narrowed by the size of the event.


def test_w1g5_callous_giant_shrugs_off_three_and_takes_four(set_pool):
    """The threshold is the card: 1, 2 and 3 are prevented whole, 4 is dealt
    whole — never "all but 3"."""
    giant_card = set_pool("INV")["Callous Giant"]
    assert _w1g5c_compile(giant_card).supported
    game, (giant, other), _ = _w1g5_duel([giant_card, _w1g5_body("Bystander", 2, 2)], [])

    for small in (1, 2, 3):
        assert _w1g5c_damage_dealt(game, giant, small) == 0, small
    assert _w1g5c_damage_dealt(game, giant, 4) == 4
    assert _w1g5c_damage_dealt(game, giant, 9, combat=True) == 9
    # "to **this** creature": nobody else on the board is shielded
    assert _w1g5c_damage_dealt(game, other, 2) == 2
    assert _w1g5c_damage_dealt(game, game.players[0], 2) == 2


def test_w1g5_callous_giant_in_combat(set_pool):
    """Through the combat damage step. Blocking a 3/3 the Giant is unmarked and
    kills it; blocking a 4/4 it takes the four and trades (it is a 4/4)."""
    giant_card = set_pool("INV")["Callous Giant"]
    game, (raider,), (giant,) = _w1g5_duel([_w1g5_body("Raider", 3, 3)], [giant_card])
    _w1g5_attack(game, 0, 0)
    assert game.is_on_battlefield(giant) and giant.damage_marked == 0
    assert not game.is_on_battlefield(raider)

    game, (brute,), (giant,) = _w1g5_duel([_w1g5_body("Brute", 4, 4)], [giant_card])
    _w1g5_attack(game, 0, 0)
    assert not game.is_on_battlefield(giant)
    assert not game.is_on_battlefield(brute)


def test_w1g5_callous_giant_judges_each_event_as_it_stands(set_pool):
    """Each source's damage is its own event, so three 3-point hits are three
    prevented events. And CR 616.1f re-asks after every applied effect: five
    damage that a prevention pool has cut to three is three or less by the
    time the Giant's shield is asked, so nothing lands."""
    game, (giant,), _ = _w1g5_duel([set_pool("INV")["Callous Giant"]], [])
    for _ in range(3):
        assert _w1g5c_damage_dealt(game, giant, 3) == 0
    giant.damage_prevention_pool = 2
    assert _w1g5c_damage_dealt(game, giant, 5) == 0
    assert giant.damage_prevention_pool == 0
    # …and a small event is taken whole before the pool is spent on it
    giant.damage_prevention_pool = 2
    assert _w1g5c_damage_dealt(game, giant, 3) == 0
    assert giant.damage_prevention_pool == 2


# --- Urborg Phantom --------------------------------------------------------
# "This creature can't block." / "{U}: Prevent all combat damage that would be
# dealt to and dealt by this creature this turn."


def _w1g5_phantom_shield(game, phantom):
    result = game.activate_permanent_ability(
        game.controller_index_of(phantom), "Urborg Phantom",
        permanent_index=game.battlefield_index_of(phantom),
    )
    assert result.supported, result.details
    _w1g5c_resolve_stack(game)  # W1G5: the Phantom's shield is armed


def test_w1g5_urborg_phantom_cannot_block(set_pool):
    phantom_card = set_pool("INV")["Urborg Phantom"]
    assert _w1g5c_compile(phantom_card).supported
    game, _attackers, (phantom,) = _w1g5_duel([_w1g5_body("Raider", 2, 2)], [phantom_card])
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused


def test_w1g5_urborg_phantoms_shield_covers_both_ends_of_its_own_combat(set_pool):
    """Activated, the 3/1 attacks into a 5/5 blocker: it deals nothing and
    takes nothing. Unblocked on another table, the defending player loses no
    life. The shield is on the Phantom and nobody else — the creature beside
    it still deals and takes combat damage — which is the reading a targetless
    ability's fallback scan would have got wrong."""
    phantom_card = set_pool("INV")["Urborg Phantom"]
    game, (phantom, friend), (wall,) = _w1g5_duel(
        [phantom_card, _w1g5_body("Friend", 2, 2)], [_w1g5_body("Wall", 5, 5)]
    )
    _w1g5_phantom_shield(game, phantom)
    assert any(
        "dealt to and dealt by Urborg Phantom this turn is prevented" in line
        for line in game.log
    )
    assert _w1g5c_damage_dealt(game, friend, 2, source=wall, combat=True) == 2
    assert _w1g5c_damage_dealt(game, wall, 2, source=friend, combat=True) == 2
    _w1g5_attack(game, 0, 0)
    assert game.is_on_battlefield(phantom) and phantom.damage_marked == 0
    assert wall.damage_marked == 0

    game, (phantom,), _ = _w1g5_duel([phantom_card], [])
    _w1g5_phantom_shield(game, phantom)
    _w1g5_attack(game, 0)
    assert game.players[1].life == 20


def test_w1g5_urborg_phantoms_shield_is_combat_damage_only_and_ends_with_the_turn(set_pool):
    """The printed "combat" and the printed "this turn", one at a time: a ping
    still kills the shielded 3/1, and after cleanup the shield is gone."""
    phantom_card = set_pool("INV")["Urborg Phantom"]
    game, (phantom,), (wall,) = _w1g5_duel([phantom_card], [_w1g5_body("Wall", 5, 5)])
    _w1g5_phantom_shield(game, phantom)
    assert _w1g5c_damage_dealt(game, phantom, 1, source=wall, combat=True) == 0
    assert _w1g5c_damage_dealt(game, wall, 3, source=phantom, combat=True) == 0
    assert _w1g5c_damage_dealt(game, phantom, 1, source=wall) == 1

    game.resolve_cleanup_step(0)
    assert _w1g5c_damage_dealt(game, phantom, 1, source=wall, combat=True) == 1
    assert _w1g5c_damage_dealt(game, wall, 3, source=phantom, combat=True) == 3


def test_w1g5_urborg_phantom_without_the_shield_is_an_ordinary_attacker(set_pool):
    """The control: unshielded, the same attack deals its 3."""
    game, (phantom,), _ = _w1g5_duel([set_pool("INV")["Urborg Phantom"]], [])
    _w1g5_attack(game, 0)
    assert game.players[1].life == 17


# --- Tsabo Tavoc -----------------------------------------------------------
# "First strike, protection from legendary creatures" /
# "{B}{B}, {T}: Destroy target legendary creature. It can't be regenerated."


def _w1g5_legend(name, power, toughness, text=""):
    return _w1g5_body(
        name, power, toughness, ("G",), type_line="Legendary Creature - Test",
        text=text,
    )  # W1G5: a legendary test creature


def test_w1g5_tsabo_tavoc_is_protected_from_legendary_creatures_and_nothing_else(set_pool):
    """CR 702.16a: the quality is a supertype *and* a type, both of them. A
    legendary creature's damage is prevented (CR 702.16e); a nonlegendary
    creature's is not, and neither is a legendary permanent's that is not a
    creature — "legendary creatures" is one quality, not two."""
    from web.serialization import _effective_keywords

    tsabo_card = set_pool("INV")["Tsabo Tavoc"]
    assert _w1g5c_compile(tsabo_card).supported
    relic = _w1g5_body("Relic", 0, 0, type_line="Legendary Artifact")
    game, (tsabo,), (legend, commoner, artifact) = _w1g5_duel(
        [tsabo_card],
        [_w1g5_legend("Old Hero", 6, 6), _w1g5_body("Commoner", 6, 6), relic],
    )
    assert game._protection_qualities(tsabo) == {("typed", "legendary creature")}
    assert "Protection from legendary creatures" in _effective_keywords(tsabo, game)

    assert _w1g5c_damage_dealt(game, tsabo, 6, source=legend) == 0
    assert _w1g5c_damage_dealt(game, tsabo, 6, source=legend, combat=True) == 0
    assert _w1g5c_damage_dealt(game, tsabo, 6, source=commoner) == 6
    assert _w1g5c_damage_dealt(game, tsabo, 2, source=artifact) == 2


def test_w1g5_tsabo_tavoc_cannot_be_blocked_by_a_legendary_creature(set_pool):
    """CR 702.16f, at the declaration: the legend may not block it and the
    nonlegendary creature beside it may."""
    game, (tsabo,), (legend, commoner) = _w1g5_duel(
        [set_pool("INV")["Tsabo Tavoc"]],
        [_w1g5_legend("Old Hero", 1, 9), _w1g5_body("Commoner", 1, 9)],
    )
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert not game._can_block_attacker(legend, tsabo)
    assert game._can_block_attacker(commoner, tsabo)
    refused = game.declare_blockers(1, {0: 0})
    assert not refused[0], refused
    assert game.declare_blockers(1, {1: 0})[0]


def test_w1g5_tsabo_tavoc_destroys_a_legend_through_regeneration(set_pool):
    """The ability names "target **legendary** creature": the commoner is not a
    legal target, and neither is Tsabo Tavoc itself — its own ability comes
    from a legendary creature, which is what it has protection from
    (CR 702.16b). The legend dies with a regeneration shield up."""
    tsabo_card = set_pool("INV")["Tsabo Tavoc"]
    hero = _w1g5_legend("Old Hero", 3, 3, text="{G}: Regenerate this creature.")
    game, (tsabo,), (legend, commoner) = _w1g5_duel(
        [tsabo_card], [hero, _w1g5_body("Commoner", 3, 3)]
    )
    # Nothing is paid for an illegal announcement (CR 602.2b): Tsabo Tavoc is
    # still untapped after each refusal.
    for illegal in (tsabo, commoner):
        refused = game.activate_permanent_ability(
            0, "Tsabo Tavoc", permanent_index=0,
            target_player_index=game.controller_index_of(illegal),
            target_permanent_ids=[illegal.permanent_id],
        )
        assert not refused.supported, illegal.card.name
        assert not tsabo.tapped

    shielded = game.activate_permanent_ability(1, "Old Hero", permanent_index=0)
    assert shielded.supported, shielded.details
    _w1g5c_resolve_stack(game)
    result = game.activate_permanent_ability(
        0, "Tsabo Tavoc", permanent_index=0, target_player_index=1,
        target_permanent_ids=[legend.permanent_id],
    )
    assert result.supported, result.details
    _w1g5c_resolve_stack(game)
    assert not game.is_on_battlefield(legend)
    assert game.is_on_battlefield(commoner) and tsabo.tapped


def test_w1g5_a_legendary_creatures_ability_cannot_target_tsabo_tavoc(set_pool):
    """CR 702.16b from the other side: a legendary pinger may not aim at it,
    and the same ability on a nonlegendary creature may."""
    ping = "{T}: This creature deals 1 damage to target creature."
    game, (tsabo,), (legend, commoner) = _w1g5_duel(
        [set_pool("INV")["Tsabo Tavoc"]],
        [_w1g5_legend("Old Archer", 1, 1, text=ping),
         _w1g5_body("Young Archer", 1, 1, text=ping)],
        active=1,
    )
    refused = game.activate_permanent_ability(
        1, "Old Archer", permanent_index=0, target_player_index=0,
        target_permanent_ids=[tsabo.permanent_id],
    )
    assert not refused.supported, refused.details
    allowed = game.activate_permanent_ability(
        1, "Young Archer", permanent_index=1, target_player_index=0,
        target_permanent_ids=[tsabo.permanent_id],
    )
    assert allowed.supported, allowed.details
    _w1g5c_resolve_stack(game)
    assert tsabo.damage_marked == 1

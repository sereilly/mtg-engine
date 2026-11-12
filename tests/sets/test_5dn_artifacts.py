"""Fifth Dawn artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
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

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.equipment import equipped_creature as _w1g4_equipped
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import settle as _w1g4_settle


def _w1g4_table(set_pool, *, hand=(), interactive=()):
    """Two seats on seat 0's first main phase; *hand* is seat 0's, by card."""
    island = set_pool("LEA")["Island"]
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P0", library=[island] * 20, hand=list(hand)),
        _W1G4PlayerState(name="P1", library=[island] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g4_put(game, card, seat):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g4_settle(game)
    return permanent


def _w1g4_activate(game, seat, permanent, ability=0, **targets):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent),
        ability_index=ability, **targets,
    )
    _w1g4_settle(game)
    return result


def _w1g4_equip(game, seat, equipment, creature):
    """Activate *equipment*'s equip ability (its last activated ability) at
    *creature* and settle."""
    abilities = _w1g4_compile(equipment.card).activated_abilities
    result = _w1g4_activate(
        game, seat, equipment, ability=len(abilities) - 1,
        target_permanent_ids=[creature.permanent_id],
    )
    assert result.supported, (result, game.log[-4:])
    return result


def _w1g4_count(game, text):
    return sum(text in line for line in game.log)


def test_w1g4_grafted_wargear_moved_by_its_own_equip_sacrifices_the_old_host(set_pool):
    """"Whenever this Equipment becomes unattached from a permanent, sacrifice
    that permanent." Equip {0} chains: moving the Wargear from the Bears to the
    Giant sacrifices the Bears (CR 701.3d — moving it is becoming unattached;
    the trigger is a stack object, CR 603.3) and the Giant gets +3/+2.
    Equipping the creature it is already on is no move (CR 701.3b; the
    2013-04-15 ruling: "it generally won't do anything") and sacrifices
    nothing."""
    fifth, alpha = set_pool("5DN"), set_pool("LEA")
    assert _w1g4_compile(fifth["Grafted Wargear"]).supported
    game = _w1g4_table(set_pool, interactive=(0,))
    wargear = _w1g4_put(game, fifth["Grafted Wargear"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    giant = _w1g4_put(game, alpha["Hill Giant"], 0)

    _w1g4_equip(game, 0, wargear, bears)
    assert (bears.effective_power, bears.effective_toughness) == (5, 4)
    assert _w1g4_count(game, "was sacrificed") == 0

    _w1g4_equip(game, 0, wargear, giant)
    assert not game.is_on_battlefield(bears)
    assert bears.card in game.players[0].graveyard
    assert (giant.effective_power, giant.effective_toughness) == (6, 5)

    _w1g4_equip(game, 0, wargear, giant)
    assert game.is_on_battlefield(giant)
    assert _w1g4_count(game, "was sacrificed") == 1


def test_w1g4_grafted_wargear_leaving_sacrifices_its_creature_and_a_dead_host_is_announced_once(set_pool):
    """Both departure halves of CR 701.3d, looked back at (CR 603.10c). The
    Wargear sacrificed: the creature it equipped is sacrificed. The creature
    destroyed: the trigger fires once — not again when the CR 704.5n sweep
    tidies the record — and does nothing (the 2020-11-10 ruling)."""
    fifth, alpha = set_pool("5DN"), set_pool("LEA")
    game = _w1g4_table(set_pool, hand=[alpha["Terror"]])
    wargear = _w1g4_put(game, fifth["Grafted Wargear"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    giant = _w1g4_put(game, alpha["Hill Giant"], 0)

    _w1g4_equip(game, 0, wargear, bears)
    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_settle(game)
    assert _w1g4_equipped(wargear) is None
    assert _w1g4_count(game, "the permanent it named is gone") == 1
    assert game.is_on_battlefield(giant)

    _w1g4_equip(game, 0, wargear, giant)
    game.sacrifice_permanent(wargear)
    _w1g4_settle(game)
    assert not game.is_on_battlefield(giant)
    assert giant.card in game.players[0].graveyard


def test_w1g4_grafted_wargear_cannot_sacrifice_an_opponents_creature(set_pool):
    """The 2004-12-01 ruling: "If your Grafted Wargear somehow ends up on an
    opponent's creature and it then becomes unattached from that creature, you
    won't be able to sacrifice that creature because you don't control it."
    Magnetic Theft puts it on the opponent's Giant; its controller equips it
    back, and the Giant stays."""
    fifth, alpha = set_pool("5DN"), set_pool("LEA")
    game = _w1g4_table(set_pool, hand=[fifth["Magnetic Theft"]])
    wargear = _w1g4_put(game, fifth["Grafted Wargear"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    giant = _w1g4_put(game, alpha["Hill Giant"], 1)

    assert game.cast_from_hand(
        0, "Magnetic Theft",
        target_permanent_ids=[wargear.permanent_id, giant.permanent_id],
    ).supported
    _w1g4_settle(game)
    assert _w1g4_equipped(wargear) is giant

    _w1g4_equip(game, 0, wargear, bears)
    assert game.is_on_battlefield(giant)
    assert _w1g4_equipped(wargear) is bears
    assert any("can't sacrifice it" in line for line in game.log)


def test_w1g4_grafted_wargear_unattached_by_an_effect_sacrifices_and_in_response_too(set_pool):
    """"Unattach all Equipment from target creature" (Disarm) is a way of
    becoming unattached, so the creature is sacrificed. And the trigger is on
    the stack until it resolves: a creature that leaves in response is
    sacrificed by nothing, and nothing else is taken in its place."""
    fifth, alpha, mirrodin = set_pool("5DN"), set_pool("LEA"), set_pool("MRD")
    game = _w1g4_table(set_pool, hand=[mirrodin["Disarm"]])
    wargear = _w1g4_put(game, fifth["Grafted Wargear"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    giant = _w1g4_put(game, alpha["Hill Giant"], 0)

    _w1g4_equip(game, 0, wargear, bears)
    assert game.cast_from_hand(
        0, "Disarm", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_settle(game)
    assert not game.is_on_battlefield(bears)
    assert _w1g4_equipped(wargear) is None

    _w1g4_equip(game, 0, wargear, giant)
    # Moved again, and the old host destroyed while the trigger waits.
    ogre = _w1g4_put(game, alpha["Gray Ogre"], 0)
    assert game.queue_permanent_ability(
        0, wargear.card.name, permanent_index=game.battlefield_index_of(wargear),
        target_permanent_ids=[ogre.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    assert [item.ability_kind for item in game.stack] == ["triggered"]
    assert _w1g4_equipped(wargear) is ogre
    game._destroy_swept_permanents(game.players[0], lambda perm: perm is giant)
    _w1g4_settle(game)
    assert giant.card in game.players[0].graveyard
    assert game.is_on_battlefield(ogre)
    assert _w1g4_equipped(wargear) is ogre
    assert _w1g4_count(game, "the permanent it named is gone") == 1

def _w1g4_kaldra_board(set_pool, *, shield_seat=0):
    """Helm and Sword of Kaldra on seat 0's side, Shield on *shield_seat*'s."""
    fifth, mirrodin, darksteel = set_pool("5DN"), set_pool("MRD"), set_pool("DST")
    game = _w1g4_table(set_pool)
    helm = _w1g4_put(game, fifth["Helm of Kaldra"], 0)
    sword = _w1g4_put(game, mirrodin["Sword of Kaldra"], 0)
    shield = _w1g4_put(game, darksteel["Shield of Kaldra"], shield_seat)
    return game, helm, sword, shield


def _w1g4_kaldras(game, seat=0):
    return [perm for perm in game.controlled_by(seat) if perm.card.name == "Kaldra"]


def test_w1g4_helm_of_kaldra_assembles_kaldra_and_attaches_all_three(set_pool):
    """"{1}: If you control Equipment named Helm of Kaldra, Sword of Kaldra, and
    Shield of Kaldra, create Kaldra, a legendary 4/4 colorless Avatar creature
    token. Attach those Equipment to it." Its 2004-12-01 ruling: "The token is
    named Kaldra, has the supertype legendary, and has creature type Avatar."
    All three go onto it: +5/+5 from the Sword, first strike, trample and haste
    from the Helm, indestructible from the Shield."""
    fifth = set_pool("5DN")
    assert _w1g4_compile(fifth["Helm of Kaldra"]).supported
    game, helm, sword, shield = _w1g4_kaldra_board(set_pool)

    result = _w1g4_activate(game, 0, helm, ability=0)
    assert result.supported, result.details
    (kaldra,) = _w1g4_kaldras(game)
    assert kaldra.metadata.get("is_token")
    assert kaldra.has_supertype("legendary") and kaldra.has_type("avatar")
    assert not kaldra.effective_card.colors
    assert all(_w1g4_equipped(each) is kaldra for each in (helm, sword, shield))
    assert (kaldra.effective_power, kaldra.effective_toughness) == (9, 9)
    assert all(
        game._has_keyword(kaldra, word)
        for word in ("first strike", "trample", "haste", "indestructible")
    )


def test_w1g4_helm_of_kaldra_wants_all_three_under_its_controller(set_pool):
    """"…unless you control all three Equipment" — two of the three, or the
    third on the opponent's side, create nothing: one conjunct per printed
    name, each asked of the activator's own board."""
    game, helm, sword, shield = _w1g4_kaldra_board(set_pool, shield_seat=1)
    assert _w1g4_activate(game, 0, helm, ability=0).supported
    assert _w1g4_kaldras(game) == [] and _w1g4_kaldras(game, 1) == []
    assert _w1g4_equipped(helm) is None and _w1g4_equipped(sword) is None


def test_w1g4_helm_of_kaldra_checks_its_condition_as_it_resolves(set_pool):
    """The ruling's "when the ability resolves": all three were there when the
    ability was activated, the Shield leaves in response, and no token is put
    onto the battlefield."""
    game, helm, sword, shield = _w1g4_kaldra_board(set_pool)
    assert game.queue_permanent_ability(
        0, helm.card.name, permanent_index=game.battlefield_index_of(helm),
        ability_index=0,
    ).supported
    assert game.stack
    game.remove_from_battlefield(shield)
    _w1g4_settle(game)
    assert _w1g4_kaldras(game) == []
    assert _w1g4_equipped(helm) is None and _w1g4_equipped(sword) is None


# ==== end w1g4 ======================================================

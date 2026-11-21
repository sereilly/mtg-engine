"""Champions of Kamigawa lands.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
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
#
# The drive list's legendary lands: each activated ability names "target
# legendary creature", and a nonlegendary one is refused.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, hands=((), ())):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_activate(game, permanent, index, target):
    return game.activate_permanent_ability(
        0, permanent.card.name, permanent_index=game.battlefield_index_of(permanent),
        ability_index=index, target_permanent_ids=[target.permanent_id],
    )


def test_w1g2_the_kamigawa_temples_reach_only_legendary_creatures(set_pool):
    """Okina's +1/+1, Shinka's first strike and Eiganjo Castle's 2-point
    shield all land on Nagao; each refuses a Grizzly Bears. A Lightning Bolt
    then deals Nagao 1 of its 3."""
    chk = set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([set_pool("LEA")["Lightning Bolt"]], ()))
    okina = _w1g2_put(game, chk["Okina, Temple to the Grandfathers"], 0)
    shinka = _w1g2_put(game, chk["Shinka, the Bloodsoaked Keep"], 0)
    eiganjo = _w1g2_put(game, chk["Eiganjo Castle"], 0)
    nagao = _w1g2_put(game, chk["Nagao, Bound by Honor"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    for land in (okina, shinka, eiganjo):
        assert not _w1g2_activate(game, land, 1, bears).supported
    for land in (okina, shinka, eiganjo):
        assert _w1g2_activate(game, land, 1, nagao).supported
        _w1g2_settle(game)
    assert (nagao.effective_power, nagao.effective_toughness) == (4, 4)
    assert nagao.has_keyword("first strike")
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[nagao.permanent_id]
    ).supported
    _w1g2_settle(game)
    assert "Prevented 2 damage to Nagao, Bound by Honor" in game.log
    assert "Lightning Bolt dealt 1 damage to Nagao, Bound by Honor" in game.log
    assert game.is_on_battlefield(nagao)

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


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    """*name* from Champions of Kamigawa, else from the sets the probes lean on."""
    for code in ("CHK", "LEA", "M21"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), opponent_hand=(), mine=(), theirs=()):
    """Two seats on seat 0's first main phase, mana costs enforced; *mine* /
    *theirs* placed untapped and not summoning sick."""
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card("Island")] * 12),
        _W1G9PlayerState(name="Bob", hand=[card(n) for n in opponent_hand],
                         library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G9Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed[0], placed[1]


def _w1g9_activate(game, permanent, seat=0, **announce):
    slot = [p.permanent_id for p in game.players[seat].battlefield].index(
        permanent.permanent_id
    )
    return game.activate_permanent_ability(
        seat, permanent.card.name, permanent_index=slot, **announce
    )


def test_w1g9_the_legendary_lands_enter_tapped_by_their_short_names(set_pool):
    """"Boseiju enters tapped." / "Hall of the Bandit Lord enters tapped." /
    "Untaidake enters tapped." CR 201.5c's shortened name is the land itself,
    so each arrives tapped by whatever road it enters."""
    game, _mine, _theirs = _w1g9_table(set_pool)
    for name in (
        "Boseiju, Who Shelters All", "Hall of the Bandit Lord",
        "Untaidake, the Cloud Keeper",
    ):
        land = _W1G9Permanent(card=_w1g9_card(set_pool, name))
        game._put_permanent_onto_battlefield(0, land, None)
        assert game.is_on_battlefield(land)
        assert land.tapped, name


def test_w1g9_untaidake_pays_two_life_for_mana_only_a_legendary_spell_spends(set_pool):
    """"{T}, Pay 2 life: Add {C}{C}. Spend this mana only to cast legendary
    spells." (CR 106.6.) The {C}{C} cannot pay a Grizzly Bears' generic pip;
    it pays Azusa's."""
    game, mine, _theirs = _w1g9_table(
        set_pool, hand=["Grizzly Bears", "Azusa, Lost but Seeking"],
        mine=["Untaidake, the Cloud Keeper"],
    )
    alice = game.players[0]
    assert _w1g9_activate(game, mine[0]).supported
    assert alice.life == 18
    assert mine[0].tapped
    assert sum(alice.mana_pool.values()) == 0
    assert alice.restricted_mana == {"legendary": {"C": 2}}

    alice.mana_pool["G"] = 1
    refused = game.cast_from_hand(0, "Grizzly Bears")
    assert not refused.supported and "insufficient mana" in refused.details
    assert [c.name for c in alice.hand].count("Grizzly Bears") == 1

    assert game.cast_from_hand(0, "Azusa, Lost but Seeking").supported
    _w1g9_settle(game)
    assert "Azusa, Lost but Seeking" in [p.card.name for p in game.controlled_by(0)]
    assert alice.restricted_mana["legendary"]["C"] == 0
    assert alice.mana_pool["G"] == 0


def test_w1g9_boseiju_mana_makes_an_instant_or_sorcery_uncounterable(set_pool):
    """"{T}, Pay 2 life: Add {C}. If that mana is spent on an instant or
    sorcery spell, that spell can't be countered." A Counterspell aimed at a
    sorcery Boseiju's mana paid for does nothing; the same mana spent on a
    creature spell is just mana, and the creature is countered (CR 106.6)."""
    game, mine, theirs = _w1g9_table(
        set_pool, hand=["Counsel of the Soratami", "Grizzly Bears"],
        opponent_hand=["Counterspell", "Counterspell"],
        mine=["Boseiju, Who Shelters All"],
    )
    alice, bob = game.players
    assert _w1g9_activate(game, mine[0]).supported
    assert alice.life == 18
    alice.mana_pool["U"] = 2
    assert game.queue_from_hand(0, "Counsel of the Soratami").supported
    assert game.stack[-1].uncounterable_by
    bob.mana_pool["U"] = 2
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g9_settle(game)
    assert len(alice.hand) == 3          # Grizzly Bears and the two it drew
    assert any("can't be countered" in line for line in game.log)

    mine[0].tapped = False
    assert _w1g9_activate(game, mine[0]).supported
    alice.mana_pool["G"] = 1
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    assert not game.stack[-1].uncounterable_by
    bob.mana_pool["U"] = 2
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=0).supported
    _w1g9_settle(game)
    assert "Grizzly Bears" not in [p.card.name for p in game.controlled_by(0)]
    assert "Grizzly Bears" in [c.name for c in alice.graveyard]


def test_w1g9_hall_of_the_bandit_lord_mana_gives_a_creature_lasting_haste(set_pool):
    """"{T}, Pay 3 life: Add {C}. If that mana is spent on a creature spell,
    it gains haste." The haste "doesn't wear off at end of turn" (ruling
    2004-12-01): the Bears attack the turn they arrive, and still have haste
    two turns later."""
    game, mine, _theirs = _w1g9_table(
        set_pool, hand=["Grizzly Bears", "Grizzly Bears"],
        mine=["Hall of the Bandit Lord", "Forest"],
    )
    alice = game.players[0]
    assert _w1g9_activate(game, mine[0]).supported
    assert alice.life == 17
    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=mine[1].permanent_id)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g9_settle(game)
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert game._has_keyword(bears, "haste")

    game._set_phase_and_step("combat", "declare_attackers")
    slot = [p.permanent_id for p in alice.battlefield].index(bears.permanent_id)
    ok, why = game.declare_attackers(0, [slot], defending_player_index=1)
    assert ok, why

    game.start_turn(1)
    game.start_turn(0)
    assert game._has_keyword(bears, "haste")

    # The second Bears, paid with a Forest's mana alone, has none.
    mine[1].tapped = False
    alice.mana_pool["G"] = 0
    alice.mana_pool["C"] = 1
    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=mine[1].permanent_id)
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g9_settle(game)
    second = [p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"][-1]
    assert second is not bears and not game._has_keyword(second, "haste")


def test_w1g9_forbidden_orchard_tap_trigger_uses_the_stack(set_pool):
    """"Whenever you tap this land for mana, target opponent creates a 1/1
    colorless Spirit creature token." It targets, so it is not a mana
    ability (CR 605.5a): it waits on the stack above the mana, and Bob gets
    the Spirit when it resolves. Tapping another land sets nothing off."""
    game, mine, _theirs = _w1g9_table(set_pool, mine=["Forbidden Orchard", "Forest"])
    alice = game.players[0]
    assert game.tap_land_for_mana(0, "Forbidden Orchard", "U", permanent_id=mine[0].permanent_id)
    assert alice.mana_pool["U"] == 1
    assert [item.card.name for item in game.stack] == ["Forbidden Orchard"]
    assert game.stack[-1].target_player_index == 1
    assert not [p for p in game.controlled_by(1)]
    _w1g9_settle(game)
    spirits = [p for p in game.controlled_by(1) if p.card.name == "Spirit Token"]
    assert len(spirits) == 1
    assert (spirits[0].effective_power, spirits[0].effective_toughness) == (1, 1)
    assert game._effective_colors(spirits[0]) in ((), [], set(), frozenset())

    assert game.tap_land_for_mana(0, "Forest", "G", permanent_id=mine[1].permanent_id)
    assert game.stack == []
    _w1g9_settle(game)
    assert len([p for p in game.controlled_by(1) if p.card.name == "Spirit Token"]) == 1

# ==== end w1g9 ======================================================

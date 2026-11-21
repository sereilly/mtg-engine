"""Champions of Kamigawa artifacts.

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

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
#
# Jade Idol's Spirit-or-Arcane cast trigger (an animation with a subtype) and
# Long-Forgotten Gohei's "Arcane spells you cast cost {1} less to cast"
# (``CostModifier.spell_type``, CR 205.3k).
from engine import Game as _W1G4Game
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from engine.object_creature_types import object_creature_types as _w1g4_types
from tests.helpers import settle as _w1g4_settle


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g4_table(set_pool, *, hand=(), mine=(), opponent_hand=(), mana=False):
    lea = set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = mana
    placed = [_w1g4_put(game, 0, card) for card in mine]
    game.start_turn(0)
    _w1g4_settle(game)
    return game, placed


def test_w1g4_jade_idol_becomes_a_spirit_artifact_creature_for_the_turn(set_pool):
    """"Whenever you cast a Spirit or Arcane spell, this artifact becomes a
    4/4 Spirit artifact creature until end of turn." — still an artifact, a
    Spirit, and back to a plain artifact after cleanup."""
    chk = set_pool("CHK")
    game, (idol,) = _w1g4_table(
        set_pool, hand=[chk["Reach Through Mists"]], mine=[chk["Jade Idol"]],
    )
    assert not idol.is_creature
    assert game.queue_from_hand(0, "Reach Through Mists").supported
    _w1g4_settle(game)
    assert idol.is_creature and idol.has_type("artifact"), game.log
    assert (idol.effective_power, idol.effective_toughness) == (4, 4)
    assert "spirit" in _w1g4_types(game, idol)
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert not idol.is_creature and idol.has_type("artifact")


def test_w1g4_jade_idol_ignores_a_spell_that_is_neither(set_pool):
    """A Grizzly Bears spell is no Spirit and no Arcane spell."""
    game, (idol,) = _w1g4_table(
        set_pool, hand=[set_pool("LEA")["Grizzly Bears"]],
        mine=[set_pool("CHK")["Jade Idol"]],
    )
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g4_settle(game)
    assert not idol.is_creature, game.log


def test_w1g4_long_forgotten_gohei_discounts_its_controllers_arcane_spells(set_pool):
    """"Arcane spells you cast cost {1} less to cast." Eerie Procession
    ({2}{U}, Sorcery — Arcane) is charged {1}{U} to Alice; Bob's, and Alice's
    non-Arcane Counsel of the Soratami ({2}{U}), are charged in full."""
    from engine.cost_modifiers import cast_mana_charge

    chk = set_pool("CHK")
    game, _ = _w1g4_table(set_pool, mine=[chk["Long-Forgotten Gohei"]])
    procession, counsel = chk["Eerie Procession"], chk["Counsel of the Soratami"]

    def charged(seat, card):
        cost = cast_mana_charge(game, seat, card)
        return cost["generic"], cost["U"]

    assert charged(0, procession) == (1, 1)
    assert charged(1, procession) == (2, 1)
    assert charged(0, counsel) == (2, 1)


def test_w1g4_long_forgotten_gohei_lets_two_mana_cast_eerie_procession(set_pool):
    """The discount paid for real: with costs enforced and {U}{U} in Alice's
    pool, Eerie Procession ({2}{U}) is cast only while the Gohei is on the
    battlefield, and the cast spends both."""
    chk = set_pool("CHK")
    for with_gohei in (True, False):
        game, _ = _w1g4_table(
            set_pool, hand=[chk["Eerie Procession"]], mana=True,
            mine=[chk["Long-Forgotten Gohei"]] if with_gohei else [],
        )
        game.players[0].mana_pool.update({"U": 2})
        cast = game.queue_from_hand(0, "Eerie Procession")
        assert cast.supported is with_gohei, (with_gohei, game.log[-4:])
        if with_gohei:
            assert game.players[0].mana_pool.get("U", 0) == 0


def test_w1g4_long_forgotten_gohei_pumps_spirit_creatures_you_control(set_pool):
    """Its second line, "Spirit creatures you control get +1/+1."."""
    chk, lea = set_pool("CHK"), set_pool("LEA")
    game, (_gohei, kami, bears) = _w1g4_table(
        set_pool, mine=[chk["Long-Forgotten Gohei"], chk["Kami of the Hunt"],
                        lea["Grizzly Bears"]],
    )
    assert (kami.effective_power, kami.effective_toughness) == (3, 3)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

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

# ==== end w1g9 ======================================================

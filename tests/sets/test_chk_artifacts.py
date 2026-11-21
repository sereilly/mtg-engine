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

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), theirs=(), interactive=()):
    """Two seats on seat 0's first main phase, costs not enforced; *mine* /
    *theirs* placed and not summoning sick."""
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card("Island")] * 12),
        _W1G9PlayerState(name="Bob", library=[card("Island")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
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
    result = game.activate_permanent_ability(
        seat, permanent.card.name, permanent_index=slot, **announce
    )
    _w1g9_settle(game)
    return result


def _w1g9_equip(game, equipment, creature):
    return _w1g9_activate(game, equipment, target_permanent_ids=[creature.permanent_id])


def _w1g9_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def test_w1g9_tenza_pumps_more_for_a_legend_and_tramples_for_a_red_creature(set_pool):
    """"Equipped creature gets +1/+1. As long as it's legendary, it gets an
    additional +2/+2. As long as it's red, it has trample." Each clause asked
    of the creature it is on now: a green legend gets +3/+3 and no trample, a
    red non-legend +1/+1 and trample, a red legend both."""
    game, mine, _theirs = _w1g9_table(set_pool, mine=[
        "Tenza, Godo's Maul", "Azusa, Lost but Seeking", "Akki Avalanchers",
        "Ryusei, the Falling Star",
    ])
    tenza, azusa, akki, ryusei = mine
    assert _w1g9_equip(game, tenza, azusa).supported
    assert _w1g9_pt(azusa) == (4, 5) and not game._has_keyword(azusa, "trample")
    assert _w1g9_equip(game, tenza, akki).supported
    assert _w1g9_pt(akki) == (2, 2) and game._has_keyword(akki, "trample")
    assert _w1g9_pt(azusa) == (1, 2)
    assert _w1g9_equip(game, tenza, ryusei).supported
    assert _w1g9_pt(ryusei) == (8, 8) and game._has_keyword(ryusei, "trample")
    assert _w1g9_pt(akki) == (1, 1) and not game._has_keyword(akki, "trample")


def test_w1g9_kondas_banner_equips_only_a_legend_and_pumps_its_kin(set_pool):
    """"Konda's Banner can be attached only to a legendary creature." The
    equip ability may target a non-legend (CR 702.6a's "target creature you
    control") and the Banner then doesn't move (CR 301.5b). On a legend,
    "Creatures that share a color with equipped creature get +1/+1" and the
    same for a creature type: every creature on the battlefield, the
    equipped one included, at most +2/+2 (rulings 2004-12-01)."""
    game, mine, theirs = _w1g9_table(
        set_pool,
        mine=["Konda's Banner", "Azusa, Lost but Seeking", "Humble Budoka", "Akki Avalanchers"],
        theirs=["Grizzly Bears"],
    )
    banner, azusa, budoka, akki = mine
    bears = theirs[0]
    assert _w1g9_equip(game, banner, akki).supported
    assert banner.metadata.get("attached_to") is None
    assert any("can be attached only to a legendary creature" in line for line in game.log)
    assert _w1g9_pt(akki) == (1, 1)

    assert _w1g9_equip(game, banner, azusa).supported
    assert banner.metadata.get("attached_to") is azusa
    assert _w1g9_pt(azusa) == (3, 4)    # green Human Monk: shares both with itself
    assert _w1g9_pt(budoka) == (4, 4)   # green Human Monk
    assert _w1g9_pt(bears) == (3, 3)    # green, not a Human or a Monk
    assert _w1g9_pt(akki) == (1, 1)     # red Goblin Warrior


def test_w1g9_oathkeeper_returns_a_samurai_and_takes_its_bearer_with_it(set_pool):
    """"Whenever equipped creature dies, return that card to the battlefield
    under your control if it's a Samurai card." A Samurai comes back, a Bear
    stays dead. "When Oathkeeper is put into a graveyard from the battlefield,
    exile equipped creature": the creature it was on when it left."""
    game, mine, _theirs = _w1g9_table(
        set_pool, hand=["Lightning Bolt", "Lightning Bolt", "Shatter"],
        mine=["Oathkeeper, Takeno's Daisho", "Kitsune Blademaster", "Grizzly Bears"],
    )
    oath, blademaster, bears = mine
    alice = game.players[0]
    assert _w1g9_equip(game, oath, blademaster).supported
    assert _w1g9_pt(blademaster) == (5, 3)
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[blademaster.permanent_id],
    ).supported
    _w1g9_settle(game)
    back = [p for p in game.controlled_by(0) if p.card.name == "Kitsune Blademaster"]
    assert len(back) == 1 and back[0] is not blademaster
    assert "Kitsune Blademaster" not in [c.name for c in alice.graveyard]

    assert _w1g9_equip(game, oath, bears).supported
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g9_settle(game)
    assert "Grizzly Bears" in [c.name for c in alice.graveyard]
    assert "Grizzly Bears" not in [p.card.name for p in game.controlled_by(0)]

    assert _w1g9_equip(game, oath, back[0]).supported
    assert game.cast_from_hand(0, "Shatter", target_permanent_ids=[oath.permanent_id]).supported
    _w1g9_settle(game)
    assert [c.name for c in alice.exile] == ["Kitsune Blademaster"]
    assert not list(game.controlled_by(0))


def test_w1g9_tatsumasa_comes_back_when_its_dragon_dies_and_not_otherwise(set_pool):
    """"{6}, Exile Tatsumasa: Create a 5/5 blue Dragon Spirit creature token
    with flying. Return Tatsumasa to the battlefield under its owner's control
    when that token dies." A delayed trigger watching the token (CR 603.7):
    the token destroyed, Tatsumasa returns from exile; the token bounced, it
    left without dying, and Tatsumasa stays exiled."""
    for removal, returns in (("Terror", True), ("Unsummon", False)):
        game, mine, _theirs = _w1g9_table(set_pool, hand=[removal], mine=["Tatsumasa, the Dragon's Fang"])
        alice = game.players[0]
        assert _w1g9_activate(game, mine[0], ability_index=0).supported
        assert [c.name for c in alice.exile] == ["Tatsumasa, the Dragon's Fang"]
        [dragon] = list(game.controlled_by(0))
        assert dragon.card.name == "Dragon Spirit Token"
        assert _w1g9_pt(dragon) == (5, 5) and game._has_keyword(dragon, "flying")
        assert game._effective_colors(dragon) == {"U"}
        assert game.cast_from_hand(
            0, removal, target_permanent_ids=[dragon.permanent_id],
        ).supported
        _w1g9_settle(game)
        names = [p.card.name for p in game.controlled_by(0)]
        if returns:
            assert names == ["Tatsumasa, the Dragon's Fang"] and alice.exile == []
        else:
            assert names == [] and [c.name for c in alice.exile] == ["Tatsumasa, the Dragon's Fang"]

# ==== end w1g9 ======================================================

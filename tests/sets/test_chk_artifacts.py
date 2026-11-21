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


# Drive list: Champions of Kamigawa artifacts supported on arrival, given a game.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import settle as _w1g1_settle


def _w1g1_table(set_pool):
    lea = set_pool("LEA")
    game = _W1G1Game(players=[
        _W1G1PlayerState(name=f"P{seat}", library=[lea["Island"]] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g1_settle(game)
    return game


def _w1g1_put(game, card, seat=0):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def test_w1g1_honor_worn_shaku_untaps_by_tapping_a_legend(set_pool):
    """Honor-Worn Shaku: {T}: Add {C}. Tap an untapped legendary permanent you
    control: Untap this artifact. Tapping Isamaru untaps it; a Grizzly Bears
    cannot pay; and a flipped Tomoya the Revealer — legendary only once
    flipped (CR 710.2) — can, where the unflipped Jushi Apprentice could not."""
    from engine.flip_cards import flip_permanent

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game = _w1g1_table(set_pool)
    shaku = _w1g1_put(game, chk["Honor-Worn Shaku"])
    bears = _w1g1_put(game, lea["Grizzly Bears"])
    jushi = _w1g1_put(game, chk["Jushi Apprentice"])

    def untap(by):
        return game.activate_permanent_ability(
            0, "Honor-Worn Shaku", permanent_index=game.battlefield_index_of(shaku),
            ability_index=1, cost_permanent_ids=[by.permanent_id],
        )

    shaku.tapped = True
    assert not untap(bears).supported
    assert not untap(jushi).supported
    assert shaku.tapped and not bears.tapped and not jushi.tapped
    flip_permanent(game, jushi)
    assert untap(jushi).supported
    _w1g1_settle(game)
    assert jushi.tapped and not shaku.tapped
    isamaru = _w1g1_put(game, chk["Isamaru, Hound of Konda"])
    shaku.tapped = True
    assert untap(isamaru).supported
    _w1g1_settle(game)
    assert isamaru.tapped and not shaku.tapped

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

from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.named_counters import counters_on as _w1g6_counters_on
from tests.helpers import settle as _w1g6_settle


def _w1g6_table(set_pool, *, hand=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else [],
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    _w1g6_settle(game)
    return game


def test_w1g6_orochi_hatchery_makes_a_snake_for_each_charge_counter(set_pool):
    """Cast for X=3, it enters with three charge counters; "{5}, {T}: Create a
    1/1 green Snake creature token for each charge counter on this artifact"
    makes three green 1/1 Snakes and taps it. The count is read as it
    resolves: a Hatchery with no counters makes nothing."""
    chk = set_pool("CHK")
    game = _w1g6_table(set_pool, hand=[chk["Orochi Hatchery"]])
    assert game.cast_from_hand(0, "Orochi Hatchery", x_value=3).supported
    _w1g6_settle(game)
    hatchery = next(p for p in game.controlled_by(0) if p.card.name == "Orochi Hatchery")
    assert _w1g6_counters_on(hatchery, "charge") == 3

    assert game.activate_permanent_ability(0, "Orochi Hatchery").supported
    _w1g6_settle(game)
    snakes = [p for p in game.controlled_by(0) if p.card.name != "Orochi Hatchery"]
    assert len(snakes) == 3 and hatchery.tapped
    for snake in snakes:
        assert snake.has_type("Snake") and snake.is_creature
        assert (snake.effective_power, snake.effective_toughness) == (1, 1)
        assert sorted(game._effective_colors(snake)) == ["G"]

    game = _w1g6_table(set_pool, hand=[chk["Orochi Hatchery"]])
    assert game.cast_from_hand(0, "Orochi Hatchery", x_value=0).supported
    _w1g6_settle(game)
    assert game.activate_permanent_ability(0, "Orochi Hatchery").supported
    _w1g6_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Orochi Hatchery"]

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


# ==== W2G4 ==========================================================
# W2G4's tests go between this line and the "end W2G4" line.

from engine import Game as _W2G4Game, PlayerState as _W2G4PlayerState
from engine.models import Permanent as _W2G4Permanent
from tests.helpers import settle as _w2g4_settle


def _w2g4_card(set_pool, name):
    for code in ("CHK", "LEA"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w2g4_put(game, card, seat=0):
    permanent = _W2G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w2g4_table(set_pool, *, hand=(), mine=(), theirs=(), library=None,
                opponent_library=None, opponent_hand=(), interactive=()):
    """Two seats on seat 0's first main phase, costs not enforced; *mine* /
    *theirs* placed and not summoning sick."""
    card = lambda name: _w2g4_card(set_pool, name)  # noqa: E731
    game = _W2G4Game(players=[
        _W2G4PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card(n) for n in (library or ["Island"] * 12)]),
        _W2G4PlayerState(name="Bob", hand=[card(n) for n in opponent_hand],
                         library=[card(n) for n in (opponent_library or ["Island"] * 12)]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {
        seat: [_w2g4_put(game, card(name), seat) for name in names]
        for seat, names in ((0, mine), (1, theirs))
    }
    game.start_turn(0)
    _w2g4_settle(game)
    return game, placed[0], placed[1]


def test_w2g4_junkyo_bell_sacrifices_its_creature_under_its_own_name(set_pool):
    """Junkyo Bell: "At the beginning of your upkeep, you may have target
    creature you control get +X/+X until end of turn, where X is the number of
    creatures you control. If you do, sacrifice that creature at the beginning
    of the next end step." The "if you do" runs as the offer is answered, after
    the trigger has left the stack; the delayed sacrifice it creates is the
    Bell's (CR 603.7e: a triggered ability's delayed ability has that
    ability's source), so the end step announces it as the Bell's — it was
    announced as the sacrificed creature's own ("Grizzly Bears ability
    resolved")."""
    game, (bears, elves), _theirs = _w2g4_table(set_pool, mine=["Grizzly Bears", "Llanowar Elves"])
    _w2g4_put(game, _w2g4_card(set_pool, "Junkyo Bell"))
    game.start_turn(0)
    _w2g4_settle(game)
    # X = 2 creatures: the Bears is 4/4 or the Elves 3/3.
    pumped = [
        permanent for permanent, size in ((bears, (4, 4)), (elves, (3, 3)))
        if (permanent.effective_power, permanent.effective_toughness) == size
    ]
    assert len(pumped) == 1, [(p.card.name, p.effective_power) for p in (bears, elves)]
    [target] = pumped
    survivor = elves if target is bears else bears
    mark = len(game.log)
    game.enter_turn_phase("ending")
    _w2g4_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == sorted(
        ["Junkyo Bell", survivor.card.name]
    )
    tail = game.log[mark:]
    assert "Junkyo Bell ability resolved" in tail, tail
    assert f"{target.card.name} ability resolved" not in tail, tail

def _w2g4_names(cards):
    return [card.name for card in cards]


def _w2g4_offered(game, seat):
    from engine.cast_permissions import playable_from_zones

    return [(entry["zone"], entry["name"], entry["source"]) for entry in playable_from_zones(game, seat)]


def _w2g4_mask_table(set_pool, *, masks=1, interactive=()):
    """Alice controls *masks* Uba Masks; her library is Grizzly Bears, Forest,
    Lightning Bolt, Mountain, Island…; Bob's is Plains, Shock, Islands."""
    game, mine, _theirs = _w2g4_table(
        set_pool, mine=["Uba Mask"] * masks, interactive=interactive,
        library=["Grizzly Bears", "Forest", "Lightning Bolt", "Mountain"] + ["Island"] * 6,
        opponent_library=["Plains", "Giant Growth"] + ["Island"] * 6,
    )
    return game, mine


def test_w2g4_uba_mask_exiles_every_players_draws_face_up(set_pool):
    """"If a player would draw a card, that player exiles that card face up
    instead." Every seat's draws (a player), one at a time (CR 121.2): an
    Ancestral Recall exiles three cards and draws none, the log names each
    (face up, CR 406.3), and Bob's draw step draw is replaced too."""
    game, (mask,) = _w2g4_mask_table(set_pool)
    alice, bob = game.players
    alice.hand.append(_w2g4_card(set_pool, "Ancestral Recall"))
    assert game.cast_from_hand(0, "Ancestral Recall", target_player_index=0).supported
    _w2g4_settle(game)
    assert alice.hand == []
    assert _w2g4_names(alice.exile) == ["Grizzly Bears", "Forest", "Lightning Bolt"]
    assert "Alice exiles Forest face up instead of drawing (Uba Mask)" in game.log
    game.start_next_turn()
    _w2g4_settle(game)
    assert bob.hand == [] and _w2g4_names(bob.exile) == ["Plains"]
    # Linked to the Mask with each exiler (CR 607.2a): Alice's three, Bob's one.
    assert [
        (entry["card"].name, entry["exiler_index"]) for entry in mask.metadata["linked_exile"]
    ] == [("Grizzly Bears", 0), ("Forest", 0), ("Lightning Bolt", 0), ("Plains", 1)]


def test_w2g4_uba_mask_lets_the_exiler_play_them_this_turn_only(set_pool):
    """"Each player may play lands and cast spells from among cards they
    exiled with this artifact this turn." Alice plays the Forest (her land
    drop: a second land from exile is refused, CR 305.2) and casts the Bears
    from exile; Bob may play none of them. "You can't play cards you exiled
    with Uba Mask on previous turns" and "Any cards you don't play just remain
    exiled when the turn ends" (rulings 2004-12-01): the Bolt left over is not
    offered on Alice's next turn, while that turn's own draw is."""
    game, (_mask,) = _w2g4_mask_table(set_pool)
    alice, _bob = game.players
    # The land drop counted (CR 305.2: the headless table counts it only
    # while costs are enforced).
    _w2g4_put(game, _w2g4_card(set_pool, "Forest"))
    game.enforce_mana_costs = True
    for _ in range(4):
        assert game._draw_with_replacements(alice, 1) == 0
    assert _w2g4_names(alice.exile) == ["Grizzly Bears", "Forest", "Lightning Bolt", "Mountain"]
    assert _w2g4_offered(game, 0) == [
        ("exile", "Grizzly Bears", "Uba Mask"), ("exile", "Forest", "Uba Mask"),
        ("exile", "Lightning Bolt", "Uba Mask"), ("exile", "Mountain", "Uba Mask"),
    ]
    assert _w2g4_offered(game, 1) == []
    played = game.cast_from_hand(0, "Forest", from_zone="exile")
    assert played.supported, played.details
    second = game.cast_from_hand(0, "Mountain", from_zone="exile")
    assert not second.supported
    # The cast is about the permission, not the mana.
    game.enforce_mana_costs = False
    cast = game.cast_from_hand(0, "Grizzly Bears", from_zone="exile")
    assert cast.supported, cast.details
    _w2g4_settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Forest", "Forest", "Grizzly Bears", "Uba Mask",
    ]
    assert _w2g4_names(alice.exile) == ["Lightning Bolt", "Mountain"]
    # Bob's turn, then Alice's: the draw step's card is exiled and offered;
    # last turn's two stay exiled and closed.
    game.start_next_turn()
    _w2g4_settle(game)
    assert _w2g4_offered(game, 0) == []
    game.start_next_turn()
    _w2g4_settle(game)
    assert _w2g4_names(alice.exile) == ["Lightning Bolt", "Mountain", "Island"]
    assert _w2g4_offered(game, 0) == [("exile", "Island", "Uba Mask")]
    assert not game.cast_from_hand(0, "Lightning Bolt", from_zone="exile",
                                   target_player_index=1).supported


def test_w2g4_uba_mask_each_seat_plays_its_own_and_an_empty_library_loses_nothing(set_pool):
    """Bob's draw is exiled by Alice's Mask and is Bob's to play (the exiler,
    not the Mask's controller). CR 614.11: a draw from an empty library is
    replaced too, so it exiles nothing and the player does not lose
    (CR 704.5b: no draw was attempted)."""
    game, (_mask,) = _w2g4_mask_table(set_pool)
    alice, bob = game.players
    game._draw_with_replacements(bob, 2)
    assert _w2g4_names(bob.exile) == ["Plains", "Giant Growth"]
    assert _w2g4_offered(game, 1) == [
        ("exile", "Plains", "Uba Mask"), ("exile", "Giant Growth", "Uba Mask"),
    ]
    assert _w2g4_offered(game, 0) == []
    alice.library.clear()
    assert game._draw_with_replacements(alice, 1) == 0
    game.check_state_based_actions()
    assert not alice.lost
    assert any("Alice exiles nothing instead of drawing" in line for line in game.log)


def test_w2g4_uba_mask_leaving_closes_its_cards_and_draws_are_draws_again(set_pool):
    """The play permission is the Mask's static ability: once it leaves, the
    cards it exiled this turn stay exiled and are nobody's to play (CR 611.3a;
    a new Mask is a new object with an empty record, CR 400.7), and a draw is
    a draw."""
    game, (mask,) = _w2g4_mask_table(set_pool)
    alice, _bob = game.players
    game._draw_with_replacements(alice, 1)
    assert _w2g4_offered(game, 0) == [("exile", "Grizzly Bears", "Uba Mask")]
    game.sacrifice_permanent(mask)
    assert _w2g4_offered(game, 0) == []
    assert _w2g4_names(alice.exile) == ["Grizzly Bears"]
    _w2g4_put(game, _w2g4_card(set_pool, "Uba Mask"))
    assert _w2g4_offered(game, 0) == []
    game.sacrifice_permanent(next(iter(game.controlled_by(0))))
    assert game._draw_with_replacements(alice, 1) == 1
    assert _w2g4_names(alice.hand) == ["Forest"]


def test_w2g4_two_uba_masks_the_drawer_picks_one_and_only_that_one_opens_it(set_pool):
    """Two Masks are two replacement effects for one draw: the drawer picks
    which applies (CR 616.1e, an ``effect_order`` prompt at an interactive
    seat; the first by default), the draw is consumed by it, and the card is
    linked to that Mask — only its leaving closes the card."""
    for interactive in ((), (0,)):
        game, (first, second) = _w2g4_mask_table(set_pool, masks=2, interactive=interactive)
        alice, _bob = game.players
        assert game._draw_with_replacements(alice, 1) == 0
        chosen = []
        if interactive:
            def answer(game, choice):
                keys = list(choice.data["_keys"])
                chosen.append(keys[1])
                assert game.resolve_pending_choice(
                    "effect_order", choice.player_index, option_index=1,
                )

            _w2g4_settle(game, answers={"effect_order": answer})
            assert len(chosen) == 1
        assert _w2g4_names(alice.exile) == ["Grizzly Bears"]
        held = [mask for mask in (first, second) if mask.metadata.get("linked_exile")]
        assert len(held) == 1
        [linker] = held
        if interactive:
            # The answer named the second Mask, and the card is linked to it.
            assert chosen == [f"_exile_drawn_card_face_up_instead:{second.permanent_id}"]
            assert linker is second
        other = second if linker is first else first
        game.sacrifice_permanent(other)
        assert _w2g4_offered(game, 0) == [("exile", "Grizzly Bears", "Uba Mask")]
        game.sacrifice_permanent(linker)
        assert _w2g4_offered(game, 0) == []

# ==== end W2G4 ======================================================

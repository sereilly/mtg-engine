"""Betrayers of Kamigawa creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
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

from engine import Game as _w1g1_Game, PlayerState as _w1g1_PlayerState
from engine.models import Permanent as _w1g1_Permanent
from tests.helpers import (_mk_creature_card as _w1g1_creature,
                           _nosick as _w1g1_nosick,
                           declare_attack as _w1g1_declare_attack,
                           drive_combat as _w1g1_drive_combat,
                           settle as _w1g1_settle)


def _w1g1_ninjutsu_table(
    set_pool, ninja, *, runners=1, theirs=(), their_hand=(), their_graveyard=(),
    my_graveyard=(), library=(), blocks=None,
):
    """*ninja* in P1's hand and *runners* vanilla 2/2s attacking P2, with
    *blocks* declared (none by default): the declare blockers step, blocks
    locked, the damage still to come — the window ninjutsu is printed for
    (CR 702.49a; "after blockers have been declared", 2021-03-19)."""
    pool = set_pool("BOK")
    mine = [
        _w1g1_nosick(_w1g1_Permanent(card=_w1g1_creature(f"Runner {i}", 2, 2)))
        for i in range(runners)
    ]
    defenders = [_w1g1_nosick(_w1g1_Permanent(card=c)) for c in theirs]
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(
            name="P1", hand=[pool[ninja]], battlefield=mine,
            graveyard=list(my_graveyard), library=list(library), life=20,
        ),
        _w1g1_PlayerState(
            name="P2", hand=list(their_hand), battlefield=defenders,
            graveyard=list(their_graveyard),
            library=[_w1g1_creature("Filler", 1, 1)] * 5, life=20,
        ),
    ])
    game.enforce_mana_costs = False
    game._settle()
    _w1g1_declare_attack(game, 0, blocks=blocks)
    return game, mine, defenders


def _w1g1_ninjutsu(game, ninja, runner):
    """Activate *ninja*'s ninjutsu returning *runner*, and resolve it."""
    result = game.activate_from_hand(
        0, ninja, cost_permanent_ids=[runner.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_settle(game)
    entered = next(p for p in game.controlled_by(0) if p.card.name == ninja)
    return entered


def test_w1g1_ninja_of_the_deep_hours_swaps_in_and_draws_on_combat_damage(set_pool):
    """Ninjutsu {1}{U}: the unblocked Runner goes home, the Ninja enters tapped
    and attacking P2 (CR 702.49c) and deals its 2 — and "Whenever this
    creature deals combat damage to a player, you may draw a card"."""
    library = [set_pool("BOK")["Ninja of the Deep Hours"]]
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Ninja of the Deep Hours", library=[_w1g1_creature("Drawn", 1, 1)],
    )
    ninja = _w1g1_ninjutsu(game, "Ninja of the Deep Hours", mine[0])
    assert ninja.tapped and ninja.attacking and not ninja.blocked
    assert [c.name for c in game.players[0].hand] == ["Runner 0"]
    _w1g1_drive_combat(game)
    assert game.players[1].life == 18
    assert sorted(c.name for c in game.players[0].hand) == ["Drawn", "Runner 0"]
    assert library  # the pool lookup above is the card under test


def test_w1g1_mistblade_shinobi_returns_a_creature_that_player_controls(set_pool):
    """"…you may return target creature **that player** controls to its
    owner's hand." The damaged player's creature goes home; P1's own second
    attacker — a creature the sentence does not name — stays."""
    elves = _w1g1_creature("Defender", 1, 1)
    game, mine, defenders = _w1g1_ninjutsu_table(
        set_pool, "Mistblade Shinobi", runners=2, theirs=[elves],
    )
    _w1g1_ninjutsu(game, "Mistblade Shinobi", mine[0])
    _w1g1_drive_combat(game)
    assert [c.name for c in game.players[1].hand] == ["Defender"]
    assert not list(game.controlled_by(1))
    assert any(p is mine[1] for p in game.controlled_by(0))
    assert game.players[1].life == 20 - 1 - 2


def test_w1g1_walker_of_secret_ways_looks_at_that_players_hand(set_pool):
    """"Whenever this creature deals combat damage to a player, look at that
    player's hand." The damaged seat's hand, shown to P1 (a ``hand_reveal``
    prompt), never P1's own."""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Walker of Secret Ways",
        their_hand=[_w1g1_creature("Secret A", 1, 1), _w1g1_creature("Secret B", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Walker of Secret Ways", mine[0])
    shown = []
    _w1g1_drive_combat(game, answers={
        "hand_reveal": lambda g, choice: (
            shown.append((
                choice.player_index, choice.data.get("target_index"),
                list(choice.data.get("card_names") or ()),
            )),
            g.discard_pending_choice(choice),
        ),
    })
    assert shown == [(0, 1, ["Secret A", "Secret B"])]
    assert any("looked at P2's hand (2 cards)" in line for line in game.log)


def test_w1g1_walker_of_secret_ways_returns_a_ninja_only_during_your_turn(set_pool):
    """"{1}{U}: Return target Ninja you control to its owner's hand. Activate
    only during your turn." Its own body is a Ninja it controls; on P2's turn
    the clause refuses it."""
    walker_card = set_pool("BOK")["Walker of Secret Ways"]
    walker = _w1g1_nosick(_w1g1_Permanent(card=walker_card))
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(name="P1", battlefield=[walker], life=20),
        _w1g1_PlayerState(name="P2", life=20),
    ])
    game.enforce_mana_costs = False
    game._settle()
    game.active_player_index = 1
    game._set_phase_and_step("precombat_main", None)
    refused = game.activate_permanent_ability(
        0, "Walker of Secret Ways", target_permanent_ids=[walker.permanent_id],
    )
    assert not refused.supported
    assert any(walker is p for p in game.controlled_by(0))
    game.active_player_index = 0
    result = game.activate_permanent_ability(
        0, "Walker of Secret Ways", target_permanent_ids=[walker.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_settle(game)
    assert [c.name for c in game.players[0].hand] == ["Walker of Secret Ways"]


def test_w1g1_okiba_gang_shinobi_makes_that_player_discard_two(set_pool):
    """"…that player discards two cards." (Of three, one is left.)"""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Okiba-Gang Shinobi",
        their_hand=[_w1g1_creature(f"Card {i}", 1, 1) for i in range(3)],
    )
    _w1g1_ninjutsu(game, "Okiba-Gang Shinobi", mine[0])
    _w1g1_drive_combat(game)
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 2
    assert game.players[1].life == 17


def test_w1g1_skullsnatcher_exiles_up_to_two_from_that_players_graveyard(set_pool):
    """"…exile up to two target cards from that player's graveyard." Two of
    P2's three go to exile; P1's own graveyard is not the pile named."""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Skullsnatcher",
        their_graveyard=[_w1g1_creature(f"Dead {i}", 1, 1) for i in range(3)],
        my_graveyard=[_w1g1_creature("Mine", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Skullsnatcher", mine[0])
    _w1g1_drive_combat(game)
    assert len(game.players[1].exile) == 2
    assert len(game.players[1].graveyard) == 1
    assert [c.name for c in game.players[0].graveyard] == ["Mine"]


def test_w1g1_throat_slitter_destroys_a_nonblack_creature_that_player_controls(set_pool):
    """"…destroy target nonblack creature that player controls." P2's
    colourless Defender dies, P2's black creature survives (nonblack), and so
    does P1's own nonblack attacker (that player)."""
    black = set_pool("BOK")["Skullsnatcher"]
    game, mine, defenders = _w1g1_ninjutsu_table(
        set_pool, "Throat Slitter", runners=2,
        theirs=[_w1g1_creature("Defender", 1, 1), black],
    )
    _w1g1_ninjutsu(game, "Throat Slitter", mine[0])
    _w1g1_drive_combat(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Skullsnatcher"]
    assert [c.name for c in game.players[1].graveyard] == ["Defender"]
    assert any(p is mine[1] for p in game.controlled_by(0))


def test_w1g1_higure_searches_for_a_ninja_card(set_pool):
    """"Whenever Higure deals combat damage to a player, you may search your
    library for a Ninja card, reveal it, put it into your hand, then
    shuffle." The Ninja comes out of a library of vanillas."""
    pool = set_pool("BOK")
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Higure, the Still Wind",
        library=[_w1g1_creature("Not A", 1, 1), pool["Skullsnatcher"],
                 _w1g1_creature("Not B", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Higure, the Still Wind", mine[0])
    _w1g1_drive_combat(game)
    assert sorted(c.name for c in game.players[0].hand) == ["Runner 0", "Skullsnatcher"]
    assert game.players[1].life == 17


def test_w1g1_higure_makes_only_a_ninja_unblockable(set_pool):
    """"{2}: Target Ninja creature can't be blocked this turn." A creature
    that is no Ninja is refused as the target; Higure, a Ninja, takes it, and
    P2's declared block on it is then refused."""
    pool = set_pool("BOK")
    higure = _w1g1_nosick(_w1g1_Permanent(card=pool["Higure, the Still Wind"]))
    other = _w1g1_nosick(_w1g1_Permanent(card=_w1g1_creature("Plain", 2, 2)))
    wall = _w1g1_nosick(_w1g1_Permanent(card=_w1g1_creature("Wall", 0, 5)))
    game = _w1g1_Game(players=[
        _w1g1_PlayerState(name="P1", battlefield=[higure, other], life=20),
        _w1g1_PlayerState(name="P2", battlefield=[wall], life=20),
    ])
    game.enforce_mana_costs = False
    game._settle()
    refused = game.activate_permanent_ability(
        0, "Higure, the Still Wind", target_permanent_ids=[other.permanent_id],
    )
    assert not refused.supported
    result = game.activate_permanent_ability(
        0, "Higure, the Still Wind", target_permanent_ids=[higure.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_settle(game)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0, 1], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    ok, _why = game.declare_blockers(1, {0: 0})
    assert not ok
    ok, why = game.declare_blockers(1, {0: 1})
    assert ok, why


def test_w1g1_ink_eyes_reanimates_from_that_players_graveyard(set_pool):
    """"…you may put target creature card from that player's graveyard onto
    the battlefield under your control." P2's creature card comes back under
    P1."""
    game, mine, _ = _w1g1_ninjutsu_table(
        set_pool, "Ink-Eyes, Servant of Oni",
        their_graveyard=[_w1g1_creature("Fallen", 3, 3)],
        my_graveyard=[_w1g1_creature("Mine", 1, 1)],
    )
    _w1g1_ninjutsu(game, "Ink-Eyes, Servant of Oni", mine[0])
    _w1g1_drive_combat(game)
    assert "Fallen" in [p.card.name for p in game.controlled_by(0)]
    assert not game.players[1].graveyard
    assert [c.name for c in game.players[0].graveyard] == ["Mine"]
    assert game.players[1].life == 15

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.
#
# The five Patrons (offering, CR 702.48, and each one's second line) and
# Kentaro, the Smiling Cat's granted alternative cost.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.cast_timing import casts_at_instant_speed as _w1g2_instant_speed
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle

_W1G2_FOX_OFFERING = "sacrifice a fox"


def _w1g2_table(set_pool, *, hands=((), ()), mana=False, interactive=()):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]))
        for seat in range(2)
    ])
    game.enforce_mana_costs = mana
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat, *, tapped=False):
    permanent = _W1G2Permanent(card=card, tapped=tapped)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_names(cards):
    return sorted(card.name for card in cards)


def _w1g2_board(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))


def test_w1g2_patron_of_the_kitsune_offering_reduces_by_the_foxs_mana_cost(set_pool):
    """Three white mana floating: the Patron's {4}{W}{W} is out of reach, and
    offering Kitsune Blademaster ({2}{W}) takes {2}{W} off it (CR 702.48c:
    generic off generic, white off white) — exactly the three. The Fox is
    sacrificed as the cost is paid (CR 702.48b)."""
    bok, chk = set_pool("BOK"), set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([bok["Patron of the Kitsune"]], ()), mana=True)
    fox = _w1g2_put(game, chk["Kitsune Blademaster"], 0)
    game.players[0].mana_pool.update({"W": 3})
    refused = game.cast_from_hand(0, "Patron of the Kitsune")
    assert not refused.supported and "insufficient mana" in refused.details
    assert game.is_on_battlefield(fox)
    result = game.cast_from_hand(
        0, "Patron of the Kitsune", optional_cost_payments={_W1G2_FOX_OFFERING: 1},
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_board(game, 0) == ["Patron of the Kitsune"]
    assert _w1g2_names(game.players[0].graveyard) == ["Kitsune Blademaster"]
    assert not any(game.players[0].mana_pool.values())
    assert "Patron of the Kitsune costs {2}{W} less to cast (offering Kitsune Blademaster)" in game.log


def test_w1g2_offering_sacrifices_the_fox_the_caster_names(set_pool):
    """Two Foxes; the caster names the cheaper one, so the reduction is {W}
    (Kitsune Diviner) and the Blademaster stays — the permanent the reduction
    is sized by is the permanent sacrificed (CR 702.48b)."""
    bok, chk = set_pool("BOK"), set_pool("CHK")
    game = _w1g2_table(set_pool, hands=([bok["Patron of the Kitsune"]], ()), mana=True)
    blademaster = _w1g2_put(game, chk["Kitsune Blademaster"], 0)
    diviner = _w1g2_put(game, chk["Kitsune Diviner"], 0)
    game.players[0].mana_pool.update({"W": 5})
    result = game.cast_from_hand(
        0, "Patron of the Kitsune", optional_cost_payments={_W1G2_FOX_OFFERING: 1},
        cost_permanent_ids=[diviner.permanent_id],
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert game.is_on_battlefield(blademaster)
    assert _w1g2_names(game.players[0].graveyard) == ["Kitsune Diviner"]
    assert not any(game.players[0].mana_pool.values())


def test_w1g2_offering_opens_the_instant_window_only_when_paid(set_pool):
    """Bob's Lightning Bolt is on the stack. With a Fox on Alice's side the
    Patron may *begin* to be cast (CR 601.3c), but a cast that declines the
    offering is refused with nothing spent; one that pays it goes on the
    stack above the Bolt and resolves first. With no Fox there is no window."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=(
        [bok["Patron of the Kitsune"]], [lea["Lightning Bolt"]],
    ))
    patron = game.players[0].hand[0]
    assert not _w1g2_instant_speed(patron, game, 0)
    fox = _w1g2_put(game, chk["Eight-and-a-Half-Tails"], 0)
    assert _w1g2_instant_speed(patron, game, 0)
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    refused = game.queue_from_hand(0, "Patron of the Kitsune")
    assert not refused.supported and "702.48a" in refused.details
    assert game.is_on_battlefield(fox) and len(game.stack) == 1
    result = game.queue_from_hand(
        0, "Patron of the Kitsune", optional_cost_payments={_W1G2_FOX_OFFERING: 1},
    )
    assert result.supported, result
    assert [item.card.name for item in game.stack] == ["Lightning Bolt", "Patron of the Kitsune"]
    _w1g2_settle(game)
    assert _w1g2_board(game, 0) == ["Patron of the Kitsune"]
    assert game.players[0].life == 17


def test_w1g2_patron_of_the_akki_attack_pumps_every_creature_you_control(set_pool):
    """"Whenever Patron of the Akki attacks, creatures you control get +2/+0
    until end of turn" — the Patron and the Bears it attacks beside; the
    opponent's creature is untouched."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    from tests.helpers import declare_attack as _w1g2_declare_attack

    game = _w1g2_table(set_pool)
    patron = _w1g2_put(game, bok["Patron of the Akki"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_declare_attack(game, 0)
    _w1g2_settle(game)
    assert (patron.effective_power, bears.effective_power) == (7, 4)
    assert theirs.effective_power == 3


def test_w1g2_patron_of_the_kitsune_gains_a_life_for_each_attacker_either_side(set_pool):
    """Ruling 2005-02-01: "You may gain life when any creatures are declared
    as attackers, not just for attacking creatures you control" — Bob's two
    attackers give Alice 2 life, answered by default."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    from tests.helpers import declare_attack as _w1g2_declare_attack

    game = _w1g2_table(set_pool)
    _w1g2_put(game, bok["Patron of the Kitsune"], 0)
    _w1g2_put(game, lea["Grizzly Bears"], 1)
    _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_declare_attack(game, 1)
    _w1g2_settle(game)
    assert game.players[0].life == 22


def test_w1g2_patron_of_the_moon_puts_up_to_two_lands_tapped(set_pool):
    """"{1}: Put up to two land cards from your hand onto the battlefield
    tapped." A person picks one of the three lands (the instant is never
    offered) and it enters tapped; a seat nobody sits in puts two."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    hand = [lea["Forest"], lea["Island"], lea["Swamp"], lea["Giant Growth"]]
    game = _w1g2_table(set_pool, hands=(hand, ()), interactive=(0,))
    patron = _w1g2_put(game, bok["Patron of the Moon"], 0)
    assert game.activate_permanent_ability(
        0, "Patron of the Moon", permanent_index=game.battlefield_index_of(patron),
    ).supported
    owed = _w1g2_settle(game, defaults=False)
    assert owed is not None and owed.kind == "choose_cards_in_hand"
    offered = sorted(game.players[0].hand[i].name for i in game.live_choose_cards_in_hand(owed))
    assert offered == ["Forest", "Island", "Swamp"]
    island = next(i for i, c in enumerate(game.players[0].hand) if c.name == "Island")
    assert game.confirm_choose_cards_in_hand(0, [island])
    _w1g2_settle(game)
    (entered,) = [perm for perm in game.controlled_by(0) if perm.card.name == "Island"]
    assert entered.tapped
    assert _w1g2_names(game.players[0].hand) == ["Forest", "Giant Growth", "Swamp"]

    game = _w1g2_table(set_pool, hands=(hand, ()))
    patron = _w1g2_put(game, bok["Patron of the Moon"], 0)
    assert game.activate_permanent_ability(
        0, "Patron of the Moon", permanent_index=game.battlefield_index_of(patron),
    ).supported
    _w1g2_settle(game)
    lands = [perm for perm in game.controlled_by(0) if perm.has_type("land")]
    assert len(lands) == 2 and all(perm.tapped for perm in lands)
    assert len(game.players[0].hand) == 2


def test_w1g2_patron_of_the_nezumi_drains_the_owner_of_each_permanent(set_pool):
    """Wrath of God takes the Patron, Alice's Bears and Bob's two creatures:
    Bob loses 2 (ruling 2005-02-01: it triggers even dying beside the
    others), Alice nothing. Then Alice's stolen Grizzly Bears goes to Bob's
    graveyard and Bob — "that player", its owner — loses 1, not the thief."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=([lea["Wrath of God"]], ()))
    _w1g2_put(game, bok["Patron of the Nezumi"], 0)
    _w1g2_put(game, lea["Grizzly Bears"], 0)
    _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_put(game, lea["Grizzly Bears"], 1)
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g2_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 18)

    game = _w1g2_table(set_pool, hands=([lea["Control Magic"], lea["Terror"]], ()))
    _w1g2_put(game, bok["Patron of the Nezumi"], 0)
    stolen = _w1g2_put(game, lea["Grizzly Bears"], 1)
    assert game.cast_from_hand(
        0, "Control Magic", target_permanent_ids=[stolen.permanent_id],
    ).supported
    _w1g2_settle(game)
    assert game.controller_index_of(stolen) == 0
    assert game.cast_from_hand(0, "Terror", target_permanent_ids=[stolen.permanent_id]).supported
    _w1g2_settle(game)
    assert (game.players[0].life, game.players[1].life) == (20, 19)


def test_w1g2_patron_of_the_nezumi_counts_a_token_and_not_a_discarded_card(set_pool):
    """A token Bob sacrifices is put into his graveyard before it ceases to
    exist (CR 111.7), so it is a permanent put there; two cards Mind Twist
    makes him discard never were permanents."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    from engine.tokens import make_token_card as _w1g2_token_card

    game = _w1g2_table(set_pool, hands=(
        [lea["Mind Twist"]], [lea["Giant Growth"], lea["Lightning Bolt"]],
    ))
    _w1g2_put(game, bok["Patron of the Nezumi"], 0)
    token = _w1g2_put(game, _w1g2_token_card(
        "Spirit", 1, 1, "Token Creature — Spirit",
    ), 1)
    game.sacrifice_permanent(token)
    _w1g2_settle(game)
    assert game.players[1].life == 19, game.log[-6:]
    assert game.cast_from_hand(0, "Mind Twist", target_player_index=1, x_value=2).supported
    _w1g2_settle(game)
    assert game.players[1].hand == [] and len(game.players[1].graveyard) == 2
    assert game.players[1].life == 19


def test_w1g2_patron_of_the_orochi_untaps_forests_and_green_creatures_once(set_pool):
    """"{T}: Untap all Forests and all green creatures. Activate only once
    each turn." Both sides' Forests and green creatures untap, a tapped
    Mountain and a tapped red creature stay tapped, and a second activation
    the same turn is refused."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    patron = _w1g2_put(game, bok["Patron of the Orochi"], 0)
    forest = _w1g2_put(game, lea["Forest"], 0, tapped=True)
    their_forest = _w1g2_put(game, lea["Forest"], 1, tapped=True)
    mountain = _w1g2_put(game, lea["Mountain"], 0, tapped=True)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0, tapped=True)
    goblins = _w1g2_put(game, lea["Hill Giant"], 0, tapped=True)
    assert game.activate_permanent_ability(
        0, "Patron of the Orochi", permanent_index=game.battlefield_index_of(patron),
    ).supported
    _w1g2_settle(game)
    assert not forest.tapped and not their_forest.tapped and not bears.tapped
    assert mountain.tapped and goblins.tapped
    # The Patron is green and untapped itself; a second activation is refused.
    assert not patron.tapped
    refused = game.activate_permanent_ability(
        0, "Patron of the Orochi", permanent_index=game.battlefield_index_of(patron),
    )
    assert not refused.supported


def test_w1g2_kentaro_lets_samurai_be_cast_for_generic_mana(set_pool):
    """Kentaro on the battlefield: Kitsune Blademaster ({2}{W}) is cast with
    three red mana as its alternative cost ({X}, X its mana value); a
    non-Samurai is offered nothing, and Bob's Samurai is offered nothing by
    Alice's Kentaro (CR 109.5, "spells you cast")."""
    bok, chk, lea = set_pool("BOK"), set_pool("CHK"), set_pool("LEA")
    game = _w1g2_table(set_pool, hands=(
        [chk["Kitsune Blademaster"], lea["Grizzly Bears"]], [chk["Kitsune Blademaster"]],
    ), mana=True)
    _w1g2_put(game, bok["Kentaro, the Smiling Cat"], 0)
    assert game.applicable_alternative_costs(1, game.players[1].hand[0]) == ()
    assert game.applicable_alternative_costs(0, game.players[0].hand[1]) == ()
    (offer,) = [
        entry for entry in game.cast_cost_offers(0, game.players[0].hand[0], spell_hand_index=0)
        if entry["kind"] == "alternative"
    ]
    assert offer["label"] == "pay {3}"
    assert offer["granted_by"] == "Kentaro, the Smiling Cat"
    game.players[0].mana_pool.update({"R": 3})
    assert not game.cast_from_hand(0, "Kitsune Blademaster").supported
    result = game.cast_from_hand(0, "Kitsune Blademaster", alternative_cost=True)
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_board(game, 0) == ["Kentaro, the Smiling Cat", "Kitsune Blademaster"]
    assert not any(game.players[0].mana_pool.values())


def test_w1g2_kentaro_applies_only_while_on_the_battlefield(set_pool):
    """Ruling 2005-02-01: "Kentaro's ability only applies while Kentaro is on
    the battlefield. You have to pay for Kentaro normally." In hand it grants
    nothing, to itself (a Samurai) or to another Samurai."""
    bok, chk = set_pool("BOK"), set_pool("CHK")
    game = _w1g2_table(set_pool, hands=(
        [bok["Kentaro, the Smiling Cat"], chk["Kitsune Blademaster"]], (),
    ), mana=True)
    assert game.applicable_alternative_costs(0, game.players[0].hand[0]) == ()
    assert game.applicable_alternative_costs(0, game.players[0].hand[1]) == ()

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# Damage: redirection, prevention and per-player damage (CR 614.9, 615).
# Each test places the card, activates it through the engine's own entry
# point, deals the damage it is about and reads the board after `settle`.

import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SEATS = [
    _w1g5_pytest.param(set(), id="nobody-asked"),
    _w1g5_pytest.param({0, 1}, id="interactive"),
]


def _w1g5_table(set_pool, interactive=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g5_settle(game)
    return game


def _w1g5_put(game, card, seat=0):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g5_activate(game, permanent, seat=0, **announce):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **announce,
    )
    assert result.supported, (result, game.log[-6:])
    _w1g5_settle(game)
    return result


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_opal_eye_takes_the_next_damage_of_the_chosen_source(set_pool, interactive):
    """"{T}: The next time a source of your choice would deal damage this
    turn, that damage is dealt to Opal-Eye instead." The chosen Prodigal
    Sorcerer pings Opal-Eye's controller: the point lands on Opal-Eye and the
    player loses nothing (CR 614.9). The redirect is one instance — the
    second ping is dealt as aimed — and an unchosen source is never moved."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, interactive)
    opal = _w1g5_put(game, bok["Opal-Eye, Konda's Yojimbo"])
    sorcerer = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    other = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    _w1g5_activate(game, opal, ability_index=0,
                   target_permanent_ids=[sorcerer.permanent_id])
    assert opal.tapped
    # The other Sorcerer — the same card, a different object — is not the
    # source chosen (CR 609.7a names one object).
    _w1g5_activate(game, other, seat=1, target_player_index=0)
    assert game.players[0].life == 19 and opal.damage_marked == 0, game.log
    _w1g5_activate(game, sorcerer, seat=1, target_player_index=0)
    assert game.players[0].life == 19 and opal.damage_marked == 1, game.log
    assert any("is dealt to Opal-Eye" in line for line in game.log), game.log
    sorcerer.tapped = False
    _w1g5_activate(game, sorcerer, seat=1, target_player_index=0)
    assert game.players[0].life == 18 and opal.damage_marked == 1, game.log


def test_w1g5_opal_eye_gone_before_the_damage_moves_nothing(set_pool):
    """CR 614.9: a redirect whose new recipient has left the battlefield does
    nothing — the damage is dealt to its original recipient."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    opal = _w1g5_put(game, bok["Opal-Eye, Konda's Yojimbo"])
    sorcerer = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    _w1g5_activate(game, opal, ability_index=0,
                   target_permanent_ids=[sorcerer.permanent_id])
    game.sacrifice_permanent(opal)
    _w1g5_settle(game)
    _w1g5_activate(game, sorcerer, seat=1, target_player_index=0)
    assert game.players[0].life == 19, game.log


def test_w1g5_opal_eye_prevents_the_next_1_damage_to_itself(set_pool):
    """"{1}{W}: Prevent the next 1 damage that would be dealt to Opal-Eye
    this turn." Two activations shield two points; a Lightning Bolt's three
    leaves 1 marked."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, hand=[lea["Lightning Bolt"]])
    opal = _w1g5_put(game, bok["Opal-Eye, Konda's Yojimbo"])
    _w1g5_activate(game, opal, ability_index=1)
    _w1g5_activate(game, opal, ability_index=1)
    assert not opal.tapped
    result = game.cast_from_hand(0, "Lightning Bolt",
                                 target_permanent_ids=[opal.permanent_id])
    assert result.supported, result.details
    _w1g5_settle(game)
    assert opal.damage_marked == 1 and game.is_on_battlefield(opal), game.log


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_kitsune_palliator_shields_every_creature_and_player_once(
    set_pool, interactive,
):
    """"{T}: Prevent the next 1 damage that would be dealt to each creature
    and each player this turn." One shield on each creature and each player
    as it resolves: Pestilence's first activation is prevented everywhere,
    but a creature that entered afterwards has none (ruling 2005-02-01), and
    the second activation is dealt to everyone."""
    bok, lea, ed2 = set_pool("BOK"), set_pool("LEA"), set_pool("2ED")
    game = _w1g5_table(set_pool, interactive)
    palliator = _w1g5_put(game, bok["Kitsune Palliator"])
    bears = _w1g5_put(game, lea["Grizzly Bears"])
    pestilence = _w1g5_put(game, ed2["Pestilence"], seat=1)
    giant = _w1g5_put(game, lea["Hill Giant"], seat=1)
    _w1g5_activate(game, palliator)
    assert palliator.tapped
    late = _w1g5_put(game, lea["Grizzly Bears"], seat=1)
    _w1g5_activate(game, pestilence, seat=1)
    assert [p.life for p in game.players] == [20, 20], game.log
    assert [c.damage_marked for c in (palliator, bears, giant, late)] == [0, 0, 0, 1]
    _w1g5_activate(game, pestilence, seat=1)
    assert [p.life for p in game.players] == [19, 19], game.log
    assert [c.damage_marked for c in (palliator, bears, giant)] == [1, 1, 1]


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_heartless_hidetsugu_halves_each_life_total_rounded_down(
    set_pool, interactive,
):
    """"{T}: Heartless Hidetsugu deals damage to each player equal to half
    that player's life total, rounded down." Each seat's own total: 15 takes
    7 (rounded down) and 20 takes 10; at 1 life half is 0, and a seat dealt
    0 is dealt no damage (CR 120.8)."""
    bok = set_pool("BOK")
    game = _w1g5_table(set_pool, interactive)
    hidetsugu = _w1g5_put(game, bok["Heartless Hidetsugu"])
    game.players[1].life = 15
    _w1g5_activate(game, hidetsugu)
    assert [p.life for p in game.players] == [10, 8], game.log
    assert "Heartless Hidetsugu dealt 7 damage to P1" in game.log
    hidetsugu.tapped = False
    game.players[0].life = 1
    _w1g5_activate(game, hidetsugu)
    assert [p.life for p in game.players] == [1, 4], game.log


# The damage family's cards supported on arrival, each given a game.


def test_w1g5_split_tail_miko_shields_two_points_of_a_bolt(set_pool):
    """"{W}, {T}: Prevent the next 2 damage that would be dealt to any target
    this turn." On the Bears, a Lightning Bolt marks 1."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, opponent_hand=[lea["Lightning Bolt"]])
    miko = _w1g5_put(game, bok["Split-Tail Miko"])
    bears = _w1g5_put(game, lea["Grizzly Bears"])
    _w1g5_activate(game, miko, target_permanent_ids=[bears.permanent_id])
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_settle(game)
    assert bears.damage_marked == 1 and game.is_on_battlefield(bears), game.log


def test_w1g5_kami_of_false_hope_fogs_the_combat(set_pool):
    """"Sacrifice this creature: Prevent all combat damage that would be dealt
    this turn." Sacrificed after an attack is declared, the attacker deals
    nothing."""
    from tests.helpers import declare_attack, drive_combat

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    kami = _w1g5_put(game, bok["Kami of False Hope"])
    _w1g5_put(game, lea["Hill Giant"], seat=1)
    declare_attack(game, 1)
    _w1g5_activate(game, kami)
    drive_combat(game)
    assert game.players[0].life == 20 and not game.is_on_battlefield(kami), game.log


def test_w1g5_damage_triggers_kami_of_the_honored_dead_and_shinka_gatekeeper(set_pool):
    """"Whenever this creature is dealt damage, you gain that much life."
    (Kami of the Honored Dead) and "Whenever this creature is dealt damage, it
    deals that much damage to you." (Shinka Gatekeeper.) A Bolt at each: the
    Kami's controller gains 3, the Gatekeeper's loses 3 — after it died, from
    the last it knew (CR 603.10)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, opponent_hand=[lea["Lightning Bolt"]] * 2)
    kami = _w1g5_put(game, bok["Kami of the Honored Dead"])
    gatekeeper = _w1g5_put(game, bok["Shinka Gatekeeper"])
    for victim in (kami, gatekeeper):
        assert game.cast_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[victim.permanent_id],
        ).supported
        _w1g5_settle(game)
    assert game.players[0].life == 20 + 3 - 3, game.log
    assert kami.damage_marked == 3 and not game.is_on_battlefield(gatekeeper)


def test_w1g5_frostling_and_takenos_cavalry_ping_creatures(set_pool):
    """"Sacrifice this creature: It deals 1 damage to target creature."
    (Frostling) kills a Llanowar Elves; "{T}: This creature deals 1 damage to
    target attacking or blocking Spirit." (Takeno's Cavalry) is refused at a
    Spirit that is not in combat and kills one that attacks."""
    from tests.helpers import declare_attack

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    frostling = _w1g5_put(game, bok["Frostling"])
    elves = _w1g5_put(game, lea["Llanowar Elves"], seat=1)
    _w1g5_activate(game, frostling, target_permanent_ids=[elves.permanent_id])
    assert not game.is_on_battlefield(elves) and not game.is_on_battlefield(frostling)
    cavalry = _w1g5_put(game, bok["Takeno's Cavalry"])
    spirit = _w1g5_put(game, bok["Frostling"], seat=1)
    refused = game.activate_permanent_ability(
        0, cavalry.card.name, permanent_index=game.battlefield_index_of(cavalry),
        target_permanent_ids=[spirit.permanent_id],
    )
    assert not refused.supported and not cavalry.tapped
    declare_attack(game, 1)
    _w1g5_activate(game, cavalry, target_permanent_ids=[spirit.permanent_id])
    assert not game.is_on_battlefield(spirit), game.log


def test_w1g5_ronin_cliffrider_pings_each_defending_creature(set_pool):
    """"Whenever this creature attacks, you may have it deal 1 damage to each
    creature defending player controls." The Elves die, the Bears keep 1,
    and the attacker's own creature is untouched."""
    from tests.helpers import declare_attack, drive_combat

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool)
    _w1g5_put(game, bok["Ronin Cliffrider"])
    elves = _w1g5_put(game, lea["Llanowar Elves"], seat=1)
    bears = _w1g5_put(game, lea["Grizzly Bears"], seat=1)
    declare_attack(game, 0)
    drive_combat(game)
    assert not game.is_on_battlefield(elves) and bears.damage_marked == 1, game.log
    assert game.players[1].life == 18, game.log

# ==== end w1g5 ======================================================

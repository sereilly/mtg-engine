"""Prophecy sorceries.

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

Cards come from `set_pool("PCY")` / `set_cards("PCY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: untapped lands and untap steps ---
from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_cast_spec as _w1g4_cast_spec
from tests.helpers import resolve_stack as _w1g4_resolve


def _w1g4_sorcery_duel(*bodies_by_seat):
    """A duel with each seat's creatures on the battlefield, ready, seat 0
    active and mana costs off. Returns the game and the two permanent lists."""
    w1g4_game = _W1G4Game(
        players=[_W1G4PlayerState(name="W1G4-A"), _W1G4PlayerState(name="W1G4-B")]
    )
    w1g4_game.enforce_mana_costs = False
    w1g4_game.active_player_index = 0
    w1g4_placed = []
    for w1g4_seat, w1g4_cards in enumerate(bodies_by_seat):
        w1g4_row = []
        for w1g4_card in w1g4_cards:
            w1g4_perm = _W1G4Permanent(card=w1g4_card)
            w1g4_game._put_permanent_onto_battlefield(w1g4_seat, w1g4_perm, None)
            w1g4_perm.metadata["summoning_sickness_turn"] = -99
            w1g4_row.append(w1g4_perm)
        w1g4_placed.append(w1g4_row)
    return w1g4_game, w1g4_placed


def test_w1g4_panic_attack_offers_three_targets_at_announcement(set_pool):
    """CR 601.2c: "up to three" is announced as up to three distinct targets.
    The picker must offer that many, or the client sends a one-target cast and
    two thirds of the card are unreachable."""
    card = set_pool("PCY")["Panic Attack"]
    spec = _w1g4_cast_spec(card, _w1g4_compile(card))
    assert spec["max_targets"] == 3 and spec["distinct_targets"]


def test_w1g4_panic_attack_stops_exactly_the_three_it_named(set_pool):
    """Cast through the real entry point with three of four blockers named; at
    the declaration the three are refused and the fourth may still block."""
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game, (mine, theirs) = _w1g4_sorcery_duel(
        [lea["Grizzly Bears"]], [lea["Grizzly Bears"]] * 4
    )
    game.players[0].hand.append(pcy["Panic Attack"])
    named = theirs[:3]
    assert game.cast_from_hand(
        0, "Panic Attack", target_player_index=1,
        target_permanent_ids=[perm.permanent_id for perm in named],
    ).supported
    _w1g4_resolve(game)
    assert game.log.count("Grizzly Bears can't block this turn") == 3

    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.current_step = "declare_blockers"
    for slot in range(3):
        ok, _why = game.declare_blockers(1, {slot: 0})
        assert not ok, f"blocker {slot} was named by Panic Attack"
    assert game.declare_blockers(1, {3: 0})[0]

# --- W1G1: rhystic ---
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec


def _w1g1_sorcery_table(set_pool, seats: int = 2, *, active: int = 0, lands=()):
    """*seats* players, the *active* one first to be asked (CR 101.4), with
    ``lands[i]`` untapped Islands on seat i. Mana enforcement off for the cast;
    every rhystic payment is still made out of the board."""
    island = set_pool("LEA")["Island"]
    players = []
    for seat in range(seats):
        count = lands[seat] if seat < len(lands) else 0
        players.append(PlayerState(
            name=f"P{seat}", life=20,
            battlefield=[Permanent(card=island) for _ in range(count)],
        ))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game


def _w1g1_owed(game) -> list[int]:
    """Which seats are being asked to pay, in queue order."""
    return [c.player_index for c in game.pending_choices if c.kind == "optional_pay"]


def _w1g1_tapped(game, seat: int) -> int:
    return sum(1 for perm in game.controlled_by(game.players[seat]) if perm.tapped)


def test_soul_strings_returns_both_cards_when_no_one_can_pay_x(set_pool):
    """"Return two target creature cards from your graveyard to your hand
    unless any player pays {X}." X is the spell's own announced X: with X = 3 a
    two-Island opponent cannot buy it off, so both cards come back."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(0, 2))
    caster = game.players[0]
    caster.hand.append(set_pool("PCY")["Soul Strings"])
    caster.graveyard.extend([lea["Grizzly Bears"], lea["Hill Giant"], lea["Island"]])

    assert game.cast_from_hand(
        0, "Soul Strings", x_value=3, target_permanent_index=[0, 1]
    ).supported
    game.auto_resolve_pending_choices()

    assert sorted(card.name for card in caster.hand) == ["Grizzly Bears", "Hill Giant"]
    assert [card.name for card in caster.graveyard] == ["Island", "Soul Strings"]
    assert _w1g1_tapped(game, 1) == 0, "nothing was paid"


def test_soul_strings_is_bought_off_for_x_by_the_opponent_not_its_caster(set_pool):
    """With X = 2 the same opponent can pay, and does; the caster — asked first,
    because it is the active player — declines rather than paying to stop its
    own spell. The {X} is charged at the announced number, off the board."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(4, 2))
    caster = game.players[0]
    caster.hand.append(set_pool("PCY")["Soul Strings"])
    caster.graveyard.extend([lea["Grizzly Bears"], lea["Hill Giant"]])

    assert game.cast_from_hand(
        0, "Soul Strings", x_value=2, target_permanent_index=[0, 1]
    ).supported
    assert _w1g1_owed(game) == [0], "the active player is asked first"
    assert game.pending_choices[0].data["cost"] == {"generic": 2}, "X is 2"
    game.auto_resolve_pending_choices()

    assert "P0 declined to pay for Soul Strings" in game.log
    assert caster.hand == [], "the payment bought the return off"
    assert _w1g1_tapped(game, 0) == 0 and _w1g1_tapped(game, 1) == 2


def test_rhystic_payment_is_asked_in_turn_order_from_the_active_player(set_pool):
    """Four seats, seat 2 active and casting. CR 101.4 orders the offer from
    the active player around the table — 2, 3, 0 — and the first payment ends
    it (CR 118.12a: one "unless"), so seat 1 is never asked."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, 4, active=2, lands=(2, 2, 2, 2))
    caster = game.players[2]
    caster.hand.append(set_pool("PCY")["Soul Strings"])
    caster.graveyard.extend([lea["Grizzly Bears"], lea["Hill Giant"]])

    assert game.cast_from_hand(
        2, "Soul Strings", x_value=1, target_permanent_index=[0, 1]
    ).supported
    asked = []
    for answer in (False, False, True):
        asked.extend(_w1g1_owed(game))
        assert game.confirm_optional_pay(asked[-1], accept=answer)

    assert asked == [2, 3, 0]
    assert _w1g1_owed(game) == [], "seat 1 is never asked once seat 0 paid"
    assert caster.hand == [] and _w1g1_tapped(game, 0) == 1


def test_rhystic_scrying_discards_three_when_an_opponent_pays(set_pool):
    """"Draw three cards. Then **if** any player pays {2}, discard three cards."
    The polarity reversed: paying is what causes the discard — and the discard
    is the caster's, whoever paid. The paying opponent's own hand is untouched."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(0, 2))
    caster, payer = game.players
    caster.hand.append(set_pool("PCY")["Rhystic Scrying"])
    caster.library.extend([lea["Island"], lea["Forest"], lea["Swamp"], lea["Plains"]])
    payer.hand.append(lea["Mountain"])

    assert game.cast_from_hand(0, "Rhystic Scrying").supported
    assert len(caster.hand) == 3, "the draw happens first"
    assert game.confirm_optional_pay(0, accept=False), "the caster declines"
    assert _w1g1_owed(game) == [1]
    assert game.confirm_optional_pay(1, accept=True)
    game.auto_resolve_pending_choices()

    assert caster.hand == []
    assert sorted(c.name for c in caster.graveyard) == [
        "Forest", "Island", "Rhystic Scrying", "Swamp",
    ]
    assert [c.name for c in payer.hand] == ["Mountain"]
    assert _w1g1_tapped(game, 1) == 2


def test_rhystic_scrying_keeps_the_cards_when_no_one_pays(set_pool):
    """Left to the AI defaults: the caster never buys its own discard, and an
    opponent with no mana cannot — so the three cards stay."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(4, 0))
    caster = game.players[0]
    caster.hand.append(set_pool("PCY")["Rhystic Scrying"])
    caster.library.extend([lea["Island"], lea["Forest"], lea["Swamp"]])

    assert game.cast_from_hand(0, "Rhystic Scrying").supported
    game.auto_resolve_pending_choices()

    assert sorted(c.name for c in caster.hand) == ["Forest", "Island", "Swamp"]
    assert _w1g1_tapped(game, 0) == 0


def test_rhystic_syphon_drains_a_target_player_who_cannot_pay(set_pool):
    """"Unless target player pays {3}, that player loses 5 life and you gain 5
    life." One seat is offered — the one the spell targeted — and two Islands
    do not cover {3}."""
    game = _w1g1_sorcery_table(set_pool, lands=(0, 2))
    syphon = set_pool("PCY")["Rhystic Syphon"]
    game.players[0].hand.append(syphon)

    assert derive_cast_spec(syphon, compile_card_oracle(syphon)) == {"kind": "player"}
    assert game.cast_from_hand(0, "Rhystic Syphon", target_player_index=1).supported
    game.auto_resolve_pending_choices()

    assert (game.players[0].life, game.players[1].life) == (25, 15)


def test_rhystic_syphon_is_paid_off_by_the_target_alone(set_pool):
    """The offer goes to the target and nobody else: with three Islands the
    target pays, and the caster's own untapped lands are never asked."""
    game = _w1g1_sorcery_table(set_pool, lands=(5, 3))
    game.players[0].hand.append(set_pool("PCY")["Rhystic Syphon"])

    assert game.cast_from_hand(0, "Rhystic Syphon", target_player_index=1).supported
    assert _w1g1_owed(game) == [1]
    game.auto_resolve_pending_choices()

    assert (game.players[0].life, game.players[1].life) == (20, 20)
    assert (_w1g1_tapped(game, 0), _w1g1_tapped(game, 1)) == (0, 3)


def test_flay_takes_a_second_random_card_from_a_target_who_cannot_pay(set_pool):
    """"Target player discards a card at random. Then **that player** discards
    **another** card at random unless they pay {1}." Both discards come from
    the one player the spell targeted — never the caster's hand — and with no
    mana the second is not bought off."""
    lea = set_pool("LEA")
    flay = set_pool("PCY")["Flay"]
    game = _w1g1_sorcery_table(set_pool, lands=(3, 0))
    caster, victim = game.players
    caster.hand.extend([flay, lea["Forest"]])
    victim.hand.extend([lea["Island"], lea["Swamp"], lea["Mountain"]])

    assert derive_cast_spec(flay, compile_card_oracle(flay)) == {"kind": "player"}
    assert game.cast_from_hand(0, "Flay", target_player_index=1).supported
    game.auto_resolve_pending_choices()

    assert len(victim.hand) == 1 and len(victim.graveyard) == 2
    assert [c.name for c in caster.hand] == ["Forest"], "the caster discards nothing"


def test_flay_second_discard_is_bought_off_by_the_target_alone(set_pool):
    """The offer is the target's: one Island pays {1}, so only the first card
    goes. The caster is never asked."""
    lea = set_pool("LEA")
    game = _w1g1_sorcery_table(set_pool, lands=(3, 1))
    caster, victim = game.players
    caster.hand.append(set_pool("PCY")["Flay"])
    victim.hand.extend([lea["Island"], lea["Swamp"], lea["Mountain"]])

    assert game.cast_from_hand(0, "Flay", target_player_index=1).supported
    assert _w1g1_owed(game) == [1]
    game.auto_resolve_pending_choices()

    assert len(victim.hand) == 2 and len(victim.graveyard) == 1
    assert (_w1g1_tapped(game, 0), _w1g1_tapped(game, 1)) == (0, 1)

# --- W1G2: spell costs ---
from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import _mk_card as _w1g2_mk_card
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_typed(name, subtype, toughness=1):
    """A 1/*toughness* creature of *subtype*, so a -1/-1 is the difference
    between dying and surviving and the board says which creatures were hit."""
    card = _w1g2_mk_card(name, "{2}", f"Creature - {subtype}", "")
    card.raw.update({"power": "1", "toughness": str(toughness)})
    return _W1G2Permanent(card=card)


def _w1g2_outbreak_game(set_pool, mine=(), theirs=(), hand_extra=(), interactive=()):
    pcy, lea = set_pool("PCY"), set_pool("LEA")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            name="P1", battlefield=list(mine),
            hand=[pcy["Outbreak"]] + [lea[n] for n in hand_extra],
        ),
        _W1G2PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game._sync_control()
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_board(game):
    return sorted(p.card.name for _seat, p in game.permanents_with_controller())


def test_w1g2_outbreak_shrinks_only_the_creature_type_its_caster_names(set_pool):
    """"Choose a creature type. All creatures of that type get -1/-1 until end
    of turn."

    Two sentences, two steps: CR 608.2d's choice is made while the spell
    resolves and recorded in its scratchpad — Extinction's record, written by a
    sentence of its own — and "of that type" reads it back. The interactive
    seat's answer arrives before the sweep, so the board it takes is the one the
    player named: both Goblins die, on both sides, and the Bear lives.
    """
    program = _w1g2_compile(set_pool("PCY")["Outbreak"])
    assert program.supported, program.reason

    game = _w1g2_outbreak_game(
        set_pool,
        mine=[_w1g2_typed("My Goblin", "Goblin")],
        theirs=[_w1g2_typed("Their Goblin", "Goblin"), _w1g2_typed("Their Bear", "Bear"),
                _w1g2_typed("Their Elf", "Elf", toughness=2)],
        interactive=[0],
    )
    game.enforce_mana_costs = False
    result = game.cast_from_hand(0, "Outbreak")
    assert result.supported, result.details
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g2_resolve_stack(game)
    game._settle()

    assert _w1g2_board(game) == ["Their Bear", "Their Elf"], game.log


def test_w1g2_outbreak_lasts_until_end_of_turn(set_pool):
    """The -1/-1 is a one-shot layer-7c change swept with the turn: a 1/2 Elf
    survives it at 1/1 and is back to 1/2 after the cleanup step."""
    elf = _w1g2_typed("Their Elf", "Elf", toughness=2)
    game = _w1g2_outbreak_game(set_pool, theirs=[elf], interactive=[0])
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Outbreak")
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g2_resolve_stack(game)
    assert (elf.effective_power, elf.effective_toughness) == (0, 1), game.log

    game.resolve_cleanup_step(0)
    assert (elf.effective_power, elf.effective_toughness) == (1, 2)


def test_w1g2_outbreak_can_be_cast_by_discarding_a_swamp_card(set_pool):
    """"You may discard a Swamp card rather than pay this spell's mana cost."

    CR 118.9 with mana enforced and an empty pool: the Swamp card leaves the
    hand for the graveyard and the spell resolves. With no Swamp card in hand
    the offer is absent from the picker and the cast is refused at CR 601.2h
    with nothing spent — the Forest beside it answers nothing.
    """
    game = _w1g2_outbreak_game(set_pool, hand_extra=("Swamp",))
    game.enforce_mana_costs = True
    offers = game.cast_cost_offers(0, set_pool("PCY")["Outbreak"], spell_hand_index=0)
    alternative = next(o for o in offers if o["kind"] == "alternative")
    assert alternative["payable"]
    assert [c["name"] for c in alternative["hand_choices"]] == ["Swamp"]
    # The button names the price: the Swamp is discarded, not exiled.
    assert alternative["hand_verb"] == "discard"

    result = game.cast_from_hand(
        0, "Outbreak", alternative_cost=True, alternative_cost_hand_index=1,
    )
    assert result.supported, result.details
    _w1g2_resolve_stack(game)
    assert sorted(c.name for c in game.players[0].graveyard) == ["Outbreak", "Swamp"]
    assert game.players[0].hand == []

    game = _w1g2_outbreak_game(set_pool, hand_extra=("Forest",))
    game.enforce_mana_costs = True
    offers = game.cast_cost_offers(0, set_pool("PCY")["Outbreak"], spell_hand_index=0)
    assert not next(o for o in offers if o["kind"] == "alternative")["payable"]
    result = game.cast_from_hand(0, "Outbreak", alternative_cost=True)
    assert not result.supported
    assert sorted(c.name for c in game.players[0].hand) == ["Forest", "Outbreak"]


def test_w1g2_of_that_type_without_a_choice_in_front_refuses(set_pool):
    """"All creatures of that type get -1/-1" with no step of the same effect
    choosing a type names nothing — and an unresolved "that type" read as no
    narrowing would shrink the whole board. The line refuses instead."""
    from engine.grammar import compile_line

    compiled = compile_line("All creatures of that type get -1/-1 until end of turn.")
    assert not compiled.usable
    assert "no step of this effect chose" in (compiled.failure_reason or "")

# --- W1G5: prevention and odd ones ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_blessed_wind_table(set_pool, *, mine, theirs):
    """Blessed Wind in seat 0's hand, the two life totals given. W1G5's own."""
    me = _W1G5PlayerState(name="W1G5-A", hand=[set_pool("PCY")["Blessed Wind"]])
    me.life = mine
    them = _W1G5PlayerState(name="W1G5-B")
    them.life = theirs
    game = _W1G5Game(players=[me, them])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    return game, me, them


def test_w1g5_blessed_wind_sets_the_target_players_life_to_twenty(set_pool):
    """"Target player's life total becomes 20."

    CR 119.5 in both directions: aimed at an opponent on 31 it is a loss of 11,
    aimed at its caster on 4 a gain of 16 — and the seat is the one announced,
    not a default: the other player's total does not move either time.
    """
    card = set_pool("PCY")["Blessed Wind"]
    game, me, them = _w1g5_blessed_wind_table(set_pool, mine=4, theirs=31)
    spec = game.cast_target_spec(0, card)
    assert spec["kind"] == "player"
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}

    assert game.cast_from_hand(0, "Blessed Wind", target_player_index=1).supported
    _w1g5_resolve_stack(game)
    assert (me.life, them.life) == (4, 20)

    game, me, them = _w1g5_blessed_wind_table(set_pool, mine=4, theirs=31)
    assert game.cast_from_hand(0, "Blessed Wind", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert (me.life, them.life) == (20, 31)
    assert any("life total became 20 (was 4)" in line for line in game.log)


def test_w1g5_blessed_wind_gain_half_is_a_life_gain(set_pool):
    """The gain is an event, not an assignment (CR 119.5): a seat that can't
    gain life (CR 119.7) stays where it was, which an assignment would ignore.
    """
    from engine.models import Permanent

    game, me, _them = _w1g5_blessed_wind_table(set_pool, mine=7, theirs=20)
    game._put_permanent_onto_battlefield(
        1, Permanent(card=set_pool("MIR")["Forsaken Wastes"]), None,
    )
    assert game.cast_from_hand(0, "Blessed Wind", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert me.life == 7, "Forsaken Wastes: players can't gain life"
# end of the W1G5 sorceries block

# --- W1G6: tokens, zones and triggers ---
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from tests.helpers import _mk_card as _w1g6_mk_card, resolve_stack as _w1g6_resolve


def _w1g6_creature_card(name):
    return _w1g6_mk_card(name, "Creature — Beast")


def _w1g6_elephants(game, seat):
    return [p for p in game.controlled_by(seat) if p.card.name == "Elephant Token"]


def test_w1g6_elephant_resurgence_sizes_each_token_by_its_controllers_graveyard(set_pool):
    """"Each player creates a green Elephant creature token. Those creatures
    have "This token's power and toughness are each equal to the number of
    creature cards in its controller's graveyard."" Each token counts its own
    controller's pile, and keeps counting it."""
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P0", hand=[set_pool("PCY")["Elephant Resurgence"]],
            graveyard=[_w1g6_creature_card("Elk"), _w1g6_creature_card("Ox")],
        ),
        _W1G6PlayerState(
            name="P1",
            graveyard=[_w1g6_creature_card("Yak"), _w1g6_mk_card("Forest", "Basic Land — Forest")],
        ),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()

    assert game.cast_from_hand(0, "Elephant Resurgence").supported
    _w1g6_resolve(game)

    (mine,), (theirs,) = _w1g6_elephants(game, 0), _w1g6_elephants(game, 1)
    assert mine.metadata.get("is_token") and theirs.metadata.get("is_token")
    assert "G" in mine.effective_colors
    assert (mine.effective_power, mine.effective_toughness) == (2, 2)
    assert (theirs.effective_power, theirs.effective_toughness) == (1, 1)

    # A creature of P1's dies: P1's token grows, P0's does not.
    gnu = _W1G6Permanent(card=_w1g6_creature_card("Gnu"))
    game._put_permanent_onto_battlefield(1, gnu, None)
    game.sacrifice_permanent(gnu)
    game._refresh_dynamic_creatures()
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)
    assert mine.effective_power == 2


def _w1g6_denying_wind_table(set_pool):
    library = [_w1g6_mk_card(f"Card {n}", "Sorcery") for n in range(10)]
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[set_pool("PCY")["Denying Wind"]]),
        _W1G6PlayerState(name="P1", library=list(library)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Denying Wind", target_player_index=1).supported
    return game  # _w1g6_denying_wind_table


def test_w1g6_denying_wind_exiles_up_to_seven_from_the_targets_library(set_pool):
    """"Search target player's library for up to seven cards and exile them.
    Then that player shuffles." The caster searches the *target's* library and
    may stop short of seven: three picks are a legal answer."""
    game = _w1g6_denying_wind_table(set_pool)
    game.interactive_seats = {0}
    _w1g6_resolve(game)
    assert [c.kind for c in game.pending_choices] == ["search_library"]
    assert game.pending_choices[0].data.get("count") == 7
    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": i} for i in (0, 4, 9)]
    )
    _w1g6_resolve(game)
    assert sorted(c.name for c in game.players[1].exile) == ["Card 0", "Card 4", "Card 9"]
    assert len(game.players[1].library) == 7
    assert not game.players[0].exile and not game.players[0].library


def _w1g6_theft_table(set_pool):
    shock = set_pool("STH")["Shock"]
    bear = _w1g6_creature_card("Bear")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[set_pool("PCY")["Psychic Theft"]]),
        _W1G6PlayerState(name="P1", hand=[bear, shock]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Psychic Theft", target_player_index=1).supported
    _w1g6_resolve(game)
    game.auto_resolve_pending_choices()
    _w1g6_resolve(game)
    return game  # _w1g6_theft_table


def test_w1g6_psychic_theft_exiles_the_instant_and_lets_you_cast_it(set_pool):
    """"Target player reveals their hand. You choose an instant or sorcery card
    from it and exile that card. You may cast that card for as long as it
    remains exiled." The instant — not the creature — goes to its owner's
    exile, and the caster casts it from there."""
    game = _w1g6_theft_table(set_pool)
    assert [c.name for c in game.players[1].exile] == ["Shock"]
    assert [c.name for c in game.players[1].hand] == ["Bear"]
    grant = game.cast_permissions[0]
    assert (grant.player_index, grant.zone_seat, grant.mode) == (0, 1, "cast")

    result = game.cast_from_hand(0, "Shock", target_player_index=1, from_zone="exile")
    assert result.supported, result.details
    _w1g6_resolve(game)
    assert game.players[1].life == 18
    assert not game.players[1].exile
    assert not game.cast_permissions
    # Which graveyard the resolved Shock lands in is not asserted: every
    # leave-the-stack site approximates the owner with the caster's seat (see
    # handlers/stack.py's exile path), so it goes to P0's — CR 400.3 says P1's.
    # Reported at the round with Grinning Totem, the other card it reaches.

    game.resolve_end_step(0)
    game._settle()
    assert [c.name for c in game.players[1].hand] == ["Bear"]


def test_w1g6_psychic_theft_waits_for_an_interactive_pick(set_pool):
    """An interactive caster answers the pick; the permission and the delayed
    return are made only once it is answered, over the card it named."""
    pcy, sth = set_pool("PCY"), set_pool("STH")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="P0", hand=[pcy["Psychic Theft"]]),
        _W1G6PlayerState(name="P1", hand=[sth["Shock"], _w1g6_creature_card("Bear")]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Psychic Theft", target_player_index=1).supported
    game.resolve_top_of_stack()  # one step: the helper would answer the pick
    assert [c.kind for c in game.pending_choices] == ["revealed_hand_pick"]
    assert not game.cast_permissions
    assert not game.confirm_revealed_hand_pick(0, 1), "a creature is not an instant"
    assert game.confirm_revealed_hand_pick(0, 0)
    _w1g6_resolve(game)
    assert [c.name for c in game.players[1].exile] == ["Shock"]
    assert [c.name for c in game.cast_permissions[0].cards] == ["Shock"]
    assert [t.event for t in game.delayed_triggers] == ["next_end_step"]


def test_w1g6_psychic_theft_returns_the_uncast_card_at_the_end_step(set_pool):
    """"At the beginning of the next end step, if you haven't cast the card,
    return it to its owner's hand." Its owner's hand, not the caster's."""
    game = _w1g6_theft_table(set_pool)
    assert [c.name for c in game.players[1].exile] == ["Shock"]

    game.resolve_end_step(0)
    game._settle()
    assert not game.players[1].exile
    assert sorted(c.name for c in game.players[1].hand) == ["Bear", "Shock"]
    assert [c.name for c in game.players[0].hand] == []


def _w1g6_survivors(set_pool, graveyard):
    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P0", hand=[set_pool("PCY")["Search for Survivors"]],
            graveyard=list(graveyard),
        ),
        _W1G6PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Search for Survivors").supported
    _w1g6_resolve(game)
    return game  # _w1g6_survivors


def test_w1g6_search_for_survivors_returns_a_creature_card(set_pool):
    """"…An opponent chooses a card at random in your graveyard. If it's a
    creature card, put it onto the battlefield." A graveyard of one creature
    card leaves nothing to chance."""
    game = _w1g6_survivors(set_pool, [_w1g6_creature_card("Elk")])
    assert [p.card.name for p in game.controlled_by(0)] == ["Elk"]
    assert [c.name for c in game.players[0].graveyard] == ["Search for Survivors"]
    assert not game.players[0].exile


def test_w1g6_search_for_survivors_exiles_a_noncreature_card(set_pool):
    """"Otherwise, exile it." — and only the one card the pick named."""
    game = _w1g6_survivors(set_pool, [_w1g6_mk_card("Forest", "Basic Land — Forest")])
    assert not list(game.controlled_by(0))
    assert [c.name for c in game.players[0].exile] == ["Forest"]


def test_w1g6_search_for_survivors_takes_exactly_one_of_several(set_pool):
    import random

    random.seed(7)
    pile = [_w1g6_creature_card("Elk"), _w1g6_mk_card("Forest", "Basic Land — Forest"),
            _w1g6_creature_card("Ox"), _w1g6_mk_card("Swamp", "Basic Land — Swamp")]
    game = _w1g6_survivors(set_pool, pile)
    moved = [p.card.name for p in game.controlled_by(0)] + [c.name for c in game.players[0].exile]
    assert len(moved) == 1
    left = sorted(c.name for c in game.players[0].graveyard if c.name != "Search for Survivors")
    assert sorted(left + moved) == ["Elk", "Forest", "Ox", "Swamp"]
    if moved[0] in ("Elk", "Ox"):
        assert not game.players[0].exile
    else:
        assert not list(game.controlled_by(0))


def test_w1g6_denying_wind_default_takes_at_most_seven(set_pool):
    game = _w1g6_denying_wind_table(set_pool)
    _w1g6_resolve(game)
    exiled = len(game.players[1].exile)
    assert 0 <= exiled <= 7
    assert exiled + len(game.players[1].library) == 10

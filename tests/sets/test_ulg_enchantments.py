"""Urza's Legacy enchantments.

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

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: upkeep triggers, intervening-ifs, and granted quoted abilities ---
#
# Four enchantments whose whole content is the beginning of an upkeep:
#
# * Rivalry           a back-referenced *seat* as a damage recipient ("them")
# * Brink of Madness  a printed zero in an intervening-if, plus a whole-hand
#                     discard aimed at a seat the announcement chose
# * Defense of the Heart  a plural back-reference in a search's placement clause
# * Aura Flux         a board-wide static granting a quoted *triggered* ability,
#                     with CR 109.5's "other" excluding its own source
#
# Every test drives a real upkeep step and reads the board afterwards, never the
# compiled instruction kinds: three of these four cards compiled to plausible
# instructions long before they did the right thing with them.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_instruction_spec
from tests.helpers import resolve_stack


def _g3_game(*seats: PlayerState) -> Game:
    """A game over *seats* with costs off and the layer pass already run.

    Named and shaped for this block alone (SET_PLAYBOOK.md's block convention:
    a helper whose last lines match another group's is spliceable by a
    mechanical union), which is why the refresh is the closing statement rather
    than the customary bare ``return game``.
    """
    game = Game(players=list(seats))
    game.enforce_mana_costs = False
    game.log.clear()
    game._refresh_dynamic_creatures()
    return game


def _g3_upkeep(game: Game, seat: int) -> None:
    """Run *seat*'s upkeep to a standstill — the step, the stack it pushed, and
    any decision the resolution left owed with the stack already empty."""
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    resolve_stack(game)
    game.auto_resolve_pending_choices()


# ---------------------------------------------------------------------------
# Rivalry — "…deals 2 damage to them"
# ---------------------------------------------------------------------------

def test_rivalry_damages_whichever_player_is_ahead_on_lands(set_pool):
    """"At the beginning of each player's upkeep, if that player controls more
    lands than each other player, this enchantment deals 2 damage to **them**."

    The accusative names the seat the trigger froze, so the enchantment's own
    controller takes it when *they* are ahead and the opponent takes it when
    the opponent is. Reading "them" as anything else would have made this a
    one-sided card.
    """
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(name="P1", battlefield=[
        Permanent(card=ulg["Rivalry"]),
        Permanent(card=lea["Forest"]),
        Permanent(card=lea["Forest"]),
        Permanent(card=lea["Forest"]),
    ])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=lea["Mountain"])])
    game = _g3_game(p1, p2)

    _g3_upkeep(game, 0)
    assert (p1.life, p2.life) == (18, 20)

    # The opponent's own upkeep: they are behind, so nothing fires.
    _g3_upkeep(game, 1)
    assert (p1.life, p2.life) == (18, 20)

    # ...and now the opponent is ahead, on the same enchantment.
    p2.battlefield.extend(Permanent(card=lea["Mountain"]) for _ in range(4))
    game._refresh_dynamic_creatures()
    _g3_upkeep(game, 1)
    assert (p1.life, p2.life) == (18, 18)


def test_rivalry_is_silent_on_a_tie(set_pool):
    """"More lands than **each other player**" is strict, so a mirrored board
    is the case this superlative and an ordinary "than you" comparison would
    answer differently."""
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(name="P1", battlefield=[
        Permanent(card=ulg["Rivalry"]),
        Permanent(card=lea["Forest"]),
        Permanent(card=lea["Forest"]),
    ])
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=lea["Mountain"]),
        Permanent(card=lea["Mountain"]),
    ])
    game = _g3_game(p1, p2)
    _g3_upkeep(game, 0)
    assert (p1.life, p2.life) == (20, 20)


# ---------------------------------------------------------------------------
# Brink of Madness — a printed zero in the intervening-if
# ---------------------------------------------------------------------------

def test_brink_of_madness_does_nothing_while_you_hold_a_card(set_pool):
    """"…**if you have no cards in hand**…" — CR 603.4's condition, and the
    printed zero ``parse_amount`` refuses as a quantity. One card in hand is
    the whole difference between this and the test below."""
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    brink = Permanent(card=ulg["Brink of Madness"])
    p1 = PlayerState(name="P1", battlefield=[brink], hand=[lea["Forest"]])
    p2 = PlayerState(name="P2", hand=[lea["Mountain"], lea["Black Lotus"]])
    game = _g3_game(p1, p2)

    _g3_upkeep(game, 0)

    assert [p.card.name for p in p1.battlefield] == ["Brink of Madness"]
    assert len(p2.hand) == 2


def test_brink_of_madness_empties_the_opponents_hand_and_sacrifices_itself(set_pool):
    """The whole sentence: the enchantment goes and the *targeted* opponent's
    hand goes with it.

    The discard is aimed at the seat the trigger announced (CR 603.3d), not at
    the ability's controller — whose hand is empty by the condition, so a
    handler falling back to the caster would look like a working card.
    """
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ulg["Brink of Madness"])])
    p2 = PlayerState(name="P2", hand=[lea["Mountain"], lea["Black Lotus"], lea["Forest"]])
    game = _g3_game(p1, p2)

    _g3_upkeep(game, 0)

    assert [p.card.name for p in p1.battlefield] == []
    assert p1.graveyard[-1].name == "Brink of Madness"
    assert p2.hand == []
    assert sorted(c.name for c in p2.graveyard) == [
        "Black Lotus", "Forest", "Mountain",
    ]


def test_brink_of_madness_names_one_opponent_and_never_its_controller(set_pool):
    """"Target **opponent**" (CR 115.4): the trigger announces a seat as it
    goes on the stack (CR 603.3d) and may not name its own controller.

    Three seats, because at two the narrowing is right by coincidence — there
    is only one other player, so a picker that ignored the word would still
    land on them. The card's own condition guarantees the controller's hand is
    empty, so a handler falling back to the caster empties nothing and looks
    exactly like a working card.
    """
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ulg["Brink of Madness"])])
    p2 = PlayerState(name="P2", hand=[lea["Forest"]])
    p3 = PlayerState(name="P3", hand=[lea["Mountain"], lea["Black Lotus"]])
    game = _g3_game(p1, p2, p3)

    spec = derive_instruction_spec([
        compile_card_oracle(ulg["Brink of Madness"]).triggered_abilities[0].instruction
    ])
    assert spec == {"kind": "player", "opponents_only": True}

    _g3_upkeep(game, 0)

    emptied = [seat.name for seat in (p2, p3) if not seat.hand]
    assert len(emptied) == 1, "exactly one opponent, not all of them"
    assert sum(len(seat.hand) for seat in (p2, p3)) == 2


# ---------------------------------------------------------------------------
# Defense of the Heart — "put those cards onto the battlefield"
# ---------------------------------------------------------------------------

def test_defense_of_the_heart_waits_until_an_opponent_has_three_creatures(set_pool):
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=ulg["Defense of the Heart"])],
        library=[lea["Craw Wurm"], lea["Hurloon Minotaur"], lea["Forest"]],
    )
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=lea["Grizzly Bears"]) for _ in range(2)
    ])
    game = _g3_game(p1, p2)

    _g3_upkeep(game, 0)

    assert [p.card.name for p in p1.battlefield] == ["Defense of the Heart"]
    assert len(p1.library) == 3


def test_defense_of_the_heart_fetches_two_creatures_onto_the_battlefield(set_pool):
    """"…search your library for up to two creature cards, **put those cards**
    onto the battlefield, then shuffle."

    The plural back-reference the placement clause reads — the same referent
    the reveal clause beside it already spelled two ways. Asserted on the
    *board*: the search arms a decision, and a test that stopped at the
    instruction would have watched an empty battlefield and called it a pass.
    """
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=ulg["Defense of the Heart"])],
        library=[
            lea["Craw Wurm"], lea["Forest"], lea["Hurloon Minotaur"],
            lea["Air Elemental"],
        ],
    )
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=lea["Grizzly Bears"]) for _ in range(3)
    ])
    game = _g3_game(p1, p2)

    _g3_upkeep(game, 0)

    assert p1.graveyard[-1].name == "Defense of the Heart"
    fetched = [p.card.name for p in p1.battlefield]
    # **Up to two**, from a library holding three creature cards: the printed
    # cap is a restriction, so it is asserted rather than assumed.
    assert len(fetched) == 2
    assert all(name != "Forest" for name in fetched)
    # One land and one creature stay behind, so the type filter held as well.
    assert sorted(c.name for c in p1.library) == sorted(
        ({"Craw Wurm", "Hurloon Minotaur", "Air Elemental"} - set(fetched))
        | {"Forest"}
    )


def test_defense_of_the_heart_finds_fewer_when_the_library_holds_fewer(set_pool):
    """CR 701.23b — a search finds as many as it can and no more. "Up to two"
    over a library with one creature card in it is one creature, not a refusal
    and not a repeat."""
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(
        name="P1",
        battlefield=[Permanent(card=ulg["Defense of the Heart"])],
        library=[lea["Forest"], lea["Craw Wurm"], lea["Mountain"]],
    )
    p2 = PlayerState(name="P2", battlefield=[
        Permanent(card=lea["Grizzly Bears"]) for _ in range(3)
    ])
    game = _g3_game(p1, p2)

    _g3_upkeep(game, 0)

    assert [p.card.name for p in p1.battlefield] == ["Craw Wurm"]
    assert sorted(c.name for c in p1.library) == ["Forest", "Mountain"]


# ---------------------------------------------------------------------------
# Aura Flux — a quoted *triggered* ability granted board-wide
# ---------------------------------------------------------------------------

def test_aura_flux_taxes_every_other_enchantment_and_not_itself(set_pool):
    """"**Other** enchantments have "At the beginning of your upkeep, sacrifice
    this enchantment unless you pay {2}."" — Energy Flux's sentence over a
    different noun, plus CR 109.5's exclusion of the source.

    "Other" is the first word of its kind in that table, and the board-wide
    static pass applies every other template to its own source deliberately
    (a Pirate token compelled to attack by the sentence it carries). So the
    exclusion is asserted rather than assumed.
    """
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    assert compile_card_oracle(ulg["Aura Flux"]).supported

    flux = Permanent(card=ulg["Aura Flux"])
    moon = Permanent(card=lea["Bad Moon"])
    ring = Permanent(card=lea["Sol Ring"])
    p1 = PlayerState(name="P1", battlefield=[flux, moon, ring])
    game = _g3_game(p1, PlayerState(name="P2"))

    triggers = game.get_upkeep_pay_triggers(0)
    # Not the Sol Ring (an artifact) and not Aura Flux itself.
    assert [t["card_name"] for t in triggers] == ["Bad Moon"]
    assert triggers[0]["cost"]["mana"]["generic"] == 2


def test_aura_flux_reaches_an_opponents_enchantment_on_their_own_upkeep(set_pool):
    """"…sacrifice this enchantment unless **you** pay {2}" — "you" inside the
    granted quote is the taxed permanent's controller, not the granting one,
    because the ability is appended to that permanent's effective card and
    compiled as though it printed it."""
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=ulg["Aura Flux"])])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=lea["Bad Moon"])])
    game = _g3_game(p1, p2)

    assert [t["card_name"] for t in game.get_upkeep_pay_triggers(1)] == ["Bad Moon"]

    _g3_upkeep(game, 1)
    assert [p.card.name for p in p2.battlefield] == []
    assert p2.graveyard[-1].name == "Bad Moon"
    # ...and the granting enchantment is still there, having paid nothing.
    assert [p.card.name for p in p1.battlefield] == ["Aura Flux"]


def test_aura_flux_grant_ends_when_it_leaves_the_battlefield(set_pool):
    """Nothing is materialised onto the taxed permanent, so the grant ends by
    the source no longer being in the board-wide list — there is no flag to
    clear (CR 611.3)."""
    ulg, lea = set_pool("ULG"), set_pool("LEA")
    flux = Permanent(card=ulg["Aura Flux"])
    p1 = PlayerState(name="P1", battlefield=[flux, Permanent(card=lea["Bad Moon"])])
    game = _g3_game(p1, PlayerState(name="P2"))
    assert len(game.get_upkeep_pay_triggers(0)) == 1

    game.remove_from_battlefield(flux)
    game._refresh_dynamic_creatures()

    assert game.get_upkeep_pay_triggers(0) == []


@pytest.mark.parametrize("card_name", [
    "Rivalry", "Brink of Madness", "Defense of the Heart", "Aura Flux",
])
def test_w1g3_cards_compile_supported(set_pool, card_name):
    program = compile_card_oracle(set_pool("ULG")[card_name])
    assert program.supported, program.unsupported_reason


# --- W1G2: the animated body — "becomes a N/N <type> creature with …" ---
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2_shipped_pool():
    """Every shipped card by name, for the spells an opponent casts at these.

    The Opal cycle's trigger is *somebody else's* spell, so a test of it needs a
    card `set_pool("ULG")` cannot give. Read through the manifest rather than a
    spelled-out filename, and memoized on the function so the whole block reads
    the JSON once.
    """
    cached = getattr(_g2_shipped_pool, "_g2_cache", None)
    if cached is None:
        cached = {}
        for path in manifest_set_paths():
            for card in load_cards(path):
                cached.setdefault(card.name, card)
        _g2_shipped_pool._g2_cache = cached
    return cached


def _g2_enchantment_board(set_pool, name):
    """*name* on Alice's battlefield in a two-seat game, Bob free to cast at it."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    permanent = Permanent(card=set_pool("ULG")[name])
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return game, permanent


def _g2_opponent_casts(game, name):
    game.players[1].hand.append(_g2_shipped_pool()[name])
    game.cast_from_hand(1, name)
    resolve_stack(game)
    return game


def test_opal_champion_animates_with_first_strike(set_pool):
    """"When an opponent casts a creature spell, if this permanent is an
    enchantment, it becomes a 3/3 Knight creature **with first strike**."

    The whole card, and the keyword is the half that was missing: the same
    sentence with "flying" compiled, because the creature body read its keyword
    list one *token* at a time against a registry whose entries are ability
    names. "first" is not one, so the loop stopped there with nothing consumed
    and the line refused — Opal Gargoyle worked and its own cycle-mate did not.
    """
    game, champion = _g2_enchantment_board(set_pool, "Opal Champion")
    assert champion.has_type("enchantment") and not champion.is_creature

    _g2_opponent_casts(game, "Grizzly Bears")

    assert champion.is_creature
    assert champion.has_type("knight")
    assert (champion.effective_power, champion.effective_toughness) == (3, 3)
    assert champion.has_keyword("first strike")


def test_opal_champion_replaces_its_types(set_pool):
    """CR 205.1a: the sentence prints none of the retention clauses, so the
    enchantment stops being an enchantment — which is what makes its own
    intervening "if this permanent is an enchantment" false the second time an
    opponent casts a creature spell."""
    game, champion = _g2_enchantment_board(set_pool, "Opal Champion")

    _g2_opponent_casts(game, "Grizzly Bears")
    assert not champion.has_type("enchantment")

    _g2_opponent_casts(game, "Hill Giant")
    assert (champion.effective_power, champion.effective_toughness) == (3, 3)


def test_opal_champion_ignores_a_noncreature_spell(set_pool):
    """The narrowing on its own. A card that woke to any spell would pass the
    test above, so the printed word "creature" is asserted separately."""
    game, champion = _g2_enchantment_board(set_pool, "Opal Champion")

    _g2_opponent_casts(game, "Lightning Bolt")

    assert not champion.is_creature
    assert champion.has_type("enchantment")


def test_opal_avenger_wakes_when_its_controller_is_low(set_pool):
    """"**When you have 10 or less life**, if this permanent is an enchantment,
    it becomes a 3/5 Soldier creature."

    CR 603.8's state trigger read off a life total — a condition with no fire
    site, since life falls to damage, a cost, a loss effect or an opponent's
    drain. It is therefore swept for beside the counter, characteristic and
    hand states, in `mixins/game_ending.py`, and the threshold is payload.
    """
    game, avenger = _g2_enchantment_board(set_pool, "Opal Avenger")

    game.check_state_based_actions()
    resolve_stack(game)
    assert not avenger.is_creature, "20 life is not 10 or less"

    game.players[0].life = 11
    game.check_state_based_actions()
    resolve_stack(game)
    assert not avenger.is_creature, "11 is one more than the printed threshold"

    game.players[0].life = 10
    game.check_state_based_actions()
    resolve_stack(game)

    assert avenger.is_creature
    assert avenger.has_type("soldier")
    assert not avenger.has_type("enchantment")
    assert (avenger.effective_power, avenger.effective_toughness) == (3, 5)


def test_opal_avenger_reads_its_own_controllers_life(set_pool):
    """"**You**" is the source's controller and not every seat, which is the
    whole difference from Veiled Crocodile's "a player". An Avenger that woke to
    an opponent's life total would animate at exactly the wrong moment."""
    game, avenger = _g2_enchantment_board(set_pool, "Opal Avenger")

    game.players[1].life = 3
    game.check_state_based_actions()
    resolve_stack(game)

    assert not avenger.is_creature


def test_opal_avengers_threshold_is_payload(set_pool):
    """The number is delimited by the trigger table and read by the shared
    number reader, so a card printing another one needs no code. Asserted on the
    compiled condition rather than by inventing a card: what would break is the
    payload, and the payload is what the sweep tests."""
    program = compile_card_oracle(set_pool("ULG")["Opal Avenger"])

    (trigger,) = program.triggered_abilities

    assert trigger.condition.kind == "life_at_most"
    assert trigger.condition.payload["life_count"] == 10


# --- W1G1: a quantity the sentence that spends it produced ---
#
# Two enchantments whose second sentence spends a number the first one made:
# what the ability's own discard cost threw away (Pyromancy) and how much life
# the trigger's own first sentence took (Subversion). Both are driven in a game,
# because an assertion about instruction kinds passes on a card that resolves
# to zero.

import random

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack as _g1e_resolve


def _g1e_seats(count=2, *, mine=(), hand=()):
    """*count* seats, mana enforcement off, seat 0 active and holding *mine*.

    ``_g1e_`` prefixed and ending on ``return game, game.players`` — SET_PLAYBOOK.md's
    note about a union splicing one helper's body onto another's signature.
    """
    seats = [PlayerState(name=f"G1E-{i}") for i in range(count)]
    seats[0].battlefield = [Permanent(card=c) for c in mine]
    seats[0].hand = list(hand)
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players


# Pyromancy — "{3}, Discard a card at random: This enchantment deals damage to
# any target equal to the mana value of the discarded card."


def test_g1_pyromancy_deals_the_discarded_cards_mana_value(set_pool):
    """CR 601.2h discards the card before the ability is on the stack, so by
    resolution it is one card among everything else in that graveyard — the
    number is the last-known information the payment recorded (CR 608.2h).

    Shivan Dragon's mana value is 6.
    """
    dragon = set_pool("LEA")["Shivan Dragon"]
    game, seats = _g1e_seats(mine=[set_pool("ULG")["Pyromancy"]], hand=[dragon])

    result = game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
    _g1e_resolve(game)

    assert result.supported, result.details
    assert [c.name for c in seats[0].graveyard] == ["Shivan Dragon"]
    assert seats[1].life == 14


def test_g1_pyromancy_scales_with_the_card_rather_than_a_printed_number(set_pool):
    """The control on the test above: an Ornithopter costs nothing, so the
    discard is real and the damage is none (CR 120.8)."""
    game, seats = _g1e_seats(
        mine=[set_pool("ULG")["Pyromancy"]], hand=[set_pool("ATQ")["Ornithopter"]],
    )

    game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
    _g1e_resolve(game)

    assert [c.name for c in seats[0].graveyard] == ["Ornithopter"]
    assert seats[1].life == 20


def test_g1_pyromancy_cannot_be_activated_with_an_empty_hand(set_pool):
    """CR 601.2h: a cost that cannot be paid is an activation that does not
    happen — not one that happens and deals nothing."""
    game, seats = _g1e_seats(mine=[set_pool("ULG")["Pyromancy"]])

    result = game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
    _g1e_resolve(game)

    assert not result.supported
    assert seats[1].life == 20


def test_g1_pyromancy_discards_at_random_and_burns_for_what_it_took(set_pool):
    """"Discard a card **at random**" — the card is not the payer's choice, and
    the damage follows whichever went. Several seeds, because one seed proves
    the pairing and not the randomness."""
    pool = set_pool("ULG")
    hand = [
        set_pool("LEA")["Shivan Dragon"],      # 6
        set_pool("ATQ")["Ornithopter"],        # 0
        set_pool("LEA")["Lightning Bolt"],     # 1
    ]
    pairs = set()
    for seed in range(30):
        random.seed(seed)
        game, seats = _g1e_seats(mine=[pool["Pyromancy"]], hand=list(hand))
        game.activate_permanent_ability(0, "Pyromancy", target_player_index=1)
        _g1e_resolve(game)
        pairs.add((seats[0].graveyard[0].name, 20 - seats[1].life))

    assert pairs == {("Shivan Dragon", 6), ("Ornithopter", 0), ("Lightning Bolt", 1)}


# Subversion — "At the beginning of your upkeep, each opponent loses 1 life. You
# gain life equal to the life lost this way."


def test_g1_subversion_gains_what_the_one_opponent_lost(set_pool):
    """The printed 1 is what each opponent loses; the gain reads what the step
    actually took."""
    game, seats = _g1e_seats(mine=[set_pool("ULG")["Subversion"]])

    game.resolve_upkeep(0)
    _g1e_resolve(game)
    game._settle()

    assert seats[1].life == 19
    assert seats[0].life == 21


def test_g1_subversion_gains_the_table_total_not_the_printed_one(set_pool):
    """The whole reason the number is a *record*: at four seats the loss runs
    three times and the gain is 3, which is a number the card never prints and
    no board read can supply — by then the life totals are the ones this step
    left behind."""
    game, seats = _g1e_seats(4, mine=[set_pool("ULG")["Subversion"]])

    game.resolve_upkeep(0)
    _g1e_resolve(game)
    game._settle()

    assert [p.life for p in seats] == [23, 19, 19, 19]


# --- W2G3: a redirect off the host, a countered-spell trigger, and a chosen-type anthem ---
#
# Three enchantments whose machinery all sat one word short of existing:
#
# * Treacherous Link    CR 614.9's static Aura redirect, in the direction
#                       ``damage_redirects`` refused -- off the enchanted
#                       permanent and onto a *player*
# * Multani's Presence  a trigger on CR 701.6a's cancel, which had no
#                       announcement anywhere because countering had three
#                       call sites and no seam
# * Engineered Plague   CR 613 layer 7c narrowed by a word the sentence never
#                       prints, recorded on the source as it entered
#
# Every test drives the real event -- a damage event, a counterspell resolving,
# a layer recompute -- and reads life totals, hands and effective P/T
# afterwards. Two of these three compiled to plausible-looking output before
# they did anything: Engineered Plague reported *supported* on the strength of
# its entry line alone while its only effect sentence went unread, and
# Multani's Presence is the shape `test_trigger_dispatchers.py` exists for.
from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.control import change_control
from engine.game_types import CardDefinition
from engine.models import Permanent
from tests.helpers import resolve_stack


def _w2g3_creature(name: str, subtype: str, power: int = 2, toughness: int = 2):
    """A vanilla creature with a printed creature type -- the whole of what a
    chosen-type anthem and a redirect Aura ask about."""
    type_line = f"Creature - {subtype}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={
            "name": name, "type_line": type_line,
            "power": str(power), "toughness": str(toughness),
        },
    )


def _w2g3_board(*seats: PlayerState) -> Game:
    """A costs-free game over *seats* with the layer pass already run.

    Shaped for this block alone (SET_PLAYBOOK.md's block convention: a helper
    whose closing lines match another group's is spliceable by a mechanical
    union), which is why the log clear is the last statement rather than the
    customary bare ``return game``.
    """
    game = Game(players=list(seats))
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    game.log.clear()
    return game


# ---------------------------------------------------------------------------
# Treacherous Link -- "All damage that would be dealt to enchanted creature is
# dealt to its controller instead."
# ---------------------------------------------------------------------------

def _w2g3_linked(set_pool, *, also=()):
    """A Bear an opponent controls wearing this block's Auras.

    The Aura is under seat 0 and the creature under seat 1 deliberately: "its
    controller" is the *creature's*, and a board where the two seats agree
    cannot tell the two readings apart.
    """
    bears = Permanent(card=_w2g3_creature("Linked Bear", "Bear"))
    auras = [Permanent(card=set_pool("ULG")["Treacherous Link"])]
    auras += [Permanent(card=card) for card in also]
    mine = PlayerState(name="A", battlefield=list(auras))
    theirs = PlayerState(name="B", battlefield=[bears])
    game = _w2g3_board(mine, theirs)
    for aura in auras:
        attach_aura(aura, bears)
    game._refresh_dynamic_creatures()
    game.log.clear()
    return game, mine, theirs, bears, auras[0]


def test_w2g3_treacherous_link_moves_the_damage_onto_the_creatures_controller(set_pool):
    """CR 614.9: the damage is *dealt*, to somebody else -- so nothing is marked
    on the creature and a whole life total moves.

    The direction ``damage_redirects.attached_static_redirects`` refused before
    this: Pariah's printing protects a player and hands the damage to a
    permanent, and this one is the mirror, which is a different scan rather than
    the same one with its ends swapped.
    """
    game, mine, theirs, bears, _ = _w2g3_linked(set_pool)

    game._mark_damage_on_permanent(bears, 3, source=None)

    assert bears.damage_marked == 0
    assert (mine.life, theirs.life) == (20, 17)


def test_w2g3_treacherous_link_reads_its_as_the_creatures_controller(set_pool):
    """The possessive takes the noun phrase the sentence has just named, and
    that is the whole card: a {1}{B} Aura you put on an *opponent's* creature so
    that damage aimed at it lands on them. Read as the Aura's controller it
    would be a card that damages you, which is what the split seats are there to
    catch -- asserted here as the negative, so the reading is checked rather
    than the arithmetic."""
    game, mine, theirs, bears, _ = _w2g3_linked(set_pool)

    game._mark_damage_on_permanent(bears, 5, source=None)

    assert mine.life == 20, "the Aura's controller must not take it"
    assert theirs.life == 15


def test_w2g3_treacherous_link_follows_a_control_change(set_pool):
    """"Its controller" is a live question (CR 613 layer 2), asked through
    ``controller_index_of`` at the damage event rather than frozen when the
    Aura attached -- so a creature that has changed hands routes its damage to
    whoever holds it now."""
    game, mine, theirs, bears, aura = _w2g3_linked(set_pool)

    change_control(bears, 0, source=aura)
    game._refresh_dynamic_creatures()
    game._mark_damage_on_permanent(bears, 2, source=None)

    assert (mine.life, theirs.life) == (18, 20)


def test_w2g3_treacherous_link_stops_the_moment_it_is_unattached(set_pool):
    """The Aura ceasing to be attached is the whole of the removal -- the record
    is derived on every damage event rather than armed, so there is no
    remembered delta to subtract and the very next point of damage is marked
    normally."""
    game, mine, theirs, bears, aura = _w2g3_linked(set_pool)

    detach_aura(aura, bears)
    game._refresh_dynamic_creatures()
    game._mark_damage_on_permanent(bears, 2, source=None)

    assert bears.damage_marked == 2
    assert (mine.life, theirs.life) == (20, 20)


def test_w2g3_pariah_and_treacherous_link_hand_off_once_each(set_pool):
    """CR 614.5: a replacement effect gets one opportunity at an event and the
    modified events resulting from it.

    Both directions of this family on one creature is the loop the re-used
    derived record exists to survive -- Pariah moves your damage onto the
    creature, this Aura moves the creature's onto its controller, and each
    hand-off re-runs the whole contention set. Each applies once and the damage
    lands on the creature's controller, which is where the rule says the chain
    stops. A fresh record per event would have recursed until the interpreter
    gave up.
    """
    game, mine, theirs, bears, _ = _w2g3_linked(
        set_pool, also=[set_pool("USG")["Pariah"]]
    )

    game._deal_damage_to_player(mine, 3)

    assert bears.damage_marked == 0
    assert (mine.life, theirs.life) == (20, 17)


# ---------------------------------------------------------------------------
# Multani's Presence -- "Whenever a spell you've cast is countered, draw a card."
# ---------------------------------------------------------------------------

def _w2g3_counter_table(set_pool, *, watcher_seat=0, counter="Counterspell"):
    """Seat 0 holds a Bolt to cast, seat 1 the counter, and *watcher_seat* the
    enchantment. The library is stocked so a draw is visible as a card arriving
    in a hand rather than as an empty-library loss."""
    lea = set_pool("LEA")
    seats = [
        PlayerState(name="A", hand=[lea["Lightning Bolt"]], library=[lea["Forest"]] * 3),
        PlayerState(name="B", hand=[lea[counter]], library=[lea["Island"]] * 3),
    ]
    seats[watcher_seat].battlefield.append(
        Permanent(card=set_pool("ULG")["Multani's Presence"])
    )
    game = _w2g3_board(*seats)
    game.active_player_index = 0
    return game, seats


def test_w2g3_multanis_presence_draws_when_your_own_spell_is_countered(set_pool):
    """The card, end to end. Nothing announced CR 701.6a before this: countering
    had three call sites spelling out their own ``stack.remove``, so the
    condition parsed on both front ends and fired nowhere."""
    game, (mine, theirs) = _w2g3_counter_table(set_pool)

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    resolve_stack(game)

    assert [c.name for c in mine.hand] == ["Forest"]
    assert len(mine.library) == 2


def test_w2g3_multanis_presence_is_silent_for_an_opponents_countered_spell(set_pool):
    """"A spell **you've** cast" is CR 109.5's "you" -- the enchantment's
    controller -- matched against the seat that cast the countered spell. The
    same board with the enchantment on the other side of the table is the whole
    difference, and an unscoped announcement would draw for both."""
    game, (mine, theirs) = _w2g3_counter_table(set_pool, watcher_seat=1)

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert game.cast_from_hand(1, "Counterspell", target_stack_index=0).supported
    resolve_stack(game)

    assert theirs.hand == []
    assert len(theirs.library) == 3


def test_w2g3_multanis_presence_is_silent_when_a_spell_merely_fizzles(set_pool):
    """CR 608.2b never says "counter": a spell whose every target has become
    illegal "doesn't resolve. It's removed from the stack and, if it's a spell,
    put into its owner's graveyard."

    This engine's log line for it still reads "was countered by the rules",
    which is the pre-M2010 wording -- so the one thing that could have made this
    card wrong is a seam that took the log at its word. The Bolt goes to the
    graveyard and no card is drawn.
    """
    lea = set_pool("LEA")
    bears = Permanent(card=_w2g3_creature("Doomed Bear", "Bear"))
    mine = PlayerState(
        name="A", hand=[lea["Lightning Bolt"]], library=[lea["Forest"]] * 3,
        battlefield=[Permanent(card=set_pool("ULG")["Multani's Presence"])],
    )
    theirs = PlayerState(name="B", battlefield=[bears])
    game = _w2g3_board(mine, theirs)
    game.active_player_index = 0

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1,
                         target_permanent_index=0)
    game.remove_from_battlefield(bears)
    resolve_stack(game)

    assert mine.hand == []
    assert len(mine.library) == 3
    assert [c.name for c in mine.graveyard] == ["Lightning Bolt"]


def test_w2g3_multanis_presence_draws_off_an_unpaid_power_sink(set_pool):
    """The second counter site: a spell countered for an unpaid cost is
    countered exactly as one countered by a Counterspell is (CR 701.6a makes no
    distinction), which is what routing both through one seam buys. The seat
    cannot pay, so the pending payment defaults to declining."""
    game, (mine, theirs) = _w2g3_counter_table(set_pool, counter="Power Sink")

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.queue_from_hand(1, "Power Sink", target_stack_index=0, x_value=3)
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [c.name for c in mine.graveyard] == ["Lightning Bolt"]
    assert [c.name for c in mine.hand] == ["Forest"]


# ---------------------------------------------------------------------------
# Engineered Plague -- "As this enchantment enters, choose a creature type." /
# "All creatures of the chosen type get -1/-1."
# ---------------------------------------------------------------------------

def _w2g3_plague_board(set_pool, creatures, *, interactive=False):
    """Engineered Plague in hand over an opponent's *creatures*, named and typed."""
    permanents = [
        Permanent(card=_w2g3_creature(name, subtype, power, toughness))
        for name, subtype, power, toughness in creatures
    ]
    mine = PlayerState(name="A", hand=[set_pool("ULG")["Engineered Plague"]])
    theirs = PlayerState(name="B", battlefield=permanents)
    game = Game(players=[mine, theirs])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0}
    game.start_turn(0)
    return game, mine, permanents


def test_w2g3_engineered_plague_shrinks_only_the_chosen_type(set_pool):
    """The set the anthem reaches is named by a word the sentence never prints:
    it is chosen as the permanent enters (CR 614.1c) and recorded on it, so
    layer 7c has to read it off the *source*. The Bear beside the Zombies is the
    control -- a narrowing the matcher could not test would shrink the whole
    board."""
    game, mine, (zombie, other_zombie, bear) = _w2g3_plague_board(
        set_pool,
        [("Zombie One", "Zombie", 2, 2), ("Zombie Two", "Zombie", 3, 3),
         ("Bear One", "Bear", 2, 2)],
    )

    assert game.cast_from_hand(0, "Engineered Plague").supported
    game._settle()

    assert mine.battlefield[-1].metadata["chosen_creature_type"] == "zombie"
    assert (zombie.effective_power, zombie.effective_toughness) == (1, 1)
    assert (other_zombie.effective_power, other_zombie.effective_toughness) == (2, 2)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


def test_w2g3_engineered_plague_follows_the_chosen_word_not_the_default(set_pool):
    """The default is stamped before the prompt so a headless seat never blocks;
    an interactive controller's answer overwrites it, and the layer pass reads
    the new word. Two types on the board is what makes the two answers
    different."""
    game, mine, (zombie, bear) = _w2g3_plague_board(
        set_pool, [("Zombie One", "Zombie", 2, 2), ("Bear One", "Bear", 2, 2)],
        interactive=True,
    )

    assert game.cast_from_hand(0, "Engineered Plague").supported
    game._settle()
    assert game.pending_enter_choice["needs_creature_type"]
    assert game.confirm_enter_choice(0, creature_type="Bear")
    game._settle()

    assert (bear.effective_power, bear.effective_toughness) == (1, 1)
    assert (zombie.effective_power, zombie.effective_toughness) == (2, 2)


def test_w2g3_engineered_plague_kills_a_one_toughness_creature_of_the_type(set_pool):
    """-1/-1 is a layer-7c contribution like any other, so a 1/1 of the chosen
    type dies to the state-based actions the moment they are checked. The
    printed sign is what makes this the pool's anthem whose *effect* is a
    death."""
    game, mine, (rat, other_rat, bear) = _w2g3_plague_board(
        set_pool,
        [("Rat One", "Rat", 1, 1), ("Rat Two", "Rat", 1, 1),
         ("Bear One", "Bear", 1, 1)],
    )

    assert game.cast_from_hand(0, "Engineered Plague").supported
    game._settle()
    assert mine.battlefield[-1].metadata["chosen_creature_type"] == "rat"
    game.check_state_based_actions()

    names = [p.card.name for p in game.players[1].battlefield]
    assert names == ["Bear One"]


def test_w2g3_engineered_plague_reaches_every_battlefield(set_pool):
    """"**All** creatures", not "creatures you control" -- the anthem carries no
    controller scope, so its own controller's creatures of the chosen type are
    shrunk too. Dropping that would be a strictly one-sided card."""
    game, mine, (zombie,) = _w2g3_plague_board(
        set_pool, [("Zombie One", "Zombie", 2, 2)],
    )
    ours = Permanent(card=_w2g3_creature("Zombie Three", "Zombie", 4, 4))
    mine.battlefield.append(ours)

    assert game.cast_from_hand(0, "Engineered Plague").supported
    game._settle()

    assert (ours.effective_power, ours.effective_toughness) == (3, 3)
    assert (zombie.effective_power, zombie.effective_toughness) == (1, 1)


def test_w2g3_engineered_plague_with_no_word_recorded_shrinks_nothing(set_pool):
    """A buff carrying the narrowing with nothing chosen yet reaches nothing,
    which is the safe direction and the one the field comment claims: a dropped
    narrowing would put -1/-1 on every creature on the battlefield. Reached by
    clearing the record rather than by never making the choice, because the
    entry replacement stamps a default precisely so that cannot happen."""
    game, mine, (zombie, bear) = _w2g3_plague_board(
        set_pool, [("Zombie One", "Zombie", 2, 2), ("Bear One", "Bear", 2, 2)],
    )
    assert game.cast_from_hand(0, "Engineered Plague").supported
    game._settle()

    # The board is deliberately mixed, so whichever word the default picked one
    # of these two was shrunk before this line and neither is after it.
    assert {
        (zombie.effective_power, zombie.effective_toughness),
        (bear.effective_power, bear.effective_toughness),
    } == {(1, 1), (2, 2)}

    mine.battlefield[-1].metadata["chosen_creature_type"] = ""
    game._settle()

    assert (zombie.effective_power, zombie.effective_toughness) == (2, 2)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

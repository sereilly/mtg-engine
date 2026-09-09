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

    assert trigger.condition.kind == "controller_life_at_most"
    assert trigger.condition.payload["life_count"] == 10

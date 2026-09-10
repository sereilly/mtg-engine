"""Urza's Destiny enchantments.

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

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: being enchanted, and enchantments that become creatures ---

from engine import Game, PlayerState
from engine.auras import attach_aura, aura_protection_colors
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _w1g3_uds_creature(name: str, power: int, toughness: int, colors=()):
    """A vanilla creature with a colour, which the protection Aura reads."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_uds_game(*battlefields, lives=None):
    """One game with each seat's battlefield handed over as a list of permanents."""
    game = Game(players=[
        PlayerState(name=f"P{index}", battlefield=list(permanents))
        for index, permanents in enumerate(battlefields)
    ])
    game.enforce_mana_costs = False
    for index, life in enumerate(lives or ()):
        game.players[index].life = life
    for player in game.players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game


# --- Mask of Law and Grace -------------------------------------------------
# "Enchanted creature has protection from black and from red." CR 702.16g makes
# that clause two protection abilities, and the Aura reader had been one colour
# wide with an unanchored tail — so it matched the line and returned black.


def test_mask_of_law_and_grace_grants_both_printed_colours(set_pool):
    host = Permanent(card=_w1g3_uds_creature("Host", 2, 2))
    mask = Permanent(card=set_pool("UDS")["Mask of Law and Grace"])
    game = _w1g3_uds_game([host, mask])
    attach_aura(mask, host)

    assert game._protection_qualities(host) == {("color", "B"), ("color", "R")}


def test_mask_of_law_and_grace_reads_both_colours_off_the_text(set_pool):
    """The reader the layer bridge asks, so a gate that admitted the line and a
    grant that dropped half of it cannot pass this together."""
    mask = set_pool("UDS")["Mask of Law and Grace"]

    assert aura_protection_colors(mask.oracle_text) == frozenset({"black", "red"})
    assert compile_card_oracle(mask).supported


def test_mask_of_law_and_grace_leaves_the_other_three_colours_alone(set_pool):
    host = Permanent(card=_w1g3_uds_creature("Host", 2, 2))
    mask = Permanent(card=set_pool("UDS")["Mask of Law and Grace"])
    game = _w1g3_uds_game([host, mask])
    attach_aura(mask, host)

    qualities = game._protection_qualities(host)

    assert ("color", "G") not in qualities
    assert ("color", "U") not in qualities
    assert ("color", "W") not in qualities


# --- Opalescence -----------------------------------------------------------
# "Each other non-Aura enchantment is a creature in addition to its other types
# and has base power and base toughness each equal to its mana value."
# Titania's Song's sentence one card type over: CR 613.1d's addition and
# CR 613.4b's base-P/T setting, both already read off a `GlobalStatic`.


def test_opalescence_animates_another_enchantment(set_pool, catalog_by_name):
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    other = Permanent(card=catalog_by_name["Nevinyrral's Disk"])  # not an enchantment
    crusade = Permanent(card=catalog_by_name["Crusade"])          # {W}{W}
    game = _w1g3_uds_game([opal, other, crusade])
    game._refresh_dynamic_creatures()

    assert crusade.is_creature
    assert crusade.has_type("enchantment")
    # Base 2/2 from its own mana value, +1/+1 because Crusade is a white
    # creature and its own anthem now reaches it.
    assert (crusade.effective_power, crusade.effective_toughness) == (3, 3)
    assert not other.is_creature


def test_opalescence_does_not_animate_itself(set_pool, catalog_by_name):
    """"Each **other**" is CR 109.5's exclusion, and the templates in this table
    are applied to their own source unless the card says otherwise."""
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    game = _w1g3_uds_game([opal, Permanent(card=catalog_by_name["Crusade"])])
    game._refresh_dynamic_creatures()

    assert not opal.is_creature


def test_opalescence_does_not_animate_an_aura(set_pool, catalog_by_name):
    """"non-Aura" is a narrowing on the noun. An animated Aura would stop being
    attached and be binned by CR 704.5m, which is the card printing the opposite
    of what it says."""
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    host = Permanent(card=_w1g3_uds_creature("Host", 2, 2))
    aura = Permanent(card=catalog_by_name["Holy Strength"])
    game = _w1g3_uds_game([opal, host, aura])
    attach_aura(aura, host)
    game._refresh_dynamic_creatures()

    assert not aura.is_creature
    assert (host.effective_power, host.effective_toughness) == (3, 4)


def test_opalescence_reaches_an_opponents_enchantment(set_pool, catalog_by_name):
    """The printed noun carries no seat, so CR 109.2's description is every
    battlefield — the same reading Darkest Hour's row takes."""
    opal = Permanent(card=set_pool("UDS")["Opalescence"])
    theirs = Permanent(card=catalog_by_name["Crusade"])
    game = _w1g3_uds_game([opal], [theirs])
    game._refresh_dynamic_creatures()

    assert theirs.is_creature


# --- Lurking Jackals -------------------------------------------------------
# "When an opponent has 10 or less life, if this permanent is an enchantment,
# it becomes a 3/2 Jackal creature." CR 603.8's state trigger over the *other*
# seat's life total, where Opal Avenger prints the same sentence about its own.


def test_lurking_jackals_sleeps_while_every_opponent_is_healthy(set_pool):
    jackals = Permanent(card=set_pool("UDS")["Lurking Jackals"])
    game = _w1g3_uds_game([jackals], [], lives=(20, 20))
    game.check_state_based_actions()
    resolve_stack(game)

    assert not jackals.is_creature


def test_lurking_jackals_wakes_when_an_opponent_falls_to_ten(set_pool):
    jackals = Permanent(card=set_pool("UDS")["Lurking Jackals"])
    game = _w1g3_uds_game([jackals], [], lives=(20, 10))
    game.check_state_based_actions()
    resolve_stack(game)

    assert jackals.is_creature
    assert (jackals.effective_power, jackals.effective_toughness) == (3, 2)
    assert jackals.has_type("jackal")


def test_lurking_jackals_ignores_its_own_controllers_life_total(set_pool):
    """"An opponent" is the printed seat. Read as "you" — which is the seat the
    row carried before Lurking Jackals arrived — this animates at exactly the
    wrong moment."""
    jackals = Permanent(card=set_pool("UDS")["Lurking Jackals"])
    game = _w1g3_uds_game([jackals], [], lives=(10, 20))
    game.check_state_based_actions()
    resolve_stack(game)

    assert not jackals.is_creature


def test_lurking_jackals_names_the_seat_on_its_condition(set_pool):
    program = compile_card_oracle(set_pool("UDS")["Lurking Jackals"])

    (trigger,) = program.triggered_abilities

    assert trigger.condition.kind == "life_at_most"
    assert trigger.condition.payload == {"life_seat": "an opponent", "life_count": 10}


# --- W1G4: eight new trigger conditions and what announces them ---
import pytest

from engine import Game
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _g4e_card(name: str, type_line: str = "Creature - Test",
              colors=(), produced=()) -> CardDefinition:
    """A fixture card. Colour and produced mana matter here — Compost narrows on
    the first and Sanctimony's Mountain has to actually tap for the second."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=colors, color_identity=colors, keywords=(), produced_mana=produced,
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    )


def _g4e_land(name: str, subtype: str, symbol: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0,
        type_line=f"Basic Land - {subtype}",
        oracle_text=f"({{T}}: Add {{{symbol}}}.)",
        colors=(), color_identity=(symbol,), keywords=(),
        produced_mana=(symbol,),
        raw={"name": name, "type_line": f"Basic Land - {subtype}"},
    )


def _g4e_duel(library: int = 9) -> Game:
    seats = [
        PlayerState(name=name,
                    library=[_g4e_card(f"{name}-lib{i}") for i in range(library)],
                    hand=[], battlefield=[])
        for name in ("A", "B")
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    return game


def _g4e_place(game: Game, seat: int, card: CardDefinition) -> Permanent:
    """Put *card* on *seat*'s battlefield, ready to be used this turn."""
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def _g4e_answer(game: Game, *, accept: bool = True) -> None:
    """Resolve the stack and answer every optional offer (CR 603.5)."""
    for _ in range(8):
        resolve_stack(game)
        owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
        if not owed:
            return
        for choice in owed:
            game.resolve_pending_choice(
                choice.kind, choice.player_index, accept=accept
            )


def _g4e_uds(set_pool, name: str) -> CardDefinition:
    return set_pool("UDS")[name]


@pytest.mark.parametrize("name", ["Compost", "Sanctimony", "Impatience"])
def test_w1g4_enchantments_compile_supported(set_pool, name):
    assert compile_card_oracle(_g4e_uds(set_pool, name)).supported


# -- Compost: one event, two printed narrowings -----------------------------

@pytest.mark.parametrize("seat,colors,fires", [
    (1, ("B",), True),    # a black card, an opponent's graveyard
    (1, ("W",), False),   # the wrong colour
    (1, (), False),       # colourless is not black
    (0, ("B",), False),   # the right colour, the controller's own graveyard
])
def test_compost_narrowings(set_pool, seat, colors, fires):
    """"a **black** card" and "**an opponent's** graveyard" are both data on one
    condition. Either one dropped is a strictly larger card, and a larger card
    reads to every census in the repo as an implemented one."""
    game = _g4e_duel()
    _g4e_place(game, 0, _g4e_uds(set_pool, "Compost"))
    before = len(game.players[0].hand)
    game.put_card_into_graveyard(
        game.players[seat], _g4e_card("G4 Victim", colors=colors)
    )
    _g4e_answer(game)
    assert (len(game.players[0].hand) - before == 1) is fires


def test_compost_is_optional(set_pool):
    """CR 603.5: the ability goes on the stack whatever its controller intends;
    the choice is made as it resolves."""
    game = _g4e_duel()
    _g4e_place(game, 0, _g4e_uds(set_pool, "Compost"))
    before = len(game.players[0].hand)
    game.put_card_into_graveyard(
        game.players[1], _g4e_card("G4 Victim", colors=("B",))
    )
    _g4e_answer(game, accept=False)
    assert len(game.players[0].hand) == before


# -- Sanctimony: a seat narrowing on a tap-for-mana trigger ------------------

@pytest.mark.parametrize("tapper,subtype,symbol,fires", [
    (1, "Mountain", "R", True),    # an opponent, the named land type
    (0, "Mountain", "R", False),   # the controller's own Mountain
    (1, "Forest", "G", False),     # an opponent, the wrong land type
])
def test_sanctimony_narrowings(set_pool, tapper, subtype, symbol, fires):
    """"Whenever **an opponent** taps a **Mountain** for mana."

    The seat is asked of whoever tapped against the *watching permanent's*
    controller (CR 109.5). Dropped, Sanctimony would gain its controller life
    for their own Mountains.
    """
    game = _g4e_duel()
    _g4e_place(game, 0, _g4e_uds(set_pool, "Sanctimony"))
    land = _g4e_place(game, tapper, _g4e_land(f"G4 {subtype}", subtype, symbol))
    before = game.players[0].life
    game.tap_land_for_mana(
        tapper, land.card.name, symbol, permanent_id=land.permanent_id
    )
    _g4e_answer(game)
    assert (game.players[0].life - before == 1) is fires


def test_sanctimony_is_optional(set_pool):
    game = _g4e_duel()
    _g4e_place(game, 0, _g4e_uds(set_pool, "Sanctimony"))
    land = _g4e_place(game, 1, _g4e_land("G4 Mountain", "Mountain", "R"))
    before = game.players[0].life
    game.tap_land_for_mana(1, "G4 Mountain", "R", permanent_id=land.permanent_id)
    _g4e_answer(game, accept=False)
    assert game.players[0].life == before


# -- Impatience: CR 603.4's intervening if ----------------------------------

@pytest.mark.parametrize("caster,damaged", [
    (None, True),   # nobody cast: the active player takes 2
    (0, False),     # the player whose end step it is cast: no damage
    (1, True),      # somebody else cast: the condition is about *that* player
])
def test_impatience_intervening_if(set_pool, caster, damaged):
    """"…**if that player didn't cast a spell this turn**" (CR 603.4).

    The seat the condition is about is the one the trigger's event named — the
    same seat the damage is dealt to. Read as the source's controller instead,
    the card would be right only on its own end step.
    """
    game = _g4e_duel()
    _g4e_place(game, 0, _g4e_uds(set_pool, "Impatience"))
    game.active_player_index = 0
    if caster is not None:
        game.players[caster].spells_cast_this_turn.append(_g4e_card("G4 Spell"))
    before = game.players[0].life
    game.enter_turn_phase("ending")
    resolve_stack(game)
    assert (before - game.players[0].life == 2) is damaged


def test_impatience_reads_the_record_and_not_the_board(set_pool):
    """The condition's own payload names the per-seat, per-turn cast record.

    Asserted on the compiled program rather than only through play, because the
    whole point is *which* record answers it: nothing on the battlefield can,
    since a resolved spell has left the stack and a permanent that entered from
    a cast looks exactly like a reanimated one.
    """
    program = compile_card_oracle(_g4e_uds(set_pool, "Impatience"))
    gate = program.triggered_abilities[0].instruction.payload["intervening_if"]
    assert gate == {
        "kind": "seat_cast_spell_this_turn",
        "who": "that_player",
        "negated": True,
    }


# --- W1G5: player-directed effects, and a cost reduction nothing implemented ---
from unittest.mock import patch

import pytest

from engine import Game, PlayerState
from engine.control import BASE_CONTROLLER
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g5_festival_game(pool, opponents: int = 1) -> tuple[Game, Permanent]:
    """A board with Goblin Festival out and *opponents* seats facing it.

    Libraries are stocked because the first untap step draws, and a seat that
    draws from an empty one loses before the ability is ever activated.
    """
    stock = [pool["Goblin Berserker"]] * 5
    seats = [PlayerState(name="P1", life=20, library=list(stock))]
    seats += [
        PlayerState(name=f"P{n + 2}", life=20, library=list(stock))
        for n in range(opponents)
    ]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    festival = Permanent(card=pool["Goblin Festival"])
    festival.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(festival)
    game._sync_control()
    game.start_turn(0)
    return game, game.players[0].battlefield[0]


def test_goblin_festival_keeps_itself_when_the_flip_is_won(set_pool):
    """"{2}: This enchantment deals 1 damage to any target. Flip a coin. If you
    lose the flip, choose one of your opponents. That player gains control of
    this enchantment."

    Every piece but one was already here — the flip, the "if you lose the flip"
    conditional (twenty cards print it) and the hand-over that reads a chosen
    seat (Rainbow Vale's "An opponent gains control of this land" compiles to
    the very same two instructions). What was missing was the *two-sentence*
    spelling of the pick, and the record's visibility across an ``if_then``.

    The won half is the one that would fail silently: a hand-over reading no
    record must give the enchantment to nobody, where falling back to the
    controller — or to whoever a resolution was carrying — is a card that
    changes hands on every activation.
    """
    pool = set_pool("UDS")
    program = compile_card_oracle(pool["Goblin Festival"])
    assert program.supported, program.reason

    game, festival = _g5_festival_game(pool)
    with patch("engine.handlers.control_flow.flip_coin", return_value=True):
        assert game.activate_permanent_ability(
            0, "Goblin Festival", target_player_index=1
        ).supported
        resolve_stack(game)

    assert game.players[1].life == 19, game.log
    assert game.controller_index_of(festival) == 0, game.log


def test_goblin_festival_hands_itself_over_when_the_flip_is_lost(set_pool):
    """The losing half: the damage still happens and the enchantment moves.

    Both in one game, because the sentence order is the whole card — a reading
    that folded the hand-over into the conditional's branch would be right here
    and would still have to be right about the won case above.
    """
    pool = set_pool("UDS")
    game, festival = _g5_festival_game(pool)
    with patch("engine.handlers.control_flow.flip_coin", return_value=False):
        assert game.activate_permanent_ability(
            0, "Goblin Festival", target_player_index=1
        ).supported
        resolve_stack(game)

    assert game.players[1].life == 19, game.log
    assert game.controller_index_of(festival) == 1, game.log
    # CR 613 layer 2 is a contribution, not a move of the card: the seat it
    # entered under is untouched, which is what an ended effect reverts to.
    assert festival.metadata[BASE_CONTROLLER] == 0


def test_goblin_festival_asks_which_opponent_at_three_seats(set_pool):
    """At two seats the pick has one answer; at three it is a prompt.

    Which is what makes the pick its own instruction rather than a word the
    hand-over resolves: a handler that has to stop and ask cannot also finish
    the sentence. The resolution suspends with the gift still owed, and the
    answer is what runs it — so the enchantment is still its controller's until
    an opponent is named.
    """
    pool = set_pool("UDS")
    game, festival = _g5_festival_game(pool, opponents=2)
    game.interactive_seats = {0}
    with patch("engine.handlers.control_flow.flip_coin", return_value=False):
        assert game.activate_permanent_ability(
            0, "Goblin Festival", target_player_index=1
        ).supported
        resolve_stack(game)

    assert [c.kind for c in game.pending_choices] == ["player_choice"]
    assert game.controller_index_of(festival) == 0, game.log

    assert game.confirm_player_choice(0, 2)
    assert game.controller_index_of(festival) == 2, game.log

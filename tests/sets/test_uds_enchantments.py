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
        # No drain — see the note on Urza's Incubator: the activation is held
        # while seat 0 owes the pick, and `resolve_stack` would answer it.

    assert [c.kind for c in game.pending_choices] == ["player_choice"]
    assert game.controller_index_of(festival) == 0, game.log

    assert game.confirm_player_choice(0, 2)
    assert game.controller_index_of(festival) == 2, game.log


# --- W2G5: Archery Training, an ability that names the Aura granting it ---
from engine import Game as _W2G5Game, PlayerState as _W2G5Player
from engine.auras import attach_aura as _w2g5_attach
from engine.granted_abilities import granter_phrase as _w2g5_granter_phrase
from engine.models import Permanent as _W2G5Perm
from engine.named_counters import add_counters as _w2g5_add_counters
from engine.named_counters import counters_on as _w2g5_counters_on
from engine.oracle import compile_card_oracle as _w2g5_compile
from engine.targeting import derive_activation_spec as _w2g5_activation_spec
from tests.helpers import _nosick as _w2g5_nosick
from tests.helpers import resolve_stack as _w2g5_resolve


def _w2g5_archery_board(set_pool, *, trainings=1, host="Grizzly Bears"):
    """A host wearing *trainings* Archery Trainings, facing an attacking Hill
    Giant and an idle Grizzly Bears, in the opponent's declare-attackers step."""
    lea, uds = set_pool("LEA"), set_pool("UDS")
    archer = _w2g5_nosick(_W2G5Perm(card=lea[host]))
    auras = [_W2G5Perm(card=uds["Archery Training"]) for _ in range(trainings)]
    giant = _w2g5_nosick(_W2G5Perm(card=lea["Hill Giant"]))
    idle = _w2g5_nosick(_W2G5Perm(card=lea["Grizzly Bears"]))
    forests = [lea["Forest"]] * 20
    game = _W2G5Game(players=[
        _W2G5Player(name="P1", battlefield=[archer, *auras], library=list(forests)),
        _W2G5Player(name="P2", battlefield=[giant, idle], library=list(forests)),
    ])
    game.enforce_mana_costs = False
    for aura in auras:
        _w2g5_attach(aura, archer)
    game._recompute_continuous_effects()
    game.start_turn(1)
    _w2g5_resolve(game)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(1, [0])[0], game.log
    game.priority_player_index = 0
    return game, archer, auras, giant, idle


def test_w2g5_archery_training_is_cast_and_gathers_arrows_each_upkeep(set_pool):
    """The Aura's own half, through the turn structure: cast onto a creature,
    one arrow counter at each of its controller's upkeeps (the "may" taken by a
    seat nobody is answering for), none at the opponent's."""
    lea, uds = set_pool("LEA"), set_pool("UDS")
    archer = _W2G5Perm(card=lea["Grizzly Bears"])
    forests = [lea["Forest"]] * 20
    game = _W2G5Game(players=[
        _W2G5Player(name="P1", battlefield=[archer], hand=[uds["Archery Training"]],
                    library=list(forests)),
        _W2G5Player(name="P2", library=list(forests)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)

    cast = game.cast_from_hand(
        0, "Archery Training", target_permanent_index=0, target_player_index=0
    )
    _w2g5_resolve(game)
    assert cast.supported, cast.details
    aura = next(p for p in game.all_permanents() if p.card.name == "Archery Training")
    assert aura.metadata.get("attached_to") is archer

    arrows = []
    for seat in (1, 0, 1, 0):
        game.start_turn(seat)
        _w2g5_resolve(game)
        # "you may": the offer outlives the trigger's place on the stack.
        game.auto_resolve_pending_choices()
        arrows.append(_w2g5_counters_on(aura, "arrow"))
    assert arrows == [0, 1, 1, 2], game.log[-12:]


def test_w2g5_archery_training_host_shoots_for_the_auras_arrows(set_pool):
    """'{T}: This creature deals X damage to target attacking or blocking
    creature, where X is the number of arrow counters on Archery Training.'

    The ability is the *creature's* — its cost taps the creature and the
    creature is the damage's source — and the count is the *Aura's*. Until this
    wave the creature's compiler met "Archery Training" as a proper noun it had
    never heard of and the creature gained nothing.
    """
    game, archer, (aura,), giant, idle = _w2g5_archery_board(set_pool)
    _w2g5_add_counters(aura, "arrow", 2)

    program = _w2g5_compile(archer.effective_card)
    assert program.supported and len(program.activated_abilities) == 1
    assert _w2g5_granter_phrase(aura.permanent_id) in archer.effective_card.oracle_text
    spec = _w2g5_activation_spec(program.activated_abilities[0])
    assert spec == {"kind": "creature", "any_states": ["attacking", "blocking"]}

    # The idle Bears is neither attacking nor blocking: refused, nothing paid.
    refused = game.activate_permanent_ability(
        0, "Grizzly Bears", ability_index=0, target_permanent_ids=[idle.permanent_id]
    )
    assert not refused.supported and not archer.tapped

    shot = game.activate_permanent_ability(
        0, "Grizzly Bears", ability_index=0, target_permanent_ids=[giant.permanent_id]
    )
    _w2g5_resolve(game)

    assert shot.supported, shot.details
    assert archer.tapped
    assert giant.damage_marked == 2
    assert "Grizzly Bears dealt 2 damage to Hill Giant" in game.log
    assert idle.damage_marked == 0


def test_w2g5_two_archery_trainings_each_count_their_own_arrows(set_pool):
    """CR 201.5a: a granted ability naming its granter names "only the specific
    object which is that first ability's source". Two Trainings on one creature
    are two abilities, and each reads the pile on the Aura that granted it —
    which is why the name is bound to an id rather than looked up by name."""
    game, archer, (first, second), giant, _idle = _w2g5_archery_board(
        set_pool, trainings=2
    )
    _w2g5_add_counters(first, "arrow", 1)
    _w2g5_add_counters(second, "arrow", 3)
    abilities = _w2g5_compile(archer.effective_card).activated_abilities
    assert len(abilities) == 2
    assert _w2g5_granter_phrase(first.permanent_id) in abilities[0].source_line
    assert _w2g5_granter_phrase(second.permanent_id) in abilities[1].source_line

    game.activate_permanent_ability(
        0, "Grizzly Bears", ability_index=0, target_permanent_ids=[giant.permanent_id]
    )
    _w2g5_resolve(game)
    assert giant.damage_marked == 1

    archer.tapped = False
    game.priority_player_index = 0
    game.activate_permanent_ability(
        0, "Grizzly Bears", ability_index=1, target_permanent_ids=[giant.permanent_id]
    )
    _w2g5_resolve(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(giant), "1 + 3 is lethal to a 3/3"


def test_w2g5_archery_training_leaves_the_host_its_own_abilities(set_pool):
    """The unread quote did more than grant nothing: appended to the host's
    rules text it made the whole creature unsupported, so a Prodigal Sorcerer
    wearing Archery Training lost its own "{T}: 1 damage to any target"."""
    game, tim, (aura,), giant, _idle = _w2g5_archery_board(
        set_pool, host="Prodigal Sorcerer"
    )
    assert len(_w2g5_compile(tim.effective_card).activated_abilities) == 2

    ping = game.activate_permanent_ability(
        0, "Prodigal Sorcerer", ability_index=0, target_player_index=1
    )
    _w2g5_resolve(game)
    assert ping.supported, ping.details
    assert game.players[1].life == 19


def test_w2g5_archery_training_takes_the_ability_with_it(set_pool):
    """Derived from the attachment on every read (CR 611.3b): when the Aura
    leaves, the creature has no ability left to activate — and the count an
    ability already activated would read is of an object that is gone, which
    is zero arrows rather than some other Archery Training's."""
    from engine.handlers._common import evaluate_count

    game, archer, (aura,), giant, _idle = _w2g5_archery_board(set_pool)
    _w2g5_add_counters(aura, "arrow", 3)
    ability = _w2g5_compile(archer.effective_card).activated_abilities[0]
    spec = ability.instruction.payload["x_from_count"]
    assert spec == {"granter_counters": "arrow", "granter_id": aura.permanent_id}
    assert evaluate_count(game, game.players[0], spec, source=archer) == 3

    game.remove_from_battlefield(aura)
    game.players[0].graveyard.append(aura.card)
    game._recompute_continuous_effects()

    assert evaluate_count(game, game.players[0], spec, source=archer) == 0
    assert _w2g5_compile(archer.effective_card).activated_abilities == ()
    refused = game.activate_permanent_ability(
        0, "Grizzly Bears", ability_index=0, target_permanent_ids=[giant.permanent_id]
    )
    assert not refused.supported
    assert giant.damage_marked == 0 and not archer.tapped

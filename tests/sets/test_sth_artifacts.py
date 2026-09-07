"""Stronghold artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("STH")` / `set_cards("STH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""



# --- W1G2: combat restrictions and requirements ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2a_creature(name, power, toughness):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g2a_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g2a_game(mine, theirs, hand=()) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine), hand=list(hand)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_bullwhip_damages_a_creature_and_then_compels_it(set_pool):
    """"{2}, {T}: This artifact deals 1 damage to target creature. That
    creature attacks this turn if able."

    Both sentences of one ability, and the second names no target of its own:
    CR 601.2c fixed one creature when the ability was activated, so "that
    creature" is the object the damage step in front of it hit. A requirement
    that asked for a second target would make the picker ask twice; one that
    dropped the pronoun would compel nobody.
    """
    bullwhip = set_pool("STH")["Bullwhip"]
    program = compile_card_oracle(bullwhip)
    assert program.supported, program.reason
    steps = program.instructions[0].payload["steps"]
    assert [i.kind for i in steps] == [
        "deal_damage", "force_bound_to_attack_until_eot",
    ]

    whip = _g2a_nosick(Permanent(card=bullwhip))
    victim = _g2a_nosick(Permanent(card=_g2a_creature("Raider", 2, 3)))
    bystander = _g2a_nosick(Permanent(card=_g2a_creature("Rider", 2, 3)))
    game = _g2a_game([whip], [victim, bystander])

    result = game.activate_permanent_ability(
        0, "Bullwhip", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    resolve_stack(game)

    assert victim.damage_marked == 1
    assert victim.metadata.get("must_attack_until_eot")
    assert not bystander.metadata.get("must_attack_until_eot"), (
        "the pronoun names the creature the damage step hit, not the board"
    )


def test_ensnaring_bridge_reads_the_hand_at_every_declaration(set_pool):
    """"Creatures with power greater than the number of cards in your hand
    can't attack."

    The bound is the size of a hidden zone and "your" is the Bridge's
    controller (CR 109.5), so the same board answers differently as its
    controller's hand empties and fills. Strictly greater: a creature exactly at
    the count still attacks.
    """
    bridge = Permanent(card=set_pool("STH")["Ensnaring Bridge"])
    program = compile_card_oracle(bridge.card)
    assert program.supported, program.reason

    big = _g2a_nosick(Permanent(card=_g2a_creature("Ogre", 3, 3)))
    small = _g2a_nosick(Permanent(card=_g2a_creature("Scout", 1, 1)))
    filler = _g2a_creature("Spare", 1, 1)
    game = _g2a_game([big, small, bridge], [])

    game.players[0].hand[:] = [filler] * 3
    assert game.can_attack(big, 1), (
        "power 3 against a hand of 3 is not *greater* than it"
    )
    game.players[0].hand[:] = [filler] * 2
    assert not game.can_attack(big, 1), "3 is greater than 2"
    assert game.can_attack(small, 1), (
        "the same board, one power down: the restriction names a threshold, "
        "not a creature"
    )

    game.players[0].hand.clear()
    assert not game.can_attack(small, 1), (
        "an empty hand grounds every creature with power 1 or more"
    )


def test_ensnaring_bridge_counts_its_own_controller_s_hand(set_pool):
    """"Your" is the seat whose ability the sentence is, not the creature's.

    A restriction printed on one permanent that reaches every seat's creatures
    is the Moat shape; what this adds is that the *number* comes from the
    Bridge's controller. Reading the attacker's controller's hand instead would
    make the card asymmetrical in the direction nobody printed.
    """
    bridge = Permanent(card=set_pool("STH")["Ensnaring Bridge"])
    theirs = _g2a_nosick(Permanent(card=_g2a_creature("Ogre", 3, 3)))
    filler = _g2a_creature("Spare", 1, 1)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bridge]),
        PlayerState(name="P2", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    game._close_current_priority_step()
    game.players[0].hand.clear()
    game.players[1].hand[:] = [filler] * 5

    assert not game.can_attack(theirs, 0), (
        "the empty hand that matters is the Bridge controller's, and the "
        "attacker's own five cards do not lift the restriction"
    )


# --- W1G5: player-action triggers and replacements ---
#
# Three artifacts whose *event* is something a player does — a land drop, an
# entry a player may pay for, a creature arriving on somebody's board. Driven
# through a real game in every case: a trigger condition can sit in both front
# ends' tables and still have nothing that announces it, and a replacement can
# claim its line and decline at run time, and no instrument here sees either.

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_G5_LEA_ART = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g5_art_game(*players: PlayerState, costs: bool = False) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = costs
    return game


def test_horn_of_greed_draws_for_whichever_player_played_the_land(set_pool):
    """"Whenever **a player** plays a land, **that player** draws a card."

    The third value of an axis that had two. The event already existed for "you"
    and "an opponent" (Dirtcowl Wurm) — one announcement made at CR 305.1's
    special action, with the printed word as the narrowing — and the unnarrowed
    reading had no value at all, so the trigger never fired for anybody. The
    drawing seat is the one the land drop froze, because a land on a battlefield
    says nothing about who played it.
    """
    program = compile_card_oracle(set_pool("STH")["Horn of Greed"])
    assert program.supported, program.reason

    horn = Permanent(card=set_pool("STH")["Horn of Greed"])
    game = _g5_art_game(
        PlayerState(name="P1", battlefield=[horn], hand=[_G5_LEA_ART["Forest"]],
                    library=[_G5_LEA_ART["Mountain"]] * 8, life=20),
        PlayerState(name="P2", hand=[_G5_LEA_ART["Island"]],
                    library=[_G5_LEA_ART["Swamp"]] * 8, life=20),
        costs=True,
    )
    game.start_turn(0)
    game.resolve_stack()

    game.cast_from_hand(0, "Forest")
    game.resolve_stack()
    assert len(game.players[0].hand) == 1, game.log      # played one, drew one
    assert len(game.players[1].hand) == 1, game.log      # untouched

    game.start_next_turn()
    game.resolve_stack()
    before = len(game.players[1].hand)
    game.cast_from_hand(1, "Island")
    game.resolve_stack()
    # P2 played a land and P2 drew for it — the opponent's land drop feeds the
    # opponent, which is exactly what makes this the unnarrowed reading.
    assert len(game.players[1].hand) == before, game.log


def test_volraths_laboratory_makes_a_token_of_the_chosen_color_and_type(set_pool):
    """"As this artifact enters, choose a color and a creature type." /
    "{5}, {T}: Create a 2/2 creature token of **the chosen color and type**."

    Both halves are back-references to one CR 614.1c choice, so both are checked
    in one game: the prompt has to carry two answers, and the token has to read
    both records — its CR 111.4 name follows the subtype, so a dropped record
    would arrive as an unnamed colourless token.
    """
    program = compile_card_oracle(set_pool("STH")["Volrath's Laboratory"])
    assert program.supported, program.reason

    game = _g5_art_game(
        PlayerState(name="P1", hand=[set_pool("STH")["Volrath's Laboratory"]], life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Volrath's Laboratory")
    game.resolve_stack()

    lab = game.players[0].battlefield[0]
    assert game.confirm_enter_choice(0, mana_color="U", creature_type="merfolk"), game.log
    assert lab.metadata["chosen_color"] == "U"
    assert lab.metadata["chosen_creature_type"] == "merfolk"

    lab.metadata["summoning_sickness_turn"] = -99
    result = game.activate_permanent_ability(0, "Volrath's Laboratory")
    game.resolve_stack()
    assert result.supported, result

    token = game.players[0].battlefield[-1]
    assert token.card.name == "Merfolk Token", game.log
    assert token.has_type("merfolk"), game.log
    assert token.card.colors == ("U",), token.card.colors
    assert (token.effective_power, token.effective_toughness) == (2, 2)


def test_mox_diamond_enters_when_a_land_is_discarded_for_it(set_pool):
    """"If this artifact would enter, you may discard a land card instead. If
    you do, put this artifact onto the battlefield."

    The paying half of an optional CR 614.1a entry replacement.
    """
    program = compile_card_oracle(set_pool("STH")["Mox Diamond"])
    assert program.supported, program.reason

    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Forest"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    pending = game.pending_entry_discard_tolls
    assert pending, game.log
    assert game.confirm_entry_discard_toll(0, hand_index=pending[0]["hand_indices"][0])

    assert [p.card.name for p in game.players[0].battlefield] == ["Mox Diamond"], game.log
    assert [c.name for c in game.players[0].graveyard] == ["Forest"], game.log


def test_mox_diamond_declined_never_enters_the_battlefield(set_pool):
    """"If you don't, put it into its owner's graveyard."

    The declining half, and the reason the whole paragraph is one replacement:
    the artifact must never *be* on the battlefield. Letting it enter and
    binning it afterwards would put a permanent into a graveyard, which is a
    death (CR 700.4) — with an id, layer contributions and every
    enters-the-battlefield trigger in front of it.
    """
    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Forest"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.interactive_seats = {0}
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    assert game.confirm_entry_discard_toll(0, hand_index=None)
    assert not game.players[0].battlefield, game.log
    assert [c.name for c in game.players[0].graveyard] == ["Mox Diamond"], game.log
    assert [c.name for c in game.players[0].hand] == ["Forest"], game.log


def test_mox_diamond_with_no_land_in_hand_goes_to_the_graveyard(set_pool):
    """CR 101.3 with nothing to choose from: an offer whose only answer is the
    decline. The permanent still never enters."""
    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Black Lotus"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    assert not game.players[0].battlefield, game.log
    assert [c.name for c in game.players[0].graveyard] == ["Mox Diamond"], game.log
    assert [c.name for c in game.players[0].hand] == ["Black Lotus"], game.log


def test_mox_diamond_taps_for_mana_once_it_is_out(set_pool):
    """The second printed line, which is only reachable through the first: a
    replacement that consumed the entry and never put anything back would leave
    this untestable and the card reporting supported."""
    game = _g5_art_game(
        PlayerState(name="P1",
                    hand=[set_pool("STH")["Mox Diamond"], _G5_LEA_ART["Forest"]],
                    life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    game.cast_from_hand(0, "Mox Diamond")
    game.resolve_stack()

    mox = game.players[0].battlefield[0]
    mox.metadata["summoning_sickness_turn"] = -99
    result = game.activate_permanent_ability(0, "Mox Diamond", mana_color="U")
    game.resolve_stack()
    assert result.supported, result
    assert game.players[0].mana_pool["U"] == 1, game.log


def _g5_portcullis_board(set_pool, existing: int) -> tuple[Game, Permanent]:
    """A Portcullis and *existing* Bears already on the battlefield, each cast
    so that every one of them entered through the one entry path."""
    portcullis = Permanent(card=set_pool("STH")["Portcullis"])
    game = _g5_art_game(
        PlayerState(name="P1", battlefield=[portcullis],
                    hand=[_G5_LEA_ART["Grizzly Bears"]] * (existing + 1), life=20),
        PlayerState(name="P2", life=20),
    )
    game.start_turn(0)
    for _ in range(existing):
        game.cast_from_hand(0, "Grizzly Bears")
        game.resolve_stack()
    return game, portcullis


def test_portcullis_lets_the_first_two_creatures_through(set_pool):
    """"…if there are two or more **other** creatures on the battlefield."

    CR 603.4's intervening-if, and the word "other" is what makes the threshold
    three creatures rather than two: it excludes the creature that just entered,
    not the artifact, which is not a creature and could never be counted. Read
    as the source instead, the second Bears would have been exiled.
    """
    program = compile_card_oracle(set_pool("STH")["Portcullis"])
    assert program.supported, program.reason

    for already_out in (0, 1):
        game, _ = _g5_portcullis_board(set_pool, already_out)
        game.cast_from_hand(0, "Grizzly Bears")
        game.resolve_stack()
        assert not game.players[0].exile, (already_out, game.log)
        creatures = [p for p in game.players[0].battlefield if p.has_type("creature")]
        assert len(creatures) == already_out + 1, (already_out, game.log)


def test_portcullis_exiles_the_third_creature_and_gives_it_back(set_pool):
    """The threshold met, and the second printed sentence behind it: the exile
    is CR 610.3-linked to the artifact, so the creature comes back when the
    artifact leaves — under its owner's control, as a new object."""
    game, portcullis = _g5_portcullis_board(set_pool, 2)
    game.cast_from_hand(0, "Grizzly Bears")
    game.resolve_stack()

    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"], game.log
    creatures = [p for p in game.players[0].battlefield if p.has_type("creature")]
    assert len(creatures) == 2, game.log

    game.remove_all_from_battlefield([portcullis])
    game.resolve_stack()

    assert not game.players[0].exile, game.log
    creatures = [p for p in game.players[0].battlefield if p.has_type("creature")]
    assert len(creatures) == 3, game.log


# --- W1G4: library, graveyard and unusual costs ---

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.cost_modifiers import (cost_modifier_claims_line,
                                   cost_modifier_reduction_sentences,
                                   cost_modifiers_for)
from engine.models import Permanent

_G4_ATQ = {c.name: c for c in load_cards(manifest_set_path("ATQ"))}
_G4_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}
_G4_LEG = {c.name: c for c in load_cards(manifest_set_path("LEG"))}


def _g4_board() -> tuple[Game, PlayerState, PlayerState]:
    """Mana enforcement **on**: this block is about what a cost costs, so a
    game that charges nothing would pass every assertion below."""
    one, two = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[one, two])
    game.active_player_index = 0
    game.enforce_mana_costs = True
    return game, one, two


@pytest.mark.cr("601.2f", "118.7a")
def test_g4_heartstone_reads_the_reduction_and_its_floor_as_one_clause(set_pool):
    """"Activated abilities of creatures cost {1} less to activate. This effect
    can't reduce the mana in that cost to less than one mana."

    Both sentences or neither. The floor is what stops a {1} ability becoming
    free, so a reader claiming only the first sentence would leave the second
    unclaimed while quietly implementing a cheaper card — the same pairing
    ``engine/auras.py`` makes for Power Artifact's identical rider.
    """
    text = set_pool("STH")["Heartstone"].oracle_text

    modifiers = cost_modifiers_for(text)
    assert len(modifiers) == 1
    assert modifiers[0].reduces is True
    assert modifiers[0].applies_to == "activate"
    assert modifiers[0].amount == 1
    assert modifiers[0].card_types == ("creature",)
    assert modifiers[0].floor == 1
    assert cost_modifier_claims_line(text)
    assert len(cost_modifier_reduction_sentences(text)) == 2


@pytest.mark.cr("601.2f")
def test_g4_heartstone_takes_one_generic_off_a_creature_s_ability(set_pool):
    """Clay Statue regenerates for {2}, and for {1} beside a Heartstone."""
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=_G4_ATQ["Clay Statue"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))
    caster.mana_pool["C"] = 2

    result = game.activate_permanent_ability(0, "Clay Statue", ability_index=0)

    assert result.supported, result.details
    assert caster.mana_pool["C"] == 1, "one mana left over"


@pytest.mark.cr("601.2f")
def test_g4_heartstone_cannot_make_an_ability_free(set_pool):
    """The printed floor, enforced rather than dropped: Carrion Ants pumps for
    {1}, and beside a Heartstone it still pumps for {1}. The failure a dropped
    rider makes is not a crash — it is an ability that works more often than
    the card allows.
    """
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=_G4_LEG["Carrion Ants"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))

    refused = game.activate_permanent_ability(0, "Carrion Ants", ability_index=0)
    assert not refused.supported, "an empty pool cannot pay the floor"

    caster.mana_pool["C"] = 1
    paid = game.activate_permanent_ability(0, "Carrion Ants", ability_index=0)
    assert paid.supported, paid.details
    assert caster.mana_pool["C"] == 0, "the floor was charged in full"


@pytest.mark.cr("601.2f")
def test_g4_heartstone_reads_the_printed_noun_and_not_every_permanent(set_pool):
    """"Activated abilities of **creatures**": an artifact that is not a
    creature pays what it prints. Basalt Monolith untaps for {3} beside a
    Heartstone, which is the narrowing the modifier carries as payload."""
    game, caster, _ = _g4_board()
    caster.battlefield.append(Permanent(card=_G4_LEA["Basalt Monolith"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))
    caster.mana_pool["C"] = 2

    refused = game.activate_permanent_ability(
        0, "Basalt Monolith", ability_index=1,
    )
    assert not refused.supported, "{3} is not reduced to {2}"

    caster.mana_pool["C"] = 3
    assert game.activate_permanent_ability(
        0, "Basalt Monolith", ability_index=1,
    ).supported


@pytest.mark.cr("601.2f")
def test_g4_heartstone_is_symmetrical(set_pool):
    """The sentence names no controller, so it cheapens an opponent's creature
    too — the scan covers every battlefield, which is what a cost modifier
    without a printed seat means."""
    game, caster, victim = _g4_board()
    victim.battlefield.append(Permanent(card=_G4_ATQ["Clay Statue"]))
    caster.battlefield.append(Permanent(card=set_pool("STH")["Heartstone"]))
    victim.mana_pool["C"] = 1

    result = game.activate_permanent_ability(1, "Clay Statue", ability_index=0)

    assert result.supported, result.details
    assert victim.mana_pool["C"] == 0

"""Exodus enchantments.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: a shield with no recipient ---
#
# Penance — CR 615.8's one-instance chosen-source shield with the "to you" left
# off, rechecked by colour under CR 615.9. Imports are in this block, per the
# header's convention.

from engine import Game as _G5eGame
from engine.card_loader import load_catalog as _g5e_catalog
from engine.models import PlayerState as _G5ePlayer, Permanent as _G5ePermanent
from engine.oracle import compile_card_oracle as _g5e_compile
from engine.shields import PREVENT_FROM_COLOR as _G5E_COLOR, shields_on as _g5e_shields
from tests.helpers import resolve_stack as _g5e_drain

_G5E_POOL = {card.name: card for card in _g5e_catalog()}


def _g5e_penance_board(set_pool, bolts=2):
    """Penance and a Grizzly Bears on seat 0; *bolts* Lightning Bolts on seat 1."""
    caster = _G5ePlayer(
        name="A", hand=[_G5E_POOL["Plains"]], library=[_G5E_POOL["Plains"]] * 5
    )
    opponent = _G5ePlayer(name="B", hand=[_G5E_POOL["Lightning Bolt"]] * bolts)
    game = _G5eGame(players=[caster, opponent])
    game.enforce_mana_costs = False
    penance = _G5ePermanent(card=set_pool("EXO")["Penance"])
    penance.metadata["summoning_sickness_turn"] = -99
    caster.battlefield.append(penance)
    bear = _G5ePermanent(card=_G5E_POOL["Grizzly Bears"])
    caster.battlefield.append(bear)
    game._settle()
    return game, caster, opponent, bear


def test_penance_arms_a_colour_shield_that_watches_no_recipient(set_pool):
    """"Put a card from your hand on top of your library: The next time a black
    or red source of your choice would deal damage this turn, prevent that
    damage."

    CR 615.8 defines this shield by the **source** — the rule's own words have
    no recipient in them — and every Circle of Protection in the pool prints
    "to you", which is what made the recipient look like part of the shape.
    Penance is the printing without one, so the shield is armed with
    ``any_recipient`` and is reached from any damaged object.
    """
    program = _g5e_compile(set_pool("EXO")["Penance"])
    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.cost.hand_to_library_top == 1, "the cost is the card"
    payload = ability.instruction.payload
    assert payload["protection_kind"] == "color"
    assert payload["prevention_colors"] == ["B", "R"]
    assert payload["prevention_any_recipient"] is True

    game, caster, _opponent, _bear = _g5e_penance_board(set_pool)
    assert game.activate_permanent_ability(0, "Penance").supported, game.log

    assert caster.hand == [] and caster.library[0].name == "Plains"
    (shield,) = [s for s in _g5e_shields(caster) if s.kind == _G5E_COLOR]
    assert shield.any_recipient and shield.colors == ("B", "R")
    assert shield.uses == 1


def test_penance_prevents_one_red_instance_to_its_controller(set_pool):
    """CR 615.8: "the next instance", so the second Bolt is dealt normally."""
    game, caster, _opponent, _bear = _g5e_penance_board(set_pool)
    game.activate_permanent_ability(0, "Penance")

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    _g5e_drain(game)
    assert caster.life == 20

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    _g5e_drain(game)
    assert caster.life == 17, "one use, spent"


def test_penance_also_covers_a_creature(set_pool):
    """The half a Circle of Protection cannot do, and the reason the shield is
    reached through a table scan rather than off the seat it hangs on: with no
    recipient printed, the damaged **permanent** finds it too."""
    game, caster, _opponent, bear = _g5e_penance_board(set_pool)
    game.activate_permanent_ability(0, "Penance")

    game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0, target_permanent_index=1
    )
    _g5e_drain(game)
    game.check_state_based_actions()

    assert any(perm is bear for perm in caster.battlefield), game.log
    assert bear.damage_marked == 0


def test_penance_declines_a_source_of_the_wrong_colour(set_pool):
    """CR 615.9 rechecks the recorded property when the damage would be dealt,
    and a white source has neither of the two this shield recorded — so nothing
    is prevented **and the shield is not used up**."""
    game, caster, _opponent, _bear = _g5e_penance_board(set_pool)
    game.activate_permanent_ability(0, "Penance")
    (shield,) = [s for s in _g5e_shields(caster) if s.kind == _G5E_COLOR]

    game._deal_damage_to_player(caster, 3, source=_G5E_POOL["Serra Angel"])

    assert caster.life == 17, "Serra Angel is white"
    assert shield.uses == 1, "an unmatched source spends nothing (CR 615.9)"
# end of the W1G5 enchantments block


# --- W1G5 (continued): an ability either player may activate ---


def _g5e_dungeon_board(set_pool, *, active):
    """Volrath's Dungeon on seat 0, a card in each hand, *active* to move."""
    controller = _G5ePlayer(
        name="A", hand=[_G5E_POOL["Grizzly Bears"]],
        library=[_G5E_POOL["Plains"]] * 5,
    )
    opponent = _G5ePlayer(
        name="B", hand=[_G5E_POOL["Hill Giant"]],
        library=[_G5E_POOL["Mountain"]] * 5,
    )
    game = _G5eGame(players=[controller, opponent])
    game.enforce_mana_costs = False
    dungeon = _G5ePermanent(card=set_pool("EXO")["Volrath's Dungeon"])
    dungeon.metadata["summoning_sickness_turn"] = -99
    controller.battlefield.append(dungeon)
    game._settle()
    game.active_player_index = active
    return game, controller, opponent


def test_volraths_dungeon_lets_either_player_pay_five_life_on_their_own_turn(
    set_pool,
):
    """"Pay 5 life: Destroy this enchantment. Any player may activate this
    ability but only during their turn."

    Two tables, one sentence, split at the printed "but": CR 602.1a's
    permission is ``engine/activation_permissions.py`` and CR 602.5's window is
    ``engine/activation_restrictions.py``, which is the arrangement Armageddon
    Clock's identical shape already made.

    The pronoun is what the permission changes. "Only during **your** turn" is
    printed on an ability only its controller may activate; "their" is printed
    beside "any player may activate this ability" and names whoever is
    activating. Both rows share one predicate because
    ``activation_denial``'s seat argument is the **activator's** — so the two
    clauses were always one question, and only the printed word differed.
    """
    for activator in (0, 1):
        game, controller, opponent = _g5e_dungeon_board(set_pool, active=activator)
        result = game.activate_permanent_ability(
            activator, "Volrath's Dungeon", ability_index=0,
            source_controller_index=0,
        )
        _g5e_drain(game)

        assert result.supported, (activator, result.details)
        assert not any(
            perm.card.name == "Volrath's Dungeon"
            for perm in controller.battlefield
        )
        assert game.players[activator].life == 15, "the activator pays"
        assert game.players[1 - activator].life == 20


def test_volraths_dungeon_refuses_either_player_outside_their_own_turn(set_pool):
    """The half that makes the clause a restriction rather than a comment.

    An unenforced timing window is not a dead ability — it is an ability that
    works *more often than the card allows*, wrong in the player's favour and
    silent. Asserted for **both** seats, because the row is reached from either
    and a predicate keyed on the permanent's controller would have passed the
    controller's half and failed only the opponent's.
    """
    for activator in (0, 1):
        game, controller, _opponent = _g5e_dungeon_board(
            set_pool, active=1 - activator
        )
        result = game.activate_permanent_ability(
            activator, "Volrath's Dungeon", ability_index=0,
            source_controller_index=0,
        )

        assert not result.supported, activator
        assert "only during their turn" in result.details
        assert any(
            perm.card.name == "Volrath's Dungeon"
            for perm in controller.battlefield
        )
        assert [p.life for p in game.players] == [20, 20], (
            "CR 602.5c: an ability that can't be activated pays no cost"
        )


def test_volraths_dungeon_puts_a_targeted_players_card_back(set_pool):
    """"Discard a card: Target player puts a card from their hand on top of
    their library. Activate only as a sorcery."

    The counted third-person move, which is the production Tainted Specter's
    toll has always used and the lowering has honoured ``target_player`` for
    since it was written — what was missing was only the arm that dispatched
    "puts" to it. The seat that owns the hand chooses, so it arms a prompt.
    """
    game, controller, opponent = _g5e_dungeon_board(set_pool, active=0)
    game.start_turn(0)
    game._close_current_priority_step()

    result = game.activate_permanent_ability(
        0, "Volrath's Dungeon", ability_index=1, target_player_index=1,
    )
    _g5e_drain(game)
    game.auto_resolve_pending_choices()
    _g5e_drain(game)

    assert result.supported, result.details
    assert [c.name for c in controller.graveyard] == ["Grizzly Bears"], "the cost"
    assert opponent.hand == []
    assert opponent.library[0].name == "Hill Giant"
# end of the W1G5 Volrath block


# --- W1G1: the Oaths, and the seat a trigger's comparison is against ---
import pytest

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g1e_card(name, type_line="Creature — Bear"):
    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1",
             "toughness": "1"},
    )


def _g1e_plains(name="Plains"):
    return _g1e_card(name, "Basic Land — Plains")


def _g1e_table(set_pool, oath, *, seat0=(), seat1=(), lives=(20, 20),
               hands=((), ()), graveyards=((), ()), libraries=(None, None)):
    """*oath* under seat 0's control, at a two-seat table seat 1 is about to
    take a turn at — so the trigger fires for a player who is **not** the
    enchantment's controller, which is the whole question these cards ask."""
    enchantment = Permanent(card=set_pool("EXO")[oath])
    players = []
    for index, (own, life, hand, graveyard, library) in enumerate(
        zip((seat0, seat1), lives, hands, graveyards, libraries)
    ):
        battlefield = [Permanent(card=c) for c in own]
        if index == 0:
            battlefield.insert(0, enchantment)
        players.append(PlayerState(
            name="P%d" % index, life=life, battlefield=battlefield,
            hand=list(hand), graveyard=list(graveyard),
            library=list(library if library is not None
                         else [_g1e_card("Deck%d %d" % (index, i))
                               for i in range(6)]),
        ))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game._settle()
    return game, players[0], players[1]


def _g1e_take_upkeep(game, seat):
    """Start *seat*'s turn and drain everything the upkeep trigger arms."""
    game.start_turn(seat)
    for _ in range(6):
        game.auto_resolve_pending_choices()
        if not resolve_stack(game):
            break
    game.auto_resolve_pending_choices()
    return game


@pytest.mark.parametrize("oath", [
    "Oath of Druids", "Oath of Ghouls", "Oath of Lieges", "Oath of Mages",
    "Oath of Scholars",
])
def test_every_oath_is_supported(set_pool, oath):
    program = compile_card_oracle(set_pool("EXO")[oath])
    assert program.supported, program.reason


def test_oath_of_lieges_fetches_for_the_player_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, that player chooses target
    player who controls more lands than they do and is their opponent. The
    first player may search their library for a basic land card…"

    The payoff belongs to **the first player** — the seat whose upkeep it is —
    and not to the enchantment's controller. An offer made to one seat and
    carried out by another is the failure this card is the test for.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Lieges",
        seat0=(_g1e_plains("Theirs A"), _g1e_plains("Theirs B")),
        libraries=(None, [_g1e_plains("Fetched")]
                   + [_g1e_card("R%d" % i) for i in range(5)]),
    )

    _g1e_take_upkeep(game, 1)

    assert "Fetched" in [p.card.name for p in seat1.battlefield]
    assert "Fetched" not in [p.card.name for p in seat0.battlefield]


def test_oath_of_lieges_does_nothing_when_nobody_is_ahead(set_pool):
    """CR 603.3c: a triggered ability with no legal target is removed from the
    stack. Without the comparison in the picker every upkeep would fetch."""
    game, _seat0, seat1 = _g1e_table(set_pool, "Oath of Lieges")

    _g1e_take_upkeep(game, 1)

    assert [p.card.name for p in seat1.battlefield] == []
    assert any("no legal target" in line for line in game.log), game.log


def test_oath_of_scholars_empties_and_refills_the_upkeep_players_hand(set_pool):
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Scholars",
        hands=([_g1e_card("Mine %d" % i) for i in range(4)],
               [_g1e_card("Theirs")]),
    )

    _g1e_take_upkeep(game, 1)

    assert len(seat0.hand) == 4, "the enchantment's controller keeps their hand"
    assert [c.name for c in seat1.graveyard] == ["Theirs"]
    assert len(seat1.hand) == 3


def test_oath_of_mages_pings_the_second_player(set_pool):
    """"The first player may have this enchantment deal 1 damage to **the
    second player**." Wizards' own disambiguator: the first player chose, the
    second was chosen, and the damage goes to the one that was chosen.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Mages", lives=(25, 15),
    )

    _g1e_take_upkeep(game, 1)

    assert seat0.life == 24
    assert seat1.life == 15


def test_oath_of_ghouls_regrows_for_the_player_who_has_lost_more(set_pool):
    """"…chooses target player whose graveyard has fewer creature cards in it
    than their graveyard does". The comparison runs the *other* way from the
    rest of the cycle — the chooser must be **ahead** on dead creatures — so
    reading it as "more" would hand the regrowth to the wrong seat.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Ghouls",
        graveyards=([_g1e_card("Theirs A")],
                    [_g1e_card("Mine %d" % i) for i in range(3)]),
    )

    _g1e_take_upkeep(game, 1)

    assert len(seat1.hand) == 1
    assert len(seat1.graveyard) == 2
    assert seat0.hand == []


def test_oath_of_ghouls_is_silent_when_the_upkeep_player_is_behind(set_pool):
    game, _seat0, seat1 = _g1e_table(
        set_pool, "Oath of Ghouls",
        graveyards=([_g1e_card("Theirs %d" % i) for i in range(3)],
                    [_g1e_card("Mine")]),
    )

    _g1e_take_upkeep(game, 1)

    assert seat1.hand == []
    assert len(seat1.graveyard) == 1


def test_oath_of_druids_reanimates_off_the_upkeep_players_own_library(set_pool):
    """"The first player may reveal cards from the top of **their** library
    until **they** reveal a creature card. If the first player does, that
    player puts that card onto the battlefield and all other cards revealed
    this way into their graveyard."

    Every pronoun in that procedure is the upkeep player's, including the
    library the run reads and the graveyard the rest lands in.
    """
    game, seat0, seat1 = _g1e_table(
        set_pool, "Oath of Druids",
        seat0=(_g1e_card("Big A"), _g1e_card("Big B")),
        libraries=(None, [_g1e_plains("Skipped 1"), _g1e_plains("Skipped 2"),
                          _g1e_card("Reanimated")]
                   + [_g1e_card("R%d" % i) for i in range(3)]),
    )

    _g1e_take_upkeep(game, 1)

    assert [p.card.name for p in seat1.battlefield] == ["Reanimated"]
    assert [c.name for c in seat1.graveyard] == ["Skipped 1", "Skipped 2"]
    assert seat0.graveyard == []


def test_an_oath_fires_on_its_own_controllers_upkeep_too(set_pool):
    """"At the beginning of **each player's** upkeep" — the enchantment's
    controller is one of them, and is behind here."""
    game, seat0, _seat1 = _g1e_table(
        set_pool, "Oath of Lieges",
        seat1=(_g1e_plains("Theirs A"), _g1e_plains("Theirs B")),
        libraries=([_g1e_plains("Fetched")]
                   + [_g1e_card("L%d" % i) for i in range(5)], None),
    )

    _g1e_take_upkeep(game, 0)

    assert "Fetched" in [p.card.name for p in seat0.battlefield]


def test_the_oaths_ask_the_upkeep_player_which_opponent(set_pool):
    """"**That player** chooses target player…" — CR 601.2c's announcement,
    made by the seat the card names rather than by the ability's controller.
    Only visible with three seats and two legal answers: at two seats the
    comparison leaves one candidate and who picks cannot be observed.
    """
    enchantment = Permanent(card=set_pool("EXO")["Oath of Mages"])
    players = [
        PlayerState(name="P0", life=30, battlefield=[enchantment],
                    library=[_g1e_card("L%d" % i) for i in range(5)]),
        PlayerState(name="P1", life=10,
                    library=[_g1e_card("R%d" % i) for i in range(5)]),
        PlayerState(name="P2", life=30,
                    library=[_g1e_card("S%d" % i) for i in range(5)]),
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1, 2}
    game._settle()

    game.start_turn(1)

    prompts = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert len(prompts) == 1, [c.kind for c in game.pending_choices]
    assert prompts[0].player_index == 1, (
        "the upkeep player announces the target, not the Oath's controller"
    )
    assert sorted(
        target["seat"] for target in prompts[0].data["targets"]
    ) == [0, 2], "both opponents who are ahead on life are offered"


def test_a_printed_chooser_beside_target_opponent_refuses(set_pool):
    """Two seats in one phrase. "Target opponent" excludes whoever announces,
    and a printed chooser is the card saying that is somebody other than the
    ability's controller — so the word would be enforced against a seat the
    card does not name. Refused rather than resolved to either half.
    """
    line = compile_line(
        "that player chooses target opponent who has more life than they do. "
        "the first player may draw a card"
    )
    assert not line.instructions
    assert line.lowering_error or line.parse_error

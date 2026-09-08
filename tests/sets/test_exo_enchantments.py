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


# --- W1G2: triggers on what a player does ---
#
# Four enchantments whose trigger is somebody *else's* action. What they have in
# common is a seat the firing event names rather than the sentence: Spellshock's
# and Mana Breach's "that player" is whoever cast, and Predatory Hunger's
# trigger fires on an opponent's cast while its effect lands on a creature the
# Aura may not even share a controller with. So every test here checks the seat,
# not only that something happened — reading it off the ability's controller is
# right in a duel by accident half the time.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.auras import attach_aura
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

_G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g2_duel():
    """A two-seat game with costs off, seat 0 active. Its own helper and its own
    ending so a mechanical union cannot splice it onto another group's."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def _g2_put(game, seat: int, card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def test_w1g2_spellshock_burns_the_player_who_cast_the_spell(set_pool):
    """CR 603.10: "that player" is the seat the firing event froze. The
    enchantment is Alice's and the spell is Bob's, so a reading that took the
    ability's controller would burn the wrong player."""
    game, alice, bob = _g2_duel()
    _g2_put(game, 0, set_pool("EXO")["Spellshock"])
    bob.hand.append(_G2_LEA["Lightning Bolt"])

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    resolve_stack(game)

    assert bob.life == 18
    assert alice.life < 20  # Bob's Bolt still resolved at Alice


def test_w1g2_spellshock_burns_its_own_controller_too(set_pool):
    """"Whenever **a player** casts a spell" is unnarrowed (CR 603.2), so the
    enchantment's own controller pays as well — which is what separates this
    condition from the opponent-scoped one Ichneumon Druid prints."""
    game, alice, _bob = _g2_duel()
    _g2_put(game, 0, set_pool("EXO")["Spellshock"])
    alice.hand.append(_G2_LEA["Grizzly Bears"])

    assert game.cast_from_hand(0, "Grizzly Bears").supported
    resolve_stack(game)

    assert alice.life == 18


def test_w1g2_mana_breach_makes_the_caster_return_their_own_land(set_pool):
    """The land comes off the *caster's* battlefield, not the enchantment
    controller's: "a land **they** control" names the seat the cast froze."""
    game, alice, bob = _g2_duel()
    game.interactive_seats = set()
    _g2_put(game, 0, set_pool("EXO")["Mana Breach"])
    _g2_put(game, 0, _G2_LEA["Mountain"])
    _g2_put(game, 1, _G2_LEA["Forest"])
    bob.hand.append(_G2_LEA["Grizzly Bears"])

    assert game.cast_from_hand(1, "Grizzly Bears").supported
    resolve_stack(game)

    assert [c.name for c in bob.hand] == ["Forest"]
    assert [p.card.name for p in game.controlled_by(bob)] == ["Grizzly Bears"]
    assert [p.card.name for p in game.controlled_by(alice)] == [
        "Mana Breach", "Mountain",
    ]


def test_w1g2_predatory_hunger_counts_only_an_opponents_creature_spells(set_pool):
    """The Aura is Alice's and watches Bob. Her own creature spell must not
    grow the host — the printed narrowing is the whole card."""
    game, alice, bob = _g2_duel()
    hunger = set_pool("EXO")["Predatory Hunger"]
    bears = _g2_put(game, 0, _G2_LEA["Grizzly Bears"])
    aura = _g2_put(game, 0, hunger)
    attach_aura(aura, bears)

    alice.hand.append(_G2_LEA["Hill Giant"])
    assert game.cast_from_hand(0, "Hill Giant").supported
    resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

    bob.hand.append(_G2_LEA["Hill Giant"])
    assert game.cast_from_hand(1, "Hill Giant").supported
    resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)


def test_w1g2_manabond_empties_the_hand_onto_the_battlefield(set_pool):
    """"You may reveal your hand and put all land cards from it onto the
    battlefield. **If you do**, discard your hand." Taking the offer is what
    fires the rider (CR 601.2), so the nonland cards go however many lands
    there were."""
    game, alice, _bob = _g2_duel()
    game.interactive_seats = set()
    _g2_put(game, 0, set_pool("EXO")["Manabond"])
    alice.hand.extend([
        _G2_LEA["Forest"], _G2_LEA["Mountain"], _G2_LEA["Giant Growth"],
    ])

    game.resolve_end_step(0)
    game._settle()
    # The offer outlives the trigger's own resolution, so it is answered here
    # rather than by ``resolve_stack``, which by contract touches only a
    # decision that is *blocking* the stack.
    game.auto_resolve_pending_choices()
    game._settle()

    assert sorted(p.card.name for p in game.controlled_by(alice)) == [
        "Forest", "Manabond", "Mountain",
    ]
    assert alice.hand == []
    assert [c.name for c in alice.graveyard] == ["Giant Growth"]


def test_w1g2_manabond_reveals_the_hand_it_discards(set_pool):
    """CR 701.20a shows the hand to every player, which is the price of the
    offer — the lowering used to refuse "you reveal your hand" on the grounds
    that the revealer already sees it, which is true of nobody else at the
    table."""
    game, alice, _bob = _g2_duel()
    game.interactive_seats = set()
    _g2_put(game, 0, set_pool("EXO")["Manabond"])
    alice.hand.append(_G2_LEA["Giant Growth"])

    game.resolve_end_step(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert any("reveals their hand" in line for line in game.log)
    assert [c.name for c in alice.graveyard] == ["Giant Growth"]


def test_w1g2_pandemonium_landed_at_w2g2(set_pool):
    """W1G2's decline, kept as the record of what it cost to land.

    "Whenever a creature enters, that creature's controller may have it deal
    damage equal to its power to any target of their choice." Five pieces were
    named and **four** were real:

    1. a parse for "any target **of their choice**" — ``parse_target_spec``
       returned the moment it read "any target" and the rest was unconsumed;
    2. a **chooser** on a target. This one had **expired**: W1G1's Oath work
       built ``_choose_trigger_targets``' ``spec["chooser"]``, and what was
       missing was one word in it (``event_subject_controller``) and the carry
       of the key onto CR 115.4's ``any`` kind;
    3. a bite whose **biter** is the entering permanent;
    4. ``handlers/damage.source_bites_target`` reading that biter, which had
       exactly one value, ``"attached"``;
    5. that handler biting a **player**, which ``resolve_target_permanent``
       cannot.

    The behaviour is asserted below; this only pins the compiled shape, because
    every one of those five is a payload key and a program that lost one would
    still resolve.
    """
    program = compile_card_oracle(set_pool("EXO")["Pandemonium"])
    assert program.supported
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may"
    assert offer.payload["actor"] == "event_subject_controller"
    (bite,) = offer.payload["action"]
    assert bite.kind == "source_bites_target"
    assert bite.payload["biter"] == "event_subject"
    assert bite.payload["targets"] == {
        "quantifier": "any_target",
        "kind": "any",
        "chooser": "event_subject_controller",
    }


# --- W1G3: combat ---

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g3e_creature(name, power, toughness, subtype="Beast"):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=f"Creature - {subtype}",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": f"Creature - {subtype}",
             "power": str(power), "toughness": str(toughness)},
    )


def _g3e_plain_aura(name="Test Charm"):
    """An Aura with no effect of its own, so "that are enchanted" is the only
    thing under test - Maniacal Rage would supply a `cant_block` of its own and
    the block half would pass whether or not the relative clause was read."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Enchantment - Aura",
        oracle_text="Enchant creature", colors=(), color_identity=(),
        keywords=("Enchant",), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment - Aura"},
    )


def _g3e_ready(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g3e_table(mine, theirs) -> Game:
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    return game


def test_high_ground_lets_your_team_block_one_more_each(set_pool):
    """CR 509.1b's ceiling, granted board-wide.

    The sentence is appended to each affected creature's effective card, so the
    printed-grant counter in `_max_blocks_for` reads it exactly as it reads
    Two-Headed Giant of Foriys' own line - which is what makes the ceilings add
    rather than replace. "You control" is the half a dropped narrowing would
    lose, so the opponent's creature is asserted too.
    """
    ground = Permanent(card=set_pool("EXO")["High Ground"])
    program = compile_card_oracle(ground.card)
    assert program.supported, program.reason

    mine = _g3e_ready(Permanent(card=_g3e_creature("Guard", 1, 3)))
    theirs = _g3e_ready(Permanent(card=_g3e_creature("Foe", 1, 3)))
    game = _g3e_table([mine], [theirs])
    assert game._max_blocks_for(mine) == 1

    game.players[0].battlefield.append(ground)
    game._recompute_continuous_effects()
    assert game._max_blocks_for(mine) == 2
    assert game._max_blocks_for(theirs) == 1, (
        "'you control' is relative to the enchantment's controller (CR 109.5)"
    )

    game.remove_from_battlefield(ground)
    game._recompute_continuous_effects()
    assert game._max_blocks_for(mine) == 1, "nothing is materialised on the creature"


def test_song_of_serenity_grounds_only_the_enchanted_creatures(set_pool):
    """"Creatures **that are enchanted** can't attack or block."

    The narrowing is printed as a relative clause behind the head noun, so it is
    the noun phrase the restriction carries rather than the sentence's subject -
    and a dropped one is a board-wide ban on attacking, which is a different
    card. Both directions are asserted for that reason.
    """
    song = Permanent(card=set_pool("EXO")["Song of Serenity"])
    program = compile_card_oracle(song.card)
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == [
        "creatures_cant_attack", "creatures_cant_block",
    ]
    assert program.instructions[0].payload["subject"]["enchanted_only"] is True

    bare = _g3e_ready(Permanent(card=_g3e_creature("Free", 2, 2)))
    bound = _g3e_ready(Permanent(card=_g3e_creature("Bound", 2, 2)))
    aura = Permanent(card=_g3e_plain_aura())
    raider = _g3e_ready(Permanent(card=_g3e_creature("Raider", 1, 1)))
    game = _g3e_table([bare, bound, aura, song], [raider])
    attach_aura(aura, bound)
    game._recompute_continuous_effects()

    assert not game.can_attack(bound, 1)
    assert game.can_attack(bare, 1), (
        "the relative clause is the whole of what keeps an unenchanted "
        "creature attacking"
    )
    assert not game._can_block_attacker(bound, raider)
    assert game._can_block_attacker(bare, raider), (
        "both prohibitions are enforced at their own step, over the same phrase"
    )


def test_maniacal_rage_grants_both_halves_of_its_one_line(set_pool):
    """"Enchanted creature gets +2/+2 **and** can't block."

    One printed line carrying two effects in two channels. The Aura used to lose
    the whole line to the conjunction, so both halves are the assertion: the
    numbers through the P/T grant and the restriction through the blockers step.
    """
    aura = Permanent(card=set_pool("EXO")["Maniacal Rage"])
    program = compile_card_oracle(aura.card)
    assert program.supported, program.reason

    host = _g3e_ready(Permanent(card=_g3e_creature("Berserker", 2, 2)))
    raider = _g3e_ready(Permanent(card=_g3e_creature("Raider", 1, 1)))
    game = _g3e_table([raider], [host, aura])
    attach_aura(aura, host)
    game._recompute_continuous_effects()

    assert (host.effective_power, host.effective_toughness) == (4, 4)
    assert not game._can_block_attacker(host, raider)


def test_reconnaissance_pulls_an_attacker_out_of_combat_and_untaps_it(set_pool):
    """"{0}: Remove target attacking creature you control from combat and untap
    it."

    The removal is the step that chooses and the pronoun behind it reads what
    the removal recorded - the mirror of Disharmony, where the untap chooses and
    the removal reads. Both halves are asserted, because a pronoun resolved to
    the ability's own source (which is what a bare "it" means everywhere else)
    would untap the enchantment and leave the creature tapped.
    """
    recon = Permanent(card=set_pool("EXO")["Reconnaissance"])
    program = compile_card_oracle(recon.card)
    assert program.supported, program.reason

    scout = _g3e_ready(Permanent(card=_g3e_creature("Scout", 2, 2)))
    game = _g3e_table([scout, recon], [_g3e_ready(Permanent(card=_g3e_creature("Guard", 2, 2)))])
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    assert scout.attacking and scout.tapped

    result = game.activate_permanent_ability(
        0, "Reconnaissance", target_player_index=0, permanent_index=1,
        target_permanent_index=0,
    )
    assert result.supported, result.details
    resolve_stack(game)

    assert not scout.attacking
    assert not scout.tapped
    assert game.combat_attackers == {}
    assert not recon.tapped, "the enchantment is not what 'it' names"


# --- W1G4: an Aura whose upkeep trigger fires on somebody else's turn -------

import pytest

from engine import Game as _G4eGame, PlayerState as _G4ePlayer
from engine.auras import attach_aura as _g4e_attach
from engine.models import Permanent as _G4ePerm

from tests.helpers import resolve_stack as _g4e_resolve


def _g4e_perm(card):
    """A permanent already on the battlefield, past its summoning sickness."""
    permanent = _G4ePerm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _g4e_paroxysm_on_an_opponents_bear(set_pool, top_card: str):
    """Paroxysm attached to P1's Grizzly Bears, P1's library topped by *top_card*."""
    exo, lea = set_pool("EXO"), set_pool("LEA")
    aura, bear = _g4e_perm(exo["Paroxysm"]), _g4e_perm(lea["Grizzly Bears"])
    p0 = _G4ePlayer(name="G4e-P0", battlefield=[aura], life=20,
                    library=[lea["Island"]] * 4)
    p1 = _G4ePlayer(name="G4e-P1", battlefield=[bear], life=20,
                    library=[lea[top_card]] + [lea["Mountain"]] * 4)
    game = _G4eGame(players=[p0, p1])
    game.enforce_mana_costs = False
    _g4e_attach(aura, bear)
    game._sync_control()
    game._refresh_dynamic_creatures()
    game.active_player_index = 1
    # The seat whose upkeep it is, and this block's own closing pair (W1G4).
    game.priority_player_index = 1
    return game, aura, bear, p0, p1


@pytest.mark.parametrize("top_card,survives", [("Forest", False), ("Grizzly Bears", True)])
def test_w1g4_paroxysm_reads_the_enchanted_players_library(set_pool, top_card, survives):
    """"At the beginning of the upkeep of enchanted creature's controller, that
    player reveals the top card of their library. If that card is a land card,
    destroy that creature. Otherwise, it gets +3/+3 until end of turn."

    Three readings that were already built and one word that was not. The
    trigger head, "destroy that creature" and "it gets +3/+3" all bind to the
    enchanted permanent already; what was missing was the *subject-verb*
    spelling of a reveal, and "that card is …" being read as the revealed
    record rather than as an exiled one.

    The library opened is the **enchanted creature's controller's**, not the
    Aura's — which is the half a compile-time check cannot see.
    """
    game, _aura, bear, _p0, p1 = _g4e_paroxysm_on_an_opponents_bear(set_pool, top_card)

    game.resolve_upkeep(1)
    game.auto_resolve_pending_choices()
    _g4e_resolve(game)
    game.check_state_based_actions()

    assert any(f"{p1.name} revealed" in line for line in game.log), game.log
    assert game.is_on_battlefield(bear) is survives
    if survives:
        assert (bear.effective_power, bear.effective_toughness) == (5, 5)


# --- W2G5: the seat a default answer is computed from ---
#
# The Oaths move CR 601.2c's announcement to a seat that is not the ability's
# controller, and the prompt already goes there. What did not move with it is
# the answer a **non-interactive** seat gives: it was computed from the Oath's
# controller, so who owns the enchantment decided which player a third party's
# default named. Invisible at two seats, where there is one opponent and every
# rule agrees; this block is three-handed for that reason.

import pytest as _g5e_pytest

from engine import Game as _G5eGame, PlayerState as _G5ePlayerState
from engine.models import CardDefinition as _G5eCard, Permanent as _G5ePermanent
from tests.helpers import resolve_stack as _g5e_resolve_stack


def _g5e_filler(name):
    return _G5eCard(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear", "power": "1",
             "toughness": "1"},
    )


def _g5e_three_handed(set_pool, oath, *, oath_seat, lives, interactive=()):
    """*oath* under *oath_seat*'s control at a three-seat table.

    Lives are the whole board state these tests need: every Oath in the pair
    below is Oath of Mages, whose comparison is a life total and whose payoff
    is one damage — so which seat the announcement named is readable straight
    off the score.
    """
    enchantment = _G5ePermanent(card=set_pool("EXO")[oath])
    players = []
    for seat, life in enumerate(lives):
        players.append(_G5ePlayerState(
            name="P%d" % seat, life=life,
            battlefield=[enchantment] if seat == oath_seat else [],
            library=[_g5e_filler("S%d-%d" % (seat, i)) for i in range(5)],
        ))
    game = _G5eGame(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    return game


def _g5e_run_upkeep(game, seat):
    """Take *seat*'s upkeep with every prompt answered by its default."""
    game.start_turn(seat)
    for _ in range(6):
        game.auto_resolve_pending_choices()
        if not _g5e_resolve_stack(game):
            break
    game.auto_resolve_pending_choices()
    return [player.life for player in game.players]


@_g5e_pytest.mark.parametrize("oath_seat", [0, 1])
def test_w2g5_the_default_target_does_not_depend_on_who_controls_the_oath(
    set_pool, oath_seat,
):
    """"**That player** chooses target player…" — so the seat that answers is
    the upkeep player, and the answer a non-interactive seat gives has to be
    computed from *that* seat.

    The two runs differ in one thing only: which of the two eligible opponents
    owns the enchantment. Neither owner is the chooser, both are legal targets
    in both runs, and the enumerated candidate list is identical — so a default
    that reads the Oath's controller makes the same board answer two different
    ways, and the player who gets hit is decided by whose card it is.
    """
    game = _g5e_three_handed(
        set_pool, "Oath of Mages", oath_seat=oath_seat, lives=(30, 25, 10),
    )

    lives = _g5e_run_upkeep(game, 2)

    assert lives == [29, 25, 10], (
        "the upkeep player's first living opponent takes the damage whoever "
        "owns the Oath; got %r" % (lives,)
    )


def test_w2g5_the_default_answers_with_an_opponent_of_the_seat_that_was_asked(
    set_pool,
):
    """The policy stated in ``_default_trigger_target`` — "the first living
    opponent" — is a fact about the seat being *asked*, and this pins it to
    that seat rather than to the ability's controller.
    """
    game = _g5e_three_handed(
        set_pool, "Oath of Mages", oath_seat=0, lives=(30, 25, 10),
    )
    chooser = 2

    _g5e_run_upkeep(game, chooser)

    hit = [
        line for line in game.log if line.startswith("Oath of Mages: targets ")
    ]
    assert hit == ["Oath of Mages: targets P%d" % game._default_opposing_seat(chooser)], (
        game.log
    )


def test_w2g5_an_oath_is_countered_when_its_comparison_stops_holding(set_pool):
    """CR 608.2b over the Oaths' half of the clause, where the comparison is
    against "…than **they** do" — the upkeep player, frozen by the firing event
    (CR 603.10) rather than read off the ability's controller.

    The Oath's controller was ahead on life when the target was announced and is
    behind by the time the trigger would resolve, so its only target is illegal
    and the ability leaves the stack. The re-check resolves the reference seat
    through the same accessor the announcement used, which is the half a gate
    with its own reading would get wrong: measured against the *controller*
    instead, the comparison would still hold and the damage would land.
    """
    game = _g5e_three_handed(
        set_pool, "Oath of Mages", oath_seat=0, lives=(30, 25, 10),
        interactive=(0, 1, 2),
    )

    game.start_turn(2)
    game.auto_resolve_pending_choices()
    assert [item.target_player_index for item in game.stack] == [0], game.log

    game.players[0].life = 5
    _g5e_resolve_stack(game)

    assert [player.life for player in game.players] == [5, 25, 10]
    assert game.stack == []
    assert any("608.2b" in line for line in game.log), game.log


def test_w2g5_an_oath_still_resolves_while_its_comparison_holds(set_pool):
    """The paired direction. The lead shrinks and survives, so nothing is
    countered — a gate that fired on any change to the board would pass the
    test above and break every Oath in the cycle.
    """
    game = _g5e_three_handed(
        set_pool, "Oath of Mages", oath_seat=0, lives=(30, 25, 10),
        interactive=(0, 1, 2),
    )

    game.start_turn(2)
    game.auto_resolve_pending_choices()
    game.players[0].life = 11
    for _ in range(6):
        game.auto_resolve_pending_choices()
        if not _g5e_resolve_stack(game):
            break
    game.auto_resolve_pending_choices()

    assert [player.life for player in game.players] == [10, 25, 10], (
        "the chosen player — 'the second player' — takes the Oath's damage"
    )
    assert not any("608.2b" in line for line in game.log), game.log


# --- W2G1: Limited Resources — a keep on entry, and a ban with a board count ---

import pytest as _w2g1e_pytest  # noqa: E402
from engine import Game as _W2G1E_Game, PlayerState as _W2G1E_PlayerState  # noqa: E402
from engine.models import Permanent as _W2G1E_Permanent  # noqa: E402
from tests.helpers import resolve_stack as _w2g1e_drain  # noqa: E402


def _w2g1e_game(set_pool, mine, theirs, hand=(), interactive=()):
    """Both seats' boards spelled out by name, with the named EXO cards in seat
    0's hand. Names resolve out of EXO first and LEA second, so a test can put
    Limited Resources and a pile of Forests on the same board."""
    pool = set_pool("EXO")
    lea = set_pool("LEA")

    def _perms(names):
        return [_W2G1E_Permanent(card=(pool.get(n) or lea[n])) for n in names]

    game = _W2G1E_Game(players=[
        _W2G1E_PlayerState(
            name="P1", hand=[pool[n] for n in hand], battlefield=_perms(mine),
        ),
        _W2G1E_PlayerState(name="P2", battlefield=_perms(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w2g1e_lands(game, seat):
    return sum(1 for perm in game.controlled_by(seat) if perm.has_type("land"))


def test_limited_resources_entry_trigger_cuts_every_seat_to_five_lands(set_pool):
    """"When this enchantment enters, each player chooses five lands they
    control and sacrifices the rest."

    Every seat, and only down: a player already on three keeps all three, which
    is the half a difference-taking implementation gets wrong in the direction
    of doing something to a player the sentence leaves alone.
    """
    game = _w2g1e_game(
        set_pool, mine=["Forest"] * 8, theirs=["Island"] * 3,
        hand=["Limited Resources"],
    )

    assert game.cast_from_hand(0, "Limited Resources").supported
    _w2g1e_drain(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert (_w2g1e_lands(game, 0), _w2g1e_lands(game, 1)) == (5, 3), game.log


def test_limited_resources_takes_only_lands(set_pool):
    """The pool is the printed noun phrase: "five **lands** they control".

    The complement is the rest of that pool and not the rest of the board, so a
    seat's Moxen and bears are untouched however many lands it loses — which is
    the difference between this card and Cataclysm and is payload rather than a
    second kind.
    """
    game = _w2g1e_game(
        set_pool,
        mine=["Forest"] * 7 + ["Black Lotus", "Grizzly Bears"],
        theirs=[], hand=["Limited Resources"],
    )

    assert game.cast_from_hand(0, "Limited Resources").supported
    _w2g1e_drain(game)
    game.auto_resolve_pending_choices()
    game._settle()

    survivors = sorted(perm.card.name for perm in game.controlled_by(0))
    assert survivors == [
        "Black Lotus", "Forest", "Forest", "Forest", "Forest", "Forest",
        "Grizzly Bears", "Limited Resources",
    ], game.log


@_w2g1e_pytest.mark.parametrize("islands, banned", [(4, False), (5, True), (6, True)])
def test_limited_resources_bans_land_plays_only_at_ten_lands(set_pool, islands, banned):
    """"Players can't play lands as long as ten or more lands are on the
    battlefield."

    The count is over **every** battlefield, because the sentence says "on the
    battlefield" and names no seat — so the five lands seat 0 controls and the
    Islands seat 1 controls are one number. Nine is under the line and the game
    carries on; ten is the line and the word is "or more".
    """
    game = _w2g1e_game(
        set_pool, mine=["Forest"] * 5 + ["Limited Resources"],
        theirs=["Island"] * islands,
    )

    assert (game._land_play_refusal(0) is not None) is banned, game.log
    # And it reaches every seat, not just the enchantment's controller.
    assert (game._land_play_refusal(1) is not None) is banned


def test_limited_resources_ban_lifts_when_the_board_falls_back_under(set_pool):
    """The condition is read off the board at each ask rather than latched.

    A ban that stayed on once it had been on would be a strictly different card:
    "as long as" is a continuous condition (CR 613), so a land leaving the
    battlefield gives the permission back.
    """
    game = _w2g1e_game(
        set_pool, mine=["Forest"] * 5 + ["Limited Resources"],
        theirs=["Island"] * 5,
    )
    assert game._land_play_refusal(0) is not None

    doomed = next(iter(game.controlled_by(1)))
    game.remove_from_battlefield(doomed)

    assert game._land_play_refusal(0) is None


def test_a_land_ban_whose_condition_counts_a_noun_the_engine_cannot_test_is_refused():
    """A restriction is only done when something enforces it.

    "As long as three or more Zombies are on the battlefield" matches the same
    printed shape and names a *subtype*, which this table counts nothing by — so
    the claim and the enforcement both decline. Admitting it would ban land
    plays a card never banned: silent, and against the player.
    """
    from engine.land_play_allowance import land_play_line, land_play_prohibition

    unconditional = "Players can't play lands"
    conditional = (
        "Players can't play lands as long as ten or more lands are on the battlefield"
    )
    uncountable = (
        "Players can't play lands as long as three or more Zombies are on the battlefield"
    )

    assert land_play_line(unconditional) == "prohibition"
    assert land_play_line(conditional) == "prohibition"
    assert land_play_line(uncountable) is None
    assert land_play_prohibition(uncountable) is None
    assert land_play_prohibition(conditional).at_least == 10
    assert land_play_prohibition(conditional).card_type == "land"
# --- W2G2: a choice somebody else makes ---

import pytest

from engine import Game as _W2G2Game, PlayerState as _W2G2PlayerState
from engine.grammar import compile_line as _w2g2_compile_line
from engine.models import CardDefinition as _W2G2CardDefinition
from engine.models import Permanent as _W2G2Permanent
from tests.helpers import resolve_stack as _w2g2_resolve_stack


def _w2g2_creature(name, power, toughness):
    return _W2G2CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={}, power=str(power), toughness=str(toughness),
    )


def _w2g2_duel(set_pool, before=()):
    """A duel with Pandemonium on seat 0's battlefield and both seats asked.

    Both seats interactive, because the whole card is about *which* seat is
    asked: with neither of them owed a prompt the defaults answer, and a
    default that happens to pick the right seat proves nothing about the
    picker.

    *before* is put onto the battlefield **first**, as ``(seat, permanent)``
    pairs. Pandemonium watches every creature that enters, its controller's
    included, so a creature placed as scenery after it arms a second prompt and
    a test reading "the" pending choice reads whichever came first.
    """
    p1, p2 = _W2G2PlayerState(name="P1"), _W2G2PlayerState(name="P2")
    game = _W2G2Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    for seat, permanent in before:
        game._put_permanent_onto_battlefield(seat, permanent, None)
    game._put_permanent_onto_battlefield(
        0, _W2G2Permanent(card=set_pool("EXO")["Pandemonium"]), None
    )
    game.log.clear()
    return game, p1, p2


def _w2g2_enter(game, seat, permanent):
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _w2g2_take_every_offer(game, limit=20):
    """Resolve the stack, accepting every "may" offer on the way.

    ``resolve_stack`` answers a blocking prompt with the registry's *default*,
    and the default for a free offer is to decline ("take gifts, pay tolls,
    make no trades") — which on this card is a resolution that does nothing and
    an assertion passing for the wrong reason.
    """
    for _ in range(limit):
        offer = next(
            (c for c in game.pending_choices if c.kind == "optional_pay"), None
        )
        if offer is not None:
            game._resolve_optional_pay(offer, True, None)
            continue
        if not game.stack:
            return
        if game.resolve_top_of_stack():
            continue
        game.auto_resolve_pending_choices()
    raise AssertionError(f"the stack did not drain: {game.log}")


def test_w2g2_pandemonium_asks_the_entering_creatures_controller(set_pool):
    """CR 603.3d: the ability's controller announces its targets **unless the
    effect says otherwise**, and this one says otherwise.

    The trigger belongs to Pandemonium's controller whichever seat's creature
    entered, so a picker armed on the ability's controller is the failure this
    card exists to catch — silent, and always in that player's favour.
    """
    game, _p1, _p2 = _w2g2_duel(set_pool)
    _w2g2_enter(game, 1, _W2G2Permanent(card=_w2g2_creature("Bear", 3, 3)))

    (choice,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    assert choice.player_index == 1
    assert [t["name"] for t in choice.data["targets"] if t["kind"] == "player"] == [
        "P1", "P2",
    ]


def test_w2g2_pandemonium_bites_with_the_creature_not_the_enchantment(set_pool):
    """CR 120.7: the *creature* deals the damage, so the amount is its power.

    Pandemonium is a 0-power enchantment. Routed through the bite's default
    biter — the ability's own source — the card compiles, resolves, logs
    nothing wrong and deals **zero**, which is the runtime decline no census in
    this repo can see.
    """
    victim = _W2G2Permanent(card=_w2g2_creature("Wall", 0, 5))
    game, _p1, _p2 = _w2g2_duel(set_pool, before=[(0, victim)])
    entering = _w2g2_enter(
        game, 1, _W2G2Permanent(card=_w2g2_creature("Bear", 3, 3))
    )

    (choice,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    game._resolve_trigger_target(choice, permanent_id=victim.permanent_id)
    _w2g2_take_every_offer(game)

    assert victim.damage_marked == 3
    assert entering.damage_marked == 0
    assert any("Bear deals 3 damage to Wall" in line for line in game.log), game.log


def test_w2g2_pandemonium_can_aim_at_a_players_face(set_pool):
    """"Any target" is CR 115.4 — a creature, a player or a planeswalker.

    And the seat it lands on is the one the *chooser* named. The offer is made
    to the entering creature's controller, and ``may``'s rebind used to move
    ``context.target`` onto the seat it was offered to — so a player who aimed
    at their opponent shot themselves instead, in silence.
    """
    game, p1, p2 = _w2g2_duel(set_pool)
    _w2g2_enter(game, 1, _W2G2Permanent(card=_w2g2_creature("Bear", 3, 3)))

    (choice,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    game._resolve_trigger_target(choice, seat=0)
    _w2g2_take_every_offer(game)

    assert (p1.life, p2.life) == (17, 20)
    assert any("Bear deals 3 damage to P1" in line for line in game.log), game.log


def test_w2g2_pandemonium_offer_is_declinable(set_pool):
    """"**May**" — and a declined offer deals nothing rather than defaulting.

    Asserted because the two halves are answered by different seats through
    different prompts, and a decline that still dealt the damage would be the
    same wrongness as a target chosen by the wrong player.
    """
    game, p1, p2 = _w2g2_duel(set_pool)
    _w2g2_enter(game, 1, _W2G2Permanent(card=_w2g2_creature("Bear", 3, 3)))

    (choice,) = [c for c in game.pending_choices if c.kind == "trigger_target"]
    game._resolve_trigger_target(choice, seat=0)
    _w2g2_resolve_stack(game)
    offer = next(c for c in game.pending_choices if c.kind == "optional_pay")
    game._resolve_optional_pay(offer, False, None)

    assert (p1.life, p2.life) == (20, 20)


W2G2_NO_FROZEN_SEAT = (
    "'of their choice' names no player this target can be announced by"
)


@pytest.mark.parametrize(
    "line",
    [
        # No trigger at all: "their" names nobody, and the pick would fall to
        # the ability's controller — the one seat "of their choice" excludes.
        "This creature deals damage equal to its power to any target "
        "of their choice.",
        # A trigger whose fire site freezes no controller. Same refusal, and it
        # is the gate rather than the sentence: the words are identical.
        "Whenever you gain life, this creature deals damage equal to its "
        "power to any target of their choice.",
    ],
)
def test_w2g2_any_target_of_their_choice_refuses_without_a_frozen_seat(line):
    """The catch-all's refusal, written before the gate was trusted.

    "Of their choice" is parsed wherever "any target" is, so every card in the
    pool printing the phrase reaches this lowering — and the direction it must
    fail in is *refuse*, because a dropped chooser is not a card doing less. It
    is the ability's controller announcing a target the card hands to somebody
    else, with nothing red and nothing logged.
    """
    compiled = _w2g2_compile_line(line)
    assert compiled.parsed
    assert compiled.lowering_error == W2G2_NO_FROZEN_SEAT


def test_w2g2_any_target_without_the_phrase_still_announces_normally():
    """The positive control for the parse above: the two spellings differ by
    the chooser key alone, so a production that swallowed "of their choice"
    from a line that never printed it would show up here."""
    compiled = _w2g2_compile_line(
        "Whenever a creature enters, it deals damage equal to its power "
        "to any target."
    )
    assert compiled.usable
    (bite,) = compiled.instructions
    assert bite.payload["targets"] == {"quantifier": "any_target", "kind": "any"}
    assert bite.payload["biter"] == "event_subject"


# --- Phase 4: the printed subject of a damage sentence ---

from engine import Game as _P4Game, PlayerState as _P4PlayerState
from engine.auras import attach_aura as _p4_attach
from engine.models import CardDefinition as _P4CardDefinition
from engine.models import Permanent as _P4Permanent
from engine.oracle import compile_card_oracle as _p4_compile
from tests.helpers import resolve_stack as _p4_resolve


def _p4_creature(name, power, toughness, colors=()):
    return _P4CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(), raw={"power": str(power), "toughness": str(toughness)},
    )


def _p4_board(set_pool):
    """Dizzying Gaze attached to a host, with a flyer to shoot at."""
    host = _P4Permanent(card=_p4_creature("Host", 3, 3, colors=("G",)))
    flyer = _P4Permanent(card=_P4CardDefinition(
        name="Flyer", mana_cost="", cmc=0.0, type_line="Creature - Bird",
        oracle_text="Flying", colors=(), color_identity=(), keywords=("Flying",),
        produced_mana=(), raw={"power": "2", "toughness": "2"}))
    gaze = _P4Permanent(card=set_pool("EXO")["Dizzying Gaze"])
    game = _P4Game(players=[
        _P4PlayerState(name="P1", battlefield=[host, gaze]),
        _P4PlayerState(name="P2", battlefield=[flyer]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    _p4_attach(gaze, host)
    return game, host, flyer, gaze


def test_dizzying_gaze_damage_comes_from_the_enchanted_creature(set_pool):
    """"**Enchanted creature** deals 1 damage to target creature with flying."

    CR 120.7: the source of the damage is the object the card names, and here
    that is the host rather than the Aura. Found by
    ``scripts/parse_coverage.py``'s deletion probe at the promotion gate —
    deleting the word "enchanted" left the compiled program *identical*, which
    is the probe's whole signal that a rule matched while ignoring a word.

    The engine had the rule backwards in a way no other card could show: the
    Aura is red and the host green, so protection from red would have stopped
    damage the rules say comes from a green creature. Every other card in the
    pool printing this shape says "**this Aura** deals" or grants a quoted
    ability, and both of those already name the right source; Dizzying Gaze is
    the only one that prints the direct form.
    """
    game, host, flyer, gaze = _p4_board(set_pool)
    before = len(game.log)
    game.activate_permanent_ability(
        0, "Dizzying Gaze", target_player_index=1, target_permanent_index=0
    )
    _p4_resolve(game)
    assert flyer.damage_marked == 1
    dealt = [l for l in game.log[before:] if "dealt 1 damage" in l]
    assert dealt == ["Host dealt 1 damage to Flyer"], game.log[before:]


def test_dizzying_gaze_deals_nothing_once_it_has_fallen_off(set_pool):
    """An Aura with no host has nothing to deal the damage *with*, and must
    deal none rather than falling back to biting as itself — the rule
    ``source_bites_target``'s attached branch already states, now shared."""
    game, host, flyer, gaze = _p4_board(set_pool)
    game.remove_from_battlefield(host)
    before = len(game.log)
    game.activate_permanent_ability(
        0, "Dizzying Gaze", target_player_index=1, target_permanent_index=0
    )
    _p4_resolve(game)
    assert flyer.damage_marked == 0
    assert any("nothing to deal the damage" in l for l in game.log[before:])


def test_farrels_mantle_still_carries_its_own_attached_dealer(catalog_by_name):
    """The regression the differential caught, kept.

    The post-condition that gives Dizzying Gaze its dealer first *refused*
    Farrel's Mantle — a shipped card that was already correct — because its
    lowering is `source_bites_target` rather than `deal_damage`. The question
    the check asks is whether the dealer survives, not which family answered
    it, and one card going quietly unsupported is what the check was written
    to prevent.
    """
    program = _p4_compile(catalog_by_name["Farrel's Mantle"])
    assert program.supported
    (trigger,) = program.triggered_abilities
    (bite,) = trigger.instruction.payload["action"]
    assert bite.payload["biter"] == "attached"

"""Planeshift creatures.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: damage and the odd ones ---
#
# Mirrorwood Treefolk: "{2}{R}{W}: The next time damage would be dealt to this
# creature this turn, that damage is dealt to any target instead." A CR 614.9
# redirect — the damage is still dealt, by the same source and in full — armed
# by an activated ability with its taker chosen on activation. Zhalfirin
# Crusader's sentence with CR 615.8's one instance where that prints a point
# pool, so it is that card's instruction with ``uses`` in place of ``amount``.

from engine import Game as _w1g8c_Game, PlayerState as _w1g8c_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8c_load,  # noqa: E402
                                manifest_set_path as _w1g8c_path)
from engine.grammar import compile_line as _w1g8c_compile_line  # noqa: E402
from engine.models import (CardDefinition as _w1g8c_Card,  # noqa: E402
                           Permanent as _w1g8c_Permanent)
from engine.oracle import compile_card_oracle as _w1g8c_compile  # noqa: E402
from engine.targeting import (  # noqa: E402
    derive_activation_spec as _w1g8c_activation_spec,
)

from tests.helpers import (_damage_dealt as _w1g8c_dealt,  # noqa: E402
                           resolve_stack as _w1g8c_resolve_stack)


def _w1g8c_lea():
    return {card.name: card for card in _w1g8c_load(_w1g8c_path("LEA"))}


def _w1g8c_body(name, power, toughness, text="", keywords=(),
                type_line="Creature - Test", colors=()):
    """A bare creature for the other side of a fight."""
    return _w1g8c_Card(
        name=name, mana_cost="{3}", cmc=3.0, type_line=type_line,
        oracle_text=text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=tuple(keywords), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )  # W1G8 creatures: a test body


def _w1g8c_duel(mine, theirs, *, hand0=(), hand1=(), active=0, interactive=()):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_w1g8c_Permanent(card=card) for card in mine]
    board1 = [_w1g8c_Permanent(card=card) for card in theirs]
    filler = _w1g8c_body("Filler", 0, 1)
    game = _w1g8c_Game(players=[
        _w1g8c_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10),
        _w1g8c_Player(name="P1", battlefield=board1, hand=list(hand1),
                      library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G8 creatures: the duel


def _w1g8c_fight(game, attacker_slot, blocks=None, *, defender):
    """The active seat attacks with one creature; combat runs to main two."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(game.active_player_index, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocked = game.declare_blockers(defender, dict(blocks or {}))
    assert blocked[0], blocked
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g8c_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G8: fought


def _w1g8c_arm(game, **target):
    """Activate the Treefolk's ability at *target* and let it resolve."""
    used = game.activate_permanent_ability(
        0, "Mirrorwood Treefolk", ability_index=0, **target
    )
    assert used.supported, used.details
    _w1g8c_resolve_stack(game)  # W1G8 creatures: the redirect is armed


def test_w1g8_mirrorwood_treefolk_offers_any_target_and_one_use(set_pool):
    """The activation picker offers CR 115.4's "any target", and the payload
    carries the one instance — never a point pool."""
    program = _w1g8c_compile(set_pool("PLS")["Mirrorwood Treefolk"])

    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.instruction.kind == "redirect_next_damage_from_source_until_eot"
    assert ability.instruction.payload == {
        "targets": {"kind": "any", "quantifier": "any_target"}, "uses": 1,
    }
    assert ability.cost.mana == {
        "B": 0, "C": 0, "G": 0, "R": 1, "U": 0, "W": 1, "generic": 2,
    }
    assert _w1g8c_activation_spec(ability) == {"kind": "any"}


def test_w1g8_mirrorwood_treefolk_moves_the_next_burn_spell_to_a_player(set_pool):
    """The whole of the next event moves — three damage to the Treefolk is
    three to the chosen player — and then the effect is spent: the second
    Bolt lands where it was aimed."""
    lea = _w1g8c_lea()
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, _ = _w1g8c_duel(
        [treefolk_card], [], hand1=[lea["Lightning Bolt"]] * 2, active=1,
    )
    treefolk = mine[0]
    _w1g8c_arm(game, target_player_index=1)

    game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[treefolk.permanent_id]
    )
    _w1g8c_resolve_stack(game)
    assert treefolk.damage_marked == 0
    assert [player.life for player in game.players] == [20, 17]

    game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[treefolk.permanent_id]
    )
    _w1g8c_resolve_stack(game)
    assert treefolk.damage_marked == 3, '"the next time" is one instance'
    assert [player.life for player in game.players] == [20, 17]


def test_w1g8_mirrorwood_treefolk_moves_combat_damage_onto_a_creature(set_pool):
    """Combat damage is damage: blocking a 3/3 with the redirect aimed back at
    it, the attacker takes its own three and the Treefolk's two, and dies."""
    lea = _w1g8c_lea()
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, theirs = _w1g8c_duel(
        [treefolk_card], [lea["Hill Giant"]], active=1,
    )
    treefolk, giant = mine[0], theirs[0]
    _w1g8c_arm(game, target_permanent_ids=[giant.permanent_id])

    _w1g8c_fight(game, 0, {0: 0}, defender=0)

    assert treefolk.damage_marked == 0
    assert game.is_on_battlefield(treefolk)
    assert not game.is_on_battlefield(giant)


def test_w1g8_mirrorwood_redirect_is_still_dealt_by_its_source(set_pool):
    """CR 614.9 moves the damage; it does not prevent it and deal other damage.
    A lifelink attacker's redirected damage is still that attacker's, so its
    controller gains the life (CR 120.3f) while the Treefolk's controller,
    who took it instead, loses it."""
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    lifelinker = _w1g8c_body("Lifelinker", 2, 2, "Lifelink", ("Lifelink",))
    game, mine, _ = _w1g8c_duel([treefolk_card], [lifelinker], active=1)
    _w1g8c_arm(game, target_player_index=0)

    _w1g8c_fight(game, 0, {0: 0}, defender=0)

    assert mine[0].damage_marked == 0
    assert [player.life for player in game.players] == [18, 22]


def test_w1g8_mirrorwood_redirect_does_nothing_once_its_taker_is_gone(set_pool):
    """CR 614.9: if the new recipient is no longer there when the damage would
    be dealt, the effect does nothing — the damage lands on the Treefolk as
    though the ability had never been activated."""
    lea = _w1g8c_lea()
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, theirs = _w1g8c_duel(
        [treefolk_card], [lea["Grizzly Bears"]],
        hand1=[lea["Lightning Bolt"]], active=1,
    )
    treefolk, bears = mine[0], theirs[0]
    _w1g8c_arm(game, target_permanent_ids=[bears.permanent_id])
    game.remove_from_battlefield(bears)

    game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[treefolk.permanent_id]
    )
    _w1g8c_resolve_stack(game)

    assert treefolk.damage_marked == 3


def test_w1g8_mirrorwood_redirects_stack_and_end_with_the_turn(set_pool):
    """Two activations are two instances, each spent by one event; and an
    unspent one is gone at cleanup ("this turn")."""
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, _ = _w1g8c_duel([treefolk_card], [])
    treefolk = mine[0]
    _w1g8c_arm(game, target_player_index=1)
    _w1g8c_arm(game, target_player_index=1)

    # the helper runs the event's first half only and spends what applies
    assert _w1g8c_dealt(game, treefolk, 2) == 0
    assert _w1g8c_dealt(game, treefolk, 2) == 0
    assert _w1g8c_dealt(game, treefolk, 2) == 2

    _w1g8c_arm(game, target_player_index=1)
    game.resolve_cleanup_step(0)
    assert _w1g8c_dealt(game, treefolk, 2) == 2


def test_w1g8_an_unsourced_instance_redirect_reads_its_whole_sentence():
    """The lowering's refusals. A narrowed taker is carried and re-checked; a
    blanket over the ability's own source, a taker nobody chose and a missing
    duration are each a wider card and refuse."""
    narrowed = _w1g8c_compile_line(
        "{1}: The next time damage would be dealt to this creature this turn, "
        "that damage is dealt to target creature you control instead.",
        card_name="Probe",
    )
    (instruction,) = narrowed.instructions
    assert instruction.kind == "redirect_next_damage_from_source_until_eot"
    assert instruction.payload["uses"] == 1
    assert instruction.payload["targets"]["filter"]["controller"] == "you"

    for text in (
        # no chosen taker: "you" is not a target this instruction resolves
        "{1}: The next time damage would be dealt to this creature this turn, "
        "that damage is dealt to you instead.",
        # no duration: a record the cleanup sweep would end a turn early
        "{1}: The next time damage would be dealt to this creature, that "
        "damage is dealt to any target instead.",
    ):
        refused = _w1g8c_compile_line(text, card_name="Probe")
        assert refused.parse_error or refused.lowering_error, text
        assert not refused.instructions, text


# W1G8, supported on arrival and driven: Tahngarth, Nemata, Ertai and
# Flametongue Kavu compiled with every instrument quiet and had never been
# run. Each gets the game that would have shown it wrong.


def test_w1g8_tahngarth_is_bitten_back_by_the_creature_itself(set_pool):
    """"…deals damage equal to its power to target creature. **That creature**
    deals damage equal to its power to Tahngarth." The second damage's source
    is the creature (CR 120.7), so a lifelink target gains its controller the
    life; and a creature the first half killed still bites back, because
    state-based actions wait for the ability to finish resolving."""
    lea = _w1g8c_lea()
    tahngarth_card = set_pool("PLS")["Tahngarth, Talruum Hero"]
    lifelinker = _w1g8c_body("Lifelinker", 3, 5, "Lifelink", ("Lifelink",))
    game, mine, theirs = _w1g8c_duel(
        [tahngarth_card], [lifelinker, lea["Grizzly Bears"]],
    )
    tahngarth = mine[0]

    used = game.activate_permanent_ability(
        0, tahngarth_card.name, ability_index=0,
        target_permanent_ids=[theirs[0].permanent_id],
    )
    assert used.supported, used.details
    _w1g8c_resolve_stack(game)
    assert theirs[0].damage_marked == 4
    assert tahngarth.damage_marked == 3
    assert game.players[1].life == 23, "the Lifelinker dealt that damage"
    assert theirs[1].damage_marked == 0, "the creature named, not its neighbour"

    game, mine, theirs = _w1g8c_duel([tahngarth_card], [lea["Grizzly Bears"]])
    used = game.activate_permanent_ability(
        0, tahngarth_card.name, ability_index=0,
        target_permanent_ids=[theirs[0].permanent_id],
    )
    assert used.supported, used.details
    _w1g8c_resolve_stack(game)
    game._settle()
    assert not game.is_on_battlefield(theirs[0])
    assert mine[0].damage_marked == 2
    assert mine[0].tapped, "{T} is part of the cost"


def test_w1g8_tahngarth_has_vigilance_and_may_target_itself(set_pool):
    """Vigilance: attacking does not tap it. And "target creature" includes
    Tahngarth — it deals itself its power twice over, once as the dealer and
    once as "that creature"."""
    tahngarth_card = set_pool("PLS")["Tahngarth, Talruum Hero"]
    game, mine, _ = _w1g8c_duel([tahngarth_card], [])
    _w1g8c_fight(game, 0, defender=1)
    assert not mine[0].tapped
    assert game.players[1].life == 16

    game, mine, _ = _w1g8c_duel([tahngarth_card], [])
    used = game.activate_permanent_ability(
        0, tahngarth_card.name, ability_index=0,
        target_permanent_ids=[mine[0].permanent_id],
    )
    assert used.supported, used.details
    _w1g8c_resolve_stack(game)
    assert mine[0].damage_marked == 8


def test_w1g8_nemata_pumps_every_players_saprolings(set_pool):
    """"Sacrifice a Saproling: Saproling creatures get +1/+1 until end of
    turn." Every player's, not only the controller's; nothing that is not a
    Saproling; until cleanup; and the cost is a Saproling or the ability
    cannot be activated."""
    lea = _w1g8c_lea()
    nemata_card = set_pool("PLS")["Nemata, Grove Guardian"]
    game, mine, _ = _w1g8c_duel([nemata_card, lea["Grizzly Bears"]], [])

    refused = game.activate_permanent_ability(
        0, nemata_card.name, ability_index=1,
        cost_permanent_ids=[mine[1].permanent_id],
    )
    assert not refused.supported, "a Bear is not a Saproling"
    assert game.is_on_battlefield(mine[1])

    for _ in range(3):
        made = game.activate_permanent_ability(0, nemata_card.name, ability_index=0)
        assert made.supported, made.details
        _w1g8c_resolve_stack(game)
    saprolings = [
        perm for perm in game.controlled_by(0) if perm.has_type("saproling")
    ]
    assert len(saprolings) == 3
    assert saprolings[0].effective_colors == {"G"}
    theirs = _w1g8c_Permanent(card=saprolings[0].card)
    game.players[1].battlefield.append(theirs)
    game._settle()

    pumped = game.activate_permanent_ability(0, nemata_card.name, ability_index=1)
    assert pumped.supported, pumped.details
    _w1g8c_resolve_stack(game)
    survivors = [
        perm for perm in game.controlled_by(0) if perm.has_type("saproling")
    ]
    assert len(survivors) == 2, "one was the cost"
    for perm in [*survivors, theirs]:
        assert (perm.effective_power, perm.effective_toughness) == (2, 2)
    assert (mine[0].effective_power, mine[0].effective_toughness) == (4, 5)
    assert (mine[1].effective_power, mine[1].effective_toughness) == (2, 2)

    game.resolve_cleanup_step(0)
    assert (theirs.effective_power, theirs.effective_toughness) == (1, 1)


def test_w1g8_ertai_may_sacrifice_itself_to_counter(set_pool):
    """"{U}, {T}, Sacrifice a creature or enchantment: Counter target spell."
    Ertai is a creature, so it may pay with itself — the ability is already on
    the stack and still counters. An enchantment pays too; with no spell to
    target the ability is refused with nothing tapped and nothing sacrificed."""
    lea = _w1g8c_lea()
    ertai_card = set_pool("PLS")["Ertai, the Corrupted"]
    game, mine, _ = _w1g8c_duel(
        [ertai_card], [], hand1=[lea["Hill Giant"]], active=1,
    )
    assert game.queue_from_hand(1, "Hill Giant").supported
    used = game.activate_permanent_ability(
        0, ertai_card.name, ability_index=0, target_stack_index=0,
        cost_permanent_ids=[mine[0].permanent_id],
    )
    assert used.supported, used.details
    assert not game.is_on_battlefield(mine[0]), "sacrificed as the cost"
    _w1g8c_resolve_stack(game)
    assert list(game.controlled_by(1)) == []
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]

    game, mine, _ = _w1g8c_duel(
        [ertai_card, lea["Crusade"]], [], hand1=[lea["Lightning Bolt"]], active=1,
    )
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    used = game.activate_permanent_ability(
        0, ertai_card.name, ability_index=0, target_stack_index=0,
        cost_permanent_ids=[mine[1].permanent_id],
    )
    assert used.supported, used.details
    _w1g8c_resolve_stack(game)
    assert game.players[0].life == 20
    assert game.is_on_battlefield(mine[0]) and mine[0].tapped
    assert not game.is_on_battlefield(mine[1])

    game, mine, _ = _w1g8c_duel([ertai_card, lea["Grizzly Bears"]], [])
    refused = game.activate_permanent_ability(0, ertai_card.name, ability_index=0)
    assert not refused.supported
    assert not mine[0].tapped and game.is_on_battlefield(mine[1])


def test_w1g8_flametongue_kavu_must_shoot_something(set_pool):
    """The trigger is mandatory (no "may", no "up to"): with a creature across
    the table it kills it, and alone on the battlefield it must target itself
    and dies — an interactive seat is offered that one target and nothing
    else."""
    lea = _w1g8c_lea()
    kavu = set_pool("PLS")["Flametongue Kavu"]
    game, _, theirs = _w1g8c_duel(
        [], [lea["Hill Giant"], lea["Grizzly Bears"]], hand0=[kavu],
    )
    cast = game.cast_from_hand(
        0, kavu.name, target_permanent_ids=[theirs[0].permanent_id]
    )
    assert cast.supported, cast.details
    _w1g8c_resolve_stack(game)
    game._settle()
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Grizzly Bears"]
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Flametongue Kavu"]

    game, _, _ = _w1g8c_duel([], [], hand0=[kavu])
    assert game.cast_from_hand(0, kavu.name).supported
    _w1g8c_resolve_stack(game)
    game._settle()
    assert list(game.controlled_by(0)) == []
    assert [card.name for card in game.players[0].graveyard] == ["Flametongue Kavu"]

    game, _, _ = _w1g8c_duel([], [], hand0=[kavu], interactive=(0,))
    assert game.cast_from_hand(0, kavu.name).supported
    game.resolve_top_of_stack()
    (prompt,) = game.pending_choices_of("trigger_target", 0)
    assert [target["name"] for target in prompt.data["targets"]] == [
        "Flametongue Kavu",
    ]


# --- W1G5: lands and mana ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.mana_payment import is_mana_ability as _w1g5_is_mana_ability
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_creature_table(set_pool, *, mine=(), theirs=(), hand=(), interactive=(), costs=True):
    """Seat 0's main phase over a board that is already there, nobody
    summoning-sick. Names resolve in Planeshift, then Alpha. Costs are
    enforced unless a test says otherwise."""
    pls, lea = set_pool("PLS"), set_pool("LEA")

    def card(name):
        return pls[name] if name in pls else lea[name]

    me = _W1G5PlayerState(
        name="W1G5-A",
        battlefield=[_W1G5Permanent(card=card(name)) for name in mine],
        hand=[card(name) for name in hand],
    )
    you = _W1G5PlayerState(
        name="W1G5-B",
        battlefield=[_W1G5Permanent(card=card(name)) for name in theirs],
    )
    game = _W1G5Game(players=[me, you])
    game.enforce_mana_costs = costs
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g5_creature_table


def _w1g5_one(game, seat: int, name: str):
    (found,) = [p for p in game.controlled_by(seat) if p.card.name == name]
    return found  # _w1g5_one


def _w1g5_mana(game, seat: int = 0) -> dict[str, int]:
    return {
        symbol: amount
        for symbol, amount in game.players[seat].mana_pool.items() if amount
    }  # _w1g5_mana


def _w1g5_activate(game, name: str, **announced):
    """Activate *name*'s ability under seat 0; the engine's answer."""
    source = _w1g5_one(game, 0, name)
    return game.activate_permanent_ability(
        0, name, permanent_index=game.battlefield_index_of(source), **announced
    )  # _w1g5_activate


def test_w1g5_quirion_explorer_sees_all_three_of_a_lairs_colours(set_pool):
    """"{T}: Add one mana of any color that a land an opponent controls could
    produce." Supported on arrival and never run. Facing a Lair it makes any of
    the Lair's three and not a fourth; an interactive seat that names no colour
    is offered exactly those three, in WUBRG order every time (the list used
    to come out in a set's order, which changes from process to process)."""
    for asked in "UBR":
        game = _w1g5_creature_table(
            set_pool, mine=["Quirion Explorer"], theirs=["Crosis's Catacombs"],
        )
        assert _w1g5_activate(game, "Quirion Explorer", mana_color=asked).supported
        assert not game.stack and _w1g5_mana(game) == {asked: 1}

    game = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Crosis's Catacombs"],
    )
    _w1g5_activate(game, "Quirion Explorer", mana_color="G")
    made = _w1g5_mana(game)
    assert sum(made.values()) == 1 and set(made) <= set("UBR"), made

    asking = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Crosis's Catacombs"],
        interactive={0},
    )
    _w1g5_activate(asking, "Quirion Explorer")
    assert asking.pending_choice_of("mana_color_choice", 0).data["colors"] == [
        "U", "B", "R",
    ]


def test_w1g5_quirion_explorer_reads_a_meteor_crater_for_what_it_makes_now(set_pool):
    """CR 106.7: what a land "could produce" is what its ability would make if
    it resolved now. Scryfall summarises Meteor Crater as all five colours, so
    an Explorer facing a lone Crater was handed five; the Crater's controller
    has no coloured permanent, it could produce nothing, and the Explorer adds
    no mana. With a Hill Giant beside the Crater, the Explorer makes red."""
    bare = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Meteor Crater"],
    )
    assert _w1g5_activate(bare, "Quirion Explorer", mana_color="R").supported
    assert _w1g5_mana(bare) == {}
    assert _w1g5_one(bare, 0, "Quirion Explorer").tapped

    red = _w1g5_creature_table(
        set_pool, mine=["Quirion Explorer"], theirs=["Meteor Crater", "Hill Giant"],
    )
    _w1g5_activate(red, "Quirion Explorer", mana_color="G")
    assert _w1g5_mana(red) == {"R": 1}


def test_w1g5_morgue_toad_is_sacrificed_for_blue_and_red(set_pool):
    """"Sacrifice this creature: Add {U}{R}." A mana ability (CR 605.1a) whose
    whole cost is the Toad: both mana arrive at once without the stack, the
    Toad is in its owner's graveyard, and — no {T} in the cost — a Toad that
    entered this turn can do it (CR 302.6 is about {T} and {Q})."""
    (ability,) = _w1g5_compile(set_pool("PLS")["Morgue Toad"]).activated_abilities
    assert _w1g5_is_mana_ability(ability) and ability.cost.sacrifice_self

    game = _w1g5_creature_table(set_pool, hand=["Morgue Toad"], costs=False)
    assert game.cast_from_hand(0, "Morgue Toad").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_activate(game, "Morgue Toad").supported

    assert _w1g5_mana(game) == {"U": 1, "R": 1}
    assert not game.stack and list(game.controlled_by(0)) == []
    assert [card.name for card in game.players[0].graveyard] == ["Morgue Toad"]


def test_w1g5_kavu_recluse_makes_a_lair_a_forest_for_the_turn(set_pool):
    """"{T}: Target land becomes a Forest until end of turn." CR 305.7: the
    Lair is a Forest and not a Lair, taps for {G} whatever it is asked for,
    and has lost the three-colour ability it prints — refused by name through
    the activation path. At cleanup it is a Lair again."""
    game = _w1g5_creature_table(
        set_pool, mine=["Kavu Recluse"], theirs=["Crosis's Catacombs"],
    )
    lair = _w1g5_one(game, 1, "Crosis's Catacombs")
    assert _w1g5_activate(
        game, "Kavu Recluse", target_permanent_ids=[lair.permanent_id]
    ).supported
    _w1g5_resolve_stack(game)

    assert lair.has_type("forest") and not lair.has_type("lair")
    assert lair.effective_produced_mana == ("G",)
    refused = game.activate_permanent_ability(
        1, "Crosis's Catacombs",
        permanent_index=game.battlefield_index_of(lair), mana_color="U",
    )
    assert not refused.supported and "305.7" in refused.details
    assert game.tap_land_for_mana(1, "Crosis's Catacombs", "U", permanent_id=lair.permanent_id)
    assert _w1g5_mana(game, 1) == {"G": 1}

    assert game.resolve_cleanup_step(0)
    assert lair.has_type("lair") and not lair.has_type("forest")
    assert set(lair.effective_produced_mana) == set("UBR")

    wrong = _w1g5_creature_table(
        set_pool, mine=["Kavu Recluse"], theirs=["Grizzly Bears"],
    )
    bears = _w1g5_one(wrong, 1, "Grizzly Bears")
    assert not _w1g5_activate(
        wrong, "Kavu Recluse", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert not _w1g5_one(wrong, 0, "Kavu Recluse").tapped, "nothing was paid"


def test_w1g5_sea_snidd_asks_for_a_basic_land_type_and_the_land_taps_for_it(set_pool):
    """"{T}: Target land becomes the basic land type of your choice until end
    of turn." The choice is made as the ability resolves (CR 608.2d) and the
    game waits on it; only a basic land type is an answer. The Mountain is a
    Swamp, taps for {B} whatever it is asked for — which casts a black spell a
    Mountain could not — and is a Mountain again after cleanup."""
    game = _w1g5_creature_table(
        set_pool, mine=["Sea Snidd", "Mountain"], hand=["Will-o'-the-Wisp"],
        interactive={0},
    )
    mountain = _w1g5_one(game, 0, "Mountain")
    assert _w1g5_activate(
        game, "Sea Snidd", target_permanent_ids=[mountain.permanent_id]
    ).supported
    game.resolve_top_of_stack()
    assert game.pending_choice_of("land_type_choice", 0) is not None
    assert game.waiting_prompt() is not None
    assert mountain.basic_land_types == ("mountain",), "not before the answer"

    assert not game.confirm_land_type(0, "lair")
    assert game.confirm_land_type(0, "swamp")
    assert mountain.basic_land_types == ("swamp",)
    assert game.tap_land_for_mana(0, "Mountain", "R", permanent_id=mountain.permanent_id)
    assert _w1g5_mana(game) == {"B": 1}
    assert game.cast_from_hand(0, "Will-o'-the-Wisp").supported
    _w1g5_resolve_stack(game)

    assert game.resolve_cleanup_step(0)
    assert mountain.basic_land_types == ("mountain",)


# --- W1G2: two kickers ---
# The five Battlemages ("Kicker {1}{G} and/or {2}{U}", one entry trigger per
# cost — CR 702.33b, CR 702.33f), and the twelve supported-on-arrival cards
# this group drove: Waterspout Elemental, and the ten gating creatures ("When
# this creature enters, return a <colour> or <colour> creature you control to
# its owner's hand."). Ertai's Trickery, the twelfth, is an instant.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.ai_policy import choose_cast_action as _w1g2_choose_cast_action
from engine.card_loader import manifest_set_path as _w1g2_manifest_set_path
from engine.cast_costs import KICKED as _W1G2_KICKED
from engine.cast_costs import KICKED_WITH as _W1G2_KICKED_WITH
from engine.cast_costs import kicked as _w1g2_kicked
from engine.cast_costs import kicker_costs as _w1g2_kicker_costs
from engine.cast_timing import casts_at_instant_speed as _w1g2_instant_speed
from engine.control import change_control as _w1g2_change_control
from engine.mana_payment import mana_cost_from_symbols as _w1g2_symbols
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack

_W1G2_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}

#: The sets a bystander is looked for in, Planeshift first.
_W1G2_SETS = ("PLS", "LEA", "INV", "VIS", "USG", "UDS", "TMP", "PCY")


def _w1g2_named(set_pool, name):
    """*name* out of whichever set prints it — a Battlemage's victims are
    Alpha's, a kicked spell is Invasion's."""
    for code in _W1G2_SETS:
        card = set_pool(code).get(name)
        if card is not None:
            return card
    raise KeyError(name)  # _w1g2_named


def _w1g2_duel(set_pool, hand, *, pool=None, humans=(), their_hand=()):
    """Two seats in a game that **charges mana** — a kicker is a price, and a
    rig that waives mana cannot tell a kicked cast from a free one. Seat 0
    holds *hand*; *humans* are the seats that are asked rather than defaulted."""
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Mage", library=[forest] * 12,
            hand=[_w1g2_named(set_pool, name) for name in hand],
        ),
        _W1G2PlayerState(
            "Rival", library=[forest] * 12,
            hand=[_w1g2_named(set_pool, name) for name in their_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(humans)
    game.players[0].mana_pool.update(_W1G2_RICH if pool is None else pool)
    return game  # _w1g2_duel


def _w1g2_put(game, set_pool, seat, name):
    permanent = _W1G2Permanent(card=_w1g2_named(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent  # _w1g2_put


def _w1g2_floating(game) -> int:
    return sum(game.players[0].mana_pool.values())  # _w1g2_floating


def _w1g2_price(printed: str) -> int:
    return sum((_w1g2_symbols(printed) or {}).values())  # _w1g2_price


def _w1g2_cast(game, name, kick=(), **announced):
    """Cast *name* from seat 0 paying the kicker costs in *kick*, resolve it,
    answer what a headless seat is left owing, and return the permanent."""
    result = game.queue_from_hand(
        0, name,
        optional_cost_payments={key: 1 for key in kick} or None, **announced,
    )
    assert result.supported, result
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return next(
        (p for p in game.controlled_by(0) if p.card.name == name), None
    )  # _w1g2_cast


def _w1g2_names(game, seat):
    return [p.card.name for p in game.controlled_by(seat)]  # _w1g2_names


def _w1g2_until_asked(game, limit=8):
    """Resolve stack objects until somebody is owed a prompt (or the stack is
    empty): a human seat's view of a resolution."""
    for _ in range(limit):
        if game.pending_choices or not game.stack:
            return
        game.resolve_top_of_stack()  # _w1g2_until_asked


#: The five Battlemages: name, first kicker cost, second kicker cost.
_W1G2_BATTLEMAGES = [
    ("Sunscape Battlemage", "{1}{G}", "{2}{U}"),
    ("Stormscape Battlemage", "{W}", "{2}{B}"),
    ("Nightscape Battlemage", "{2}{U}", "{2}{R}"),
    ("Thunderscape Battlemage", "{1}{B}", "{G}"),
    ("Thornscape Battlemage", "{R}", "{W}"),
]


@_w1g2_pytest.mark.parametrize("name,first,second", _W1G2_BATTLEMAGES)
def test_w1g2_a_battlemage_offers_two_kickers_and_pays_for_the_ones_it_takes(
    set_pool, name, first, second
):
    """CR 702.33b: "Kicker [cost 1] and/or [cost 2]" is two kicker abilities.
    Each is its own offer, each is charged only when taken, and the cast
    remembers *which* — on the stack item, then on the permanent."""
    card = set_pool("PLS")[name]
    assert _w1g2_kicker_costs(card.oracle_text) == (first, second)

    offers = _w1g2_duel(set_pool, [name]).cast_cost_offers(0, card)
    assert [(o["symbols"], o["label"], o["max_times"]) for o in offers] == [
        (first, "kicker", 1), (second, "kicker", 1),
    ]

    for taken in ((), (first,), (second,), (first, second)):
        game = _w1g2_duel(set_pool, [name])
        # Something for a kicked trigger to hit that is not the Battlemage: a
        # mandatory "destroy target nonblack creature" with no other creature
        # in play has to take its own source (the test after next).
        _w1g2_put(game, set_pool, 1, "Grizzly Bears")
        before = _w1g2_floating(game)
        result = game.queue_from_hand(
            0, name, optional_cost_payments={key: 1 for key in taken} or None
        )
        assert result.supported, (taken, result)
        item = next(i for i in game.stack if i.card is card)
        assert _w1g2_kicked(card, item.choices) is bool(taken)
        assert before - _w1g2_floating(game) == _w1g2_price(card.mana_cost) + sum(
            _w1g2_price(key) for key in taken
        ), taken
        _w1g2_resolve_stack(game)
        game.auto_resolve_pending_choices()
        mage = next(p for p in game.controlled_by(0) if p.card is card)
        assert bool(mage.metadata.get(_W1G2_KICKED)) is bool(taken)
        assert tuple(mage.metadata.get(_W1G2_KICKED_WITH) or ()) == taken
        assert (f"Mage kicked {name}" in game.log) is bool(taken)


def test_w1g2_two_kickers_are_priced_as_a_sum_not_one_at_a_time(set_pool):
    """Sunscape Battlemage is {2}{W} with kickers {1}{G} and {2}{U}: eight mana
    for everything. Seven pays for either kicker and not for both, the offer
    prompt says so once one is taken, and a cast that announces both anyway is
    refused with nothing spent (CR 601.2h)."""
    card = set_pool("PLS")["Sunscape Battlemage"]
    seven = {"W": 1, "G": 1, "U": 1, "R": 4}
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage"], pool=seven)

    assert [o["max_times"] for o in game.cast_cost_offers(0, card)] == [1, 1]
    after_green = game.cast_cost_offers(0, card, taken={"{1}{G}": 1})
    assert [(o["symbols"], o["max_times"]) for o in after_green] == [
        ("{1}{G}", 1), ("{2}{U}", 0),
    ]

    refused = game.queue_from_hand(
        0, "Sunscape Battlemage",
        optional_cost_payments={"{1}{G}": 1, "{2}{U}": 1},
    )
    assert not refused.supported
    assert _w1g2_floating(game) == 7
    assert [c.name for c in game.players[0].hand] == ["Sunscape Battlemage"]

    eight = _w1g2_duel(
        set_pool, ["Sunscape Battlemage"], pool={**seven, "R": 5}
    )
    mage = _w1g2_cast(eight, "Sunscape Battlemage", kick=("{1}{G}", "{2}{U}"))
    assert mage is not None and _w1g2_floating(eight) == 0


@_w1g2_pytest.mark.parametrize("name,first,second", _W1G2_BATTLEMAGES)
def test_w1g2_a_battlemage_nothing_cast_was_kicked_with_nothing(
    set_pool, name, first, second
):
    """CR 400.7 / CR 702.33d: put onto the battlefield without being cast — a
    reanimation, a blink — there was no CR 601.2b, so neither "if" holds.
    Nothing triggers, nothing is asked, and the board is untouched."""
    game = _w1g2_duel(set_pool, [], humans=(0,))
    board = [
        _w1g2_put(game, set_pool, 1, victim) for victim in
        ("Serra Angel", "Grizzly Bears", "Forest", "Sol Ring", "Castle")
    ]
    mage = _w1g2_put(game, set_pool, 0, name)

    assert not mage.metadata.get(_W1G2_KICKED)
    assert not mage.metadata.get(_W1G2_KICKED_WITH)
    assert game.stack == [] and game.pending_choices == []
    assert all(game.is_on_battlefield(permanent) for permanent in board)
    assert (game.players[0].life, len(game.players[0].hand)) == (20, 0)


def test_w1g2_sunscape_battlemage_each_kicker_buys_its_own_trigger(set_pool):
    """"…if it was kicked with its {1}{G} kicker, destroy target creature with
    flying." / "…with its {2}{U} kicker, draw two cards." CR 702.33f: each
    ability is linked to one cost, so each combination does exactly its own."""
    outcomes = {}
    for taken in ((), ("{1}{G}",), ("{2}{U}",), ("{1}{G}", "{2}{U}")):
        game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
        angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
        bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
        named = {"target_permanent_ids": [angel.permanent_id]} if "{1}{G}" in taken else {}
        _w1g2_cast(game, "Sunscape Battlemage", kick=taken, **named)
        assert game.is_on_battlefield(bears)
        outcomes[taken] = (game.is_on_battlefield(angel), len(game.players[0].hand))

    assert outcomes == {
        (): (True, 0),
        ("{1}{G}",): (False, 0),
        ("{2}{U}",): (True, 2),
        ("{1}{G}", "{2}{U}"): (False, 2),
    }


def test_w1g2_sunscape_battlemage_the_wrong_kicker_does_not_destroy(set_pool):
    """The question is *which* kicker. A cast that paid {2}{U} and named a
    flier anyway draws its two cards and destroys nothing: the destroy is the
    {1}{G} trigger's, and that trigger did not trigger (CR 603.4)."""
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    _w1g2_cast(
        game, "Sunscape Battlemage", kick=("{2}{U}",),
        target_permanent_ids=[angel.permanent_id],
    )
    assert game.is_on_battlefield(angel)
    assert len(game.players[0].hand) == 2
    assert game.players[1].graveyard == []


def test_w1g2_sunscape_battlemage_destroys_only_a_flier(set_pool):
    """"Destroy target creature **with flying**": the picker offers the fliers
    on either side and nothing else."""
    card = set_pool("PLS")["Sunscape Battlemage"]
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
    for seat, name in ((1, "Serra Angel"), (1, "Grizzly Bears"), (0, "Air Elemental")):
        _w1g2_put(game, set_pool, seat, name)
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{1}{G}": 1})
    assert sorted(entry["name"] for entry in spec["valid_targets"]) == [
        "Air Elemental", "Serra Angel",
    ]


def test_w1g2_stormscape_battlemage_gains_life_and_buries_a_nonblack_creature(set_pool):
    """{W}: "you gain 3 life" — *you*, whoever the other trigger is aimed at.
    {2}{B}: "destroy target nonblack creature. That creature can't be
    regenerated." — a regeneration shield does not save it."""
    outcomes = {}
    for taken in (("{W}",), ("{2}{B}",), ("{W}", "{2}{B}")):
        game = _w1g2_duel(set_pool, ["Stormscape Battlemage"])
        bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
        bears.regeneration_shield = 1
        named = {"target_permanent_ids": [bears.permanent_id]} if "{2}{B}" in taken else {}
        _w1g2_cast(game, "Stormscape Battlemage", kick=taken, **named)
        outcomes[taken] = (
            game.players[0].life, game.players[1].life,
            [card.name for card in game.players[1].graveyard],
        )

    assert outcomes == {
        ("{W}",): (23, 20, []),
        ("{2}{B}",): (20, 20, ["Grizzly Bears"]),
        ("{W}", "{2}{B}"): (23, 20, ["Grizzly Bears"]),
    }


def test_w1g2_a_mandatory_target_can_be_the_battlemage_itself(set_pool):
    """A trigger's target is not optional (CR 603.3d): Stormscape Battlemage is
    blue, so with no other nonblack creature anywhere its own {2}{B} trigger
    has exactly one legal target, and takes it. Legal, and a reason the AI
    does not pay {2}{B} onto that board — it pays {W} alone."""
    game = _w1g2_duel(set_pool, ["Stormscape Battlemage"])
    _w1g2_put(game, set_pool, 1, "Black Knight")
    assert _w1g2_cast(game, "Stormscape Battlemage", kick=("{2}{B}",)) is None
    assert [c.name for c in game.players[0].graveyard] == ["Stormscape Battlemage"]

    seven = ["Island"] * 3 + ["Plains"] + ["Swamp"] * 3
    _game, action = _w1g2_ai_table(
        set_pool, "Stormscape Battlemage", seven, theirs=["Black Knight"]
    )
    assert action.optional_cost_payments == {"{W}": 1}


def test_w1g2_stormscape_battlemage_cannot_be_aimed_at_a_black_creature(set_pool):
    """"Destroy target **nonblack** creature." The picker never offers the
    black one, and a cast that names it anyway does not destroy it.

    It used to end "…destroys nothing": the handler declining an illegal
    target it had been handed. The trigger chooses as it is put on the stack
    (CR 603.3d), so an announcement it could not have made is set aside and
    it takes the picker's default instead — the Bears."""
    card = set_pool("PLS")["Stormscape Battlemage"]
    game = _w1g2_duel(set_pool, ["Stormscape Battlemage"])
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    spec = game.cast_target_spec(0, card, optional_cost_payments={"{2}{B}": 1})
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]

    _w1g2_cast(
        game, "Stormscape Battlemage", kick=("{2}{B}",),
        target_permanent_ids=[knight.permanent_id],
    )
    assert game.is_on_battlefield(knight) and not game.is_on_battlefield(bears)


def test_w1g2_nightscape_battlemage_returns_up_to_two_nonblack_creatures(set_pool):
    """{2}{U}: "return **up to two** target nonblack creatures to their owners'
    hands." Two are named — one on each side — and each goes to its own
    owner's hand. The black creature is never offered, and no land is touched
    (that is the other kicker's trigger)."""
    card = set_pool("PLS")["Nightscape Battlemage"]
    game = _w1g2_duel(set_pool, ["Nightscape Battlemage"])
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    mine = _w1g2_put(game, set_pool, 0, "Grizzly Bears")

    spec = game.cast_target_spec(0, card, optional_cost_payments={"{2}{U}": 1})
    assert (spec["kind"], spec["max_targets"]) == ("creature", 2)
    assert "exact_targets" not in spec
    assert sorted(entry["name"] for entry in spec["valid_targets"]) == [
        "Grizzly Bears", "Serra Angel",
    ]

    _w1g2_cast(
        game, "Nightscape Battlemage", kick=("{2}{U}",),
        target_permanent_ids=[angel.permanent_id, mine.permanent_id],
    )
    assert [c.name for c in game.players[1].hand] == ["Serra Angel"]
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert game.is_on_battlefield(knight) and game.is_on_battlefield(forest)


def test_w1g2_nightscape_battlemage_destroys_a_land(set_pool):
    """{2}{R}: "destroy target land." Nothing is returned to a hand."""
    game = _w1g2_duel(set_pool, ["Nightscape Battlemage"])
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    _w1g2_cast(
        game, "Nightscape Battlemage", kick=("{2}{R}",),
        target_permanent_ids=[forest.permanent_id],
    )
    assert [c.name for c in game.players[1].graveyard] == ["Forest"]
    assert game.is_on_battlefield(angel) and game.players[1].hand == []


def test_w1g2_a_both_kicked_battlemage_asks_for_the_second_triggers_target(set_pool):
    """One cast carries one set of target fields, and they are the *first*
    trigger's. Nightscape Battlemage kicked both ways with two creatures named
    returns them — and "destroy target land" asks its controller as it goes on
    the stack, where it used to be handed the two creatures and report its
    target gone (CR 603.3d).

    Both triggers are stack objects (CR 603.3), so the land is asked for as
    the pair goes on the stack — before either has resolved — and the first
    printed, the bounce, resolves first."""
    game = _w1g2_duel(set_pool, ["Nightscape Battlemage"], humans=(0,))
    angel = _w1g2_put(game, set_pool, 1, "Serra Angel")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    mountain = _w1g2_put(game, set_pool, 0, "Mountain")

    result = game.queue_from_hand(
        0, "Nightscape Battlemage",
        optional_cost_payments={"{2}{U}": 1, "{2}{R}": 1},
        target_permanent_ids=[angel.permanent_id, bears.permanent_id],
    )
    assert result.supported, result
    _w1g2_until_asked(game)

    assert len(game.stack) == 2 and all(item.is_ability for item in game.stack)
    assert game.players[1].hand == [], "nothing has resolved yet"
    (asked,) = game.pending_choices
    assert (asked.kind, asked.player_index) == ("trigger_target", 0)
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Forest", "Mountain"]
    assert game.confirm_trigger_target(0, permanent_id=forest.permanent_id)

    assert game.resolve_top_of_stack()
    assert sorted(c.name for c in game.players[1].hand) == [
        "Grizzly Bears", "Serra Angel",
    ]
    assert game.is_on_battlefield(forest) and game.is_on_battlefield(mountain)

    _w1g2_resolve_stack(game)
    assert not game.is_on_battlefield(forest) and game.is_on_battlefield(mountain)


def test_w1g2_thunderscape_battlemage_discard_and_enchantment(set_pool):
    """{1}{B}: "target player discards two cards." {G}: "destroy target
    enchantment." Each alone does its own half and nothing of the other."""
    game = _w1g2_duel(
        set_pool, ["Thunderscape Battlemage"],
        their_hand=["Forest", "Forest", "Grizzly Bears"],
    )
    castle = _w1g2_put(game, set_pool, 1, "Castle")
    _w1g2_cast(game, "Thunderscape Battlemage", kick=("{1}{B}",), target_player_index=1)
    assert len(game.players[1].hand) == 1
    assert len(game.players[1].graveyard) == 2
    assert game.is_on_battlefield(castle)

    game = _w1g2_duel(
        set_pool, ["Thunderscape Battlemage"],
        their_hand=["Forest", "Forest", "Grizzly Bears"],
    )
    castle = _w1g2_put(game, set_pool, 1, "Castle")
    _w1g2_cast(
        game, "Thunderscape Battlemage", kick=("{G}",),
        target_permanent_ids=[castle.permanent_id],
    )
    assert [c.name for c in game.players[1].graveyard] == ["Castle"]
    assert len(game.players[1].hand) == 3


def test_w1g2_a_trigger_is_never_handed_another_triggers_target(set_pool):
    """The defect the both-kicked cast exposed. Thunderscape Battlemage kicked
    both ways with the discard aimed at **its own controller**: the enchantment
    trigger was handed that seat, fell to the handler's board scan and
    destroyed the caster's own Crusade. It is asked instead — both
    enchantments on offer — and nothing is destroyed until it is answered."""
    game = _w1g2_duel(
        set_pool, ["Thunderscape Battlemage", "Forest", "Forest", "Forest"],
        humans=(0,),
    )
    crusade = _w1g2_put(game, set_pool, 0, "Crusade")
    castle = _w1g2_put(game, set_pool, 1, "Castle")

    result = game.queue_from_hand(
        0, "Thunderscape Battlemage",
        optional_cost_payments={"{1}{B}": 1, "{G}": 1}, target_player_index=0,
    )
    assert result.supported, result
    _w1g2_until_asked(game)

    # Both triggers are on the stack (CR 603.3); the enchantment's target is
    # asked for as it goes there, and the discard has not begun.
    assert game.is_on_battlefield(crusade) and game.is_on_battlefield(castle)
    assert len(game.stack) == 2 and len(game.players[0].hand) == 3
    kinds = sorted((choice.kind, choice.player_index) for choice in game.pending_choices)
    assert kinds == [("trigger_target", 0)]
    asked = next(c for c in game.pending_choices if c.kind == "trigger_target")
    assert sorted(t["name"] for t in asked.data["targets"]) == ["Castle", "Crusade"]
    assert game.confirm_trigger_target(0, permanent_id=castle.permanent_id)

    # The first printed resolves first: the discard, at the seat the cast named.
    _w1g2_until_asked(game)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 0)]
    assert game.is_on_battlefield(crusade) and game.is_on_battlefield(castle)

    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    assert game.is_on_battlefield(crusade) and not game.is_on_battlefield(castle)
    assert len(game.players[0].hand) == 1


def test_w1g2_thornscape_battlemage_two_damage_and_an_artifact(set_pool):
    """{R}: "it deals 2 damage to any target" — a face or a creature. {W}:
    "destroy target artifact.\""""
    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"])
    ring = _w1g2_put(game, set_pool, 1, "Sol Ring")
    _w1g2_cast(game, "Thornscape Battlemage", kick=("{R}",), target_player_index=1)
    assert game.players[1].life == 18 and game.is_on_battlefield(ring)

    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"])
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    _w1g2_cast(
        game, "Thornscape Battlemage", kick=("{R}",),
        target_permanent_ids=[bears.permanent_id],
    )
    game.check_state_based_actions()
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]
    assert game.players[1].life == 20

    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"])
    ring = _w1g2_put(game, set_pool, 1, "Sol Ring")
    _w1g2_cast(
        game, "Thornscape Battlemage", kick=("{W}",),
        target_permanent_ids=[ring.permanent_id],
    )
    assert [c.name for c in game.players[1].graveyard] == ["Sol Ring"]
    assert game.players[1].life == 20


def test_w1g2_a_both_kicked_battlemage_puts_two_triggers_on_the_stack(set_pool):
    """With nothing named at cast, CR 603.3d has both choices to make:
    Thornscape Battlemage's two triggers are two stack objects, a human seat
    is asked for each with that trigger's own candidates, and each answer is
    the one that resolves."""
    game = _w1g2_duel(set_pool, ["Thornscape Battlemage"], humans=(0,))
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    ring = _w1g2_put(game, set_pool, 1, "Sol Ring")
    pearl = _w1g2_put(game, set_pool, 0, "Mox Pearl")

    result = game.queue_from_hand(
        0, "Thornscape Battlemage", optional_cost_payments={"{R}": 1, "{W}": 1}
    )
    assert result.supported, result
    assert game.resolve_top_of_stack()

    assert len(game.stack) == 2
    # The first printed is on top, so it resolves first (CR 603.3b at the
    # engine's stated order) — which makes it the *last* put on the stack, and
    # so the last asked.
    assert "2 damage" in game.stack[-1].ability_text
    destroy, damage = game.pending_choices
    assert (damage.kind, destroy.kind) == ("trigger_target", "trigger_target")
    assert sorted(t["name"] for t in damage.data["targets"]) == [
        "Black Knight", "Mage", "Rival", "Thornscape Battlemage",
    ]
    assert sorted(t["name"] for t in destroy.data["targets"]) == [
        "Mox Pearl", "Sol Ring",
    ]

    # Each answer is held to the prompt it answers: the Knight is no artifact.
    assert not game.confirm_trigger_target(0, permanent_id=knight.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=ring.permanent_id)
    assert game.confirm_trigger_target(0, permanent_id=knight.permanent_id)
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Black Knight", "Sol Ring",
    ]
    assert game.is_on_battlefield(pearl)
    assert [p.life for p in game.players] == [20, 20]


#: What the cast's picker asks for under each announcement: the *first*
#: trigger that announcement fires and that has a target (CR 702.33g).
_W1G2_PICKERS = [
    ("Sunscape Battlemage", (), "none"),
    ("Sunscape Battlemage", ("{1}{G}",), "creature"),
    ("Sunscape Battlemage", ("{2}{U}",), "none"),
    ("Sunscape Battlemage", ("{1}{G}", "{2}{U}"), "creature"),
    ("Stormscape Battlemage", ("{W}",), "none"),
    ("Stormscape Battlemage", ("{2}{B}",), "creature"),
    ("Nightscape Battlemage", ("{2}{U}",), "creature"),
    ("Nightscape Battlemage", ("{2}{R}",), "land"),
    ("Nightscape Battlemage", ("{2}{U}", "{2}{R}"), "creature"),
    ("Thunderscape Battlemage", ("{1}{B}",), "player"),
    ("Thunderscape Battlemage", ("{G}",), "permanent"),
    ("Thunderscape Battlemage", ("{1}{B}", "{G}"), "player"),
    ("Thornscape Battlemage", ("{R}",), "any"),
    ("Thornscape Battlemage", ("{W}",), "artifact"),
    ("Thornscape Battlemage", ("{R}", "{W}"), "any"),
]


@_w1g2_pytest.mark.parametrize("name,taken,kind", _W1G2_PICKERS)
def test_w1g2_a_battlemage_names_a_target_only_for_the_kicker_it_paid(
    set_pool, name, taken, kind
):
    """CR 702.33g: "the spell's controller chooses those targets only if that
    spell was kicked" — and with two kickers, only if it was kicked with the
    one the target belongs to."""
    card = set_pool("PLS")[name]
    game = _w1g2_duel(set_pool, [name])
    spec = game.cast_target_spec(
        0, card, optional_cost_payments={key: 1 for key in taken}
    )
    assert spec["kind"] == kind
    assert spec["requires_target"] is (kind != "none")


def test_w1g2_a_recast_battlemage_forgets_how_it_was_kicked(set_pool):
    """CR 400.7: the Battlemage that drew two cards, returned to its owner's
    hand and cast again for its mana cost alone is a new object that was
    kicked with nothing — no stamp, and no second pair of cards."""
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage", "Unsummon"])
    mage = _w1g2_cast(game, "Sunscape Battlemage", kick=("{2}{U}",))
    assert mage.metadata.get(_W1G2_KICKED_WITH) == ("{2}{U}",)
    drawn = [c for c in game.players[0].hand if c.name != "Unsummon"]
    assert len(drawn) == 2

    assert game.queue_from_hand(
        0, "Unsummon", target_permanent_ids=[mage.permanent_id]
    ).supported
    _w1g2_resolve_stack(game)
    assert "Sunscape Battlemage" in [c.name for c in game.players[0].hand]

    again = _w1g2_cast(game, "Sunscape Battlemage")
    assert again is not mage
    assert not again.metadata.get(_W1G2_KICKED)
    assert not again.metadata.get(_W1G2_KICKED_WITH)
    assert len(game.players[0].hand) == 2


def test_w1g2_a_clone_of_a_kicked_battlemage_was_kicked_with_nothing(set_pool):
    """A Clone that enters as a copy of a both-kicked Sunscape Battlemage has
    the Battlemage's two entry triggers (CR 707.5) and was cast as a *Clone*,
    which prints no kicker: neither "if" holds, so it draws nothing."""
    game = _w1g2_duel(set_pool, ["Sunscape Battlemage", "Clone"])
    mage = _w1g2_cast(game, "Sunscape Battlemage", kick=("{1}{G}", "{2}{U}"))
    held = len(game.players[0].hand)

    result = game.queue_from_hand(
        0, "Clone", target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[mage.permanent_id],
    )
    assert result.supported, result
    _w1g2_resolve_stack(game)
    clone = next(p for p in game.controlled_by(0) if p is not mage)

    assert clone.effective_card.name == "Sunscape Battlemage"
    assert not clone.metadata.get(_W1G2_KICKED_WITH)
    assert len(game.players[0].hand) == held - 1
    assert game.stack == []


def test_w1g2_either_kicker_alone_is_a_kicked_spell_to_everything_else(set_pool):
    """CR 702.33d: "any of that spell's kicker costs". Saproling Infestation's
    "whenever a player kicks a spell" sees a Battlemage that paid only its
    *second* kicker, and does not see an unkicked one."""
    for taken, tokens in (((), 0), (("{2}{U}",), 1), (("{1}{G}",), 1)):
        game = _w1g2_duel(set_pool, ["Sunscape Battlemage"])
        _w1g2_put(game, set_pool, 1, "Saproling Infestation")
        _w1g2_cast(game, "Sunscape Battlemage", kick=taken)
        saprolings = [
            p for p in game.controlled_by(1) if p.metadata.get("is_token")
        ]
        assert len(saprolings) == tokens, taken


def _w1g2_ai_table(set_pool, name, lands, mine=(), theirs=()):
    """Seat 0 is an AI holding *name* with *lands* untapped and nothing
    floating; returns the game and what it would cast."""
    game = _w1g2_duel(set_pool, [name], pool={})
    for land in lands:
        _w1g2_put(game, set_pool, 0, land)
    for seat, names in ((0, mine), (1, theirs)):
        for permanent in names:
            _w1g2_put(game, set_pool, seat, permanent)
    return game, _w1g2_choose_cast_action(game, 0)  # _w1g2_ai_table


def test_w1g2_the_ai_kicks_what_it_can_pay_for_and_has_a_target_for(set_pool):
    """The stated policy, per kicker. Eight lands and an opposing flier: both.
    The same lands and the only flier its own: the draw alone. Five lands that
    make no blue and no flier to hit: the plain 2/2."""
    wwwgguuu = ["Plains"] * 3 + ["Forest"] * 2 + ["Island"] * 3
    _game, both = _w1g2_ai_table(
        set_pool, "Sunscape Battlemage", wwwgguuu, theirs=["Serra Angel"]
    )
    assert both.optional_cost_payments == {"{1}{G}": 1, "{2}{U}": 1}
    assert len(both.land_tap_indices) == 8

    _game, draw = _w1g2_ai_table(
        set_pool, "Sunscape Battlemage", wwwgguuu, mine=["Serra Angel"]
    )
    assert draw.optional_cost_payments == {"{2}{U}": 1}

    _game, plain = _w1g2_ai_table(
        set_pool, "Sunscape Battlemage", ["Plains"] * 3 + ["Forest"] * 2,
        theirs=["Grizzly Bears"],
    )
    assert (plain.card_name, plain.optional_cost_payments) == (
        "Sunscape Battlemage", None,
    )


def test_w1g2_the_ai_does_not_pay_to_destroy_its_own_permanent(set_pool):
    """The second trigger's target is chosen on the stack, where the choice is
    mandatory — so a seat that pays for it while only its own seat holds a
    legal target must destroy its own. Nightscape Battlemage with every land
    on the table its own does not pay {2}{R}; Thornscape Battlemage with the
    only artifact its own does not pay {W}."""
    nine = ["Swamp"] * 3 + ["Island"] * 3 + ["Mountain"] * 3
    _game, action = _w1g2_ai_table(
        set_pool, "Nightscape Battlemage", nine, theirs=["Serra Angel"]
    )
    assert action.optional_cost_payments == {"{2}{U}": 1}

    _game, action = _w1g2_ai_table(
        set_pool, "Nightscape Battlemage", nine, theirs=["Serra Angel", "Forest"]
    )
    assert action.optional_cost_payments == {"{2}{U}": 1, "{2}{R}": 1}

    five = ["Forest"] * 3 + ["Mountain", "Plains"]
    _game, action = _w1g2_ai_table(
        set_pool, "Thornscape Battlemage", five, mine=["Sol Ring"]
    )
    assert action.optional_cost_payments == {"{R}": 1}
    _game, action = _w1g2_ai_table(
        set_pool, "Thornscape Battlemage", five, theirs=["Sol Ring"]
    )
    assert action.optional_cost_payments == {"{R}": 1, "{W}": 1}


def test_w1g2_the_ai_aims_a_battlemages_discard_at_an_opponent(set_pool):
    """Thunderscape Battlemage's "target player discards two cards" is the
    cast's seat, and the AI used to give a creature spell's seat to itself."""
    six = ["Mountain"] * 3 + ["Swamp"] * 2 + ["Forest"]
    game, action = _w1g2_ai_table(
        set_pool, "Thunderscape Battlemage", six, theirs=["Castle"]
    )
    assert action.optional_cost_payments == {"{1}{B}": 1, "{G}": 1}
    assert action.target_player_index == 1


def test_w1g2_the_ai_returns_two_opposing_creatures_not_its_own(set_pool):
    """Nightscape Battlemage's "up to two target nonblack creatures", named by
    the AI: both of the opponent's, with two of its own on the table."""
    six = ["Swamp"] * 3 + ["Island"] * 3
    game, action = _w1g2_ai_table(
        set_pool, "Nightscape Battlemage", six,
        mine=["Grizzly Bears", "Air Elemental"],
        theirs=["Serra Angel", "Hill Giant"],
    )
    assert action.optional_cost_payments == {"{2}{U}": 1}
    assert action.target_player_index == 1
    named = sorted(
        game.permanent_at(game.players[1], slot).card.name
        for slot in action.target_permanent_index
    )
    assert named == ["Hill Giant", "Serra Angel"]


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_plays_battlemages_through_whole_games():
    """All five pinned into both decks of six simulated games: they are cast,
    several are kicked, and none is ever refused or left owing a prompt as its
    step ends. (The pool is a measured set, so other cards' unsupported casts
    are in the report; only the Battlemages' lines are read. The floors are
    well under what the seed gives today — five cast, eleven kicked — so
    another card becoming castable does not move them.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [name for name, _first, _second in _W1G2_BATTLEMAGES]
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("PLS", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )
    assert report.games_completed == 6
    cast = {
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    }
    assert len(cast) >= 3, sorted(cast)
    kicked = [line for line in report.log_lines if " kicked " in line and "Battlemage" in line]
    assert len(kicked) >= 4, kicked
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [i.message for i in report.issues if "Battlemage" in i.message] == []
    w1g2_battlemages_left_nothing_owing = not report.steps_left_owing
    assert w1g2_battlemages_left_nothing_owing, report.steps_left_owing


# Waterspout Elemental ------------------------------------------------------


def test_w1g2_waterspout_elemental_kicked_empties_the_board_and_skips_a_turn(set_pool):
    """"When this creature enters, if it was kicked, return all **other**
    creatures to their owners' hands and you skip your next turn." Both halves,
    for the {U}: every creature but the Elemental goes home, and the seat that
    cast it sits out its next turn — the opponent takes two in a row."""
    game = _w1g2_duel(set_pool, ["Waterspout Elemental"])
    _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    _w1g2_put(game, set_pool, 1, "Serra Angel")
    forest = _w1g2_put(game, set_pool, 1, "Forest")
    before = _w1g2_floating(game)
    elemental = _w1g2_cast(game, "Waterspout Elemental", kick=("{U}",))

    assert before - _w1g2_floating(game) == 6
    assert _w1g2_names(game, 0) == ["Waterspout Elemental"]
    assert _w1g2_names(game, 1) == ["Forest"]
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].hand] == ["Serra Angel"]
    assert game.is_on_battlefield(elemental) and game.is_on_battlefield(forest)
    assert game._has_keyword(elemental, "flying")

    game.active_player_index = 0
    assert [game.start_next_turn() for _ in range(4)] == [1, 1, 0, 1]


def test_w1g2_waterspout_elemental_unkicked_is_a_five_mana_flier(set_pool):
    """Unkicked, the entry trigger does not trigger (CR 603.4): nothing is
    returned and no turn is skipped."""
    game = _w1g2_duel(set_pool, ["Waterspout Elemental"])
    _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    _w1g2_put(game, set_pool, 1, "Serra Angel")
    before = _w1g2_floating(game)
    _w1g2_cast(game, "Waterspout Elemental")

    assert before - _w1g2_floating(game) == 5
    assert _w1g2_names(game, 0) == ["Grizzly Bears", "Waterspout Elemental"]
    assert _w1g2_names(game, 1) == ["Serra Angel"]
    game.active_player_index = 0
    assert [game.start_next_turn() for _ in range(3)] == [1, 0, 1]


# Gating ---------------------------------------------------------------------

#: The ten gating creatures and the two colours each one's entry trigger names.
_W1G2_GATERS = [
    ("Cavern Harpy", "U", "B"),
    ("Fleetfoot Panther", "G", "W"),
    ("Horned Kavu", "R", "G"),
    ("Lava Zombie", "B", "R"),
    ("Marsh Crocodile", "U", "B"),
    ("Razing Snidd", "B", "R"),
    ("Shivan Wurm", "R", "G"),
    ("Silver Drake", "W", "U"),
    ("Sparkcaster", "R", "G"),
    ("Steel Leaf Paladin", "G", "W"),
]

#: A vanilla Alpha creature of each colour, to stand on the board.
_W1G2_OF_COLOR = {
    "W": "Savannah Lions", "U": "Merfolk of the Pearl Trident",
    "B": "Black Knight", "R": "Goblin Balloon Brigade", "G": "Grizzly Bears",
}


def _w1g2_gate_prompt(game):
    """The one gating prompt owed, with the names it offers."""
    asked = next(c for c in game.pending_choices if c.kind == "permanent_set_choice")
    offered = [p.card.name for p in game.live_permanent_set_choices(asked)]
    return asked, offered  # _w1g2_gate_prompt


@_w1g2_pytest.mark.parametrize("name,one,two", _W1G2_GATERS)
def test_w1g2_a_gater_alone_returns_itself(set_pool, name, one, two):
    """The return is not optional and the creature that asks is itself a legal
    answer — so alone, or beside only creatures of the wrong colours, it is
    the only one, and the card goes back to its owner's hand.

    (Marsh Crocodile's *other* trigger then makes each player discard a card,
    and the Crocodile is the only card its controller holds.)"""
    off = next(c for c in "WUBRG" if c not in (one, two))
    for bystanders in ((), (_W1G2_OF_COLOR[off],)):
        game = _w1g2_duel(set_pool, [name])
        for bystander in bystanders:
            _w1g2_put(game, set_pool, 0, bystander)
        announced = {"target_player_index": 1} if name == "Sparkcaster" else {}
        assert _w1g2_cast(game, name, **announced) is None
        assert _w1g2_names(game, 0) == list(bystanders)
        assert f"{name} returned {name} to hand" in game.log
        mage = game.players[0]
        held = mage.graveyard if name == "Marsh Crocodile" else mage.hand
        assert [c.name for c in held] == [name]


@_w1g2_pytest.mark.parametrize("name,one,two", _W1G2_GATERS)
def test_w1g2_a_gater_asks_which_creature_and_takes_only_a_legal_answer(
    set_pool, name, one, two
):
    """A human seat is *asked*, and offered exactly what the line prints: the
    creatures of either colour it controls, the gater included — not one of
    another colour, not an opponent's. One creature, no fewer and no more."""
    off = next(c for c in "WUBRG" if c not in (one, two))
    game = _w1g2_duel(set_pool, [name], humans=(0,))
    first = _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[one])
    second = _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[two])
    wrong = _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[off])
    theirs = _w1g2_put(game, set_pool, 1, _W1G2_OF_COLOR[two])

    announced = {"target_player_index": 1} if name == "Sparkcaster" else {}
    assert game.queue_from_hand(0, name, **announced).supported
    _w1g2_until_asked(game)
    asked, offered = _w1g2_gate_prompt(game)
    assert asked.player_index == 0
    assert offered == [_W1G2_OF_COLOR[one], _W1G2_OF_COLOR[two], name]

    for illegal in (
        [wrong.permanent_id], [theirs.permanent_id], [],
        [first.permanent_id, second.permanent_id],
    ):
        assert not game.confirm_permanent_set_choice(0, illegal), illegal
    assert not game.confirm_permanent_set_choice(1, [first.permanent_id])

    assert game.confirm_permanent_set_choice(0, [second.permanent_id])
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    assert [c.name for c in game.players[0].hand] == [_W1G2_OF_COLOR[two]]
    assert _w1g2_names(game, 0) == [
        _W1G2_OF_COLOR[one], _W1G2_OF_COLOR[off], name,
    ]
    assert game.is_on_battlefield(theirs)


def test_w1g2_gating_reads_colour_through_the_layers(set_pool):
    """Cavern Harpy asks for "a blue or black creature". A green creature
    turned blue (Thoughtlace) is one; a black creature turned red (Chaoslace)
    is not — the printed colours answer neither question."""
    game = _w1g2_duel(set_pool, ["Thoughtlace", "Cavern Harpy"], humans=(0,))
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Thoughtlace", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g2_resolve_stack(game)
    assert game.queue_from_hand(0, "Cavern Harpy").supported
    _w1g2_until_asked(game)
    assert _w1g2_gate_prompt(game)[1] == ["Grizzly Bears", "Cavern Harpy"]

    game = _w1g2_duel(set_pool, ["Chaoslace", "Cavern Harpy"], humans=(0,))
    knight = _w1g2_put(game, set_pool, 0, "Black Knight")
    assert game.queue_from_hand(
        0, "Chaoslace", target_permanent_ids=[knight.permanent_id]
    ).supported
    _w1g2_resolve_stack(game)
    assert game.queue_from_hand(0, "Cavern Harpy").supported
    _w1g2_until_asked(game)
    assert _w1g2_gate_prompt(game)[1] == ["Cavern Harpy"]


def test_w1g2_gating_does_not_target(set_pool):
    """"Return a red or green creature you control" names no target, so shroud
    is no answer to it: Elvish Lookout is offered and goes home."""
    game = _w1g2_duel(set_pool, ["Horned Kavu"], humans=(0,))
    lookout = _w1g2_put(game, set_pool, 0, "Elvish Lookout")
    assert game._has_keyword(lookout, "shroud")
    assert game.queue_from_hand(0, "Horned Kavu").supported
    _w1g2_until_asked(game)
    assert _w1g2_gate_prompt(game)[1] == ["Elvish Lookout", "Horned Kavu"]
    assert game.confirm_permanent_set_choice(0, [lookout.permanent_id])
    assert [c.name for c in game.players[0].hand] == ["Elvish Lookout"]
    assert _w1g2_names(game, 0) == ["Horned Kavu"]


def test_w1g2_a_gated_creature_goes_to_its_owners_hand(set_pool):
    """"…a creature **you control** to **its owner's** hand": a creature
    taken from the opponent is a legal answer and returns to the opponent."""
    game = _w1g2_duel(set_pool, ["Horned Kavu"], humans=(0,))
    stolen = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    _w1g2_change_control(stolen, 0, source="w1g2")
    assert game.controller_index_of(stolen) == 0
    assert game.queue_from_hand(0, "Horned Kavu").supported
    _w1g2_until_asked(game)
    assert game.confirm_permanent_set_choice(0, [stolen.permanent_id])
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]
    assert game.players[0].hand == []
    assert _w1g2_names(game, 0) == ["Horned Kavu"]


def test_w1g2_a_headless_gater_gives_back_its_cheapest_creature_not_its_best(set_pool):
    """A seat nobody asks used to give back whichever legal creature had been
    on the battlefield longest. Craw Wurm, then Llanowar Elves, then Horned
    Kavu: the Elves go home, not the Wurm — and not the Kavu, which is the
    answer that undoes the cast."""
    game = _w1g2_duel(set_pool, ["Horned Kavu"])
    _w1g2_put(game, set_pool, 0, "Craw Wurm")
    _w1g2_put(game, set_pool, 0, "Llanowar Elves")
    _w1g2_cast(game, "Horned Kavu")
    assert [c.name for c in game.players[0].hand] == ["Llanowar Elves"]
    assert _w1g2_names(game, 0) == ["Craw Wurm", "Horned Kavu"]


def test_w1g2_the_ai_holds_a_gater_it_could_only_return(set_pool):
    """Cast with no other red or green creature, Shivan Wurm returns itself
    and the seat has spent five mana on nothing — and proposes it again next
    turn. With one to give back that costs no more than the Wurm, it is cast;
    Horned Kavu is not cast to send a Shivan Wurm home."""
    five = ["Mountain"] * 3 + ["Forest"] * 2
    _game, alone = _w1g2_ai_table(set_pool, "Shivan Wurm", five)
    assert alone is None or alone.card_name != "Shivan Wurm"

    _game, beside_wrong = _w1g2_ai_table(
        set_pool, "Shivan Wurm", five, mine=["Savannah Lions"]
    )
    assert beside_wrong is None or beside_wrong.card_name != "Shivan Wurm"

    _game, with_elves = _w1g2_ai_table(
        set_pool, "Shivan Wurm", five, mine=["Llanowar Elves"]
    )
    assert with_elves.card_name == "Shivan Wurm"

    _game, trade_down = _w1g2_ai_table(
        set_pool, "Horned Kavu", five, mine=["Craw Wurm"]
    )
    assert trade_down is None or trade_down.card_name != "Horned Kavu"


def test_w1g2_cavern_harpy_pays_a_life_to_come_home(set_pool):
    """"Pay 1 life: Return this creature to its owner's hand." Flying, and an
    escape that costs life rather than mana."""
    game = _w1g2_duel(set_pool, [], pool={})
    _w1g2_put(game, set_pool, 0, "Black Knight")
    harpy = _w1g2_put(game, set_pool, 0, "Cavern Harpy")
    # The gate is a stack object (CR 603.3); it returns the Knight when it
    # resolves, not as the Harpy arrives.
    assert _w1g2_names(game, 0) == ["Black Knight", "Cavern Harpy"]
    _w1g2_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g2_names(game, 0) == ["Cavern Harpy"]
    assert game._has_keyword(harpy, "flying")

    assert game.activate_permanent_ability(0, "Cavern Harpy").supported
    _w1g2_resolve_stack(game)
    assert game.players[0].life == 19
    assert sorted(c.name for c in game.players[0].hand) == [
        "Black Knight", "Cavern Harpy",
    ]
    assert _w1g2_names(game, 0) == []


def test_w1g2_fleetfoot_panther_has_flash_and_the_others_do_not(set_pool):
    """Flash is what makes the Panther's gate a rescue: it may be cast any
    time its controller has priority, and the timing gate the web layer asks
    says so of it and of no other gater."""
    game = _w1g2_duel(set_pool, ["Fleetfoot Panther"])
    lions = _w1g2_put(game, set_pool, 0, "Savannah Lions")
    game.active_player_index = 1
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    for name, _one, _two in _W1G2_GATERS:
        assert _w1g2_instant_speed(set_pool("PLS")[name], game, 0) is (
            name == "Fleetfoot Panther"
        ), name

    panther = _w1g2_cast(game, "Fleetfoot Panther")
    assert (panther.effective_power, panther.effective_toughness) == (3, 4)
    assert [c.name for c in game.players[0].hand] == ["Savannah Lions"]
    assert not game.is_on_battlefield(lions)


def test_w1g2_lava_zombie_pumps_until_end_of_turn(set_pool):
    """"{2}: This creature gets +1/+0 until end of turn.\""""
    game = _w1g2_duel(set_pool, [])
    _w1g2_put(game, set_pool, 0, "Black Knight")
    zombie = _w1g2_put(game, set_pool, 0, "Lava Zombie")
    game.auto_resolve_pending_choices()
    before = _w1g2_floating(game)
    assert game.activate_permanent_ability(0, "Lava Zombie").supported
    _w1g2_resolve_stack(game)
    assert (zombie.effective_power, zombie.effective_toughness) == (5, 3)
    assert before - _w1g2_floating(game) == 2
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert (zombie.effective_power, zombie.effective_toughness) == (4, 3)


def test_w1g2_marsh_crocodile_makes_each_player_discard(set_pool):
    """Two entry triggers: the gate, and "each player discards a card" — each
    seat choosing its own.

    Two stack objects, resolved one at a time (CR 603.3): the gate is asked
    and answered before the discard begins, where the inline path ran the
    discard into the gate's unanswered prompt and asked all three at once."""
    game = _w1g2_duel(
        set_pool, ["Marsh Crocodile", "Forest", "Island"], humans=(0, 1),
        their_hand=["Grizzly Bears", "Forest"],
    )
    knight = _w1g2_put(game, set_pool, 0, "Black Knight")
    assert game.queue_from_hand(0, "Marsh Crocodile").supported
    _w1g2_until_asked(game)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("permanent_set_choice", 0),
    ]
    assert game.confirm_permanent_set_choice(0, [knight.permanent_id])
    assert "Black Knight" in [c.name for c in game.players[0].hand]
    _w1g2_until_asked(game)
    assert sorted((c.kind, c.player_index) for c in game.pending_choices) == [
        ("discard", 0), ("discard", 1),
    ]
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    assert _w1g2_names(game, 0) == ["Marsh Crocodile"]
    assert len(game.players[0].graveyard) == 1
    assert len(game.players[1].graveyard) == 1 and len(game.players[1].hand) == 1
    assert "Black Knight" in [c.name for c in game.players[0].hand]


def test_w1g2_razing_snidd_makes_each_player_sacrifice_a_land(set_pool):
    """"Each player sacrifices a land **of their choice**": a prompt for each
    seat, over that seat's own lands."""
    game = _w1g2_duel(set_pool, ["Razing Snidd"], humans=(0, 1))
    knight = _w1g2_put(game, set_pool, 0, "Black Knight")
    for seat in (0, 1):
        _w1g2_put(game, set_pool, seat, "Swamp")
        _w1g2_put(game, set_pool, seat, "Mountain")
    assert game.queue_from_hand(0, "Razing Snidd").supported
    # Two stack objects, one at a time (CR 603.3): the gate first, and only
    # once it is answered does the sacrifice ask anybody anything.
    _w1g2_until_asked(game)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("permanent_set_choice", 0),
    ]
    assert game.confirm_permanent_set_choice(0, [knight.permanent_id])
    _w1g2_until_asked(game)
    assert sorted((c.kind, c.player_index) for c in game.pending_choices) == [
        ("sacrifice", 0), ("sacrifice", 1),
    ]
    game.auto_resolve_pending_choices()
    _w1g2_resolve_stack(game)
    for seat in (0, 1):
        lands = [p for p in game.controlled_by(seat) if p.has_type("land")]
        assert len(lands) == 1, seat
        assert len([c for c in game.players[seat].graveyard if "Land" in c.type_line]) == 1
    snidd = next(p for p in game.controlled_by(0) if p.card.name == "Razing Snidd")
    assert (snidd.effective_power, snidd.effective_toughness) == (3, 3)


def test_w1g2_sparkcaster_pings_a_player_as_it_gates(set_pool):
    """"…it deals 1 damage to target player or planeswalker" beside the gate:
    the named player takes one, and the gate is still answered."""
    game = _w1g2_duel(set_pool, ["Sparkcaster"])
    _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    caster = _w1g2_cast(game, "Sparkcaster", target_player_index=1)
    assert [p.life for p in game.players] == [20, 19]
    assert (caster.effective_power, caster.effective_toughness) == (5, 3)
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]


@_w1g2_pytest.mark.parametrize("name,keyword,body", [
    ("Shivan Wurm", "trample", (7, 7)),
    ("Silver Drake", "flying", (3, 3)),
    ("Steel Leaf Paladin", "first strike", (4, 4)),
    ("Horned Kavu", None, (3, 4)),
])
def test_w1g2_a_gater_that_stays_is_the_printed_body(set_pool, name, keyword, body):
    """With another creature to give back, the gater stays: its printed body
    and its printed keyword, at a discount the returned creature paid for."""
    colours = next((one, two) for gater, one, two in _W1G2_GATERS if gater == name)
    game = _w1g2_duel(set_pool, [name])
    _w1g2_put(game, set_pool, 0, _W1G2_OF_COLOR[colours[0]])
    gater = _w1g2_cast(game, name)
    assert (gater.effective_power, gater.effective_toughness) == body
    if keyword is not None:
        assert game._has_keyword(gater, keyword)
    assert [c.name for c in game.players[0].hand] == [_W1G2_OF_COLOR[colours[0]]]


@_w1g2_pytest.mark.slow
def test_w1g2_the_ai_plays_gaters_without_bouncing_them_back(set_pool):
    """All ten pinned into both decks of six simulated games. Before this
    round 112 of 127 gating triggers returned the creature that had just been
    cast; now a gater is cast when there is something cheaper to give back,
    and none ever returns itself. (Floors well under today's seven cast and
    thirty-odd gates, for the Battlemage run's reason.)"""
    from engine.ai_simulator import run_ai_simulation

    names = [name for name, _one, _two in _W1G2_GATERS]
    report = run_ai_simulation(
        [_w1g2_manifest_set_path("PLS", include_measured=True)],
        games=6, seed=1337, max_turns=24, required_cards=names,
    )
    assert report.games_completed == 6
    cast = [
        name for name in names
        if any(f" cast {name} -> resolved" in line for line in report.log_lines)
    ]
    assert len(cast) >= 4, cast
    gated = [
        line for line in report.log_lines
        if " to hand" in line and any(f"{name} returned " in line for name in names)
    ]
    assert len(gated) >= 8
    undone = [
        line for line in gated
        if any(f"{name} returned {name} to hand" in line for name in names)
    ]
    assert undone == []
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [i.message for i in report.issues if any(n in i.message for n in names)] == []
    w1g2_gaters_left_nothing_owing = not report.steps_left_owing
    assert w1g2_gaters_left_nothing_owing, report.steps_left_owing
# end of the W1G2 creatures block


# --- W1G1: non-mana kicker ---
#
# "Kicker—Return a creature you control to its owner's hand." / "Kicker—Pay 3
# life." CR 702.33a: "Kicker [cost]" means "You may pay an additional [cost] as
# you cast this spell", and the cost need not be mana. Imports are in this
# block, per the header's parallel-authorship convention.

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import KICKED as _W1G1_KICKED
from engine.cast_costs import additional_costs as _w1g1_additional_costs
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_duel(set_pool, hand, pool=None):
    """A two-seat game that **charges mana**, seat 0 holding *hand* (PLS names)
    with *pool* floating. Costs are enforced because a kicker is a price: a rig
    that waives mana cannot tell a kicked cast from a free one."""
    pls = set_pool("PLS")
    forest = set_pool("LEA")["Forest"]
    mine = _W1G1PlayerState(
        "Kicker", library=[forest] * 10, hand=[pls[name] for name in hand],
    )
    theirs = _W1G1PlayerState("Bystander", library=[forest] * 10)
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH if pool is None else pool)
    return game  # _w1g1_duel (creatures)


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (creatures)


def _w1g1_floating(game) -> int:
    return sum(game.players[0].mana_pool.values())  # _w1g1_floating (creatures)


def _w1g1_named(game, seat, name):
    return next(
        (p for p in game.controlled_by(seat) if p.card.name == name), None
    )  # _w1g1_named (creatures)


def test_w1g1_a_kicker_line_behind_an_em_dash_is_one_optional_cost(set_pool):
    """The rewrite, and the one string it turns on. The key the announcement is
    accepted under, the key the payment charges by and the key `kicked` reads
    back are all the cost's own ``optional_key`` — two spellings of one cost is
    a spell that paid its kicker and resolved unkicked."""
    pls = set_pool("PLS")
    for name, key in (
        ("Arctic Merfolk", "return a creature you control to its owner's hand"),
        ("Phyrexian Scuta", "pay 3 life"),
    ):
        card = pls[name]
        (cost,) = _w1g1_additional_costs(card)
        assert cost.optional_key == key
        assert _w1g1_kicker_cost(card.oracle_text) == key
        assert not cost.optional_mana, "nothing here is folded into the mana"


def test_w1g1_arctic_merfolk_kicked_returns_the_creature_its_caster_names(set_pool):
    """Kicked: the creature the caster **names** goes back to its owner's hand
    as the spell is cast (a cost, CR 601.2h — before the Merfolk exists), and
    the Merfolk enters with a +1/+1 counter. Two creatures are on the table so
    that naming one means something."""
    card = set_pool("PLS")["Arctic Merfolk"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    lea = set_pool("LEA")
    kept = _w1g1_put(game, 0, lea["Grizzly Bears"])
    named = _w1g1_put(game, 0, lea["Hill Giant"])
    before = _w1g1_floating(game)

    result = game.queue_from_hand(
        0, "Arctic Merfolk", optional_cost_payments={key: 1},
        cost_permanent_ids=[named.permanent_id],
    )
    assert result.supported, result.details
    assert [c.name for c in game.players[0].hand] == ["Hill Giant"]
    assert _w1g1_named(game, 0, "Arctic Merfolk") is None, "still a spell"
    _w1g1_resolve_stack(game)

    merfolk = _w1g1_named(game, 0, "Arctic Merfolk")
    assert (merfolk.effective_power, merfolk.effective_toughness) == (2, 2)
    assert int(merfolk.metadata.get("plus_counters", 0)) == 1
    assert merfolk.metadata.get(_W1G1_KICKED)
    assert game.is_on_battlefield(kept)
    assert before - _w1g1_floating(game) == 2, "{1}{U} and no mana for the kicker"
    assert "Kicker kicked Arctic Merfolk" in game.log


def test_w1g1_arctic_merfolk_unkicked_is_a_one_one_and_returns_nothing(set_pool):
    """An offer is not a price (CR 601.2b): declined, the creature beside it
    stays and the Merfolk is the printed 1/1."""
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    assert game.cast_from_hand(0, "Arctic Merfolk").supported
    _w1g1_resolve_stack(game)

    merfolk = _w1g1_named(game, 0, "Arctic Merfolk")
    assert (merfolk.effective_power, merfolk.effective_toughness) == (1, 1)
    assert not merfolk.metadata.get(_W1G1_KICKED)
    assert game.is_on_battlefield(bears) and not game.players[0].hand


def test_w1g1_arctic_merfolk_cannot_be_kicked_with_no_creature_to_return(set_pool):
    """CR 601.2h: an unpayable cost is an uncastable spell, never a free kick —
    refused with the mana still floating and the card still in hand. And the
    offer the browser is shown says so (``max_times`` 0), from the same gate."""
    card = set_pool("PLS")["Arctic Merfolk"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    before = _w1g1_floating(game)

    [offer] = game.cast_cost_offers(0, card)
    assert (offer["label"], offer["symbols"], offer["max_times"]) == ("kicker", key, 0)
    refused = game.cast_from_hand(
        0, "Arctic Merfolk", optional_cost_payments={key: 1}
    )
    assert not refused.supported and "601.2h" in refused.details
    assert _w1g1_floating(game) == before
    assert [c.name for c in game.players[0].hand] == ["Arctic Merfolk"]

    _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    [offer] = game.cast_cost_offers(0, card)
    assert offer["max_times"] == 1


def test_w1g1_the_kicked_cast_asks_which_creature_and_the_plain_one_does_not(set_pool):
    """The picker (CR 601.2b): a kicked Arctic Merfolk raises a *return* cost
    picker over the caster's own creatures, and a declined kicker raises none —
    a caster who is not kicking must not be asked to name a creature."""
    card = set_pool("PLS")["Arctic Merfolk"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Arctic Merfolk"])
    bears = _w1g1_put(game, 0, set_pool("LEA")["Grizzly Bears"])
    _w1g1_put(game, 1, set_pool("LEA")["Hill Giant"])
    _w1g1_put(game, 0, set_pool("LEA")["Forest"])

    plain = game.cast_target_spec(0, card, optional_cost_payments={})
    assert plain["kind"] == "none" and not plain.get("return_cost")

    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    assert kicked["kind"] == "creature" and kicked["return_cost"]
    assert [
        game.permanent_at(t["seat"], t["index"]).permanent_id
        for t in kicked["valid_targets"]
    ] == [bears.permanent_id], "the caster's own creatures and nothing else"


def test_w1g1_phyrexian_scuta_kicked_pays_three_life_for_two_counters(set_pool):
    """"Kicker—Pay 3 life." A 3/3 for {3}{B}, or a 5/5 for {3}{B} and 3 life:
    real counters, the life paid as the spell is cast, and no extra mana."""
    card = set_pool("PLS")["Phyrexian Scuta"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Phyrexian Scuta"])
    before = _w1g1_floating(game)

    result = game.queue_from_hand(
        0, "Phyrexian Scuta", optional_cost_payments={key: 1}
    )
    assert result.supported, result.details
    assert game.players[0].life == 17, "paid on the way to the stack, not at resolution"
    _w1g1_resolve_stack(game)

    scuta = _w1g1_named(game, 0, "Phyrexian Scuta")
    assert (scuta.effective_power, scuta.effective_toughness) == (5, 5)
    assert int(scuta.metadata.get("plus_counters", 0)) == 2
    assert before - _w1g1_floating(game) == 4


def test_w1g1_phyrexian_scuta_unkicked_keeps_its_life_and_its_printed_body(set_pool):
    game = _w1g1_duel(set_pool, ["Phyrexian Scuta"])
    assert game.cast_from_hand(0, "Phyrexian Scuta").supported
    _w1g1_resolve_stack(game)
    scuta = _w1g1_named(game, 0, "Phyrexian Scuta")
    assert (scuta.effective_power, scuta.effective_toughness) == (3, 3)
    assert game.players[0].life == 20
    assert not scuta.metadata.get(_W1G1_KICKED)


def test_w1g1_phyrexian_scuta_cannot_be_kicked_with_two_life(set_pool):
    """CR 119.4: life can be paid only down to 0, so 2 life cannot pay 3 — and
    CR 601.2h makes that a refused cast with nothing spent. Three life can."""
    card = set_pool("PLS")["Phyrexian Scuta"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_duel(set_pool, ["Phyrexian Scuta"])
    game.players[0].life = 2
    before = _w1g1_floating(game)

    [offer] = game.cast_cost_offers(0, card)
    assert offer["max_times"] == 0
    refused = game.cast_from_hand(0, "Phyrexian Scuta", optional_cost_payments={key: 1})
    assert not refused.supported and "601.2h" in refused.details
    assert (game.players[0].life, _w1g1_floating(game)) == (2, before)

    game.players[0].life = 3
    assert game.queue_from_hand(
        0, "Phyrexian Scuta", optional_cost_payments={key: 1}
    ).supported
    assert game.players[0].life == 0


def test_w1g1_a_scuta_nothing_cast_was_not_kicked(set_pool):
    """Put onto the battlefield without being cast: no CR 601.2b, so no kicker
    and no counters, whatever its controller's life total could have paid."""
    game = _w1g1_duel(set_pool, [])
    scuta = _w1g1_put(game, 0, set_pool("PLS")["Phyrexian Scuta"])
    assert (scuta.effective_power, scuta.effective_toughness) == (3, 3)
    assert game.players[0].life == 20


def _w1g1_ai_board(set_pool, name, *, swamps, life=20):
    """Seat 0 on its own main phase holding *name*, with *swamps* untapped
    Swamps and an empty pool — the AI has to plan its own taps."""
    game = _w1g1_duel(set_pool, [name], pool={})
    for _ in range(swamps):
        _w1g1_put(game, 0, set_pool("LEA")["Swamp"])
    game.players[0].life = life
    game.active_player_index = 0
    game.current_phase = "main"
    return game  # _w1g1_ai_board (creatures)


def test_w1g1_the_ai_kicks_a_scuta_only_with_life_to_spare(set_pool):
    """The policy for a kicker that is not mana is the buyback one, by the
    *resource*: life is spent while the reserve still stands after it. At 20
    the seat kicks; at 12 it casts the plain 3/3 rather than drop to 9 — and
    it still casts, because declining an offer is not declining the spell."""
    card = set_pool("PLS")["Phyrexian Scuta"]
    key = _w1g1_kicker_cost(card.oracle_text)

    healthy = _w1g1_choose_cast_action(_w1g1_ai_board(set_pool, card.name, swamps=4), 0)
    assert healthy is not None and healthy.card_name == "Phyrexian Scuta"
    assert healthy.optional_cost_payments == {key: 1}

    hurt = _w1g1_choose_cast_action(
        _w1g1_ai_board(set_pool, card.name, swamps=4, life=12), 0
    )
    assert hurt is not None and hurt.card_name == "Phyrexian Scuta"
    assert not hurt.optional_cost_payments


# -- Dralnu's Pet: a kicker with two clauses, and a count read off the cost --


def _w1g1_pet_duel(set_pool, others, pool):
    """Seat 0 holds Dralnu's Pet and *others* (LEA names) with *pool* floating."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Dralnu's Pet"], pool=pool)
    game.players[0].hand.extend(lea[name] for name in others)
    return game  # _w1g1_pet_duel


_W1G1_PET_POOL = {"U": 10, "B": 10}


def test_w1g1_dralnus_pet_kicker_is_one_offer_of_mana_and_a_creature_card(set_pool):
    """"Kicker—{2}{B}, Discard a creature card." One offer with two clauses:
    the mana is a clause of the price, not a second offer a caster could take
    without the discard — so it is ``mana_symbols`` on the cost that carries
    the key, and ``optional_mana`` stays empty."""
    card = set_pool("PLS")["Dralnu's Pet"]
    (cost,) = _w1g1_additional_costs(card)
    assert cost.optional_key == _w1g1_kicker_cost(card.oracle_text)
    assert cost.mana_symbols == "{2}{B}" and cost.mana_cost == {"generic": 2, "B": 1}
    assert (cost.discard_cards, cost.discard_filters) == (1, ({"type_filter": "creature"},))
    assert not cost.optional_mana


def test_w1g1_dralnus_pet_kicked_flies_with_the_discarded_cards_mana_value(set_pool):
    """Kicked by discarding Hill Giant (mana value 4): six mana in all, the
    Giant in the graveyard — the card the caster **named**, with a cheaper
    creature card beside it — and a 6/6 flier with four real counters that
    still flies after the turn ends."""
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_pet_duel(
        set_pool, ["Lightning Bolt", "Grizzly Bears", "Hill Giant"], _W1G1_PET_POOL
    )

    result = game.queue_from_hand(
        0, "Dralnu's Pet", optional_cost_payments={key: 1}, cost_hand_index=3,
    )
    assert result.supported, result.details
    assert [c.name for c in game.players[0].graveyard] == ["Hill Giant"]
    _w1g1_resolve_stack(game)

    pet = _w1g1_named(game, 0, "Dralnu's Pet")
    assert (pet.effective_power, pet.effective_toughness) == (6, 6)
    assert int(pet.metadata.get("plus_counters", 0)) == 4
    assert game._has_keyword(pet, "flying")
    assert sum(_W1G1_PET_POOL.values()) - _w1g1_floating(game) == 6
    assert [c.name for c in game.players[0].hand] == ["Lightning Bolt", "Grizzly Bears"]

    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert game._has_keyword(pet, "flying"), "no duration: it lasts while the Pet does"
    assert "flying" not in {k.lower() for k in pet.card.keywords}, "a grant, not the card"


def test_w1g1_dralnus_pet_unkicked_is_a_two_two_that_does_not_fly(set_pool):
    """The word "flying" sits in a line about being kicked. An unkicked Pet
    must not have it (the failure Invasion's Faerie Squadron had), discards
    nothing and costs {1}{U}{U}."""
    game = _w1g1_pet_duel(set_pool, ["Hill Giant"], _W1G1_PET_POOL)
    assert game.cast_from_hand(0, "Dralnu's Pet").supported
    _w1g1_resolve_stack(game)

    pet = _w1g1_named(game, 0, "Dralnu's Pet")
    assert (pet.effective_power, pet.effective_toughness) == (2, 2)
    assert not game._has_keyword(pet, "flying")
    assert [c.name for c in game.players[0].hand] == ["Hill Giant"]
    assert sum(_W1G1_PET_POOL.values()) - _w1g1_floating(game) == 3

    put = _w1g1_put(game, 1, set_pool("PLS")["Dralnu's Pet"])
    assert (put.effective_power, put.effective_toughness) == (2, 2)
    assert not game._has_keyword(put, "flying"), "not cast, so not kicked"


def test_w1g1_dralnus_pet_kicked_with_a_free_creature_flies_and_gets_nothing(set_pool):
    """X is the discarded card's mana value, and 0 is a mana value: the Pet
    still flies (the keyword is not sized by X) and gets no counter."""
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_pet_duel(set_pool, [], _W1G1_PET_POOL)
    free = next(
        c for c in set_pool("ATQ").values()
        if c.primary_type == "creature" and not int(c.cmc)
    )
    game.players[0].hand.append(free)
    assert game.cast_from_hand(
        0, "Dralnu's Pet", optional_cost_payments={key: 1}
    ).supported
    _w1g1_resolve_stack(game)

    pet = _w1g1_named(game, 0, "Dralnu's Pet")
    assert (pet.effective_power, pet.effective_toughness) == (2, 2)
    assert game._has_keyword(pet, "flying")


def test_w1g1_dralnus_pets_kicker_is_all_or_nothing(set_pool):
    """Every way the price cannot be met is a refused cast with nothing spent
    and nothing discarded (CR 601.2h): no creature card to discard, a card
    named that is not one, the mana short, and the {B} missing."""
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    kick = {"optional_cost_payments": {key: 1}}

    no_creature = _w1g1_pet_duel(set_pool, ["Lightning Bolt"], _W1G1_PET_POOL)
    refused = no_creature.cast_from_hand(0, "Dralnu's Pet", **kick)
    assert not refused.supported and "601.2h" in refused.details

    wrong_card = _w1g1_pet_duel(
        set_pool, ["Lightning Bolt", "Hill Giant"], _W1G1_PET_POOL
    )
    assert not wrong_card.cast_from_hand(
        0, "Dralnu's Pet", cost_hand_index=1, **kick
    ).supported

    for pool in ({"U": 3}, {"U": 5, "G": 3}):
        short = _w1g1_pet_duel(set_pool, ["Hill Giant"], pool)
        assert not short.cast_from_hand(0, "Dralnu's Pet", **kick).supported
        assert sum(short.players[0].mana_pool.values()) == sum(pool.values())
        assert not short.players[0].graveyard, "the discard is not paid first"
        [offer] = short.cast_cost_offers(0, card, spell_hand_index=0)
        assert offer["max_times"] == 0, "nor is it offered"

    for game in (no_creature, wrong_card):
        assert not game.players[0].graveyard
        assert _w1g1_floating(game) == sum(_W1G1_PET_POOL.values())
        assert game.players[0].hand[0].name == "Dralnu's Pet"

    payable = _w1g1_pet_duel(set_pool, ["Hill Giant"], {"U": 5, "B": 1})
    [offer] = payable.cast_cost_offers(0, card, spell_hand_index=0)
    assert (offer["label"], offer["max_times"]) == ("kicker", 1)


def test_w1g1_the_kicked_pet_asks_which_creature_card_to_discard(set_pool):
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)
    game = _w1g1_pet_duel(
        set_pool, ["Lightning Bolt", "Grizzly Bears", "Hill Giant"], _W1G1_PET_POOL
    )
    plain = game.cast_target_spec(0, card, optional_cost_payments={})
    assert plain["kind"] == "none"
    kicked = game.cast_target_spec(0, card, optional_cost_payments={key: 1})
    assert kicked["discard_cost"] and kicked["kind"] == "hand_card"
    assert [t["name"] for t in kicked["valid_targets"]] == ["Grizzly Bears", "Hill Giant"]


def test_w1g1_the_ai_plans_the_pets_whole_price_or_declines_it(set_pool):
    """A hand big enough to spare a card (the buyback reserve) and six lands of
    the right colours: the AI kicks, and the lands it plans pay all six mana.
    With only Islands the {B} is not there, so it casts the plain Pet — never
    an announcement the engine then refuses."""
    lea = set_pool("LEA")
    card = set_pool("PLS")["Dralnu's Pet"]
    key = _w1g1_kicker_cost(card.oracle_text)

    def board(swamps):
        game = _w1g1_pet_duel(set_pool, ["Hill Giant"] + ["Forest"] * 9, {})
        for name, count in (("Island", 3), ("Swamp", swamps)):
            for _ in range(count):
                _w1g1_put(game, 0, lea[name])
        game.active_player_index = 0
        game.current_phase = "main"
        game.lands_played_this_turn[0] = 1
        return game

    kicked = _w1g1_choose_cast_action(board(3), 0)
    assert kicked.card_name == "Dralnu's Pet"
    assert kicked.optional_cost_payments == {key: 1}
    assert len(kicked.land_tap_indices) == 6

    plain = _w1g1_choose_cast_action(board(0), 0)
    assert plain.card_name == "Dralnu's Pet" and not plain.optional_cost_payments
    assert len(plain.land_tap_indices) == 3


# --- W1G3: revealed cards ---
# Choices made out of a hand. Doomsday Specter looks at the hand of the player
# it damaged — the seat the *damage* froze (CR 603.10), where every shipped
# printing of the sentence read a seat a cast or a target supplied. Sawtooth
# Loon is Brainstorm's put-back at the other end of the library, without the
# "in any order" rider CR 401.4 makes redundant.
from engine import Game as _W1G3Game
from engine import PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_creature_table(set_pool, mine=(), theirs=(), *, hands=(), seats=2):
    """Seat 0 controls *mine* and seat 1 *theirs*, put straight onto the
    battlefield with no entry trigger run; ``hands[seat]`` is each seat's hand.
    Seat 0 is interactive and it is seat 0's turn. Returns the game, a
    name -> card lookup, and both battlefields."""
    pools = [set_pool(code) for code in ("PLS", "LEA")]

    def w1g3_card(card_name):
        return next(pool[card_name] for pool in pools if card_name in pool)

    w1g3_players = []
    for seat in range(seats):
        names = (mine, theirs)[seat] if seat < 2 else ()
        held = hands[seat] if seat < len(hands) else ()
        w1g3_players.append(_W1G3PlayerState(
            name="ABC"[seat],
            battlefield=[_W1G3Permanent(card=w1g3_card(n)) for n in names],
            hand=[w1g3_card(n) for n in held],
            library=[w1g3_card("Forest")] * 6,
        ))
    w1g3_game = _W1G3Game(players=w1g3_players)
    w1g3_game.enforce_mana_costs = False
    w1g3_game.interactive_seats = {0}
    w1g3_game.start_turn(0)
    w1g3_game._sync_control()
    for w1g3_player in w1g3_players:
        for w1g3_perm in w1g3_player.battlefield:
            w1g3_perm.metadata["summoning_sickness_turn"] = -99
    return w1g3_game, w1g3_card, w1g3_players[0].battlefield, w1g3_players[1].battlefield  # _w1g3_creature_table


def _w1g3_attack(game, attacker, *, defender=None, pick=None, blocks=None):
    """Declare *attacker* at *defender* and run combat to its end, answering a
    ``revealed_hand_pick`` with hand slot *pick*. *blocks* maps a blocker's
    battlefield slot to the attacker's. Returns the prompts seen, as
    ``(kind, seat owing it, seat whose hand it is about)``."""
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    slot = next(
        index for index, perm in enumerate(game.players[0].battlefield)
        if perm is attacker
    )
    declared = game.declare_attackers(0, [slot], defending_player_index=defender)
    assert declared[0], declared
    w1g3_seen = []
    for _ in range(5):
        game.advance_combat_phase()
        if blocks and game.current_step == "declare_blockers":
            blocker_seat = 1 if defender is None else defender
            assert game.declare_blockers(blocker_seat, blocks)[0]
            blocks = None
        for _ in range(8):
            if game.pending_choices:
                choice = game.pending_choices[0]
                w1g3_seen.append(
                    (choice.kind, choice.player_index, choice.data.get("victim_index"))
                )
                if choice.kind == "revealed_hand_pick" and pick is not None:
                    assert game.confirm_revealed_hand_pick(0, hand_index=pick)
                else:
                    game.auto_resolve_pending_choices()
            elif game.stack:
                game.resolve_top_of_stack()
    return w1g3_seen  # _w1g3_attack


def test_w1g3_doomsday_specter_picks_a_card_out_of_the_damaged_players_hand(set_pool):
    """"Whenever this creature deals combat damage to a player, look at that
    player's hand and choose a card from it. The player discards that card."
    Three seats, and the Specter attacks the *far* one: C took the damage, so
    it is C's hand the Specter's controller chooses from — the Counterspell,
    slot 1 — and B, the first opponent, keeps their card."""
    game, _card, mine, _theirs = _w1g3_creature_table(
        set_pool, ["Doomsday Specter"], [],
        hands=([], ["Swamp"], ["Shivan Dragon", "Counterspell", "Forest"]), seats=3,
    )

    seen = _w1g3_attack(game, mine[0], defender=2, pick=1)

    assert seen == [("revealed_hand_pick", 0, 2)], seen
    assert [player.life for player in game.players] == [20, 20, 18]
    assert [card.name for card in game.players[2].graveyard] == ["Counterspell"]
    assert [card.name for card in game.players[2].hand] == ["Shivan Dragon", "Forest"]
    assert [card.name for card in game.players[1].hand] == ["Swamp"]
    # "Look at", not "reveals": the hand is shown to the chooser alone.
    assert any("C showed their hand (3 card(s)) to A" in line for line in game.log)


def test_w1g3_doomsday_specter_chooses_nothing_from_an_empty_hand(set_pool):
    """A hand with no card in it offers no choice: the damage is dealt, no
    prompt is armed and nothing is discarded."""
    game, _card, mine, _theirs = _w1g3_creature_table(
        set_pool, ["Doomsday Specter"], [], hands=([], []),
    )

    seen = _w1g3_attack(game, mine[0])

    assert seen == [], seen
    assert game.players[1].life == 18
    assert not game.players[1].graveyard and not game.stack


def test_w1g3_doomsday_specter_does_not_trigger_when_it_is_blocked(set_pool):
    """"…deals combat damage **to a player**": blocked by a flyer, its damage
    goes to the creature, so no hand is looked at and no card is discarded."""
    game, _card, mine, theirs = _w1g3_creature_table(
        set_pool, ["Doomsday Specter"], ["Air Elemental"],
        hands=([], ["Counterspell"]),
    )

    seen = _w1g3_attack(game, mine[0], pick=0, blocks={0: 0})

    assert seen == [], seen
    assert game.players[1].life == 20
    assert [card.name for card in game.players[1].hand] == ["Counterspell"]
    assert theirs[0].damage_marked == 2 or not game.is_on_battlefield(theirs[0])


def test_w1g3_doomsday_specter_is_gated_by_a_blue_or_black_creature(set_pool):
    """"When this creature enters, return a blue or black creature you control
    to its owner's hand." Cast for real: the red Hill Giant is not offered, the
    black Drudge Skeletons is, and the Specter stays."""
    game, card, mine, _theirs = _w1g3_creature_table(
        set_pool, ["Hill Giant", "Drudge Skeletons"], [],
        hands=(["Doomsday Specter"], []),
    )
    giant, skeletons = mine[0], mine[1]

    result = game.cast_from_hand(0, "Doomsday Specter")
    assert result.supported, result.details
    owed = next(c for c in game.pending_choices if c.kind == "permanent_set_choice")
    assert not game.confirm_permanent_set_choice(0, [game.permanent_id_of(giant)])
    assert game.confirm_permanent_set_choice(0, [game.permanent_id_of(skeletons)])
    _w1g3_resolve_stack(game)

    assert owed.player_index == 0
    assert sorted(perm.card.name for perm in game.controlled_by(0)) == [
        "Doomsday Specter", "Hill Giant",
    ]
    assert [held.name for held in game.players[0].hand] == ["Drudge Skeletons"]


def _w1g3_cast_loon(set_pool, hand, library):
    """Cast Sawtooth Loon from a hand of the Loon plus *hand*, over *library*
    (top first), answer its gating by returning the Loon itself — the only
    white or blue creature its controller has — and resolve its second entry
    trigger up to its question. Returns the game and seat 0.

    The two triggers are two stack objects (CR 603.3) and the first printed,
    the gate, resolves first and completely: the Loon is back in its owner's
    hand before "draw two cards, then put two cards from your hand on the
    bottom of your library" begins."""
    game, card, _mine, _theirs = _w1g3_creature_table(
        set_pool, [], [], hands=(["Sawtooth Loon", *hand], []),
    )
    player = game.players[0]
    player.library[:] = [card(name) for name in library]
    result = game.cast_from_hand(0, "Sawtooth Loon")
    assert result.supported, result.details
    gating = next(c for c in game.pending_choices if c.kind == "permanent_set_choice")
    loon = next(p for p in game.controlled_by(0) if p.card.name == "Sawtooth Loon")
    assert not any(c.kind == "hand_to_library" for c in game.pending_choices)
    assert game.resolve_pending_choice(
        gating.kind, 0, permanent_ids=[game.permanent_id_of(loon)]
    )
    assert "Sawtooth Loon" in [held.name for held in player.hand]
    assert game.resolve_top_of_stack(pause_for_choices=True)
    return game, player  # _w1g3_cast_loon


def test_w1g3_sawtooth_loon_draws_two_then_bottoms_two_in_the_order_named(set_pool):
    """"When this creature enters, draw two cards, then put two cards from your
    hand on the bottom of your library." Two are drawn first — the put-back is
    chosen out of the hand *with* them in it — and exactly two go down, in the
    order their owner names them (CR 401.4): the last named is the very bottom."""
    game, player = _w1g3_cast_loon(
        set_pool, ["Counterspell"], ["Island", "Swamp", "Plains", "Mountain"],
    )
    owed = next(c for c in game.pending_choices if c.kind == "hand_to_library")
    names = [card.name for card in player.hand]

    assert owed.data["count"] == 2 and owed.data["destination"] == "bottom"
    assert sorted(names) == [
        "Counterspell", "Island", "Sawtooth Loon", "Swamp",
    ], "two drawn, into a hand the gate has already returned the Loon to"
    assert not game.confirm_hand_to_library(0, [0]), "one card is not two"
    assert game.confirm_hand_to_library(
        0, [names.index("Swamp"), names.index("Counterspell")]
    )
    _w1g3_resolve_stack(game)

    assert [card.name for card in player.library] == [
        "Plains", "Mountain", "Swamp", "Counterspell",
    ]
    # The Island it drew and kept, and the Loon its own gating returned.
    assert sorted(card.name for card in player.hand) == ["Island", "Sawtooth Loon"]
    assert any("put 2 card(s) on the bottom" in line for line in game.log)


def test_w1g3_sawtooth_loon_bottoms_what_it_can_from_a_short_hand(set_pool):
    """CR 608.2's "as much as possible": an empty library draws nothing, the
    hand holds one card, and that one card is what goes to the bottom.

    The one card is the Loon itself — its gate resolved first and returned it,
    so it is in the hand the second trigger bottoms from."""
    game, player = _w1g3_cast_loon(set_pool, [], [])
    owed = next(c for c in game.pending_choices if c.kind == "hand_to_library")

    assert owed.data["count"] == 1
    assert game.confirm_hand_to_library(0, [0])
    _w1g3_resolve_stack(game)

    assert [card.name for card in player.library] == ["Sawtooth Loon"]
    assert player.hand == []


def _w1g3_lord_table(set_pool, mine_graveyard, *, interactive=(0, 1)):
    """Lord of the Undead for seat 0 with *mine_graveyard* behind it."""
    game, card, mine, _theirs = _w1g3_creature_table(set_pool, ["Lord of the Undead"], [])
    game.interactive_seats = set(interactive)
    game.players[0].graveyard.extend(card(name) for name in mine_graveyard)
    return game, game.players[0], mine[0]  # _w1g3_lord_table


def test_w1g3_lord_of_the_undead_pumps_every_other_zombie(set_pool):
    """"Other Zombie creatures get +1/+1." Every Zombie on every battlefield —
    an opponent's too — but not the Lord itself, and not a Bear."""
    game, _card, mine, theirs = _w1g3_creature_table(
        set_pool, ["Lord of the Undead", "Scathe Zombies", "Grizzly Bears"],
        ["Scathe Zombies"],
    )
    lord, zombie, bear = mine

    assert (lord.effective_power, lord.effective_toughness) == (2, 2)
    assert (zombie.effective_power, zombie.effective_toughness) == (3, 3)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert (theirs[0].effective_power, theirs[0].effective_toughness) == (3, 3)


def test_w1g3_lord_of_the_undead_returns_a_zombie_card_and_only_a_zombie(set_pool):
    """"{1}{B}, {T}: Return target **Zombie** card from your graveyard to your
    hand." A Bear is not a legal target and the activation is refused with the
    Lord untapped; the Maggot Carrier is, and comes back."""
    game, player, lord = _w1g3_lord_table(set_pool, ["Grizzly Bears", "Maggot Carrier"])

    refused = game.queue_permanent_ability(0, "Lord of the Undead", target_permanent_index=0)
    assert not refused.supported and not lord.tapped and not game.stack

    result = game.queue_permanent_ability(0, "Lord of the Undead", target_permanent_index=1)
    _w1g3_resolve_stack(game)

    assert result.supported and lord.tapped, result.details
    assert [card.name for card in player.hand] == ["Maggot Carrier"]
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]


def test_w1g3_lord_of_the_undead_never_falls_back_to_a_card_that_is_not_a_zombie(set_pool):
    """What driving it found. With no slot announced the handler's fallback took
    the first *creature* card in the pile — the Grizzly Bears lying ahead of the
    Zombie — because the generic scan reads no subtype. It takes the Zombie now;
    and with no Zombie in the pile the ability cannot be activated at all
    (CR 602.2b), rather than returning a Bear."""
    game, player, _lord = _w1g3_lord_table(set_pool, ["Grizzly Bears", "Maggot Carrier"])

    assert game.queue_permanent_ability(0, "Lord of the Undead").supported
    _w1g3_resolve_stack(game)

    assert [card.name for card in player.hand] == ["Maggot Carrier"]
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]

    game, player, lord = _w1g3_lord_table(set_pool, ["Grizzly Bears"])
    refused = game.queue_permanent_ability(0, "Lord of the Undead")
    assert not refused.supported and not lord.tapped
    assert not player.hand


def test_w1g3_lord_of_the_undead_returns_no_bystander_when_its_zombie_has_gone(set_pool):
    """The Zombie leaves the graveyard in response. The ability's only target is
    gone, and what is left in the pile is not a Zombie — so nothing comes back.
    It used to return the Grizzly Bears."""
    game, player, _lord = _w1g3_lord_table(set_pool, ["Grizzly Bears", "Maggot Carrier"])
    game.queue_permanent_ability(0, "Lord of the Undead", target_permanent_index=1)

    player.graveyard.pop(1)
    _w1g3_resolve_stack(game)

    assert not player.hand
    assert [card.name for card in player.graveyard] == ["Grizzly Bears"]


def test_w1g3_maggot_carrier_costs_every_player_a_life(set_pool):
    """"When this creature enters, each player loses 1 life." Cast for real at a
    three-seat table: its controller too, and both opponents."""
    game, _card, _mine, _theirs = _w1g3_creature_table(
        set_pool, [], [], hands=(["Maggot Carrier"],), seats=3,
    )

    result = game.cast_from_hand(0, "Maggot Carrier")
    _w1g3_resolve_stack(game)

    assert result.supported, result.details
    assert [player.life for player in game.players] == [19, 19, 19]
    assert [perm.card.name for perm in game.controlled_by(0)] == ["Maggot Carrier"]

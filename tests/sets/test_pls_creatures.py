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

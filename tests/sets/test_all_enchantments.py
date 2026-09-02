"""Per-card tests for Alliances' enchantments.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G3: Aura effect templates ---

from engine import Game, PlayerState
from engine.auras import attach_aura, aura_static_pt_grant, detach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec


def _w1g3_creature(name: str, power: int, toughness: int, colors=()):
    """A vanilla creature with a colour, which three of these cards read."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g3_board(set_pool, aura_name, *, host_colors=(), host_pt=(2, 2)):
    """An Aura attached to a creature, with a second creature beside it.

    Returns ``(game, host, other, aura)``. Seat 0 controls all of it, which is
    what the two activated abilities need; the tests that care about an
    opponent's creature build their own board.

    *host_pt* is a parameter because Phyrexian Boon's penalty arm is -1/-2: on a
    2/2 the state-based sweep kills the creature the moment the turn starts
    (CR 704.5a) and bins the Aura behind it (CR 704.5m), so the board under test
    would be empty before the test read it.
    """
    host = Permanent(card=_w1g3_creature("Host", *host_pt, host_colors))
    other = Permanent(card=_w1g3_creature("Other", 1, 1))
    aura = Permanent(card=set_pool("ALL")[aura_name])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[host, other, aura]),
        PlayerState(name="P1"),
    ])
    game.enforce_mana_costs = False
    attach_aura(aura, host)
    for permanent in (host, other):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, host, other, aura


def _w1g3_combat(set_pool, aura_name, *, on_blocker):
    """A declared block with *aura_name* attached to one side of it.

    ``on_blocker`` picks which half of a joined condition is under test: on the
    blocking creature the *blocks* half fires, on the attacking creature the
    *becomes blocked* half does. Returns ``(game, attacker, blocker, aura)``
    with the trigger already resolved.
    """
    attacker = Permanent(card=_w1g3_creature("Attacker", 2, 2))
    blocker = Permanent(card=_w1g3_creature("Blocker", 2, 2))
    aura = Permanent(card=set_pool("ALL")[aura_name])
    game = Game(players=[
        PlayerState(name="P0",
                    battlefield=[attacker] + ([] if on_blocker else [aura])),
        PlayerState(name="P1",
                    battlefield=[blocker] + ([aura] if on_blocker else [])),
    ])
    game.enforce_mana_costs = False
    attach_aura(aura, blocker if on_blocker else attacker)
    for permanent in (attacker, blocker):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack(pause_for_choices=True)
    return game, attacker, blocker, aura


# --- Phyrexian Boon --------------------------------------------------------
# "Enchanted creature gets +2/+1 as long as it's black. Otherwise, it gets
# -1/-2." Two continuous effects with complementary criteria, printed as two
# sentences on one line.


def test_phyrexian_boon_applies_the_arm_the_creatures_colour_selects(set_pool):
    """Both arms, on two boards that differ only in the host's colour.

    Testing one arm alone would pass on an implementation that applied it
    unconditionally, which is exactly what the reader did before the
    "Otherwise" sentence was parsed at all.
    """
    game, host, _other, _aura = _w1g3_board(
        set_pool, "Phyrexian Boon", host_colors=("B",), host_pt=(3, 3)
    )
    game._refresh_dynamic_creatures()
    assert (host.effective_power, host.effective_toughness) == (5, 4)

    game, host, _other, _aura = _w1g3_board(
        set_pool, "Phyrexian Boon", host_colors=("G",), host_pt=(3, 3)
    )
    game._refresh_dynamic_creatures()
    assert (host.effective_power, host.effective_toughness) == (2, 1)


def test_phyrexian_boon_swaps_arms_when_the_creature_changes_colour(set_pool):
    """CR 613.1: the criteria are re-asked on every recompute, so the arm that
    applies changes the moment the creature does — and nothing is left over from
    the arm that stopped applying."""
    game, host, _other, aura = _w1g3_board(
        set_pool, "Phyrexian Boon", host_colors=("G",), host_pt=(3, 3)
    )
    game._refresh_dynamic_creatures()
    assert (host.effective_power, host.effective_toughness) == (2, 1)

    host.metadata["color_override"] = ("B",)
    game._refresh_dynamic_creatures()
    assert (host.effective_power, host.effective_toughness) == (5, 4)

    detach_aura(aura, host)
    game._refresh_dynamic_creatures()
    assert (host.effective_power, host.effective_toughness) == (3, 3), (
        "neither arm survives the Aura leaving"
    )


def test_phyrexian_boon_lowers_one_instruction_carrying_both_arms(set_pool):
    """One ``conditional_static``, not two.

    A second instruction would be a second condition, asked separately and free
    to answer True alongside its own negation — and the compiler wraps a
    multi-instruction line in a ``sequence``, which every pass that scans
    ``prog.instructions`` for this kind would then look straight past.
    """
    program = compile_card_oracle(set_pool("ALL")["Phyrexian Boon"])
    assert program.supported, program.reason
    statics = [i for i in program.instructions if i.kind == "conditional_static"]
    assert len(statics) == 1
    payload = statics[0].payload
    assert payload["subject"] == "attached"
    assert payload["condition"] == {
        "kind": "attached_matches", "filter": {"color_filter": "B"}
    }
    assert (payload["power"], payload["toughness"]) == (2, 1)
    assert (payload["otherwise_power"], payload["otherwise_toughness"]) == (-1, -2)


# --- Bestial Fury and Gift of the Woods ------------------------------------
# The two block triggers watched by an Aura rather than by the creature itself.


def test_bestial_fury_pumps_and_grants_trample_when_its_host_is_blocked(set_pool):
    """"Whenever enchanted creature becomes blocked, it gets +4/+0 and gains
    trample until end of turn."

    "It" is the enchanted creature, not the Aura — an Aura that pumped itself
    would be a card doing nothing at all, and it is the same pronoun on both
    halves of the sentence.
    """
    game, attacker, _blocker, _aura = _w1g3_combat(
        set_pool, "Bestial Fury", on_blocker=False
    )
    assert (attacker.effective_power, attacker.effective_toughness) == (6, 2)
    assert game._has_keyword(attacker, "trample")


def test_bestial_fury_grants_nothing_before_the_block(set_pool):
    """The regression this card was found by.

    ``aura_static_pt_grant`` searched every line for "gets +N/+N", so the +4/+0
    printed *inside* the trigger's effect was also read as a permanent layer-7c
    grant: the creature got it on attach, kept it through the opponent's turn,
    and got a second +4/+0 on top when it was actually blocked. The trample half
    was correct, which is what made the whole thing invisible in a game.
    """
    assert aura_static_pt_grant(set_pool("ALL")["Bestial Fury"].oracle_text) is None

    game, host, _other, _aura = _w1g3_board(set_pool, "Bestial Fury")
    game._refresh_dynamic_creatures()
    assert (host.effective_power, host.effective_toughness) == (2, 2)
    assert not game._has_keyword(host, "trample")


def test_gift_of_the_woods_fires_on_either_side_of_the_block(set_pool):
    """"Whenever enchanted creature blocks or becomes blocked …" — one printed
    sentence naming two events (CR 509.1a and CR 509.3c), so the Aura fires
    whichever side of the block its host is on, and the life goes to *its*
    controller (CR 113.7a) rather than the creature's."""
    game, attacker, _blocker, _aura = _w1g3_combat(
        set_pool, "Gift of the Woods", on_blocker=False
    )
    assert (attacker.effective_power, attacker.effective_toughness) == (2, 5)
    assert [player.life for player in game.players] == [21, 20]

    game, _attacker, blocker, _aura = _w1g3_combat(
        set_pool, "Gift of the Woods", on_blocker=True
    )
    assert (blocker.effective_power, blocker.effective_toughness) == (2, 5)
    assert [player.life for player in game.players] == [20, 21]


def test_the_two_block_triggers_carry_the_attachment_narrowing(set_pool):
    """``combatant_attached`` is what sends the combat dispatchers to the
    combatant's *attachments* instead of to its own card. Without it the
    condition parses, the effect lowers, the card reports supported and no fire
    site ever looks at the Aura."""
    for name, kind in (
        ("Bestial Fury", "creature_becomes_blocked"),
        ("Gift of the Woods", "creature_blocks_or_blocked_by"),
    ):
        program = compile_card_oracle(set_pool("ALL")[name])
        assert program.supported, program.reason
        trigger = next(
            t for t in program.triggered_abilities if t.condition.kind == kind
        )
        assert trigger.condition.payload["combatant_attached"] == "creature"


# --- Veteran's Voice -------------------------------------------------------
# "Tap enchanted creature: Target creature other than the creature tapped this
# way gets +2/+1 until end of turn. Activate only if enchanted creature is
# untapped."


def _w1g3_picker(game, aura, index=0):
    """The candidates the activation picker offers for one ability."""
    ability = compile_card_oracle(aura.card).activated_abilities[index]
    spec = derive_activation_spec(ability)
    assert spec is not None, "an ability that targets must derive a picker"
    return [
        candidate["name"] for candidate in game._enumerate_targets(
            game.controller_index_of(aura), aura.effective_card, spec,
            for_cast=False, ability_instruction=ability.instruction,
            source_permanent=aura, ability_source=aura,
        )
    ]


def test_veterans_voice_never_offers_the_creature_its_cost_taps(set_pool):
    """"…other than the creature tapped this way".

    The referent is resolved to the attached host, and it has to be: CR 601.2h
    pays costs *after* targets are chosen, so at the moment the picker is built
    the cost-tap record is still empty. Reading the record here would offer the
    very creature the card excludes and then fizzle at resolution once the
    record had filled in — a picker and an enforcement disagreeing about one
    list.
    """
    game, _host, _other, aura = _w1g3_board(set_pool, "Veteran's Voice")
    assert _w1g3_picker(game, aura) == ["Other"]


def test_veterans_voice_taps_its_host_and_pumps_the_other_creature(set_pool):
    """The whole ability: the cost taps the host, the effect pumps somebody
    else, and the printed restriction refuses a second activation because the
    host is now tapped (CR 602.5)."""
    game, host, other, aura = _w1g3_board(set_pool, "Veteran's Voice")
    result = game.activate_permanent_ability(
        0, aura.card.name, target_player_index=0, ability_index=0,
        target_permanent_index=game.battlefield_index_of(other),
    )
    game.resolve_stack(pause_for_choices=True)
    assert result.details == "resolved"
    assert host.tapped, "the cost taps the enchanted creature"
    assert (other.effective_power, other.effective_toughness) == (3, 2)

    again = game.activate_permanent_ability(
        0, aura.card.name, target_player_index=0, ability_index=0,
        target_permanent_index=game.battlefield_index_of(other),
    )
    assert "not in that state" in (again.details or "")


# --- Nature's Chosen -------------------------------------------------------
# "Activate only if enchanted creature is white and untapped and only once each
# turn." Three conjuncts, and the colour is the one that had no reader.


def test_natures_chosen_enforces_the_colour_half_of_its_restriction(set_pool):
    """The clause conjoins a colour and a state with a plain "and", which the
    conjunct splitter does *not* cut on — so the colour is read by the one row
    that matches the sentence, or it is dropped. Dropped, the ability would work
    off a green creature the card never allows."""
    for colors, expected in ((("W",), True), (("G",), False)):
        game, _host, other, aura = _w1g3_board(
            set_pool, "Nature's Chosen", host_colors=colors
        )
        game.become_tapped(other)
        result = game.activate_permanent_ability(
            0, aura.card.name, target_player_index=0, ability_index=1,
            target_permanent_index=game.battlefield_index_of(other),
        )
        game.resolve_stack(pause_for_choices=True)
        assert (not other.tapped) is expected, (colors, result.details)


# --- Kjeldoran Pride -------------------------------------------------------
# "{2}{U}: Attach this Aura to target creature other than enchanted creature."


def test_kjeldoran_pride_moves_itself_and_takes_its_bonus_along(set_pool):
    """CR 701.3a's attach action, printed on an Aura rather than an Equipment.

    The +1/+2 is derived from the Aura's text on every recompute, so moving the
    Aura moves the bonus with nothing to subtract — the old host is back to what
    it was printed as.
    """
    game, host, other, aura = _w1g3_board(set_pool, "Kjeldoran Pride")
    game._refresh_dynamic_creatures()
    assert (host.effective_power, host.effective_toughness) == (3, 4)

    game.activate_permanent_ability(
        0, aura.card.name, target_player_index=0, ability_index=0,
        target_permanent_index=game.battlefield_index_of(other),
    )
    game.resolve_stack(pause_for_choices=True)
    assert aura.metadata.get("attached_to") is other
    assert (host.effective_power, host.effective_toughness) == (2, 2)
    assert (other.effective_power, other.effective_toughness) == (2, 3)


def test_kjeldoran_pride_never_offers_the_creature_it_already_enchants(set_pool):
    """"…other than enchanted creature". Not ``other_than_source``: the source
    is the Aura, and no creature is ever it, so that key would exclude nothing
    at all while reading as a restriction."""
    game, _host, _other, aura = _w1g3_board(set_pool, "Kjeldoran Pride")
    assert _w1g3_picker(game, aura) == ["Other"]


# --- False Demise ----------------------------------------------------------
# "When enchanted creature dies, return that card to the battlefield under your
# control."


def test_false_demise_returns_the_dead_creature_under_the_auras_controller(set_pool):
    """CR 400.3: "under your control" moves control and never ownership.

    Enchanting an *opponent's* creature is the case that tells a correct
    implementation from one that merely moves the card: the creature comes back
    on the Aura's controller's battlefield, still owned by the player whose
    graveyard it was in.
    """
    host = Permanent(card=_w1g3_creature("Victim", 2, 2))
    aura = Permanent(card=set_pool("ALL")["False Demise"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[aura]),
        PlayerState(name="P1", battlefield=[host]),
    ])
    attach_aura(aura, host)
    card = host.card

    game._destroy_target_permanent(game.players[1], type_filter="creature")
    game.check_state_based_actions()
    game.resolve_stack(pause_for_choices=True)

    returned = [p for p in game.players[0].battlefield if p.card is card]
    assert len(returned) == 1, "it comes back under the Aura's controller"
    assert returned[0].metadata.get("owner_player_index") == 1
    assert card not in game.players[1].graveyard
    assert not game.players[1].battlefield


def test_false_demise_deals_no_damage_of_creature_bonds(set_pool):
    """The standing regression for every "when enchanted creature dies" Aura:
    a dispatcher keyed on the *condition* once gave all of them Creature Bond's
    "damage equal to that creature's toughness"."""
    host = Permanent(card=_w1g3_creature("Victim", 2, 2))
    aura = Permanent(card=set_pool("ALL")["False Demise"])
    game = Game(players=[
        PlayerState(name="P0", battlefield=[aura]),
        PlayerState(name="P1", battlefield=[host]),
    ])
    attach_aura(aura, host)

    game._destroy_target_permanent(game.players[1], type_filter="creature")
    game.check_state_based_actions()
    game.resolve_stack(pause_for_choices=True)

    assert game.players[1].life == 20


# --- W1G2: library-top costs ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g2_card(name: str = "Deck Card") -> CardDefinition:
    """A vanilla card to stack a library with."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Artifact", oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Artifact"},
    )


def _w1g2_board(set_pool, name: str, library_size: int):
    perm = Permanent(card=set_pool("ALL")[name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=[_w1g2_card()] * library_size),
        PlayerState(name="P2", library=[_w1g2_card()] * 10),
    ])
    game.enforce_mana_costs = False
    return game, perm


def _w1g2_settle(game):
    while game.stack:
        game.resolve_top_of_stack()
    game.check_state_based_actions()


def test_thought_lash_cumulative_upkeep_exiles_more_each_turn(set_pool):
    """"Cumulative upkeep—Exile the top card of your library."

    CR 702.24a's cost is *any* cost, and "for each age counter on it" scales
    the whole of it — so the second upkeep exiles two cards and the third
    three. A cost read as mana-only would have made this permanent free
    forever.
    """
    game, lash = _w1g2_board(set_pool, "Thought Lash", 12)
    me = game.players[0]
    for expected in (1, 3, 6):
        game.start_turn(0)
        _w1g2_settle(game)
        assert len(me.exile) == expected
        assert game.is_on_battlefield(lash)
        game.start_turn(1)
        _w1g2_settle(game)


def test_thought_lash_unpaid_upkeep_exiles_the_whole_library(set_pool):
    """"When a player doesn't pay this enchantment's cumulative upkeep, that
    player exiles all cards from their library."

    The trigger's one fire site is the upkeep handler's non-payment branch —
    nothing on a board records who declined — and "that player" is the seat
    that event froze. The enchantment is sacrificed either way (CR 702.24a).
    """
    game, lash = _w1g2_board(set_pool, "Thought Lash", 8)
    me = game.players[0]
    game.start_turn(0)
    game.resolve_upkeep(0, human_choices={"Thought Lash": False})
    _w1g2_settle(game)
    assert not me.library, "the whole library went to exile"
    assert len(me.exile) == 8
    assert not game.is_on_battlefield(lash)


def test_thought_lash_with_an_empty_library_cannot_pay_its_upkeep(set_pool):
    """CR 118.3 in the upkeep's half of the engine: a library holding fewer
    cards than the cost names cannot pay it *fully*, so none of it is paid and
    CR 702.24a sacrifices the permanent."""
    game, lash = _w1g2_board(set_pool, "Thought Lash", 0)
    game.start_turn(0)
    _w1g2_settle(game)
    assert not game.is_on_battlefield(lash)


def test_thought_lash_prevention_ability_charges_its_library_cost(set_pool):
    """"Exile the top card of your library: Prevent the next 1 damage that
    would be dealt to you this turn."

    The third line, and the one with no mana in its cost at all.
    """
    game, _lash = _w1g2_board(set_pool, "Thought Lash", 4)
    me = game.players[0]
    assert game.activate_permanent_ability(0, "Thought Lash").supported
    assert len(me.library) == 3 and len(me.exile) == 1
    game.resolve_top_of_stack()
    assert me.damage_prevention_pool == 1


# --- W2G1: combat triggers and restrictions ---

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g1_presence_board(set_pool, blockers, lands):
    """An Elvish Ranger wearing Awesome Presence, attacking a defender holding
    *blockers* creatures and *lands* untapped mana lands."""
    pool = set_pool("ALL")
    attacker = Permanent(card=pool["Elvish Ranger"])
    aura = Permanent(card=pool["Awesome Presence"])
    defenders = [Permanent(card=pool["Elvish Ranger"]) for _ in range(blockers)]
    forests = [Permanent(card=pool["School of the Unseen"]) for _ in range(lands)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker, aura], life=20),
        PlayerState(name="P2", battlefield=defenders + forests, life=20),
    ])
    attach_aura(aura, attacker)
    game._settle()
    for perm in [attacker] + defenders:
        perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    ok, message = game.declare_blockers(1, {i: 0 for i in range(blockers)})
    return game, forests, ok, message


def test_awesome_presence_is_supported_through_the_aura_subject_rewrite(set_pool):
    """"Enchanted creature can't be blocked unless defending player pays {3} for
    each creature they control that's blocking it."

    One ``combat_restrictions.py`` row, reached the way Brainwash's
    pay-to-attack twin is: ``auras.aura_combat_restriction`` rewrites the
    printed subject and asks the same table, so the Aura and a creature
    printing the sentence about itself are one template.
    """
    from engine.auras import aura_combat_restriction

    card = set_pool("ALL")["Awesome Presence"]
    assert compile_card_oracle(card).supported

    restriction = aura_combat_restriction(card.oracle_text.splitlines()[1])
    assert restriction is not None
    assert restriction.kind == "cant_be_blocked_unless_pay"
    assert restriction.payload["mana"] == {"generic": 3}


@pytest.mark.parametrize(
    "blockers,lands,expected", [(1, 3, 3), (2, 6, 6)],
    ids=["one blocker costs {3}", "two blockers cost {6}"],
)
def test_awesome_presence_charges_three_per_blocker(
    set_pool, blockers, lands, expected
):
    """"...**for each creature they control that's blocking it**."

    No multiplier rides the payload: ``_block_mana_costs_of`` is asked once per
    (blocker, attacker) pair and ``_block_declaration_mana_plan`` sums the
    pairs (CR 509.1d), so a per-pair {3} already is {3} per blocking creature.
    Koskun Falls records the same argument on the attack side.
    """
    game, lands_on_board, ok, message = _w2g1_presence_board(
        set_pool, blockers, lands
    )

    assert ok, message
    assert sum(1 for land in lands_on_board if land.tapped) == expected


@pytest.mark.parametrize(
    "blockers,lands", [(1, 2), (2, 5)],
    ids=["one blocker, {2} available", "two blockers, {5} available"],
)
def test_awesome_presence_refuses_a_declaration_that_cannot_be_paid(
    set_pool, blockers, lands
):
    """CR 509.1b and 509.1f: partial payments are not allowed, so a defender who
    cannot cover the total has made an illegal declaration.

    **Nothing is rolled back, because nothing has happened yet** - CR 509.1g
    makes the chosen creatures blockers only *after* the cost is paid, which is
    why this needs no pending choice and no undo of a declared block.
    """
    game, lands_on_board, ok, _ = _w2g1_presence_board(set_pool, blockers, lands)

    assert not ok
    assert not any(land.tapped for land in lands_on_board), "nothing spent"


def test_awesome_presence_leaves_a_declined_block_free(set_pool):
    """CR 509.1c: the defender is never *required* to pay, because they are
    never required to block. Declaring none costs nothing."""
    game, lands_on_board, ok, message = _w2g1_presence_board(set_pool, 0, 3)

    assert ok, message
    assert not any(land.tapped for land in lands_on_board)
# --- end W2G1 ---


# --- W2G4: library and modal ---
"""Browse: an ordered look whose leftovers leave the game.

The template was already here — See the Truth and Diabolic Vision look at the
top N, take one and put the rest somewhere — and Browse differs in two printed
words: it runs the sentence on with a comma instead of a full stop, and it
**exiles** the rest instead of bottoming them. Both are read rather than
defaulted, and the second is the whole card: the pile shrinks every activation,
which is what makes a four-mana repeatable draw fair.
"""

from engine import Game, PlayerState
from engine.game_types import CardDefinition, Permanent


def _w2g4_card(name: str, type_line: str = "Artifact") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line},
    )


def _w2g4_browse(set_pool, library):
    p1 = PlayerState(name="P1", library=list(library))
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._put_permanent_onto_battlefield(
        0, Permanent(card=set_pool("ALL")["Browse"]), None
    )
    return game, p1


def test_w2g4_browse_takes_one_and_exiles_the_other_four(set_pool):
    """"…put one of them into your hand, and exile the rest." The rest leave
    the game; nothing goes back to the library."""
    deck = [_w2g4_card(f"Card {i}") for i in range(6)]
    game, me = _w2g4_browse(set_pool, deck)

    assert game.activate_permanent_ability(0, "Browse").supported
    assert [c.kind for c in game.pending_choices] == ["look_top_pick"]
    assert game.confirm_look_top_pick(0, 2)
    game._settle()

    assert [c.name for c in me.hand] == ["Card 2"]
    assert [c.name for c in me.exile] == [
        "Card 0", "Card 1", "Card 3", "Card 4",
    ]
    assert [c.name for c in me.library] == ["Card 5"]


def test_w2g4_browse_eats_its_own_library(set_pool):
    """The point of the exile, stated as a number: two activations move nine
    cards out of a ten-card library. Bottoming them instead would leave the
    library the same size forever, which is a different — and much stronger —
    card."""
    deck = [_w2g4_card(f"Card {i}") for i in range(10)]
    game, me = _w2g4_browse(set_pool, deck)

    for _ in range(2):
        assert game.activate_permanent_ability(0, "Browse").supported
        assert game.confirm_look_top_pick(0, 0)
        game._settle()

    assert len(me.hand) == 2
    assert len(me.exile) == 8
    assert len(me.library) == 0


def test_w2g4_browse_looks_at_what_is_left_when_the_library_is_short(set_pool):
    """CR 701.19-style "as many as you can": a library shorter than five is not
    an error, and the ability still resolves."""
    game, me = _w2g4_browse(set_pool, [_w2g4_card("Only Card")])

    assert game.activate_permanent_ability(0, "Browse").supported
    assert game.confirm_look_top_pick(0, 0)
    game._settle()

    assert [c.name for c in me.hand] == ["Only Card"]
    assert me.exile == []


# --- W2G5: damage, prevention and zones ---
#
# Two enchantments, both declined, both recorded as the pieces they need. The
# refusal *sites* on each are accurate and the layer each names is not the
# whole story, which is why the parts below are written out.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, trigger_condition_of_line

_W2G5E_POOLS: dict = {}


def _w2g5e_from(code: str, name: str) -> CardDefinition:
    if code not in _W2G5E_POOLS:
        _W2G5E_POOLS[code] = {
            card.name: card for card in load_cards(manifest_set_path(code))
        }
    return _W2G5E_POOLS[code][name]


def _w2g5e_ice(name: str) -> CardDefinition:
    return _w2g5e_from("ICE", name)


def _w2g5e_lea(name: str) -> CardDefinition:
    return _w2g5e_from("LEA", name)


def test_the_snow_land_tap_trigger_fires_end_to_end():
    """The three parts of Winter's Night this group *did* build, exercised on an
    invented card carrying only its first sentence — which is the check
    CLAUDE.md asks for when a shape has one printed instance: give the same text
    to a card the engine invents and watch the behaviour happen.

    A snow land tapped for mana adds its mana twice; an ordinary Forest adds it
    once. That covers the new condition row in ``engine/oracle.py``, the
    active-voice production in ``engine/grammar/triggers.py``, and the
    ``has_supertype`` test at the inline fire site (CR 605.4a) - three readers
    that all had to agree before anything could fire at all.
    """
    snow_forest = _w2g5e_ice("Snow-Covered Forest")
    card = CardDefinition(
        name="W2G5 Snow Test", mana_cost="{R}{G}{W}", cmc=3.0,
        type_line="World Enchantment",
        oracle_text=(
            "Whenever a player taps a snow land for mana, that player adds "
            "one mana of any type that land produced."
        ),
        colors=("R", "G", "W"), color_identity=("R", "G", "W"),
        keywords=(), produced_mana=(), raw={},
    )
    assert compile_card_oracle(card).supported

    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    for permanent in (
        Permanent(card=card),
        Permanent(card=snow_forest),
        Permanent(card=_w2g5e_lea("Forest")),
    ):
        game._put_permanent_onto_battlefield(0, permanent, None)

    assert game.tap_land_for_mana(0, "Snow-Covered Forest")
    assert game.players[0].mana_pool["G"] == 2, "the land's own mana, plus the trigger's"

    assert game.tap_land_for_mana(0, "Forest")
    assert game.players[0].mana_pool["G"] == 3, (
        "a land without the supertype is not one the trigger names"
    )


def test_winters_night_is_declined_naming_one_remaining_part(set_pool):
    """Its condition, its narrowing and its first sentence all work now (see
    the test above). What is left is the **second** sentence, and the blocker is
    not the sentence - it is where this trigger resolves.

    CR 605.4a keeps a triggered mana ability off the stack, so
    ``mixins/turn_management`` resolves this event *inline*, dispatching on
    ``trig.instruction.kind``. A two-sentence effect lowers to a ``sequence``,
    which that dispatch has no arm for - and ``lower.py``'s ``whole_effect``
    gate refuses the nested occurrence for exactly that reason rather than
    emitting a kind nothing would reach. So the remaining work is two pieces:

    1. **The inline fire site walking a ``sequence``.** Every other dispatcher
       in the engine reaches an instruction through ``EFFECT_HANDLERS``; this
       one reads the ability's whole instruction kind, so a composed effect is
       invisible to it. ``targeting._from_instructions`` already recurses into
       ``sequence`` steps for the picker, and this site wants the same shape.
    2. **A referent for the trigger's own land.** "**That land** doesn't untap
       during its controller's next untap step" names the event's subject - a
       sixth referent for ``_lower_doesnt_untap_next_step``, beside the fifth
       (``block_pair``, Labyrinth Minotaur) it already has and built the same
       way: a ``subject`` value the marker's handler resolves rather than a
       scratchpad record, because no step of this effect chose the land.

    The refusal is at least accurate now. Before this round the whole line fell
    past the trigger table into the *delayed*-ability production and refused
    with "this delayed ability states no duration" - a message about a
    mechanism the card does not use.
    """
    program = compile_card_oracle(set_pool("ALL")["Winter's Night"])

    assert not program.supported
    assert program.reason == "unsupported triggered ability"

    card = set_pool("ALL")["Winter's Night"]
    condition, _ = trigger_condition_of_line(card.oracle_text.split(chr(10))[0], card.name)
    assert condition is not None and condition.kind == "land_tapped_for_mana"
    assert condition.payload == {"tapped_land_supertype": "snow"}


def test_natures_blessing_is_declined_naming_two_parts(set_pool):
    """"{G}{W}, Discard a card: Put a +1/+1 counter on target creature **or**
    that creature gains banding, first strike, or trample. (This effect lasts
    indefinitely.)"

    Both halves of the ability already exist in isolation - the counter
    placement lowers, and each of the three keywords is in
    ``vocabulary.IMPLEMENTED_KEYWORDS``. Two parts are missing:

    1. **A modal written with "or" rather than "Choose one -".** The engine's
       modes come from bulleted lines (``OracleProgram.modes``); this is pre-
       Sixth-Edition templating that prints the alternatives inline, and the
       nested "banding, first strike, or trample" is a *second* choice inside
       the second mode, so the sentence offers four modes and not two.
    2. **A keyword grant with an indefinite duration (CR 611.2a).** "Target
       creature gains first strike." with no duration refuses today with
       "continuous keyword grant needs the CR 613 layers engine" - the grant
       kinds in the pool all end at a sweep (end of turn, end of combat), and
       an effect that lasts indefinitely has no sweep to end it and so must be
       a layer-6 contribution that outlives the resolution.
    """
    program = compile_card_oracle(set_pool("ALL")["Nature's Blessing"])
    assert not program.supported


# --- W2G3: upkeep and counters ---
#
# Splintering Wind: a token that carries printed abilities, one of them the
# cumulative upkeep that will kill it and fire the other.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W2G3_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g3_perm(card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w2g3_settle(game):
    game._settle()
    while game.stack:
        game.resolve_top_of_stack()
        game._settle()


def test_w2g3_splintering_wind_makes_a_token_that_carries_its_own_abilities(set_pool):
    """A Splinter token has flying, cumulative upkeep {G}, and a leaves-the-
    battlefield trigger - the last of them printed as an unquoted sentence after
    the token rather than inside the quotes, which is typography and not a
    difference in rules.

    The whole card is driven rather than read: the ability is activated, the
    token is made, its upkeep goes unpaid, and the trigger the sacrifice fires
    is the thing that proves the printed line reached the token at all.
    """
    wind = _w2g3_perm(set_pool("ALL")["Splintering Wind"])
    bear = _w2g3_perm(_W2G3_LEA["Grizzly Bears"])
    victim = _w2g3_perm(_W2G3_LEA["Hurloon Minotaur"])
    p1 = PlayerState(name="P1", battlefield=[wind, bear])
    p2 = PlayerState(name="P2", battlefield=[victim])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    assert game.activate_permanent_ability(
        0, "Splintering Wind", target_player_index=1, target_permanent_index=0
    ).supported
    _w2g3_settle(game)

    tokens = [perm for perm in p1.battlefield if perm.metadata.get("is_token")]
    assert len(tokens) == 1
    token = tokens[0]
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.has_keyword("flying")
    assert "Cumulative upkeep {G}" in token.card.oracle_text
    assert "leaves the battlefield" in token.card.oracle_text
    assert victim.damage_marked == 1

    p1.life = 20
    game.resolve_upkeep(0)
    _w2g3_settle(game)

    assert token not in p1.battlefield, "unpaid cumulative upkeep sacrifices it"
    assert p1.life == 19, "and its own trigger deals 1 to its controller"
    assert bear.damage_marked == 1, "and 1 to each creature they control"


def test_w2g3_splintering_wind_reads_every_line(set_pool):
    """The enchantment gate admits a permanent when *any* ability is
    implemented, so the whole activated line is asserted rather than the card's
    support flag: this one is a sentence for damage, a sentence for the token
    and two sentences of the token's own text."""
    program = compile_card_oracle(set_pool("ALL")["Splintering Wind"])
    assert program.supported
    assert len(program.activated_abilities) == 1
    ability = program.activated_abilities[0]
    assert ability.supported and ability.instruction is not None
    steps = ability.instruction.payload["steps"]
    kinds = [step.kind for step in steps]
    assert kinds == ["deal_damage", "create_token"]
    granted = steps[1].payload["oracle_text"].splitlines()
    assert granted == [
        "Cumulative upkeep {G}",
        "When this creature leaves the battlefield, it deals 1 damage to you "
        "and each creature you control.",
    ]

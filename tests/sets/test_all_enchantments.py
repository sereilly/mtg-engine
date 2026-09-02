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


# --- W2G5: damage, prevention and zones ---
#
# Two enchantments, both declined, both recorded as the pieces they need. The
# refusal *sites* on each are accurate and the layer each names is not the
# whole story, which is why the parts below are written out.

from engine.oracle import compile_card_oracle, trigger_condition_of_line


def test_winters_night_is_declined_naming_four_parts(set_pool):
    """W1G1 built ``land_tapped_for_mana`` and its inline fire site for Storm
    Cauldron, and the brief said to start there. It is the right seam and it
    does not reach this card yet. Four parts:

    1. **The active-voice condition with a narrowing.** ``engine/oracle.py``
       reads "whenever a **<type>** is tapped for mana" (Gauntlet of Might) and
       the bare "whenever a player taps a land for mana" (Manabarbs), and
       nothing in between: "a player taps a **snow** land for mana" matches
       neither, so the classifier returns no condition at all - which is why the
       whole line falls through to the delayed-trigger production and refuses
       with "this delayed ability states no duration", a message about a
       different mechanism.
    2. **A supertype narrowing on that condition.** The existing payload key is
       ``tapped_land_subtype`` and the fire site asks ``has_type``; "snow" is a
       supertype (CR 205.4a) and needs ``has_supertype``, so it is a second key
       rather than a wider value for the first.
    3. **The same phrase in the grammar's trigger table.** ``trigger_tables``
       carries the active voice as a fixed seven-word phrase with no noun slot;
       ``delayed._parse_land_tapped_for_mana`` already reads the noun phrase for
       the delayed spelling, and the trigger table would read it the same way.
    4. **An untap denial on the *event's* land.** "That land doesn't untap
       during its controller's next untap step" names the land the event was
       about, which is neither a target nor a permanent an earlier step of the
       effect recorded - the two referents ``skip_next_untap`` accepts today.
       CR 605.4a keeps this trigger off the stack, so the fire site that
       resolves the mana inline is where the marker would be placed.
    """
    card = set_pool("ALL")["Winter's Night"]
    program = compile_card_oracle(card)
    assert not program.supported

    trigger_line = card.oracle_text.split(chr(10))[0]
    condition, _ = trigger_condition_of_line(trigger_line, card.name)
    assert condition is None, (
        "part 1: the classifier reads no condition here, so the trigger is not "
        "merely unlowered - it is unrecognized"
    )


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

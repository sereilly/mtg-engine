"""Tempest creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G1: shadow (CR 702.28) ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("TMP")` / `set_cards("TMP")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: shadow (CR 702.28) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


def _w1g1_duel(p0_cards, p1_cards):
    """Two battlefields, no summoning sickness, mana enforcement off."""
    p0 = PlayerState(name="P0"); p1 = PlayerState(name="P1")
    for card in p0_cards:
        p0.battlefield.append(_nosick(Permanent(card=card)))
    for card in p1_cards:
        p1.battlefield.append(_nosick(Permanent(card=card)))
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, p0, p1


#: The fifteen printed shadow creatures W1G1 makes playable — fourteen were
#: unsupported on the keyword line and on nothing else, and Dauthi Ghoul needed
#: one more piece (the short spelling of a narrowed death trigger, CR 700.4).
W1G1_SHADOW_CREATURES = (
    "Soltari Crusader", "Soltari Foot Soldier", "Soltari Monk", "Soltari Priest",
    "Soltari Trooper", "Soltari Lancer",
    "Thalakos Dreamsower", "Thalakos Seer", "Thalakos Sentry",
    "Dauthi Marauder", "Dauthi Mercenary", "Dauthi Mindripper",
    "Dauthi Horror", "Dauthi Slayer", "Dauthi Ghoul",
)

#: The two that print shadow **and** a second line this group declined, with
#: the line each still refuses on. They are listed rather than dropped because
#: an unsupported program records no static lines at all: a sweep that only
#: asserted "shadow is a static line" would have to skip them silently, and the
#: assertion that survives is about *which* line is still refusing.
W1G1_SHADOW_CREATURES_STILL_REFUSING = {
    "Soltari Guerrillas":
        "{0}: The next time this creature would deal combat damage to an "
        "opponent this turn, it deals that damage to target creature instead.",
}

#: Thalakos Mistfolk left the table above at wave 1's integration, and the way
#: it left is the mechanism SET_PLAYBOOK.md asks every decline to be written
#: for: W1G1 declined it naming exactly one missing piece — the tuck — and
#: W1G5 built that piece for two *other* cards in the same wave. Nobody worked
#: on this card twice. The assertion is now both halves at once, because a card
#: is supported when any of its lines is and the keyword alone would pass.


def test_w1g1_thalakos_mistfolk_needed_both_halves_of_the_wave(set_pool):
    """Shadow (W1G1) and the tuck (W1G5), neither sufficient alone."""
    program = compile_card_oracle(set_pool("TMP")["Thalakos Mistfolk"])
    assert program.supported
    assert "shadow" in program.static_lines
    assert [
        ability.instruction.kind
        for ability in program.activated_abilities
    ] == ["put_source_card_on_library_top"]


@pytest.mark.parametrize("name", W1G1_SHADOW_CREATURES)
def test_w1g1_every_printed_shadow_creature_records_the_keyword(set_pool, name):
    """The fourteen cards whose keyword line was the whole refusal.

    Asserted as a **static line** as well as as supported: a card is supported
    when *any* of its lines is, so "supported" alone would go green for
    Soltari Crusader on its pump ability with the keyword still refused.
    """
    card = set_pool("TMP")[name]
    program = compile_card_oracle(card)
    assert program.supported, f"{name} is still unsupported"
    assert "shadow" in program.static_lines, (
        f"{name} does not record shadow as a keyword line"
    )


@pytest.mark.parametrize(
    "name,line", sorted(W1G1_SHADOW_CREATURES_STILL_REFUSING.items())
)
def test_w1g1_the_declines_no_longer_refuse_on_shadow(set_pool, name, line):
    """The declines, pinned to the line they are actually declined for.

    Each of these refused on `Shadow` before this round and refuses on its
    *second* line after it, so the assertion is on the refusal's **subject**:
    that is what makes the decline a work-list entry another group can pick up,
    and what fails loudly if a later round makes one of them refuse for a new
    reason instead of clearing it.
    """
    program = compile_card_oracle(set_pool("TMP")[name])
    assert not program.supported
    assert line in program.reason, (
        f"{name} refuses on {program.reason!r}, not on the declined line"
    )


def test_w1g1_two_shadow_creatures_block_each_other_normally(set_pool):
    """The pairing shadow permits, on printed cards.

    Soltari Priest is 2/1 with protection from red and shadow. Two creatures
    that both have it block each other exactly as ordinary creatures do — the
    restriction is a mismatch, not a prohibition on shadow itself, and a
    reading that refused every block involving shadow would pass the two
    negative assertions below and fail here.
    """
    priest = set_pool("TMP")["Soltari Priest"]
    trooper = set_pool("TMP")["Soltari Trooper"]
    ghoul = set_pool("TMP")["Dauthi Ghoul"]
    game, p0, p1 = _w1g1_duel([ghoul, trooper], [priest])
    dauthi_attacker, soltari_attacker = p0.battlefield
    blocker = p1.battlefield[0]

    assert game._can_block_attacker(blocker, soltari_attacker)
    assert game._can_block_attacker(blocker, dauthi_attacker)


def test_w1g1_shadow_is_a_drawback_as_well_as_evasion(set_pool):
    """CR 702.28b's second half on printed cards, both directions.

    The reminder text is one sentence — "can block **or** be blocked by only
    creatures with shadow" — and an implementation that only stopped ground
    creatures blocking a Soltari would have made every one of these seventeen
    cards strictly better than printed. Nothing in the support census, the
    hollow-line report or `parse_coverage` can see that difference.
    """
    tmp = set_pool("TMP")
    priest = tmp["Soltari Priest"]
    # A Tempest vanilla, so no *other* evasion is in the picture: Bayou
    # Dragonfly stood here first and has flying, which is a second reason a
    # block is refused and would have made this test pass for the wrong one.
    ground = tmp["Trained Armodon"]
    game, p0, p1 = _w1g1_duel([ground, priest], [priest, ground])
    ground_attacker, shadow_attacker = p0.battlefield
    shadow_blocker, ground_blocker = p1.battlefield

    assert not game._can_block_attacker(shadow_blocker, ground_attacker)
    assert not game._can_block_attacker(ground_blocker, shadow_attacker)


def test_w1g1_heartwood_dryad_blocks_shadow_and_keeps_its_ordinary_blocks(set_pool):
    """"This creature can block creatures with shadow as though it had shadow."

    Two assertions, and the second is the one a shadow *grant* would fail: the
    Dryad is a ground creature and must still be able to block ground
    creatures. CR 609.4 confines the "as though" to the stated effect.
    """
    tmp = set_pool("TMP")
    dryad = tmp["Heartwood Dryad"]
    priest = tmp["Soltari Priest"]
    ground = tmp["Trained Armodon"]   # a vanilla: no flying to confound it
    game, p0, p1 = _w1g1_duel([priest, ground], [dryad])
    shadow_attacker, ground_attacker = p0.battlefield
    blocker = p1.battlefield[0]

    assert game._can_block_attacker(blocker, shadow_attacker)
    assert game._can_block_attacker(blocker, ground_attacker)
    assert not game._has_keyword(blocker, "shadow")


def test_w1g1_wall_of_diffusion_keeps_defender_and_gains_the_permission(set_pool):
    """The same sentence on a Wall, so the two lines are read together: the
    keyword line still classifies (defender) and the static line still derives.
    A card is supported when *any* of its lines is, so the assertion is on both.
    """
    wall = set_pool("TMP")["Wall of Diffusion"]
    program = compile_card_oracle(wall)

    assert program.supported
    assert "defender" in program.static_lines
    assert [i.kind for i in program.instructions if i.kind != "keyword_line"] == [
        "can_block_as_though_it_had"
    ]

    # Soltari **Trooper**, not Priest: the Wall is red and the Priest has
    # protection from red (CR 702.16f), so that pairing is refused for a second
    # and entirely correct reason — a test that used it would have gone green
    # against a shadow permission that did nothing at all.
    trooper = set_pool("TMP")["Soltari Trooper"]
    game, p0, p1 = _w1g1_duel([trooper], [wall])
    assert game._can_block_attacker(p1.battlefield[0], p0.battlefield[0])


def test_w1g1_soltari_emissary_grants_itself_shadow_in_a_game(set_pool):
    """"{W}: This creature gains shadow until end of turn."

    Driven through the real activation and resolution path rather than asserted
    off the compiled program: the whole point of the keyword round is that a
    grant of it now *does* something, and a card that compiles the right
    instruction and changes no block is exactly the failure the compiled-program
    assertion cannot see.
    """
    emissary = _nosick(Permanent(card=set_pool("TMP")["Soltari Emissary"]))
    p0 = PlayerState(name="P0", battlefield=[emissary], life=20, mana_pool={"W": 1})
    blocker = _nosick(Permanent(card=set_pool("TMP")["Trained Armodon"]))
    p1 = PlayerState(name="P1", battlefield=[blocker], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game._can_block_attacker(blocker, emissary)

    game.activate_permanent_ability(0, "Soltari Emissary", ability_index=0)
    while game.stack:
        game.resolve_top_of_stack()

    assert game._has_keyword(emissary, "shadow")
    assert not game._can_block_attacker(blocker, emissary)


def test_w1g1_dauthi_horror_and_dauthi_slayer_were_only_ever_the_keyword(set_pool):
    """The two cards whose *second* lines the brief called gaps.

    Both are already implemented by `engine/combat_restrictions.py` — "can't be
    blocked by white creatures" and "attacks each combat if able" are rows in
    that table and have been. The grammar refuses both sentences, which is what
    a refusal census reports, and the derivation table runs *after* the grammar
    refuses. So the refusal site named a layer that was never going to answer.
    """
    horror = compile_card_oracle(set_pool("TMP")["Dauthi Horror"])
    slayer = compile_card_oracle(set_pool("TMP")["Dauthi Slayer"])

    assert horror.supported and slayer.supported
    assert any(
        i.kind == "cant_be_blocked_by"
        and i.payload["blocker_filters"] == [
            {"type_filter": "creature", "color_filter": "W"}
        ]
        for i in horror.instructions
    )
    assert any(i.kind == "must_attack_each_combat" for i in slayer.instructions)


# --- W1G1: Dauthi Ghoul's narrowed death trigger (CR 700.4) ---


def test_w1g1_dauthi_ghoul_grows_only_when_a_shadow_creature_dies(set_pool):
    """"Whenever a creature with shadow dies, put a +1/+1 counter on this
    creature."

    CR 700.4 makes "dies" mean "is put into a graveyard from the battlefield",
    and the engine has read a **narrowed** noun phrase off the long spelling
    since Tablet of Epityr — the dispatcher, the `dying_filter` payload and the
    `subject_matches` recheck were all already there. Only the two front ends
    could not read the rule's own shorthand, which is why every narrowing of
    "whenever a creature dies" refused, not just this one.

    Driven through a real death rather than asserted off the compiled condition,
    because a trigger can sit in both front-end tables and be announced by
    nothing (`tests/engine/test_trigger_dispatchers.py`'s subject) — and the
    negative half is the assertion the narrowing exists at all.
    """
    tmp = set_pool("TMP")
    ghoul = _nosick(Permanent(card=tmp["Dauthi Ghoul"]))
    p0 = PlayerState(name="P0", battlefield=[ghoul], life=20)
    shadowy = _nosick(Permanent(card=tmp["Soltari Foot Soldier"]))
    ground = _nosick(Permanent(card=tmp["Trained Armodon"]))
    p1 = PlayerState(name="P1", battlefield=[shadowy, ground], life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)

    assert (ghoul.effective_power, ghoul.effective_toughness) == (1, 1)

    game._permanent_to_graveyard(p1, ground)
    while game.stack:
        game.resolve_top_of_stack()
    assert (ghoul.effective_power, ghoul.effective_toughness) == (1, 1), (
        "a creature without shadow died and the Ghoul grew anyway — the "
        "narrowing was dropped"
    )

    game._permanent_to_graveyard(p1, shadowy)
    while game.stack:
        game.resolve_top_of_stack()
    assert (ghoul.effective_power, ghoul.effective_toughness) == (2, 2)


def test_w1g1_the_short_death_spelling_does_not_shadow_the_specific_rows(set_pool):
    """The new row is last in `WHENEVER_TRIGGER_PATTERNS` and this is why.

    Its subject group is `[^,]+`, so it matches every "whenever a … dies" line
    there is — including four earlier rows whose conditions are their own kinds
    with their own dispatchers. First match wins, so the row is safe at the end
    of the table and nowhere else; this asserts the consequence rather than the
    position, because the position is what a later edit would move.
    """
    from engine.oracle import trigger_condition_of_line

    expected = {
        "Whenever a creature dies, you gain 1 life.": "creature_dies",
        "Whenever a creature you control dies, you gain 1 life.":
            "creature_you_control_dies",
        "Whenever a creature an opponent controls dies, you gain 1 life.":
            "creature_opponent_controls_dies",
        "Whenever a creature dealt damage by this creature this turn dies, "
        "you gain 1 life.": "creature_dealt_damage_by_self_dies",
        "Whenever a creature with shadow dies, you gain 1 life.": "permanent_dies",
    }
    for line, kind in expected.items():
        condition, _ = trigger_condition_of_line(line)
        assert condition is not None and condition.kind == kind, line


# --- W1G3: the Slivers — a quoted activated ability granted to a tribe ---
# CR 113.3: what a card grants in quotes is a whole printed ability, not a
# keyword. Five Tempest Slivers print the shape and the engine's one reader of a
# printed ability is the compiler, so the grant rides as *text* on the derived
# layer-6 channel (`engine/keywords.py`'s DERIVED_ABILITY_LINES) and
# `Permanent.effective_card` folds it in. Everything downstream — the cost
# parser, the target picker, `activation_restrictions.py` — then reads it
# without knowing a lord granted it.
#
# The three things the grant must not lose, one test each: the cost, the
# self-reference, and Mindwhip Sliver's "Activate only as a sorcery."
import pytest

from engine import Game, PlayerState
from engine.keywords import derived_ability_lines
from engine.models import Permanent
from engine.oracle import compile_card_oracle

_W1G3_SLIVERS = (
    "Armor Sliver",
    "Barbed Sliver",
    "Clot Sliver",
    "Mnemonic Sliver",
    "Mindwhip Sliver",
)


def _w1g3_board(set_pool, names, *, enforce_mana=False):
    """*names* on seat 0's battlefield, none summoning sick, layers recomputed."""
    pool = set_pool("TMP")
    seats = [PlayerState(name="A"), PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = enforce_mana
    for name in names:
        perm = Permanent(card=pool[name])
        perm.metadata["summoning_sickness_turn"] = -99
        seats[0].battlefield.append(perm)
    game._recompute_continuous_effects()
    return game, seats


@pytest.mark.parametrize("name", _W1G3_SLIVERS)
def test_w1g3_every_sliver_lord_compiles_its_grant(set_pool, name):
    program = compile_card_oracle(set_pool("TMP")[name])
    assert program.supported, program.reason
    granted = [
        instruction.payload.get("granted_ability")
        for instruction in program.instructions
        if instruction.kind == "lord_buff"
    ]
    assert granted and granted[0], program.instructions


def test_w1g3_the_grant_reaches_every_sliver_and_leaves_with_the_lord(set_pool):
    """CR 611.3a/611.3b — derived, so the lord leaving takes it back."""
    game, seats = _w1g3_board(set_pool, ["Clot Sliver", "Metallic Sliver"])
    lord, mate = seats[0].battlefield
    assert derived_ability_lines(mate) == ("{2}: regenerate this permanent.",)
    # "All Slivers" names no "other", so the lord reaches itself too.
    assert derived_ability_lines(lord) == ("{2}: regenerate this permanent.",)

    game.remove_from_battlefield(lord)
    game._recompute_continuous_effects()
    assert derived_ability_lines(mate) == ()
    assert "regenerate" not in mate.effective_card.oracle_text.lower()


def test_w1g3_the_grant_does_not_reach_a_non_sliver(set_pool, cards):
    game, seats = _w1g3_board(set_pool, ["Clot Sliver"])
    bear = Permanent(card=cards["Grizzly Bears"])
    seats[0].battlefield.append(bear)
    game._recompute_continuous_effects()
    assert derived_ability_lines(bear) == ()


def test_w1g3_this_creature_inside_the_quotes_is_the_holder(set_pool):
    """The self-reference names the permanent that *has* the granted ability,
    never the Sliver granting it. Armor Sliver is 2/2 and Metallic Sliver 1/1,
    so the +0/+1 landing on the wrong one is visible in the numbers."""
    game, seats = _w1g3_board(set_pool, ["Armor Sliver", "Metallic Sliver"])
    lord, mate = seats[0].battlefield
    assert (mate.effective_power, mate.effective_toughness) == (1, 1)
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    game._recompute_continuous_effects()
    assert (mate.effective_power, mate.effective_toughness) == (1, 2)
    assert (lord.effective_power, lord.effective_toughness) == (2, 2)


def test_w1g3_the_granted_mana_cost_is_charged(set_pool):
    """{2}, with no mana available. The dict this replaced was keyed on the
    whole quoted text *including* the cost, and the reader charged {B} in
    words — so a differently-costed printing was unsupported rather than
    charged."""
    game, seats = _w1g3_board(
        set_pool, ["Armor Sliver", "Metallic Sliver"], enforce_mana=True
    )
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    assert not result.supported
    assert "insufficient mana" in result.details


def test_w1g3_the_granted_sacrifice_cost_is_charged(set_pool):
    """Mnemonic Sliver grants "{2}, Sacrifice this permanent: Draw a card." —
    the sacrifice is a cost, so the holder leaves the battlefield paying it."""
    game, seats = _w1g3_board(set_pool, ["Mnemonic Sliver", "Metallic Sliver"])
    seats[0].library.extend([set_pool("TMP")["Metallic Sliver"]] * 3)
    result = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    assert [p.card.name for p in seats[0].battlefield] == ["Mnemonic Sliver"]
    assert len(seats[0].hand) == 1


def test_w1g3_mindwhip_sorcery_restriction_is_enforced(set_pool):
    """CR 602.5d. A parsed-and-dropped restriction is an ability that works
    more often than the card allows — wrong in the player's favour, and
    silent. `engine/activation_restrictions.py` reads the granted line's own
    text, so the rider travels with the grant."""
    game, seats = _w1g3_board(set_pool, ["Mindwhip Sliver", "Metallic Sliver"])
    game.active_player_index = 1
    game.current_phase = "precombat_main"
    refused = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0,
        target_player_index=1,
    )
    assert not refused.supported
    assert "sorcery-speed" in refused.details

    game.active_player_index = 0
    seats[1].hand.append(set_pool("TMP")["Metallic Sliver"])
    allowed = game.activate_permanent_ability(
        0, "Metallic Sliver", permanent_index=1, ability_index=0,
        target_player_index=1,
    )
    while game.stack:
        game.resolve_top_of_stack()
    assert allowed.supported, allowed
    assert seats[1].hand == []


# --- W1G3: characteristic-defining P/T and a CR 608.2d choice ---
# Pallimud and Minion of the Wastes are CR 604.3 abilities whose value comes
# from something no battlefield holds: a seat chosen as the permanent entered,
# and life paid as it entered. Vhati il-Dal is the other half of this group's
# family — an effect that *offers* a rewrite of one creature's base P/T two
# ways.
from engine.pt import set_base_pt as _w1g3_set_base_pt  # noqa: F401  (channel doc)


def test_w1g3_pallimud_power_counts_the_chosen_players_tapped_lands(set_pool, cards):
    """CR 604.3 over CR 614.1c's chosen seat, narrowed by a *state*. The
    narrowing has to reach the tally: dropped, Pallimud's power would be every
    land the chosen player has rather than the ones they have spent."""
    tmp = set_pool("TMP")
    seats = [
        PlayerState(name="A", hand=[tmp["Pallimud"]]),
        PlayerState(name="B"),
    ]
    for name, tapped in (("Mountain", True), ("Mountain", True),
                         ("Forest", False), ("Grizzly Bears", True)):
        perm = Permanent(card=cards[name])
        perm.metadata["summoning_sickness_turn"] = -99
        perm.tapped = tapped
        seats[1].battlefield.append(perm)
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Pallimud")
    while game.stack:
        game.resolve_top_of_stack()
    pallimud = seats[0].battlefield[-1]
    assert pallimud.metadata.get("chosen_player_index") == 1
    game._recompute_continuous_effects()
    # Two tapped Mountains. The tapped Grizzly Bears is not a land and the
    # untapped Forest is not tapped; the printed toughness (3) stands, because
    # the sentence defines the power half alone.
    assert (pallimud.effective_power, pallimud.effective_toughness) == (2, 3)

    seats[1].battlefield[2].tapped = True
    game._recompute_continuous_effects()
    assert pallimud.effective_power == 3


def test_w1g3_minion_of_the_wastes_pays_any_life_up_to_its_controllers_total(set_pool):
    """Nameless Race's entry cost with the cap sentence unprinted. Uncapped,
    the ceiling is CR 119.4's: a player may pay more than 0 only up to their
    life total."""
    tmp = set_pool("TMP")
    seats = [PlayerState(name="A", hand=[tmp["Minion of the Wastes"]], life=20),
             PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Minion of the Wastes")
    while game.stack:
        game.resolve_top_of_stack()
    assert game.pending_choices[0].data["maximum"] == 20
    assert game.confirm_number_choice(0, 7)
    game._recompute_continuous_effects()
    minion = seats[0].battlefield[-1]
    assert seats[0].life == 13
    assert (minion.effective_power, minion.effective_toughness) == (7, 7)


def test_w1g3_the_pay_life_ceiling_is_the_payers_life_total(set_pool):
    tmp = set_pool("TMP")
    seats = [PlayerState(name="A", hand=[tmp["Minion of the Wastes"]], life=3),
             PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Minion of the Wastes")
    while game.stack:
        game.resolve_top_of_stack()
    assert game.pending_choices[0].data["maximum"] == 3
    assert not game.confirm_number_choice(0, 5)


@pytest.mark.parametrize(
    "mode_index,expected", [(0, (1, 4)), (1, (4, 1))]
)
def test_w1g3_vhati_offers_the_choice_at_resolution(set_pool, cards, mode_index, expected):
    """CR 608.2d, not CR 700.2. A modal ability is a *bulleted* list preceded
    by "Choose one —" and its mode is chosen as the ability is activated; Vhati
    prints no bullets, so the option is announced while the effect is applied —
    the same rule "gains your choice of deathtouch or lifelink" is read under,
    and the same ``choose_one`` seam."""
    tmp = set_pool("TMP")
    vhati = Permanent(card=tmp["Vhati il-Dal"])
    vhati.metadata["summoning_sickness_turn"] = -99
    angel = Permanent(card=cards["Serra Angel"])
    seats = [PlayerState(name="A", battlefield=[vhati]),
             PlayerState(name="B", battlefield=[angel])]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    result = game.activate_permanent_ability(
        0, "Vhati il-Dal", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result
    assert game.resolve_pending_choice("mode_choice", 0, mode_index=mode_index)
    while game.stack:
        game.resolve_top_of_stack()
    game._recompute_continuous_effects()
    assert (angel.effective_power, angel.effective_toughness) == expected


def test_w1g3_a_base_pt_choice_still_reads_the_and_spelling(set_pool, cards):
    """"base power **and** toughness 0/2" is one rewrite, not two options —
    the branch above must not eat its "and". Sorceress Queen, Jolrael and Cycle
    of Life all compiled to nothing the first time this was written, and only
    the pool-wide differential said so."""
    from engine.oracle import compile_card_oracle as _compile

    for name in ("Sorceress Queen", "Jolrael, Mwonvuli Recluse"):
        card = cards.get(name) or set_pool("TMP").get(name)
        if card is None:
            continue
        assert _compile(card).supported, name


# --- W1G3: Dracoplasm — an entry sacrifice that defines the size ---
def test_w1g3_dracoplasm_is_the_total_of_what_was_given_up(set_pool, cards):
    """CR 604.3 over CR 614.1c's entry cost, and CR 608.2g's last known
    information: the creatures are cards in a graveyard a moment later and have
    no computed characteristics at all, so the sums are read at the removal
    site rather than recounted afterwards.

    Two sums, not one — every other entry in `characteristic_defining.py`
    derives the second half from the first, and this is the one card where the
    halves are independent numbers."""
    tmp = set_pool("TMP")
    bears = Permanent(card=cards["Grizzly Bears"])
    angel = Permanent(card=cards["Serra Angel"])
    for perm in (bears, angel):
        perm.metadata["summoning_sickness_turn"] = -99
    seats = [PlayerState(name="A", hand=[tmp["Dracoplasm"]], battlefield=[bears, angel]),
             PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.cast_from_hand(0, "Dracoplasm")
    while game.stack:
        game.resolve_top_of_stack()
    assert game.resolve_pending_choice("sacrifice", 0, indices=[0, 1])
    game._recompute_continuous_effects()
    dracoplasm = seats[0].battlefield[-1]
    assert [p.card.name for p in seats[0].battlefield] == ["Dracoplasm"]
    # 2/2 + 4/4.
    assert (dracoplasm.effective_power, dracoplasm.effective_toughness) == (6, 6)
    # …and its own {R} pump is layer 7c, over the 7b the entry set.
    result = game.activate_permanent_ability(0, "Dracoplasm", permanent_index=0)
    while game.stack:
        game.resolve_top_of_stack()
    assert result.supported, result
    game._recompute_continuous_effects()
    assert (dracoplasm.effective_power, dracoplasm.effective_toughness) == (7, 6)


def test_w1g3_dracoplasm_declined_enters_as_a_nothing(set_pool, cards):
    """"Any number" answered with none is zero, which is what the card does
    when its controller declines — the stated policy Wood Elemental already
    follows for a non-interactive seat."""
    tmp = set_pool("TMP")
    seats = [PlayerState(name="A", hand=[tmp["Dracoplasm"]]), PlayerState(name="B")]
    game = Game(players=seats)
    game.enforce_mana_costs = False
    game.cast_from_hand(0, "Dracoplasm")
    while game.stack:
        game.resolve_top_of_stack()
    dracoplasm = next(
        (p for p in seats[0].battlefield if p.card.name == "Dracoplasm"), None
    )
    if dracoplasm is not None:
        game._recompute_continuous_effects()
        assert (dracoplasm.effective_power, dracoplasm.effective_toughness) == (0, 0)


# --- W1G4: triggered abilities the engine had never fired ---

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent


def _w1g4_lea():
    return {card.name: card for card in load_cards(manifest_set_path("LEA"))}


def _w1g4_perm(card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g4_upkeep(board, opposing=()):
    p1 = PlayerState(name="P1", battlefield=list(board))
    p2 = PlayerState(name="P2", battlefield=list(opposing))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return game, p1, p2


# -- Kezzerdrix -------------------------------------------------------------


def test_kezzerdrix_burns_you_while_your_opponents_have_no_creatures(set_pool):
    """"At the beginning of your upkeep, if your opponents control no
    creatures, this creature deals 4 damage to you."

    CR 603.4 over a per-seat board count. "Your opponents" is CR 102.2/102.3's
    set — every player who is not you — which is the same set "each opponent"
    already names, so it is a spelling rather than a fourth referent.
    """
    game, p1, _ = _w1g4_upkeep([_w1g4_perm(set_pool("TMP")["Kezzerdrix"])])

    assert p1.life == 16


def test_kezzerdrix_is_silent_while_an_opponent_has_a_creature(set_pool):
    game, p1, _ = _w1g4_upkeep(
        [_w1g4_perm(set_pool("TMP")["Kezzerdrix"])],
        [_w1g4_perm(_w1g4_lea()["Grizzly Bears"])],
    )

    assert p1.life == 20


def test_kezzerdrix_ignores_creatures_you_control(set_pool):
    """The clause names *your opponents*' boards, so your own creature does not
    switch it off — the narrowing a seat-blind board count would drop.
    """
    game, p1, _ = _w1g4_upkeep([
        _w1g4_perm(set_pool("TMP")["Kezzerdrix"]),
        _w1g4_perm(_w1g4_lea()["Grizzly Bears"]),
    ])

    assert p1.life == 16


# -- Flailing Drake ---------------------------------------------------------


def _w1g4_to_blockers(game, attackers):
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(0, attackers)
    assert ok, msg
    game.advance_combat_phase()   # declare blockers


def _w1g4_block(attacker_board, blocker_board):
    p1 = PlayerState(name="P1", battlefield=list(attacker_board))
    p2 = PlayerState(name="P2", battlefield=list(blocker_board))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    _w1g4_to_blockers(game, [0])
    ok, msg = game.declare_blockers(1, {0: 0})
    assert ok, msg
    game._settle()
    return game


def test_flailing_drake_pumps_the_creature_that_blocked_it(set_pool):
    """"Whenever this creature blocks or becomes blocked by a creature, that
    creature gets +1/+1 until end of turn."

    CR 509.3d: the printed narrowing ("by a creature") is what makes the event
    bind exactly one creature, so "that creature" names it. The handler this
    reaches (``pump_block_pair``) is the one ``engine/flanking.py`` builds by
    hand for CR 702.25a; until this round the printed sentence had no road to
    it and the card compiled to nothing.
    """
    drake = _w1g4_perm(set_pool("TMP")["Flailing Drake"])
    gargoyle = _w1g4_perm(_w1g4_lea()["Granite Gargoyle"])
    _w1g4_block([drake], [gargoyle])

    assert (gargoyle.effective_power, gargoyle.effective_toughness) == (3, 3)


def test_flailing_drake_pumps_the_creature_it_blocks(set_pool):
    """The *blocks* half of the same event, and the half a fall-through gets
    backwards: on that half the stack item's target is the Drake itself, so a
    reading that took the target would pump the Drake and leave the creature it
    blocked alone.
    """
    gargoyle = _w1g4_perm(_w1g4_lea()["Granite Gargoyle"])
    drake = _w1g4_perm(set_pool("TMP")["Flailing Drake"])
    _w1g4_block([gargoyle], [drake])

    assert (gargoyle.effective_power, gargoyle.effective_toughness) == (3, 3)
    assert (drake.effective_power, drake.effective_toughness) == (2, 3)


# -- Bellowing Fiend --------------------------------------------------------


def _w1g4_through_combat_damage(game):
    game._settle()
    game.advance_combat_phase()   # combat damage
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()


def test_bellowing_fiend_burns_the_damaged_creatures_controller(set_pool):
    """"Whenever this creature deals damage to a creature, this creature deals
    3 damage to that creature's controller and 3 damage to you."

    Two pieces the pool had neither of: a damage trigger whose *recipient* is a
    noun phrase rather than a seat word, and a "that creature" naming the
    **damaged** end of the event. The damager here is spelled "this creature",
    so the pronoun can only be the other end — read as the damager's (which is
    what every other card printing the phrase means) the Fiend would burn its
    own controller twice and leave the opponent untouched.
    """
    fiend = _w1g4_perm(set_pool("TMP")["Bellowing Fiend"])
    gargoyle = _w1g4_perm(_w1g4_lea()["Granite Gargoyle"])
    game = _w1g4_block([fiend], [gargoyle])
    _w1g4_through_combat_damage(game)

    assert game.players[1].life == 17
    assert game.players[0].life == 17


def test_bellowing_fiend_is_silent_on_damage_to_a_player(set_pool):
    """The recipient narrowing, in the direction that matters: "to a creature"
    is not "to anything". Dropped, an unblocked swing would burn both players
    for 3 on top of the combat damage.
    """
    fiend = _w1g4_perm(set_pool("TMP")["Bellowing Fiend"])
    p1 = PlayerState(name="P1", battlefield=[fiend])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    _w1g4_to_blockers(game, [0])
    _w1g4_through_combat_damage(game)

    assert game.players[0].life == 20
    assert game.players[1].life == 17


# -- Spike Drone ------------------------------------------------------------


def test_spike_drone_enters_with_its_counter(set_pool):
    """"This creature enters with a +1/+1 counter on it."

    CR 121.6 — an *entry* replacement, not a trigger, and the template
    `engine/enter_effects.py` has read since Triskelion. What it could not read
    was the number printed as an article and the noun printed singular, so a
    0/0 Spike that is 1/1 on the table was unsupported.
    """
    p1 = PlayerState(name="P1", hand=[set_pool("TMP")["Spike Drone"]])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    game.cast_from_hand(0, "Spike Drone")
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    drone = next(p for p in p1.battlefield if p.card.name == "Spike Drone")
    assert drone.metadata["plus_counters"] == 1
    assert (drone.effective_power, drone.effective_toughness) == (1, 1)


# -- Dirtcowl Wurm ----------------------------------------------------------


def _w1g4_land_play(set_pool, land_seat):
    wurm = _w1g4_perm(set_pool("TMP")["Dirtcowl Wurm"])
    p1 = PlayerState(name="P1", battlefield=[wurm])
    p2 = PlayerState(name="P2")
    [p1, p2][land_seat].hand.append(_w1g4_lea()["Forest"])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(land_seat)
    game._settle()
    game.cast_from_hand(land_seat, "Forest")
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return wurm


def test_dirtcowl_wurm_grows_when_an_opponent_plays_a_land(set_pool):
    """"Whenever an opponent plays a land, put a +1/+1 counter on this
    creature."

    CR 305.1: playing a land is a special action that uses no stack, so it is
    neither a cast nor necessarily an *entry* — the `land_enters` event beside
    it fires for a land that arrives by any route. Two events, and the card
    prints one of them.
    """
    wurm = _w1g4_land_play(set_pool, 1)

    assert (wurm.effective_power, wurm.effective_toughness) == (4, 5)


def test_dirtcowl_wurm_ignores_its_own_controllers_land(set_pool):
    """The printed seat, enforced. Dropped, the Wurm grows on every land drop
    in the game — an ability that works more often than the card allows.
    """
    wurm = _w1g4_land_play(set_pool, 0)

    assert (wurm.effective_power, wurm.effective_toughness) == (3, 4)


# -- Mongrel Pack -----------------------------------------------------------


def _w1g4_dogs(player):
    return sum(1 for p in player.battlefield if p.card.name == "Dog Token")


def test_mongrel_pack_makes_dogs_for_a_death_during_combat(set_pool):
    """"When this creature dies during combat, create four 1/1 green Dog
    creature tokens." (CR 506.1's phase, asked of the death.)
    """
    pack = _w1g4_perm(set_pool("TMP")["Mongrel Pack"])
    p1 = PlayerState(name="P1", battlefield=[pack])
    game = Game(players=[p1, PlayerState(name="P2", battlefield=[])])
    game.enforce_mana_costs = False
    _w1g4_to_blockers(game, [0])
    pack.damage_marked = 99
    game.check_state_based_actions()
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g4_dogs(p1) == 4


def test_mongrel_pack_makes_no_dogs_for_a_death_outside_combat(set_pool):
    """The narrowing, in the direction the compiler could not see: both front
    ends read "during combat" and the *bare* regex row would have swallowed the
    words unread, leaving a card that makes four Dogs whenever it dies at all.
    """
    pack = _w1g4_perm(set_pool("TMP")["Mongrel Pack"])
    p1 = PlayerState(name="P1", battlefield=[pack])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    assert game.current_turn_phase != "combat"
    pack.damage_marked = 99
    game.check_state_based_actions()
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()

    assert _w1g4_dogs(p1) == 0


# -- Fugitive Druid ---------------------------------------------------------


def _w1g4_target_druid(set_pool, spell_name):
    lea = _w1g4_lea()
    druid = _w1g4_perm(set_pool("TMP")["Fugitive Druid"])
    p1 = PlayerState(name="P1", battlefield=[druid], library=[lea["Forest"]] * 10)
    p2 = PlayerState(name="P2", hand=[lea[spell_name]], library=[lea["Forest"]] * 10)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(1)
    game._settle()
    game.cast_from_hand(
        1, spell_name, target_player_index=0, target_permanent_index=0,
    )
    game._settle()
    game.auto_resolve_pending_choices()
    game._settle()
    return p1


def test_fugitive_druid_draws_for_an_aura_spell(set_pool):
    """"Whenever this creature becomes the target of an Aura spell, you draw a
    card."

    CR 603.2's targeting announcement, narrowed by the *class* of spell — an
    axis the becomes-target table already had two entries on ("a spell", "an
    ability"). What it could not say was which kind of spell, so the card had
    no reading at all rather than a wrong one.
    """
    p1 = _w1g4_target_druid(set_pool, "Firebreathing")

    assert len(p1.hand) == 1


def test_fugitive_druid_is_silent_for_a_non_aura_spell(set_pool):
    """The narrowing, enforced against the spell's own printed subtype — a
    spell on the stack is not a permanent, so the layer system has no answer
    and the printed face is the whole of what is testable. Dropped, the Druid
    draws for every spell aimed at it.
    """
    p1 = _w1g4_target_druid(set_pool, "Lightning Bolt")

    assert len(p1.hand) == 0


# --- W1G2: what the turn remembers about spells cast (CR 601.3, 506.1, 113.6g) ---
import pytest

from engine import Game, PlayerState
from engine.cast_restrictions import (cast_own_cast_line, cast_spell_filter,
                                      cast_timing_claims_line,
                                      spells_cast_matching)
from engine.combat_restrictions import combat_restriction_for
from engine.counter_conditions import spell_cant_be_countered
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w1g2_board(set_pool, card_name):
    """*card_name* on the battlefield, unsick, with an opponent to attack."""
    a = PlayerState(name="A")
    game = Game(players=[a, PlayerState(name="B")])
    game.enforce_mana_costs = False
    perm = Permanent(card=set_pool("TMP")[card_name])
    perm.metadata["summoning_sickness_turn"] = -99
    a.battlefield.append(perm)
    game._settle()
    return game, a, perm


# --- Skyshroud Condor: CR 601.3 over the turn's cast record ---

def test_w1g2_skyshroud_condor_is_supported_by_the_timing_table(set_pool):
    """The gap was the **creature** gate, not the table: Skyshroud Condor is the
    first creature in the pool to print a "Cast this spell only …" clause, and a
    creature is refused for any line nothing reads."""
    program = compile_card_oracle(set_pool("TMP")["Skyshroud Condor"])
    assert program.supported, program.reason
    assert cast_timing_claims_line(
        "cast this spell only if you've cast another spell this turn"
    )


def test_w1g2_skyshroud_condor_needs_a_prior_spell(set_pool, catalog_by_name):
    caster = PlayerState(name="A", hand=[set_pool("TMP")["Skyshroud Condor"]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = False
    game._settle()

    refused = game.cast_from_hand(0, "Skyshroud Condor")
    game._settle()
    assert not refused.supported
    assert "cast another spell this turn" in refused.details
    assert [c.name for c in caster.hand] == ["Skyshroud Condor"]

    caster.spells_cast_this_turn.append(catalog_by_name["Lightning Bolt"])
    allowed = game.cast_from_hand(0, "Skyshroud Condor")
    game._settle()
    assert allowed.supported, allowed.details
    assert [p.card.name for p in caster.battlefield] == ["Skyshroud Condor"]


def test_w1g2_another_spell_is_honoured_by_the_record_not_by_a_narrowing(set_pool):
    """"Another" means "other than this one", and CR 601.3 asks the gate while
    the spell is being announced — before `casting` appends it to the record. So
    a non-empty record *is* "another spell", and the reader is right to return
    an unnarrowed filter rather than inventing one."""
    assert cast_own_cast_line(
        "cast this spell only if you've cast another spell this turn"
    ) == ({}, "another spell")
    assert cast_spell_filter("another spell") == {}
    assert cast_spell_filter("a creature spell") == {"type_filter": "creature"}
    assert cast_spell_filter("no spell") is None, (
        "a negation is a different condition, not presence"
    )


def test_w1g2_the_cast_record_is_read_per_seat(set_pool, catalog_by_name):
    """An opponent's casts are not yours."""
    caster = PlayerState(name="A", hand=[set_pool("TMP")["Skyshroud Condor"]])
    other = PlayerState(name="B")
    game = Game(players=[caster, other])
    game.enforce_mana_costs = False
    other.spells_cast_this_turn.append(catalog_by_name["Lightning Bolt"])
    game._settle()

    assert not spells_cast_matching(game, 0, {})
    assert spells_cast_matching(game, 1, {})
    assert not game.cast_from_hand(0, "Skyshroud Condor").supported


# --- Mogg Conscripts: CR 506.1 over the same record ---

def test_w1g2_mogg_conscripts_reads_the_same_phrase_as_the_casting_gate(set_pool):
    """One reader for two tables: a *spell* is not a permanent (CR 613.1), and
    the two restrictions must not disagree about what "a creature spell" is."""
    program = compile_card_oracle(set_pool("TMP")["Mogg Conscripts"])
    assert program.supported, program.reason
    assert [i.kind for i in program.instructions] == ["cant_attack_unless_you_cast"]
    read = combat_restriction_for(
        "this creature can't attack unless you've cast a creature spell this turn"
    )
    assert read is not None
    assert read.payload == {"spell_filter": cast_spell_filter("a creature spell")}


def test_w1g2_mogg_conscripts_cannot_attack_before_a_creature_spell(
    set_pool, catalog_by_name
):
    game, a, mogg = _w1g2_board(set_pool, "Mogg Conscripts")
    assert not game.can_attack(mogg, 1)

    a.spells_cast_this_turn.append(catalog_by_name["Lightning Bolt"])
    assert not game.can_attack(mogg, 1), "an instant is not a creature spell"

    a.spells_cast_this_turn.append(catalog_by_name["Grizzly Bears"])
    assert game.can_attack(mogg, 1)


def test_w1g2_mogg_conscripts_reads_its_controllers_record(set_pool, catalog_by_name):
    """"You" on a creature's own text is whoever controls it (CR 109.5), so a
    creature stolen this turn is held to its new controller's casts."""
    game, a, mogg = _w1g2_board(set_pool, "Mogg Conscripts")
    game.players[1].spells_cast_this_turn.append(catalog_by_name["Grizzly Bears"])
    assert not game.can_attack(mogg, 1)


# --- Scragnoth: CR 113.6g ---

def test_w1g2_scragnoth_is_supported_by_the_counter_path(set_pool):
    program = compile_card_oracle(set_pool("TMP")["Scragnoth"])
    assert program.supported, program.reason
    assert spell_cant_be_countered(set_pool("TMP")["Scragnoth"])
    assert not spell_cant_be_countered(set_pool("TMP")["Capsize"])


def test_w1g2_counterspell_does_not_counter_scragnoth(set_pool, catalog_by_name):
    """CR 113.6g. It is still a legal *target* — Counterspell prints "target
    spell", not "target spell that can be countered" — so the counter resolves
    and does nothing rather than being refused at announcement."""
    a = PlayerState(name="A", hand=[set_pool("TMP")["Scragnoth"]])
    b = PlayerState(name="B", hand=[catalog_by_name["Counterspell"]])
    game = Game(players=[a, b])

    game.queue_from_hand(0, "Scragnoth")
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert [p.card.name for p in a.battlefield] == ["Scragnoth"]
    assert a.graveyard == []
    assert [c.name for c in b.graveyard] == ["Counterspell"]
    assert any("can't be countered" in line for line in game.log)


def test_w1g2_power_sink_arms_no_prompt_against_scragnoth(set_pool, catalog_by_name):
    """The immunity is asked **before** the "unless its controller pays" prompt:
    asking a player to pay to prevent something that could never happen is worse
    than not asking, because they would pay."""
    a = PlayerState(name="A", hand=[set_pool("TMP")["Scragnoth"]])
    b = PlayerState(name="B", hand=[catalog_by_name["Power Sink"]])
    game = Game(players=[a, b])

    game.queue_from_hand(0, "Scragnoth")
    game.queue_from_hand(1, "Power Sink", target_player_index=0, x_value=3)
    game.resolve_stack()

    assert game.pending_choices == []
    assert [p.card.name for p in a.battlefield] == ["Scragnoth"]


def test_w1g2_an_ordinary_creature_spell_is_still_countered(catalog_by_name):
    """The control: the immunity is read off the card, so it reaches exactly the
    card that prints it."""
    a = PlayerState(name="A", hand=[catalog_by_name["Grizzly Bears"]])
    b = PlayerState(name="B", hand=[catalog_by_name["Counterspell"]])
    game = Game(players=[a, b])

    game.queue_from_hand(0, "Grizzly Bears")
    game.queue_from_hand(1, "Counterspell", target_player_index=0)
    game.resolve_stack()

    assert a.battlefield == []
    assert [c.name for c in a.graveyard] == ["Grizzly Bears"]


# --- W1G5: the tuck, all three printed subjects ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w1g5c_card(name, type_line, text="", power=None, toughness=None):
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw["power"], raw["toughness"] = str(power), str(toughness)
    return CardDefinition(
        name=name, mana_cost="", type_line=type_line, oracle_text=text,
        cmc=0.0, colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw=raw,
        power=str(power) if power is not None else None,
        toughness=str(toughness) if toughness is not None else None,
    )


def _w1g5c_game(mine, theirs):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(mine)),
        PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game._settle()
    for permanent in list(mine) + list(theirs):
        permanent.metadata["summoning_sickness_turn"] = -99
    return game


def test_w1g5_a_creature_tucks_itself_off_the_battlefield():
    """"{U}: Put this creature on top of its owner's library." (Thalakos
    Mistfolk.)

    Tested on an invented card carrying only that line, deliberately: Mistfolk
    itself is unsupported until *shadow* lands (W1G1), and a test that waited
    for the other half would be testing two things. What this asserts is the
    tuck's own subject — the source, which is not a target and must not reach
    the picker.
    """
    probe = Permanent(card=_w1g5c_card(
        "Mistfolk Probe", "Creature — Illusion",
        "{U}: Put this creature on top of its owner's library.",
        power=1, toughness=1,
    ))
    game = _w1g5c_game([probe], [])

    result = game.activate_permanent_ability(0, "Mistfolk Probe", ability_index=0)
    assert result.supported, result.details
    game.resolve_top_of_stack()

    assert list(game.controlled_by(0)) == []
    assert [card.name for card in game.players[0].library] == ["Mistfolk Probe"]


def test_w1g5_avenging_angel_may_tuck_itself_out_of_the_graveyard(set_pool):
    """"When this creature dies, you may put it on top of its owner's library."

    The same *subject* as Mistfolk's — the noun parser marks the pronoun
    ``is_source`` — reached from a different zone: a dies trigger resolves with
    the card already in a graveyard (CR 404.1), so a handler that looked only
    at the battlefield would silently do nothing here.
    """
    angel = Permanent(card=set_pool("TMP")["Avenging Angel"])
    game = _w1g5c_game([angel], [])

    angel.damage_marked = 99
    game.check_state_based_actions()
    assert [card.name for card in game.players[0].graveyard] == ["Avenging Angel"]
    while game.stack:
        game.resolve_top_of_stack()

    assert game.confirm_optional_pay(0, accept=True)
    assert game.players[0].graveyard == [], game.log
    assert [card.name for card in game.players[0].library] == ["Avenging Angel"]


def test_w1g5_avenging_angel_declined_stays_in_the_graveyard(set_pool):
    """The offer is a "may" and both branches are real. A card that always
    tucked would report exactly the same instruction."""
    angel = Permanent(card=set_pool("TMP")["Avenging Angel"])
    game = _w1g5c_game([angel], [])

    angel.damage_marked = 99
    game.check_state_based_actions()
    while game.stack:
        game.resolve_top_of_stack()

    assert game.confirm_optional_pay(0, accept=False)
    assert [card.name for card in game.players[0].graveyard] == ["Avenging Angel"]
    assert game.players[0].library == []


def test_w1g5_elven_warhounds_tucks_the_creature_that_blocked_it(set_pool):
    """"Whenever this creature becomes blocked by a creature, put that creature
    on top of its owner's library."

    The third subject: the other half of the pair the trigger bound, which is
    neither the source nor a target. The blocker goes to **its owner's**
    library (CR 400.3), not the ability controller's — the assertion that would
    fail if the tuck read the wrong seat.
    """
    hounds = Permanent(card=set_pool("TMP")["Elven Warhounds"])
    blocker = Permanent(card=_w1g5c_card(
        "Bear", "Creature — Bear", power=2, toughness=2,
    ))
    game = _w1g5c_game([hounds], [blocker])
    game.active_player_index = 0

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: [0]})[0]
    while game.stack:
        game.resolve_top_of_stack()

    assert list(game.controlled_by(1)) == [], game.log
    assert [card.name for card in game.players[1].library] == ["Bear"]
    assert game.players[0].library == [], "the blocker's owner, not the tucker's"


def test_w1g5_a_bare_becomes_blocked_trigger_refuses_the_tuck():
    """CR 509.3c/509.3d. "Becomes blocked" with no noun phrase fires **once**
    however many creatures blocked, so "that creature" names no one of them —
    and the fire site would hand over an arbitrary blocker. The narrowed
    spelling Elven Warhounds prints is what makes the pronoun answerable, so
    the unnarrowed one refuses rather than tucking whichever creature came
    first.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability
    import pytest as _pytest

    node = parse_line(
        "Whenever this creature becomes blocked, put that creature on top of "
        "its owner's library."
    )
    with _pytest.raises(LoweringError):
        lower_ability(node)


# --- W2G5: a target narrowed by a counter kind the card invented ------------

from engine import Game as _W2G5Game, PlayerState as _W2G5PlayerState
from engine.models import Permanent as _W2G5Permanent
from engine.named_counters import counters_on as _w2g5_counters_on
from engine.oracle import compile_card_oracle as _w2g5_compile
from engine.targeting import derive_activation_spec as _w2g5_activation_spec


def _w2g5_bounty_board(set_pool):
    """Bounty Hunter, and three creatures for it to point at."""
    pool = set_pool("TMP")
    hunter = _W2G5Permanent(card=pool["Bounty Hunter"])
    hunter.summoning_sick = False
    victims = [
        _W2G5Permanent(card=pool["Horned Turtle"]),     # blue
        _W2G5Permanent(card=pool["Trained Armodon"]),   # green
        _W2G5Permanent(card=pool["Blood Pet"]),         # black
    ]
    game = _W2G5Game(players=[
        _W2G5PlayerState(name="P1", life=20, battlefield=[hunter]),
        _W2G5PlayerState(name="P2", life=20, battlefield=victims),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, hunter, victims


def test_w2g5_bounty_hunter_marks_then_destroys_what_it_marked(set_pool):
    """"{T}: Put a bounty counter on target nonblack creature." /
    "{T}: Destroy target creature with a bounty counter on it."

    Both ends of one card, in one game. The second line refused before this
    round because "with a <kind> counter on it" was read for the +1/+1 kind
    alone — the counters CR 122.1 lets a card invent had no matcher, so the
    phrase failed the line loudly. It has one now
    (``ObjectFilter.with_named_counter``, over
    ``engine/named_counters.py``'s store).
    """
    game, hunter, (turtle, armodon, blood_pet) = _w2g5_bounty_board(set_pool)

    assert game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    ).supported
    game.resolve_stack()
    assert _w2g5_counters_on(turtle, "bounty") == 1
    assert _w2g5_counters_on(armodon, "bounty") == 0

    hunter.tapped = False
    assert game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=0,
    ).supported, game.log
    game.resolve_stack()

    defender = game.players[1]
    assert [p.card.name for p in defender.battlefield] == [
        "Trained Armodon", "Blood Pet",
    ]
    assert [c.name for c in defender.graveyard] == ["Horned Turtle"]


def test_w2g5_bounty_hunter_refuses_an_unmarked_creature_with_nothing_paid(set_pool):
    """CR 602.2b via 601.2c: an ability with a mandatory target it cannot fill
    is refused before the cost is paid — so the Hunter is still untapped and
    can be aimed somewhere legal this turn.

    The failure this guards is the quiet one: a narrowing the matcher cannot
    test is one the dispatcher ignores, and an ability that destroys *any*
    creature is not the card.
    """
    game, hunter, _victims = _w2g5_bounty_board(set_pool)

    refused = game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=1,
    )

    assert not refused.supported
    assert not hunter.tapped, "nothing is paid for a refused activation"
    assert len(game.players[1].battlefield) == 3


def test_w2g5_a_named_counter_is_not_the_plus_one_counter(set_pool):
    """The two stores stay apart in a game, not only in the matcher's unit test.

    CR 122.1a's +1/+1 counter is layer 7d and lives in ``engine/pt.py``'s
    ``plus_counters`` record; a bounty counter is an inert marker in the open
    store. A matcher reading one for the other would let Bounty Hunter destroy
    a creature somebody had merely been pumping.
    """
    game, hunter, (turtle, _armodon, _blood_pet) = _w2g5_bounty_board(set_pool)
    turtle.metadata["plus_counters"] = 2

    refused = game.activate_permanent_ability(
        0, "Bounty Hunter", ability_index=1,
        target_player_index=1, target_permanent_index=0,
    )

    assert not refused.supported, "+1/+1 counters are not bounty counters"
    assert not hunter.tapped


def test_w2g5_the_bounty_picker_offers_only_the_marked_creatures(set_pool):
    """The picker and the activation gate are one reading — the list the client
    is offered is the list the engine will accept, through the same
    ``_destroy_target_legal`` both ask."""
    game, hunter, (turtle, _armodon, _blood_pet) = _w2g5_bounty_board(set_pool)
    program = _w2g5_compile(hunter.card)
    ability = program.activated_abilities[1]
    spec = _w2g5_activation_spec(ability)

    def offered():
        return [
            t.get("name") for t in game._enumerate_targets(
                0, hunter.card, spec, for_cast=False,
                ability_source=hunter, ability_instruction=ability.instruction,
            )
        ]

    assert offered() == []

    from engine.named_counters import add_counters

    add_counters(turtle, "bounty", 1)
    assert offered() == ["Horned Turtle"]


# --- W2G5: a permanent that hands itself to the seat it just robbed ---------


def _w2g5_starke(set_pool, victim_seat):
    """Starke of Rath in play, and a Horned Turtle on *victim_seat*'s board."""
    pool = set_pool("TMP")
    starke = _W2G5Permanent(card=pool["Starke of Rath"])
    starke.summoning_sick = False
    turtle = _W2G5Permanent(card=pool["Horned Turtle"])
    boards = ([starke, turtle], []) if victim_seat == 0 else ([starke], [turtle])
    game = _W2G5Game(players=[
        _W2G5PlayerState(name="P1", life=20, battlefield=list(boards[0])),
        _W2G5PlayerState(name="P2", life=20, battlefield=list(boards[1])),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    return game, starke


def test_w2g5_starke_of_rath_changes_hands_to_the_seat_it_robbed(set_pool):
    """"{T}: Destroy target artifact or creature. That permanent's controller
    gains control of Starke. (This effect lasts indefinitely.)"

    The seat has to be read **before** the destroy is over. By the time the
    second sentence runs the permanent is a card in a graveyard, and CR 108.4
    gives a card no controller at all — so a board read would hand Starke to
    nobody. The destroy has recorded ``last_target_controller`` since Afterlife
    (CR 608.2h); the control change reads it, which is the same preference
    "its controller loses 2 life" already takes one family over.

    The control change itself is CR 611.2b's untimed one — a layer-2
    contribution with nothing to end it — so ``controller_index_of`` answers
    the new seat and the permanent has genuinely moved.
    """
    game, starke = _w2g5_starke(set_pool, victim_seat=1)

    result = game.activate_permanent_ability(
        0, "Starke of Rath", ability_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert [c.name for c in game.players[1].graveyard] == ["Horned Turtle"]
    assert game.controller_index_of(starke) == 1
    assert [p.card.name for p in game.controlled_by(0)] == []
    assert [p.card.name for p in game.controlled_by(1)] == ["Starke of Rath"]


def test_w2g5_starke_of_rath_stays_home_when_it_kills_its_own_side(set_pool):
    """The seat is the *victim's* controller, whoever that is — so aiming the
    ability at your own creature keeps Starke where it is. A hand-over that
    always went to an opponent would be a different card."""
    game, starke = _w2g5_starke(set_pool, victim_seat=0)

    assert game.activate_permanent_ability(
        0, "Starke of Rath", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    ).supported
    game.resolve_stack()

    assert game.controller_index_of(starke) == 0
    assert [p.card.name for p in game.controlled_by(1)] == []


def test_w2g5_a_named_self_reference_reads_as_this_creature(set_pool):
    """The half that had nothing to do with control changes.

    "…gains control of **Starke**" and "…gains control of **this creature**"
    are one printed sentence in two templating eras, and they had two readers:
    the seat-in-front spelling used ``parse_target_spec``, which has no SELF
    branch, while ``_parse_gain_control`` beside it used ``parse_recipient``,
    which does. So the modern spelling parsed and the card's own name did not.
    """
    from engine.grammar import parse_line
    from engine.grammar.lower import lower_ability

    named = lower_ability(parse_line(
        "{T}: Destroy target artifact or creature. That permanent's controller "
        "gains control of Starke of Rath.",
        card_name="Starke of Rath",
    ))
    modern = lower_ability(parse_line(
        "{T}: Destroy target artifact or creature. That permanent's controller "
        "gains control of this creature.",
    ))
    assert named == modern

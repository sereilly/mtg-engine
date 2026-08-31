"""Ice Age (ICE) sorcery cards.

ICE **ships** (SET_PLAYBOOK.md Phase 4 moved it from ``measured`` to ``sets``).
It was measured while these tests were written, and the pool resolves through
``set_pool("ICE")`` either way — that fixture is about which cards a test may
name, not about which a player may deck. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle


# --- Round 3: the cantrip cycle — "at the beginning of the next turn's upkeep" ---
def _all_instructions(program):
    """Every instruction the program carries, card-level and per-ability.

    The cycle prints its cantrip in three places — a spell's second sentence, an
    Aura's enters trigger, an artifact's activated ability — so a reader that
    looked only at ``program.instructions`` would find the clause on some of
    them and quietly miss it on the rest.
    """
    def walk(instruction):
        yield instruction
        # A `sequence` is how two sentences on one line compose (Barbed
        # Sextant's "Add one mana of any color. Draw a card at …"), so a reader
        # that stopped at the top level would find the clause on five of the
        # seven and report the other two clean.
        for step in instruction.payload.get("steps", ()):
            yield from walk(step)

    for instruction in program.instructions:
        yield from walk(instruction)
    for ability in (*program.activated_abilities, *program.triggered_abilities):
        if ability.instruction is not None:
            yield from walk(ability.instruction)
def test_the_cantrip_cycle_arms_the_unseated_upkeep_event(set_pool):
    """Seven cards, one sentence. What makes it one round rather than seven is
    that they all compile to the same delayed event — and it is the *unseated*
    one, because "the next turn's upkeep" is whichever comes next."""
    pool = set_pool("ICE")
    for name in (
        "Portent", "Krovikan Fetish", "Panic", "Pyknite",
        "Touch of Vitae", "Barbed Sextant",
    ):
        program = compile_card_oracle(pool[name])
        assert program.supported, name
        events = {
            instruction.payload.get("event")
            for instruction in _all_instructions(program)
            if instruction.kind == "create_delayed_trigger"
        }
        assert events == {"next_turns_upkeep"}, (name, events)
# --- Round 11: "If that land was a snow land, …" (CR 608.2h) ---
def _cast_land_destroyer(set_pool, spell: str, land: str):
    """Cast *spell* at a *land* the opponent controls; return the board."""
    pool = set_pool("ICE")
    victim = Permanent(card=pool[land])
    p1 = PlayerState(name="P1", hand=[pool[spell]], life=20)
    p2 = PlayerState(name="P2", battlefield=[victim], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.cast_from_hand(
        0, spell, target_player_index=1, target_permanent_index=0
    )
    game._settle()
    return game, p1, p2, victim
def test_thermokarst_gains_life_only_for_a_snow_land(set_pool):
    """"Destroy target land. If that land was a snow land, you gain 1 life."

    The condition is asked **after** the land is a card in a graveyard, so it
    reads the object as it was (CR 608.2h) — nothing on the board can answer it.
    """
    _game, p1, p2, snow = _cast_land_destroyer(
        set_pool, "Thermokarst", "Snow-Covered Forest"
    )
    assert snow not in p2.battlefield
    assert p1.life == 21

    _game, p1, p2, plain = _cast_land_destroyer(set_pool, "Thermokarst", "Forest")
    assert plain not in p2.battlefield
    assert p1.life == 20, "an ordinary Forest is not a snow land"
def test_icequake_damages_the_controller_only_for_a_snow_land(set_pool):
    """The other half of the cycle, whose rider names the land's controller —
    a seat the destruction has to have recorded for the same reason."""
    _game, p1, p2, snow = _cast_land_destroyer(
        set_pool, "Icequake", "Snow-Covered Swamp"
    )
    assert snow not in p2.battlefield
    assert p2.life == 19

    _game, p1, p2, plain = _cast_land_destroyer(set_pool, "Icequake", "Swamp")
    assert plain not in p2.battlefield
    assert p2.life == 20
# --- Round 28: N cards from a hand back onto the top of a library ---
def _casting(set_pool, spell: str, *, hand=(), library=(), opponent_hand=(), opponent_library=()):
    """The caster holding *spell*, with both seats' hidden zones set."""
    pool = set_pool("ICE")
    from engine.card_loader import load_catalog

    shipped = {card.name: card for card in load_catalog()}

    def card(name):
        return pool.get(name) or shipped[name]

    p1 = PlayerState(
        name="P1", hand=[card(spell), *[card(n) for n in hand]],
        library=[card(n) for n in library], life=20,
    )
    p2 = PlayerState(
        name="P2", hand=[card(n) for n in opponent_hand],
        library=[card(n) for n in opponent_library], life=20,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0, 1}
    return game, p1, p2
def test_stunted_growth_asks_the_targeted_player(set_pool):
    """"Target player chooses three cards from their hand and puts them on top
    of their library in any order."

    The same effect over a printed subject: the seat that owns the hand is the
    seat that chooses, and it is not the caster.
    """
    game, p1, p2 = _casting(
        set_pool, "Stunted Growth",
        library=["Hoar Shade"],
        opponent_hand=["Balduvian Bears", "Hoar Shade", "Icy Manipulator", "Snow Fortress"],
        opponent_library=["Dark Banishing"],
    )

    result = game.cast_from_hand(0, "Stunted Growth", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    assert game.pending_choice_of("hand_to_library", 0) is None, "not the caster's choice"
    choice = game.pending_choice_of("hand_to_library", 1)
    assert choice is not None and choice.data["count"] == 3

    game.confirm_hand_to_library(1, [0, 1, 2])
    game._settle()

    assert len(p2.hand) == 1
    assert len(p2.library) == 4
def test_stunted_growth_takes_what_a_short_hand_has(set_pool):
    """CR 608.2: a spell does as much as it can. A player holding fewer cards
    than the card names puts back what they have rather than the effect
    refusing."""
    game, _p1, p2 = _casting(
        set_pool, "Stunted Growth",
        library=["Hoar Shade"],
        opponent_hand=["Balduvian Bears"],
        opponent_library=["Dark Banishing"],
    )

    game.cast_from_hand(0, "Stunted Growth", target_player_index=1)
    game._settle()

    choice = game.pending_choice_of("hand_to_library", 1)
    assert choice is not None and choice.data["count"] == 1
# --- Round 33: the rest go back on top, and that is a decision ---
def _library_of(set_pool, *names):
    pool = set_pool("ICE")
    return [pool[n] for n in names]
def test_diabolic_vision_keeps_one_and_stacks_the_rest(set_pool):
    """"Look at the top five cards of your library. Put one of them into your
    hand and the rest on top of your library in any order."

    See the Truth prints the same template with three differences — "those
    cards" for "them", the bottom for the top, and a cast-zone rider — and
    every one of them was written into the production as a required word.
    """
    library = _library_of(
        set_pool, "Balduvian Bears", "Tor Giant", "Scaled Wurm",
        "Forest", "Mountain", "Island",
    )
    p1 = PlayerState(
        name="P1", library=list(library),
        hand=[set_pool("ICE")["Diabolic Vision"]], life=20,
    )
    game = Game(
        players=[p1, PlayerState(name="P2", life=20)], interactive_seats={0}
    )

    game.queue_from_hand(0, "Diabolic Vision")
    while game.stack:
        game.resolve_top_of_stack()

    assert game.pending_choice_of("look_top_pick", 0) is not None
    assert game.confirm_look_top_pick(0, 1) is True
    assert [c.name for c in p1.hand] == ["Tor Giant"]

    # The four that were not taken are back on top, not on the bottom.
    assert [c.name for c in p1.library[:4]] == [
        "Balduvian Bears", "Scaled Wurm", "Forest", "Mountain",
    ]
    assert game.confirm_reorder_library(0, [3, 2, 1, 0]) is True
    assert [c.name for c in p1.library] == [
        "Mountain", "Forest", "Scaled Wurm", "Balduvian Bears", "Island",
    ]


# --- Round 42: X targets for a destroy, mirroring the untap that has them ---
def _r42_avalanche(set_pool, snow_lands=3, plain_lands=0):
    pool = set_pool("ICE")
    p1 = PlayerState(name="P1", hand=[pool["Avalanche"]], life=20)
    board = [Permanent(card=pool["Snow-Covered Forest"]) for _ in range(snow_lands)]
    board += [Permanent(card=pool["Snow-Covered Mountain"]) for _ in range(0)]
    p2 = PlayerState(name="P2", battlefield=board, life=20)
    if plain_lands:
        from engine.card_loader import load_cards
        p2.battlefield.extend(
            Permanent(card=set_pool("LEA")["Forest"]) for _ in range(plain_lands)
        )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p2


def test_avalanche_destroys_exactly_the_lands_named(set_pool):
    """"Destroy X target snow lands."

    The lowering refused this outright — "unsupported destroy quantifier" —
    while the untap beside it had read the identical shape since Candelabra of
    Tawnos. Each slot resolves strictly, so a target that has left is dropped
    rather than slid onto another (CR 608.2b).
    """
    game, defender = _r42_avalanche(set_pool, snow_lands=3)

    result = game.cast_from_hand(
        0, "Avalanche", x_value=2,
        target_player_index=1, target_permanent_index=[0, 1],
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert len(defender.battlefield) == 1
    assert len(defender.graveyard) == 2


def test_avalanche_destroys_only_snow_lands(set_pool):
    """The printed noun phrase is enforced at resolution as well as at
    announcement — `resolve_target_permanents` defaults to "is it a creature?",
    which would have matched none of these."""
    game, defender = _r42_avalanche(set_pool, snow_lands=1, plain_lands=1)

    refused = game.cast_from_hand(
        0, "Avalanche", x_value=2,
        target_player_index=1, target_permanent_index=[0, 1],
    )
    assert not refused.supported, "a plain Forest is not a legal target (CR 601.2c)"

    game.cast_from_hand(
        0, "Avalanche", x_value=1,
        target_player_index=1, target_permanent_index=[0],
    )
    game.resolve_stack()

    remaining = [perm.card.name for perm in defender.battlefield]
    assert remaining == ["Forest"], "an ordinary Forest is not a snow land"


def test_a_several_target_destroy_used_to_describe_no_targets_at_all(set_pool):
    """The latent half of the same gap, kept as the regression.

    "Destroy up to two target creatures" reached the *single*-target path:
    `_targets_payload` refuses a several-target spec, so the instruction went
    out with no target description, the picker had nothing to read, and the
    spell would have destroyed one of the two permanents it names. No card in
    the pool prints it, which is the only reason that was latent rather than
    live.
    """
    from engine.grammar import parse_line
    from engine.grammar.lower import lower_ability

    instruction, = lower_ability(parse_line("destroy up to two target creatures"))

    assert instruction.kind == "destroy_target_permanent"
    assert instruction.payload["targets"]["count"] == 2


# --- W1G3: mana, additional costs, cost restrictions ---
def test_w1g3_fumarole_names_two_targets_and_pays_for_them(set_pool):
    """"As an additional cost to cast this spell, pay 3 life." / "Destroy target
    creature and target land." (W3G3 — the refusal this test used to pin.)

    Three of the four pieces W1G3 named turned out to be already built. The
    engine has carried an ordered **roles** target description since Glyph of
    Delusion: ``targeting.roles_spec`` answers with a list rather than one
    ``kind``, ``legality.role_target_options`` enumerates role *n* with roles
    0…n−1 settled, ``casting._validate_cast_targets`` gates the whole
    announcement, and the wire's ``target_permanent_ids`` is already the
    ordered cross-battlefield channel. Only the *union parse* refused, and its
    stated reason — "the cast picker asks a spell for one target" — had stopped
    being true.

    So the refusal moved to the callers that genuinely cannot describe several:
    a union lowered to a ``Conjunction`` is a sequence of instructions whose
    spec comes from the first one, and the rest would be picked by nobody.
    """
    from engine.cast_costs import additional_costs

    fumarole = set_pool("ICE")["Fumarole"]
    program = compile_card_oracle(fumarole)
    assert program.supported

    (cost,) = additional_costs(fumarole)
    assert cost.pay_life == 3

    (instruction,) = [i for i in program.instructions if i.kind != "spell_pattern"]
    assert instruction.kind == "destroy_target_permanent"
    roles = instruction.payload["targets"]["roles"]
    assert [role["role"] for role in roles] == ["creature", "land"]


# --- end W1G3 ---


# --- W1G4: library, hand and graveyard ---
def _mind_warp_game(set_pool, x_value):
    pool = set_pool("ICE")
    p1 = PlayerState(name="P1", hand=[pool["Mind Warp"]], life=20)
    p2 = PlayerState(
        name="P2",
        hand=[pool["Balduvian Bears"], pool["Brown Ouphe"], pool["Tor Giant"]],
        life=20,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    result = game.cast_from_hand(
        0, "Mind Warp", target_player_index=1, x_value=x_value
    )
    assert result.supported, result.details
    game._settle()
    return pool, p1, p2, game


def test_mind_warp_discards_x_chosen_cards(set_pool):
    """"Look at target player\'s hand and choose X cards from it. That player
    discards those cards."

    X is the announced value, and the caster does the choosing out of somebody
    else\'s hidden zone — which is Duress\'s template with two things changed,
    so it is Duress\'s node.
    """
    pool, p1, p2, game = _mind_warp_game(set_pool, 2)

    first = game.pending_choice_of("revealed_hand_pick", 0)
    assert first is not None, "the caster chooses, not the victim"
    assert first.data["remaining"] == 2

    assert game.confirm_revealed_hand_pick(0, 0)
    second = game.pending_choice_of("revealed_hand_pick", 0)
    assert second is not None, "the second pick is asked against the hand as it now is"
    assert game.confirm_revealed_hand_pick(0, 0)

    assert game.pending_choice_of("revealed_hand_pick", 0) is None
    assert [card.name for card in p2.hand] == ["Tor Giant"]
    assert sorted(card.name for card in p2.graveyard) == [
        "Balduvian Bears", "Brown Ouphe",
    ]


def test_mind_warp_for_more_than_the_hand_takes_the_hand(set_pool):
    """CR 608.2 does as much as it can: X of 5 against three cards discards
    three and does not leave a prompt nobody can answer."""
    pool, p1, p2, game = _mind_warp_game(set_pool, 5)

    for _ in range(3):
        prompt = game.pending_choice_of("revealed_hand_pick", 0)
        assert prompt is not None
        assert game.confirm_revealed_hand_pick(0, prompt.data["legal_indices"][0])

    assert game.pending_choice_of("revealed_hand_pick", 0) is None
    assert p2.hand == []
    assert len(p2.graveyard) == 3


def test_mind_warp_for_zero_asks_nothing(set_pool):
    """X of 0 chooses no cards, so no prompt is armed at all — an offer with
    nothing to choose is not a choice."""
    pool, p1, p2, game = _mind_warp_game(set_pool, 0)

    assert game.pending_choice_of("revealed_hand_pick", 0) is None
    assert len(p2.hand) == 3
# --- end W1G4 ---


# --- Misfiled from test_ice_creatures.py: the card this test names is a Sorcery ---
def test_a_union_of_two_targeted_phrases_is_one_announcement(set_pool):
    """"Destroy target creature and target land." (Fumarole.)

    This test pinned the refusal. CR 601.2c chooses every target of a spell as
    part of one announcement, so the union is **one** statement with an ordered
    roles description rather than two statements — and the picker walks the
    roles in order. The two cards above are unaffected either way: their first
    phrase is the source rather than a target.
    """
    from engine.targeting import derive_cast_spec, spec_roles

    fumarole = set_pool("ICE")["Fumarole"]
    program = compile_card_oracle(fumarole)

    assert program.supported
    assert [role["kind"] for role in spec_roles(derive_cast_spec(fumarole, program))] == [
        "creature", "land",
    ]


# --- W2G5: mass effects and X-spells ---
def _w2g5_burst_game(set_pool, *, victim_name="Tor Giant"):
    """Seat 0 holding Lava Burst; seat 1 with one creature out."""
    pool = set_pool("ICE")
    p1 = PlayerState(name="P1", hand=[pool["Lava Burst"]], life=20)
    victim = Permanent(card=pool[victim_name])
    p2 = PlayerState(name="P2", battlefield=[victim], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    return pool, p1, p2, victim, game


def test_lava_burst_damage_to_a_creature_ignores_a_shield(set_pool):
    """"If Lava Burst would deal damage to a creature, that damage can't be
    prevented or dealt instead to another permanent or player."

    A three-point prevention shield on the creature absorbs nothing: the lock
    drops the contenders that prevent or move the damage, and keeps every other
    kind.
    """
    from engine.shields import Shield, add_shield, shields_on, PREVENT_NEXT_N

    pool, p1, p2, victim, game = _w2g5_burst_game(set_pool)
    add_shield(victim, Shield(kind=PREVENT_NEXT_N, amount=3, uses=None))

    result = game.cast_from_hand(
        0, "Lava Burst", target_player_index=1, target_permanent_index=0, x_value=3
    )
    game._settle()

    assert result.supported, result.details
    assert victim.damage_marked == 3, "the shield had nothing to absorb"
    assert shields_on(victim)[0].amount == 3, "and nothing was spent doing it"


def test_lava_burst_shield_on_a_creature_still_works_against_another_source(set_pool):
    """The control the assertion above needs: the shield is a real shield. The
    same three points from an ordinary source are prevented in full — so what
    the test above measured is the lock, not a shield that never worked."""
    from engine.shields import Shield, add_shield, PREVENT_NEXT_N

    pool, p1, p2, victim, game = _w2g5_burst_game(set_pool)
    add_shield(victim, Shield(kind=PREVENT_NEXT_N, amount=3, uses=None))

    game._mark_damage_on_permanent(victim, 3, source=pool["Balduvian Bears"])

    assert victim.damage_marked == 0


def test_lava_burst_damage_to_a_player_is_shielded_as_normal(set_pool):
    """"…would deal damage to **a creature**" is the whole scope of the clause.
    Aimed at a face, Lava Burst is an ordinary damage spell and a Circle-shaped
    shield answers it — reading the lock as unconditional is the direction that
    makes the card larger than printed."""
    from engine.shields import Shield, add_shield, PREVENT_NEXT_N

    pool, p1, p2, victim, game = _w2g5_burst_game(set_pool)
    add_shield(p2, Shield(kind=PREVENT_NEXT_N, amount=3, uses=None))

    result = game.cast_from_hand(0, "Lava Burst", target_player_index=1, x_value=3)
    game._settle()

    assert result.supported, result.details
    assert p2.life == 20


def test_lava_burst_lock_is_not_left_on_the_creature(set_pool):
    """The clause is about this spell's damage, not about the creature. A
    second source aiming at the same creature later in the turn is shielded
    normally — which is the difference between this rider and Whippoorwill's
    marker, and the reason it rides the event."""
    from engine.shields import Shield, add_shield, PREVENT_NEXT_N

    pool, p1, p2, victim, game = _w2g5_burst_game(set_pool)
    game.cast_from_hand(
        0, "Lava Burst", target_player_index=1, target_permanent_index=0, x_value=1
    )
    game._settle()
    assert victim.damage_marked == 1

    add_shield(victim, Shield(kind=PREVENT_NEXT_N, amount=2, uses=None))
    game._mark_damage_on_permanent(victim, 2, source=pool["Balduvian Bears"])

    assert victim.damage_marked == 1, "the later damage was prevented"


def _w2g5_filter_game(set_pool, *, interactive):
    """Essence Filter in seat 0's hand; a white and a blue enchantment out."""
    pool = set_pool("ICE")
    justice = Permanent(card=pool["Justice"])
    snowfall = Permanent(card=pool["Snowfall"])
    p1 = PlayerState(name="P1", hand=[pool["Essence Filter"]], battlefield=[justice], life=20)
    p2 = PlayerState(name="P2", battlefield=[snowfall], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    if interactive:
        game.interactive_seats = {0}
    else:
        game.interactive_seats = set()
    game._sync_control()
    return pool, p1, p2, justice, snowfall, game


def test_essence_filter_offers_both_halves_of_its_or(set_pool):
    """"Destroy all enchantments or all nonwhite enchantments."

    Not CR 700.2's modes — no bulleted list, nothing announced as the spell is
    cast — but CR 608.2d's choice made while the effect is applied. It reaches
    the same prompt the printed "you may A or B" does, with both object phrases
    offered.
    """
    pool, p1, p2, justice, snowfall, game = _w2g5_filter_game(set_pool, interactive=True)

    result = game.cast_from_hand(0, "Essence Filter")
    game._settle()

    assert result.supported, result.details
    prompt = game.pending_choice_of("mode_choice", 0)
    assert prompt is not None, "the caster chooses at resolution"
    assert len(prompt.data["labels"]) == 2


def test_essence_filter_second_half_spares_the_white_enchantment(set_pool):
    """The narrowing is the whole content of the second option, and it is the
    half a sweep silently loses: taking it destroys the blue enchantment and
    leaves the white one alone."""
    pool, p1, p2, justice, snowfall, game = _w2g5_filter_game(set_pool, interactive=True)
    game.cast_from_hand(0, "Essence Filter")
    game._settle()

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    game._settle()

    assert justice in p1.battlefield, "white was excluded"
    assert snowfall not in p2.battlefield


def test_essence_filter_first_half_destroys_both(set_pool):
    """And the other option really is the wider one — otherwise the choice is
    a prompt with one answer wearing two labels."""
    pool, p1, p2, justice, snowfall, game = _w2g5_filter_game(set_pool, interactive=True)
    game.cast_from_hand(0, "Essence Filter")
    game._settle()

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=0)
    game._settle()

    assert justice not in p1.battlefield
    assert snowfall not in p2.battlefield


def test_essence_filter_takes_the_first_option_headless(set_pool):
    """A non-interactive seat answers where the prompt stands, so a headless or
    AI game never stalls on the choice."""
    pool, p1, p2, justice, snowfall, game = _w2g5_filter_game(set_pool, interactive=False)

    game.cast_from_hand(0, "Essence Filter")
    game._settle()

    assert game.pending_choice_of("mode_choice", 0) is None
    assert justice not in p1.battlefield
    assert snowfall not in p2.battlefield

def _w2g5_stench_game(set_pool, *, interactive):
    """Seat 0 holds Stench of Evil; seat 1 has two Plains and a Forest out."""
    pool = set_pool("ICE")
    plains = Permanent(card=pool["Plains"])
    snowy = Permanent(card=pool["Snow-Covered Plains"])
    forest = Permanent(card=pool["Forest"])
    p1 = PlayerState(name="P1", hand=[pool["Stench of Evil"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[plains, snowy, forest], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0, 1} if interactive else set()
    game._sync_control()
    return pool, p1, p2, (plains, snowy, forest), game


def test_stench_of_evil_destroys_every_plains_and_nothing_else(set_pool):
    """"Destroy all Plains." A Snow-Covered Plains is a Plains (CR 305.6), and
    a Forest is not — the sweep has to hit exactly the first two."""
    pool, p1, p2, (plains, snowy, forest), game = _w2g5_stench_game(
        set_pool, interactive=True
    )

    result = game.cast_from_hand(0, "Stench of Evil")
    game._settle()

    assert result.supported, result.details
    assert plains not in p2.battlefield
    assert snowy not in p2.battlefield
    assert forest in p2.battlefield


def test_stench_of_evil_offers_the_land_controller_one_choice_per_land(set_pool):
    """"For each land destroyed this way, Stench of Evil deals 1 damage to that
    land's controller unless they pay {2}."

    The sweep records what it destroyed and whose it was — before this round it
    recorded nothing at all, so the loop would have found an empty set and the
    card would have reported itself supported having done half its text. Two
    lands died, so two offers, both to their controller and not to the caster.
    """
    pool, p1, p2, _lands, game = _w2g5_stench_game(set_pool, interactive=True)

    game.cast_from_hand(0, "Stench of Evil")
    game._settle()

    assert len(game.pending_choices_of("optional_pay", 1)) == 2
    assert not game.pending_choices_of("optional_pay", 0), "the caster owes nothing"


def test_stench_of_evil_deals_one_damage_per_declined_offer(set_pool):
    """Declining both offers takes 2 damage — one point per land, not one for
    the whole sweep and not one for every land on the board."""
    pool, p1, p2, _lands, game = _w2g5_stench_game(set_pool, interactive=True)
    game.cast_from_hand(0, "Stench of Evil")
    game._settle()

    while game.pending_choices_of("optional_pay", 1):
        assert game.confirm_optional_pay(1, accept=False)
    game._settle()

    assert p2.life == 18
    assert p1.life == 20, "the caster is not the land's controller"


def test_stench_of_evil_spares_a_controller_who_pays(set_pool):
    """And the offer is a real offer: paying the {2} once costs one point of
    the two."""
    pool, p1, p2, _lands, game = _w2g5_stench_game(set_pool, interactive=True)
    p2.mana_pool["C"] = 2
    game.cast_from_hand(0, "Stench of Evil")
    game._settle()

    assert game.confirm_optional_pay(1, accept=True)
    assert game.confirm_optional_pay(1, accept=False)
    game._settle()

    assert p2.life == 19


def test_stench_of_evil_over_a_board_with_no_plains_asks_nothing(set_pool):
    """An empty sweep is an empty loop, not a loop over the whole board: the
    Forest's controller is never offered anything."""
    pool = set_pool("ICE")
    forest = Permanent(card=pool["Forest"])
    p1 = PlayerState(name="P1", hand=[pool["Stench of Evil"]], life=20)
    p2 = PlayerState(name="P2", battlefield=[forest], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game._sync_control()

    game.cast_from_hand(0, "Stench of Evil")
    game._settle()

    assert forest in p2.battlefield
    assert not game.pending_choices_of("optional_pay", 1)
    assert p2.life == 20

def _w2g5_pox_game(set_pool, *, interactive=False):
    """A board built so every one of Pox's four fractions rounds differently.

    Seat 0: 20 life, 4 cards in hand, 3 creatures, 4 lands.
    Seat 1:  7 life, 2 cards in hand, 1 creature, 2 lands.

    Rounded up, that is 7/3 life, 2/1 cards, 1/1 creatures and 2/1 lands — four
    boundaries, and 7 life is the one that separates "a third rounded up" (3)
    from "a third rounded down" (2).
    """
    pool = set_pool("ICE")
    mine = [Permanent(card=pool[n]) for n in (
        "Balduvian Bears", "Tor Giant", "Brown Ouphe",
        "Forest", "Swamp", "Mountain", "Plains",
    )]
    theirs = [Permanent(card=pool[n]) for n in ("Goblin Mutant", "Island", "Forest")]
    p1 = PlayerState(
        name="P1",
        hand=[pool["Pox"]] + [pool[n] for n in (
            "Balduvian Bears", "Tor Giant", "Brown Ouphe", "Goblin Mutant",
        )],
        battlefield=mine, life=20,
    )
    p2 = PlayerState(
        name="P2",
        hand=[pool[n] for n in ("Balduvian Bears", "Tor Giant")],
        battlefield=theirs, life=7,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0, 1} if interactive else set()
    game._sync_control()
    return pool, p1, p2, game


def test_pox_takes_a_third_of_each_life_total_rounded_up(set_pool):
    """"Each player loses a third of their life… Round up each time."

    7 is the boundary: a third of it rounded up is 3 and rounded down is 2. And
    the fraction is per seat — a single number computed off one player's life
    and subtracted from everybody is the shape this had to avoid.
    """
    pool, p1, p2, game = _w2g5_pox_game(set_pool)

    result = game.cast_from_hand(0, "Pox")
    game._settle()

    assert result.supported, result.details
    assert p1.life == 13, "a third of 20, rounded up, is 7"
    assert p2.life == 4, "a third of 7, rounded up, is 3"


def test_pox_discards_a_third_of_each_hand_rounded_up(set_pool):
    """The second clause. Counted after the spell has left the hand — Pox is
    not one of the four cards its caster discards a third of."""
    pool, p1, p2, game = _w2g5_pox_game(set_pool)

    game.cast_from_hand(0, "Pox")
    game._settle()

    assert len(p1.hand) == 2, "a third of 4, rounded up, is 2"
    assert len(p2.hand) == 1, "a third of 2, rounded up, is 1"


def test_pox_sacrifices_a_third_of_the_creatures_and_a_third_of_the_lands(set_pool):
    """The third and fourth clauses, and the two that prove the noun matters:
    the creature sweep must not eat a land and the land sweep must not eat a
    creature."""
    pool, p1, p2, game = _w2g5_pox_game(set_pool)

    game.cast_from_hand(0, "Pox")
    game._settle()

    mine = [perm.card.name for perm in game.controlled_by(0)]
    theirs = [perm.card.name for perm in game.controlled_by(1)]
    assert sum(1 for perm in game.controlled_by(0) if perm.is_creature) == 2, mine
    assert sum(1 for perm in game.controlled_by(0) if perm.has_type("land")) == 2, mine
    assert sum(1 for perm in game.controlled_by(1) if perm.is_creature) == 0, theirs
    assert sum(1 for perm in game.controlled_by(1) if perm.has_type("land")) == 1, theirs


def test_pox_asks_every_seat_and_not_only_the_caster(set_pool):
    """CR 608.2e: each of the four actions is taken by every player. An
    interactive seat is prompted for its own discard, so the opponent owes a
    prompt too — a sweep that only asked its caster would pass every test built
    on one seat."""
    pool, p1, p2, game = _w2g5_pox_game(set_pool, interactive=True)

    game.cast_from_hand(0, "Pox")
    game._settle()

    assert game.pending_choice_of("discard", 0) is not None
    assert game.pending_choice_of("discard", 1) is not None
    assert game.pending_choice_of("discard", 0).data["count"] == 2
    assert game.pending_choice_of("discard", 1).data["count"] == 1


def test_pox_over_an_empty_board_asks_nobody_to_sacrifice(set_pool):
    """A third of nothing is nothing, and CR 608.2 does as much as it can: a
    seat that owes no sacrifice is not handed a prompt it cannot answer."""
    pool = set_pool("ICE")
    p1 = PlayerState(name="P1", hand=[pool["Pox"]], life=3)
    p2 = PlayerState(name="P2", life=3)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game._sync_control()

    result = game.cast_from_hand(0, "Pox")
    game._settle()

    assert result.supported, result.details
    assert p1.life == 2 and p2.life == 2, "a third of 3 is 1"
    assert game.pending_choice_of("sacrifice", 0) is None
    assert game.pending_choice_of("discard", 0) is None

def test_a_type_sweep_records_the_permanents_it_destroyed(set_pool):
    """Not a card: the class Stench of Evil's fix belongs to.

    "For each <noun> destroyed this way, …" reads the objects a sweep recorded,
    and the lowering admits the clause on the strength of the *count* being
    produced. So a sweep that recorded the count and not the objects compiled
    such a card supported and then iterated an empty list. Five type sweeps did
    (`destroy_all_creatures` and its four siblings) and the by-type land sweep
    did not record even the count.

    Checked against a live board rather than against the table, because the
    table is the claim: the record has to be what actually died, and whose it
    was.
    """
    from engine.game_types import OracleExecutionContext
    from engine.handlers.registry import EFFECT_HANDLERS
    from engine.oracle_types import OracleInstruction, PER_OBJECT_SEAT_RECORDS

    pool = set_pool("ICE")
    mine = Permanent(card=pool["Balduvian Bears"])
    theirs = Permanent(card=pool["Tor Giant"])
    land = Permanent(card=pool["Forest"])
    p1 = PlayerState(name="P1", battlefield=[mine, land], life=20)
    p2 = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[p1, p2])
    game._sync_control()
    context = OracleExecutionContext(caster=p1, target=p2, card=pool["Pox"])

    EFFECT_HANDLERS["destroy_all_creatures"](
        game, OracleInstruction("destroy_all_creatures", "", {}), context
    )

    destroyed = context.results["destroyed_this_way_objects"]
    assert context.results["destroyed_this_way"] == 2
    assert {perm.card.name for perm in destroyed} == {"Balduvian Bears", "Tor Giant"}
    seats = context.results[PER_OBJECT_SEAT_RECORDS["controller"]]
    assert seats[mine.permanent_id] == 0
    assert seats[theirs.permanent_id] == 1
    assert land in game.controlled_by(0), "the land was not a creature"
# --- end W2G5 ---


# --- W2G1: pay-or-consequence tolls ---
# Forgotten Lore was begun on wave 1's G4 branch and interrupted; the
# tests are that branch's, with the driver corrected (see the round's
# commit) — kept in this wave's block because this wave is what landed
# them.
def _lore_game(set_pool, graveyard):
    pool = set_pool("ICE")
    p1 = PlayerState(
        name="P1",
        hand=[pool["Forgotten Lore"]],
        graveyard=[pool[name] for name in graveyard],
        life=20,
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    # The repetition's {G} is a real payment even with the cast cost waived:
    # `_player_can_pay_optional` asks the board, and a seat that cannot pay
    # declines whatever it answers.
    p1.mana_pool["G"] = 3
    # Queued and passed rather than cast headlessly, because *this* card is
    # about a resolution that stops to ask: CR 608.2m puts a spell into its
    # owner's graveyard as the **final** part of its resolution, so Forgotten
    # Lore must not be one of the cards its own loop offers. `cast_from_hand`
    # settles the stack in one go and would bin it between the rounds.
    result = game.queue_from_hand(0, "Forgotten Lore", target_player_index=1)
    assert result.supported, result.details
    game.start_priority_window(0)
    game.pass_priority(0)
    game.pass_priority(1)
    return pool, p1, p2, game


def test_forgotten_lore_gives_you_the_card_the_opponent_chose(set_pool):
    """"Target opponent chooses a card in your graveyard. You may pay {G}. …
    Then put the last chosen card into your hand."

    Declining the payment ends the process, and the pick it stopped on is the
    one you keep — however little you wanted it.
    """
    pool, p1, p2, game = _lore_game(set_pool, ["Balduvian Bears", "Dark Ritual"])

    pick = game.pending_choice_of("graveyard_pick_for_price", 1)
    assert pick is not None, "the opponent chooses, not the caster"
    assert sorted(pick.data["legal_indices"]) == [0, 1]

    assert game.confirm_graveyard_pick_for_price(1, 0)
    offer = game.pending_choice_of("optional_pay", 0)
    assert offer is not None, "the price is the caster's to pay"

    assert game.confirm_optional_pay(0, accept=False)

    assert [card.name for card in p1.hand] == ["Balduvian Bears"]
    # Forgotten Lore itself is there too, put in by CR 608.2n as it finished.
    assert sorted(card.name for card in p1.graveyard) == [
        "Dark Ritual", "Forgotten Lore",
    ]


def test_forgotten_lore_repeats_and_cannot_reoffer_a_chosen_card(set_pool):
    """"…repeat this process except that opponent can't choose a card already
    chosen for Forgotten Lore."

    Without the exclusion the loop would offer the same card forever, which is
    a different card — and one the payment could never get past.
    """
    pool, p1, p2, game = _lore_game(
        set_pool, ["Balduvian Bears", "Dark Ritual", "Brown Ouphe"]
    )

    assert game.confirm_graveyard_pick_for_price(1, 0)
    assert game.confirm_optional_pay(0, accept=True)

    second = game.pending_choice_of("graveyard_pick_for_price", 1)
    assert second is not None, "paying repeats the process"
    assert 0 not in second.data["legal_indices"], (
        "the card already chosen is off the list"
    )

    assert game.confirm_graveyard_pick_for_price(1, 1)
    assert game.confirm_optional_pay(0, accept=False)

    assert [card.name for card in p1.hand] == ["Dark Ritual"], (
        "the *last* chosen card, not the first"
    )
    assert sorted(card.name for card in p1.graveyard) == [
        "Balduvian Bears", "Brown Ouphe", "Forgotten Lore",
    ]


def test_forgotten_lore_ends_when_the_graveyard_runs_out(set_pool):
    """The other way out of the loop: "repeat this process" over a graveyard
    with nothing left to choose ends it, and the last pick is still kept."""
    pool, p1, p2, game = _lore_game(set_pool, ["Balduvian Bears"])

    assert game.confirm_graveyard_pick_for_price(1, 0)
    assert game.confirm_optional_pay(0, accept=True)

    assert game.pending_choice_of("graveyard_pick_for_price", 1) is None
    assert [card.name for card in p1.hand] == ["Balduvian Bears"]
    assert [card.name for card in p1.graveyard] == ["Forgotten Lore"]


def test_forgotten_lore_on_an_empty_graveyard_chooses_nothing(set_pool):
    """Nothing to choose at all is not a prompt, and nothing is put anywhere:
    an offer with no legal answer is not an offer."""
    pool, p1, p2, game = _lore_game(set_pool, [])

    assert game.pending_choice_of("graveyard_pick_for_price", 1) is None
    assert p1.hand == []
# --- end W2G1 ---


# --- W3G3: X spells, multiple targets, damage sources ---
def _fumarole_board(set_pool, *, lands=("Forest",)):
    """Seat 0 holds Fumarole; seat 1 holds a creature and the named lands."""
    pool = set_pool("ICE")
    bears = Permanent(card=pool["Balduvian Bears"])
    theirs = [bears] + [Permanent(card=pool[name]) for name in lands]
    p0 = PlayerState(name="P0", hand=[pool["Fumarole"]], life=20)
    p1 = PlayerState(name="P1", battlefield=theirs, life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p0, p1, bears, theirs[1:]


def test_fumarole_destroys_both_of_its_targets_and_pays_the_life(set_pool):
    """One announcement, two targets, and the additional cost charged once."""
    game, p0, _p1, bears, (forest,) = _fumarole_board(set_pool)

    result = game.cast_from_hand(
        0, "Fumarole",
        target_permanent_ids=[bears.permanent_id, forest.permanent_id],
    )
    assert result.supported, result.details
    game._settle()

    assert not game.is_on_battlefield(bears)
    assert not game.is_on_battlefield(forest)
    assert p0.life == 17, "CR 601.2b: the additional cost is paid once, on the cast"


def test_fumarole_asks_for_the_creature_then_the_land(set_pool):
    """The picker walks the roles in order, and each role offers only its own
    noun — a land is not an answer to the creature slot (CR 601.2c)."""
    game, _p0, _p1, _bears, _lands = _fumarole_board(
        set_pool, lands=("Forest", "Mountain")
    )
    pool = set_pool("ICE")

    spec = game.cast_target_spec(0, pool["Fumarole"])
    assert [role["kind"] for role in spec["roles"]] == ["creature", "land"]
    first = spec["valid_targets"]
    assert [option["name"] for option in first] == ["Balduvian Bears"]
    assert sorted(option["name"] for option in first[0]["next"]) == ["Forest", "Mountain"]


def test_fumarole_cannot_be_cast_with_no_land_to_name(set_pool):
    """CR 601.2c: every target is chosen as part of one announcement, so a role
    with nothing legal in it is not "the spell resolves half way" — the spell
    cannot be announced at all."""
    game, _p0, _p1, bears, _lands = _fumarole_board(set_pool, lands=())

    refused = game.cast_from_hand(
        0, "Fumarole", target_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported
    assert "target" in refused.details.lower()


def test_fumarole_destroys_the_target_that_is_still_there(set_pool):
    """CR 608.2b: the spell leaves the stack unresolved only when **every**
    target is illegal. One of two gone is one still destroyed — an all-or-
    nothing re-check would have Fumarole fizzle whole."""
    game, _p0, p1, bears, (forest,) = _fumarole_board(set_pool)

    result = game.queue_from_hand(
        0, "Fumarole",
        target_permanent_ids=[bears.permanent_id, forest.permanent_id],
    )
    assert result.supported, result.details
    game.remove_from_battlefield(forest)
    game._settle()

    assert not game.is_on_battlefield(bears)


def test_a_union_mixing_targets_and_a_sweep_is_refused():
    """Two targets plus a swept set is not one announcement.

    A single target beside a sweep is unchanged — that is still a conjunction of
    two statements, and only the first names anything for a picker to ask about.
    What refuses is the shape whose roles description would have to leave the
    sweep out: "target creature, target land, and all artifacts" would compile
    supported and quietly destroy no artifacts.
    """
    from engine.grammar import compile_line

    assert compile_line("Destroy target creature and target land.").parsed
    assert compile_line("Destroy target creature and all lands.").parsed
    mixed = compile_line("Destroy target creature, target land, and all artifacts.")
    assert not mixed.parsed
    assert "one announcement" in (mixed.parse_error or "")


def _spoils_board(set_pool, *, graveyard, mine=("Balduvian Bears", "Tor Giant")):
    pool = set_pool("ICE")
    lea = set_pool("LEA")
    creatures = [Permanent(card=pool[name]) for name in mine]
    p0 = PlayerState(
        name="P0", hand=[pool["Spoils of War"]], battlefield=creatures, life=20,
    )
    p1 = PlayerState(
        name="P1", life=20,
        graveyard=[(pool.get(n) or lea[n]) for n in graveyard],
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, creatures


def test_spoils_of_war_defines_its_own_x_off_the_opponents_graveyard(set_pool):
    """"X is the number of artifact and/or creature cards in an opponent's
    graveyard as you cast this spell." (CR 107.3c.)

    The caster never announces it — the cast path computes it, the same way an
    activated ability's printed "X is …" is computed one table over. The picker
    is told the number too (``defined_x``), because a divided spell's caster
    needs it *before* announcing the division (CR 601.2d) and a browser that
    asked for X would have got a different one.
    """
    from engine.oracle import compile_card_oracle

    game, _mine = _spoils_board(
        set_pool,
        graveyard=("Balduvian Bears", "Black Lotus", "Mountain", "Tor Giant"),
    )
    spoils = set_pool("ICE")["Spoils of War"]
    assert compile_card_oracle(spoils).supported

    spec = game.cast_target_spec(0, spoils)
    assert spec["defined_x"] == 3, "the Mountain is neither an artifact nor a creature"


def test_spoils_of_war_distributes_the_counters_as_announced(set_pool):
    """"Distribute X +1/+1 counters among any number of target creatures."

    CR 601.2d's counter half, travelling on the same ``divided_targets`` list a
    divided damage spell's shares do.
    """
    game, (bears, giant) = _spoils_board(
        set_pool,
        graveyard=("Balduvian Bears", "Black Lotus", "Mountain", "Tor Giant"),
    )

    result = game.cast_from_hand(
        0, "Spoils of War", divided_targets=[(0, 0, 1), (0, 1, 2)],
    )
    assert result.supported, result.details
    game._settle()

    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    assert (giant.effective_power, giant.effective_toughness) == (5, 5)


def test_an_even_distribution_would_have_answered_differently(set_pool):
    """The boundary. Three counters over two creatures, unannounced, is one
    each and one lost to the rounding — so the 1/2 split above is not what an
    engine ignoring the announcement would have done."""
    game, (bears, giant) = _spoils_board(
        set_pool,
        graveyard=("Balduvian Bears", "Black Lotus", "Mountain", "Tor Giant"),
    )

    game.cast_from_hand(0, "Spoils of War", divided_targets=[(0, 0), (0, 1)])
    game._settle()

    assert (bears.effective_power, giant.effective_power) == (3, 4)


def test_the_distribution_must_total_the_defined_x(set_pool):
    """CR 601.2d against a number the *card* fixed: the caster cannot announce
    a division of the X they would have liked."""
    game, _mine = _spoils_board(
        set_pool, graveyard=("Balduvian Bears", "Black Lotus", "Tor Giant"),
    )

    refused = game.cast_from_hand(
        0, "Spoils of War", divided_targets=[(0, 0, 1), (0, 1, 1)],
    )
    assert not refused.supported and "total 3" in refused.details
# --- end W3G3 ---


# --- W3G4: coin flips, ante, noted mana ---
def _chaos_game(set_pool, interactive=(0, 1)):
    """Game of Chaos in hand, both seats at 20, both able to answer a prompt."""
    pool = set_pool("ICE")
    p0 = PlayerState(name="P0", hand=[pool["Game of Chaos"]], life=20)
    p1 = PlayerState(name="P1", life=20)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = set(interactive)
    return game, p0, p1


def test_game_of_chaos_pays_the_winner_and_lets_the_winner_decide(set_pool):
    """"Flip a coin. If you win the flip, you gain 1 life and target opponent
    loses 1 life, and **you** decide whether to flip again."

    Who decides is the half a composed lowering cannot carry: it is not the
    caster, it is whoever the *result* named. Both outcomes are checked,
    because a handler that always offered the caster passes the winning one.
    """
    from unittest.mock import patch

    game, p0, p1 = _chaos_game(set_pool)
    with patch("engine.handlers._common.random.random", return_value=0.0):
        game.cast_from_hand(0, "Game of Chaos", target_player_index=1)
        game._settle()

    assert (p0.life, p1.life) == (21, 19)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("flip_again", 0)
    ]


def test_losing_the_flip_hands_the_decision_to_the_opponent(set_pool):
    """"If you lose the flip, you lose 1 life and that opponent gains 1 life,
    and **that player** decides whether to flip again." """
    from unittest.mock import patch

    game, p0, p1 = _chaos_game(set_pool)
    with patch("engine.handlers._common.random.random", return_value=0.99):
        game.cast_from_hand(0, "Game of Chaos", target_player_index=1)
        game._settle()

    assert (p0.life, p1.life) == (19, 21)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("flip_again", 1)
    ]


def test_the_life_stakes_double_with_each_flip(set_pool):
    """"Double the life stakes with each flip." One, then two, then four — so
    three winning flips take the caster from 20 to 27 and the opponent to 13.
    The first flip is for the printed number: the doubling applies to the round
    the *offer* buys, which is what the prompt's stake says.
    """
    from unittest.mock import patch

    game, p0, p1 = _chaos_game(set_pool)
    with patch("engine.handlers._common.random.random", return_value=0.0):
        game.cast_from_hand(0, "Game of Chaos", target_player_index=1)
        game._settle()
        assert game.pending_choice_of("flip_again", 0).data["stake"] == 2

        game.confirm_flip_again(0, accept=True)
        game._settle()
        assert (p0.life, p1.life) == (23, 17)
        assert game.pending_choice_of("flip_again", 0).data["stake"] == 4

        game.confirm_flip_again(0, accept=True)
        game._settle()
        assert (p0.life, p1.life) == (27, 13)

        game.confirm_flip_again(0, accept=False)
        game._settle()

    assert (p0.life, p1.life) == (27, 13)
    assert game.pending_choices == []
    assert game.effect_suspended is False
    assert game.stack == []


def test_a_headless_seat_stops_after_one_flip(set_pool):
    """The stated default, and the reason it is stated: the offer doubles the
    stake every round and the flip is even money, so "yes" is not a default, it
    is a game that never ends. The resolution still finishes."""
    from unittest.mock import patch

    game, p0, p1 = _chaos_game(set_pool, interactive=())
    with patch("engine.handlers._common.random.random", return_value=0.99):
        game.cast_from_hand(0, "Game of Chaos", target_player_index=1)
        game._settle()

    assert (p0.life, p1.life) == (19, 21)
    assert game.pending_choices == []
    assert game.effect_suspended is False


def test_the_paragraph_refuses_when_its_four_stakes_disagree(set_pool):
    """The four printed amounts are one quantity. A production that let them
    differ would compile a card nobody printed, and the stake the handler runs
    at would be whichever of the four the lowering happened to read."""
    from engine.grammar import compile_line

    result = compile_line(
        "Flip a coin. If you win the flip, you gain 1 life and target opponent "
        "loses 2 life, and you decide whether to flip again. If you lose the "
        "flip, you lose 1 life and that opponent gains 1 life, and that player "
        "decides whether to flip again. Double the life stakes with each flip."
    )

    assert not result.parsed


def test_the_doubling_sentence_is_read_rather_than_consumed(set_pool):
    """It is optional in the production and load-bearing in the payload: a card
    printing the same first three sentences without it keeps a constant stake,
    which is a real card one sentence shorter. Consumed-and-dropped would make
    the words free to delete with no change to what runs, which is the
    dropped-rider bug the deletion probe exists for."""
    from engine.grammar import compile_line

    without = compile_line(
        "Flip a coin. If you win the flip, you gain 1 life and target opponent "
        "loses 1 life, and you decide whether to flip again. If you lose the "
        "flip, you lose 1 life and that opponent gains 1 life, and that player "
        "decides whether to flip again."
    )

    assert without.lowered
    payload = without.instructions[0].payload
    assert payload["stake"] == 1
    assert payload["doubling"] is False


def test_the_printed_target_opponent_survives_the_lowering(set_pool):
    """The other rider in the same paragraph, and the one that *was* dropped.

    The production reads "and target opponent loses N life" as fixed words, so
    the two that matter — "target opponent" — were consumed and thrown away:
    the handler asks ``context.target`` for the seat it stakes against, nothing
    described the choice, and the picker therefore never ran. In a duel the one
    opponent is the right answer by luck; at three or four seats the spell
    staked whichever opponent the resolution happened to carry.

    CR 601.2c chooses that seat as the spell is cast, so the description belongs
    in the payload where every reader — picker, cast gate, AI — already looks
    for one.
    """
    from engine.grammar import compile_line
    from engine.targeting import _from_targets_payload

    lowered = compile_line(
        "Flip a coin. If you win the flip, you gain 1 life and target opponent "
        "loses 1 life, and you decide whether to flip again. If you lose the "
        "flip, you lose 1 life and that opponent gains 1 life, and that player "
        "decides whether to flip again. Double the life stakes with each flip."
    )

    targets = lowered.instructions[0].payload["targets"]
    assert targets["quantifier"] == "target"
    assert _from_targets_payload(targets) == {
        "kind": "player", "opponents_only": True,
    }


def test_game_of_chaos_asks_which_opponent_it_is_played_against(set_pool):
    """And the whole point of describing it: the spell derives its own prompt.

    Read through ``derive_cast_spec`` rather than off the payload, because the
    payload is what the previous test pins — this is the consumer, and a
    description no picker reads would be a rider dropped one step later.
    """
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    card = set_pool("ICE")["Game of Chaos"]

    assert derive_cast_spec(card, compile_card_oracle(card)) == {
        "kind": "player", "opponents_only": True,
    }
# --- end W3G4 ---


# --- W3G2: combat control and attack requirements ---
def _w3g2_gaze_board(set_pool):
    """Gaze of Pain in hand, one attacker, and on the other side a creature to
    aim at plus a Wall to block with.

    Seat 0 is interactive so the two prompts the ability owes — its target and
    the "you may" — *queue* rather than take their defaults at once, which is
    also what makes combat wait for them (CR 608.2, ``_combat_awaits_an_answer``).
    """
    pool = set_pool("ICE")
    attacker = Permanent(card=pool["Balduvian Bears"])   # 2/2
    victim = Permanent(card=pool["Balduvian Bears"])
    blocker = Permanent(card=pool["Glacial Wall"])       # 0/7 defender
    game = Game(players=[
        PlayerState(
            name="P0", battlefield=[attacker], life=20,
            hand=[pool["Gaze of Pain"]],
        ),
        PlayerState(name="P1", battlefield=[victim, blocker], life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._settle()
    game.start_turn(0)
    for perm in (attacker, victim, blocker):
        perm.metadata["summoning_sickness_turn"] = -99
    return game, attacker, victim, blocker


def _w3g2_gaze_combat(game, blocker, *, block):
    """Cast the sorcery, attack, declare (or decline) the block, and stop at
    the moment blocks lock — which is where the delayed ability fires."""
    assert game.cast_from_hand(0, "Gaze of Pain").supported
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()   # declare blockers
    slot = next(
        i for i, perm in enumerate(game.controlled_by(game.players[1]))
        if perm is blocker
    )
    assert game.declare_blockers(1, {slot: [0]} if block else {})[0]
    game._settle()
    game.advance_combat_phase()   # blocks lock: the delayed ability fires here
    return list(game.pending_choices_of("trigger_target"))


def _w3g2_finish_combat(game):
    for _ in range(len(list(game._phase_steps("combat"))) + 1):
        if game.current_turn_phase != "combat":
            break
        before = (game.current_turn_phase, game.current_step)
        game.advance_combat_phase()
        game._settle()
        if (game.current_turn_phase, game.current_step) == before:
            break
    game.check_state_based_actions()


def test_w3g2_gaze_of_pain_is_supported(set_pool):
    """One line, three things: a delayed ability with a stated duration
    (CR 603.7b), an event nothing announced before it, and a "may" whose
    rider is the second half of the card."""
    program = compile_card_oracle(set_pool("ICE")["Gaze of Pain"])

    assert program.supported
    assert [i.kind for i in program.instructions] == ["create_delayed_trigger"]
    assert program.instructions[0].payload["event"] == "creature_attacks_unblocked"
    assert program.instructions[0].payload["once"] is False


def test_w3g2_gaze_of_pain_bites_instead_of_connecting(set_pool):
    """Taking the offer: the attacker deals its power to the chosen creature
    and then assigns no combat damage — so the defending player's life is
    what proves the rider ran, not a flag."""
    game, attacker, victim, blocker = _w3g2_gaze_board(set_pool)

    pending = _w3g2_gaze_combat(game, blocker, block=False)

    assert len(pending) == 1, game.log
    offered = {t["permanent_id"] for t in pending[0].data["targets"]}
    assert victim.permanent_id in offered
    assert game.confirm_trigger_target(0, victim.permanent_id)
    game._settle()
    assert game.confirm_optional_pay(0, "Gaze of Pain", accept=True)
    _w3g2_finish_combat(game)

    assert not any(
        perm is victim for perm in game.controlled_by(game.players[1])
    ), game.log
    assert game.players[1].life == 20, game.log


def test_w3g2_declining_the_gaze_leaves_the_combat_damage_alone(set_pool):
    """"If you do" — the other half. Nothing bitten, so the rider never runs
    and the 2/2 connects for two."""
    game, attacker, victim, blocker = _w3g2_gaze_board(set_pool)

    pending = _w3g2_gaze_combat(game, blocker, block=False)
    assert game.confirm_trigger_target(0, victim.permanent_id)
    game._settle()
    assert game.confirm_optional_pay(0, "Gaze of Pain", accept=False)
    _w3g2_finish_combat(game)

    assert victim.damage_marked == 0
    assert game.players[1].life == 18, game.log


def test_w3g2_a_blocked_attacker_never_wakes_the_gaze(set_pool):
    """The event is CR 509.1h — an attacker nobody blocked — so a blocked one
    offers nothing at all. Its own event rather than a narrowing of the attack
    declaration for exactly this: at CR 508.1 no blocker has been declared and
    the question cannot yet be answered."""
    game, attacker, victim, blocker = _w3g2_gaze_board(set_pool)

    pending = _w3g2_gaze_combat(game, blocker, block=True)

    assert pending == [], game.log
    assert not game.pending_optional_pays
    _w3g2_finish_combat(game)
    assert victim.damage_marked == 0
    assert game.players[1].life == 20


def test_w3g2_the_gaze_watches_only_its_casters_creatures(set_pool):
    """"a creature **you control**" — the delayed entry carries the printed
    noun phrase, and `DelayedTrigger.matches` tests it against the seat that
    armed it. An opponent's unblocked attacker is not the event."""
    game, attacker, victim, blocker = _w3g2_gaze_board(set_pool)
    assert game.cast_from_hand(0, "Gaze of Pain").supported
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()

    entry = game.delayed_triggers[0]
    assert entry.event == "creature_attacks_unblocked"
    assert entry.subject_filter == {"type_filter": "creature", "controller": "you"}
    assert entry.controller_index == 0
    assert not entry.matches(game, "creature_attacks_unblocked", victim)
    assert entry.matches(game, "creature_attacks_unblocked", attacker)
# --- end W3G2 ---


# --- W4G3: X spent by colour, and the life-gain cap ---
def _soul_burn_game(set_pool, pool_mana, *, victim_life=20, creature=None):
    """Soul Burn in hand, mana in the pool, and costs **enforced**.

    Enforced deliberately, and it is the whole of what these tests measure:
    "the amount of {B} spent on X" is a fact about the payment, so a game that
    charges nothing gains nothing here — correctly, and uselessly. The mana in
    the pool is the experiment.
    """
    ice = set_pool("ICE")
    p0 = PlayerState(name="P0", hand=[ice["Soul Burn"]], life=20)
    p1 = PlayerState(
        name="P1", life=victim_life,
        battlefield=[Permanent(card=ice[creature])] if creature else [],
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = True
    game._sync_control()
    p0.mana_pool = dict(pool_mana)
    return game, p0, p1


def _cast_soul_burn(game, x_value, *, at_creature=False):
    result = game.cast_from_hand(
        0, "Soul Burn", x_value=x_value, target_player_index=1,
        **({"target_permanent_index": 0} if at_creature else {}),
    )
    assert result.supported, result.details
    game._settle()
    return result


def test_soul_burn_is_supported_and_composes_rather_than_fusing(set_pool):
    """"Spend only black and/or red mana on X." / "Soul Burn deals X damage to
    any target. You gain life equal to the damage dealt, but not more than the
    amount of {B} spent on X, the player's life total before the damage was
    dealt, the planeswalker's loyalty before the damage was dealt, or the
    creature's toughness."

    Declined twice before this. What was actually missing, freshly counted:

    * the colour reader held **one** symbol, so "black and/or red" came back as
      the same answer as "no restriction at all" and the restriction went
      unenforced rather than refusing;
    * "the amount of {B} spent on X" is an *allocation*, not a record — this
      card costs {X}{2}{B}, so a black unit missing from the pool may have paid
      the mandatory pip, the generic {2} or X, and a pool delta cannot tell
      those apart;
    * the cap sentence had no production, and Drain Life — which prints it with
      one term fewer — was riding a name-keyed hook for it.

    The pre-damage snapshots (items 3 and 4 of the original scoping) were
    already built by the round that fixed Drain Life's uncapped life.

    Two instructions, not a fused kind: the damage records what it dealt and
    the gain reads it back, which is what lets the cap be part of the gain
    while the damage dealt stays whole (lifelink and every damage trigger read
    the latter).
    """
    program = compile_card_oracle(set_pool("ICE")["Soul Burn"])
    assert program.supported

    (effect,) = [i for i in program.instructions if i.kind != "spell_pattern"]
    assert effect.kind == "sequence"
    damage, gain = effect.payload["steps"]
    assert damage.kind == "deal_damage"
    assert damage.payload["targets"]["quantifier"] == "any_target"
    assert gain.kind == "target_gains_life"
    assert gain.payload["amount_from"] == "damage_dealt"
    assert gain.payload["capped_by"] == [
        {"kind": "recipient_capacity",
         "recipients": ["player", "planeswalker", "creature"]},
        {"kind": "mana_spent_on_x", "symbol": "B"},
    ]


def test_soul_burn_x_may_be_paid_with_either_colour(set_pool):
    """"Spend only black and/or red mana on X."

    Both halves of the restriction in one board: the pool holds no black beyond
    the mandatory {B} pip, so every point of X is red — which the card allows,
    and which the old single-symbol reader could not express at all.
    """
    game, p0, p1 = _soul_burn_game(set_pool, {"B": 1, "R": 3, "G": 2})

    _cast_soul_burn(game, 3)

    assert p1.life == 17, "three damage, paid for with red"
    assert p0.life == 20, "no {B} on X, so no life"


def test_soul_burn_x_cannot_be_paid_with_a_colour_the_card_excludes(set_pool):
    """The other end of it: green is in the pool and green is not on the list,
    so the {2} is payable and X is not. Refused with nothing spent (CR 601.2h:
    an unpayable cost can't be paid), rather than cast for a cheaper X."""
    game, p0, _p1 = _soul_burn_game(set_pool, {"B": 1, "G": 5})

    result = game.cast_from_hand(0, "Soul Burn", x_value=3, target_player_index=1)

    assert not result.supported
    assert "X can be paid only with" in result.details
    assert p0.mana_pool == {"B": 1, "G": 5}, "a refused cast spends nothing"


def test_soul_burn_gains_no_more_than_the_black_mana_spent_on_x(set_pool):
    """"…but not more than the amount of {B} spent on X…"

    The term the whole round is about, at its boundary. Two black in the pool:
    one pays the mandatory {B} of {X}{2}{B} and exactly one is left for X, so
    three damage gains one life. A cast that measured the black *missing from
    the pool* instead would say two and gain twice what the card allows.
    """
    game, p0, p1 = _soul_burn_game(set_pool, {"B": 2, "R": 5})

    _cast_soul_burn(game, 3)

    assert p1.life == 17, "three damage either way"
    assert p0.life == 21, "one black reached X, so one life"


def test_soul_burn_gains_no_more_than_the_targets_life_total(set_pool):
    """"…the player's life total **before the damage was dealt**…"

    Read before, because the damage is exactly what changes the number the card
    measures against: an opponent on 2 taking 3 is on -1, and reading the life
    total afterwards would gain nothing at all.
    """
    game, p0, _p1 = _soul_burn_game(set_pool, {"B": 6}, victim_life=2)

    _cast_soul_burn(game, 3)

    assert p0.life == 22, "three black on X, but the opponent had only two life"


def test_soul_burn_gains_no_more_than_the_creatures_toughness(set_pool):
    """"…or the creature's toughness." Three damage at a 2/2 gains two, with
    three black spent on X and nothing else binding."""
    game, p0, _p1 = _soul_burn_game(set_pool, {"B": 6}, creature="Balduvian Bears")

    _cast_soul_burn(game, 3, at_creature=True)

    assert p0.life == 22


def test_soul_burn_gains_the_whole_amount_when_nothing_caps_it(set_pool):
    """The baseline the four tests above are measured against: a cap only
    proves itself where the uncapped answer would have differed."""
    game, p0, p1 = _soul_burn_game(set_pool, {"B": 6, "R": 2})

    _cast_soul_burn(game, 3)

    assert p1.life == 17
    assert p0.life == 23, "three black on X, an opponent on 20 — nothing binds"
# --- end W4G3 ---


# --- FixC: a sweep names a class, not a target ---
def test_jokulhaups_names_three_classes_and_chooses_none_of_them(set_pool):
    """"Destroy all artifacts, creatures, and lands." CR 115.1a: a sorcery is
    targeted only where its ability says "target".

    The union lowers to ``type_filter: ["artifact", "creature", "land"]``, and
    the target derivation read a union as the general permanent picker — so
    the browser demanded a click on one permanent before letting a spell
    destroy every one of them. The click was ignored; the sweep never reads a
    target.
    """
    lea = set_pool("LEA")
    mine = Permanent(card=lea["Mox Ruby"])
    theirs = [Permanent(card=lea["Scathe Zombies"]), Permanent(card=lea["Forest"])]
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("ICE")["Jokulhaups"]],
                    battlefield=[mine]),
        PlayerState(name="P2", battlefield=theirs),
    ])
    game.enforce_mana_costs = False
    game._sync_control()

    assert game.cast_target_spec(0, set_pool("ICE")["Jokulhaups"]) == {
        "kind": "none", "requires_target": False, "valid_targets": [],
    }

    result = game.cast_from_hand(0, "Jokulhaups")
    game._settle()

    assert result.supported, result.details
    assert game.players[0].battlefield == []
    assert game.players[1].battlefield == []


def test_jokulhaups_resolves_over_an_empty_board(set_pool):
    """Nothing to destroy is not nothing to cast."""
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("ICE")["Jokulhaups"]]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False

    result = game.cast_from_hand(0, "Jokulhaups")
    game._settle()

    assert result.supported, result.details
    assert game.stack == []
def test_pox_hits_each_player_and_lets_none_of_them_be_picked(set_pool):
    """The same defect through a different payload key. "Each player loses a
    third of their life" lowers to a life loss whose ``recipient`` is *each
    player*, and the kind was answered flat as ``{"kind": "player"}`` — so the
    caster was handed a seat picker for an effect that hits everybody, and
    whichever seat was clicked went nowhere.
    """
    game = Game(players=[PlayerState(name="P1", hand=[set_pool("ICE")["Pox"]]),
                         PlayerState(name="P2")])
    game.enforce_mana_costs = False
    p1, p2 = game.players

    assert game.cast_target_spec(0, set_pool("ICE")["Pox"]) == {
        "kind": "none", "requires_target": False, "valid_targets": [],
    }

    result = game.cast_from_hand(0, "Pox")
    game._settle()

    assert result.supported, result.details
    assert (p1.life, p2.life) == (13, 13)   # both, symmetrically
# --- end FixC ---

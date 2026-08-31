"""Ice Age (ICE) sorcery cards.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
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
def test_w1g3_fumarole_is_declined_on_its_second_target_not_its_cost(set_pool):
    """"As an additional cost to cast this spell, pay 3 life." / "Destroy target
    creature and target land."

    The cost half already works — ``cast_costs``'s preamble-plus-clause table
    names Fumarole in its own docstring, and the refusal report's "expected a
    subject" on that line is the *grammar* declining a sentence the cost table
    claims, not a gap. What is missing is the second target, and it is missing
    in four places rather than one:

    1. ``effects/board._parse_further_subjects`` raises "no spell picks two
       targets from one verb" on purpose;
    2. ``targeting.derive_cast_spec`` answers with a single ``kind``, so the
       picker has no way to ask for a creature *and* a land;
    3. the wire carries one ``target_permanent_index`` per cast, and
       ``target_permanent_ids`` is a list of ids for *one* described set;
    4. ``legality.cast_target_refusal`` and ``illegal_targets_refusal`` are
       written around one target list from one instruction (CR 601.2c,
       CR 608.2b), and two heterogeneous targets need both checked separately.

    Landing the parse alone would compile the card supported and leave it
    uncastable, its second target picked by nobody.
    """
    from engine.cast_costs import additional_costs
    from engine.grammar import compile_line

    fumarole = set_pool("ICE")["Fumarole"]
    assert not compile_card_oracle(fumarole).supported

    # The cost is read and would be charged.
    (cost,) = additional_costs(fumarole)
    assert cost.pay_life == 3

    refused = compile_line("Destroy target creature and target land.")
    assert not refused.parsed
    assert "two targets" in (refused.parse_error or "")


def test_w1g3_soul_burn_is_declined_and_says_which_pieces_are_missing(set_pool):
    """"Spend only black and/or red mana on X." / "Soul Burn deals X damage to
    any target. You gain life equal to the damage dealt, but not more than the
    amount of {B} spent on X, the player's life total before the damage was
    dealt, the planeswalker's loyalty before the damage was dealt, or the
    creature's toughness."

    Four pieces, and the second sentence is *nearly* there — without the cap it
    lowers today, which is exactly why the cap must not be dropped: the life
    gain would be unbounded.

    1. ``oracle_types.x_spend_color_from_text`` returns **one** symbol (Drain
       Life's "Spend only black mana on X"). This card names two, and the
       payment reader takes ``x_color`` as a single symbol through
       ``_parse_mana_cost`` and ``_infer_x_value``.
    2. "the amount of **{B}** spent on X" — the casting path keeps no record of
       *which* symbols paid a cast. The activation path measures one now
       (``mana_spent_for_cost``); its casting twin does not exist.
    3. "the player's life total / the planeswalker's loyalty / the creature's
       toughness **before the damage was dealt**" — nothing snapshots a
       recipient's pre-damage state for a later clause to read.
    4. "but not more than A, B, C, or D" — the grammar has no minimum-of-several
       amount node at all.
    """
    from engine.grammar import compile_line
    from engine.oracle_types import x_spend_color_from_text

    assert not compile_card_oracle(set_pool("ICE")["Soul Burn"]).supported

    # Piece 1: one colour is read, a pair is not.
    assert x_spend_color_from_text("Spend only black mana on X.") == "B"
    assert x_spend_color_from_text("Spend only black and/or red mana on X.") is None

    # Pieces 2-4: the sentence without its cap already lowers, so the cap is
    # the whole of what is left — and dropping it would gain unbounded life.
    uncapped = compile_line(
        "Soul Burn deals X damage to any target. You gain life equal to the "
        "damage dealt.",
        card_name="Soul Burn",
    )
    assert uncapped.lowered
    capped = compile_line(
        "Soul Burn deals X damage to any target. You gain life equal to the "
        "damage dealt, but not more than the amount of {B} spent on X, the "
        "player's life total before the damage was dealt, the planeswalker's "
        "loyalty before the damage was dealt, or the creature's toughness.",
        card_name="Soul Burn",
    )
    assert not capped.parsed
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
def test_a_union_of_two_targeted_phrases_is_refused(set_pool):
    """"Destroy target creature and target land." (Fumarole.)

    The union reads it, and the *picker* cannot: a spell is asked for one
    target (``targeting.derive_cast_spec`` answers with one kind), so admitting
    this would compile a card that is supported and uncastable, its second
    target chosen by nobody. It refuses naming that, and the two cards above are
    unaffected because their first phrase is the source rather than a target.
    """
    program = compile_card_oracle(set_pool("ICE")["Fumarole"])

    assert not program.supported


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

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

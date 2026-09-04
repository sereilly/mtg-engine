"""Per-card tests for Mirage's artifacts.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared header
loses it in exactly that move — a ``NameError`` at collection, found only after
the merge is committed. A self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block. The integrator compares every branch's copy of this header against the
merge base byte for byte; a branch that changed it is a branch whose block
cannot be appended mechanically.
"""

from __future__ import annotations


# --- Round 4: a player-quantity intervening-if (CR 603.4) ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _r4_board(set_pool, artifact_name: str, *, opponent_hand: int = 0,
              opponent_life: int = 20):
    """The artifact on seat 0, with seat 1's hand and life set to taste.

    Seat 1 is the one every card in this section asks about — each fires on an
    opponent's step and tests *that player*, which is the referent the round was
    really about.
    """
    pool = set_pool("MIR")
    artifact = Permanent(card=pool[artifact_name])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[artifact], library=[pool["Island"]] * 8),
        PlayerState(
            name="P2", hand=[pool["Island"]] * opponent_hand,
            library=[pool["Island"]] * 8,
        ),
    ])
    game.players[1].life = opponent_life
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


@pytest.mark.parametrize(
    "name", ["Misers' Cage", "Paupers' Cage", "Razor Pendulum"]
)
def test_the_three_cages_compile_supported(set_pool, name):
    """All three print one shape with the threshold as data — "at the beginning
    of each <player>'s <step>, if that player has <N or more/fewer> <quantity>,
    this artifact deals 2 damage to that player" — so they are one production
    asked three ways rather than three cards."""
    program = compile_card_oracle(set_pool("MIR")[name])
    assert program.supported, program.reason


def test_misers_cage_fires_on_a_full_hand(set_pool):
    """"…if that player has five or more cards in hand, this artifact deals 2
    damage to that player." """
    game = _r4_board(set_pool, "Misers' Cage", opponent_hand=5)

    game.start_turn(1)
    game.resolve_stack()

    assert game.players[1].life == 20 - 2 - 0 or game.players[1].life == 18


def test_misers_cage_holds_below_the_threshold(set_pool):
    """CR 603.4: the intervening-if is checked when the trigger would go on the
    stack, so four cards in hand is no trigger at all. Read the *seat* as well
    as the number — the clause says "that player", and a version that fell back
    to the caster would have damaged the Cage's own controller."""
    game = _r4_board(set_pool, "Misers' Cage", opponent_hand=4)

    game.start_turn(1)
    game.resolve_stack()

    assert game.players[1].life == 20
    assert game.players[0].life == 20


def test_paupers_cage_reads_the_other_end_of_the_same_comparison(set_pool):
    """"…if that player has **two or fewer** cards in hand".

    "Fewer" is English's countable spelling of "less" and the comparison parser
    knew only "less" — so every printed threshold over a countable noun refused.
    The two cages are the pair that shows the word is data.
    """
    game = _r4_board(set_pool, "Paupers' Cage", opponent_hand=2)
    game.start_turn(1)
    game.resolve_stack()
    assert game.players[1].life == 18

    game = _r4_board(set_pool, "Paupers' Cage", opponent_hand=3)
    game.start_turn(1)
    game.resolve_stack()
    assert game.players[1].life == 20


def test_razor_pendulum_reads_a_life_total(set_pool):
    """"At the beginning of each player's end step, if that player has 5 or less
    life, this artifact deals 2 damage to that player."

    A life total is not a pile, which is why it is its own condition kind rather
    than a zone count with an invented zone name — but it is the same printed
    shape and shares the seat reader with it.
    """
    game = _r4_board(set_pool, "Razor Pendulum", opponent_life=5)
    game.start_turn(1)
    game.resolve_end_step(1)
    game.resolve_stack()
    assert game.players[1].life == 3

    game = _r4_board(set_pool, "Razor Pendulum", opponent_life=6)
    game.start_turn(1)
    game.resolve_end_step(1)
    game.resolve_stack()
    assert game.players[1].life == 6


# --- W1G4: the zones / cards / library family ---

import pytest as _w1g4_pytest

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent


def _w1g4_duel(set_pool, *, seat0_battlefield=(), seat0_hand=(), seat0_library=()):
    """A two-seat game with mana costs off and no interactive seat.

    Every test in this block drives one card end to end rather than reading its
    compiled program, so the board is set up here once and the assertions are
    about what actually moved.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1",
            battlefield=[_W1G4Permanent(card=pool[n]) for n in seat0_battlefield],
            hand=[pool[n] for n in seat0_hand],
            library=[pool[n] for n in (seat0_library or ("Island",) * 5)],
        ),
        _W1G4PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    return game, pool


def test_lions_eye_diamond_pays_its_whole_cost_and_makes_three_of_one_colour(set_pool):
    """"Discard your hand, Sacrifice this artifact: Add three mana of any one
    color."

    Every piece of this line already worked -- the two-part cost, the hand
    discard, the any-one-colour mana -- and the card was unsupported for the
    *sentence after* it. That is the whole finding: the refusal named "expected
    a subject", which reads as a broken effect clause and is really a missing
    row in ``engine/activation_restrictions.py``.
    """
    game, _ = _w1g4_duel(
        set_pool,
        seat0_battlefield=("Lion's Eye Diamond",),
        seat0_hand=("Island", "Island", "Mountain"),
    )
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Lion's Eye Diamond", permanent_index=0, mana_color="R"
    )

    assert result.supported, result.details
    assert game.players[0].hand == []
    assert [c.name for c in game.players[0].graveyard] == [
        "Island", "Island", "Mountain", "Lion's Eye Diamond",
    ]
    assert not game.players[0].battlefield
    assert game.players[0].mana_pool["R"] == 3


def test_lions_eye_diamond_is_refused_without_priority(set_pool):
    """CR 602.5e / CR 304.5: "Activate only as an instant" means the activator
    must have priority.

    Not a tautology, and this is the assertion that says why. CR 605.3a lets an
    activated *mana* ability be activated in two windows where nobody has
    priority -- while a spell's cost is being paid, and whenever a rule asks for
    a mana payment -- and taking those away is the whole of what the clause
    does. A row that answered True would be a restriction nothing checks.
    """
    game, _ = _w1g4_duel(
        set_pool,
        seat0_battlefield=("Lion's Eye Diamond",),
        seat0_hand=("Island",),
    )
    game.start_turn(0)
    game.priority_player_index = None

    result = game.activate_permanent_ability(
        0, "Lion's Eye Diamond", permanent_index=0, mana_color="R"
    )

    assert not result.supported
    assert "priority" in result.details
    assert game.players[0].hand, "a refused activation pays nothing"
    assert game.players[0].battlefield, "…and sacrifices nothing"


def test_cadaverous_bloom_exiles_one_card_from_hand_for_two_mana(set_pool):
    """"Exile a card from your hand: Add {B}{B} or {G}{G}."

    The mana half of this line already worked -- the alternatives are one
    payload the mana lowering has read since Alliances. What refused was the
    *cost*: an exile charged out of a **hand**, a third zone beside the
    battlefield and the graveyard the payment path already enumerated.

    The count is the assertion that matters. A hand repeats one immutable
    ``CardDefinition`` per copy, so the two Islands here are the same Python
    object; the payment goes through ``take_card_from_hand`` and eats exactly
    one of them.
    """
    game, _ = _w1g4_duel(
        set_pool,
        seat0_battlefield=("Cadaverous Bloom",),
        seat0_hand=("Island", "Island", "Mana Prism"),
    )
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Cadaverous Bloom", permanent_index=0, mana_color="B"
    )

    assert result.supported, result.details
    assert [c.name for c in game.players[0].hand] == ["Island", "Mana Prism"]
    assert [c.name for c in game.players[0].exile] == ["Island"]
    assert game.players[0].mana_pool["B"] == 2
    assert [p.card.name for p in game.players[0].battlefield] == [
        "Cadaverous Bloom",
    ], "the source pays nothing; the hand does"


def test_cadaverous_bloom_is_unactivatable_with_an_empty_hand(set_pool):
    """CR 602.2b: a cost that cannot be paid refuses the activation with
    nothing spent. Before the hand branch existed the payment fell through to
    the battlefield one, which exiled the Bloom itself and produced the mana
    anyway."""
    game, _ = _w1g4_duel(set_pool, seat0_battlefield=("Cadaverous Bloom",))
    game.start_turn(0)

    result = game.activate_permanent_ability(
        0, "Cadaverous Bloom", permanent_index=0, mana_color="G"
    )

    assert not result.supported
    assert game.players[0].mana_pool["G"] == 0
    assert game.players[0].exile == []
    assert game.players[0].battlefield, "the Bloom is still there"


# --- W1G3: damage / prevention / life ---

from engine import Game as _W1G3Game, PlayerState as _W1G3PlayerState
from engine.models import Permanent as _W1G3Permanent


def _w1g3_bone_mask_board(set_pool, library_size=5):
    pool = set_pool("MIR")
    mask = _W1G3Permanent(card=pool["Bone Mask"])
    ogre = _W1G3Permanent(card=pool["Wild Elephant"])
    other = _W1G3Permanent(card=pool["Azimaet Drake"])
    p1 = _W1G3PlayerState(
        name="P1", battlefield=[mask], life=20,
        library=[pool["Island"]] * library_size,
    )
    p2 = _W1G3PlayerState(name="P2", battlefield=[ogre, other], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game, p1, mask, ogre, other


def test_bone_mask_prevents_the_whole_instance_and_pays_from_the_library(set_pool):
    """"{2}, {T}: The next time a source of your choice would deal damage to
    you this turn, prevent that damage. **Exile cards from the top of your
    library equal to the damage prevented this way.**"

    Reverse Damage's printed sentence with a different rider after it, which is
    what made the shape a production: the pool had exactly one card printing
    those seven words, so it sat in `card_hooks.py` under that card's name.
    A second card sharing the shape is the entry bar failing, and the hook is
    gone.

    The rider is CR 615.5's additional effect and runs *inside* the prevention,
    so it is sized by what was absorbed rather than by what was announced — a
    whole instance, however big (CR 615.8).
    """
    from tests.helpers import _damage_dealt

    game, p1, mask, ogre, other = _w1g3_bone_mask_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Bone Mask", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    assert mask.tapped

    assert _damage_dealt(game, p1, 4, source=ogre) == 0, "the whole instance"
    assert p1.life == 20
    assert len(p1.library) == 1, "four cards paid for four damage"
    assert len(p1.exile) == 4


def test_bone_mask_waits_for_the_source_it_chose(set_pool):
    """Without this the test above passes for a shield that answers to
    everything — and then the library pays for damage the card never stopped."""
    from tests.helpers import _damage_dealt

    game, p1, mask, ogre, other = _w1g3_bone_mask_board(set_pool)

    game.activate_permanent_ability(
        0, "Bone Mask", target_player_index=1, target_permanent_index=0
    )

    assert _damage_dealt(game, p1, 3, source=other) == 3
    assert p1.exile == []
    assert _damage_dealt(game, p1, 3, source=ogre) == 0
    assert len(p1.exile) == 3


def test_bone_mask_exiles_what_is_left_of_an_empty_library(set_pool):
    """Running out is not a loss until a draw is attempted (CR 104.3c), and
    this is not a draw — so the rider takes what is there and stops."""
    from tests.helpers import _damage_dealt

    game, p1, mask, ogre, other = _w1g3_bone_mask_board(set_pool, library_size=1)

    game.activate_permanent_ability(
        0, "Bone Mask", target_player_index=1, target_permanent_index=0
    )
    assert _damage_dealt(game, p1, 5, source=ogre) == 0

    assert p1.library == []
    assert len(p1.exile) == 1
    assert not p1.lost


def _w1g3_sling_board(set_pool, payer_name):
    pool = set_pool("MIR")
    sling = _W1G3Permanent(card=pool["Unerring Sling"])
    payer = _W1G3Permanent(card=pool[payer_name])
    flier = _W1G3Permanent(card=pool["Cerulean Wyvern"])     # 3/3 flier
    ground = _W1G3Permanent(card=pool["Wall of Corpses"])
    p1 = _W1G3PlayerState(name="P1", battlefield=[sling, payer], life=20)
    p2 = _W1G3PlayerState(name="P2", battlefield=[flier, ground], life=20)
    game = _W1G3Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    ok, msg = game.declare_attackers(1, [0])                  # the flier attacks
    assert ok, msg
    return game, sling, payer, flier, ground


def test_unerring_sling_reads_the_creature_its_cost_tapped(set_pool):
    """"{3}, {T}, Tap an untapped creature you control: This artifact deals
    damage equal to **the tapped creature's power** to target attacking or
    blocking creature with flying."

    The third payment channel beside "the sacrificed creature's" and "the
    exiled card's", and the odd one of the three: the creature is still on the
    battlefield at resolution, so this is a plain back-reference rather than
    last-known information — a board scan would name whichever creature its
    controller had tapped since (the argument `untapped_for_cost` already makes
    for Benthic Explorers' land).
    """
    game, sling, payer, flier, ground = _w1g3_sling_board(
        set_pool, "Wild Elephant"                             # 3/3
    )

    result = game.activate_permanent_ability(
        0, "Unerring Sling",
        target_player_index=1, target_permanent_index=0,
        cost_permanent_ids=[payer.permanent_id],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert payer.tapped, "the cost tapped it"
    assert flier.damage_marked == 3, f"the payer's power: {game.log}"
    assert ground.damage_marked == 0


def test_unerring_sling_reads_a_different_payers_power(set_pool):
    """The same ability with a smaller creature paying — without this the test
    above passes for an ability that deals whatever number it likes."""
    game, sling, payer, flier, ground = _w1g3_sling_board(
        set_pool, "Zhalfirin Commander"                       # 2/2
    )

    result = game.activate_permanent_ability(
        0, "Unerring Sling",
        target_player_index=1, target_permanent_index=0,
        cost_permanent_ids=[payer.permanent_id],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert flier.damage_marked == 2, f"the payer's power: {game.log}"


# --- W1G5: the statics / characteristics / control family ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _g5_bear(name: str = "Bear", power: int = 2, toughness: int = 5) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _g5_chariot(set_pool):
    """Chariot of the Sun on seat 0 beside a 2/5, ready to activate."""
    pool = set_pool("MIR")
    chariot = Permanent(card=pool["Chariot of the Sun"])
    chariot.metadata["summoning_sickness_turn"] = -1
    bear = Permanent(card=_g5_bear())
    game = Game(players=[
        PlayerState(name="P1", battlefield=[chariot, bear],
                    library=[pool["Island"]] * 5),
        PlayerState(name="P2", library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    return game, bear


def test_chariot_of_the_sun_grants_flying_and_rewrites_the_toughness(set_pool):
    """"{2}, {T}: Until end of turn, target creature you control **gains flying
    and has base toughness 1**."

    Two things were missing and they are one sentence. ``has base toughness N``
    had no branch — the production demanded "power", so the toughness-only half
    of CR 613.4b's rewrite could not be spelled at all, though ``set_base_pt``'s
    None has expressed it since People of the Woods. And the conjunction is an
    arm of the grant beside "and gets", "and loses" and "and \\"…\\"", under the
    same duration rule: whichever half prints one governs both, and the leading
    "Until end of turn" this card uses is distributed by the sentence layer.
    """
    game, bear = _g5_chariot(set_pool)
    assert (bear.effective_power, bear.effective_toughness) == (2, 5)
    assert not game._has_keyword(bear, "flying")

    result = game.activate_permanent_ability(
        0, "Chariot of the Sun", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert game._has_keyword(bear, "flying")
    assert (bear.effective_power, bear.effective_toughness) == (2, 1), (
        "the printed power stands; only the toughness is rewritten"
    )


def test_the_chariots_rewrite_ends_with_the_turn(set_pool):
    """Both halves carry the one printed duration. A base P/T that outlived the
    turn would be the dropped-rider bug with the sign reversed — the creature
    stays a 2/1 for good."""
    game, bear = _g5_chariot(set_pool)
    game.activate_permanent_ability(
        0, "Chariot of the Sun", permanent_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game.resolve_stack()
    game._settle()

    game.resolve_cleanup_step(0)
    game._settle()

    assert not game._has_keyword(bear, "flying")
    assert (bear.effective_power, bear.effective_toughness) == (2, 5)


def test_cursed_totem_shuts_off_a_creatures_mana_ability(set_pool, catalog_by_name):
    """"Activated abilities of creatures can't be activated."

    The *board* half of CR 602.5, and the exact mirror of
    ``cast_restrictions.global_cast_ban`` one rule over: not a clause the
    ability prints about itself but a prohibition one permanent imposes on
    everybody, so it is read off the board at every activation.
    ``activation_denial`` is handed one printed line and rightly asks only
    about it, which is why this could not live there.

    **No mana-ability exception**, which is the whole of what the card does:
    CR 605 makes a mana ability an activated ability like any other and the
    sentence names no exception.
    """
    pool = set_pool("MIR")
    bird = Permanent(card=catalog_by_name["Birds of Paradise"])
    bird.metadata["summoning_sickness_turn"] = -1
    mox = Permanent(card=catalog_by_name["Mox Emerald"])
    mox.metadata["summoning_sickness_turn"] = -1
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bird, mox],
                    library=[catalog_by_name["Forest"]] * 5),
        PlayerState(name="P2", library=[catalog_by_name["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()

    assert game.activate_permanent_ability(
        0, "Birds of Paradise", permanent_index=0
    ).supported

    game.players[0].battlefield.append(Permanent(card=pool["Cursed Totem"]))
    game._settle()

    stopped = game.activate_permanent_ability(
        0, "Birds of Paradise", permanent_index=0
    )
    assert not stopped.supported
    assert "can't be activated" in stopped.details

    # It binds the type the sentence names and nothing else — a Mox is not a
    # creature, and the prohibition is read off `has_type` like every other
    # type question in this engine.
    assert game.activate_permanent_ability(
        0, "Mox Emerald", permanent_index=1
    ).supported


def test_cursed_totem_binds_its_own_controller_too(set_pool, catalog_by_name):
    """The sentence names nobody, so it binds everybody — including the seat
    that played it. Read as "your opponents'" it would be a strictly better
    card than the one printed."""
    pool = set_pool("MIR")
    bird = Permanent(card=catalog_by_name["Birds of Paradise"])
    bird.metadata["summoning_sickness_turn"] = -1
    game = Game(players=[
        PlayerState(name="P1", battlefield=[Permanent(card=pool["Cursed Totem"])],
                    library=[catalog_by_name["Forest"]] * 5),
        PlayerState(name="P2", battlefield=[bird],
                    library=[catalog_by_name["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()

    assert not game.activate_permanent_ability(
        1, "Birds of Paradise", permanent_index=0
    ).supported


def _g5_prison(set_pool):
    pool = set_pool("MIR")
    prison = Permanent(card=pool["Amber Prison"])
    prison.metadata["summoning_sickness_turn"] = -1
    bear = Permanent(card=CardDefinition(
        name="Bear", mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": "Bear", "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    ))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[prison], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[bear], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    result = game.activate_permanent_ability(
        0, "Amber Prison", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()
    return game, prison, bear


def test_amber_prison_holds_its_target_down_while_it_stays_tapped(set_pool):
    """"Tap target artifact, creature, or land. **That permanent** doesn't
    untap during its controller's untap step for as long as this artifact
    remains tapped."

    Every piece of this was already built — Phyrexian Gremlins prints the same
    linked restriction and Giant Oyster prints it with the duration in front.
    What refused was two words: ``parse_bound_subject`` reads "that
    <card type>", and "permanent" is a *generic* noun. It is the right word for
    this card and not a looser one: a sentence back-referencing a choice across
    three card types cannot say "that artifact", so the phrase carries no card
    type at all — which is exactly the narrowing it means.
    """
    game, prison, bear = _g5_prison(set_pool)
    assert bear.tapped and prison.tapped

    game.start_turn(1)
    game._settle()
    assert bear.tapped, "the Prison is still tapped"


def test_amber_prisons_grip_ends_when_it_untaps(set_pool):
    """"…for as long as this artifact remains tapped." The restriction is read
    off the source at the untap step rather than recorded on the creature, so
    the Prison untapping releases it with nothing to clear."""
    game, prison, bear = _g5_prison(set_pool)

    prison.tapped = False
    game.start_turn(1)
    game._settle()

    assert not bear.tapped


# --- W1G2: an X of a named counter, and the mana it becomes a turn later ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w1g2_bottle(set_pool):
    bottle = Permanent(card=set_pool("MIR")["Ventifact Bottle"])
    bottle.metadata["summoning_sickness_turn"] = -99
    filler = set_pool("MIR")["Femeref Scouts"]
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bottle], library=[filler] * 20, life=20),
        PlayerState(name="P2", library=[filler] * 20, life=20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    # The activation is sorcery-speed (CR 601.3d), so the game has to be in a
    # main phase with an empty stack before it will be accepted.
    game._enter_main_phase(precombat=True)
    game.resolve_stack()
    return game, bottle


def test_ventifact_bottle_stores_x_charge_counters(set_pool):
    """"{X}{1}, {T}: Put **X** charge counters on this artifact. Activate only
    as a sorcery."

    The named-counter placement admitted a *fixed* number only — the P/T branch
    beside it had learned the cast's announced X and this one had not, so the
    whole card refused on a value the handler was already able to resolve.
    """
    program = compile_card_oracle(set_pool("MIR")["Ventifact Bottle"])
    assert program.supported, program.reason

    game, bottle = _w1g2_bottle(set_pool)
    result = game.activate_permanent_ability(
        0, "Ventifact Bottle", permanent_index=0, x_value=3
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert counters_on(bottle, "charge") == 3, game.log


def test_ventifact_bottle_pays_out_at_the_next_first_main_phase(set_pool):
    """"At the beginning of your first main phase, **if this artifact has a
    charge counter on it**, tap it and remove all charge counters from it. Add
    {C} for each charge counter removed this way."

    Two more halves. The intervening-if knew "one or more" and not the article
    that means the same thing — a presence test, where reading "a" as a count
    would have meant *exactly* one and emptied the Bottle after its second
    activation. And "for each charge counter removed **this way**" had one
    producer, the Mana Batteries' *cost* payment; here the removal is an effect
    two instructions earlier, so the number is in this resolution's scratchpad
    and the lowering is what chooses between the two.
    """
    game, bottle = _w1g2_bottle(set_pool)
    game.activate_permanent_ability(
        0, "Ventifact Bottle", permanent_index=0, x_value=3
    )
    game.resolve_stack()

    game.start_next_turn()          # the opponent's turn
    game.start_next_turn()          # back to the Bottle's controller
    game._enter_main_phase(precombat=True)
    game.resolve_stack()

    assert counters_on(bottle, "charge") == 0, game.log
    assert bottle.tapped, game.log
    assert game.players[0].mana_pool["C"] == 3, game.log


def test_an_empty_ventifact_bottle_does_nothing(set_pool):
    """CR 603.4: the intervening-if is checked as the trigger would go on the
    stack, so a Bottle with no counters is not a trigger at all — and taps
    itself for nothing if it were."""
    game, bottle = _w1g2_bottle(set_pool)

    game.start_next_turn()
    game.start_next_turn()
    game._enter_main_phase(precombat=True)
    game.resolve_stack()

    assert not bottle.tapped, game.log
    assert game.players[0].mana_pool["C"] == 0, game.log


# --- W2G1: combat triggers and their bound referents ---
#
# Basalt Golem is filed here rather than with the creatures for the reason
# tests/sets/README.md gives: by the printed type of the card the test names,
# and its type line reads "Artifact Creature — Golem".

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g1a_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g1a_golem_blocked(set_pool):
    """Basalt Golem attacking, blocked by a Wall, run out to end of combat."""
    golem = Permanent(card=set_pool("MIR")["Basalt Golem"])
    golem.summoning_sick = False
    blocker = Permanent(card=_w2g1a_creature("Wall of Stone", 0, 7))
    blocker.summoning_sick = False
    bystander = Permanent(card=_w2g1a_creature("Bystander", 1, 1))
    bystander.summoning_sick = False
    game = Game(players=[
        PlayerState(name="P1", battlefield=[golem]),
        PlayerState(name="P2", battlefield=[blocker, bystander]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.resolve_stack()
    return game, golem, blocker, bystander


def test_basalt_golem_arms_a_delayed_sacrifice_of_what_blocked_it(set_pool):
    """"That creature's controller sacrifices it at end of combat."

    The pronoun spelling of "sacrifice that creature": the object is named in
    the *possessive* and the subject is a bare pronoun, so the reader that
    decides whether a delay binds an object -- which looks at the noun phrase's
    quantifier -- saw no binding and the entry would have armed about nothing.
    The seat the possessive names is CR 701.17a's answer anyway (a permanent is
    sacrificed by whoever controls it), so the two printed spellings are one
    instruction.
    """
    program = compile_card_oracle(set_pool("MIR")["Basalt Golem"])
    assert program.supported, program.reason
    (trig,) = program.triggered_abilities
    payload = trig.instruction.payload
    assert payload["event"] == "next_end_of_combat"
    assert payload["binds_target"] is True
    assert [step.kind for step in payload["instruction"].payload["steps"]] == [
        "sacrifice_bound_permanent", "if_then"
    ]

    game, _golem, blocker, _bystander = _w2g1a_golem_blocked(set_pool)
    assert [(e.event, e.bound_permanent_id) for e in game.delayed_triggers] == [
        ("next_end_of_combat", blocker.permanent_id)
    ], game.log


def test_basalt_golem_gives_the_wall_to_the_player_who_lost_a_creature(set_pool):
    """"If the player does, **they** create a 0/2 … Wall …"

    Both riders belong to the *delayed* ability. Left beside it they would run
    when the block trigger resolved -- a whole combat before the sacrifice they
    ask about -- and read a record nothing had written. And "they" is the
    sacrificing player, read off the seat the sacrifice recorded before the
    creature left: by the time the token is created it is a card in a graveyard
    and its controller is nobody's to look up.
    """
    game, _golem, _blocker, _bystander = _w2g1a_golem_blocked(set_pool)

    for _ in range(4):
        game.advance_combat_phase()
        game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Wall of Stone"], game.log
    assert sorted(p.card.name for p in game.players[1].battlefield) == [
        "Bystander", "Wall Token"
    ], game.log
    assert [p.card.name for p in game.players[0].battlefield] == ["Basalt Golem"]


def test_basalt_golem_makes_no_wall_when_the_creature_is_already_gone(set_pool):
    """"**If** the player does" asks a real question even though the sacrifice
    is not optional: CR 701.17a's action does not happen when the permanent has
    already left, and the rider is what stops the token arriving anyway."""
    game, _golem, blocker, _bystander = _w2g1a_golem_blocked(set_pool)
    game.remove_from_battlefield(blocker)

    for _ in range(4):
        game.advance_combat_phase()
        game.resolve_stack()

    assert [p.card.name for p in game.players[1].battlefield] == ["Bystander"], game.log


def _w2g1a_wall(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Wall",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Wall",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g1a_dagger(set_pool, blocker: CardDefinition | None):
    """The Dagger and an attacker of its controller's, in the declare-blockers
    step with the ability already activated on that attacker."""
    dagger = Permanent(card=set_pool("MIR")["Acidic Dagger"])
    dagger.summoning_sick = False
    attacker = Permanent(card=_w2g1a_creature("Ogre", 3, 3))
    attacker.summoning_sick = False
    theirs = []
    if blocker is not None:
        blocking = Permanent(card=blocker)
        blocking.summoning_sick = False
        theirs.append(blocking)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[dagger, attacker]),
        PlayerState(name="P2", battlefield=theirs),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [1])[0]
    game.advance_combat_phase()
    return game, dagger, attacker


def test_acidic_dagger_destroys_what_its_target_damaged(set_pool):
    """"Whenever target creature deals combat damage to a non-Wall creature this
    turn, destroy **that non-Wall creature**."

    The event has two objects and the sentence acts on the one the entry is
    *not* bound to: the ability targets the creature that will deal the damage,
    and the words name what it hit. An agent used to be matched and never
    carried -- ``agent_filter`` decided whether the entry answered and nothing
    could then act on the creature it answered about -- so the fire site stamps
    the agent's id and the destroy reads it.
    """
    program = compile_card_oracle(set_pool("MIR")["Acidic Dagger"])
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    damage_delay, leaves_delay = ability.instruction.payload["steps"]
    assert damage_delay.payload["event"] == "bound_permanent_deals_combat_damage"
    assert damage_delay.payload["instruction"].kind == "destroy_delayed_agent"
    assert damage_delay.payload["agent_filter"]["exclude_subtypes"] == ["wall"]
    assert leaves_delay.payload["event"] == "bound_permanent_leaves_battlefield"

    game, _dagger, _attacker = _w2g1a_dagger(
        set_pool, _w2g1a_creature("Bear", 2, 5)
    )
    game.activate_permanent_ability(
        0, "Acidic Dagger", target_player_index=0, target_permanent_index=1
    )
    game.resolve_stack()
    assert game.declare_blockers(1, {0: 1})[0]
    game.resolve_stack()
    for _ in range(3):
        game.advance_combat_phase()
        game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Bear"], game.log


def test_acidic_dagger_spares_a_wall(set_pool):
    """"…to a **non-Wall** creature". The narrowing is what stops the Dagger
    killing the Wall that held its attacker, and it is read on both ends: as the
    entry's agent filter, so a Wall never fires it, and again at resolution."""
    game, _dagger, _attacker = _w2g1a_dagger(
        set_pool, _w2g1a_wall("Stone Wall", 0, 6)
    )
    game.activate_permanent_ability(
        0, "Acidic Dagger", target_player_index=0, target_permanent_index=1
    )
    game.resolve_stack()
    assert game.declare_blockers(1, {0: 1})[0]
    game.resolve_stack()
    for _ in range(3):
        game.advance_combat_phase()
        game.resolve_stack()

    assert [p.card.name for p in game.players[1].battlefield] == ["Stone Wall"], game.log
    assert not game.players[1].graveyard


def test_acidic_dagger_goes_when_the_creature_it_named_does(set_pool):
    """"When **the targeted creature** leaves the battlefield this turn,
    sacrifice this artifact."

    The definite spelling of the same referent "that creature" carries: the
    ability targeted once (CR 602.2b), so both of its delayed sentences are
    about that one creature and reach the same binding.
    """
    game, dagger, attacker = _w2g1a_dagger(set_pool, None)
    game.activate_permanent_ability(
        0, "Acidic Dagger", target_player_index=0, target_permanent_index=1
    )
    game.resolve_stack()
    assert [e.bound_permanent_id for e in game.delayed_triggers] == [
        attacker.permanent_id, attacker.permanent_id
    ], game.log

    game.remove_from_battlefield(attacker)
    game.resolve_stack()

    assert [c.name for c in game.players[0].graveyard] == ["Acidic Dagger"], game.log


def test_acidic_dagger_cannot_be_activated_once_blockers_are_declared(set_pool):
    """"Activate only before blockers are declared."

    One combat step later than the window Norritt prints, and its own predicate
    for that one's stated reason: two spellings of "when is it too late" would
    be two answers. The declaration is what closes it, not the step's arrival --
    the Dagger is meant to be usable *in* the declare-blockers step, before the
    defending player has committed.
    """
    game, _dagger, _attacker = _w2g1a_dagger(
        set_pool, _w2g1a_creature("Bear", 2, 5)
    )
    assert game.declare_blockers(1, {0: 1})[0]
    game.resolve_stack()

    result = game.activate_permanent_ability(
        0, "Acidic Dagger", target_player_index=0, target_permanent_index=1
    )
    assert "only before blockers are declared" in result.details, result


# --- W3G5: Grinning Totem, a card played out of somebody else's exile ---

from engine import Game as _w3g5_Game, PlayerState as _w3g5_PlayerState  # noqa: E402
from engine.cast_permissions import (  # noqa: E402
    playable_from_zones as _w3g5_playable,
)
from engine.grammar import compile_line as _w3g5_compile_line  # noqa: E402
from engine.models import Permanent as _w3g5_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g5_compile  # noqa: E402


def _w3g5_totem_board(set_pool):
    """Grinning Totem on seat 0's battlefield, three known cards on seat 1's
    library with a creature on top."""
    pool = set_pool("MIR")
    totem = _w3g5_Permanent(card=pool["Grinning Totem"])
    game = _w3g5_Game(players=[
        _w3g5_PlayerState(
            name="P1", battlefield=[totem], library=[pool["Island"]] * 12
        ),
        _w3g5_PlayerState(
            name="P2",
            library=[pool["Bay Falcon"], pool["Mountain"], pool["Forest"]]
            + [pool["Island"]] * 8,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    return game, totem


def _w3g5_activate_and_find(set_pool):
    """The board after the ability has resolved and the search been answered:
    Bay Falcon is in seat 1's exile and seat 0 may play it."""
    game, _totem = _w3g5_totem_board(set_pool)
    result = game.activate_permanent_ability(
        0, "Grinning Totem", target_player_index=1
    )
    assert result.supported, result.details
    game.resolve_stack()
    assert game.confirm_search_library(0, 0, "library")
    return game


def test_grinning_totem_exiles_into_the_searched_players_own_exile(set_pool):
    """"Search target opponent's library for a card and exile it."

    CR 400.3 sends the card to its **owner's** exile, and its owner is the
    player whose library it came out of — so it lands in seat 1's pile, not the
    searcher's. That split is the whole of what makes this card hard: the
    permission below belongs to the other seat.
    """
    game = _w3g5_activate_and_find(set_pool)

    assert [c.name for c in game.players[1].exile] == ["Bay Falcon"]
    assert game.players[0].exile == []
    # "Then that player shuffles" — the search is over, and what is left of the
    # library is everything it did not take.
    assert len(game.players[1].library) == 10


def test_grinning_totem_grants_its_controller_a_cross_seat_permission(set_pool):
    """"Until the beginning of your next upkeep, you may play that card."

    Two seats, and the grant has to name both: the *player* who may play it is
    the Totem's controller, and the *pile* it is in is the opponent's. Read as
    one seat the grant is wrong in a stated direction either way — as the
    grantee it covers a card nothing holds, and as the owner it lets the wrong
    player cast it.
    """
    game = _w3g5_activate_and_find(set_pool)

    grant = game.cast_permissions[0]
    assert (grant.player_index, grant.zone_seat) == (0, 1)
    assert grant.mode == "play"          # a land is played, not cast
    assert grant.duration == "your_next_upkeep"
    assert [c.name for c in grant.cards] == ["Bay Falcon"]

    # And the seat sees it as something it may play, with the pile named.
    assert _w3g5_playable(game, 0) == [{
        "zone": "exile", "index": 0, "name": "Bay Falcon", "free": False,
        "source": "Grinning Totem", "owner_seat": 1,
    }]
    # The card's owner has no permission — it is seat 0's, not the card's.
    assert _w3g5_playable(game, 1) == []


def test_grinning_totem_lets_the_card_be_cast_out_of_the_other_pile(set_pool):
    """The game the grant exists for: seat 0 casts an opponent's card out of the
    opponent's exile, and the one-card grant retires as it is used."""
    game = _w3g5_activate_and_find(set_pool)

    result = game.cast_from_hand(0, "Bay Falcon", from_zone="exile")
    assert result.supported, result.details
    game.resolve_stack()

    # The Totem itself went as a cost ("Sacrifice this artifact"), so the only
    # permanent seat 0 has is the opponent's card.
    assert [p.card.name for p in game.controlled_by(0)] == ["Bay Falcon"]
    assert game.players[1].exile == []
    assert game.cast_permissions == []


def test_grinning_totem_bins_the_card_it_was_not_played(set_pool):
    """"At the beginning of your next upkeep, if you haven't played it, put it
    into its owner's graveyard."

    A CR 603.7 delayed ability, and *its owner's* graveyard is seat 1's — the
    same seat whose library the card came out of.
    """
    game = _w3g5_activate_and_find(set_pool)
    assert [t.event for t in game.delayed_triggers] == ["controllers_next_upkeep"]

    game.resolve_upkeep(0)
    game._settle()

    assert game.players[1].exile == []
    assert [c.name for c in game.players[1].graveyard] == ["Bay Falcon"]
    # Seat 0's own graveyard holds only the Totem it sacrificed as a cost —
    # "its owner's graveyard" is not the searcher's.
    assert [c.name for c in game.players[0].graveyard] == ["Grinning Totem"]
    # The permission is swept at that same upkeep (CR 611.2a).
    assert game.cast_permissions == []


def test_grinning_totem_bins_nothing_when_the_card_was_played(set_pool):
    """The printed condition, enforced rather than parsed and dropped.

    It is enforced by *where the card is*: a card the player played is no longer
    in exile, and the move only ever takes a card out of exile. It cannot be
    enforced by asking the permission — a "your next upkeep" grant is swept as
    that upkeep begins, before any ability of that upkeep can fire, so by the
    time this ability resolves every such grant is gone whether it was spent or
    not.
    """
    game = _w3g5_activate_and_find(set_pool)
    assert game.cast_from_hand(0, "Bay Falcon", from_zone="exile").supported
    game.resolve_stack()

    game.resolve_upkeep(0)
    game._settle()

    assert [p.card.name for p in game.controlled_by(0)] == ["Bay Falcon"]
    assert game.players[1].graveyard == []
    assert "the exiled card was played" in " ".join(game.log)


def test_the_permission_needs_a_step_that_actually_exiled(set_pool):
    """The producer gate, and the reason it is keyed on the search's *payload*
    rather than on its kind.

    A library search records what it exiled only when the printed sentence sent
    its find to exile. Declaring the record flat on ``search_library`` would
    admit this line — a tutor to the hand followed by permission to play "that
    card" — which would compile clean and permit nothing at all.
    """
    compiled = _w3g5_compile_line(
        "Search your library for a creature card, put it into your hand, then "
        "shuffle. Until the beginning of your next upkeep, you may play that card."
    )

    assert not compiled.instructions
    assert "no exile in this effect" in (compiled.lowering_error or ""), (
        compiled.lowering_error
    )


def test_grinning_totem_reports_supported_with_all_three_steps(set_pool):
    """Every printed sentence reaches an instruction: the search, the CR 601.3
    permission and the CR 603.7 delayed ability."""
    pool = set_pool("MIR")
    program = _w3g5_compile(pool["Grinning Totem"])

    assert program.supported
    (ability,) = program.activated_abilities
    steps = ability.instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "search_library", "grant_cast_permission", "create_delayed_trigger",
    ]
    assert steps[0].payload["destination"] == "exile"
    assert steps[2].payload["instruction"].payload == {
        "zone": "graveyard", "only_if_unplayed": True,
    }


# --- W3G2: Mangara's Tome ---
#
# A search that makes a *pile* and an ability that reads it one card at a time.
# Both halves needed a piece the engine did not have:
#
# * "exile them in a face-down pile, and shuffle that pile" is `SearchAndExile`
#   with two printed facts on it. The record it builds is CR 610.3's linked
#   pile (`engine/linked_exile.py`) — the same one Knowledge Vault and Tetravus
#   already use — which is what a later ability naming "the exiled pile" can be
#   about at all.
# * "The next time you would draw a card this turn, instead <effect>" is a
#   CR 614.1 one-shot draw replacement, and it is a *general* production
#   because three cards in the pool print that opener: Aladdin's Lamp and Ring
#   of Ma'rûf print it too, with inner sentences this grammar does not read, so
#   they keep their card hooks and this claims neither.
#
# The armed replacement lives on the game rather than on the Tome, which is
# CR 611.2: the effect belongs to the ability that resolved, so destroying the
# artifact in response does not un-arm the draw it paid for.

import random as _w3g2t_random  # noqa: E402

from engine import Game as _w3g2t_Game, PlayerState as _w3g2t_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w3g2t_load,  # noqa: E402
                                manifest_set_path as _w3g2t_path)
from engine.linked_exile import linked_entries as _w3g2t_pile  # noqa: E402
from engine.models import Permanent as _w3g2t_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g2t_compile  # noqa: E402


def _w3g2t_lea():
    return {card.name: card for card in _w3g2t_load(_w3g2t_path("LEA"))}


#: Five distinct cards plus filler, so "which five went into the pile" and
#: "what order is the pile in" are both readable off the names.
_W3G2T_DECK = (
    "Black Lotus", "Grizzly Bears", "Hurloon Minotaur", "Mox Pearl",
    "Healing Salve", "Island", "Island", "Island", "Island",
)


def _w3g2t_board(set_pool, *, seed=7):
    """A game with a Mangara's Tome already resolved on P1's battlefield.

    The Tome is *cast* rather than placed, so the entry trigger runs and the
    pile is what the search actually built. The seed pins the two shuffles —
    the library's and the pile's — so the assertions below name cards rather
    than counting them.
    """
    _w3g2t_random.seed(seed)
    lea = _w3g2t_lea()
    game = _w3g2t_Game(players=[
        _w3g2t_PlayerState(
            name="P1", library=[lea[name] for name in _W3G2T_DECK],
            hand=[set_pool("MIR")["Mangara's Tome"]],
        ),
        _w3g2t_PlayerState(name="P2", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    assert game.cast_from_hand(0, "Mangara's Tome").supported
    game._settle()
    game.auto_resolve_pending_choices()
    tome = next(iter(game.controlled_by(game.players[0])))
    tome.metadata["summoning_sickness_turn"] = -99
    return game, tome


def _w3g2t_arm(game, tome):
    game.activate_permanent_ability(0, "Mangara's Tome")
    game._settle()
    game.auto_resolve_pending_choices()


def test_w3g2_mangaras_tome_is_supported_in_both_halves(set_pool):
    program = _w3g2t_compile(set_pool("MIR")["Mangara's Tome"])
    assert program.supported, program.reason
    assert [t.source_line for t in program.triggered_abilities if t.instruction is None] == []
    assert [a.source_line for a in program.activated_abilities if a.instruction is None] == []


def test_w3g2_the_entry_search_builds_a_face_down_pile(set_pool):
    """"…search your library for five cards, exile them in a face-down pile,
    and shuffle that pile. Then shuffle your library."

    Five cards leave the library for exile, every one of them face down
    (CR 406.3), and the record on the artifact is what makes them a *pile*
    rather than five loose cards in the exile zone.
    """
    game, tome = _w3g2t_board(set_pool)
    player = game.players[0]

    assert len(player.exile) == 5, game.log
    assert len(player.library) == len(_W3G2T_DECK) - 5

    entries = _w3g2t_pile(tome)
    assert len(entries) == 5
    assert all(entry.get("face_down") for entry in entries)
    assert all(entry.get("owner_index") == 0 for entry in entries)
    # The pile holds the same five cards the exile does, in its own order.
    assert sorted(entry["card"].name for entry in entries) == sorted(
        card.name for card in player.exile
    )
    # "…and shuffle that pile": the order is the shuffle's, not the search's.
    assert [entry["card"].name for entry in entries] != [
        card.name for card in player.exile
    ], "an unshuffled pile would come back in the order it was exiled"


def test_w3g2_the_armed_ability_replaces_the_next_draw(set_pool):
    """"{2}: The next time you would draw a card this turn, instead put the top
    card of the exiled pile into its owner's hand."

    Nothing is drawn — the library is untouched and the seam reports 0 — and
    the card that arrives is the pile's top, which leaves both the pile and
    the exile zone.
    """
    game, tome = _w3g2t_board(set_pool)
    player = game.players[0]
    top = _w3g2t_pile(tome)[0]["card"]
    library_before = len(player.library)

    _w3g2t_arm(game, tome)
    assert game._draw_with_replacements(player, 1) == 0

    assert [card.name for card in player.hand] == [top.name], game.log
    assert len(player.library) == library_before, "no card left the library"
    assert len(_w3g2t_pile(tome)) == 4
    assert top not in player.exile


def test_w3g2_each_activation_arms_one_draw(set_pool):
    """"The next time" is one draw (CR 121.2 makes a two-card instruction two
    draws), and two activations are two effects — so a two-card draw under two
    charges takes two cards off the pile and none off the library."""
    game, tome = _w3g2t_board(set_pool)
    player = game.players[0]
    first, second = [entry["card"] for entry in _w3g2t_pile(tome)[:2]]
    library_before = len(player.library)

    _w3g2t_arm(game, tome)
    _w3g2t_arm(game, tome)
    assert game._draw_with_replacements(player, 2) == 0

    assert [card.name for card in player.hand] == [first.name, second.name], game.log
    assert len(player.library) == library_before
    assert game.armed_draw_replacements == []


def test_w3g2_one_charge_leaves_the_second_draw_alone(set_pool):
    """The other half of the same rule: with one charge armed, the first draw
    is replaced and the second is an ordinary draw off the library."""
    game, tome = _w3g2t_board(set_pool)
    player = game.players[0]
    library_before = len(player.library)

    _w3g2t_arm(game, tome)
    drawn = game._draw_with_replacements(player, 2)

    assert drawn == 1, game.log
    assert len(player.hand) == 2
    assert len(player.library) == library_before - 1


def test_w3g2_an_empty_pile_still_takes_the_draw(set_pool):
    """CR 614.1: the charge is spent on the next draw whether or not the effect
    behind it finds anything to do. Five cards is all Mangara's Tome ever
    exiles, so the sixth activation is the card's own failure mode, and it has
    to be the printed one — the draw is replaced and nothing arrives, not a
    draw that quietly happens anyway."""
    game, tome = _w3g2t_board(set_pool)
    player = game.players[0]
    for _ in range(5):
        _w3g2t_arm(game, tome)
        game._draw_with_replacements(player, 1)
    assert len(player.hand) == 5
    assert _w3g2t_pile(tome) == ()

    library_before = len(player.library)
    _w3g2t_arm(game, tome)
    assert game._draw_with_replacements(player, 1) == 0

    assert len(player.hand) == 5, game.log
    assert len(player.library) == library_before, "the draw was replaced, not made"
    assert any("the exiled pile is empty" in line for line in game.log)


def test_w3g2_the_charge_expires_with_the_turn(set_pool):
    """"…**this turn**." An unspent charge does not wait for the next one, and
    the next turn's draw step is an ordinary draw."""
    game, tome = _w3g2t_board(set_pool)
    player = game.players[0]
    _w3g2t_arm(game, tome)
    assert game.armed_draw_replacements

    game.start_next_turn()          # P2's turn
    assert game.armed_draw_replacements == []
    library_before = len(player.library)
    assert game._draw_with_replacements(player, 1) == 1
    assert len(player.library) == library_before - 1


def test_w3g2_destroying_the_tome_does_not_unarm_the_draw(set_pool):
    """CR 611.2: the replacement belongs to the ability that resolved, not to
    the permanent that printed it.

    The record is on the game for exactly this, and the pile it reads is a link
    between two *abilities* (CR 610.3) rather than between two objects — so a
    Tome destroyed with the charge armed still hands over its top card. Written
    down because the obvious place for the record is the artifact's metadata,
    where a destroyed Tome would silently make the {2} the player just paid buy
    nothing.
    """
    game, tome = _w3g2t_board(set_pool)
    player = game.players[0]
    top = _w3g2t_pile(tome)[0]["card"]
    _w3g2t_arm(game, tome)

    game.remove_from_battlefield(tome)
    game._permanent_to_graveyard(player, tome)

    assert game._draw_with_replacements(player, 1) == 0
    assert [card.name for card in player.hand] == [top.name], game.log


def test_w3g2_the_other_two_cards_printing_this_opener_keep_their_hooks(set_pool):
    """The sweep this production owes. Three cards in the pool print "The next
    time you would draw a card this turn, instead …", and the other two —
    Aladdin's Lamp and Ring of Ma'rûf — carry inner sentences this grammar does
    not read.

    A production that consumed the opener and then fell through would have
    taken their lines away and left them doing nothing; because it parses the
    inner sentence as an ordinary statement, the whole line refuses and the
    compiler goes on to ``card_hooks`` as it always did. Asserted as
    *behaviour* — both cards still arm their own replacement — rather than as a
    claim about which registry read the line.
    """
    lea = _w3g2t_lea()
    arn = {card.name: card for card in _w3g2t_load(_w3g2t_path("ARN"))}

    for name, check in (
        ("Aladdin's Lamp", lambda g: g.lamp_draw_replacements),
        ("Ring of Ma'rûf", lambda g: g.outside_game_draw_replacements),
    ):
        pool = arn
        program = _w3g2t_compile(pool[name])
        assert program.supported, (name, program.reason)
        game = _w3g2t_Game(players=[
            _w3g2t_PlayerState(name="P1", library=[lea["Island"]] * 10),
            _w3g2t_PlayerState(name="P2", library=[lea["Island"]] * 10),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = set()
        permanent = _w3g2t_Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        game.start_turn(0)
        game.activate_permanent_ability(0, name, x_value=2)
        game._settle()
        assert check(game), (name, game.log)
        assert game.armed_draw_replacements == [], (
            f"{name} still arms its own replacement, not the general one"
        )

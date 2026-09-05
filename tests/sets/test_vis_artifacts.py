"""Visions artifacts.

Each group appends its own block with its own imports at the top of that block,
so a per-set merge is an append rather than a conflict (SET_PLAYBOOK.md).
"""

from __future__ import annotations
import pytest
from engine import Game, PlayerState
from engine.grammar import parse_line
from engine.grammar.errors import GrammarError
from engine.hand_size import maximum_hand_size
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.untap_restrictions import untap_restriction_for
from engine.card_loader import manifest_set_path, load_cards
from engine.models import Permanent
from engine.targeting import derive_activation_spec
from engine.oracle import compile_card_oracle as _g5w_compile

# --- W1G4: upkeep, end-step and per-player step triggers ---



def _w1g4_forest(name: str) -> CardDefinition:
    """A basic land under a made-up name, so a hand or library is countable."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Basic Land - Forest",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=("G",), raw={"name": name},
    )


def _w1g4_bear(name: str, tapped: bool = False) -> Permanent:
    return Permanent(
        card=CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
            oracle_text="", colors=(), color_identity=(), keywords=(),
            produced_mana=(), raw={"name": name}, power="2", toughness="2",
        ),
        tapped=tapped,
    )


def _w1g4_game(*, hands=(0, 0), libraries=(0, 0)) -> Game:
    game = Game(players=[
        PlayerState(
            name=f"P{seat}",
            hand=[_w1g4_forest(f"H{seat}_{i}") for i in range(hands[seat])],
            library=[_w1g4_forest(f"L{seat}_{i}") for i in range(libraries[seat])],
        )
        for seat in (0, 1)
    ])
    game.enforce_mana_costs = False
    return game


def _w1g4_drain(game: Game) -> None:
    """Resolve everything the step just put on the stack."""
    for _ in range(20):
        if not game.stack:
            return
        game.resolve_top_of_stack()
    raise AssertionError("the stack never drained")


def test_anvil_of_bogardan_removes_every_players_maximum_hand_size(set_pool):
    """"Players have no maximum hand size." - CR 402.2, for everyone at the
    table, and derived from the board so it ends with the artifact (CR 611.3a).

    Asserted at the cleanup step rather than off the reader alone: a restriction
    line parsed and enforced by nobody is the failure that never crashes and is
    always in the player's favour.
    """
    game = _w1g4_game(hands=(10, 10))
    anvil = Permanent(card=set_pool("VIS")["Anvil of Bogardan"])
    game.players[0].battlefield.append(anvil)
    game.begin_turn_bookkeeping(0)

    assert maximum_hand_size(game, 0) is None
    # Its controller's opponent too - the line says "players", not "you".
    assert maximum_hand_size(game, 1) is None
    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == 10
    assert game.players[0].graveyard == []

    game.remove_from_battlefield(anvil)
    assert maximum_hand_size(game, 0) == 7
    game.resolve_cleanup_step(0)
    assert len(game.players[0].hand) == 7


def test_sands_of_time_makes_every_player_skip_their_untap_step(set_pool):
    """"Each player skips their untap step." - the distributive spelling of
    Stasis's "Players skip their untap steps", and the same CR 502 restriction,
    so it is one row in the table rather than a second."""
    sands = set_pool("VIS")["Sands of Time"]
    restriction = untap_restriction_for(sands.oracle_text)

    assert restriction is not None
    assert (restriction.scope, restriction.limit) == ("all", 0)

    game = _w1g4_game()
    game.players[0].battlefield.append(Permanent(card=sands))
    bear = _w1g4_bear("Bear", tapped=True)
    game.players[0].battlefield.append(bear)
    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0

    game.resolve_untap_step(0)

    assert bear.tapped is True


def test_sands_of_time_inverts_only_the_upkeeps_own_players_permanents(set_pool):
    """"At the beginning of each player's upkeep, that player **simultaneously**
    untaps each tapped artifact, creature, and land they control and taps each
    untapped artifact, creature, and land they control."

    Two assertions, and the second is the adverb. The seat is the one whose
    upkeep it is (CR 603.10), so an opponent's board is untouched; and the two
    sweeps are simultaneous (CR 611.2c), so a permanent that was tapped comes up
    and *stays* up rather than being caught by the tap half.
    """
    pool = set_pool("VIS")
    game = _w1g4_game()

    sands = Permanent(card=pool["Sands of Time"])
    game.players[0].battlefield.append(sands)
    mine_tapped = _w1g4_bear("Mine tapped", tapped=True)
    mine_untapped = _w1g4_bear("Mine untapped")
    game.players[0].battlefield.extend([mine_tapped, mine_untapped])
    theirs_tapped = _w1g4_bear("Theirs tapped", tapped=True)
    game.players[1].battlefield.append(theirs_tapped)

    game.begin_turn_bookkeeping(0)
    game.active_player_index = 0
    game.resolve_upkeep(0, defer_priority=True)
    _w1g4_drain(game)

    assert mine_tapped.tapped is False
    assert mine_untapped.tapped is True
    # The artifact is one of the permanents its own sentence names.
    assert sands.tapped is True
    # Somebody else's upkeep, somebody else's board.
    assert theirs_tapped.tapped is True


def test_teferis_puzzle_box_bottoms_a_hand_and_redraws_it(set_pool):
    """"At the beginning of each player's draw step, that player puts the cards
    in their hand on the **bottom** of their library in any order, then draws
    that many cards."

    Three facts, and each is a place this card could go wrong quietly: the seat
    is the one whose draw step it is, the cards go to the *bottom* (a prompt
    that could not tell the ends apart would put them on top), and the redraw
    counts what the put actually moved rather than a printed number.
    """
    game = _w1g4_game(hands=(3, 3), libraries=(20, 20))
    game.players[0].battlefield.append(
        Permanent(card=set_pool("VIS")["Teferi's Puzzle Box"])
    )
    game.turn = 2
    game.begin_turn_bookkeeping(1)
    game.active_player_index = 1
    old_hand = [card.name for card in game.players[1].hand]
    top_before = [card.name for card in game.players[1].library[:3]]

    game.resolve_upkeep(1, defer_priority=True)
    game.resolve_draw_step(1, defer_priority=True)
    game.resolve_top_of_stack()

    # The prompt is owed before anything moves, and it is owed by the seat whose
    # draw step this is (CR 608.2, CR 117.3b).
    assert [choice.kind for choice in game.pending_choices] == ["hand_to_library"]
    choice = game.pending_choices[0]
    assert choice.player_index == 1
    assert choice.data["destination"] == "bottom"
    # The turn-based draw happens inside the step and before this trigger
    # resolves, so what goes back is the hand as it stands then - which is
    # exactly why the count is read off the board rather than printed.
    held = len(game.players[1].hand)
    assert held == len(old_hand) + 1
    assert choice.data["count"] == held
    assert game.confirm_hand_to_library(1, list(range(held)))

    assert [card.name for card in game.players[1].library[-held:]][:3] == old_hand
    assert [card.name for card in game.players[1].hand][:2] == top_before[1:]
    # The Puzzle Box's controller is not the seat whose draw step it was.
    assert len(game.players[0].hand) == 3


def test_teferis_puzzle_box_compiles_the_bottoming_and_the_redraw_as_one_step(set_pool):
    """The two halves are one ``sequence``, and the draw reads the record the
    put wrote - "that many" has no other producer, and a back-reference with
    none reads as zero."""
    program = compile_card_oracle(set_pool("VIS")["Teferi's Puzzle Box"])
    (trigger,) = program.triggered_abilities

    assert trigger.condition.kind == "draw_step_each"
    assert trigger.instruction.kind == "sequence"
    put, draw = trigger.instruction.payload["steps"]
    assert put.kind == "put_hand_cards_on_library"
    assert put.payload["destination"] == "bottom"
    assert put.payload["whole_hand"] is True
    assert put.payload["recipient"] == "event_subject_player"
    assert draw.kind == "draw_target_cards"
    assert draw.payload["amount_from"] == "hand_cards_to_library"
    assert draw.payload["drawer_seat_record"] == "event_subject_player"


@pytest.mark.parametrize("line", [
    # The ordering rider is the whole of what the player still decides once the
    # card has named the end, so a bottoming sentence without it must refuse
    # rather than parse with the choice dropped.
    "That player puts the cards in their hand on the bottom of their library.",
    # A destination this production does not read.
    "That player puts the cards in their hand beside their library in any order.",
])
def test_the_bottoming_production_refuses_what_it_cannot_read(line):
    """A production consumes every token of its line or raises (CLAUDE.md)."""
    with pytest.raises(GrammarError):
        parse_line(line)


@pytest.mark.parametrize("line", [
    # Half a sentence: the tap sweep is what makes it an inversion.
    "That player simultaneously untaps each tapped creature they control.",
])
def test_the_inversion_production_refuses_what_it_cannot_read(line):
    """The refusal test for the other production this block added."""
    with pytest.raises(GrammarError):
        parse_line(line)


# --- W1G5: the Chimera cycle (CR 122.1, CR 611.2b) ---



#: The four Chimeras print one sentence with one keyword changed, which is the
#: whole reason they are one production rather than four hooks.
CHIMERAS = {
    "Brass-Talon Chimera": "first strike",
    "Iron-Heart Chimera": "vigilance",
    "Lead-Belly Chimera": "trample",
    "Tin-Wing Chimera": "flying",
}


def _g5_board(set_pool, *creatures):
    """A board of the named VIS/LEA cards on seat 0, all able to act."""
    vis = set_pool("VIS")
    lea = set_pool("LEA")
    permanents = [
        Permanent(card=(vis[name] if name in vis else lea[name]))
        for name in creatures
    ]
    game = Game(players=[
        PlayerState(name="P1", battlefield=permanents, library=[lea["Island"]] * 8),
        PlayerState(name="P2", library=[lea["Island"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._settle()
    for permanent in permanents:
        permanent.metadata["summoning_sickness_turn"] = -99
    return game, permanents


@pytest.mark.parametrize("name,keyword", sorted(CHIMERAS.items()))
def test_every_chimera_compiles_its_sacrifice_ability(set_pool, name, keyword):
    """One sentence with one word changed, so the fourth one comes for free.

    The refusal was a *lowering* one and not a parse one: the placement branch
    in ``lowering/counters.py`` listed the fields it would honour and left
    ``subtypes`` off, while ``to_payload`` emits it as ``subtype_filter`` and
    ``permanent_matches_filter`` tests it — a false refusal of a phrase the
    payload carries perfectly well.
    """
    program = compile_card_oracle(set_pool("VIS")[name])
    assert program.supported, program.reason

    sacrifices = [
        ability for ability in program.activated_abilities
        if ability.cost.sacrifice_self
    ]
    assert len(sacrifices) == 1
    steps = sacrifices[0].instruction.payload["steps"]
    assert steps[0].kind == "add_counter_to_target"
    assert steps[0].payload["counter"] == "+2/+2"
    # The printed creature type survives as payload, which is what makes this a
    # production rather than four hooks: the word is data.
    for step in steps:
        assert step.payload["targets"]["filter"] == {
            "type_filter": "creature", "subtype_filter": "chimera",
        }
    # The keyword rides the payload where the pool has a generic grant, and
    # rides the *kind* where it has a dedicated one — flying is the engine's
    # one keyword with its own handler.
    assert keyword in str(steps[1].payload) or keyword in steps[1].kind


@pytest.mark.parametrize("name,keyword", sorted(CHIMERAS.items()))
def test_a_chimera_picker_offers_only_chimeras(set_pool, name, keyword):
    """The activation picker and the resolution have to agree on the noun
    phrase, or the player announces a target the effect then declines."""
    program = compile_card_oracle(set_pool("VIS")[name])
    ability = next(
        a for a in program.activated_abilities if a.cost.sacrifice_self
    )
    assert derive_activation_spec(ability) == {
        "kind": "creature", "filter": {"subtype_filter": "chimera"},
    }


def test_a_chimera_pumps_and_arms_another_chimera_indefinitely(set_pool):
    """The Rock Hydra test. Brass-Talon sacrifices itself, Tin-Wing takes the
    +2/+2 counter and first strike, and the grant survives the turn because
    "(This effect lasts indefinitely.)" is a *reminder* (CR 207.2) of what a
    continuous effect with no printed duration already means (CR 611.2b) —
    which is why nothing was built for it: the lexer strips the parenthetical
    and ``Duration()`` lowers to ``duration: None``.
    """
    game, (brass, tin, bear) = _g5_board(
        set_pool, "Brass-Talon Chimera", "Tin-Wing Chimera", "Grizzly Bears",
    )

    result = game.activate_permanent_ability(
        0, "Brass-Talon Chimera",
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(tin),
    )
    assert result.supported
    game.resolve_stack()

    assert (tin.effective_power, tin.effective_toughness) == (4, 4)
    assert tin.has_keyword("first strike")
    # The bystander took nothing: the counter and the keyword both read the
    # printed noun phrase, not the first creature a scan reaches.
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert not bear.has_keyword("first strike")
    assert not game.is_on_battlefield(brass)

    # Indefinitely: two turn boundaries later it is still a 4/4 first-striker.
    game.start_turn(1)
    game.resolve_stack()
    game.start_turn(0)
    game.resolve_stack()
    assert (tin.effective_power, tin.effective_toughness) == (4, 4)
    assert tin.has_keyword("first strike")


def test_a_chimera_refuses_to_activate_with_no_chimera_to_aim_at(set_pool):
    """CR 602.2b/601.2c: a mandatory object target that cannot be filled is
    refused with nothing paid, rather than activated onto a bystander. Written
    as the refusal half of the production, because a placement that admitted
    every creature would pass every positive case above."""
    game, (brass, bear) = _g5_board(
        set_pool, "Brass-Talon Chimera", "Grizzly Bears",
    )

    result = game.activate_permanent_ability(
        0, "Brass-Talon Chimera",
        target_player_index=0,
        target_permanent_index=game.battlefield_index_of(bear),
    )

    assert not result.supported
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert not bear.has_keyword("first strike")
    # Nothing was paid: the Chimera is still on the battlefield.
    assert game.is_on_battlefield(brass)


def test_the_counter_placement_still_refuses_a_narrowing_it_cannot_test(set_pool):
    """The allow-set was widened by exactly two fields, so a phrase outside it
    still refuses rather than being silently dropped — which is the direction
    ``_restrictions_beyond`` exists to fail in."""
    from engine.grammar import lower_ability, parse_line
    from engine.grammar.errors import LoweringError

    with pytest.raises(LoweringError, match="lands on a creature"):
        lower_ability(parse_line(
            "put a +2/+2 counter on target tapped chimera creature"
        ))


# --- W1G5: a look, a price and the card it turned up (Wand of Denial) ---



def test_wand_of_denial_bins_only_a_nonland_and_only_if_paid_for(set_pool):
    """"{T}: Look at the top card of target player's library. If it's a nonland
    card, you may pay 2 life. If you do, put it into that player's graveyard."

    Four gaps in one line, three of them in the *parse*: "if it's a **nonland**
    card" is Wand of Ith's "if it isn't a land card" with the negation inside
    the noun phrase, and only one spelling was read; "you may pay **2 life**"
    is a price with no mana in it, which the mana reader refuses outright; and
    "put **it** into that player's graveyard" names the card the look turned up,
    where the production beside it moves the ability's own source. The fourth is
    that the look recorded nothing, so even a parsed pronoun had no producer.
    """
    vis, lea = set_pool("VIS"), set_pool("LEA")
    program = _g5w_compile(vis["Wand of Denial"])
    assert program.supported, program.reason
    steps = program.activated_abilities[0].instruction.payload["steps"]
    assert [step.kind for step in steps] == [
        "look_at_target_library_top", "if_then",
    ]
    assert steps[1].payload["condition"]["excluded_types"] == ["land"]
    offer = steps[1].payload["then"][0]
    assert offer.kind == "may" and offer.payload["life_cost"] == 2
    assert offer.payload["then"][0].kind == "bin_revealed_card"

    def play(top, *, pay):
        wand = Permanent(card=vis["Wand of Denial"])
        game = Game(players=[
            PlayerState(name="P1", battlefield=[wand], library=[lea["Island"]] * 4),
            PlayerState(name="P2", library=[top, lea["Forest"], lea["Swamp"]]),
        ])
        game.enforce_mana_costs = False
        game.interactive_seats = {0}
        game._settle()
        wand.metadata["summoning_sickness_turn"] = -99
        assert game.activate_permanent_ability(
            0, "Wand of Denial", target_player_index=1,
        ).supported
        game.resolve_stack()
        for _ in range(4):
            if not game.pending_choices:
                break
            pending = game.pending_choices[0]
            if pending.kind == "reorder_library":
                game.confirm_reorder_library(
                    0, list(range(pending.data["top_count"])), False,
                )
            else:
                game.resolve_pending_choice(pending.kind, 0, accept=pay)
            game.resolve_stack()
        return game

    paid = play(lea["Black Lotus"], pay=True)
    assert paid.players[0].life == 18
    assert [c.name for c in paid.players[1].graveyard] == ["Black Lotus"]

    declined = play(lea["Black Lotus"], pay=False)
    assert declined.players[0].life == 20
    assert declined.players[1].graveyard == []

    # A land on top is not offered at all: the price is behind the printed
    # exclusion, not beside it.
    land = play(lea["Mountain"], pay=True)
    assert land.players[0].life == 20
    assert land.players[1].graveyard == []
    assert land.players[1].library[0].name == "Mountain"


# --- W2G1: costs, alternative and additional ---

from engine import Game as _W2G1aGame, PlayerState as _W2G1aPlayerState
from engine.models import Permanent as _W2G1aPermanent
from engine.card_loader import load_cards as _w2g1a_load, manifest_set_path as _w2g1a_path

_W2G1A_LEA = {c.name: c for c in _w2g1a_load(_w2g1a_path("LEA"))}


def _w2g1a_scene(set_pool, hand):
    p1 = _W2G1aPlayerState(name="A", hand=list(hand))
    p2 = _W2G1aPlayerState(name="B")
    game = _W2G1aGame(players=[p1, p2])
    game.enforce_mana_costs = False
    p1.battlefield.append(_W2G1aPermanent(card=set_pool("VIS")["Juju Bubble"]))
    return game, p1, p2


def test_juju_bubble_goes_when_its_controller_plays_a_land(set_pool):
    """CR 701.18b: to play a card is to play it as a land **or** cast it as a
    spell. A trigger that watched only casts would leave the artifact sitting
    through a land drop, which is half the card."""
    game, caster, _ = _w2g1a_scene(set_pool, [_W2G1A_LEA["Forest"]])

    game.queue_from_hand(0, "Forest")
    game.resolve_stack()

    assert [p.card.name for p in caster.battlefield] == ["Forest"]
    assert [c.name for c in caster.graveyard] == ["Juju Bubble"]


def test_juju_bubble_goes_when_its_controller_casts_a_spell(set_pool):
    """The other half of the same rule."""
    game, caster, _ = _w2g1a_scene(set_pool, [_W2G1A_LEA["Lightning Bolt"]])

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.resolve_stack()

    assert "Juju Bubble" in {c.name for c in caster.graveyard}


def test_juju_bubble_ignores_the_other_seat(set_pool):
    """The printed word is "**you**"."""
    game, caster, opponent = _w2g1a_scene(set_pool, [])
    opponent.hand.append(_W2G1A_LEA["Forest"])

    game.queue_from_hand(1, "Forest")
    game.resolve_stack()

    assert [p.card.name for p in caster.battlefield] == ["Juju Bubble"]
    assert caster.graveyard == []

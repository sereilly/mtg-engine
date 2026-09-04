"""Per-card tests for Mirage's enchantments — wave 2's sections.

The continuation of `test_mir_enchantments.py`, which crossed the 2,600-line
guard at wave 2's integration by **one line**, with no single group at fault:
four groups' blocks merely summed. Cut at the wave boundary, the same seam
`test_mir_creatures_wave_two.py` took one merge earlier — every section here is
self-contained and written up in ROADMAP.md under the group that bought it, so
a section stays whole and stays findable from its round.

The same block convention holds: append a delimited block headed
``# --- W<wave>G<n>: <topic> ---`` with **its own imports at the top of its own
block**, and do not edit this docstring or an earlier block.
"""

from __future__ import annotations


# --- W2G3: Binding Agony and Circle of Despair ---
#
# One Aura that watches an event about its *host* rather than about itself, and
# one enchantment whose activated ability makes two choices in one announcement
# — a target to protect and a source to protect it from.

from engine import Game as _w2g3e_Game, PlayerState as _w2g3e_PlayerState  # noqa: E402
from engine.auras import attach_aura as _w2g3e_attach  # noqa: E402
from engine.card_loader import (load_cards as _w2g3e_load,  # noqa: E402
                                manifest_set_path as _w2g3e_path)
from engine.models import Permanent as _w2g3e_Permanent  # noqa: E402
from engine.shields import shields_on as _w2g3e_shields  # noqa: E402


def _w2g3e_lea():
    return {card.name: card for card in _w2g3e_load(_w2g3e_path("LEA"))}


def _w2g3e_board(pool, seats, hand=()):
    """A game with *seats* — ``(seat, card name, which pool)`` — already in play."""
    lea = _w2g3e_lea()
    game = _w2g3e_Game(players=[
        _w2g3e_PlayerState(name="P1", hand=[lea[name] for name in hand],
                           library=[lea["Island"]] * 6),
        _w2g3e_PlayerState(name="P2", library=[lea["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat, name in seats:
        card = pool[name] if name in pool else lea[name]
        game._put_permanent_onto_battlefield(seat, _w2g3e_Permanent(card=card), None)
    for player in game.players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


def test_w2g3_binding_agony_bites_the_hosts_controller(set_pool):
    """"Whenever enchanted creature is dealt damage, this Aura deals that much
    damage to that creature's controller."

    Three pieces met here. The trigger's subject is the Aura's *host*, so the
    fire site scans what is attached to the damaged creature as well as the
    creature's own card — an Aura's ability is the Aura's, not a granted ability
    of its host (CR 113.7a). And "that creature's controller" is frozen while
    the creature is still on the battlefield, which is what makes the lethal
    case work at all: by the time this trigger resolves off the stack (CR 603.3)
    the creature is a card in a graveyard with no controller (CR 400.7).
    """
    pool = set_pool("MIR")
    game = _w2g3e_board(
        pool, [(0, "Binding Agony"), (1, "Hill Giant")], hand=["Lightning Bolt"],
    )
    aura = game.players[0].battlefield[0]
    giant = game.players[1].battlefield[0]
    _w2g3e_attach(aura, giant)

    cast = game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=1, target_permanent_index=0,
    )
    assert cast.supported, cast.details
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(giant), "3 to a 3/3 is lethal"
    assert game.players[1].life == 17, "the dead creature's controller takes 3"
    assert game.players[0].life == 20, "never the Aura controller's"


def test_w2g3_binding_agony_is_silent_about_other_creatures(set_pool):
    """The trigger is about the host and nothing else. Damage to a creature the
    Aura is not on fires it nowhere — the scan is over what is attached to the
    *damaged* permanent, so an Aura elsewhere on the board never sees it."""
    pool = set_pool("MIR")
    game = _w2g3e_board(
        pool,
        [(0, "Binding Agony"), (1, "Hill Giant"), (1, "Grizzly Bears")],
        hand=["Lightning Bolt"],
    )
    aura = game.players[0].battlefield[0]
    giant, bears = game.players[1].battlefield
    _w2g3e_attach(aura, giant)

    game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=1, target_permanent_index=1,
    )
    game.resolve_stack()
    game._settle()

    assert not game.is_on_battlefield(bears), "3 to a 2/2 is lethal"
    assert game.is_on_battlefield(giant), "the Aura's host was never damaged"
    assert game.players[1].life == 20, "the Bears wear no Aura"


def _w2g3e_circle(pool):
    """Circle of Despair, a creature to protect, a creature to eat, two pingers."""
    game = _w2g3e_board(pool, [
        (0, "Circle of Despair"),
        (0, "Hill Giant"),               # the protected target
        (0, "Mons's Goblin Raiders"),    # the sacrifice the cost eats
        (1, "Prodigal Sorcerer"),        # the chosen source
        (1, "Rod of Ruin"),              # a source nobody chose
    ])
    return game, game.players[0].battlefield[1]


def _w2g3e_arm(game, protected):
    """Activate the Circle: the target on the target channel, the source on the
    announcement's own ``chosen_source`` field."""
    used = game.activate_permanent_ability(
        0, "Circle of Despair",
        target_player_index=0, target_permanent_ids=[protected.permanent_id],
        source_seat=1, source_permanent_index=0, cost_permanent_index=2,
    )
    assert used.supported, used.details
    game.resolve_stack()
    game._settle()


def test_w2g3_circle_of_despair_shields_the_creature_it_named(set_pool):
    """"{1}, Sacrifice a creature: The next time a source of your choice would
    deal damage to any target this turn, prevent that damage."

    The shield goes around what the ability *targeted* — CR 615.1 puts one
    around a player or a permanent — and answers to the source the announcement
    chose, which cannot ride the target channel because the target is spent on
    the thing being protected.
    """
    pool = set_pool("MIR")
    game, giant = _w2g3e_circle(pool)
    _w2g3e_arm(game, giant)

    armed = _w2g3e_shields(giant)
    assert [s.kind for s in armed] == ["prevent_whole"], game.log
    assert armed[0].source.card.name == "Prodigal Sorcerer"

    game.activate_permanent_ability(
        1, "Prodigal Sorcerer", target_player_index=0,
        target_permanent_index=1, ability_index=0,
    )
    game.resolve_stack()
    game._settle()

    assert giant.damage_marked == 0
    assert not _w2g3e_shields(giant), "one use, spent (CR 615.3)"


def test_w2g3_circle_of_despair_ignores_a_source_nobody_chose(set_pool):
    """The other half of the same shield, and the half a dropped choice would
    get wrong: with no source recorded the handler falls back to a shield
    answering to everything, which is a strictly stronger card."""
    pool = set_pool("MIR")
    game, giant = _w2g3e_circle(pool)
    _w2g3e_arm(game, giant)

    game.activate_permanent_ability(
        1, "Rod of Ruin", target_player_index=0,
        target_permanent_index=1, ability_index=0,
    )
    game.resolve_stack()
    game._settle()

    assert giant.damage_marked == 1, "the Rod is not the chosen source"
    assert len(_w2g3e_shields(giant)) == 1, "and the shield is still waiting"


def test_w2g3_circle_of_despair_can_shield_a_player(set_pool):
    """"Any target" is CR 115.4's four kinds, and the player half goes through
    the same handler: the shield lands on whoever the ability named."""
    pool = set_pool("MIR")
    game, _giant = _w2g3e_circle(pool)
    game.activate_permanent_ability(
        0, "Circle of Despair", target_player_index=0,
        source_seat=1, source_permanent_index=0, cost_permanent_index=2,
    )
    game.resolve_stack()
    game._settle()

    assert [s.kind for s in _w2g3e_shields(game.players[0])] == ["prevent_whole"]

    game.activate_permanent_ability(
        1, "Prodigal Sorcerer", target_player_index=0, ability_index=0,
    )
    game.resolve_stack()
    game._settle()

    assert game.players[0].life == 20


def test_w2g3_the_circle_asks_for_a_target_and_then_a_source(set_pool):
    """The picker's shape, because a card whose source went unasked is a card
    whose shield answers to everything. Two choices in one announcement is Jade
    Monolith's spec — a target, then ``requires_source``'s second prompt."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    pool = set_pool("MIR")
    program = compile_card_oracle(pool["Circle of Despair"])
    spec = derive_activation_spec(program.activated_abilities[0])

    assert spec == {
        "kind": "any",
        "requires_source": True,
        # "**Sacrifice a creature**" is a third choice in the same
        # announcement (CR 602.2b reaching CR 601.2b), and it has always had
        # its own picker.
        "cost_spec": {"kind": "creature", "own_only": True, "sacrifice_cost": True},
    }, spec


# --- W2G5: a chosen *land* type (CR 205.3i, CR 614.1c) ---
#
# Shimmer names a fourth quality the "as this enters, choose ..." sentence can
# carry, and the whole of what made it hard is that the phrase it is read back
# by is **identical** to An-Zerrin Ruins': "of the chosen type". The catalog the
# word came from is spelled exactly once, in the head noun — a land there, a
# creature there — so the noun phrase produces a different filter key and the
# choice is recorded in a different slot on the source. One key for both would
# have let a Shimmer that named Desert answer a sentence asking for a creature
# type, and stored a land type under a creature type's name for the next reader
# to trip on.

from engine import Game, PlayerState
from engine.grammar import compile_line
from engine.lord_buffs import lord_buff_from_payload, lord_buff_payload
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card


def _w2g5_land(name: str, subtype: str) -> Permanent:
    return Permanent(card=_mk_card(name, f"Land - {subtype}", ""))


def _w2g5_shimmer_board(set_pool, *, chosen: str | None = None, interactive=False):
    """Shimmer on seat 0; seat 1 holding an Island, a Forest and a Desert.

    A Desert on purpose: CR 205.3i's land types are not the five basics, and
    "choose a land type" may name any of them — which is why this choice does
    not travel on the five-way encoding Illusionary Terrain's ordered pair uses.
    """
    pool = set_pool("MIR")
    shimmer = Permanent(card=pool["Shimmer"])
    island = _w2g5_land("Isle", "Island")
    forest = _w2g5_land("Wood", "Forest")
    desert = _w2g5_land("Dust", "Desert")
    game = Game(players=[
        PlayerState(name="P1", battlefield=[shimmer]),
        PlayerState(name="P2", battlefield=[island, forest, desert]),
    ])
    game.enforce_mana_costs = False
    # A non-interactive seat takes the default the moment the prompt is armed,
    # so a test that means to *answer* has to own a seat that waits.
    game.interactive_seats = {0} if interactive else set()
    game._initialize_permanent_state(shimmer, 0, 1)
    if chosen is not None:
        shimmer.metadata["chosen_land_type"] = chosen
        game._recalculate_lord_buffs()
    game._settle()
    return game, shimmer, {"island": island, "forest": forest, "desert": desert}


def test_shimmer_is_supported(set_pool):
    program = compile_card_oracle(set_pool("MIR")["Shimmer"])
    assert program.supported, program.reason


def test_shimmer_grants_phasing_only_to_the_chosen_type(set_pool):
    """The static, in a game. The restriction is the whole card: an anthem that
    lost it would phase out every land on the board, which is the widening
    direction and silent."""
    game, _shimmer, lands = _w2g5_shimmer_board(set_pool, chosen="desert")

    assert game._has_keyword(lands["desert"], "phasing")
    assert not game._has_keyword(lands["island"], "phasing")
    assert not game._has_keyword(lands["forest"], "phasing")


def test_shimmer_may_name_a_nonbasic_land_type(set_pool):
    """A Desert is a land type (CR 205.3i) and not a basic one, so the choice
    travels as the word rather than on the colour encoding the *basic* pair
    uses. Asserted through the resolver the web answer path calls, so the
    prompt and the record cannot disagree."""
    game, shimmer, lands = _w2g5_shimmer_board(set_pool, interactive=True)

    assert game.confirm_enter_choice(0, land_type="desert")
    game._settle()

    assert shimmer.metadata["chosen_land_type"] == "desert"
    assert game._has_keyword(lands["desert"], "phasing")


def test_shimmer_refuses_a_word_that_is_not_a_land_type(set_pool):
    """CR 205.3i bounds the choice by the catalog, so an answer outside it is
    refused rather than repaired — quietly keeping the default would tell the
    player they had chosen something they had not. "Bear" is a creature type,
    which is the near miss the two keys exist to keep apart."""
    game, shimmer, _lands = _w2g5_shimmer_board(set_pool, interactive=True)
    shimmer.metadata["chosen_land_type"] = "island"

    assert not game.confirm_enter_choice(0, land_type="bear")
    assert shimmer.metadata["chosen_land_type"] == "island"


def test_shimmer_s_lands_phase_out_at_their_controller_s_untap_step(set_pool):
    """CR 702.26a's alternation, reached through layer 6 — the keyword is a
    derived grant, not a flag anyone wrote on the land."""
    game, _shimmer, lands = _w2g5_shimmer_board(set_pool, chosen="forest")

    game.start_turn(1)

    assert lands["forest"] in game.players[1].phased_out
    assert lands["island"] not in game.players[1].phased_out
    assert lands["desert"] not in game.players[1].phased_out


def test_shimmer_leaving_takes_the_phasing_with_it(set_pool):
    """Derived on every recompute, so there is nothing to undo: the land stops
    having the keyword the moment the enchantment stops contributing it."""
    game, shimmer, lands = _w2g5_shimmer_board(set_pool, chosen="forest")
    assert game._has_keyword(lands["forest"], "phasing")

    game.remove_from_battlefield(shimmer)
    game._recalculate_lord_buffs()
    game._settle()

    assert not game._has_keyword(lands["forest"], "phasing")


def test_the_chosen_type_narrowing_survives_the_instruction(set_pool):
    """The payload is the only thing the consumer sees.

    ``_lord_filter``'s round trip proves the derivation *table* can carry a
    restriction; it says nothing about whether the emitted instruction does.
    The narrowing was carried through the first round trip and dropped by the
    second on the first writing of this, which is an anthem that compiles,
    reports supported and reaches every land there is.
    """
    compiled = compile_line("Each land of the chosen type has phasing.")
    assert compiled.instructions, compiled.parse_error or compiled.lowering_error
    payload = compiled.instructions[0].payload

    assert payload["chosen_land_type"] is True
    assert lord_buff_from_payload(payload).filter.chosen_land_type


# --- W2G5 (continued): two seats, one record, a name-keyed ban (CR 601.3a) ---
#
# Null Chamber is two templates, and both were shapes the engine had exactly
# half of.
#
# "You and an opponent **each** choose a card name" is two armings of the one
# `enter_choice` prompt rather than a new kind: what differs from Runed Halo's
# single choice is who answers and which slot the answer lands in, and both are
# data. It is read *before* Runed Halo's phrase, which is a substring of it —
# tried first that one would claim this line, record one name, and leave the
# opponent's choice unmade.
#
# And the ban is `global_cast_ban`'s twin keyed on what a card is *called*
# rather than on its type. One row for both halves of the printed sentence,
# because a spell and a land drop are the same action to `cast_from_hand` — and
# claiming only the casting half would ship an enchantment that stops a Wrath of
# God and lets its Island through, which is not the card.


def _w2g5_chamber_board(set_pool):
    """Null Chamber on seat 0, with a hand each side has cards to name from."""
    pool = set_pool("MIR")
    chamber = Permanent(card=pool["Null Chamber"])
    bear = _mk_card("Grizzly Bears", "{1}{G}", "Creature - Bear", "")
    wolf = _mk_card("Timber Wolves", "{1}{G}", "Creature - Wolf", "")
    forest = _mk_card("Forest", "", "Basic Land - Forest", "")
    tower = _mk_card("Ivory Tower", "{2}", "Artifact", "")
    game = Game(players=[
        PlayerState(name="P1", battlefield=[chamber], hand=[bear, wolf, forest, tower]),
        PlayerState(name="P2", battlefield=[Permanent(card=bear)], hand=[wolf]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game._initialize_permanent_state(chamber, 0, 1)
    return game, chamber


def test_null_chamber_is_supported(set_pool):
    program = compile_card_oracle(set_pool("MIR")["Null Chamber"])
    assert program.supported, program.reason


def test_both_seats_are_asked_and_both_answers_are_kept(set_pool):
    """Two prompts, one per seat, writing into two slots of one record. Written
    by index rather than appended, because a prompt answering into the wrong
    slot would swap the two players' choices — which no test of the *ban* could
    tell apart, since it reads the record as a set."""
    game, chamber = _w2g5_chamber_board(set_pool)

    owed = [(c.player_index, c.data.get("card_name_slot")) for c in game.pending_choices]
    assert owed == [(0, 0), (1, 1)], owed

    assert game.confirm_enter_choice(0, card_name="Grizzly Bears")
    assert game.confirm_enter_choice(1, card_name="Timber Wolves")

    assert chamber.metadata["chosen_card_names"] == ["Grizzly Bears", "Timber Wolves"]


def test_a_basic_land_name_is_refused(set_pool):
    """The one restriction the sentence prints, and the whole of the card's
    cost: without it Null Chamber names Forest and stops a deck. Refused rather
    than repaired — quietly keeping the default would tell the player they had
    chosen something they had not."""
    game, chamber = _w2g5_chamber_board(set_pool)

    assert not game.confirm_enter_choice(0, card_name="Forest")
    assert [c.player_index for c in game.pending_choices] == [0, 1], (
        "a rejected answer leaves the prompt owed"
    )


def test_the_ban_binds_both_players_including_its_controller(set_pool):
    """CR 601.3a: the sentence names nobody, so it binds everybody — which for
    this card is the design, since one of the two names is the *opponent's*
    choice and stops the enchantment's own controller."""
    game, _chamber = _w2g5_chamber_board(set_pool)
    assert game.confirm_enter_choice(0, card_name="Grizzly Bears")
    assert game.confirm_enter_choice(1, card_name="Timber Wolves")
    game.start_turn(0)

    stopped = game.cast_from_hand(0, "Timber Wolves")
    assert not stopped.supported
    assert "Null Chamber" in stopped.details

    assert game.cast_from_hand(0, "Ivory Tower").supported, (
        "the control: a card neither seat named is unaffected"
    )


def test_a_named_land_cannot_be_played_either(set_pool):
    """"…**and lands with the chosen names can't be played**." The second half
    of one printed sentence, and the half a type-keyed ban cannot express — the
    gate sits above the land-drop refusal, which is behind `enforce_mana_costs`
    while a prohibition is not."""
    pool = set_pool("MIR")
    chamber = Permanent(card=pool["Null Chamber"])
    haven = _mk_card("Safe Haven", "", "Land", "")
    game = Game(players=[
        PlayerState(name="P1", battlefield=[chamber], hand=[haven]),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._initialize_permanent_state(chamber, 0, 1)
    assert game.confirm_enter_choice(0, card_name="Safe Haven")
    game.start_turn(0)

    refused = game.cast_from_hand(0, "Safe Haven")

    assert not refused.supported
    assert "Null Chamber" in refused.details, refused.details


# --- W2G5 (continued): the multiplier at its other printed position ---
#
# "When a round extends a fragment production, look for the other one first."
# Waiting in the Weeds prints "…token **for each** untapped Forest they control"
# with nothing after the token spec; Tombstone Stairwell prints "…token **named
# Tombspawn** for each creature card in their graveyard", and the name parser
# ran to the end of the line — so it swallowed the multiplier and called the
# token "Tombspawn For Each Creature Card In Their Graveyard", one per player,
# where the card makes one per creature card.
#
# Tombstone Stairwell does not collect this yet: its trigger line refuses one
# layer up, on the intervening-if ("at the beginning of each upkeep, **if this
# enchantment is on the battlefield**"), and `oracle_diff` reports no card moved.
# What it buys is the production this branch added being right at *both* printed
# positions rather than at the one the first card happened to use.

from engine.grammar import compile_line as _w2g5_compile_line


def test_a_token_name_does_not_swallow_the_multiplier():
    """The name and the count are two clauses, and the name is read first. No
    token Magic prints is named "… for each …", so stopping the run there costs
    nothing — and leaving it unbounded costs the whole count."""
    compiled = _w2g5_compile_line(
        "Each player creates a 2/2 black Zombie creature token with haste named "
        "Tombspawn for each creature card in their graveyard."
    )
    assert compiled.instructions, compiled.parse_error or compiled.lowering_error
    payload = compiled.instructions[0].payload

    assert payload["name"] == "Tombspawn"
    assert payload["count"]["per_recipient"] is True
    assert payload["count"]["per_each"]["zone"] == "graveyard"


def test_the_zone_possessive_names_the_recipient_too():
    """One printed clause names the distributed player two ways: "they
    **control**" narrows by controller and "**their** graveyard" names a zone
    owner. Reading only the first would take the graveyard count on the
    caster's pile for every player — the same number for everyone, and the
    caster's."""
    compiled = _w2g5_compile_line(
        "Each player creates a 1/1 white Soldier creature token for each "
        "creature card in their graveyard."
    )
    assert compiled.instructions, compiled.parse_error or compiled.lowering_error

    assert compiled.instructions[0].payload["count"]["per_recipient"] is True


# --- W2G2: upkeep, delayed triggers and counters ---

from engine import Game, PlayerState
from engine.auras import attach_aura, aura_color_grants, detach_aura
import pytest

from engine.land_mana_swaps import swapped_symbol
from engine.linked_exile import linked_entries
from engine.named_counters import add_counters, counters_on, remove_counters
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g2_vanilla(name: str, power: int = 2, toughness: int = 2,
                  colors: tuple[str, ...] = ("G",)) -> CardDefinition:
    type_line = "Creature - Test"
    return CardDefinition(
        name=name, mana_cost="{G}", cmc=1.0, type_line=type_line,
        oracle_text="", colors=colors, color_identity=colors, keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g2_game(*battlefield, opponent=()):
    game = Game(players=[
        PlayerState(name="P1", battlefield=list(battlefield), life=20),
        PlayerState(name="P2", battlefield=list(opponent), life=20),
    ])
    game.interactive_seats = set()
    game._settle()
    return game


def test_grave_servitude_makes_the_creature_black_and_gives_back_its_colour(set_pool):
    """"Enchanted creature gets +3/-1 **and is black**."

    CR 105.3: a granted colour **replaces** every colour the object had, and
    CR 613.1e puts it in layer 5. Derived from the Aura's own text on each
    recompute like every other half of ``auras.py``, so detaching it gives the
    printed colour back with nothing having to be undone — which is the whole
    reason the grant is not a ``color_override`` stamped onto the creature: an
    override that replaced every colour would leave nothing to put back.
    """
    pool = set_pool("MIR")
    aura = Permanent(card=pool["Grave Servitude"])
    host = Permanent(card=_w2g2_vanilla("Host", 2, 2, colors=("W",)))
    game = _w2g2_game(aura, host)

    assert host.effective_colors == {"W"}

    attach_aura(aura, host)
    game._settle()
    assert host.effective_colors == {"B"}, game.log
    # The P/T half of the same printed line still reads, which is the point of
    # `aura_static_pt_grant` searching rather than anchoring.
    assert (host.effective_power, host.effective_toughness) == (5, 1)

    detach_aura(aura, host)
    game._settle()
    assert host.effective_colors == {"W"}
    assert (host.effective_power, host.effective_toughness) == (2, 2)


def test_the_aura_colour_reader_takes_the_bare_sentence_too():
    """The grant is read off the printed line, and the P/T half in front of it
    is optional — a card printing "Enchanted creature is black" alone reaches
    the same layer-5 contribution. Asserted on the reader rather than on a
    card, because no card in this pool prints the bare form yet and a
    production that only worked with a P/T prefix in front of it is one the
    next such card would have to discover.
    """
    assert aura_color_grants("Enchanted creature gets +3/-1 and is black.") == ("black",)
    assert aura_color_grants("Enchanted creature is red.") == ("red",)
    # "as long as" is a condition this does not implement, so the anchored end
    # of the pattern refuses it rather than granting the colour unconditionally.
    assert aura_color_grants(
        "Enchanted creature is blue as long as you control a Forest."
    ) == ()


def test_purgatory_exiles_what_dies_and_buys_it_back_for_mana_and_life(set_pool):
    """Both halves of Purgatory, and the link between them (CR 610.3).

    The death trigger's "exile **that card**" prints no zone, because its own
    condition already said which one — so the card is the ``dead_card`` the
    death seam froze, found by identity. The exile is recorded against the
    enchantment, which is the only thing that can answer "a card exiled with
    this enchantment" a turn later.

    The upkeep offer charges "{4} **and** 2 life": one offer with two prices,
    where CR 118.8's "or" would be an alternative. Both are taken.
    """
    pool = set_pool("MIR")
    purgatory = Permanent(card=pool["Purgatory"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    lands = [Permanent(card=pool["Plains"]) for _ in range(5)]
    game = _w2g2_game(purgatory, bear, *lands)

    game._permanent_to_graveyard(game.players[0], bear)
    game.remove_from_battlefield(bear)
    game.resolve_stack()

    assert [c.name for c in game.players[0].graveyard] == []
    assert [c.name for c in game.players[0].exile] == ["Bear"]
    assert [e["card"].name for e in linked_entries(purgatory)] == ["Bear"], game.log

    game.start_turn(0)
    game.resolve_upkeep(0)
    game.resolve_stack()

    assert game.confirm_optional_pay(0, "Purgatory", accept=True), game.log
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    assert game.players[0].life == 18, game.log
    assert [c.name for c in game.players[0].exile] == []
    assert "Bear" in [p.card.name for p in game.players[0].battlefield], game.log
    # CR 610.3: the pile gives up one entry, and is not drained wholesale.
    assert linked_entries(purgatory) == ()


def test_purgatory_declines_its_own_offer_when_the_life_is_missing(set_pool):
    """"You may pay {4} **and** 2 life" is one price with two halves, so a
    player who can cover only one of them is never offered it at all
    (CR 601.2h asked of the whole cost).

    The direction matters: read as CR 118.8's alternative the offer would be
    takeable on the mana alone, and Purgatory would reanimate for free at one
    life.
    """
    pool = set_pool("MIR")
    purgatory = Permanent(card=pool["Purgatory"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    lands = [Permanent(card=pool["Plains"]) for _ in range(5)]
    game = _w2g2_game(purgatory, bear, *lands)

    game._permanent_to_graveyard(game.players[0], bear)
    game.remove_from_battlefield(bear)
    game.resolve_stack()

    game.players[0].life = 1
    game.start_turn(0)
    game.resolve_upkeep(0)
    game.resolve_stack()

    assert not game.pending_choices_of("optional_pay"), game.log
    assert game.players[0].life == 1
    assert [c.name for c in game.players[0].exile] == ["Bear"]


def test_purgatory_returns_the_card_under_its_controllers_control(set_pool):
    """"…return a card exiled with this enchantment **to the battlefield**" —
    the one destination with no possessive to print, so CR 110.2a decides: the
    card enters under the control of the player the effect instructed, which is
    this ability's controller.

    Its opposite is Safe Haven, which prints "under **its owner's** control"
    out loud; the two are different sentences and lower to different seats.
    """
    pool = set_pool("MIR")
    program = compile_card_oracle(pool["Purgatory"])
    upkeep = next(
        t for t in program.triggered_abilities
        if t.condition.kind == "upkeep_self"
    )
    assert upkeep.supported
    step = upkeep.instruction.payload["then"][0]
    assert step.kind == "put_exiled_with_source"
    assert step.payload["under_control_of"] == "chooser"
    # And no "you own" narrowing, which Purgatory does not print: its pile is
    # every card the enchantment exiled.
    assert "owned_by_chooser" not in step.payload


def test_afiya_grove_moves_a_counter_each_upkeep_and_dies_empty(set_pool):
    """Three lines, of which the engine used to run one: it entered with three
    +1/+1 counters and then did nothing at all, for ever.

    The upkeep line is CR 121.6's **move** — one action, not a removal and a
    placement — and the last line is CR 603.8's state trigger in the direction
    the threshold sweep could not express: the store being *empty*.
    """
    pool = set_pool("MIR")
    grove = Permanent(card=pool["Afiya Grove"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Forest"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Forest"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, grove, None)
    game._put_permanent_onto_battlefield(0, bear, None)
    game._settle()

    assert counters_on(grove, "+1/+1") == 3
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)

    for expected in (2, 1, 0):
        game.start_next_turn()
        if game.active_player_index != 0:
            game.start_next_turn()
        game.auto_resolve_pending_choices()
        game.resolve_stack()
        game._settle()
        assert counters_on(grove, "+1/+1") == expected, game.log

    # The counter really moved: what the Grove lost the Bear gained, and the
    # P/T came with it (CR 122.1a).
    assert (bear.effective_power, bear.effective_toughness) == (5, 5), game.log

    game.check_state_based_actions()
    game.resolve_stack()
    assert grove not in game.players[0].battlefield, game.log
    assert "Afiya Grove" in [c.name for c in game.players[0].graveyard]


def test_afiya_grove_moves_nothing_when_it_has_nothing(set_pool):
    """CR 121.6: with no counter on the source the move does not happen — to
    **either** end.

    The direction that matters: written as a ``sequence`` of the removal and
    the placement beside it, an empty Grove would still put a counter on the
    target, and its own last line would then never fire because it would be
    sacrificed the turn it emptied and grow the board every turn until then.
    """
    pool = set_pool("MIR")
    grove = Permanent(card=pool["Afiya Grove"])
    bear = Permanent(card=_w2g2_vanilla("Bear"))
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Forest"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Forest"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, grove, None)
    game._put_permanent_onto_battlefield(0, bear, None)
    game._settle()
    remove_counters(grove, "+1/+1", 3)
    assert counters_on(grove, "+1/+1") == 0

    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    assert (bear.effective_power, bear.effective_toughness) == (2, 2), game.log
    assert counters_on(bear, "+1/+1") == 0


def test_energy_vortex_tolls_the_chosen_player_per_counter(set_pool):
    """"At the beginning of **the chosen player's** upkeep, this enchantment
    deals 3 damage to that player unless they pay {1} **for each vortex
    counter** on this enchantment."

    Two things stood between this and firing, and both were gates written when
    ``upkeep_self`` was the only upkeep condition either pay-or-else flow could
    reach: the lowering refused every other upkeep condition outright, and the
    per-counter escalation had a reader only behind a *destruction*. The seat
    was never the problem — the upkeep step has frozen it on every ordinary
    firing since Takklemaggot.

    The price is read at resolution (CR 608.2), which is what makes the card
    work: its own upkeep trigger strips the counters a step earlier on its
    controller's turn, so the toll is whatever was put back since.
    """
    pool = set_pool("MIR")
    vortex = Permanent(card=pool["Energy Vortex"])
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Island"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Island"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, vortex, None)
    game._settle()

    # "As this enchantment enters, choose an opponent."
    assert vortex.metadata.get("chosen_player_index") == 1
    add_counters(vortex, "vortex", 2)

    game.start_turn(1)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    # Two counters, so the offer is {2}; P2 has no mana and takes the damage.
    assert any("may pay {2}" in line for line in game.log), game.log
    assert game.players[1].life == 17, game.log
    # The counters are not spent by the toll — only the controller's own upkeep
    # trigger removes them.
    assert counters_on(vortex, "vortex") == 2


def test_energy_vortex_offers_nothing_to_the_controller(set_pool):
    """The seat is the one the enters-choice recorded, not the ability's
    controller — so the Vortex's own upkeep brings the counter wipe and no
    toll at all.
    """
    pool = set_pool("MIR")
    vortex = Permanent(card=pool["Energy Vortex"])
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Island"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Island"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, vortex, None)
    game._settle()
    add_counters(vortex, "vortex", 3)

    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    assert game.players[0].life == 20, game.log
    # "At the beginning of your upkeep, remove all vortex counters from this
    # enchantment" — the half that already worked, and the reason the toll is
    # read at resolution rather than when the trigger was put on the stack.
    assert counters_on(vortex, "vortex") == 0, game.log


def _w2g2_soul_echo(set_pool, x: int):
    """Soul Echo on the battlefield with *x* echo counters, its first upkeep
    resolved and the offer answered."""
    pool = set_pool("MIR")
    echo = Permanent(card=pool["Soul Echo"])
    # "This enchantment enters with X echo counters on it" reads the announced
    # X (CR 601.2b) off the cast, which is the one thing a hand-built permanent
    # has to be given.
    echo.metadata["cast_x_value"] = x
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Plains"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Plains"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, echo, None)
    game._settle()
    return game, echo


def test_soul_echo_enters_with_its_announced_x(set_pool):
    """The half the census called hollow and the engine had all along.

    ``enters_with_x_named_counters`` has read this sentence since Iceberg; what
    was missing was everything downstream of it, so the counters went on and
    nothing ever took one off.
    """
    _game, echo = _w2g2_soul_echo(set_pool, 3)
    assert counters_on(echo, "echo") == 3


def test_soul_echo_turns_damage_into_counters_and_then_stops(set_pool):
    """The card end to end, and the bug it was hiding.

    "You don't lose the game for having 0 or less life" was live; the upkeep
    trigger that would sacrifice the enchantment was unsupported and the
    counters had nothing to remove them — so a player at −7 life never lost,
    for ever.

    The offer is CR 614's replacement, made to an **opponent** and covering the
    ability's *controller* (CR 109.5's "you"), and it takes one counter per
    point of damage. As much as possible (CR 614.6): a store smaller than the
    damage gives up what it has and the rest is dealt, which is what makes the
    card finite.
    """
    game, echo = _w2g2_soul_echo(set_pool, 3)
    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    game._deal_damage_to_player(game.players[0], 2)
    assert game.players[0].life == 20, game.log
    assert counters_on(echo, "echo") == 1

    # Five more against one counter: one point becomes a counter and four are
    # dealt.
    game._deal_damage_to_player(game.players[0], 5)
    assert counters_on(echo, "echo") == 0
    assert game.players[0].life == 16, game.log

    # …and from here it is an ordinary damage event again.
    game._deal_damage_to_player(game.players[0], 3)
    assert game.players[0].life == 13, game.log


def test_soul_echo_stops_protecting_once_its_counters_are_gone(set_pool):
    """The whole point of the card, and the exact bug: below zero life the
    static holds while the enchantment is there, and the upkeep trigger takes
    the enchantment away the moment its store is empty (CR 704.5a then ends the
    game).
    """
    game, echo = _w2g2_soul_echo(set_pool, 2)
    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    game._deal_damage_to_player(game.players[0], 27)
    game.check_state_based_actions()
    assert game.players[0].life == -5
    assert not any("lost the game" in line for line in game.log), game.log

    game.start_next_turn()
    game.start_next_turn()
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    game.check_state_based_actions()

    assert echo not in game.players[0].battlefield, game.log
    assert any("lost the game" in line for line in game.log), game.log


def test_soul_echo_offers_a_fresh_replacement_every_upkeep(set_pool):
    """"…until your next upkeep" is swept at the top of that upkeep, before the
    trigger that offers a new one — the rule every other duration of this
    spelling already follows there.

    Without the sweep the record would stand for ever and the opponent's
    decision would be made once, on the first upkeep, for the rest of the game.
    """
    from engine.replacements import DAMAGE_TO_COUNTER_REMOVAL_RECORD

    game, echo = _w2g2_soul_echo(set_pool, 4)
    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    assert echo.metadata.get(DAMAGE_TO_COUNTER_REMOVAL_RECORD) == {
        "counter": "echo", "seat": 0,
    }

    game.start_next_turn()          # the opponent's turn — the record stands
    assert DAMAGE_TO_COUNTER_REMOVAL_RECORD in echo.metadata, game.log

    game.start_next_turn()          # back to the controller: swept, then re-armed
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    assert echo.metadata.get(DAMAGE_TO_COUNTER_REMOVAL_RECORD) == {
        "counter": "echo", "seat": 0,
    }, game.log


def test_the_counter_replacement_covers_only_the_abilitys_controller(set_pool):
    """CR 109.5: "you" is the ability's controller wherever it is printed, and
    this sentence is printed inside an offer made to somebody else.

    Read off the offer instead, Soul Echo would spend its counters on damage
    dealt to the opponent — the whole card inverted — so the lowering pins the
    seat and the arming handler records it.
    """
    from engine.replacements import DAMAGE_TO_COUNTER_REMOVAL_RECORD

    game, echo = _w2g2_soul_echo(set_pool, 3)
    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    assert echo.metadata[DAMAGE_TO_COUNTER_REMOVAL_RECORD]["seat"] == 0

    # Damage to the seat that was *offered* the choice is ordinary damage.
    game._deal_damage_to_player(game.players[1], 3)
    assert game.players[1].life == 17, game.log
    assert counters_on(echo, "echo") == 3


def test_hall_of_gemstone_makes_every_land_produce_the_active_players_colour(set_pool):
    """"At the beginning of each player's upkeep, **that player** chooses a
    color. Until end of turn, lands tapped for mana produce mana of the chosen
    color instead of any other color."

    Two halves and two seats. The chooser is the seat the fire site froze
    (CR 603.10) — a different player every turn and never the enchantment's
    controller except on their own turn — and the swap covers *every* player's
    lands, because the sentence names no seat at all.
    """
    pool = set_pool("MIR")
    hall = Permanent(card=pool["Hall of Gemstone"])
    forest = Permanent(card=pool["Forest"])
    island = Permanent(card=pool["Island"])
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Forest"]] * 20),
        PlayerState(name="P2", library=[pool["Island"]] * 20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, hall, None)
    game._put_permanent_onto_battlefield(0, forest, None)
    game._put_permanent_onto_battlefield(1, island, None)
    game._settle()

    assert swapped_symbol(game, forest) is None
    assert swapped_symbol(game, island) is None

    game.start_turn(0)
    game.auto_resolve_pending_choices()
    game.resolve_stack()

    chosen = hall.metadata.get("chosen_color")
    assert chosen, game.log
    assert swapped_symbol(game, forest) == chosen, game.log
    # The opponent's Island too: the swap is armed on every seat, because
    # ``swapped_symbol`` asks the land's *own* controller for their records.
    assert swapped_symbol(game, island) == chosen, game.log

    game.tap_land_for_mana(1, "Island")
    assert game.players[1].mana_pool.get(chosen) == 1, game.log
    assert not game.players[1].mana_pool.get("U"), game.log


def test_hall_of_gemstone_asks_the_player_whose_upkeep_it_is(set_pool):
    """The seat is read off the frozen event and not off the enchantment's
    controller, which is the difference the card's own subject is printed for.
    """
    pool = set_pool("MIR")
    hall = Permanent(card=pool["Hall of Gemstone"])
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Forest"]] * 20),
        PlayerState(name="P2", library=[pool["Island"]] * 20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, hall, None)
    game._settle()

    game.start_turn(1)
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    assert any("P2 chooses a color" in line for line in game.log), game.log


def test_consuming_ferocity_grows_its_host_then_kills_it(set_pool):
    """The whole trigger, and every pronoun in it names the same object.

    "Put a +1/+0 counter on **enchanted creature**. If **that creature** has
    three or more +1/+0 counters on it, **it** deals damage equal to **its**
    power to **its controller**, then destroy **that creature** and it can't be
    regenerated."

    Nothing after the first clause says "enchanted" again, so what makes the
    rest readable is the record that first step writes (CR 608.2h) — the same
    record Orcish Mine's destroy has written since it landed. Without it the
    damage clause reads "it" as the Aura, which has no power, and the card
    deals nothing while compiling clean.
    """
    pool = set_pool("MIR")
    aura = Permanent(card=pool["Consuming Ferocity"])
    victim = Permanent(card=_w2g2_vanilla("Victim", 2, 4))
    game = Game(players=[
        PlayerState(name="P1", library=[pool["Mountain"]] * 20, life=20),
        PlayerState(name="P2", library=[pool["Mountain"]] * 20, life=20),
    ])
    game.interactive_seats = set()
    game._put_permanent_onto_battlefield(0, aura, None)
    # An **opponent's** creature, so "its controller" and the ability's
    # controller are different seats — the whole reason the recipient is read
    # off the host rather than off the caster.
    game._put_permanent_onto_battlefield(1, victim, None)
    attach_aura(aura, victim)
    game._settle()

    assert (victim.effective_power, victim.effective_toughness) == (3, 4)

    for expected in (1, 2):
        game.start_next_turn() if expected > 1 else game.start_turn(0)
        if game.active_player_index != 0:
            game.start_next_turn()
        game.auto_resolve_pending_choices()
        game.resolve_stack()
        game._settle()
        assert counters_on(victim, "+1/+0") == expected, game.log
        assert game.players[1].life == 20, game.log
        assert victim in game.players[1].battlefield

    # The third counter crosses the threshold: 2 printed + 1 from the Aura's
    # static + 3 counters = 6 damage, to the creature's controller.
    game.start_next_turn()
    if game.active_player_index != 0:
        game.start_next_turn()
    game.auto_resolve_pending_choices()
    game.resolve_stack()
    game.check_state_based_actions()

    assert game.players[1].life == 14, game.log
    assert victim not in game.players[1].battlefield, game.log
    assert "Victim" in [c.name for c in game.players[1].graveyard]


def test_the_attached_counter_condition_refuses_an_unbound_that(set_pool):
    """"That creature" names the host only because a step in front of it did.

    The gate is the record, not the word: a line whose first sentence never
    touched the attachment leaves the pronoun naming nothing, and a condition
    that answered off the attachment anyway would be reading a card that never
    said "enchanted".
    """
    from engine.grammar import GrammarError, LoweringError, lower_ability, parse_line

    node = parse_line(
        "At the beginning of your upkeep, if that creature has three or more "
        "+1/+0 counters on it, destroy that creature."
    )
    with pytest.raises((GrammarError, LoweringError)):
        lower_ability(node)


def test_a_counter_condition_reads_a_pt_counter_kind():
    """"three or more **+1/+0** counters" against "three or more **echo**
    counters".

    The lexer gives a P/T counter its own token kind, so the word table never
    saw it — which is why Fasting's clause has worked since Ice Age and
    Consuming Ferocity's identical one refused.
    """
    from engine.grammar import lower_ability, parse_line

    instructions = lower_ability(parse_line(
        "If this enchantment has three or more +1/+0 counters on it, "
        "sacrifice it."
    ))
    assert [i.kind for i in instructions] == ["if_then"]
    assert instructions[0].payload["condition"] == {
        "kind": "source_counter_count",
        "counter": "+1/+0",
        "count": 3,
        "comparison": "at_least",
    }


# --- W2G4: a sweep with no seat, and a counter priced by a name ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g4_bazaar(set_pool, graveyard=(), battlefield=()):
    """Bazaar of Wonders on seat 0, a spell in seat 1's hand to cast into it."""
    bazaar = Permanent(card=set_pool("MIR")["Bazaar of Wonders"])
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[bazaar] + [
                Permanent(card=set_pool("MIR")[n]) for n in battlefield
            ],
            life=20,
        ),
        PlayerState(
            name="P2", hand=[set_pool("MIR")["Femeref Knight"]],
            graveyard=[set_pool("MIR")[n] for n in graveyard], life=20,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(1)
    return game


def test_bazaar_of_wonders_is_supported(set_pool):
    """Both lines were refusals and neither was about the other. "Exile all
    graveyards" names nobody, and "counter it **if** a card with the same name
    …" is a disjunction of two clauses comparing against an object the printed
    text never names."""
    program = compile_card_oracle(set_pool("MIR")["Bazaar of Wonders"])
    assert program.supported, program.reason
    assert program.instructions[0].payload == {"every": True}
    condition = program.instructions[1].payload["condition"]
    assert condition["kind"] == "any_of"
    assert [part["zone"] for part in condition["conditions"]] == [
        "graveyard", "battlefield",
    ]
    assert [part["nontoken"] for part in condition["conditions"]] == [False, True]


def test_bazaar_of_wonders_exiles_every_graveyard_as_it_enters(set_pool):
    """"Exile **all** graveyards" chooses no target (CR 115.1), so the sweep is
    the *absence* of a target description rather than a sentinel seat — and it
    reaches its own controller's pile as well as everyone else's."""
    game = Game(players=[
        PlayerState(
            name="P1", hand=[set_pool("MIR")["Bazaar of Wonders"]],
            graveyard=[set_pool("MIR")["Soar"]], life=20,
        ),
        PlayerState(
            name="P2",
            graveyard=[set_pool("MIR")["Femeref Knight"], set_pool("MIR")["Soar"]],
            life=20,
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game.queue_from_hand(0, "Bazaar of Wonders")
    game.resolve_stack()

    assert [c.name for c in game.players[0].graveyard] == [], game.log
    assert [c.name for c in game.players[1].graveyard] == [], game.log
    assert [c.name for c in game.players[0].exile] == ["Soar"], game.log
    assert [c.name for c in game.players[1].exile] == ["Femeref Knight", "Soar"]


def test_bazaar_of_wonders_lets_an_unmatched_spell_resolve(set_pool):
    """The condition is the card. Read as an unconditional counter it is Nether
    Void; the assertion is that a spell with no twin anywhere resolves."""
    game = _w2g4_bazaar(set_pool)
    game.queue_from_hand(1, "Femeref Knight")
    game.resolve_stack()

    assert [p.card.name for p in game.players[1].battlefield] == [
        "Femeref Knight"
    ], game.log


def test_bazaar_of_wonders_counters_a_spell_named_in_a_graveyard(set_pool):
    """"…if a card with the same name is in **a** graveyard" — any pile, not
    the caster's. The name compared against is the spell the trigger fired on,
    frozen by the cast fire site, because by resolution the spell may have left
    the stack."""
    game = _w2g4_bazaar(set_pool, graveyard=["Femeref Knight"])
    game.queue_from_hand(1, "Femeref Knight")
    game.resolve_stack()

    assert [p.card.name for p in game.players[1].battlefield] == [], game.log
    assert [c.name for c in game.players[1].graveyard] == [
        "Femeref Knight", "Femeref Knight",
    ], game.log


def test_bazaar_of_wonders_counters_a_spell_named_on_the_battlefield(set_pool):
    """The second half of the disjunction, and the half a card printing only
    the first would not have. Neither zone is the stack, so the spell being
    cast is never one of the objects it is compared with."""
    game = _w2g4_bazaar(set_pool, battlefield=["Femeref Knight"])
    game.queue_from_hand(1, "Femeref Knight")
    game.resolve_stack()

    assert [p.card.name for p in game.players[1].battlefield] == [], game.log


def test_bazaar_of_wonders_ignores_a_token_of_the_same_name(set_pool):
    """"a **nontoken** permanent with the same name" (CR 111). A production
    that consumed the word and dropped it would counter a spell whose only twin
    is a token, which is the opposite of what the card prints."""
    from engine.tokens import make_token_card

    game = _w2g4_bazaar(set_pool)
    token = Permanent(card=make_token_card("Femeref Knight", 2, 2, "Token Creature — Human Knight"))
    token.metadata["is_token"] = True
    game.players[0].battlefield.append(token)

    game.queue_from_hand(1, "Femeref Knight")
    game.resolve_stack()

    assert [p.card.name for p in game.players[1].battlefield] == [
        "Femeref Knight"
    ], game.log


# --- W2G1: combat triggers and their bound referents ---

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g1_creature(name, power, toughness, keywords=()) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=tuple(keywords),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g1_nosick(perm: Permanent) -> Permanent:
    perm.summoning_sick = False
    return perm


def _w2g1_combat(*seats) -> Game:
    """A game sitting in the declare-attackers step, one battlefield per seat."""
    game = Game(players=[
        PlayerState(name=f"P{i + 1}", battlefield=list(board))
        for i, board in enumerate(seats)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


def _w2g1_resolve(game: Game) -> None:
    for _ in range(40):
        if not game.stack:
            return
        game.resolve_top_of_stack()


def test_barbed_foliage_compiles_both_triggers_with_the_defender_narrowing(set_pool):
    """"Whenever a creature attacks **you**" is CR 506.2's defending player as a
    narrowing of the trigger's *subject*, and the word had been unread.

    The bare ``matching_creature_attacks`` row is a strict prefix of this one, so
    before the narrowed row existed the regex matched "whenever a creature
    attacks" and left "you" in the effect clause -- the silent widening the
    negative lookahead beside it exists to stop. Both front ends carry it: the
    grammar sets ``attacking_you`` on the parsed subject and the oracle table
    folds it in from an empty marker group, so the condition cannot be narrowed
    on one side of the pipeline and not the other.
    """
    program = compile_card_oracle(set_pool("MIR")["Barbed Foliage"])

    assert program.supported, program.reason
    conditions = [trig.condition for trig in program.triggered_abilities]
    assert [c.kind for c in conditions] == [
        "matching_creature_attacks", "matching_creature_attacks"
    ]
    assert all(
        c.payload["attacker_filter"].get("attacking_you") for c in conditions
    ), conditions
    # …and the second trigger keeps its own printed narrowing beside it.
    assert conditions[1].payload["attacker_filter"]["without_keywords"] == ["flying"]


def test_barbed_foliage_takes_flanking_off_the_attacker_and_gives_it_back(set_pool):
    """The first line, and the reason it needed a channel of its own.

    CR 702.25a *defines* flanking as a triggered ability, so the compiler builds
    it out of the printed keyword line and layer 6's word set is not where its
    reader looks -- a ``remove_keyword`` there would have recorded a removal and
    taken nothing away. ``remove_ability_keyword`` strikes the keyword out of the
    line instead, and the cleanup sweep puts it back (CR 611.2c).
    """
    flanker = _w2g1_nosick(Permanent(card=set_pool("MIR")["Mtenda Herder"]))
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    game = _w2g1_combat([flanker], [foliage])

    assert game._has_keyword(flanker, "flanking")
    assert game.declare_attackers(0, [0])[0]
    _w2g1_resolve(game)

    assert not game._has_keyword(flanker, "flanking"), game.log
    assert "flanking" not in flanker.effective_card.oracle_text.lower()

    game.resolve_cleanup_step(0)
    assert game._has_keyword(flanker, "flanking")
    assert "Flanking" in flanker.effective_card.oracle_text


def test_barbed_foliage_takes_a_granted_flanking_too(set_pool):
    """Agility grants flanking as a printed *line* and as the word, so a removal
    that struck only the line would leave the creature counting as "with
    flanking" for the next flanker's own filter.

    The order in ``Permanent.effective_card`` is what makes the line half work:
    the keyword strip runs after the grants are folded in, so it reaches a line
    that was not there when the removal was recorded.
    """
    host = _w2g1_nosick(Permanent(card=_w2g1_creature("Footman", 2, 2)))
    agility = Permanent(card=set_pool("MIR")["Agility"])
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    game = _w2g1_combat([host, agility], [foliage])
    attach_aura(agility, host)
    game._recompute_continuous_effects()

    assert game._has_keyword(host, "flanking")
    assert game.declare_attackers(0, [0])[0]
    _w2g1_resolve(game)

    assert not game._has_keyword(host, "flanking"), game.log
    assert "flanking" not in host.effective_card.oracle_text.lower()


def test_barbed_foliage_pings_the_ground_and_spares_the_flier(set_pool):
    """The second line: "**it**" is the attacker the event was about, not the
    enchantment that says the word.

    A bare "it" reads as the ability's own source, which is what it means on a
    line whose trigger names nothing else; here the pronoun is rebound to the
    condition's subject, so the damage needed a recipient that says so. Left to
    fall through, a targetless trigger's damage lands on whatever the resolution
    context was carrying.
    """
    ground = _w2g1_nosick(Permanent(card=_w2g1_creature("Footman", 2, 2)))
    flier = _w2g1_nosick(
        Permanent(card=_w2g1_creature("Skyguard", 2, 2, ("Flying",)))
    )
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    game = _w2g1_combat([ground, flier], [foliage])

    assert game.declare_attackers(0, [0, 1])[0]
    _w2g1_resolve(game)

    assert ground.damage_marked == 1, game.log
    assert flier.damage_marked == 0, game.log
    assert game.players[1].life == 20


def test_barbed_foliage_ignores_an_attack_aimed_at_somebody_else(set_pool):
    """The narrowing the word "you" is, shown where it is visible: a duel has
    one defender, so only a third seat can tell "attacks" from "attacks you".

    Dropped, the enchantment would ping a creature attacking a player it is not
    defending against -- and in a duel that difference never shows, which is
    exactly why the widening would have shipped.
    """
    attacker = _w2g1_nosick(Permanent(card=_w2g1_creature("Footman", 2, 2)))
    foliage = Permanent(card=set_pool("MIR")["Barbed Foliage"])
    victim = _w2g1_nosick(Permanent(card=_w2g1_creature("Bystander", 1, 1)))
    game = _w2g1_combat([attacker], [foliage], [victim])

    # Seat 2 is the defender; the Foliage sits on seat 1's battlefield.
    assert game.declare_attackers(0, [0], defending_player_index=2)[0]
    _w2g1_resolve(game)

    assert attacker.damage_marked == 0, game.log
    assert game._has_keyword(attacker, "flanking") is False  # it never had it


def _w2g1_reparations(set_pool, catalog_by_name, spell: str, mine_extra=()):
    """Reparations on seat 1's battlefield, with *spell* in seat 0's hand.

    The spell comes from the shipped catalog and the enchantment from MIR,
    which is still ``measured`` -- ``catalog_by_name`` is the shipped pool and
    does not carry it.
    """
    game = Game(players=[
        PlayerState(
            name="P1",
            battlefield=[_w2g1_nosick(Permanent(card=_w2g1_creature("Ogre", 3, 3)))],
            hand=[catalog_by_name[spell]],
        ),
        PlayerState(
            name="P2",
            battlefield=[Permanent(card=set_pool("MIR")["Reparations"]), *mine_extra],
            library=[_w2g1_creature("Top", 1, 1) for _ in range(5)],
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_reparations_narrows_on_what_the_spell_targets(set_pool):
    """"Whenever an opponent casts a spell **that targets you or a creature you
    control**."

    The bare ``opponent_casts_spell`` row is a strict prefix of this condition
    and claimed it, leaving the clause unread -- an enchantment that drew a card
    off every spell an opponent cast. The narrowing is not about the spell at
    all, so it rides as a marker the cast filter reads against what the
    announcement froze (CR 601.2c settles a spell's targets as it goes on the
    stack, and by resolution the spell may have been countered).
    """
    program = compile_card_oracle(set_pool("MIR")["Reparations"])
    assert program.supported, program.reason
    (trig,) = program.triggered_abilities
    assert "targets_you_or_your_creature" in trig.condition.payload
    assert trig.condition.raw_text.endswith("you or a creature you control")


@pytest.mark.parametrize(
    "spell, kwargs, mine_extra, fires",
    [
        ("Lightning Bolt", {"target_player_index": 1}, 0, True),
        ("Lightning Bolt", {"target_player_index": 0, "target_permanent_index": 0}, 0, False),
        ("Lightning Bolt", {"target_player_index": 1, "target_permanent_index": 1}, 1, True),
        ("Wrath of God", {}, 0, False),
    ],
    ids=["my face", "their own creature", "my creature", "targets nothing"],
)
def test_reparations_fires_only_on_a_spell_aimed_at_its_controller(
    set_pool, catalog_by_name, spell, kwargs, mine_extra, fires
):
    """The four readings the clause distinguishes, in a game.

    "You" is the trigger's own controller (CR 109.5), which is what keeps the
    enchantment silent while its opponents shoot at each other -- and a spell
    that targets nothing at all fires it never. The middle case is the one the
    unread clause got wrong: ``target_player_index`` beside a permanent index is
    a *battlefield* rather than a target, so a filter that read the field would
    have drawn off every removal spell pointed at anybody.
    """
    extra = [
        _w2g1_nosick(Permanent(card=_w2g1_creature("Bear", 2, 2)))
        for _ in range(mine_extra)
    ]
    game = _w2g1_reparations(set_pool, catalog_by_name, spell, mine_extra=extra)

    game.queue_from_hand(0, spell, **kwargs)
    game.resolve_stack()

    offered = [c for c in game.pending_choices if c.player_index == 1]
    assert bool(offered) is fires, game.log


def test_reparations_draws_when_its_controller_takes_the_offer(set_pool, catalog_by_name):
    """"…you **may** draw a card" -- the offer goes to the enchantment's
    controller, who is not the player whose turn it is."""
    game = _w2g1_reparations(set_pool, catalog_by_name, "Lightning Bolt")

    game.queue_from_hand(0, "Lightning Bolt", target_player_index=1)
    game.resolve_stack()
    assert game.confirm_optional_pay(1, accept=True)

    assert len(game.players[1].hand) == 1, game.log
    assert len(game.players[1].library) == 4


# --- W3G3: Preferred Selection, one looked-at pile and two destinations ---
#
# "At the beginning of your upkeep, look at the top two cards of your library.
# You may sacrifice this enchantment and pay {2}{G}{G}. If you do, put one of
# those cards into your hand. If you don't, put one of those cards on the
# bottom of your library."
#
# Four sentences and one pile. Both branches pick from the **same** two cards
# and only the destination differs, so the whole ability is an ordinary
# `ast.May` — its cost, its accept branch and its decline branch all reach
# machinery that already existed, and the look rides `May.looked_at_top` into
# the offer's own prompt.
#
# That last part is the card. "Look at the top two cards" is printed **first**,
# so the decision is not made blind: with the look folded into the branches
# instead, a player would be asked to sacrifice an enchantment and pay four
# mana before seeing what they were paying for — a strictly different card, and
# one no assertion about instruction kinds could tell apart from this one.
#
# The two picks are also genuinely different choices, which is why the offer
# has to come *before* the pick rather than after: paying, you take the best
# card; declining, you bury the worst.

from engine import (Game as _w3g3e_Game,  # noqa: E402
                    PlayerState as _w3g3e_PlayerState)
from engine.card_loader import (load_cards as _w3g3e_load,  # noqa: E402
                                manifest_set_path as _w3g3e_path)
from engine.models import Permanent as _w3g3e_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w3g3e_compile  # noqa: E402


def _w3g3e_lea():
    return {card.name: card for card in _w3g3e_load(_w3g3e_path("LEA"))}


def _w3g3e_selection_game(set_pool, lands=4):
    """Preferred Selection on seat 0, with Black Lotus and Mox Jet on top."""
    lea = _w3g3e_lea()
    enchantment = _w3g3e_Permanent(card=set_pool("MIR")["Preferred Selection"])
    forests = [_w3g3e_Permanent(card=lea["Forest"]) for _ in range(lands)]
    for forest in forests:
        forest.metadata["summoning_sickness_turn"] = -99
    game = _w3g3e_Game(players=[
        _w3g3e_PlayerState(
            name="P1", battlefield=[enchantment] + forests,
            library=[lea["Black Lotus"], lea["Mox Jet"], lea["Island"],
                     lea["Forest"], lea["Plains"]],
        ),
        _w3g3e_PlayerState(name="P2", library=[lea["Forest"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game.resolve_upkeep(0)
    game._settle()
    return game, enchantment


def test_w3g3_preferred_selection_is_supported(set_pool):
    """One offer, one look, two picks that differ only in where the card goes.

    The unchosen card goes back on **top** in both branches, which is where it
    already was: the card moves nothing it does not name.
    """
    program = _w3g3e_compile(set_pool("MIR")["Preferred Selection"])
    assert program.supported, program.reason

    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may" and offer.payload["actor"] == "you"
    assert offer.payload["cost"] == {"G": 2, "generic": 2}
    assert offer.payload["looked_at_library_top"] == 2
    assert [step.kind for step in offer.payload["action"]] == ["sacrifice_self"]

    taken = offer.payload["then"][0]
    declined = offer.payload["otherwise"][0]
    assert taken.kind == declined.kind == "look_top_pick_to_hand"
    assert taken.payload["amount"] == declined.payload["amount"] == 2
    assert taken.payload.get("pick_destination") is None       # the hand
    assert declined.payload["pick_destination"] == "library_bottom"
    assert taken.payload["rest_destination"] == "library_top"
    assert declined.payload["rest_destination"] == "library_top"


def test_w3g3_preferred_selection_shows_the_cards_before_asking(set_pool):
    """"**Look at the top two cards of your library.** You may sacrifice…"

    The first sentence is what makes the offer a decision rather than a gamble,
    and the offer's own prompt is the only channel this engine has for showing
    one seat a hidden zone without also asking them something else. A card that
    dropped the sentence would ask for four mana and an enchantment blind.
    """
    game, _ = _w3g3e_selection_game(set_pool)
    owed = [c for c in game.pending_choices if c.kind == "optional_pay"]
    assert len(owed) == 1 and owed[0].player_index == 0
    assert owed[0].data["looked_at"] == ["Black Lotus", "Mox Jet"]
    assert "Black Lotus, Mox Jet" in owed[0].data["prompt"]
    assert bool(game.waiting_prompt()), game.log


def test_w3g3_preferred_selection_paying_takes_a_card_and_keeps_the_rest(set_pool):
    """Accepting charges both halves of the price — the sacrifice and the mana
    — and the chosen card reaches the hand. The other stays on top, so the
    ability is a filtered draw and not a two-card dig."""
    game, enchantment = _w3g3e_selection_game(set_pool)
    assert game.confirm_optional_pay(0, accept=True), game.log
    assert enchantment not in game.players[0].battlefield
    assert [c.name for c in game.players[0].graveyard] == ["Preferred Selection"]
    assert all(perm.tapped for perm in game.players[0].battlefield)

    assert [c.kind for c in game.pending_choices] == ["look_top_pick"]
    assert game.confirm_look_top_pick(0, 0), game.log

    assert [c.name for c in game.players[0].hand] == ["Black Lotus"]
    assert [c.name for c in game.players[0].library] == [
        "Mox Jet", "Island", "Forest", "Plains",
    ], game.log


def test_w3g3_preferred_selection_declining_buries_one_card(set_pool):
    """Declining keeps the enchantment and buries the card the player names.
    The one they did not name stays on top — which is the difference between
    this and a card that bottomed "the rest"."""
    game, enchantment = _w3g3e_selection_game(set_pool)
    assert game.confirm_optional_pay(0, accept=False), game.log
    assert enchantment in game.players[0].battlefield
    assert game.players[0].graveyard == []

    assert [c.kind for c in game.pending_choices] == ["look_top_pick"]
    assert game.confirm_look_top_pick(0, 1), game.log

    assert game.players[0].hand == []
    assert [c.name for c in game.players[0].library] == [
        "Black Lotus", "Island", "Forest", "Plains", "Mox Jet",
    ], game.log


def test_w3g3_preferred_selection_still_buries_when_the_price_is_unpayable(set_pool):
    """CR 601.2h asked of an offer: a board that cannot pay is never offered
    the choice, and the decline branch is what happens instead. The bottoming
    is the card's floor, not its penalty for saying no."""
    game, enchantment = _w3g3e_selection_game(set_pool, lands=0)
    assert [c.kind for c in game.pending_choices] == ["look_top_pick"]
    assert game.confirm_look_top_pick(0, 1), game.log

    assert enchantment in game.players[0].battlefield
    assert game.players[0].hand == []
    assert game.players[0].library[-1].name == "Mox Jet", game.log


# --- W3G4: Cycle of Life, four pieces in one printed line ---
#
# "Return this enchantment to its owner's hand: Target creature you cast this
#  turn has base power and toughness 0/1 until your next upkeep. At the
#  beginning of your next upkeep, put a +1/+1 counter on that creature."
#
# * a **cost** that is a zone change of the source (CR 118.3), so the ability
#   resolves with its own source already in a hand (CR 603.6);
# * a target narrowed by CR 701.5a's *cast* — not "you control", not "entered
#   this turn": a reanimated creature entered without being cast, and one you
#   cast and then gave away is still one you cast;
# * a base-P/T rewrite (CR 613 layer 7b) whose duration ends as an upkeep
#   *begins*, beside Halfdane's stamp which ends as one *ends*;
# * a CR 603.7 delayed ability about the creature the first half chose, which
#   reads that choice out of the scratchpad its creating effect froze
#   (CR 603.7d).

import pytest as _w3g4e_pytest  # noqa: E402

from engine import Game as _w3g4e_Game, PlayerState as _w3g4e_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w3g4e_load,  # noqa: E402
                                manifest_set_path as _w3g4e_path)
from engine.grammar import compile_line as _w3g4e_compile  # noqa: E402
from engine.models import Permanent as _w3g4e_Permanent  # noqa: E402


def _w3g4e_lea():
    return {card.name: card for card in _w3g4e_load(_w3g4e_path("LEA"))}


def _w3g4e_game(pool, *, mine=(), theirs=(), hand=("Shivan Dragon",)):
    lea = _w3g4e_lea()
    game = _w3g4e_Game(players=[
        _w3g4e_PlayerState(
            name="P1", hand=[lea[name] for name in hand],
            battlefield=[_w3g4e_Permanent(card=pool["Cycle of Life"]), *mine],
            library=[lea["Island"]] * 20,
        ),
        _w3g4e_PlayerState(name="P2", battlefield=list(theirs),
                           library=[lea["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game


def _w3g4e_cycle(game):
    return next(p for p in game.players[0].battlefield
                if p.card.name == "Cycle of Life")


def test_w3g4_cycle_of_life_offers_only_what_you_cast_this_turn(set_pool):
    """CR 701.5a. The board also holds a creature that was already there and
    one an opponent controls; neither was cast by this player this turn, and
    the printed restriction is what says so."""
    pool = set_pool("MIR")
    lea = _w3g4e_lea()
    already = _w3g4e_Permanent(card=lea["Grizzly Bears"])
    game = _w3g4e_game(pool, mine=[already],
                       theirs=[_w3g4e_Permanent(card=lea["Hill Giant"])])

    game.cast_from_hand(0, "Shivan Dragon")
    game.resolve_stack()
    game._settle()

    cycle = _w3g4e_cycle(game)
    spec = game.activation_target_spec(
        0, game.players[0].battlefield.index(cycle)
    )

    assert {t["name"] for t in spec["valid_targets"]} == {"Shivan Dragon"}, (
        spec["valid_targets"]
    )


def test_w3g4_cycle_of_life_costs_its_own_return_and_still_resolves(set_pool):
    """CR 118.3: the cost is paid on activation, so the enchantment is in its
    owner's hand before the ability resolves — and it resolves anyway
    (CR 603.6, the rule that lets a sacrificed source resolve from a
    graveyard)."""
    pool = set_pool("MIR")
    game = _w3g4e_game(pool)
    game.cast_from_hand(0, "Shivan Dragon")
    game.resolve_stack()
    game._settle()
    dragon = next(p for p in game.players[0].battlefield
                  if p.card.name == "Shivan Dragon")
    cycle = _w3g4e_cycle(game)

    result = game.activate_permanent_ability(
        0, "Cycle of Life", target_player_index=0,
        permanent_index=game.players[0].battlefield.index(cycle),
        target_permanent_index=game.players[0].battlefield.index(dragon),
    )
    assert result.supported, result.details
    game.resolve_stack()
    game._settle()

    assert "Cycle of Life" in [c.name for c in game.players[0].hand], game.log
    assert not any(p is cycle for p in game.players[0].battlefield)
    assert (dragon.effective_power, dragon.effective_toughness) == (0, 1), game.log


def test_w3g4_cycle_of_life_reverts_and_counters_at_the_next_upkeep(set_pool):
    """The rewrite ends as the controller's next upkeep *begins* (CR 613's
    duration, swept beside the keyword and type grants that answer to the same
    printed words), and the CR 603.7 delayed ability then puts the counter on
    the creature the first half chose — read out of the scratchpad the creating
    effect froze (CR 603.7d), because by now that step ran a turn ago."""
    pool = set_pool("MIR")
    game = _w3g4e_game(pool)
    game.cast_from_hand(0, "Shivan Dragon")
    game.resolve_stack()
    game._settle()
    dragon = next(p for p in game.players[0].battlefield
                  if p.card.name == "Shivan Dragon")
    cycle = _w3g4e_cycle(game)
    game.activate_permanent_ability(
        0, "Cycle of Life", target_player_index=0,
        permanent_index=game.players[0].battlefield.index(cycle),
        target_permanent_index=game.players[0].battlefield.index(dragon),
    )
    game.resolve_stack()
    game._settle()
    assert (dragon.effective_power, dragon.effective_toughness) == (0, 1)

    game.turn += 1
    game.start_turn(1)
    game.resolve_stack()
    game._settle()
    assert (dragon.effective_power, dragon.effective_toughness) == (0, 1), (
        "the opponent's upkeep is not 'your next upkeep'"
    )

    game.turn += 1
    game.start_turn(0)
    game.resolve_stack()
    game._settle()

    # 5/5 printed, plus the +1/+1 counter the delayed ability placed.
    assert (dragon.effective_power, dragon.effective_toughness) == (6, 6), game.log
    assert (dragon.power_bonus, dragon.toughness_bonus) == (1, 1), game.log


@_w3g4e_pytest.mark.parametrize(
    "line,fragment",
    [
        # A base-P/T rewrite whose duration nothing sweeps: admitted, it would
        # never end.
        (
            "{G}: Target creature has base power and toughness 0/1 until end "
            "of combat.",
            "end-of-turn duration",
        ),
        # A narrowing the instruction cannot carry: admitted, the restriction
        # would be enforced by nothing and the ability would rewrite any
        # creature at all.
        (
            "{G}: Target tapped creature has base power and toughness 0/1 "
            "until end of turn.",
            "narrowing",
        ),
    ],
)
def test_w3g4_a_base_pt_rewrite_refuses_what_it_cannot_honour(line, fragment):
    """The gate that was missing: the payload was built from three named fields
    and every other restriction on the noun phrase was silently dropped."""
    compiled = _w3g4e_compile(line, card_name="Probe")

    assert compiled.parsed, compiled.parse_error
    assert not compiled.instructions
    assert fragment in (compiled.lowering_error or ""), compiled.lowering_error


# --- W4G3: Forsaken Wastes and Grim Feast, the three unimplemented lines ---
#
# Both cards reported supported on one line each while a second (and, for the
# Wastes, a third) printed sentence had nothing behind it. What went in:
# `engine/life_prohibitions.py` (CR 119.7's ban, asked at the one life-gain
# seam *before* CR 614's contenders), the object-class narrowing on
# `self_becomes_target` plus the seat its announcement now freezes, and
# `permanent_dies`' graveyard-owner key read both ways round with the dead
# permanent's last-known toughness beside it.

import pytest as _w4g3e_pytest  # noqa: E402

from engine import Game as _w4g3e_Game, PlayerState as _w4g3e_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _w4g3e_load,  # noqa: E402
                                manifest_set_path as _w4g3e_path)
from engine.models import CardDefinition as _w4g3e_Card  # noqa: E402
from engine.models import Permanent as _w4g3e_Permanent  # noqa: E402
from engine.oracle import compile_card_oracle as _w4g3e_compile  # noqa: E402
from engine.tokens import make_token_card as _w4g3e_token  # noqa: E402


def _w4g3e_lea():
    return {card.name: card for card in _w4g3e_load(_w4g3e_path("LEA"))}


def _w4g3e_game(seat0=(), seat1=(), hands=(), libraries=8):
    """A two-seat board with *seat0* / *seat1* already in play.

    ``hands`` is ``(seat, card)`` pairs. Every seat gets a library so a draw
    replacement has something to take, and no seat is interactive so a prompt
    takes its default instead of waiting.
    """
    lea = _w4g3e_lea()
    game = _w4g3e_Game(players=[
        _w4g3e_PlayerState(name="P1", battlefield=list(seat0),
                           library=[lea["Forest"]] * libraries),
        _w4g3e_PlayerState(name="P2", battlefield=list(seat1),
                           library=[lea["Forest"]] * libraries),
    ])
    for seat, card in hands:
        game.players[seat].hand.append(card)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._recompute_continuous_effects()
    return game


def _w4g3e_bear(power=2, toughness=3, name="Test Bear"):
    return _w4g3e_Card(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


# --- Forsaken Wastes -------------------------------------------------------

def test_w4g3e_forsaken_wastes_compiles_all_three_of_its_lines(set_pool):
    """The card reported supported on its upkeep line alone. Both of the other
    two are now accounted for: the ban through the derived-static claim (a
    rule this shape produces no instruction, so the support gate has to read
    the table that carries it out), and the targeting trigger as a real
    triggered ability with the printed narrowing as payload."""
    program = _w4g3e_compile(set_pool("MIR")["Forsaken Wastes"])

    assert program.supported, program.reason
    assert any(
        instruction.kind == "derived_static_rule"
        and instruction.value == "life_prohibitions"
        for instruction in program.instructions
    ), "the ban is claimed by the table that enforces it"

    conditions = {
        trigger.condition.kind: trigger for trigger in program.triggered_abilities
    }
    assert set(conditions) == {"upkeep_each", "self_becomes_target"}
    targeted = conditions["self_becomes_target"]
    assert targeted.condition.payload == {"targeted_by": "a spell"}
    assert targeted.instruction.payload == {
        "amount": 5, "recipient": "event_subject_player",
    }


def test_w4g3e_the_wastes_locks_both_seats_including_its_own(set_pool):
    """"Players", so the enchantment stops its controller too. A lock read off
    the gaining player's own permanents would have been a one-sided card, which
    is the narrowing this pool keeps producing."""
    game = _w4g3e_game(seat0=[_w4g3e_Permanent(card=set_pool("MIR")["Forsaken Wastes"])])

    game._gain_life(game.players[0], 3, "a test")
    game._gain_life(game.players[1], 4, "a test")

    assert [p.life for p in game.players] == [20, 20]
    assert [p.life_gained_this_turn for p in game.players] == [0, 0]


def test_w4g3e_the_lock_reaches_a_spell_a_trigger_and_lifelink(set_pool):
    """Three different gain paths, because a lock wired to one path is the bug.

    They arrive at the seam from three directions - a resolving spell, a
    triggered ability, and combat damage - and the reason one check covers all
    three is that `Game._gain_life` is the only place a life total rises.
    """
    mir, lea = set_pool("MIR"), _w4g3e_lea()

    def wastes():
        return _w4g3e_Permanent(card=mir["Forsaken Wastes"])

    # A resolving spell.
    game = _w4g3e_game(seat0=[wastes()], hands=[(1, lea["Stream of Life"])])
    game.cast_from_hand(1, "Stream of Life", target_player_index=1, x_value=4)
    game.resolve_stack()
    assert game.players[1].life == 20

    # A triggered ability (Grim Feast's own gain, which is the pair below).
    game = _w4g3e_game(
        seat0=[_w4g3e_Permanent(card=mir["Grim Feast"]), wastes()],
        seat1=[_w4g3e_Permanent(card=_w4g3e_bear())],
    )
    game._permanent_to_graveyard(game.players[1], game.players[1].battlefield[0])
    game.resolve_stack()
    assert game.players[0].life == 20

    # Combat damage with lifelink (CR 702.15b), whose gain is not a spell at
    # all and is the path a lock wired to one resolution would have missed.
    linker = _w4g3e_Card(
        name="Test Linker", mana_cost="", cmc=0.0, type_line="Creature - Bear",
        oracle_text="Lifelink", colors=(), color_identity=(),
        keywords=("Lifelink",), produced_mana=(),
        raw={"name": "Test Linker", "type_line": "Creature - Bear",
             "power": "3", "toughness": "3"},
    )
    game = _w4g3e_game(seat0=[_w4g3e_Permanent(card=linker), wastes()])
    game._deal_damage_to_player(
        game.players[1], 3, source=game.players[0].battlefield[0],
    )
    assert [p.life for p in game.players] == [20, 17]


def test_w4g3e_the_lock_lifts_with_the_enchantment(set_pool):
    """A continuous effect and not a stamp: nothing is written onto the player,
    so the gain works again the moment the enchantment leaves."""
    wastes = _w4g3e_Permanent(card=set_pool("MIR")["Forsaken Wastes"])
    game = _w4g3e_game(seat0=[wastes])

    game._gain_life(game.players[0], 3, "a test")
    assert game.players[0].life == 20

    game.remove_from_battlefield(wastes)
    game._gain_life(game.players[0], 3, "a test")
    assert game.players[0].life == 23


@_w4g3e_pytest.mark.parametrize("caster,expected", [(0, [15, 20]), (1, [20, 15])])
def test_w4g3e_targeting_the_wastes_costs_the_spells_controller_five(
    set_pool, caster, expected,
):
    """"That spell's controller", which is the seat the *event* froze rather
    than the enchantment's own controller - so pointing your own Disenchant at
    your own Wastes costs you the five."""
    lea = _w4g3e_lea()
    game = _w4g3e_game(
        seat0=[_w4g3e_Permanent(card=set_pool("MIR")["Forsaken Wastes"])],
        hands=[(caster, lea["Disenchant"])],
    )

    game.cast_from_hand(caster, "Disenchant", target_player_index=0,
                        target_permanent_index=0)
    game.resolve_stack()

    assert [p.life for p in game.players] == expected


def test_w4g3e_an_ability_pointed_at_the_wastes_costs_nothing(set_pool):
    """"...the target of **a spell**", so an activated ability is not it. The
    narrowing is the whole difference between this card and Warden of the
    Woods, and a narrowing nothing enforces is an ability that fires more often
    than the card allows."""
    pointer = _w4g3e_Card(
        name="Test Pointer", mana_cost="", cmc=0.0, type_line="Artifact",
        oracle_text="{T}: Destroy target enchantment.", colors=(),
        color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Test Pointer", "type_line": "Artifact"},
    )
    pointer_perm = _w4g3e_Permanent(card=pointer)
    pointer_perm.summoning_sick = False
    game = _w4g3e_game(
        seat0=[_w4g3e_Permanent(card=set_pool("MIR")["Forsaken Wastes"])],
        seat1=[pointer_perm],
    )

    game.activate_permanent_ability(1, "Test Pointer", target_player_index=0,
                                    target_permanent_index=0)
    game.resolve_stack()

    assert [p.life for p in game.players] == [20, 20]
    assert not game.players[0].battlefield, "the ability still destroyed it"


def test_w4g3e_the_wastes_still_bleeds_each_player_on_their_upkeep(set_pool):
    """The line that already worked, kept green beside the two that did not -
    three sentences on one card is three chances for a round to break the one
    it was not looking at."""
    game = _w4g3e_game(seat0=[_w4g3e_Permanent(card=set_pool("MIR")["Forsaken Wastes"])])

    game.start_turn(0)
    game.resolve_stack()
    assert [p.life for p in game.players] == [19, 20]

    game.start_turn(1)
    game.resolve_stack()
    assert [p.life for p in game.players] == [19, 19]

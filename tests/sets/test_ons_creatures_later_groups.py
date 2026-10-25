"""Onslaught creatures (legendary ones too) — wave 1's groups W1G3 to W1G13.

The set prints 174 creatures; W1G1 (morph) and W1G2 (face-down) write in
`test_ons_creatures.py`, every later group here, so neither file reaches the
2,600-line cap mid-wave.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ONS")` / `set_cards("ONS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# --- W1G3: cycling triggers on creatures, and the cycling creatures --------
#
# Krosan Tusker's "When you cycle this card" is the cycled card's own trigger
# (CR 702.29c), asked of the card in the graveyard; Fleeting Aven's "Whenever
# a player cycles a card" is a permanent watching the table. Both announced
# where the cycling ability's discard is paid
# (`CardActivationMixin._announce_cycle`).
import pytest

from engine import Game
from engine.activation_zones import HAND
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import _mk_creature_card, resolve_stack


def _w1g3_table(set_pool, *hand, opponent_hand=(), library=()):
    """Alice (seat 0, active) holding *hand* over *library* (top first) and
    five Plains; Bob holding *opponent_hand*."""
    ons = set_pool("ONS")
    filler = ons["Plains"]
    alice = PlayerState(
        name="Alice", hand=[ons[name] for name in hand],
        library=[ons[name] for name in library] + [filler] * 5,
    )
    bob = PlayerState(
        name="Bob", hand=[ons[name] for name in opponent_hand],
        library=[filler] * 5,
    )
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game, alice, bob


def _w1g3_put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g3_krosan_tusker_cycled_searches_before_it_draws(set_pool):
    """"When you cycle this card, you may search your library for a basic land
    card, reveal that card, put it into your hand, then shuffle. (Do this
    before you draw.)" The library's top card is Wellwisher, a creature; the
    search takes the Forest from under it, and only then is a card drawn."""
    game, alice, _bob = _w1g3_table(
        set_pool, "Krosan Tusker", library=("Wellwisher", "Forest"),
    )
    game.enforce_mana_costs = True
    alice.mana_pool.update({"C": 2, "G": 1})

    assert game.activate_from_hand(0, "Krosan Tusker").supported
    assert not any(alice.mana_pool.values())
    assert game.stack[-1].ability_text.startswith("When you cycle this card")
    assert game.resolve_top_of_stack()
    offer = game.pending_choice_of("optional_pay", 0)
    assert game._resolve_optional_pay(offer, True, None)
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.hand] == ["Forest"], "searched, not yet drawn"
    assert len(alice.library) == 6
    assert any("revealed Forest" in line for line in game.log)
    resolve_stack(game)
    assert len(alice.hand) == 2 and len(alice.library) == 5
    assert [c.name for c in alice.graveyard] == ["Krosan Tusker"]


def test_w1g3_krosan_tusker_is_supported_and_cycles_only_from_hand(set_pool):
    """The creature compiles now that its cycle trigger does; on the
    battlefield it is a 6/5 with no cycling to reach (CR 702.29b / 113.6j),
    and another card's cycle is not its own."""
    tusker = set_pool("ONS")["Krosan Tusker"]
    program = compile_card_oracle(tusker)
    assert program.supported, program.reason
    assert usable_activated_abilities(program) == []

    game, alice, _bob = _w1g3_table(set_pool, "Lay Waste")
    beast = _w1g3_put(game, 0, tusker)
    assert (beast.effective_power, beast.effective_toughness) == (6, 5)
    assert not game.activate_permanent_ability(0, "Krosan Tusker").supported
    assert game.activate_from_hand(0, "Lay Waste").supported
    assert [item.card.name for item in game.stack] == ["Lay Waste"]
    resolve_stack(game)


@pytest.mark.parametrize("cycler", [0, 1])
def test_w1g3_fleeting_aven_returns_to_hand_when_anyone_cycles(set_pool, cycler):
    """"Whenever a player cycles a card, return this creature to its owner's
    hand." — its controller's cycle or its opponent's, before the draw."""
    game, alice, bob = _w1g3_table(set_pool, "Lay Waste", opponent_hand=["Swat"])
    aven = _w1g3_put(game, 0, set_pool("ONS")["Fleeting Aven"])
    name = "Lay Waste" if cycler == 0 else "Swat"
    cycling_player = game.players[cycler]

    assert game.activate_from_hand(cycler, name).supported
    assert game.stack[-1].card.name == "Fleeting Aven"
    assert game.resolve_top_of_stack()
    assert not game.is_on_battlefield(aven)
    assert "Fleeting Aven" in [c.name for c in alice.hand]
    assert "Plains" not in [c.name for c in cycling_player.hand], "not drawn yet"
    resolve_stack(game)
    assert "Plains" in [c.name for c in cycling_player.hand]


#: The Onslaught creatures that print cycling and nothing triggering on it,
#: with the mana their cycling cost takes from the pool.
_W1G3_PLAIN_CYCLING_CREATURES = {
    "Barkhide Mauler": {"C": 2},
    "Disciple of Grace": {"C": 2},
    "Disciple of Malice": {"C": 2},
    "Slipstream Eel": {"C": 1, "U": 1},
    "Undead Gladiator": {"C": 1, "B": 1},
}


@pytest.mark.parametrize("name", sorted(_W1G3_PLAIN_CYCLING_CREATURES))
def test_w1g3_a_cycling_creature_cycles_from_hand_and_never_from_play(set_pool, name):
    """From a hand: the printed cycling cost, the card to the graveyard, one
    card drawn. On the battlefield (CR 702.29b): the ability still exists, and
    nothing can activate it (CR 113.6j)."""
    card = set_pool("ONS")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    cycling = [
        a for a in usable_activated_abilities(program, zone=HAND)
        if a.source_line.endswith("Discard this card: Draw a card.")
    ]
    assert len(cycling) == 1
    assert cycling[0] not in usable_activated_abilities(program)

    game, alice, _bob = _w1g3_table(set_pool, name)
    game.enforce_mana_costs = True
    alice.mana_pool.update(_W1G3_PLAIN_CYCLING_CREATURES[name])
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert not any(alice.mana_pool.values()), alice.mana_pool
    assert [c.name for c in alice.graveyard] == [name]
    assert [c.name for c in alice.hand] == ["Plains"]

    game, alice, _bob = _w1g3_table(set_pool)
    _w1g3_put(game, 0, card)
    library = len(alice.library)
    game.activate_permanent_ability(0, name)
    resolve_stack(game)
    assert len(alice.library) == library and alice.hand == []
    assert alice.graveyard == []

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

from engine import Game as _W1G4Game
from engine import PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from engine.targeting import derive_activation_spec as _w1g4_activation_spec
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import _nosick as _w1g4_nosick
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_card(name, subtype):
    return _w1g4_mk_card(name, "{2}", f"Creature - {subtype}", "")


def _w1g4_creature(name, subtype, *, tapped=False):
    perm = _w1g4_nosick(_W1G4Permanent(card=_w1g4_card(name, subtype)))
    perm.tapped = tapped
    return perm


def _w1g4_game(mine=(), theirs=(), *, hand=(), library=(), interactive=()):
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P1", battlefield=list(mine), hand=list(hand), library=list(library),
        ),
        _W1G4PlayerState(name="P2", battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w1g4_named(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))


# --- Riptide Chronologist ---------------------------------------------------------


def test_w1g4_riptide_chronologist_untaps_only_the_named_type(set_pool):
    """"{U}, Sacrifice this creature: Untap all creatures of the creature type of
    your choice." Chosen as the ability resolves (CR 608.2d), and every
    creature of it untaps — the opponent's too — while the rest stay tapped."""
    chronologist = _w1g4_nosick(_W1G4Permanent(card=set_pool("ONS")["Riptide Chronologist"]))
    my_elf = _w1g4_creature("My Elf", "Elf", tapped=True)
    my_goblin = _w1g4_creature("My Goblin", "Goblin", tapped=True)
    their_elf = _w1g4_creature("Their Elf", "Elf", tapped=True)
    game = _w1g4_game([chronologist, my_elf, my_goblin], [their_elf], interactive=[0])

    result = game.activate_permanent_ability(0, "Riptide Chronologist")
    assert result.supported, result.details
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert my_elf.tapped, "nothing untaps before the answer"
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g4_resolve_stack(game)

    assert (my_elf.tapped, their_elf.tapped, my_goblin.tapped) == (False, False, True)
    assert "Riptide Chronologist" in [c.name for c in game.players[0].graveyard]


def test_w1g4_riptide_chronologist_default_untaps_its_own_commonest_type(set_pool):
    """Nobody asked: the controller's own most common type, net of the
    opponent's — an untap is a gift. Goblins 2 − 0 over Elves 1 − 3."""
    chronologist = _w1g4_nosick(_W1G4Permanent(card=set_pool("ONS")["Riptide Chronologist"]))
    goblins = [_w1g4_creature(f"My Goblin {n}", "Goblin", tapped=True) for n in range(2)]
    my_elf = _w1g4_creature("My Elf", "Elf", tapped=True)
    their_elves = [_w1g4_creature(f"Their Elf {n}", "Elf", tapped=True) for n in range(3)]
    game = _w1g4_game([chronologist, *goblins, my_elf], their_elves)
    game.activate_permanent_ability(0, "Riptide Chronologist")
    _w1g4_resolve_stack(game)

    assert [perm.tapped for perm in goblins] == [False, False]
    assert my_elf.tapped and all(perm.tapped for perm in their_elves)


# --- Walking Desecration ----------------------------------------------------------


def test_w1g4_walking_desecration_compels_only_the_named_type(set_pool):
    """"{B}, {T}: Creatures of the creature type of your choice attack this turn
    if able." The refusal this lowering held until now was right: a
    requirement must not reach a creature the phrase does not name. With the
    word read, the Goblins are compelled (CR 508.1d) and the Zombie beside them
    is not — asserted on the mark and on the declaration the defender's turn
    then has to make."""
    desecration = _w1g4_nosick(_W1G4Permanent(card=set_pool("ONS")["Walking Desecration"]))
    goblin = _w1g4_creature("Their Goblin", "Goblin")
    zombie = _w1g4_creature("Their Zombie", "Zombie")
    game = _w1g4_game([desecration], [goblin, zombie], interactive=[0])
    assert game.activate_permanent_ability(0, "Walking Desecration").supported
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g4_resolve_stack(game)

    assert goblin.metadata.get("must_attack_until_eot") is True
    assert not zombie.metadata.get("must_attack_until_eot")

    game.active_player_index = 1
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(1, [], defending_player_index=0)
    assert not ok, "the Goblin must attack"
    goblin_slot = next(
        slot for slot, perm in enumerate(game.players[1].battlefield) if perm is goblin
    )
    ok, why = game.declare_attackers(1, [goblin_slot], defending_player_index=0)
    assert ok, why


def test_w1g4_walking_desecration_with_no_type_compels_nothing(set_pool):
    """No creature on the board means no type worth naming, and the
    requirement then marks nothing — never every creature."""
    desecration = _w1g4_nosick(_W1G4Permanent(card=set_pool("ONS")["Walking Desecration"]))
    game = _w1g4_game([desecration], [])
    # Walking Desecration is a Zombie itself; it taps for the cost, but the
    # default still reads the board, which holds its own type.
    game.activate_permanent_ability(0, "Walking Desecration")
    _w1g4_resolve_stack(game)
    assert all(
        not perm.metadata.get("must_attack_until_eot") or perm is desecration
        for perm in game.all_permanents()
    )


# --- Callous Oppressor ------------------------------------------------------------


def test_w1g4_callous_oppressor_asks_the_opponent_as_it_enters(set_pool):
    """"As this creature enters, an opponent chooses a creature type."
    CR 614.1c / 614.12a: the choice is the opponent's and is made as the
    Oppressor enters — the prompt is armed on P2's seat, P1 cannot answer it,
    and the record is what P2 said."""
    game = _w1g4_game(
        [], [_w1g4_creature("Their Zombie", "Zombie")],
        hand=[set_pool("ONS")["Callous Oppressor"]], interactive=[0, 1],
    )
    assert game.cast_from_hand(0, "Callous Oppressor").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", 1)]
    assert not game.confirm_enter_choice(0, creature_type="goblin")
    assert game.confirm_enter_choice(1, creature_type="goblin")
    oppressor = next(p for p in game.controlled_by(0) if p.card.name == "Callous Oppressor")
    assert oppressor.metadata["chosen_creature_type"] == "goblin"


def test_w1g4_callous_oppressor_opponent_default_protects_their_own_type(set_pool):
    """Nobody asked: the opponent names the type their own creatures have the
    most of — the type that keeps the most of them out of the Oppressor's
    reach. Counted over their own board alone: the Oppressor's controller
    holding three Zombies of its own changes nothing about which of the
    opponent's creatures it can take, so a net count (which would name the
    lone Goblin) is the wrong question."""
    game = _w1g4_game(
        [_w1g4_creature(f"My Zombie {n}", "Zombie") for n in range(3)],
        [_w1g4_creature("Their Zombie A", "Zombie"), _w1g4_creature("Their Zombie B", "Zombie"),
         _w1g4_creature("Their Goblin", "Goblin")],
        hand=[set_pool("ONS")["Callous Oppressor"]],
    )
    game.cast_from_hand(0, "Callous Oppressor")
    _w1g4_resolve_stack(game)
    oppressor = next(p for p in game.controlled_by(0) if p.card.name == "Callous Oppressor")
    assert oppressor.metadata["chosen_creature_type"] == "zombie"


def test_w1g4_callous_oppressor_steals_only_other_types_while_tapped(set_pool):
    """"{T}: Gain control of target creature that isn't of the chosen type for
    as long as this creature remains tapped." The picker offers no creature of
    the chosen type and the activation naming one is refused with nothing paid;
    another type is taken, and comes back the moment the Oppressor untaps
    (CR 611.2b)."""
    zombie = _w1g4_creature("Their Zombie", "Zombie")
    goblin = _w1g4_creature("Their Goblin", "Goblin")
    game = _w1g4_game(
        [], [zombie, goblin], hand=[set_pool("ONS")["Callous Oppressor"]], interactive=[1],
    )
    game.cast_from_hand(0, "Callous Oppressor")
    assert game.confirm_enter_choice(1, creature_type="zombie")
    oppressor = _w1g4_nosick(
        next(p for p in game.controlled_by(0) if p.card.name == "Callous Oppressor")
    )

    ability = _w1g4_compile(set_pool("ONS")["Callous Oppressor"]).activated_abilities[0]
    offered = {
        target["name"]
        for target in game._enumerate_targets(
            0, oppressor.card, _w1g4_activation_spec(ability), for_cast=False,
            ability_instruction=ability.instruction,
            source_permanent=oppressor, ability_source=oppressor,
        )
    }
    assert "Their Goblin" in offered and "Their Zombie" not in offered

    refused = game.activate_permanent_ability(
        0, "Callous Oppressor", target_permanent_ids=[zombie.permanent_id],
    )
    assert not refused.supported and not oppressor.tapped

    taken = game.activate_permanent_ability(
        0, "Callous Oppressor", target_permanent_ids=[goblin.permanent_id],
    )
    assert taken.supported, taken.details
    _w1g4_resolve_stack(game)
    assert _w1g4_named(game, 0) == ["Callous Oppressor", "Their Goblin"]

    game.become_untapped(oppressor)
    game.check_state_based_actions()
    assert _w1g4_named(game, 1) == ["Their Goblin", "Their Zombie"]


# --- Bloodline Shaman --------------------------------------------------------------


def _w1g4_shaman_game(set_pool, library, interactive=(0,)):
    shaman = _w1g4_nosick(_W1G4Permanent(card=set_pool("ONS")["Bloodline Shaman"]))
    return _w1g4_game([shaman], [], library=library, interactive=interactive)


def test_w1g4_bloodline_shaman_keeps_a_creature_of_the_chosen_type(set_pool):
    """"{T}: Choose a creature type. Reveal the top card of your library. If that
    card is a creature card of the chosen type, put it into your hand." The
    type is the one this activation chose, not anything the Shaman recorded."""
    top = _w1g4_card("Top Elf", "Elf")
    game = _w1g4_shaman_game(set_pool, [top, _w1g4_card("Next", "Bear")])
    assert game.activate_permanent_ability(0, "Bloodline Shaman").supported
    assert [c.kind for c in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g4_resolve_stack(game)

    player = game.players[0]
    assert [card.name for card in player.hand] == ["Top Elf"]
    assert [card.name for card in player.library] == ["Next"]
    assert player.graveyard == []


def test_w1g4_bloodline_shaman_bins_another_type_or_a_noncreature(set_pool):
    """"Otherwise, put it into your graveyard." — a creature of another type,
    and a card that is not a creature at all, both go."""
    for top, word in ((_w1g4_card("Top Elf", "Elf"), "goblin"),
                      (_w1g4_mk_card("Top Bolt", "{R}", "Instant", ""), "elf")):
        game = _w1g4_shaman_game(set_pool, [top])
        game.activate_permanent_ability(0, "Bloodline Shaman")
        assert game.confirm_creature_type_choice(0, word)
        _w1g4_resolve_stack(game)
        assert [card.name for card in game.players[0].graveyard] == [top.name]
        assert game.players[0].hand == []


def test_w1g4_bloodline_shaman_default_names_its_librarys_commonest_type(set_pool):
    """Nobody asked: the type most common among the controller's own library's
    creature cards (a player knows their decklist, not its order) — here Elf,
    three to one, so the Elf on top is kept."""
    library = [_w1g4_card("Top Elf", "Elf"), _w1g4_card("Elf 2", "Elf"),
               _w1g4_card("Elf 3", "Elf"), _w1g4_card("Goblin", "Goblin")]
    game = _w1g4_shaman_game(set_pool, library, interactive=())
    game.activate_permanent_ability(0, "Bloodline Shaman")
    _w1g4_resolve_stack(game)
    assert [card.name for card in game.players[0].hand] == ["Top Elf"]

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# --- W1G5: creature types changed (CR 205.1a, CR 613.1d) -------------------
#
# "{1}: This creature becomes the creature type of your choice until end of
# turn." The type is chosen as the ability resolves (CR 608.2d, W1G4's
# ``creature_type_choice``) and *set*: it replaces the creature's creature
# types (CR 205.1a) in layer 4, with its own timestamp, until the cleanup step
# drops the record. Everything that asks a type through the layers sees it —
# a lord, a chosen-type anthem, a count, a "tap N untapped <type>" cost.
import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.face_down import face_down_card as _w1g5_face_down_card
from engine.face_down import turn_face_up as _w1g5_turn_face_up
from engine.layer_bridge import computed_types as _w1g5_computed_types
from engine.models import Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from engine.targeting import derive_activation_spec as _w1g5_activation_spec
from tests.helpers import resolve_stack as _w1g5_resolve_stack

_W1G5_MISTFORMS = (
    "Mistform Dreamer", "Mistform Skyreaver", "Mistform Stalker",
    "Mistform Wall", "Mistform Shrieker",
)


def _w1g5_game(*, interactive=(0,)):
    """Two seats with costs off, seat 0 active in its main phase. Seat 0 is
    interactive by default, so the type prompt is *queued* and answered by the
    test rather than by its default."""
    game = _W1G5Game(players=[_W1G5PlayerState(name="A"), _W1G5PlayerState(name="B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    return game


def _w1g5_put(game, seat, card):
    """*card* onto *seat*'s battlefield, able to act this turn."""
    permanent = _W1G5Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._recompute_continuous_effects()
    return permanent


def _w1g5_types(permanent):
    """The creature's subtypes through the CR 613 layers."""
    return set(_w1g5_computed_types(permanent)[1])


def _w1g5_become(game, name, word, *, seat=0):
    """*seat* activates *name*'s type change and answers *word*."""
    result = game.activate_permanent_ability(seat, name)
    assert result.supported, result.details
    assert [choice.kind for choice in game.pending_choices] == ["creature_type_choice"]
    assert game.confirm_creature_type_choice(seat, word)
    _w1g5_resolve_stack(game)


@_w1g5_pytest.mark.parametrize("name", _W1G5_MISTFORMS)
def test_w1g5_each_mistform_becomes_the_chosen_type_and_only_that_type(
    set_pool, catalog_by_name, name,
):
    """The whole sentence on each of the five: nothing changes before the
    answer, then the creature is a Goblin and **no longer** an Illusion (or a
    Wall) — the set replaces (CR 205.1a) — so an opponent's Goblin King pumps it
    and gives it mountainwalk; at cleanup the record ends and it is what it
    printed again. The activation names no target, so no picker is derived."""
    card = set_pool("ONS")[name]
    game = _w1g5_game()
    mistform = _w1g5_put(game, 0, card)
    _w1g5_put(game, 1, catalog_by_name["Goblin King"])
    printed = _w1g5_types(mistform)
    assert "illusion" in printed and "goblin" not in printed
    body = (mistform.effective_power, mistform.effective_toughness)

    ability = next(
        ab for ab in _w1g5_compile(card).activated_abilities
        if "creature type of your choice" in ab.source_line
    )
    assert _w1g5_activation_spec(ability) is None

    result = game.activate_permanent_ability(0, name)
    assert result.supported, result.details
    assert _w1g5_types(mistform) == printed, "nothing changes before the answer"
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g5_resolve_stack(game)

    assert _w1g5_types(mistform) == {"goblin"}
    assert (mistform.effective_power, mistform.effective_toughness) == (
        body[0] + 1, body[1] + 1,
    )
    assert game._has_keyword(mistform, "mountainwalk")
    assert f"{name} became a Goblin until end of turn ({name})" in game.log

    game.resolve_cleanup_step(0)
    assert _w1g5_types(mistform) == printed
    assert (mistform.effective_power, mistform.effective_toughness) == body
    assert not game._has_keyword(mistform, "mountainwalk")


def test_w1g5_two_mistform_activations_apply_in_timestamp_order(
    set_pool, catalog_by_name,
):
    """Two sets on one creature are two layer-4 effects, and CR 613.7 applies
    the later one last: Goblin then Elf is an Elf, and the Goblin King that was
    pumping it stops. Two activations stacked at once resolve top first, so the
    one activated *first* resolves last and is the one that wins."""
    game = _w1g5_game()
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    _w1g5_put(game, 1, catalog_by_name["Goblin King"])
    _w1g5_become(game, "Mistform Dreamer", "goblin")
    assert (dreamer.effective_power, dreamer.effective_toughness) == (3, 2)
    _w1g5_become(game, "Mistform Dreamer", "elf")
    assert _w1g5_types(dreamer) == {"elf"}
    assert (dreamer.effective_power, dreamer.effective_toughness) == (2, 1)

    stacked = _w1g5_game()
    dreamer = _w1g5_put(stacked, 0, set_pool("ONS")["Mistform Dreamer"])
    assert stacked.queue_permanent_ability(0, "Mistform Dreamer").supported
    assert stacked.queue_permanent_ability(0, "Mistform Dreamer").supported
    assert len(stacked.stack) == 2
    stacked.resolve_top_of_stack(pause_for_choices=True)
    assert stacked.confirm_creature_type_choice(0, "elf")
    _w1g5_resolve_stack(stacked)
    assert stacked.confirm_creature_type_choice(0, "goblin")
    _w1g5_resolve_stack(stacked)
    assert _w1g5_types(dreamer) == {"goblin"}


def test_w1g5_a_mistform_that_left_in_response_changes_nothing(set_pool):
    """The ability names its source. Gone before it resolves — a new object if
    it comes back (CR 400.7) — so nothing becomes anything, and nothing else on
    the battlefield is changed in its place."""
    game = _w1g5_game(interactive=())
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    other = _w1g5_put(game, 0, set_pool("ONS")["Mistform Stalker"])
    assert game.queue_permanent_ability(0, "Mistform Dreamer").supported
    game.remove_from_battlefield(dreamer)
    _w1g5_resolve_stack(game)
    assert _w1g5_types(other) == {"illusion"}
    assert "Mistform Dreamer: has left the battlefield, so nothing changes" in game.log


def test_w1g5_shared_triumph_naming_illusion_stops_pumping_a_mistform_that_became_a_goblin(
    set_pool,
):
    """A chosen-type anthem asks the type through the layers too: Shared
    Triumph naming Illusion pumps the Dreamer until it becomes a Goblin, and
    again once cleanup ends the change."""
    game = _w1g5_game()
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    triumph = _w1g5_put(game, 0, set_pool("ONS")["Shared Triumph"])
    triumph.metadata["chosen_creature_type"] = "illusion"
    game._recompute_continuous_effects()
    assert (dreamer.effective_power, dreamer.effective_toughness) == (3, 2)

    _w1g5_become(game, "Mistform Dreamer", "goblin")
    assert (dreamer.effective_power, dreamer.effective_toughness) == (2, 1)

    game.resolve_cleanup_step(0)
    assert (dreamer.effective_power, dreamer.effective_toughness) == (3, 2)


def test_w1g5_mistform_wall_has_defender_only_while_it_is_a_wall(set_pool):
    """"This creature has defender as long as it's a Wall." A static asked of
    its own type through layer 4 every recompute: printed, it is a Wall and
    cannot attack (CR 702.3b); made a Goblin it has no defender and attacks;
    made a Wall again it has it back, and so it does when cleanup ends the
    change."""
    game = _w1g5_game()
    wall = _w1g5_put(game, 0, set_pool("ONS")["Mistform Wall"])
    assert game._has_keyword(wall, "defender")
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(0, [0], defending_player_index=1)
    assert not ok

    game._set_phase_and_step("precombat_main", "precombat_main")
    _w1g5_become(game, "Mistform Wall", "goblin")
    assert _w1g5_types(wall) == {"goblin"}
    assert not game._has_keyword(wall, "defender")
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, why

    other = _w1g5_game()
    wall = _w1g5_put(other, 0, set_pool("ONS")["Mistform Wall"])
    _w1g5_become(other, "Mistform Wall", "goblin")
    _w1g5_become(other, "Mistform Wall", "wall")
    assert _w1g5_types(wall) == {"wall"}
    assert other._has_keyword(wall, "defender")
    _w1g5_become(other, "Mistform Wall", "elf")
    other.resolve_cleanup_step(0)
    assert other._has_keyword(wall, "defender")


def test_w1g5_mistform_wall_defender_line_compiles_to_a_self_type_condition(set_pool):
    """The static is read by ``static_bonuses``' table (the grammar declines a
    same-subject condition to it), as a ``self_matches`` condition over the
    noun phrase — asked by ``subject_matches``, never by the printed type
    line."""
    program = _w1g5_compile(set_pool("ONS")["Mistform Wall"])
    (static,) = [ins for ins in program.instructions if ins.kind == "conditional_static"]
    assert static.payload["keywords"] == ["defender"]
    assert static.payload["condition"] == {
        "kind": "self_matches",
        "filter": {"type_filter": "creature", "subtype_filter": "wall"},
    }


def test_w1g5_mistform_shrieker_changes_type_once_turned_face_up(set_pool):
    """Face down, W1G1's blank 2/2 has no ability to activate (their test);
    turned face up it is the Shrieker, and its line works."""
    shrieker_card = set_pool("ONS")["Mistform Shrieker"]
    game = _w1g5_game()
    shrieker = _W1G5Permanent(card=_w1g5_face_down_card(shrieker_card))
    shrieker.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(shrieker)
    assert game.usable_abilities_of(shrieker, card=shrieker.effective_card) == []
    assert _w1g5_types(shrieker) == set()

    assert _w1g5_turn_face_up(game, shrieker)
    _w1g5_become(game, "Mistform Shrieker", "dragon")
    assert _w1g5_types(shrieker) == {"dragon"}
    assert game._has_keyword(shrieker, "flying")


# --- the tribal counts and costs see the layer ------------------------------


def test_w1g5_reckless_one_counts_a_mistform_that_became_a_goblin(set_pool):
    """"…power and toughness are each equal to the number of Goblins on the
    battlefield." A characteristic-defining count (W1G7's drive list) over the
    layers: the Dreamer made a Goblin is one more Goblin, and stops being one
    at cleanup."""
    game = _w1g5_game()
    reckless = _w1g5_put(game, 0, set_pool("ONS")["Reckless One"])
    _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    game._refresh_dynamic_creatures()
    assert reckless.effective_power == 1
    _w1g5_become(game, "Mistform Dreamer", "goblin")
    assert (reckless.effective_power, reckless.effective_toughness) == (2, 2)
    game.resolve_cleanup_step(0)
    game._refresh_dynamic_creatures()
    assert reckless.effective_power == 1


def test_w1g5_wellwisher_counts_a_mistform_that_became_an_elf(set_pool):
    """"{T}: You gain 1 life for each Elf on the battlefield." A count read at
    resolution: Wellwisher and a Dreamer made an Elf are two Elves."""
    game = _w1g5_game()
    _w1g5_put(game, 0, set_pool("ONS")["Wellwisher"])
    _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    _w1g5_become(game, "Mistform Dreamer", "elf")
    assert "Mistform Dreamer became an Elf until end of turn (Mistform Dreamer)" in game.log
    life = game.players[0].life
    assert game.activate_permanent_ability(0, "Wellwisher").supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == life + 2


def test_w1g5_a_mistform_made_a_wizard_pays_aphetto_grifters_cost(set_pool):
    """"Tap two untapped Wizards you control: Tap target permanent." The cost
    asks the type through the layers: Grifter alone cannot pay it, and with a
    Dreamer made a Wizard it can — the Dreamer is tapped for it."""
    game = _w1g5_game(interactive=())
    grifter = _w1g5_put(game, 0, set_pool("ONS")["Aphetto Grifter"])
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    target = _w1g5_put(game, 1, set_pool("ONS")["Mistform Stalker"])
    assert not game.activate_permanent_ability(
        0, "Aphetto Grifter", target_permanent_ids=[target.permanent_id],
    ).supported

    game.interactive_seats = {0}
    _w1g5_become(game, "Mistform Dreamer", "wizard")
    result = game.activate_permanent_ability(
        0, "Aphetto Grifter", target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, result.details
    _w1g5_resolve_stack(game)
    assert grifter.tapped and dreamer.tapped and target.tapped


# --- the default a seat nobody asks takes -----------------------------------


def test_w1g5_a_mistform_nobody_asks_joins_its_controllers_tribe(
    set_pool, catalog_by_name,
):
    """The default for a type set on the source: the controller's own
    commonest type among its *other* creatures — the tribe its lords pump.
    With Lord of Atlantis beside it the Dreamer becomes a Merfolk (+1/+1 and
    islandwalk); with no other creature of its controller's it names nothing
    and changes nothing, even beside an opponent's Goblin King."""
    game = _w1g5_game(interactive=())
    dreamer = _w1g5_put(game, 0, set_pool("ONS")["Mistform Dreamer"])
    _w1g5_put(game, 0, catalog_by_name["Lord of Atlantis"])
    _w1g5_put(game, 1, catalog_by_name["Grizzly Bears"])
    assert game.activate_permanent_ability(0, "Mistform Dreamer").supported
    _w1g5_resolve_stack(game)
    assert _w1g5_types(dreamer) == {"merfolk"}
    assert (dreamer.effective_power, dreamer.effective_toughness) == (3, 2)

    lonely = _w1g5_game(interactive=())
    dreamer = _w1g5_put(lonely, 0, set_pool("ONS")["Mistform Dreamer"])
    _w1g5_put(lonely, 1, catalog_by_name["Goblin King"])
    assert lonely.activate_permanent_ability(0, "Mistform Dreamer").supported
    _w1g5_resolve_stack(lonely)
    assert _w1g5_types(dreamer) == {"illusion"}
    assert "Mistform Dreamer: no creature type was chosen, so nothing changes" in lonely.log

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================


# ==== W1G11 ==========================================================
# W1G11's tests go between this line and the "end W1G11" line.

# ==== end W1G11 ======================================================


# ==== W1G12 ==========================================================
# W1G12's tests go between this line and the "end W1G12" line.

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================

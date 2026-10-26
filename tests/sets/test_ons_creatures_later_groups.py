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



# --- the drive list: supported on arrival, given a game ---------------------


def test_w1g5_imagecrafter_taps_to_set_a_targets_type(set_pool, catalog_by_name):
    """"{T}: Choose a creature type other than Wall. Target creature becomes
    that type until end of turn." Summoning sick it cannot pay {T}; ready, it
    taps, Wall is refused, and the opponent's Bears become a Goblin under
    their own Goblin King's pump until cleanup."""
    game = _w1g5_game()
    crafter_card = set_pool("ONS")["Imagecrafter"]
    sick = _W1G5Permanent(card=crafter_card)
    game._put_permanent_onto_battlefield(0, sick, None)
    bears = _w1g5_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w1g5_put(game, 1, catalog_by_name["Goblin King"])
    assert not game.activate_permanent_ability(
        0, "Imagecrafter", target_permanent_ids=[bears.permanent_id],
    ).supported

    sick.metadata["summoning_sickness_turn"] = -99
    assert game.activate_permanent_ability(
        0, "Imagecrafter", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert sick.tapped
    assert game.confirm_creature_type_choice(0, "wall") is False
    assert game.confirm_creature_type_choice(0, "goblin")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(bears) == {"goblin"}
    assert (bears.effective_power, bears.effective_toughness) == (3, 3)
    game.resolve_cleanup_step(0)
    assert _w1g5_types(bears) == {"bear"}


def test_w1g5_mistform_mutant_pays_its_cost_and_sets_a_targets_type(
    set_pool, catalog_by_name,
):
    """"{1}{U}: Choose a creature type other than Wall. Target creature
    becomes that type until end of turn." Paid from the pool with costs on;
    aimed at a Wall of Wood, the set takes its Wall type away (it keeps its
    printed defender — a keyword, not a type)."""
    game = _w1g5_game()
    game.enforce_mana_costs = True
    _w1g5_put(game, 0, set_pool("ONS")["Mistform Mutant"])
    wall = _w1g5_put(game, 1, catalog_by_name["Wall of Wood"])
    assert not game.activate_permanent_ability(
        0, "Mistform Mutant", target_permanent_ids=[wall.permanent_id],
    ).supported, "nothing to pay with"
    game.players[0].mana_pool.update({"U": 1, "C": 1})
    assert game.activate_permanent_ability(
        0, "Mistform Mutant", target_permanent_ids=[wall.permanent_id],
    ).supported
    assert sum(game.players[0].mana_pool.values()) == 0
    assert game.confirm_creature_type_choice(0, "elf")
    _w1g5_resolve_stack(game)
    assert _w1g5_types(wall) == {"elf"}
    assert game._has_keyword(wall, "defender")

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
#
# Tribal nouns and counts: the Avatars' CDAs, the plural "Elves", a per-type
# life loss, a type's dies trigger, a type's prevention, a type card from a
# graveyard. Every count is asked of a creature of the type, one not of it,
# and one that *became* the type through a layer-4 effect.

import dataclasses as _w1g7_dataclasses

from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.mana_payment import is_mana_ability as _w1g7_is_mana_ability
from engine.models import Permanent as _w1g7_Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from engine.type_changes import gain_types as _w1g7_gain_types
from tests.helpers import _nosick as _w1g7_nosick, resolve_stack as _w1g7_resolve


def _w1g7_perm(pool, name):
    return _w1g7_nosick(_w1g7_Permanent(card=pool[name]))


def _w1g7_game(mine=(), theirs=(), *, p1=None, p2=None):
    one = _w1g7_PlayerState(name="P1", battlefield=list(mine), **(p1 or {}))
    two = _w1g7_PlayerState(name="P2", battlefield=list(theirs), **(p2 or {}))
    game = _w1g7_Game(players=[one, two])
    game.enforce_mana_costs = False
    game._settle()
    return game, one, two


def _w1g7_pt(game, perm):
    game._recompute_continuous_effects()
    return perm.effective_power, perm.effective_toughness


def _w1g7_tokens(player, name):
    return [p for p in player.battlefield if p.card.name == name]


def test_w1g7_heedless_one_counts_every_elf_on_the_battlefield(set_pool):
    """"…equal to the number of **Elves** on the battlefield." The plural
    "-ves" is singularized by the grammar's one singularizer, and the count is
    CR 403.1's shared zone: its own Elf, an opponent's, not a Goblin — and a
    Goblin that became an Elf (layer 4) is one."""
    pool = set_pool("ONS")
    heedless = _w1g7_perm(pool, "Heedless One")
    goblin = _w1g7_perm(pool, "Skirk Prospector")
    game, _p1, _p2 = _w1g7_game(
        [heedless, _w1g7_perm(pool, "Wirewood Elf"), goblin],
        [_w1g7_perm(pool, "Wellwisher")],
    )
    assert _w1g7_pt(game, heedless) == (3, 3)

    _w1g7_gain_types(goblin, subtypes=("elf",))
    assert _w1g7_pt(game, heedless) == (4, 4)
    assert game._has_keyword(heedless, "trample")


def test_w1g7_soulless_one_adds_the_zombie_cards_in_every_graveyard(set_pool):
    """"…the number of Zombies on the battlefield **plus** the number of Zombie
    cards in all graveyards." Two counts summed (``plus_count``): both
    battlefields, both graveyards, and neither a non-Zombie card nor a
    non-Zombie creature."""
    pool = set_pool("ONS")
    soulless = _w1g7_perm(pool, "Soulless One")
    elf = _w1g7_perm(pool, "Wirewood Elf")
    game, p1, p2 = _w1g7_game(
        [soulless, _w1g7_perm(pool, "Shepherd of Rot"), elf],
        [_w1g7_perm(pool, "Gangrenous Goliath")],
        p1={"graveyard": [pool["Rotlung Reanimator"], pool["Wellwisher"]]},
        p2={"graveyard": [pool["Aphetto Vulture"]]},
    )
    # Battlefield: Soulless One, Shepherd, Goliath = 3; graveyards: 2.
    assert _w1g7_pt(game, soulless) == (5, 5)

    _w1g7_gain_types(elf, subtypes=("zombie",))
    assert _w1g7_pt(game, soulless) == (6, 6)

    # A Zombie card leaving a graveyard is one fewer.
    p2.graveyard.clear()
    assert _w1g7_pt(game, soulless) == (5, 5)


def test_w1g7_shepherd_of_rot_drains_every_player_per_zombie(set_pool):
    """"{T}: Each player loses 1 life for each Zombie on the battlefield." One
    number, every battlefield's Zombies, and every player loses it — the
    Shepherd's own controller too."""
    pool = set_pool("ONS")
    shepherd = _w1g7_perm(pool, "Shepherd of Rot")
    game, p1, p2 = _w1g7_game(
        [shepherd, _w1g7_perm(pool, "Wirewood Elf")],
        [_w1g7_perm(pool, "Gangrenous Goliath")],
    )
    assert game.activate_permanent_ability(0, "Shepherd of Rot").supported
    _w1g7_resolve(game)
    assert (p1.life, p2.life) == (18, 18)
    assert shepherd.tapped


def test_w1g7_voice_of_the_woods_taps_five_elves_for_an_elemental(set_pool):
    """"Tap five untapped **Elves** you control" — the Voice itself among them
    (Voice of the Woods, 2004-10-04: "You may tap any untapped permanents you
    control with the appropriate creature type (including this creature)"),
    and a Goblin is never one of them."""
    pool = set_pool("ONS")
    voice = _w1g7_perm(pool, "Voice of the Woods")
    goblin = _w1g7_perm(pool, "Skirk Prospector")
    elves = [_w1g7_perm(pool, name) for name in (
        "Wirewood Elf", "Wellwisher", "Elvish Scrapper",
    )]
    game, p1, _p2 = _w1g7_game([voice, goblin] + elves)
    # Four Elves and a Goblin: the cost cannot be paid.
    refused = game.activate_permanent_ability(0, "Voice of the Woods")
    assert not refused.supported
    assert not _w1g7_tokens(p1, "Elemental Token")

    _w1g7_gain_types(goblin, subtypes=("elf",))
    game._recompute_continuous_effects()
    assert game.activate_permanent_ability(0, "Voice of the Woods").supported
    _w1g7_resolve(game)
    (elemental,) = _w1g7_tokens(p1, "Elemental Token")
    assert _w1g7_pt(game, elemental) == (7, 7)
    assert game._has_keyword(elemental, "trample")
    assert all(p.tapped for p in [voice, goblin] + elves)


def test_w1g7_birchlore_rangers_taps_two_elves_for_one_mana(set_pool):
    """"Tap two untapped Elves you control: Add one mana of any color." A mana
    ability (CR 605.1a), off the stack, the Rangers counted as one of the two.

    The real card is unsupported on this base for its Morph line, which is
    W1G1's; the line is driven on the printed card with that line alone."""
    real = set_pool("ONS")["Birchlore Rangers"]
    assert real.oracle_text.splitlines()[0].startswith("Tap two untapped Elves")
    rangers_card = _w1g7_dataclasses.replace(
        real, oracle_text=real.oracle_text.splitlines()[0]
    )
    program = _w1g7_compile(rangers_card)
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    assert _w1g7_is_mana_ability(ability)

    pool = set_pool("ONS")
    rangers = _w1g7_nosick(_w1g7_Permanent(card=rangers_card))
    elf = _w1g7_perm(pool, "Wirewood Elf")
    goblin = _w1g7_perm(pool, "Skirk Prospector")
    game, p1, _p2 = _w1g7_game([rangers, elf, goblin])
    assert game.activate_permanent_ability(0, rangers_card.name, mana_color="U").supported
    assert p1.mana_pool.get("U") == 1
    assert rangers.tapped and elf.tapped and not goblin.tapped
    assert not game.stack

    # One Elf left untapped beside a Goblin: refused, nothing made.
    game, p1, _p2 = _w1g7_game([
        _w1g7_nosick(_w1g7_Permanent(card=rangers_card)),
        _w1g7_perm(pool, "Skirk Prospector"),
    ])
    assert not game.activate_permanent_ability(0, rangers_card.name, mana_color="U").supported
    assert not any(p1.mana_pool.values())


def test_w1g7_rotlung_reanimator_its_own_death_and_another_clerics(set_pool):
    """"Whenever this creature or another Cleric dies" — a union. Its own death
    on every road (destroyed, sacrificed: CR 603.10a looks back in time), any
    other Cleric's on either side, never a non-Cleric's."""
    pool = set_pool("ONS")

    def board():
        rot = _w1g7_perm(pool, "Rotlung Reanimator")
        elf = _w1g7_perm(pool, "Wirewood Elf")
        theirs = _w1g7_perm(pool, "Daunting Defender")
        game, p1, p2 = _w1g7_game([rot, elf], [theirs])
        return game, p1, p2, rot, elf, theirs

    game, p1, _p2, rot, _elf, _theirs = board()
    game._destroy_target_permanent(p1, target_permanent_index=0)
    _w1g7_resolve(game)
    assert len(_w1g7_tokens(p1, "Zombie Token")) == 1

    game, p1, _p2, rot, _elf, _theirs = board()
    assert game.sacrifice_permanent(rot) is rot
    _w1g7_resolve(game)
    assert len(_w1g7_tokens(p1, "Zombie Token")) == 1

    game, p1, p2, _rot, _elf, _theirs = board()
    game._destroy_target_permanent(p2, target_permanent_index=0)
    _w1g7_resolve(game)
    assert len(_w1g7_tokens(p1, "Zombie Token")) == 1
    assert not _w1g7_tokens(p2, "Zombie Token"), "the token is the Reanimator's controller's"

    game, p1, _p2, _rot, elf, _theirs = board()
    game.sacrifice_permanent(elf)
    _w1g7_resolve(game)
    assert not _w1g7_tokens(p1, "Zombie Token")

    # An Elf that became a Cleric is another Cleric.
    game, p1, _p2, _rot, elf, _theirs = board()
    _w1g7_gain_types(elf, subtypes=("cleric",))
    game._recompute_continuous_effects()
    game.sacrifice_permanent(elf)
    _w1g7_resolve(game)
    assert len(_w1g7_tokens(p1, "Zombie Token")) == 1


def test_w1g7_rotlung_reanimator_is_this_creature_whatever_its_types(set_pool):
    """"This creature" names the object (CR 201.5), not a Cleric: a Reanimator
    that stopped being a Cleric (Conspiracy naming Goblin, CR 205.1a) still
    makes a Zombie as it dies. The reading that folded the union into "a
    Cleric dies" made nothing here."""
    pool = set_pool("ONS")
    rot = _w1g7_perm(pool, "Rotlung Reanimator")
    game, p1, _p2 = _w1g7_game([rot])
    conspiracy = _w1g7_Permanent(card=set_pool("MMQ")["Conspiracy"])
    p1.battlefield.append(conspiracy)
    game._initialize_permanent_state(conspiracy, 0, None)
    conspiracy.metadata["chosen_creature_type"] = "goblin"
    game.check_state_based_actions()
    assert not rot.has_type("cleric") and rot.has_type("goblin")

    game._destroy_target_permanent(p1, target_permanent_index=0)
    _w1g7_resolve(game)
    assert len(_w1g7_tokens(p1, "Zombie Token")) == 1


def test_w1g7_aphetto_vulture_puts_a_zombie_card_on_top(set_pool):
    """"When this creature dies, you may put target Zombie card from your
    graveyard on top of your library." The picker offers Zombie cards alone —
    the Vulture itself among them (Aphetto Vulture, 2004-10-04: "The ability
    can be used to return itself to the top of your library") — and the
    "may" is asked."""
    pool = set_pool("ONS")
    vulture = _w1g7_perm(pool, "Aphetto Vulture")
    game, p1, _p2 = _w1g7_game(
        [vulture],
        p1={"graveyard": [pool["Wirewood Elf"], pool["Gangrenous Goliath"]],
            "library": [pool["Swamp"]] * 3},
    )
    game._destroy_target_permanent(p1, target_permanent_index=0)
    _w1g7_resolve(game)
    assert game.confirm_optional_pay(0, accept=True)
    _w1g7_resolve(game)
    assert p1.library[0].name == "Gangrenous Goliath"
    assert [c.name for c in p1.graveyard] == ["Wirewood Elf", "Aphetto Vulture"]


def test_w1g7_aphetto_vulture_never_offers_a_non_zombie(set_pool):
    pool = set_pool("ONS")
    vulture = _w1g7_perm(pool, "Aphetto Vulture")
    game, p1, _p2 = _w1g7_game(
        [vulture],
        p1={"graveyard": [pool["Wirewood Elf"]], "library": [pool["Swamp"]] * 3},
    )
    game._destroy_target_permanent(p1, target_permanent_index=0)
    _w1g7_resolve(game)
    if game.pending_choices:
        game.confirm_optional_pay(0, accept=True)
        _w1g7_resolve(game)
    # The Vulture is the one Zombie card in the pile; the Elf never moves.
    assert [c.name for c in p1.graveyard] == ["Wirewood Elf"]
    assert p1.library[0].name == "Aphetto Vulture"


def test_w1g7_daunting_defender_shaves_one_off_each_cleric_you_control(set_pool):
    """"If a source would deal damage to a Cleric creature you control,
    prevent 1 of that damage." Its own Clerics (itself included), not a
    Giant, not an opponent's Cleric, not the player — and a Giant that became
    a Cleric (layer 4) is one."""
    pool = set_pool("ONS")
    defender = _w1g7_perm(pool, "Daunting Defender")
    giant = _w1g7_perm(pool, "Gangrenous Goliath")
    archon = _w1g7_perm(pool, "Cabal Archon")
    game, p1, p2 = _w1g7_game(
        [defender, giant], [archon], p2={"hand": [pool["Shock"]] * 5},
    )

    def shock(target=None):
        if target is None:
            result = game.cast_from_hand(1, "Shock", target_player_index=0)
        else:
            result = game.cast_from_hand(
                1, "Shock",
                target_player_index=game.controller_index_of(target),
                target_permanent_ids=[target.permanent_id],
            )
        assert result.supported, result.details
        _w1g7_resolve(game)

    shock(defender)
    assert defender.damage_marked == 1
    shock(giant)
    assert giant.damage_marked == 2
    shock(archon)
    assert not game.is_on_battlefield(archon), "an opponent's Cleric is not shielded"
    _w1g7_gain_types(giant, subtypes=("cleric",))
    game._recompute_continuous_effects()
    shock(giant)
    assert giant.damage_marked == 3 and game.is_on_battlefield(giant)
    shock()
    assert p1.life == 18, "the player is not a Cleric creature"


def test_w1g7_gangrenous_goliath_taps_three_clerics_from_the_graveyard(set_pool):
    """"Tap three untapped Clerics you control: Return this card from your
    graveyard to your hand." Supported on arrival and never activatable: the
    graveyard door refused every tap-other-permanents cost. The Clerics are on
    the battlefield and the card is in the pile, which CR 602 does not mind.
    Two Clerics are not enough, an Elf is no Cleric, an Elf that became one
    pays, and a Wizard named to pay is a refusal (CR 601.2h)."""
    pool = set_pool("ONS")
    medic = _w1g7_perm(pool, "Battlefield Medic")
    archon = _w1g7_perm(pool, "Cabal Archon")
    elf = _w1g7_perm(pool, "Wirewood Elf")
    wizard = _w1g7_perm(pool, "Aphetto Grifter")
    game, p1, _p2 = _w1g7_game(
        [medic, archon, elf, wizard], p1={"graveyard": [pool["Gangrenous Goliath"]]},
    )
    refused = game.activate_from_graveyard(0, "Gangrenous Goliath")
    assert not refused.supported
    assert not any(p.tapped for p in (medic, archon, elf, wizard))

    _w1g7_gain_types(elf, subtypes=("cleric",))
    game._recompute_continuous_effects()
    named_wrong = game.activate_from_graveyard(
        0, "Gangrenous Goliath",
        cost_permanent_ids=[medic.permanent_id, archon.permanent_id, wizard.permanent_id],
    )
    assert not named_wrong.supported
    assert not any(p.tapped for p in (medic, archon, elf, wizard))

    result = game.activate_from_graveyard(0, "Gangrenous Goliath")
    assert result.supported, result.details
    _w1g7_resolve(game)
    assert [c.name for c in p1.hand] == ["Gangrenous Goliath"]
    assert p1.graveyard == []
    assert medic.tapped and archon.tapped and elf.tapped and not wizard.tapped

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

# --- W1G12: revealing ---------------------------------------------------------
from engine import Game as _w1g12_Game
from engine.models import Permanent as _w1g12_Permanent
from engine.models import PlayerState as _w1g12_PlayerState
from engine.oracle import compile_card_oracle as _w1g12_compile
from engine.targeting import derive_activation_spec as _w1g12_activation_spec

from tests.helpers import resolve_stack as _w1g12_resolve_stack


def _w1g12_table(set_pool, library, *, hands=None, interactive=(), seats=2):
    ons = set_pool("ONS")
    hands = hands or {}
    names = ["Alice", "Bob", "Cara"][:seats]
    players = [
        _w1g12_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=(
                [ons[c] if isinstance(c, str) else c for c in library]
                if seat == 0 else [ons["Plains"]] * 5
            ),
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g12_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g12_put(game, seat, card):
    permanent = _w1g12_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g12_names(cards):
    return [card.name for card in cards]


def test_w1g12_goblin_machinist_pumps_by_the_first_nonland_and_bottoms_the_run(set_pool):
    """"{2}{R}: Reveal cards from the top of your library until you reveal a
    nonland card. This creature gets +X/+0 until end of turn, where X is that
    card's mana value. Put the revealed cards on the bottom of your library in
    any order." The run stops on Akroma's Vengeance (mana value 6) under two
    lands; the Machinist is 6/5; the three revealed cards — the find among
    them — go under the two cards that were never turned over, in the order
    the interactive owner chose (CR 401.4)."""
    game = _w1g12_table(
        set_pool,
        ["Mountain", "Island", "Akroma's Vengeance", "Forest", "Goblin Taskmaster"],
        interactive={0},
    )
    machinist = _w1g12_put(game, 0, set_pool("ONS")["Goblin Machinist"])
    assert game.activate_permanent_ability(0, "Goblin Machinist").supported
    assert not game.resolve_top_of_stack()
    order = game.pending_choice_of("reorder_library", 0)
    assert order is not None and order.data["position"] == "bottom"
    assert order.data["top_count"] == 3
    # Before the order is answered the pump has already happened (CR 608.2c:
    # the pump is printed before the bottom).
    assert (machinist.effective_power, machinist.effective_toughness) == (6, 5)
    assert game.confirm_reorder_library(0, [2, 1, 0])
    _w1g12_resolve_stack(game)
    assert _w1g12_names(game.players[0].library) == [
        "Forest", "Goblin Taskmaster", "Akroma's Vengeance", "Island", "Mountain",
    ]
    assert (machinist.effective_power, machinist.effective_toughness) == (6, 5)
    assert any("stopped on Akroma's Vengeance" in line for line in game.log)


def test_w1g12_goblin_machinist_over_an_all_land_library_is_zero(set_pool):
    """The ruling (2004-10-04): "If all the cards in your library are lands, X
    is zero." The whole library is revealed and put back, in the order a
    headless owner leaves it; the Machinist stays 0/5."""
    game = _w1g12_table(set_pool, ["Mountain", "Island", "Forest"])
    machinist = _w1g12_put(game, 0, set_pool("ONS")["Goblin Machinist"])
    assert game.activate_permanent_ability(0, "Goblin Machinist").supported
    _w1g12_resolve_stack(game)
    assert (machinist.effective_power, machinist.effective_toughness) == (0, 5)
    assert _w1g12_names(game.players[0].library) == ["Mountain", "Island", "Forest"]
    assert game.pending_choices == []


def test_w1g12_riptide_shapeshifter_digs_for_the_type_it_names(set_pool):
    """"{2}{U}{U}, Sacrifice this creature: Choose a creature type. Reveal
    cards from the top of your library until you reveal a creature card of
    that type. Put that card onto the battlefield and shuffle the rest into
    your library." Named Goblin, the run passes the Elf (a creature card, but
    not of that type) and stops on the Goblin under it; the Elf and the land
    are shuffled back, the Goblin under the bottom stays in the library."""
    game = _w1g12_table(
        set_pool,
        ["Forest", "Wellwisher", "Goblin Taskmaster", "Island", "Skirk Commando"],
        interactive={0},
    )
    _w1g12_put(game, 0, set_pool("ONS")["Riptide Shapeshifter"])
    # It targets nothing: no picker for the client to fill in.
    assert _w1g12_activation_spec(
        _w1g12_compile(set_pool("ONS")["Riptide Shapeshifter"]).activated_abilities[0]
    ) is None
    assert game.activate_permanent_ability(0, "Riptide Shapeshifter").supported
    assert _w1g12_names(game.players[0].graveyard) == ["Riptide Shapeshifter"]
    assert not game.resolve_top_of_stack()
    assert game.confirm_creature_type_choice(0, "Goblin")
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Goblin Taskmaster"]
    assert sorted(_w1g12_names(game.players[0].library)) == [
        "Forest", "Island", "Skirk Commando", "Wellwisher",
    ]


def test_w1g12_riptide_shapeshifter_naming_a_type_nothing_has_finds_nothing(set_pool):
    """A type no card in the library has: the whole library is revealed,
    nothing enters, and every card is shuffled back — never the first creature
    card of some other type. And the default a seat nobody asks takes is its
    own library's commonest type (two Goblins against one Elf)."""
    game = _w1g12_table(
        set_pool, ["Forest", "Wellwisher", "Island"], interactive={0},
    )
    _w1g12_put(game, 0, set_pool("ONS")["Riptide Shapeshifter"])
    assert game.activate_permanent_ability(0, "Riptide Shapeshifter").supported
    assert not game.resolve_top_of_stack()
    assert game.confirm_creature_type_choice(0, "Goblin")
    _w1g12_resolve_stack(game)
    assert list(game.all_permanents()) == []
    assert sorted(_w1g12_names(game.players[0].library)) == [
        "Forest", "Island", "Wellwisher",
    ]

    game = _w1g12_table(
        set_pool,
        ["Forest", "Wellwisher", "Goblin Taskmaster", "Island", "Skirk Commando"],
    )
    _w1g12_put(game, 0, set_pool("ONS")["Riptide Shapeshifter"])
    assert game.activate_permanent_ability(0, "Riptide Shapeshifter").supported
    _w1g12_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Goblin Taskmaster"]


def _w1g12_ogre_numbers(set_pool, numbers, *, seats=2):
    """Cast Menacing Ogre with every seat interactive and answer each seat's
    secret number; the Ogre and the table after the trigger resolves."""
    game = _w1g12_table(
        set_pool, ["Mountain"] * 5, hands={0: ["Menacing Ogre"]},
        interactive=set(range(seats)), seats=seats,
    )
    assert game.cast_from_hand(0, "Menacing Ogre").supported
    assert len(game.stack) == 1, "the entry trigger is on the stack (CR 603.3)"
    assert not game.resolve_top_of_stack()
    owed = sorted(c.player_index for c in game.pending_choices if c.kind == "secret_number")
    assert owed == list(range(seats))
    # Answered last seat first: no number is shown before the last exists.
    for seat in reversed(range(seats)):
        assert not any(
            line.startswith("Menacing Ogre: ") and " revealed " in line
            for line in game.log
        ), "a secret number was shown before every seat had one"
        assert game.confirm_secret_number(seat, numbers[seat])
    _w1g12_resolve_stack(game)
    ogre = next(p for p in game.all_permanents() if p.card.name == "Menacing Ogre")
    return game, ogre


def test_w1g12_menacing_ogre_a_tie_for_highest_costs_both_and_feeds_the_ogre(set_pool):
    """"When this creature enters, each player secretly chooses a number. Then
    those numbers are revealed. Each player with the highest number loses that
    much life. If you are one of those players, put two +1/+1 counters on this
    creature." Alice and Bob both name 3: each loses 3, and Alice — one of
    those players — gets her two counters. The reveal is one line, every
    number at once, after the last answer."""
    game, ogre = _w1g12_ogre_numbers(set_pool, [3, 3])
    assert [p.life for p in game.players] == [17, 17]
    assert (ogre.effective_power, ogre.effective_toughness) == (5, 5)
    assert any("Alice revealed 3, Bob revealed 3" in line for line in game.log)


def test_w1g12_menacing_ogre_only_the_highest_pays_and_a_loser_gets_nothing(set_pool):
    """Bob's 4 beats Alice's 1: Bob alone loses 4, Alice nothing, and the Ogre
    stays 3/3. At three seats Bob and Cara tie on 6 over Alice's 2: both lose
    6 and Alice is not one of those players."""
    game, ogre = _w1g12_ogre_numbers(set_pool, [1, 4])
    assert [p.life for p in game.players] == [20, 16]
    assert (ogre.effective_power, ogre.effective_toughness) == (3, 3)

    game, ogre = _w1g12_ogre_numbers(set_pool, [2, 6, 6], seats=3)
    assert [p.life for p in game.players] == [20, 14, 14]
    assert (ogre.effective_power, ogre.effective_toughness) == (3, 3)


def test_w1g12_menacing_ogre_numbers_are_whole_and_not_negative(set_pool):
    """The ruling (2004-10-04): "You have to choose zero or a positive number.
    It must be an integer number." Minus one and a fraction are refused with
    the prompt kept; zero is an answer. And seats nobody asks name the floor —
    the highest pays, so any more is life lost for nothing — which ties them
    at 0 and gives the Ogre its counters for free."""
    game = _w1g12_table(
        set_pool, ["Mountain"] * 5, hands={0: ["Menacing Ogre"]}, interactive={0, 1},
    )
    assert game.cast_from_hand(0, "Menacing Ogre").supported
    assert not game.resolve_top_of_stack()
    assert not game.confirm_secret_number(0, -1)
    assert not game.confirm_secret_number(0, "1.5")
    assert game.pending_choice_of("secret_number", 0) is not None
    assert game.confirm_secret_number(0, 0)

    game = _w1g12_table(set_pool, ["Mountain"] * 5, hands={0: ["Menacing Ogre"]})
    assert game.cast_from_hand(0, "Menacing Ogre").supported
    _w1g12_resolve_stack(game)
    ogre = next(p for p in game.all_permanents() if p.card.name == "Menacing Ogre")
    assert [p.life for p in game.players] == [20, 20]
    assert (ogre.effective_power, ogre.effective_toughness) == (5, 5)

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# --- W1G13: each player, and graveyards --------------------------------------
from engine import Game as _w1g13_Game
from engine.models import Permanent as _w1g13_Permanent
from engine.models import PlayerState as _w1g13_PlayerState

from tests.helpers import _mk_creature_card as _w1g13_creature
from tests.helpers import resolve_stack as _w1g13_resolve_stack


def _w1g13_table(set_pool, hands=None, *, interactive=(), seats=3):
    ons = set_pool("ONS")
    hands = hands or {}
    names = ["Alice", "Bob", "Cara", "Dan"][:seats]
    players = [
        _w1g13_PlayerState(
            name=name,
            hand=[ons[card] if isinstance(card, str) else card for card in hands.get(seat, ())],
            library=[ons["Plains"]] * 5,
        )
        for seat, name in enumerate(names)
    ]
    game = _w1g13_Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.active_player_index = 0
    return game


def _w1g13_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_entrails_feaster_exiles_from_any_graveyard_it_names(set_pool):
    """"At the beginning of your upkeep, you may exile a creature card from a
    graveyard. If you do, put a +1/+1 counter on this creature." Any pile:
    the controller names Cara's graveyard and the creature card in it, never
    the land beside it, and the Feaster grows."""
    game = _w1g13_table(set_pool, interactive={0})
    alice, bob, cara = game.players
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    bob.graveyard.append(_w1g13_creature("Bob's Bear", 2, 2))
    cara.graveyard.extend([set_pool("ONS")["Plains"], _w1g13_creature("Cara's Giant", 3, 3)])
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Entrails Feaster", accept=True)
    pile = game.pending_choice_of("graveyard_pile_choice", 0)
    assert pile is not None and sorted(pile.data["seats"]) == [1, 2]
    assert game.confirm_graveyard_pile_choice(0, 2)
    assert game.confirm_graveyard_exile_pick(0, [1])
    _w1g13_resolve_stack(game)
    assert [c.name for c in cara.exile] == ["Cara's Giant"]
    assert [c.name for c in cara.graveyard] == ["Plains"]
    assert [c.name for c in bob.graveyard] == ["Bob's Bear"]
    assert (feaster.effective_power, feaster.effective_toughness) == (2, 2)
    assert not feaster.tapped


def test_w1g13_entrails_feaster_taps_when_it_does_not_exile(set_pool):
    """"If you don't, tap this creature." Declining taps it; and with no
    creature card in any graveyard there is nothing to exile, so the offer is
    never made and it taps all the same."""
    game = _w1g13_table(set_pool, interactive={0})
    bob = game.players[1]
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    bob.graveyard.append(_w1g13_creature("Bob's Bear", 2, 2))
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Entrails Feaster", accept=False)
    _w1g13_resolve_stack(game)
    assert feaster.tapped and feaster.effective_power == 1
    assert [c.name for c in bob.graveyard] == ["Bob's Bear"]

    game = _w1g13_table(set_pool)
    feaster = _w1g13_put(game, 0, set_pool("ONS")["Entrails Feaster"])
    game.players[1].graveyard.append(set_pool("ONS")["Plains"])
    game.resolve_upkeep(0)
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert game.pending_choices == []
    assert feaster.tapped and feaster.effective_power == 1


def test_w1g13_gigapede_returns_from_the_graveyard_for_a_discard(set_pool):
    """"At the beginning of your upkeep, if this card is in your graveyard,
    you may discard a card. If you do, return this card to your hand." The
    graveyard-trigger census's red on the ingest was the census, not the card:
    the discard pays, and the Gigapede is in the hand."""
    gigapede = set_pool("ONS")["Gigapede"]
    game = _w1g13_table(set_pool, {0: ["Plains"]}, interactive={0})
    alice = game.players[0]
    alice.graveyard.append(gigapede)
    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, "Gigapede", accept=True)
    assert game.resolve_pending_choice(
        "discard", 0, hand_indices=[0], to_library=False,
    )
    _w1g13_resolve_stack(game)
    assert [c.name for c in alice.hand] == ["Gigapede"]
    assert [c.name for c in alice.graveyard] == ["Plains"]


def _w1g13_quiet_put(game, seat, card):
    permanent = _w1g13_Permanent(card=card)
    game.players[seat].battlefield.append(permanent)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def test_w1g13_tempting_wurm_each_opponent_puts_cards_from_their_hand(set_pool):
    """"When this creature enters, each opponent may put any number of
    artifact, creature, enchantment, and/or land cards from their hand onto
    the battlefield." Each opponent in APNAP order, Bob before Cara, offered
    only the four printed types (never the instant), the Wurm's controller
    never asked; the chosen cards enter together under their owners, after
    the last choice, and an Aura enters attached to a creature already there
    (CR 303.4f) — its controller asked which."""
    ons = set_pool("ONS")
    giant = _w1g13_creature("Bob's Giant", 3, 3)
    game = _w1g13_table(
        set_pool,
        {0: ["Tempting Wurm"], 1: [giant, "Pacifism", "Shock", "Forest"],
         2: ["Plains"]},
        interactive={0, 1, 2},
    )
    alice, bob, cara = game.players
    alices = _w1g13_quiet_put(game, 0, _w1g13_creature("Alice's Bear", 2, 2))
    assert game.cast_from_hand(0, "Tempting Wurm").supported
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 1),
    ]
    offered = game.live_choose_cards_in_hand(game.pending_choices[0])
    assert [bob.hand[i].name for i in offered] == ["Bob's Giant", "Pacifism", "Forest"]
    assert game.confirm_choose_cards_in_hand(1, offered)
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("choose_cards_in_hand", 2),
    ]
    assert not any(perm.card is giant for perm in game.controlled_by(1)), (
        "nothing enters before the last opponent has chosen"
    )
    assert game.confirm_choose_cards_in_hand(2, [])
    host = game.pending_choice_of("permanent_choice", 1)
    assert host is not None, "Bob chooses what his Pacifism enchants"
    assert game.confirm_permanent_choice(1, alices.permanent_id)
    _w1g13_resolve_stack(game)
    assert sorted(perm.card.name for perm in game.controlled_by(1)) == [
        "Bob's Giant", "Forest", "Pacifism",
    ]
    assert [c.name for c in bob.hand] == ["Shock"]
    pacifism = next(p for p in game.controlled_by(1) if p.card is ons["Pacifism"])
    assert pacifism.metadata.get("attached_to") is alices
    assert [c.name for c in cara.hand] == ["Plains"]
    assert [perm.card.name for perm in game.controlled_by(2)] == []


def test_w1g13_tempting_wurm_an_aura_with_nothing_to_enchant_stays_in_hand(set_pool):
    """CR 303.4g: with no creature already on the battlefield besides the
    Wurm — here none at all once the Wurm is gone — an Aura stays in the hand.
    A seat nobody asks takes every card the sentence offers."""
    ons = set_pool("ONS")
    game = _w1g13_table(set_pool, {0: ["Tempting Wurm"], 1: ["Pacifism", "Forest"]})
    bob = game.players[1]
    assert game.queue_from_hand(0, "Tempting Wurm").supported
    game.resolve_top_of_stack()
    wurm = next(p for p in game.controlled_by(0) if p.card.name == "Tempting Wurm")
    game.remove_from_battlefield(wurm)
    _w1g13_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [perm.card.name for perm in game.controlled_by(1)] == ["Forest"]
    assert [c.name for c in bob.hand] == ["Pacifism"]
    assert any("303.4g" in line for line in game.log)
    assert ons["Pacifism"] in bob.hand

# ==== end W1G13 ======================================================

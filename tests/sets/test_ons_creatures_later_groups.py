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
    reach — not the type the Oppressor's controller has most of."""
    game = _w1g4_game(
        [_w1g4_creature(f"My Elf {n}", "Elf") for n in range(3)],
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

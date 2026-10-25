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

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

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

# ==== end W1G12 ======================================================


# ==== W1G13 ==========================================================
# W1G13's tests go between this line and the "end W1G13" line.

# ==== end W1G13 ======================================================

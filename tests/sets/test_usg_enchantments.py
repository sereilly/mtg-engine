"""Urza's Saga enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: the Auras ---
#
# Eleven cards, and every one of them is given a game rather than a compile
# check: "it reports supported" is what the hollow-lines and parse-coverage
# instruments exist to catch, and this set already ships nine supported cards
# carrying a line nothing implements.
import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack


def _g4_creature(name: str, power: int = 2, toughness: int = 2) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="{1}{G}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _g4_board(*, mine: list, theirs: list | None = None, life: int = 20):
    """A two-seat game with mana costs off and control synced.

    Returns ``(game, seat0, seat1)`` - never a bare ``game``, so no mechanical
    union can splice a different group's helper body onto this signature.
    """
    g4_seat0 = PlayerState(name="P1", battlefield=list(mine), life=life)
    g4_seat1 = PlayerState(name="P2", battlefield=list(theirs or []), life=life)
    g4_game = Game(players=[g4_seat0, g4_seat1])
    g4_game.enforce_mana_costs = False
    g4_game._sync_control()
    return g4_game, g4_seat0, g4_seat1


@pytest.mark.parametrize(
    "aura_name",
    ["Brilliant Halo", "Despondency", "Fiery Mantle", "Fortitude", "Launch",
     "Spreading Algae"],
)
def test_w1g4_the_self_returning_auras_compile_a_real_trigger(set_pool, aura_name):
    """All six print "When this Aura is put into a graveyard from the
    battlefield, return it to its owner's hand".

    The compiled trigger is asserted, not just ``supported``: the card is
    supported on the strength of its *other* lines, and the whole defect this
    round fixed was a sentence that read fine on one front end and produced no
    ability at all on the one that dispatches.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("USG")[aura_name])
    assert program.supported, program.reason
    assert any(
        trig.condition.kind == "dies"
        and trig.instruction is not None
        and trig.instruction.kind == "return_source_card_to_owners_hand"
        for trig in program.triggered_abilities
    ), [trig.condition.kind for trig in program.triggered_abilities]


def test_w1g4_brilliant_halo_returns_itself_when_its_host_dies(set_pool):
    """The CR 704.5m path: the host leaves, the sweep bins the Aura, and the
    Aura's own death trigger hands it back."""
    host = Permanent(card=_g4_creature("Host"))
    aura = Permanent(card=set_pool("USG")["Brilliant Halo"])
    game, mine, _ = _g4_board(mine=[host, aura])
    attach_aura(aura, host)

    game._destroy_swept_permanents(mine, lambda perm: perm is host)
    game.check_state_based_actions()
    resolve_stack(game)

    assert [card.name for card in mine.hand] == ["Brilliant Halo"]
    assert [card.name for card in mine.graveyard] == ["Host"]


def test_w1g4_launch_returns_itself_when_the_aura_alone_is_destroyed(set_pool):
    """The other path - the host survives - because the trigger is on the
    Aura's own death and not on its host's."""
    host = Permanent(card=_g4_creature("Host"))
    aura = Permanent(card=set_pool("USG")["Launch"])
    game, mine, _ = _g4_board(mine=[host, aura])
    attach_aura(aura, host)

    game._destroy_swept_permanents(mine, lambda perm: perm is aura)
    resolve_stack(game)

    assert [card.name for card in mine.hand] == ["Launch"]
    assert [perm.card.name for perm in mine.battlefield] == ["Host"]
    assert mine.graveyard == []


def test_w1g4_spreading_algae_only_enchants_a_swamp(set_pool):
    """Both halves of the Roots lesson: the picker offers Swamps alone, and the
    attach check refuses anything else rather than taking the permissive
    fallback that a noun with no matcher row would reach."""
    from engine.auras import aura_attach_refusal
    from engine.mixins.stack.casting import permanent_matches_enchant_noun
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_cast_spec

    pool = set_pool("USG")
    algae = pool["Spreading Algae"]
    swamp = Permanent(card=pool["Swamp"])
    mountain = Permanent(card=pool["Mountain"])
    game, _, _ = _g4_board(mine=[swamp, mountain])

    spec = derive_cast_spec(algae, compile_card_oracle(algae))
    assert spec == {"kind": "land", "enchant_land_type": "swamp"}
    offered = game._enumerate_targets(0, algae, spec, for_cast=True)
    assert [entry["name"] for entry in offered] == ["Swamp"]

    assert permanent_matches_enchant_noun(swamp, "swamp")
    assert not permanent_matches_enchant_noun(mountain, "swamp")
    aura = Permanent(card=algae)
    assert aura_attach_refusal(game, aura, swamp) is None
    assert aura_attach_refusal(game, aura, mountain) is not None


def test_w1g4_spreading_algae_destroys_its_swamp_and_comes_back(set_pool):
    pool = set_pool("USG")
    swamp = Permanent(card=pool["Swamp"])
    aura = Permanent(card=pool["Spreading Algae"])
    game, mine, _ = _g4_board(mine=[swamp, aura])
    attach_aura(aura, swamp)

    game.become_tapped(swamp)
    resolve_stack(game)
    game.check_state_based_actions()
    resolve_stack(game)

    assert [card.name for card in mine.graveyard] == ["Swamp"]
    assert [card.name for card in mine.hand] == ["Spreading Algae"]
    assert mine.battlefield == []


def test_w1g4_pariah_moves_its_controllers_damage_onto_the_host(set_pool):
    host = Permanent(card=_g4_creature("Wall", 0, 6))
    aura = Permanent(card=set_pool("USG")["Pariah"])
    game, mine, _ = _g4_board(mine=[host, aura])

    game._deal_damage_to_player(mine, 3, source=aura)
    assert mine.life == 17, "unattached, the Aura moves nothing"

    attach_aura(aura, host)
    game._deal_damage_to_player(mine, 3, source=aura)
    assert mine.life == 17
    assert host.damage_marked == 3


def test_w1g4_pariah_stops_the_moment_the_host_is_gone(set_pool):
    """CR 614.9's liveness half, and the reason the redirection is derived from
    the Aura's text rather than armed as a record: the Aura falls off with its
    host and there is nothing left to undo."""
    host = Permanent(card=_g4_creature("Wall", 0, 4))
    aura = Permanent(card=set_pool("USG")["Pariah"])
    game, mine, _ = _g4_board(mine=[host, aura])
    attach_aura(aura, host)

    game._deal_damage_to_player(mine, 4, source=aura)
    game.check_state_based_actions()
    assert mine.life == 20
    assert sorted(card.name for card in mine.graveyard) == ["Pariah", "Wall"]

    game._deal_damage_to_player(mine, 3, source=aura)
    assert mine.life == 17


def test_w1g4_cloak_of_mists_makes_its_host_unblockable(set_pool):
    attacker = Permanent(card=_g4_creature("Attacker"))
    blocker = Permanent(card=_g4_creature("Blocker"))
    aura = Permanent(card=set_pool("USG")["Cloak of Mists"])
    game, _, _ = _g4_board(mine=[attacker, aura], theirs=[blocker])
    attacker.attacking = True

    assert game._can_block_attacker(blocker, attacker)
    assert not game.is_unblockable(attacker)

    attach_aura(aura, attacker)
    assert not game._can_block_attacker(blocker, attacker)
    assert game.is_unblockable(attacker), (
        "the UI's fade and the blocker gate have to agree, or the client "
        "promises a block the step then rejects"
    )

    detach_aura(aura, attacker)
    assert game._can_block_attacker(blocker, attacker)


def test_w1g4_fertile_ground_adds_a_mana_of_the_colour_asked_for(set_pool):
    pool = set_pool("USG")
    forest = Permanent(card=pool["Forest"])
    aura = Permanent(card=pool["Fertile Ground"])
    game, mine, _ = _g4_board(mine=[forest, aura])
    attach_aura(aura, forest)

    game.tap_land_for_mana(0, "Forest", chosen_color="U")
    assert {sym: n for sym, n in mine.mana_pool.items() if n} == {"G": 1, "U": 1}

    forest.tapped = False
    game.clear_mana_pools()
    detach_aura(aura, forest)
    game.tap_land_for_mana(0, "Forest", chosen_color="U")
    assert {sym: n for sym, n in mine.mana_pool.items() if n} == {"G": 1}


def test_w1g4_venomous_fangs_destroys_what_its_host_damaged(set_pool):
    host = Permanent(card=_g4_creature("Host", 1, 5))
    victim = Permanent(card=_g4_creature("Victim", 1, 9))
    aura = Permanent(card=set_pool("USG")["Venomous Fangs"])
    game, mine, theirs = _g4_board(mine=[host, aura], theirs=[victim])
    attach_aura(aura, host)

    game._mark_damage_on_permanent(victim, 1, source=host, combat=True)
    resolve_stack(game)
    game.check_state_based_actions()

    assert [card.name for card in theirs.graveyard] == ["Victim"], (
        "'the other creature' is the one that took the damage, not the host"
    )
    assert [perm.card.name for perm in mine.battlefield] == [
        "Host", "Venomous Fangs",
    ]


def test_w1g4_vampiric_embrace_grows_the_enchanted_creature(set_pool):
    """"That creature" is the **enchanted** one - Sengir Vampire's ability
    granted by an Aura, with the counter on the killer."""
    host = Permanent(card=_g4_creature("Host"))
    victim = Permanent(card=_g4_creature("Victim", 1, 2))
    aura = Permanent(card=set_pool("USG")["Vampiric Embrace"])
    game, _, theirs = _g4_board(mine=[host, aura], theirs=[victim])
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    assert (host.effective_power, host.effective_toughness) == (4, 4)
    assert game._has_keyword(host, "flying")

    game._mark_damage_on_permanent(victim, 2, source=host, combat=True)
    game.check_state_based_actions()
    resolve_stack(game)
    game._recompute_continuous_effects()

    assert [card.name for card in theirs.graveyard] == ["Victim"]
    assert (host.effective_power, host.effective_toughness) == (5, 5)


def test_w1g4_a_creature_the_host_did_not_damage_grows_nothing(set_pool):
    """The narrowing the fire site enforces: the condition is about a creature
    *this Aura's host* damaged, and an unrelated death is not one."""
    host = Permanent(card=_g4_creature("Host"))
    bystander = Permanent(card=_g4_creature("Bystander", 1, 1))
    aura = Permanent(card=set_pool("USG")["Vampiric Embrace"])
    game, _, theirs = _g4_board(mine=[host, aura], theirs=[bystander])
    attach_aura(aura, host)

    game._destroy_swept_permanents(theirs, lambda perm: perm is bystander)
    resolve_stack(game)

    assert host.metadata.get("plus_counters", 0) == 0

# --- W1G3: "it becomes a N/N creature" — the Hidden / Opal / Veiled cycle ---
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g3_pool():
    """Every shipped card by name, for the spells an opponent casts at these.

    The cycle's whole trigger is *somebody else's* spell, so a test of it needs
    a second set's card to cast — which is what `set_pool("USG")` deliberately
    cannot give. Loaded from the manifest rather than from a spelled-out
    filename, and memoized on the function so eighteen tests read the JSON once.
    """
    cached = getattr(_g3_pool, "_cache", None)
    if cached is None:
        cached = {}
        for path in manifest_set_paths():
            for card in load_cards(path):
                cached.setdefault(card.name, card)
        _g3_pool._cache = cached
    return cached


def _g3_board(set_pool, name):
    """*name* on Alice's battlefield in a two-seat game, with Bob to cast at it."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    permanent = Permanent(card=set_pool("USG")[name])
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return game, permanent, bob


def _g3_cast(game, name):
    game.players[1].hand.append(_g3_pool()[name])
    game.cast_from_hand(1, name)
    resolve_stack(game)


def test_opal_gargoyle_wakes_and_stops_being_an_enchantment(set_pool):
    """"When an opponent casts a creature spell, if this permanent is an
    enchantment, it becomes a 2/2 Gargoyle creature with flying."

    Three things at once, and the third is the one a partial reading would
    drop: the enchantment becomes a creature (CR 205.1a), it stops being an
    enchantment, and it has flying. The middle assertion is what its own
    intervening-if then reads — an animation that merely *added* the creature
    type would leave the Gargoyle re-animating on every creature spell for the
    rest of the game.
    """
    game, gargoyle, _ = _g3_board(set_pool, "Opal Gargoyle")
    assert gargoyle.has_type("enchantment") and not gargoyle.is_creature

    _g3_cast(game, "Grizzly Bears")

    assert gargoyle.is_creature
    assert not gargoyle.has_type("enchantment")
    assert gargoyle.has_type("gargoyle")
    assert (gargoyle.effective_power, gargoyle.effective_toughness) == (2, 2)
    assert gargoyle.has_keyword("flying")


def test_opal_gargoyle_ignores_a_spell_that_is_not_a_creature_spell(set_pool):
    """The narrowing, asserted on its own.

    A card that woke to any spell would pass the test above, which is why the
    negative is written beside it: the printed word "creature" is the whole
    difference between Opal Gargoyle and Veil of Birds.
    """
    game, gargoyle, _ = _g3_board(set_pool, "Opal Gargoyle")

    _g3_cast(game, "Lightning Bolt")

    assert not gargoyle.is_creature
    assert gargoyle.has_type("enchantment")


def test_veil_of_birds_wakes_to_any_spell(set_pool):
    """Veil of Birds is Opal Gargoyle's unnarrowed twin — "casts **a spell**" —
    so the Bolt that leaves the Gargoyle asleep wakes this one."""
    game, veil, _ = _g3_board(set_pool, "Veil of Birds")

    _g3_cast(game, "Lightning Bolt")

    assert veil.is_creature and veil.has_keyword("flying")
    assert (veil.effective_power, veil.effective_toughness) == (1, 1)


def test_hidden_ancients_watches_enchantment_spells(set_pool):
    """"When an opponent casts an **enchantment** spell…" — the same trigger
    with a different type word, so the pair asserts that the narrowing is
    payload rather than a per-card reading."""
    game, ancients, _ = _g3_board(set_pool, "Hidden Ancients")

    _g3_cast(game, "Grizzly Bears")
    assert not ancients.is_creature, "a creature spell is not an enchantment spell"

    _g3_cast(game, "Bad Moon")
    assert ancients.is_creature
    assert (ancients.effective_power, ancients.effective_toughness) == (5, 5)


def test_hidden_guerrillas_watches_artifact_spells_and_gains_trample(set_pool):
    """The artifact narrowing, plus the keyword the body grants — asserted
    together because a body whose keyword list was dropped still animates."""
    game, guerrillas, _ = _g3_board(set_pool, "Hidden Guerrillas")

    _g3_cast(game, "Black Lotus")

    assert guerrillas.is_creature
    assert (guerrillas.effective_power, guerrillas.effective_toughness) == (5, 3)
    assert guerrillas.has_keyword("trample")


def test_hidden_spider_reads_the_keyword_on_the_spell_it_watches(set_pool):
    """"When an opponent casts a creature spell **with flying**…"

    The narrowing is on an ability of the spell rather than on its type line,
    so both halves are asserted: a ground creature leaves the Spider asleep and
    a flier wakes it. Without the second the card looks broken; without the
    first a Spider that woke to every creature spell would pass.
    """
    game, spider, _ = _g3_board(set_pool, "Hidden Spider")

    _g3_cast(game, "Grizzly Bears")
    assert not spider.is_creature, "Grizzly Bears does not fly"

    _g3_cast(game, "Serra Angel")
    assert spider.is_creature
    assert (spider.effective_power, spider.effective_toughness) == (3, 5)
    assert spider.has_keyword("reach")


def test_hidden_herd_wakes_only_for_a_nonbasic_land(set_pool):
    """"When an opponent plays a **nonbasic** land…" (CR 205.4a, CR 305.1.)

    A land *played*, not a land entering — and the supertype is the narrowing,
    so the basic case is asserted first. A Herd that woke to any land drop
    would pass the second assertion alone.
    """
    game, herd, bob = _g3_board(set_pool, "Hidden Herd")
    game.active_player_index = 1

    bob.hand.append(_g3_pool()["Forest"])
    game.cast_from_hand(1, "Forest")
    resolve_stack(game)
    assert not herd.is_creature, "a Forest is a basic land"

    bob.hand.append(_g3_pool()["Mishra's Factory"])
    game.cast_from_hand(1, "Mishra's Factory")
    resolve_stack(game)
    assert herd.is_creature
    assert (herd.effective_power, herd.effective_toughness) == (3, 3)


def test_hidden_stag_turns_back_into_an_enchantment_on_your_own_land_drop(set_pool):
    """Both of Hidden Stag's lines, in the order the card plays them.

    "Whenever an opponent plays a land, if this permanent is an enchantment, it
    becomes a 3/2 Elk Beast creature." / "Whenever you play a land, if this
    permanent is a creature, it becomes an enchantment."

    The second line is the one a card reported "supported" on its first line
    alone would silently drop, and the round trip is what proves the two
    layer-4 records are ordered rather than one deleting the other.
    """
    game, stag, bob = _g3_board(set_pool, "Hidden Stag")
    game.active_player_index = 1
    bob.hand.append(_g3_pool()["Forest"])
    game.cast_from_hand(1, "Forest")
    resolve_stack(game)
    assert stag.is_creature and not stag.has_type("enchantment")
    assert (stag.effective_power, stag.effective_toughness) == (3, 2)

    game.active_player_index = 0
    game.players[0].hand.append(_g3_pool()["Plains"])
    game.cast_from_hand(0, "Plains")
    resolve_stack(game)
    assert stag.has_type("enchantment") and not stag.is_creature


def test_opal_acrolith_can_hide_again_and_wake_again(set_pool):
    """"{0}: This permanent becomes an enchantment." — the cycle's one
    activated way back, and the reason the animation record has a timestamp.

    Asserted over three states, because the middle one is where an
    implementation that *deleted* the animation record would still look right
    and the third is where it would fail.
    """
    game, acrolith, _ = _g3_board(set_pool, "Opal Acrolith")

    _g3_cast(game, "Grizzly Bears")
    assert acrolith.is_creature
    assert (acrolith.effective_power, acrolith.effective_toughness) == (2, 4)

    game.activate_permanent_ability(0, "Opal Acrolith")
    resolve_stack(game)
    assert acrolith.has_type("enchantment") and not acrolith.is_creature

    _g3_cast(game, "Hill Giant")
    assert acrolith.is_creature
    assert (acrolith.effective_power, acrolith.effective_toughness) == (2, 4)


def test_opal_archangel_carries_both_of_its_keywords(set_pool):
    """"…a 5/5 Angel creature with flying **and** vigilance."

    Two keywords joined by "and", which is the shape a list production that
    stopped at the first would silently halve.
    """
    game, angel, _ = _g3_board(set_pool, "Opal Archangel")

    _g3_cast(game, "Grizzly Bears")

    assert angel.has_keyword("flying") and angel.has_keyword("vigilance")
    assert (angel.effective_power, angel.effective_toughness) == (5, 5)


def test_opal_titan_takes_protection_from_the_colours_of_the_spell(set_pool):
    """"…a 4/4 Giant creature with **protection from each of that spell's
    colors**." (CR 702.16g.)

    The colours are not on the card, so what is asserted is that the Titan's
    protection follows the spell: a green creature spell gives protection from
    green and from nothing else.
    """
    game, titan, _ = _g3_board(set_pool, "Opal Titan")

    _g3_cast(game, "Grizzly Bears")

    assert titan.is_creature
    assert (titan.effective_power, titan.effective_toughness) == (4, 4)
    assert game._protection_colors(titan) == {"G"}


def test_veiled_sentry_is_as_big_as_the_spell_that_woke_it(set_pool):
    """"…an Illusion creature with power and toughness each equal to that
    spell's mana value." (CR 208.2.)

    The body prints no size at all, so the assertion is the number: a Sentry
    woken by a six-mana spell is a 6/6.
    """
    game, sentry, _ = _g3_board(set_pool, "Veiled Sentry")

    _g3_cast(game, "Shivan Dragon")

    assert sentry.is_creature and sentry.has_type("illusion")
    assert (sentry.effective_power, sentry.effective_toughness) == (6, 6)


def test_veiled_apparition_is_granted_its_quoted_upkeep_ability(set_pool):
    """"…a 3/3 Illusion creature with flying **and "At the beginning of your
    upkeep, sacrifice this creature unless you pay {1}{U}."**"

    The quoted sentence is half of what the permanent becomes, so it is
    asserted as an *ability the permanent now has* rather than as text: the
    grant goes on the layer-6 line channel and `effective_card` folds it back
    in, which is what makes the compiler produce the upkeep trigger.
    """
    game, apparition, _ = _g3_board(set_pool, "Veiled Apparition")

    _g3_cast(game, "Lightning Bolt")

    assert apparition.is_creature and apparition.has_keyword("flying")
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(apparition.effective_card)
    assert any(
        trig.condition.kind == "upkeep_self"
        for trig in program.triggered_abilities
    ), "the quoted upkeep trigger is an ability the permanent has"


def test_veiled_serpent_is_granted_its_quoted_combat_restriction(set_pool):
    """The same grant with the quote taking the whole `with` clause rather than
    trailing a keyword — "…a 4/4 Serpent creature with "This creature can't
    attack unless defending player controls an Island.""

    Asserted through the restriction table rather than through the text,
    because that table is what the declare-attackers step actually asks.
    """
    game, serpent, _ = _g3_board(set_pool, "Veiled Serpent")

    _g3_cast(game, "Lightning Bolt")

    assert serpent.is_creature
    assert (serpent.effective_power, serpent.effective_toughness) == (4, 4)
    serpent.metadata["summoning_sickness_turn"] = -99
    assert not game.can_attack(serpent, 1), (
        "the granted restriction is enforced by the declare-attackers step"
    )

    island = Permanent(card=_g3_pool()["Island"])
    game._put_permanent_onto_battlefield(1, island, None)
    assert game.can_attack(serpent, 1)


def test_hidden_predators_wakes_on_a_state_and_not_on_an_event(set_pool):
    """"When an opponent controls a creature with power 4 or greater…"
    (CR 603.8.)

    Nothing is cast and nothing is played — the Predators wake because the
    board *is* a certain way. Both directions are asserted: a 2/2 opposite
    them changes nothing, and a 5/5 wakes them on the next state-based check.
    """
    game, predators, _ = _g3_board(set_pool, "Hidden Predators")
    small = Permanent(card=_g3_pool()["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, small, None)

    game.check_state_based_actions()
    resolve_stack(game)
    assert not predators.is_creature

    big = Permanent(card=_g3_pool()["Force of Nature"])
    game._put_permanent_onto_battlefield(1, big, None)
    game.check_state_based_actions()
    resolve_stack(game)

    assert predators.is_creature
    assert (predators.effective_power, predators.effective_toughness) == (4, 4)


def test_veiled_crocodile_wakes_when_any_hand_is_empty(set_pool):
    """"When a player has no cards in hand…" (CR 603.8.)

    "A player" is every seat, the Crocodile's own controller included, so the
    negative is asserted with *both* hands stocked and the positive with the
    opponent's emptied.
    """
    game, crocodile, bob = _g3_board(set_pool, "Veiled Crocodile")
    game.players[0].hand.append(_g3_pool()["Grizzly Bears"])
    bob.hand.append(_g3_pool()["Grizzly Bears"])

    game.check_state_based_actions()
    resolve_stack(game)
    assert not crocodile.is_creature

    bob.hand.clear()
    game.check_state_based_actions()
    resolve_stack(game)

    assert crocodile.is_creature
    assert (crocodile.effective_power, crocodile.effective_toughness) == (4, 4)


def test_the_cycle_does_not_re_animate_once_it_is_already_a_creature(set_pool):
    """CR 603.4's second check, on the card that shows why it is printed.

    Opal Caryatid wakes on the first creature spell. The second one still
    triggers — it is the same event — but the intervening-if is false by then,
    so nothing happens. The assertion is on the *size*: the Caryatid is first
    given a +3/+3 modifier, which a re-animation would leave in place while
    resetting nothing — so the number is only stable if the second resolution
    really did nothing at all.
    """
    game, caryatid, _ = _g3_board(set_pool, "Opal Caryatid")

    _g3_cast(game, "Grizzly Bears")
    assert caryatid.is_creature
    from engine.pt import add_pt_modifier

    add_pt_modifier(caryatid, 3, 3)
    assert (caryatid.effective_power, caryatid.effective_toughness) == (5, 5)

    _g3_cast(game, "Hill Giant")

    assert (caryatid.effective_power, caryatid.effective_toughness) == (5, 5), (
        "the second trigger's intervening-if is false, so it does nothing"
    )

# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import BATTLEFIELD, HAND
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The seven Runes of Protection plus Sicken and Power Taint. The Runes are the
#: shape worth naming: each prints a real activated ability *and* cycling, so
#: after the rewrite the compiled order is [{W} prevention, cycling] and the
#: battlefield list must be the first alone. All seven reported supported
#: before the rewrite with the keyword unclaimed; Sicken and Power Taint were
#: refused, because an Aura is gated on every effect line being claimed and
#: "cycling {2}" was not one the Aura reader knew.
_G1_RUNES = (
    "Rune of Protection: Artifacts",
    "Rune of Protection: Black",
    "Rune of Protection: Blue",
    "Rune of Protection: Green",
    "Rune of Protection: Lands",
    "Rune of Protection: Red",
    "Rune of Protection: White",
)


def _g1_ench_game(card, *, library=4):
    """Seat 0 holds *card*; the library is copies of it. Distinct to this block."""
    holder = PlayerState(name="G1-E", hand=[card], library=[card] * library)
    duel = Game(players=[holder, PlayerState(name="G1-F")])
    duel.enforce_mana_costs = False
    return duel, holder


@pytest.mark.parametrize("name", _G1_RUNES)
def test_w1g1_a_rune_of_protection_keeps_its_own_ability_and_gains_cycling(
    set_pool, name
):
    """Two abilities, two zones, and the index has to be right in both.

    ``usable_activated_abilities`` is what the web layer and the AI number an
    ability by. If cycling were left in a Rune's battlefield list the prevention
    ability would still be index 0 — but the second entry would be an ability
    the engine refuses, and the {2} the client collected for it would be spent
    on nothing.
    """
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason

    battlefield = usable_activated_abilities(program)
    assert len(battlefield) == 1
    assert battlefield[0].source_line.startswith("{W}: The next time")
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    duel, holder = _g1_ench_game(card)
    assert duel.activate_from_hand(0, name).supported
    resolve_stack(duel)
    assert [c.name for c in holder.graveyard] == [name]
    assert len(holder.library) == 3


@pytest.mark.parametrize("name", ("Sicken", "Power Taint"))
def test_w1g1_a_cycling_aura_is_supported_and_cycles(set_pool, name):
    """An Aura is unsupported unless every effect line is claimed
    (``engine/auras.py``), and "cycling {2}" was refused there — so these two
    were unsupported for a keyword rather than for their Aura text. The rewrite
    turns the line into an activated ability before the Aura gate reads it."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    duel, holder = _g1_ench_game(card)
    assert duel.activate_from_hand(0, name).supported
    resolve_stack(duel)
    assert [c.name for c in holder.graveyard] == [name]
    assert len(holder.library) == 3


def test_w1g1_veiled_serpent_is_whole_once_both_halves_land(set_pool):
    """Half a card, said out loud — and then the other half arrived.

    Veiled Serpent's cycling line is W1G1's and its "becomes a 4/4 Serpent
    creature with …" trigger is W1G3's. W1G1 wrote this test asserting the
    *opposite* of what it asserts now: that the card reported `supported` off
    its cycling line alone while the trigger it is famous for was still
    unimplemented. A card is supported when **any** of its lines is, so nothing
    else in the repo would have said so.

    It was written to fail the day the other half landed, and at the wave-1
    integration it did — which is the tripwire working rather than a
    regression, and the reason the claim is now the whole card. Keep both
    assertions: the cycling ability is offered **only from a hand** (CR 702.29a)
    and the trigger lowers, so neither group's half can quietly rot without
    this failing.
    """
    program = compile_card_oracle(set_pool("USG")["Veiled Serpent"])
    assert program.supported
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]
    assert not usable_activated_abilities(program, zone=BATTLEFIELD)
    assert program.triggered_abilities
    assert all(trig.supported for trig in program.triggered_abilities)
    assert [t.instruction.kind for t in program.triggered_abilities] == [
        "animate_self_indefinitely"
    ]
